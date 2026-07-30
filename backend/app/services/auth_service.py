from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.identifiers import normalize_username
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.core.utils import sha256_hex, utcnow
from app.db.models import User, UserSession
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair


# Groups the auth business operations; API route handlers call it to enforce application business rules.
class AuthService:
    # Registers a new user account; API route handlers call it to enforce application business rules.
    @staticmethod
    async def register(db: AsyncSession, req: RegisterRequest) -> User:
        username = normalize_username(req.username)
        email = req.email.strip().lower() if req.email is not None else None

        existing_username = await db.execute(select(User.id).where(User.username == username))
        # Reject the operation when `existing_username.scalar_one_or_none() is not None` to keep invalid state from progressing.
        if existing_username.scalar_one_or_none() is not None:
            raise AppError(
                "username already exists",
                409,
                code="CONFLICT",
                details={"field": "username"},
            )

        # Run this conditional step only when `email is not None` is true.
        if email is not None:
            existing_email = await db.execute(select(User.id).where(func.lower(User.email) == email))
            # Reject the operation when `existing_email.scalar_one_or_none() is not None` to keep invalid state from progressing.
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

    # Authenticates credentials and creates a user session; API route handlers call it to enforce application business rules.
    @staticmethod
    async def login(db: AsyncSession, req: LoginRequest, user_agent: str | None, ip: str | None, refresh_ttl_days: int) -> TokenPair:
        identity = req.username_or_email.strip()
        normalized_identity = identity.lower()
        result = await db.execute(
            select(User).where(or_(User.username == identity, func.lower(User.email) == normalized_identity))
        )
        user = result.scalar_one_or_none()
        # Reject the operation when `not user or not verify_password(req.password, user.password_hash)` to keep invalid state from progressing.
        if not user or not verify_password(req.password, user.password_hash):
            raise AppError("invalid credentials", 401, code="AUTH_INVALID")
        # Reject the operation when `not user.is_active` to keep invalid state from progressing.
        if not user.is_active:
            raise AppError("account is deactivated", 403, code="ACCOUNT_DISABLED")

        session = UserSession(
            user_id=user.id,
            refresh_token_hash="",
            user_agent=user_agent,
            ip=ip,
            last_used_at=utcnow(),
            expires_at=utcnow() + timedelta(days=refresh_ttl_days),
        )
        db.add(session)
        await db.flush()

        refresh = create_refresh_token(user.id, session.id)
        session.refresh_token_hash = sha256_hex(refresh)
        access = create_access_token(user.id)
        await db.commit()
        return TokenPair(access_token=access, refresh_token=refresh)

    # Rotates the refresh credential and issues a new token pair; API route handlers call it to enforce application business rules.
    @staticmethod
    async def refresh(db: AsyncSession, refresh_token: str, user_agent: str | None, ip: str | None, refresh_ttl_days: int) -> TokenPair:
        session = await AuthService._get_valid_refresh_session(db, refresh_token)
        user = await db.get(User, session.user_id)
        # Run this conditional step only when `not user or not user.is_active` is true.
        if not user or not user.is_active:
            session.revoked_at = utcnow()
            await db.commit()
            raise AppError("account is deactivated", 403, code="ACCOUNT_DISABLED")

        now = utcnow()
        session.last_used_at = now
        session.expires_at = now + timedelta(days=refresh_ttl_days)
        session.user_agent = user_agent
        session.ip = ip
        new_refresh = create_refresh_token(session.user_id, session.id)
        session.refresh_token_hash = sha256_hex(new_refresh)
        new_access = create_access_token(session.user_id)
        await db.commit()
        return TokenPair(access_token=new_access, refresh_token=new_refresh)

    # Revokes the current user session; API route handlers call it to enforce application business rules.
    @staticmethod
    async def logout(db: AsyncSession, refresh_token: str) -> None:
        session = await AuthService._get_valid_refresh_session(db, refresh_token)
        # Run this conditional step only when `session.revoked_at is None` is true.
        if session.revoked_at is None:
            session.revoked_at = utcnow()
            await db.commit()

    # Retrieves user from access token; API route handlers call it to enforce application business rules.
    @staticmethod
    async def get_user_from_access_token(db: AsyncSession, token: str) -> User:
        payload = decode_token(token)
        # Reject the operation when `payload.get('type') != 'access'` to keep invalid state from progressing.
        if payload.get("type") != "access":
            raise AppError("invalid access token", 401, code="AUTH_INVALID")
        user_id = payload.get("sub")
        # Reject the operation when `not user_id` to keep invalid state from progressing.
        if not user_id:
            raise AppError("invalid access token payload", 401, code="AUTH_INVALID")
        user = await db.get(User, UUID(user_id))
        # Reject the operation when `not user` to keep invalid state from progressing.
        if not user:
            raise AppError("user not found", 404)
        # Reject the operation when `not user.is_active` to keep invalid state from progressing.
        if not user.is_active:
            raise AppError("account is deactivated", 403, code="ACCOUNT_DISABLED")
        return user

    # Lists sessions; API route handlers call it to enforce application business rules.
    @staticmethod
    async def list_sessions(db: AsyncSession, user_id: UUID) -> list[UserSession]:
        rows = await db.execute(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > utcnow(),
            )
            .order_by(UserSession.created_at.desc())
        )
        return list(rows.scalars().all())

    # Revokes session; API route handlers call it to enforce application business rules.
    @staticmethod
    async def revoke_session(db: AsyncSession, user_id: UUID, session_id: UUID) -> None:
        session = await db.get(UserSession, session_id)
        # Reject the operation when `not session or session.user_id != user_id` to keep invalid state from progressing.
        if not session or session.user_id != user_id:
            raise AppError("session not found", 404)
        # Run this conditional step only when `session.revoked_at is None` is true.
        if session.revoked_at is None:
            session.revoked_at = utcnow()
            await db.commit()

    # Revokes all active sessions for a user; API route handlers call it to enforce application business rules.
    @staticmethod
    async def logout_all(db: AsyncSession, user_id: UUID) -> int:
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
        return int(result.rowcount or 0)

    # Retrieves valid refresh session; API route handlers call it to enforce application business rules.
    @staticmethod
    async def _get_valid_refresh_session(db: AsyncSession, refresh_token: str) -> UserSession:
        payload = decode_token(refresh_token)
        # Reject the operation when `payload.get('type') != 'refresh'` to keep invalid state from progressing.
        if payload.get("type") != "refresh":
            raise AppError("invalid token type", 401, code="AUTH_EXPIRED")

        sid = payload.get("sid")
        sub = payload.get("sub")
        # Reject the operation when `not sid or not sub` to keep invalid state from progressing.
        if not sid or not sub:
            raise AppError("invalid token payload", 401, code="AUTH_EXPIRED")

        session = await db.get(UserSession, UUID(sid))
        # Reject the operation when `not session or session.user_id != UUID(sub)` to keep invalid state from progressing.
        if not session or session.user_id != UUID(sub):
            raise AppError("invalid session", 401, code="AUTH_INVALID")
        # Reject the operation when `session.revoked_at is not None or session.expires_at < utcnow()` to keep invalid state from progressing.
        if session.revoked_at is not None or session.expires_at < utcnow():
            raise AppError("session expired or revoked", 401, code="AUTH_EXPIRED")
        # Reject the operation when `session.refresh_token_hash != sha256_hex(refresh_token)` to keep invalid state from progressing.
        if session.refresh_token_hash != sha256_hex(refresh_token):
            raise AppError("refresh token mismatch", 401, code="AUTH_INVALID")
        return session
