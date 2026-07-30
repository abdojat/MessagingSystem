import asyncio

import aio_pika
from redis.asyncio import Redis

from worker_app.amqp_consumer_runner import OnlineUserConsumerManager
from worker_app.core.config import get_settings
from worker_app.core.logging import configure_logging
from worker_app.outbox_runner import run_outbox_publisher
from worker_app.mq.topology import ensure_topology


# Runs the module's command-line workflow; the worker runtime uses it for asynchronous broker delivery.
async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)

    amqp = None
    # Process each `_` from `range(30)` to apply this step to the full collection.
    for _ in range(30):
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            amqp = await aio_pika.connect_robust(settings.rabbitmq_url)
            await ensure_topology(amqp)
            break
        # Handle `Exception` here so this workflow can recover or report the failure consistently.
        except Exception:
            await asyncio.sleep(1)
    # Reject the operation when `amqp is None` to keep invalid state from progressing.
    if amqp is None:
        raise RuntimeError("cannot connect to rabbitmq")

    manager = OnlineUserConsumerManager(amqp, redis)

    # Protect this operation so its cleanup step runs even if processing fails.
    try:
        await asyncio.gather(
            run_outbox_publisher(amqp),
            manager.run(),
        )
    # Always run this cleanup path after the guarded operation finishes.
    finally:
        await redis.close()
        await amqp.close()


# Run this conditional step only when `__name__ == '__main__'` is true.
if __name__ == "__main__":
    asyncio.run(main())
