import aio_pika

from app.core.identifiers import normalize_channel_slug, normalize_username
from app.mq.topology import EXCHANGE_NAME


async def ensure_user_queue(channel: aio_pika.abc.AbstractChannel, username: str) -> aio_pika.abc.AbstractQueue:
    """Declare the durable per-user queue using a validated broker-safe username."""

    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    safe_username = normalize_username(username)
    queue = await channel.declare_queue(f"user.{safe_username}", durable=True, auto_delete=False, exclusive=False)
    await queue.bind(exchange, routing_key=f"user.{safe_username}")
    return queue


async def bind_user_channel(channel: aio_pika.abc.AbstractChannel, username: str, channel_slug: str) -> None:
    """Subscribe a user's durable queue to a channel topic routing key."""

    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await ensure_user_queue(channel, username)
    await queue.bind(exchange, routing_key=f"channel.{normalize_channel_slug(channel_slug)}")


async def unbind_user_channel(channel: aio_pika.abc.AbstractChannel, username: str, channel_slug: str) -> None:
    """Remove a user's queue binding when they leave or lose channel access."""

    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await ensure_user_queue(channel, username)
    await queue.unbind(exchange, routing_key=f"channel.{normalize_channel_slug(channel_slug)}")
