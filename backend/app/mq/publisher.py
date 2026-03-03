import aio_pika

from app.mq.topology import EXCHANGE_NAME


async def ensure_user_queue(channel: aio_pika.abc.AbstractChannel, user_id: str) -> aio_pika.abc.AbstractQueue:
    return await channel.declare_queue(f"user.{user_id}", durable=True, auto_delete=False, exclusive=False)


async def bind_user_channel(channel: aio_pika.abc.AbstractChannel, user_id: str, channel_id: str) -> None:
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await ensure_user_queue(channel, user_id)
    await queue.bind(exchange, routing_key=f"channel.{channel_id}")


async def unbind_user_channel(channel: aio_pika.abc.AbstractChannel, user_id: str, channel_id: str) -> None:
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await ensure_user_queue(channel, user_id)
    await queue.unbind(exchange, routing_key=f"channel.{channel_id}")
