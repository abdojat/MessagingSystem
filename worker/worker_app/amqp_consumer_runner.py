import asyncio
import logging

import aio_pika
from redis.asyncio import Redis

from worker_app.core.config import get_settings
from worker_app.redis_fanout import online_users_key, user_pubsub_channel, user_queue_name

logger = logging.getLogger(__name__)


class OnlineUserConsumerManager:
    def __init__(self, amqp: aio_pika.RobustConnection, redis: Redis):
        self.amqp = amqp
        self.redis = redis
        self.settings = get_settings()
        self.tasks: dict[str, asyncio.Task] = {}

    async def run(self) -> None:
        # Keep reconciling online-user consumers for the lifetime of the worker.
        while True:
            try:
                online = await self.redis.smembers(online_users_key())
                online_users = {u.decode("utf-8") if isinstance(u, bytes) else str(u) for u in online}

                for username in online_users:
                    if username not in self.tasks:
                        self.tasks[username] = asyncio.create_task(self._consume_user(username))

                for username in list(self.tasks):
                    if username not in online_users:
                        self.tasks[username].cancel()
                        self.tasks.pop(username, None)
            except Exception:
                logger.exception("online user scan failed")
            await asyncio.sleep(self.settings.worker_online_scan_interval)

    async def _consume_user(self, username: str) -> None:
        channel = await self.amqp.channel()
        queue = await channel.declare_queue(user_queue_name(username), durable=True, auto_delete=False, exclusive=False)

        async with queue.iterator() as iterator:
            async for message in iterator:
                async with message.process(requeue=True):
                    data = message.body.decode("utf-8")
                    await self.redis.publish(user_pubsub_channel(username), data)
