import logging
import math
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.identifiers import normalize_username
from app.realtime.redis_pubsub import online_users_key

logger = logging.getLogger(__name__)


class PresenceTransition(str, Enum):
    online = "online"
    offline = "offline"
    none = "none"
    unknown = "unknown"


@dataclass(frozen=True)
class PresenceReapResult:
    offline_usernames: tuple[str, ...]
    available: bool = True


_REGISTER_OR_REFRESH_SCRIPT = r"""
local expired = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[4])
for _, connection_id in ipairs(expired) do
    redis.call('ZREM', KEYS[2], ARGV[1] .. ':' .. connection_id)
end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[4])
local before = redis.call('ZCARD', KEYS[1])
redis.call('ZADD', KEYS[1], ARGV[5], ARGV[2])
redis.call('ZADD', KEYS[2], ARGV[5], ARGV[1] .. ':' .. ARGV[2])
redis.call('HSET', KEYS[3], ARGV[1], ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[6])
redis.call('SADD', KEYS[4], ARGV[3])
if before == 0 then
    return 1
end
return 0
"""


_DISCONNECT_SCRIPT = r"""
local expired = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[4])
for _, connection_id in ipairs(expired) do
    redis.call('ZREM', KEYS[2], ARGV[1] .. ':' .. connection_id)
end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[4])
local before = redis.call('ZCARD', KEYS[1])
redis.call('ZREM', KEYS[1], ARGV[2])
redis.call('ZREM', KEYS[2], ARGV[1] .. ':' .. ARGV[2])
local remaining = redis.call('ZCARD', KEYS[1])
if remaining == 0 then
    redis.call('DEL', KEYS[1])
    redis.call('HDEL', KEYS[3], ARGV[1])
    redis.call('SREM', KEYS[4], ARGV[3])
    if before > 0 then
        return -1
    end
end
return 0
"""


_REAP_SCRIPT = r"""
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[2], 'LIMIT', 0, ARGV[3])
local offline = {}
for _, member in ipairs(due) do
    local separator = string.find(member, ':', 1, true)
    if separator then
        local user_id = string.sub(member, 1, separator - 1)
        local connection_id = string.sub(member, separator + 1)
        local current_index_score = redis.call('ZSCORE', KEYS[1], member)
        if current_index_score and tonumber(current_index_score) <= tonumber(ARGV[2]) then
            redis.call('ZREM', KEYS[1], member)
            local user_key = ARGV[1] .. user_id
            local current_user_score = redis.call('ZSCORE', user_key, connection_id)
            if current_user_score and tonumber(current_user_score) <= tonumber(ARGV[2]) then
                redis.call('ZREM', user_key, connection_id)
            end
            redis.call('ZREMRANGEBYSCORE', user_key, '-inf', ARGV[2])
            if redis.call('ZCARD', user_key) == 0 then
                redis.call('DEL', user_key)
                local username = redis.call('HGET', KEYS[2], user_id)
                redis.call('HDEL', KEYS[2], user_id)
                if username and redis.call('SREM', KEYS[3], username) == 1 then
                    table.insert(offline, username)
                end
            end
        end
    else
        redis.call('ZREM', KEYS[1], member)
    end
end
return offline
"""


class PresenceService:
    """Distributed, lease-based aggregate presence stored atomically in Redis."""

    def __init__(
        self,
        redis: Redis | None,
        *,
        namespace: str = "presence",
        online_key: str | None = None,
        lease_seconds: int | None = None,
        reaper_batch_size: int | None = None,
    ) -> None:
        settings = get_settings()
        self._redis = redis
        self._namespace = namespace.rstrip(":")
        self._online_key = online_key or online_users_key()
        self._lease_seconds = lease_seconds or settings.presence_lease_seconds
        self._reaper_batch_size = reaper_batch_size or settings.presence_reaper_batch_size
        self._last_failure_log_at = 0.0

    @staticmethod
    def new_connection_id() -> str:
        return secrets.token_urlsafe(24)

    def user_key(self, user_id: UUID | str) -> str:
        return f"{self._namespace}:user:{user_id}"

    @property
    def expiration_index_key(self) -> str:
        return f"{self._namespace}:expirations"

    @property
    def usernames_key(self) -> str:
        return f"{self._namespace}:usernames"

    async def register(
        self,
        user_id: UUID,
        username: str,
        connection_id: str,
        *,
        now_epoch: float | None = None,
    ) -> PresenceTransition:
        return await self._register_or_refresh(user_id, username, connection_id, now_epoch=now_epoch)

    async def refresh(
        self,
        user_id: UUID,
        username: str,
        connection_id: str,
        *,
        now_epoch: float | None = None,
    ) -> PresenceTransition:
        return await self._register_or_refresh(user_id, username, connection_id, now_epoch=now_epoch)

    async def disconnect(
        self,
        user_id: UUID,
        username: str,
        connection_id: str,
        *,
        now_epoch: float | None = None,
    ) -> PresenceTransition:
        if self._redis is None:
            return PresenceTransition.unknown
        now = now_epoch if now_epoch is not None else time.time()
        try:
            result = await self._redis.eval(
                _DISCONNECT_SCRIPT,
                4,
                self.user_key(user_id),
                self.expiration_index_key,
                self.usernames_key,
                self._online_key,
                str(user_id),
                connection_id,
                normalize_username(username),
                now,
            )
            return PresenceTransition.offline if int(result) == -1 else PresenceTransition.none
        except Exception:
            self._log_redis_failure("disconnect")
            # Never infer a global offline transition from local state when the
            # distributed source cannot be checked.
            return PresenceTransition.unknown

    async def reap_expired(self, *, now_epoch: float | None = None) -> PresenceReapResult:
        if self._redis is None:
            return PresenceReapResult((), available=False)
        now = now_epoch if now_epoch is not None else time.time()
        try:
            result = await self._redis.eval(
                _REAP_SCRIPT,
                3,
                self.expiration_index_key,
                self.usernames_key,
                self._online_key,
                f"{self._namespace}:user:",
                now,
                self._reaper_batch_size,
            )
            usernames = tuple(
                item.decode("utf-8") if isinstance(item, bytes) else str(item)
                for item in result
            )
            return PresenceReapResult(usernames)
        except Exception:
            self._log_redis_failure("reaper")
            return PresenceReapResult((), available=False)

    async def _register_or_refresh(
        self,
        user_id: UUID,
        username: str,
        connection_id: str,
        *,
        now_epoch: float | None,
    ) -> PresenceTransition:
        if self._redis is None:
            return PresenceTransition.unknown
        now = now_epoch if now_epoch is not None else time.time()
        expires_at = now + self._lease_seconds
        key_ttl = max(self._lease_seconds + 1, math.ceil(self._lease_seconds * 2))
        try:
            result = await self._redis.eval(
                _REGISTER_OR_REFRESH_SCRIPT,
                4,
                self.user_key(user_id),
                self.expiration_index_key,
                self.usernames_key,
                self._online_key,
                str(user_id),
                connection_id,
                normalize_username(username),
                now,
                expires_at,
                key_ttl,
            )
            return PresenceTransition.online if int(result) == 1 else PresenceTransition.none
        except Exception:
            self._log_redis_failure("register/heartbeat")
            return PresenceTransition.unknown

    def _log_redis_failure(self, operation: str) -> None:
        now = time.monotonic()
        if now - self._last_failure_log_at >= 30:
            logger.warning("distributed presence Redis operation unavailable", extra={"operation": operation})
            self._last_failure_log_at = now
