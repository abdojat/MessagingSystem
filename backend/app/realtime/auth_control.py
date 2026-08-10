import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.services.auth_service import SessionRevocation, UserRevocation

if TYPE_CHECKING:
    from app.realtime.ws_manager import WSManager

logger = logging.getLogger(__name__)


def auth_control_channel() -> str:
    return "rt.auth_control"


@dataclass(frozen=True)
class AuthControlEvent:
    user_id: UUID
    reason: str
    session_id: UUID | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": "auth.session_revoked",
                "user_id": str(self.user_id),
                "session_id": str(self.session_id) if self.session_id else None,
                "reason": self.reason,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "AuthControlEvent":
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        if payload.get("type") != "auth.session_revoked":
            raise ValueError("unsupported auth control event")
        user_id = UUID(str(payload["user_id"]))
        session_raw = payload.get("session_id")
        session_id = UUID(str(session_raw)) if session_raw else None
        reason = str(payload.get("reason") or "session revoked")[:123]
        return cls(user_id=user_id, session_id=session_id, reason=reason)

    @classmethod
    def for_session(cls, revocation: SessionRevocation) -> "AuthControlEvent":
        return cls(
            user_id=revocation.user_id,
            session_id=revocation.session_id,
            reason=revocation.reason,
        )

    @classmethod
    def for_user(cls, revocation: UserRevocation) -> "AuthControlEvent":
        return cls(user_id=revocation.user_id, reason=revocation.reason)


async def dispatch_auth_control(redis: Redis, manager: "WSManager", event: AuthControlEvent) -> bool:
    # Local dispatch provides immediate behavior even when Redis is down. The
    # durable database revocation remains authoritative for future requests and
    # handshakes; Redis only accelerates cross-instance socket closure.
    await manager.handle_auth_control_event(event)
    try:
        await redis.publish(auth_control_channel(), event.to_json())
        return True
    except RedisError:
        logger.warning(
            "could not publish auth control event; database revocation remains authoritative",
            extra={"user_id": str(event.user_id), "session_id": str(event.session_id) if event.session_id else None},
        )
        return False
