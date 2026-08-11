import asyncio
import logging

import aio_pika
from redis.asyncio import Redis
from sqlalchemy import text

from worker_app.amqp_consumer_runner import OnlineUserConsumerManager
from worker_app.core.config import get_settings
from worker_app.core.logging import configure_logging
from worker_app.db.session import SessionLocal
from worker_app.outbox_runner import run_outbox_publisher
from worker_app.mq.topology import ensure_topology, migrate_legacy_user_queue


logger = logging.getLogger(__name__)


async def reconcile_retained_user_queues(amqp: aio_pika.RobustConnection) -> int:
    """Migrate managed user queues created before bounded arguments existed."""

    async with SessionLocal() as db:
        rows = await db.execute(
            text(
                """
                SELECT DISTINCT u.username
                FROM broker_binding_states AS bs
                JOIN users AS u ON u.id = bs.user_id
                ORDER BY u.username
                """
            )
        )
        usernames = list(rows.scalars().all())

    settings = get_settings()
    migrated = 0
    for username in usernames:
        migrated += int(await migrate_legacy_user_queue(amqp, str(username), settings))
    if migrated:
        logger.warning("migrated %s retained legacy user queue(s) to bounded arguments", migrated)
    return migrated


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)

    amqp: aio_pika.RobustConnection | None = None
    for _ in range(30):
        candidate: aio_pika.RobustConnection | None = None
        try:
            candidate = await aio_pika.connect_robust(settings.rabbitmq_url)
            await ensure_topology(candidate)
            await reconcile_retained_user_queues(candidate)
            amqp = candidate
            break
        except Exception as exc:
            if candidate is not None:
                await candidate.close()
            logger.warning("worker dependency bootstrap failed (%s); retrying", type(exc).__name__)
            await asyncio.sleep(1)
    if amqp is None:
        raise RuntimeError("cannot connect to rabbitmq")

    manager = OnlineUserConsumerManager(amqp, redis)

    try:
        await asyncio.gather(
            run_outbox_publisher(amqp),
            manager.run(),
        )
    finally:
        await redis.close()
        await amqp.close()


if __name__ == "__main__":
    asyncio.run(main())
