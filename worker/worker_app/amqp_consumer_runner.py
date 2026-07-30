import asyncio
import logging

import aio_pika
from redis.asyncio import Redis

from worker_app.core.config import get_settings
from worker_app.redis_fanout import online_users_key, user_pubsub_channel, user_queue_name

logger = logging.getLogger(__name__)


# Defines the online user consumer manager project abstraction; the worker runtime uses it for asynchronous broker delivery.
class OnlineUserConsumerManager:
    # Initializes a online user consumer manager; the worker runtime uses it for asynchronous broker delivery.
    def __init__(self, amqp: aio_pika.RobustConnection, redis: Redis):
        self.amqp = amqp
        self.redis = redis
        self.settings = get_settings()
        self.tasks: dict[str, asyncio.Task] = {}

    # Runs; the worker runtime uses it for asynchronous broker delivery.
    async def run(self) -> None:
        # Keep reconciling online-user consumers for the lifetime of the worker.
        while True:
            # Attempt this operation and handle expected failures in the exception branches below.
            try:
                online = await self.redis.smembers(online_users_key())
                online_users = {u.decode("utf-8") if isinstance(u, bytes) else str(u) for u in online}

                # Process each `username` from `online_users` to apply this step to the full collection.
                for username in online_users:
                    # Run this conditional step only when `username not in self.tasks` is true.
                    if username not in self.tasks:
                        self.tasks[username] = asyncio.create_task(self._consume_user(username))

                # Process each `username` from `list(self.tasks)` to apply this step to the full collection.
                for username in list(self.tasks):
                    # Run this conditional step only when `username not in online_users` is true.
                    if username not in online_users:
                        self.tasks[username].cancel()
                        self.tasks.pop(username, None)
            # Handle `Exception` here so this workflow can recover or report the failure consistently.
            except Exception:
                logger.exception("online user scan failed")
            await asyncio.sleep(self.settings.worker_online_scan_interval)

    # Consumes user; the worker runtime uses it for asynchronous broker delivery.
    async def _consume_user(self, username: str) -> None:
        channel = await self.amqp.channel()
        queue = await channel.declare_queue(user_queue_name(username), durable=True, auto_delete=False, exclusive=False)

        # Keep `queue.iterator()` active while this scoped operation is performed.
        async with queue.iterator() as iterator:
            # Process each `message` from `iterator` to apply this step to the full collection.
            async for message in iterator:
                # Keep `message.process(requeue=True)` active while this scoped operation is performed.
                async with message.process(requeue=True):
                    data = message.body.decode("utf-8")
                    await self.redis.publish(user_pubsub_channel(username), data)
