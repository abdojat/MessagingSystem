import asyncio
import json
import logging
from datetime import timedelta

import aio_pika
from sqlalchemy import text

from worker_app.core.config import get_settings
from worker_app.db.session import SessionLocal
from worker_app.mq.topology import EXCHANGE_NAME

logger = logging.getLogger(__name__)


async def run_outbox_publisher(amqp: aio_pika.RobustConnection) -> None:
    settings = get_settings()
    channel = await amqp.channel(publisher_confirms=True)
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)

    while True:
        try:
            async with SessionLocal() as db:
                rows = await db.execute(
                    text(
                        """
                        SELECT id, payload, routing_key, attempts
                        FROM outbox
                        WHERE (status = 'pending' OR status = 'failed')
                          AND (next_retry_at IS NULL OR next_retry_at <= now())
                        ORDER BY created_at ASC
                        LIMIT 100
                        FOR UPDATE SKIP LOCKED
                        """
                    )
                )
                records = rows.mappings().all()
                if not records:
                    await db.rollback()
                    await asyncio.sleep(settings.outbox_poll_interval)
                    continue

                for rec in records:
                    outbox_id = rec["id"]
                    attempts = int(rec["attempts"])
                    payload = rec["payload"]
                    if not isinstance(payload, str):
                        payload = json.dumps(payload)
                    try:
                        await exchange.publish(
                            aio_pika.Message(
                                body=payload.encode("utf-8"),
                                content_type="application/json",
                                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            ),
                            routing_key=rec["routing_key"],
                        )
                        await db.execute(
                            text(
                                """
                                UPDATE outbox
                                SET status='sent', sent_at=now(), published_at=now(), last_error=NULL
                                WHERE id = :id
                                """
                            ),
                            {"id": outbox_id},
                        )
                    except Exception as exc:
                        delay = min(300, 2 ** min(attempts + 1, 8))
                        await db.execute(
                            text(
                                """
                                UPDATE outbox
                                SET status='failed',
                                    attempts = attempts + 1,
                                    last_error = :err,
                                    next_retry_at = now() + make_interval(secs => :delay)
                                WHERE id = :id
                                """
                            ),
                            {"id": outbox_id, "err": str(exc)[:1000], "delay": delay},
                        )
                await db.commit()
        except Exception:
            logger.exception("outbox loop failed")
            await asyncio.sleep(settings.outbox_poll_interval)
