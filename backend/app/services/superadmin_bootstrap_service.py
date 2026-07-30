from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identifiers import normalize_username, validate_username
from app.core.security import hash_password
from app.db.models import User
from app.services.event_service import log_event


class SuperadminBootstrapService:
    @staticmethod
    async def ensure(
        db: AsyncSession,
        *,
        username: str,
        password: str,
        email: str | None = None,
    ) -> tuple[User, bool]:
        normalized_username = normalize_username(validate_username(username))
        # The bootstrap path is powerful and usually configured by environment,
        # so require a stronger password before creating the first admin.
        if len(password) < 12:
            raise RuntimeError("SUPERADMIN_PASSWORD must contain at least 12 characters")
        normalized_email = email.strip().lower() if email and email.strip() else None

        existing = (await db.execute(select(User).where(User.username == normalized_username))).scalar_one_or_none()
        if existing:
            # Avoid silently upgrading a normal account from configuration; that
            # would be surprising and hard to defend in the audit log.
            if not existing.is_superadmin:
                raise RuntimeError(
                    "refusing to auto-promote an existing normal user; choose a new SUPERADMIN_USERNAME"
                )
            return existing, False

        if normalized_email:
            # Email uniqueness is checked explicitly to fail with a clear setup
            # error instead of an opaque database integrity exception.
            email_owner = (
                await db.execute(select(User.id).where(func.lower(User.email) == normalized_email))
            ).scalar_one_or_none()
            if email_owner is not None:
                raise RuntimeError("SUPERADMIN_EMAIL already belongs to another account")

        user = User(
            username=normalized_username,
            email=normalized_email,
            password_hash=hash_password(password),
            is_superadmin=True,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        await log_event(
            db,
            "superadmin.bootstrapped",
            {"user_id": str(user.id), "username": user.username},
            actor_user_id=user.id,
        )
        await db.commit()
        await db.refresh(user)
        return user, True
