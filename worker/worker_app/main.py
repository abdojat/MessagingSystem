import asyncio

import aio_pika
from redis.asyncio import Redis

from worker_app.amqp_consumer_runner import OnlineUserConsumerManager
from worker_app.core.config import get_settings
from worker_app.core.logging import configure_logging
from worker_app.outbox_runner import run_outbox_publisher
from worker_app.mq.topology import ensure_topology


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)

    amqp = None
    for _ in range(30):
        try:
            amqp = await aio_pika.connect_robust(settings.rabbitmq_url)
            await ensure_topology(amqp)
            break
        except Exception:
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
