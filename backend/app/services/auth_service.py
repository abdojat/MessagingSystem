import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.identifiers import normalize_username
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.core.utils import sha256_hex, utcnow
from app.db.models import User, UserSession
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair
from app.services.event_service import log_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccessContext:
    user: User
    session_id: UUID
    token_expires_at: datetime
    authentication_expires_at: datetime


@dataclass(frozen=True)
class SessionRevocation:
    user_id: UUID
    session_id: UUID
    reason: str


@dataclass(frozen=True)
class UserRevocation:
    user_id: UUID
    revoked_count: int
    reason: str


class RefreshTokenReplayError(AppError):
    def __init__(self, user_id: UUID, session_id: UUID):
        super().__init__("refresh token replay detected", 401, code="AUTH_REPLAY_DETECTED")
        self.revocation = SessionRevocation(user_id=user_id, session_id=session_id, reason="refresh token replay")


class AuthService:
    """Coordinates account registration, login, token rotation, and session revocation."""

    @staticmethod
    async def register(db: AsyncSession, req: RegisterRequest) -> User:
        username = normalize_username(req.username)
        email = req.email.strip().lower() if req.email is not None else None

        existing_username = await db.execute(select(User.id).where(User.username == username))
        if existing_username.scalar_one_or_none() is not None:
            raise AppError(
                "username already exists",
                409,
                code="CONFLICT",
                details={"field": "username"},
            )

        if email is not None:
            existing_email = await db.execute(select(User.id).where(func.lower(User.email) == email))
            if existing_email.scalar_one_or_none() is not None:
                raise AppError(
                    "email already exists",
                    409,
                    code="CONFLICT",
                    details={"field": "email"},
                )

        user = User(username=username, email=email, password_hash=hash_password(req.password))
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def login(
        db: AsyncSession,
        req: LoginRequest,
        user_agent: str | None,
        ip: str | None,
        refresh_ttl_days: int,
        absolute_ttl_days: int | None = None,
    ) -> TokenPair:
        identity = req.username_or_email.strip()
        normalized_identity = identity.lower()
        result = await db.execute(
            select(User).where(or_(User.username == identity, func.lower(User.email) == normalized_identity))
        )
        user = result.scalar_one_or_none()
        if not user or not verify_password(req.password, user.password_hash):
            raise AppError("invalid credentials", 401, code="AUTH_INVALID")
        if not user.is_active:
            raise AppError("account is deactivated", 403, code="ACCOUNT_DISABLED")

        now = utcnow()
        absolute_days = absolute_ttl_days or get_settings().session_absolute_ttl_days
        absolute_expires_at = now + timedelta(days=absolute_days)
        idle_expires_at = min(now + timedelta(days=refresh_ttl_days), absolute_expires_at)
        session = UserSession(
            user_id=user.id,
            refresh_token_hash="",
            user_agent=user_agent,
            ip=ip,
            last_used_at=now,
            expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
        )
        db.add(session)
        # Flush first so both token types can carry the stable session id.
        await db.flush()

        refresh = create_refresh_token(user.id, session.id, idle_expires_at)
        # Only a hash of the current refresh token is stored. A signed token for
        # this session that no longer matches is treated as family replay.
        session.refresh_token_hash = sha256_hex(refresh)
        access = create_access_token(user.id, session.id, idle_expires_at)
        await db.commit()
        return TokenPair(access_token=access, refresh_token=refresh)

    @staticmethod
    async def refresh(
        db: AsyncSession,
        refresh_token: str,
        user_agent: str | None,
        ip: str | None,
        refresh_ttl_days: int,
    ) -> TokenPair:
        session = await AuthService._get_valid_refresh_session(db, refresh_token, lock=True)
        user = await db.get(User, session.user_id)
        if not user or not user.is_active:
            session.revoked_at = utcnow()
            await db.commit()
            raise AppError("account is deactivated", 403, code="ACCOUNT_DISABLED")

        now = utcnow()
        # Idle lifetime slides on legitimate refresh, but the absolute deadline
        # is immutable and is always the upper bound.
        session.last_used_at = now
        session.expires_at = min(now + timedelta(days=refresh_ttl_days), session.absolute_expires_at)
        session.user_agent = user_agent
        session.ip = ip
        new_refresh = create_refresh_token(session.user_id, session.id, session.expires_at)
        session.refresh_token_hash = sha256_hex(new_refresh)
        new_access = create_access_token(session.user_id, session.id, session.expires_at)
        await db.commit()
        return TokenPair(access_token=new_access, refresh_token=new_refresh)

    @staticmethod
    async def logout(db: AsyncSession, refresh_token: str) -> SessionRevocation:
        session = await AuthService._get_valid_refresh_session(db, refresh_token, lock=True)
        if session.revoked_at is None:
            session.revoked_at = utcnow()
            await db.commit()
        return SessionRevocation(user_id=session.user_id, session_id=session.id, reason="logout")

    @staticmethod
    async def get_access_context(db: AsyncSession, token: str) -> AccessContext:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise AppError("invalid access token", 401, code="AUTH_INVALID")
        user_id = AuthService._uuid_claim(payload, "sub")
        session_id = AuthService._uuid_claim(payload, "sid")
        token_expires_at = AuthService._expiry_claim(payload)
        return await AuthService.get_session_access_context(db, user_id, session_id, token_expires_at)

    @staticmethod
    async def get_session_access_context(
        db: AsyncSession,
        user_id: UUID,
        session_id: UUID,
        token_expires_at: datetime,
    ) -> AccessContext:
        row = (
            await db.execute(
                select(User, UserSession)
                .join(UserSession, UserSession.user_id == User.id)
                .where(User.id == user_id, UserSession.id == session_id)
            )
        ).one_or_none()
        if row is None:
            raise AppError("invalid authentication session", 401, code="AUTH_INVALID")
        user, session = row
        now = utcnow()
        if not user.is_active:
            raise AppError("account is deactivated", 403, code="ACCOUNT_DISABLED")
        AuthService._assert_active_session(session, now)
        if token_expires_at <= now:
            raise AppError("authentication expired", 401, code="AUTH_EXPIRED")
        return AccessContext(
            user=user,
            session_id=session.id,
            token_expires_at=token_expires_at,
            authentication_expires_at=min(token_expires_at, session.expires_at, session.absolute_expires_at),
        )

    @staticmethod
    async def get_user_from_access_token(db: AsyncSession, token: str) -> User:
        return (await AuthService.get_access_context(db, token)).user

    @staticmethod
    async def list_sessions(db: AsyncSession, user_id: UUID) -> list[UserSession]:
        now = utcnow()
        rows = await db.execute(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
                UserSession.absolute_expires_at > now,
            )
            .order_by(UserSession.created_at.desc())
        )
        return list(rows.scalars().all())

    @staticmethod
    async def revoke_session(db: AsyncSession, user_id: UUID, session_id: UUID) -> SessionRevocation:
        session = await db.get(UserSession, session_id)
        if not session or session.user_id != user_id:
            raise AppError("session not found", 404)
        if session.revoked_at is None:
            session.revoked_at = utcnow()
            await db.commit()
        return SessionRevocation(user_id=user_id, session_id=session_id, reason="session revoked")

    @staticmethod
    async def logout_all(db: AsyncSession, user_id: UUID) -> UserRevocation:
        now = utcnow()
        result = await db.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await db.commit()
        return UserRevocation(user_id=user_id, revoked_count=int(result.rowcount or 0), reason="logout all")

    @staticmethod
    async def _get_valid_refresh_session(
        db: AsyncSession,
        refresh_token: str,
        *,
        lock: bool = False,
    ) -> UserSession:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise AppError("invalid token type", 401, code="AUTH_EXPIRED")

        session_id = AuthService._uuid_claim(payload, "sid")
        user_id = AuthService._uuid_claim(payload, "sub")
        stmt = select(UserSession).where(UserSession.id == session_id)
        if lock:
            # Serialize rotations so two uses of the same token cannot both win.
            stmt = stmt.with_for_update()
        session = (await db.execute(stmt)).scalar_one_or_none()
        if not session or session.user_id != user_id:
            raise AppError("invalid session", 401, code="AUTH_INVALID")

        now = utcnow()
        AuthService._assert_active_session(session, now)
        if session.refresh_token_hash != sha256_hex(refresh_token):
            session.revoked_at = now
            session.replay_detected_at = now
            # Durable revocation must not depend on the best-effort audit path.
            await db.commit()
            try:
                await log_event(
                    db,
                    "security.refresh_replay_detected",
                    {"session_id": str(session.id), "user_id": str(session.user_id)},
                    actor_user_id=session.user_id,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "refresh replay was revoked but its audit event could not be stored",
                    extra={"user_id": str(session.user_id), "session_id": str(session.id)},
                )
            raise RefreshTokenReplayError(session.user_id, session.id)
        return session

    @staticmethod
    def _assert_active_session(session: UserSession, now: datetime) -> None:
        if session.revoked_at is not None:
            raise AppError("session revoked", 401, code="AUTH_EXPIRED")
        if session.expires_at <= now:
            raise AppError("session idle lifetime expired", 401, code="AUTH_EXPIRED")
        if session.absolute_expires_at <= now:
            raise AppError("session absolute lifetime expired", 401, code="AUTH_EXPIRED")

    @staticmethod
    def _uuid_claim(payload: dict, name: str) -> UUID:
        raw = payload.get(name)
        if not raw:
            raise AppError("invalid token payload", 401, code="AUTH_INVALID")
        try:
            return UUID(str(raw))
        except (TypeError, ValueError) as exc:
            raise AppError("invalid token payload", 401, code="AUTH_INVALID") from exc

    @staticmethod
    def _expiry_claim(payload: dict) -> datetime:
        raw = payload.get("exp")
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (TypeError, ValueError, OSError) as exc:
            raise AppError("invalid token expiry", 401, code="AUTH_INVALID") from exc
