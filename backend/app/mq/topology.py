import aio_pika

EXCHANGE_NAME = "ex.channels"


async def ensure_topology(connection: aio_pika.RobustConnection) -> None:
    channel = await connection.channel()
    await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    await channel.close()
