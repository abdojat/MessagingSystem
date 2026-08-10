import asyncio
import heapq
import math
import time
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException
from redis.asyncio import Redis

from app.core.config import get_settings


FailurePolicy = Literal["local", "allow"]


_REDIS_FIXED_WINDOW_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if count == 1 or ttl < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
    ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


@dataclass(frozen=True)
class RateLimitResult:
    retry_after_seconds: int | None
    backend: Literal["redis", "local", "bypassed"]


class RateLimitService:
    """Redis limiter with a bounded per-process emergency fallback.

    The local fallback intentionally has a capped key set so an outage cannot
    turn attacker-controlled identities into an in-process memory exhaustion
    vector. It is not a replacement for distributed Redis enforcement, but it
    keeps sensitive endpoints bounded on every API instance during an outage.
    """

    # key -> (window expiry, count). Expiry heap entries are created only when
    # a new fixed window is admitted, so both structures remain bounded by the
    # configured key cardinality.
    _local_windows: dict[str, tuple[float, int]] = {}
    _local_expiries: list[tuple[float, str]] = []
    _local_lock = asyncio.Lock()

    @classmethod
    async def hit(
        cls,
        redis: Redis,
        key: str,
        limit: int,
        window_seconds: int,
        *,
        failure_policy: FailurePolicy = "local",
    ) -> RateLimitResult:
        try:
            result = await redis.eval(_REDIS_FIXED_WINDOW_SCRIPT, 1, key, window_seconds)
            count, ttl = int(result[0]), int(result[1])
            if count > limit:
                return RateLimitResult(int(ttl if ttl > 0 else 1), "redis")
            return RateLimitResult(None, "redis")
        except Exception:
            if failure_policy == "allow":
                return RateLimitResult(None, "bypassed")
            return await cls._hit_local(key, limit, window_seconds)

    @classmethod
    async def _hit_local(cls, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.monotonic()
        async with cls._local_lock:
            cls._purge_expired_local_windows(now)
            current = cls._local_windows.get(key)
            if current is None:
                max_keys = get_settings().rate_limit_local_max_keys
                if len(cls._local_windows) >= max_keys:
                    # Sensitive fallback saturation denies previously unseen
                    # identities instead of evicting established security state.
                    next_expiry = cls._local_expiries[0][0] if cls._local_expiries else now + window_seconds
                    return RateLimitResult(max(1, math.ceil(next_expiry - now)), "local")
                expires_at = now + window_seconds
                count = 0
                cls._local_windows[key] = (expires_at, count)
                heapq.heappush(cls._local_expiries, (expires_at, key))
            else:
                expires_at, count = current
            count += 1
            cls._local_windows[key] = (expires_at, count)
            retry_after = max(1, math.ceil(expires_at - now)) if count > limit else None
            return RateLimitResult(retry_after, "local")

    @classmethod
    def _purge_expired_local_windows(cls, now: float) -> None:
        while cls._local_expiries and cls._local_expiries[0][0] <= now:
            expires_at, key = heapq.heappop(cls._local_expiries)
            current = cls._local_windows.get(key)
            if current is not None and current[0] == expires_at:
                cls._local_windows.pop(key, None)

    @classmethod
    def reset_local_for_tests(cls) -> None:
        cls._local_windows.clear()
        cls._local_expiries.clear()


async def enforce_rate_limit(
    redis: Redis,
    key: str,
    *,
    limit: int,
    window_seconds: int,
    failure_policy: FailurePolicy = "local",
) -> None:
    result = await RateLimitService.hit(
        redis,
        key,
        limit,
        window_seconds,
        failure_policy=failure_policy,
    )
    if result.retry_after_seconds is None:
        return
    retry_after = result.retry_after_seconds
    raise HTTPException(
        status_code=429,
        detail={
            "code": "RATE_LIMITED",
            "message": "rate limit exceeded",
            "details": {"retry_after_seconds": retry_after},
        },
        headers={"Retry-After": str(retry_after)},
    )
