import json
import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.utils import sha256_hex, utcnow
from app.services.auth_service import AccessContext


@dataclass(frozen=True)
class WebSocketTicket:
    value: str
    expires_at: datetime


@dataclass(frozen=True)
class WebSocketTicketClaims:
    user_id: UUID
    session_id: UUID
    authentication_expires_at: datetime


class WebSocketTicketService:
    """Issues opaque, single-use WebSocket credentials backed by Redis."""

    KEY_PREFIX = "auth:ws-ticket:"

    @staticmethod
    async def issue(redis: Redis, auth: AccessContext) -> WebSocketTicket:
        now = utcnow()
        expires_at = min(
            now + timedelta(seconds=get_settings().ws_ticket_ttl_seconds),
            auth.authentication_expires_at,
        )
        remaining = (expires_at - now).total_seconds()
        if remaining <= 0:
            raise AppError("authentication expired", 401, code="AUTH_EXPIRED")

        payload = json.dumps(
            {
                "user_id": str(auth.user.id),
                "session_id": str(auth.session_id),
                "authentication_expires_at": auth.authentication_expires_at.isoformat(),
                "ticket_expires_at": expires_at.isoformat(),
            },
            separators=(",", ":"),
        )
        ttl_seconds = max(1, math.ceil(remaining))
        try:
            # Collision is cryptographically implausible, but NX keeps the
            # one-ticket/one-record invariant explicit.
            for _ in range(3):
                value = secrets.token_urlsafe(32)
                stored = await redis.set(
                    WebSocketTicketService._key(value),
                    payload,
                    ex=ttl_seconds,
                    nx=True,
                )
                if stored:
                    return WebSocketTicket(value=value, expires_at=expires_at)
        except RedisError as exc:
            raise AppError("WebSocket authentication is temporarily unavailable", 503, code="WS_TICKET_UNAVAILABLE") from exc
        raise AppError("could not create WebSocket ticket", 503, code="WS_TICKET_UNAVAILABLE")

    @staticmethod
    async def consume(redis: Redis, value: str) -> WebSocketTicketClaims:
        if not value or len(value) > 256:
            raise AppError("invalid WebSocket ticket", 401, code="WS_TICKET_INVALID")
        try:
            # Redis GETDEL atomically consumes the ticket across every backend
            # instance, so concurrent/repeated handshakes cannot both succeed.
            raw = await redis.getdel(WebSocketTicketService._key(value))
        except RedisError as exc:
            raise AppError("WebSocket authentication is temporarily unavailable", 503, code="WS_TICKET_UNAVAILABLE") from exc
        if raw is None:
            raise AppError("invalid or expired WebSocket ticket", 401, code="WS_TICKET_INVALID")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(raw)
            user_id = UUID(str(payload["user_id"]))
            session_id = UUID(str(payload["session_id"]))
            auth_expires_at = WebSocketTicketService._datetime(payload["authentication_expires_at"])
            ticket_expires_at = WebSocketTicketService._datetime(payload["ticket_expires_at"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AppError("invalid WebSocket ticket", 401, code="WS_TICKET_INVALID") from exc

        now = utcnow()
        if ticket_expires_at <= now or auth_expires_at <= now:
            raise AppError("expired WebSocket ticket", 401, code="WS_TICKET_INVALID")
        return WebSocketTicketClaims(
            user_id=user_id,
            session_id=session_id,
            authentication_expires_at=auth_expires_at,
        )

    @staticmethod
    def _key(value: str) -> str:
        # Redis contains only a hash of the bearer ticket, never its plaintext.
        return f"{WebSocketTicketService.KEY_PREFIX}{sha256_hex(value)}"

    @staticmethod
    def _datetime(value: object) -> datetime:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
