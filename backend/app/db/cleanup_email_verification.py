"""Bounded cleanup for historical email-verification challenges."""

import asyncio
from datetime import timedelta

from sqlalchemy import delete, or_, select

from app.core.utils import utcnow
from app.db.models import EmailVerificationChallenge
from app.db.session import SessionLocal


BATCH_SIZE = 500
RETENTION_DAYS = 7


async def cleanup() -> int:
    total = 0
    cutoff = utcnow() - timedelta(days=RETENTION_DAYS)
    while True:
        async with SessionLocal() as db:
            stale_ids = list(
                (
                    await db.execute(
                        select(EmailVerificationChallenge.id)
                        .where(
                            EmailVerificationChallenge.created_at < cutoff,
                            or_(
                                EmailVerificationChallenge.expires_at < utcnow(),
                                EmailVerificationChallenge.consumed_at.is_not(None),
                                EmailVerificationChallenge.revoked_at.is_not(None),
                            ),
                        )
                        .order_by(EmailVerificationChallenge.created_at.asc())
                        .limit(BATCH_SIZE)
                    )
                ).scalars()
            )
            if not stale_ids:
                return total
            result = await db.execute(
                delete(EmailVerificationChallenge).where(EmailVerificationChallenge.id.in_(stale_ids))
            )
            await db.commit()
            total += int(result.rowcount or 0)


async def _main() -> None:
    removed = await cleanup()
    print(f"Removed {removed} historical email-verification challenges.")


if __name__ == "__main__":
    asyncio.run(_main())
