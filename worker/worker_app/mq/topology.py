import aio_pika

from worker_app.core.config import Settings, get_settings
from worker_app.redis_fanout import _normalize_username

EXCHANGE_NAME = "ex.channels"
DEAD_LETTER_EXCHANGE_NAME = "ex.channels.dlx"
DEAD_LETTER_QUEUE_NAME = "q.dead.messages"
DEAD_LETTER_BINDING_KEY = "dead.#"


def user_queue_arguments(settings: Settings | None = None) -> dict[str, int | str]:
    settings = settings or get_settings()
    return {
        "x-expires": settings.rabbit_user_queue_expires_ms,
        "x-message-ttl": settings.rabbit_user_queue_message_ttl_ms,
        "x-max-length": settings.rabbit_user_queue_max_length,
        "x-overflow": "drop-head",
    }


async def declare_user_queue(
    channel: aio_pika.abc.AbstractChannel,
    username: str,
    settings: Settings | None = None,
) -> tuple[aio_pika.abc.AbstractQueue, aio_pika.abc.AbstractExchange]:
    safe_username = _normalize_username(username)
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    queue = await channel.declare_queue(
        f"user.{safe_username}",
        durable=True,
        auto_delete=False,
        exclusive=False,
        arguments=user_queue_arguments(settings),
    )
    await queue.bind(exchange, routing_key=f"user.{safe_username}")
    return queue, exchange


async def ensure_topology(connection: aio_pika.RobustConnection) -> aio_pika.abc.AbstractRobustExchange:
    channel = await connection.channel()
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    dlx = await channel.declare_exchange(DEAD_LETTER_EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    dlq = await channel.declare_queue(DEAD_LETTER_QUEUE_NAME, durable=True, auto_delete=False, exclusive=False)
    await dlq.bind(dlx, routing_key=DEAD_LETTER_BINDING_KEY)
    return exchange
