"""Enqueue a full RabbitMQ binding projection repair from PostgreSQL state."""

import asyncio

from app.db.session import SessionLocal
from app.services.outbox_service import enqueue_all_broker_binding_reconciliation


async def _run() -> None:
    async with SessionLocal() as db:
        count = await enqueue_all_broker_binding_reconciliation(db)
        await db.commit()
    print(f"enqueued {count} broker binding reconciliation row(s)")


if __name__ == "__main__":
    asyncio.run(_run())
