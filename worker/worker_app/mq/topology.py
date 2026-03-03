import aio_pika

EXCHANGE_NAME = "ex.channels"


async def ensure_topology(connection: aio_pika.RobustConnection) -> aio_pika.abc.AbstractRobustExchange:
    channel = await connection.channel()
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    return exchange
