import aio_pika

from app.mq.topology import EXCHANGE_NAME


async def ensure_user_queue(channel: aio_pika.abc.AbstractChannel, username: str) -> aio_pika.abc.AbstractQueue:
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await channel.declare_queue(f"user.{username}", durable=True, auto_delete=False, exclusive=False)
    await queue.bind(exchange, routing_key=f"user.{username}")
    return queue


async def bind_user_channel(channel: aio_pika.abc.AbstractChannel, username: str, channel_slug: str) -> None:
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await ensure_user_queue(channel, username)
    await queue.bind(exchange, routing_key=f"channel.{channel_slug}")


async def unbind_user_channel(channel: aio_pika.abc.AbstractChannel, username: str, channel_slug: str) -> None:
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await ensure_user_queue(channel, username)
    await queue.unbind(exchange, routing_key=f"channel.{channel_slug}")
