from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.core.utils import sha256_hex, utcnow
from app.db.models import User, UserSession
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair


class AuthService:
    @staticmethod
    async def register(db: AsyncSession, req: RegisterRequest) -> User:
        username = req.username.strip()
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
    async def login(db: AsyncSession, req: LoginRequest, user_agent: str | None, ip: str | None, refresh_ttl_days: int) -> TokenPair:
        result = await db.execute(
            select(User).where(or_(User.username == req.username_or_email, User.email == req.username_or_email))
        )
        user = result.scalar_one_or_none()
        if not user or not verify_password(req.password, user.password_hash):
            raise AppError("invalid credentials", 401, code="AUTH_INVALID")

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

    @staticmethod
    async def refresh(db: AsyncSession, refresh_token: str, user_agent: str | None, ip: str | None, refresh_ttl_days: int) -> TokenPair:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise AppError("invalid token type", 401, code="AUTH_EXPIRED")
        sid = payload.get("sid")
        sub = payload.get("sub")
        if not sid or not sub:
            raise AppError("invalid token payload", 401, code="AUTH_EXPIRED")

        session = await db.get(UserSession, UUID(sid))
        if not session or session.user_id != UUID(sub):
            raise AppError("invalid session", 401, code="AUTH_INVALID")
        if session.revoked_at is not None or session.expires_at < utcnow():
            raise AppError("session expired or revoked", 401, code="AUTH_EXPIRED")
        if session.refresh_token_hash != sha256_hex(refresh_token):
            raise AppError("refresh token mismatch", 401, code="AUTH_INVALID")

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

    @staticmethod
    async def logout(db: AsyncSession, refresh_token: str) -> None:
        payload = decode_token(refresh_token)
        sid = payload.get("sid")
        if not sid:
            raise AppError("invalid token payload", 401, code="AUTH_INVALID")
        session = await db.get(UserSession, UUID(sid))
        if session and session.revoked_at is None:
            session.revoked_at = utcnow()
            await db.commit()

    @staticmethod
    async def get_user_from_access_token(db: AsyncSession, token: str) -> User:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise AppError("invalid access token", 401, code="AUTH_INVALID")
        user_id = payload.get("sub")
        if not user_id:
            raise AppError("invalid access token payload", 401, code="AUTH_INVALID")
        user = await db.get(User, UUID(user_id))
        if not user:
            raise AppError("user not found", 404)
        return user

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

    @staticmethod
    async def revoke_session(db: AsyncSession, user_id: UUID, session_id: UUID) -> None:
        session = await db.get(UserSession, session_id)
        if not session or session.user_id != user_id:
            raise AppError("session not found", 404)
        if session.revoked_at is None:
            session.revoked_at = utcnow()
            await db.commit()

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
