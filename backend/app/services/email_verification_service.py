import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.email_identity import normalize_email
from app.core.errors import AppError
from app.core.utils import sha256_hex, utcnow
from app.db.models import EmailVerificationChallenge, User
from app.services.email_delivery_service import VerificationMailer, build_verification_url
from app.services.event_service import log_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationRequestResult:
    status: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class VerificationConfirmationResult:
    status: str
    verified_at: datetime


class EmailVerificationService:
    HISTORY_RETENTION_DAYS = 7
    REQUEST_CLEANUP_LIMIT = 100

    @staticmethod
    async def request_verification(
        db: AsyncSession,
        user_id: UUID,
        mailer: VerificationMailer,
    ) -> VerificationRequestResult:
        settings = get_settings()
        if not settings.email_verification_enabled:
            raise AppError(
                "email verification is unavailable",
                503,
                code="EMAIL_VERIFICATION_UNAVAILABLE",
            )

        user = (
            await db.execute(select(User).where(User.id == user_id).with_for_update())
        ).scalar_one_or_none()
        if user is None:
            raise AppError("user not found", 404, code="NOT_FOUND")
        if user.email is None:
            raise AppError("an email address is required", 400, code="EMAIL_REQUIRED")

        email = normalize_email(user.email)
        if user.email_verified_at is not None:
            await db.rollback()
            return VerificationRequestResult(status="already_verified")

        now = utcnow()
        await EmailVerificationService._cleanup_user_history(db, user_id, now)
        await db.execute(
            update(EmailVerificationChallenge)
            .where(
                EmailVerificationChallenge.user_id == user_id,
                EmailVerificationChallenge.consumed_at.is_(None),
                EmailVerificationChallenge.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

        raw_token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(minutes=settings.email_verification_ttl_minutes)
        challenge = EmailVerificationChallenge(
            user_id=user_id,
            email=email,
            token_hash=sha256_hex(raw_token),
            created_at=now,
            expires_at=expires_at,
        )
        db.add(challenge)
        await log_event(
            db,
            "email.verification_requested",
            {"user_id": str(user_id)},
            actor_user_id=user_id,
        )
        await db.commit()

        verification_url = build_verification_url(settings.email_verification_public_url, raw_token)
        try:
            await mailer.send_verification(email, verification_url)
        except Exception:
            # A failed/ambiguous provider attempt never verifies the account.
            # Revoke this challenge so a subsequent request creates a clean,
            # independently deliverable lifecycle.
            await EmailVerificationService._record_delivery_failure(db, challenge.id, user_id)
            logger.warning("email verification delivery failed", extra={"user_id": str(user_id)})
            raise AppError(
                "verification email could not be delivered",
                503,
                code="EMAIL_DELIVERY_FAILED",
            )

        return VerificationRequestResult(status="sent", expires_at=expires_at)

    @staticmethod
    async def confirm(
        db: AsyncSession,
        user_id: UUID,
        raw_token: str,
    ) -> VerificationConfirmationResult:
        if not get_settings().email_verification_enabled:
            raise AppError(
                "email verification is unavailable",
                503,
                code="EMAIL_VERIFICATION_UNAVAILABLE",
            )

        token_hash = sha256_hex(raw_token)
        challenge_owner_id = await db.scalar(
            select(EmailVerificationChallenge.user_id).where(
                EmailVerificationChallenge.token_hash == token_hash
            )
        )
        if challenge_owner_id is None:
            await EmailVerificationService._raise_confirmation_failure(
                db,
                user_id,
                reason="invalid_token",
                message="invalid email verification token",
                status_code=400,
                code="EMAIL_VERIFICATION_INVALID",
            )
        if challenge_owner_id != user_id:
            await EmailVerificationService._raise_confirmation_failure(
                db,
                user_id,
                reason="user_mismatch",
                message="verification token belongs to another account",
                status_code=403,
                code="EMAIL_VERIFICATION_INVALID",
            )

        # Follow the repository lock order: mutable User first, then its
        # dependent challenge. The unique token row lock serializes concurrent
        # confirmation so only one request can consume it.
        user = (
            await db.execute(select(User).where(User.id == user_id).with_for_update())
        ).scalar_one_or_none()
        challenge = (
            await db.execute(
                select(EmailVerificationChallenge)
                .where(EmailVerificationChallenge.token_hash == token_hash)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if user is None or challenge is None or challenge.user_id != user_id:
            await EmailVerificationService._raise_confirmation_failure(
                db,
                user_id,
                reason="invalid_token",
                message="invalid email verification token",
                status_code=400,
                code="EMAIL_VERIFICATION_INVALID",
            )

        now = utcnow()
        if challenge.consumed_at is not None:
            await EmailVerificationService._raise_confirmation_failure(
                db,
                user_id,
                reason="already_consumed",
                message="email verification token was already used",
                status_code=409,
                code="EMAIL_VERIFICATION_USED",
            )
        if challenge.revoked_at is not None:
            await EmailVerificationService._raise_confirmation_failure(
                db,
                user_id,
                reason="revoked",
                message="email verification token is no longer valid",
                status_code=400,
                code="EMAIL_VERIFICATION_INVALID",
            )
        if challenge.expires_at <= now:
            challenge.revoked_at = now
            await EmailVerificationService._raise_confirmation_failure(
                db,
                user_id,
                reason="expired",
                message="email verification token expired",
                status_code=400,
                code="EMAIL_VERIFICATION_EXPIRED",
            )

        current_email = normalize_email(user.email) if user.email is not None else None
        if current_email != challenge.email:
            challenge.revoked_at = now
            await EmailVerificationService._raise_confirmation_failure(
                db,
                user_id,
                reason="email_changed",
                message="email address changed after this verification was requested",
                status_code=400,
                code="EMAIL_VERIFICATION_INVALID",
            )

        challenge.consumed_at = now
        user.email_verified_at = now
        await db.execute(
            update(EmailVerificationChallenge)
            .where(
                EmailVerificationChallenge.user_id == user_id,
                EmailVerificationChallenge.id != challenge.id,
                EmailVerificationChallenge.consumed_at.is_(None),
                EmailVerificationChallenge.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await log_event(
            db,
            "email.verified",
            {"user_id": str(user_id)},
            actor_user_id=user_id,
        )
        await db.commit()
        return VerificationConfirmationResult(status="verified", verified_at=now)

    @staticmethod
    async def _raise_confirmation_failure(
        db: AsyncSession,
        user_id: UUID,
        *,
        reason: str,
        message: str,
        status_code: int,
        code: str,
    ) -> None:
        try:
            await log_event(
                db,
                "email.verification_failed",
                {"user_id": str(user_id), "reason": reason},
                actor_user_id=user_id,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning(
                "email verification failure audit could not be stored",
                extra={"user_id": str(user_id), "reason": reason},
            )
        raise AppError(message, status_code, code=code)

    @staticmethod
    async def _record_delivery_failure(
        db: AsyncSession,
        challenge_id: UUID,
        user_id: UUID,
    ) -> None:
        challenge = (
            await db.execute(
                select(EmailVerificationChallenge)
                .where(EmailVerificationChallenge.id == challenge_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if challenge is not None and challenge.consumed_at is None and challenge.revoked_at is None:
            challenge.revoked_at = utcnow()
        # Persist revocation before the best-effort audit write so a temporary
        # event-chain failure cannot leave a possibly delivered token active.
        await db.commit()
        try:
            await log_event(
                db,
                "email.verification_failed",
                {"user_id": str(user_id), "reason": "delivery_failed"},
                actor_user_id=user_id,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning(
                "email delivery failure audit could not be stored",
                extra={"user_id": str(user_id)},
            )

    @staticmethod
    async def _cleanup_user_history(db: AsyncSession, user_id: UUID, now: datetime) -> int:
        cutoff = now - timedelta(days=EmailVerificationService.HISTORY_RETENTION_DAYS)
        stale_ids = list(
            (
                await db.execute(
                    select(EmailVerificationChallenge.id)
                    .where(
                        EmailVerificationChallenge.user_id == user_id,
                        EmailVerificationChallenge.created_at < cutoff,
                        or_(
                            EmailVerificationChallenge.expires_at < now,
                            EmailVerificationChallenge.consumed_at.is_not(None),
                            EmailVerificationChallenge.revoked_at.is_not(None),
                        ),
                    )
                    .order_by(EmailVerificationChallenge.created_at.asc())
                    .limit(EmailVerificationService.REQUEST_CLEANUP_LIMIT)
                )
            ).scalars()
        )
        if stale_ids:
            await db.execute(
                delete(EmailVerificationChallenge).where(EmailVerificationChallenge.id.in_(stale_ids))
            )
        return len(stale_ids)
