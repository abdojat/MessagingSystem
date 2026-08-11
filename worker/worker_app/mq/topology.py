import logging

import aio_pika
from aio_pika.exceptions import ChannelPreconditionFailed

from worker_app.core.config import Settings, get_settings
from worker_app.redis_fanout import _normalize_username

EXCHANGE_NAME = "ex.channels"
DEAD_LETTER_EXCHANGE_NAME = "ex.channels.dlx"
DEAD_LETTER_QUEUE_NAME = "q.dead.messages"
DEAD_LETTER_BINDING_KEY = "dead.#"
MANAGED_QUEUE_ARGUMENTS = ("x-expires", "x-message-ttl", "x-max-length", "x-overflow")

logger = logging.getLogger(__name__)


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


def _is_legacy_user_queue_mismatch(exc: BaseException, queue_name: str) -> bool:
    """Recognize only pre-bounded managed queues; do not delete arbitrary mismatches."""

    message = str(exc)
    return bool(
        isinstance(exc, ChannelPreconditionFailed)
        and "inequivalent arg" in message
        and f"queue '{queue_name}'" in message
        and "current is none" in message
        and any(f"'{argument}'" in message for argument in MANAGED_QUEUE_ARGUMENTS)
    )


async def migrate_legacy_user_queue(
    connection: aio_pika.RobustConnection,
    username: str,
    settings: Settings | None = None,
) -> bool:
    """Replace one pre-bounded realtime queue while PostgreSQL retains history."""

    safe_username = _normalize_username(username)
    queue_name = f"user.{safe_username}"
    channel = await connection.channel()
    try:
        await declare_user_queue(channel, safe_username, settings)
        return False
    except ChannelPreconditionFailed as exc:
        if not _is_legacy_user_queue_mismatch(exc, queue_name):
            raise

    # The failed declaration closes its AMQP channel. Delete and redeclare on a
    # fresh channel, refusing to disrupt a queue that another worker consumes.
    repair_channel = await connection.channel()
    await repair_channel.queue_delete(queue_name, if_unused=True, if_empty=False)
    await declare_user_queue(repair_channel, safe_username, settings)
    logger.warning(
        "recreated legacy unbounded realtime queue %s; missed delivery remains recoverable through PostgreSQL sync",
        queue_name,
    )
    return True


async def ensure_topology(connection: aio_pika.RobustConnection) -> aio_pika.abc.AbstractRobustExchange:
    channel = await connection.channel()
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    dlx = await channel.declare_exchange(DEAD_LETTER_EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    dlq = await channel.declare_queue(DEAD_LETTER_QUEUE_NAME, durable=True, auto_delete=False, exclusive=False)
    await dlq.bind(dlx, routing_key=DEAD_LETTER_BINDING_KEY)
    return exchange
