import aio_pika

EXCHANGE_NAME = "ex.channels"
DEAD_LETTER_EXCHANGE_NAME = "ex.channels.dlx"
DEAD_LETTER_QUEUE_NAME = "q.dead.messages"
DEAD_LETTER_BINDING_KEY = "dead.#"


# Ensures topology; the API and worker use it to manage RabbitMQ routing.
async def ensure_topology(connection: aio_pika.RobustConnection) -> None:
    channel = await connection.channel()
    await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    dlx = await channel.declare_exchange(DEAD_LETTER_EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    dlq = await channel.declare_queue(DEAD_LETTER_QUEUE_NAME, durable=True, auto_delete=False, exclusive=False)
    await dlq.bind(dlx, routing_key=DEAD_LETTER_BINDING_KEY)
    await channel.close()
