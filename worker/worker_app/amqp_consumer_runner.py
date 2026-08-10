import asyncio
import logging

import aio_pika
from redis.asyncio import Redis

from worker_app.core.config import get_settings
from worker_app.redis_fanout import online_users_key, user_pubsub_channel
from worker_app.mq.topology import declare_user_queue

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
        queue, _ = await declare_user_queue(channel, username, self.settings)

        async with queue.iterator() as iterator:
            failure_streak = 0
            async for message in iterator:
                async with message.process(requeue=True):
                    data = message.body.decode("utf-8")
                    try:
                        await publish_redis_with_backoff(self.redis, user_pubsub_channel(username), data, self.settings)
                        failure_streak = 0
                    except Exception:
                        failure_streak += 1
                        # Sleep before NACK/requeue so a Redis outage cannot turn
                        # one RabbitMQ delivery into a tight CPU/network loop.
                        await asyncio.sleep(redis_requeue_delay(failure_streak, self.settings))
                        raise


def redis_requeue_delay(failure_streak: int, settings) -> float:
    initial = max(0.05, float(settings.redis_fanout_initial_retry_delay_seconds))
    cap = max(initial, float(settings.redis_fanout_max_retry_delay_seconds))
    return min(cap, initial * (2 ** max(failure_streak - 1, 0)))


async def publish_redis_with_backoff(redis: Redis, channel_name: str, data: str, settings) -> None:
    attempts = max(1, int(settings.redis_fanout_max_attempts))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await redis.publish(channel_name, data)
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                await asyncio.sleep(redis_requeue_delay(attempt, settings))
    assert last_error is not None
    raise last_error
