import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import aio_pika
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker_app.core.config import Settings, get_settings
from worker_app.db.session import SessionLocal
from worker_app.mq.topology import DEAD_LETTER_EXCHANGE_NAME, EXCHANGE_NAME

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 1000
HASH_ALGORITHM = "sha256"
INTEGRITY_VERSION = 1


# Canonicalizes value; the worker runtime uses it for asynchronous broker delivery.
def _canonical_value(value: Any) -> Any:
    # Run this conditional step only when `isinstance(value, datetime)` is true.
    if isinstance(value, datetime):
        normalized = _as_utc_datetime(value)
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    # Return early when `isinstance(value, dict)` because the remaining work is not applicable.
    if isinstance(value, dict):
        return {str(key): _canonical_value(value[key]) for key in sorted(value.keys(), key=str)}
    # Return early when `isinstance(value, (list, tuple))` because the remaining work is not applicable.
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


# Implements the as utc datetime operation; the worker runtime uses it for asynchronous broker delivery.
def _as_utc_datetime(value: datetime) -> datetime:
    # Return early when `value.tzinfo is None` because the remaining work is not applicable.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# Implements the event integrity scope operation; the worker runtime uses it for asynchronous broker delivery.
def _event_integrity_scope(channel_id: Any) -> str:
    # Return early when `channel_id is None` because the remaining work is not applicable.
    if channel_id is None:
        return "system"
    return f"channel:{channel_id}"


# Computes event hash; the worker runtime uses it for asynchronous broker delivery.
def _compute_event_hash(
    *,
    event_id: str,
    channel_id: Any,
    actor_user_id: Any,
    event_type: str,
    payload: dict[str, Any],
    created_at: datetime,
    previous_hash: str | None,
    integrity_scope: str,
) -> str:
    canonical_payload = {
        "id": str(event_id),
        "channel_id": str(channel_id) if channel_id is not None else None,
        "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
        "event_type": event_type,
        "created_at": _canonical_value(created_at),
        "payload": _canonical_value(payload or {}),
        "previous_hash": previous_hash,
        "integrity_version": INTEGRITY_VERSION,
        "integrity_scope": integrity_scope,
    }
    canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# Sanitizes error; the worker runtime uses it for asynchronous broker delivery.
def sanitize_error(exc: BaseException | str) -> str:
    message = str(exc)
    message = re.sub(r"(amqps?://)([^:/@\s]+):([^@\s]+)@", r"\1***:***@", message)
    message = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1***", message)
    message = re.sub(r"(?i)((?:token|secret|password|key)=)[^&\s]+", r"\1***", message)
    return message[:MAX_ERROR_LENGTH]


# Calculates retry delay; the worker runtime uses it for asynchronous broker delivery.
def calculate_retry_delay(attempt_count: int, settings: Settings) -> int:
    initial = max(1, int(settings.outbox_initial_retry_delay_seconds))
    multiplier = max(1.0, float(settings.outbox_retry_backoff_multiplier))
    cap = max(initial, int(settings.outbox_max_retry_delay_seconds))
    delay = initial * (multiplier ** max(attempt_count - 1, 0))
    return int(min(cap, delay))


# Runs outbox publisher; the worker runtime uses it for asynchronous broker delivery.
async def run_outbox_publisher(amqp: aio_pika.RobustConnection) -> None:
    settings = get_settings()
    channel = await amqp.channel(publisher_confirms=True)
    exchange = await channel.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)
    dead_letter_exchange = await channel.declare_exchange(DEAD_LETTER_EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True)

    # Keep polling the persistent outbox until the worker process is stopped.
    while True:
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            # Keep `SessionLocal()` active while this scoped operation is performed.
            async with SessionLocal() as db:
                processed = await process_outbox_batch(db, exchange, dead_letter_exchange, settings)
                # Run this conditional step only when `processed == 0` is true.
                if processed == 0:
                    await asyncio.sleep(settings.outbox_poll_interval)
        # Handle `Exception` here so this workflow can recover or report the failure consistently.
        except Exception:
            logger.exception("outbox loop failed")
            await asyncio.sleep(settings.outbox_poll_interval)


# Processes outbox batch; the worker runtime uses it for asynchronous broker delivery.
async def process_outbox_batch(
    db: AsyncSession,
    exchange: aio_pika.abc.AbstractExchange,
    dead_letter_exchange: aio_pika.abc.AbstractExchange,
    settings: Settings,
    limit: int = 100,
) -> int:
    rows = await db.execute(
        text(
            """
            SELECT id, payload, routing_key, attempts, max_attempts,
                   channel_id, aggregate_type, aggregate_id, type
            FROM outbox
            WHERE status = 'pending'
               OR (status = 'retry_scheduled' AND next_retry_at <= now())
            ORDER BY created_at ASC
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": limit},
    )
    records = rows.mappings().all()
    # Run this conditional step only when `not records` is true.
    if not records:
        await db.rollback()
        return 0

    # Process each `rec` from `records` to apply this step to the full collection.
    for rec in records:
        await _mark_publishing(db, rec["id"])
        body = _payload_to_body(rec["payload"])
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            await _publish_to_exchange(exchange, rec["routing_key"], body)
            await _mark_published(db, rec["id"])
        # Handle `Exception` here so this workflow can recover or report the failure consistently.
        except Exception as exc:
            await _handle_publish_failure(db, dead_letter_exchange, rec, body, exc, settings)

    await db.commit()
    return len(records)


# Implements the payload to body operation; the worker runtime uses it for asynchronous broker delivery.
def _payload_to_body(payload: Any) -> bytes:
    # Return early when `isinstance(payload, str)` because the remaining work is not applicable.
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, default=str).encode("utf-8")


# Publishes to exchange; the worker runtime uses it for asynchronous broker delivery.
async def _publish_to_exchange(exchange: aio_pika.abc.AbstractExchange, routing_key: str, body: bytes) -> None:
    await exchange.publish(
        aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=routing_key,
    )


# Publishes to dead letter exchange; the worker runtime uses it for asynchronous broker delivery.
async def _publish_to_dead_letter_exchange(
    dead_letter_exchange: aio_pika.abc.AbstractExchange,
    rec: dict[str, Any],
    body: bytes,
    error_text: str,
    attempt_count: int,
) -> None:
    await dead_letter_exchange.publish(
        aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            headers={
                "x-outbox-id": str(rec["id"]),
                "x-original-routing-key": str(rec["routing_key"]),
                "x-attempt-count": attempt_count,
                "x-last-error": error_text[:500],
            },
        ),
        routing_key=f"dead.{rec['routing_key']}",
    )


# Marks publishing; the worker runtime uses it for asynchronous broker delivery.
async def _mark_publishing(db: AsyncSession, outbox_id: Any) -> None:
    await db.execute(
        text(
            """
            UPDATE outbox
            SET status = 'publishing',
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": outbox_id},
    )


# Marks published; the worker runtime uses it for asynchronous broker delivery.
async def _mark_published(db: AsyncSession, outbox_id: Any) -> None:
    await db.execute(
        text(
            """
            UPDATE outbox
            SET status = 'published',
                sent_at = now(),
                published_at = now(),
                next_retry_at = NULL,
                last_error = NULL,
                dead_lettered_at = NULL,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": outbox_id},
    )


# Handles publish failure; the worker runtime uses it for asynchronous broker delivery.
async def _handle_publish_failure(
    db: AsyncSession,
    dead_letter_exchange: aio_pika.abc.AbstractExchange,
    rec: dict[str, Any],
    body: bytes,
    exc: BaseException,
    settings: Settings,
) -> None:
    error_text = sanitize_error(exc)
    previous_attempts = int(rec["attempts"] or 0)
    attempt_count = previous_attempts + 1
    max_attempts = max(1, int(rec["max_attempts"] or settings.outbox_max_attempts))

    # Run this conditional step only when `attempt_count >= max_attempts` is true.
    if attempt_count >= max_attempts:
        await _mark_dead_lettered(db, rec["id"], error_text, attempt_count)
        await _insert_delivery_event(
            db,
            "broker.dead_lettered",
            rec.get("channel_id"),
            {
                "outbox_id": str(rec["id"]),
                "routing_key": rec["routing_key"],
                "attempt_count": attempt_count,
                "max_attempts": max_attempts,
                "last_error": error_text,
            },
        )
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            await _publish_to_dead_letter_exchange(dead_letter_exchange, rec, body, error_text, attempt_count)
        # Handle `Exception` here so this workflow can recover or report the failure consistently.
        except Exception as dlq_exc:
            logger.warning(
                "failed to mirror dead-lettered outbox item %s to RabbitMQ DLQ: %s",
                rec["id"],
                sanitize_error(dlq_exc),
            )
        return

    delay = calculate_retry_delay(attempt_count, settings)
    await _mark_retry_scheduled(db, rec["id"], error_text, attempt_count, delay)
    await _insert_delivery_event(
        db,
        "broker.retry_scheduled",
        rec.get("channel_id"),
        {
            "outbox_id": str(rec["id"]),
            "routing_key": rec["routing_key"],
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
            "retry_in_seconds": delay,
            "last_error": error_text,
        },
    )


# Marks retry scheduled; the worker runtime uses it for asynchronous broker delivery.
async def _mark_retry_scheduled(db: AsyncSession, outbox_id: Any, error_text: str, attempt_count: int, delay: int) -> None:
    await db.execute(
        text(
            """
            UPDATE outbox
            SET status = 'retry_scheduled',
                attempts = :attempt_count,
                last_error = :err,
                next_retry_at = now() + make_interval(secs => :delay),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": outbox_id, "err": error_text, "attempt_count": attempt_count, "delay": delay},
    )


# Marks dead lettered; the worker runtime uses it for asynchronous broker delivery.
async def _mark_dead_lettered(db: AsyncSession, outbox_id: Any, error_text: str, attempt_count: int) -> None:
    await db.execute(
        text(
            """
            UPDATE outbox
            SET status = 'dead_lettered',
                attempts = :attempt_count,
                last_error = :err,
                next_retry_at = NULL,
                dead_lettered_at = now(),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": outbox_id, "err": error_text, "attempt_count": attempt_count},
    )


# Inserts delivery event; the worker runtime uses it for asynchronous broker delivery.
async def _insert_delivery_event(db: AsyncSession, event_type: str, channel_id: Any, payload: dict[str, Any]) -> None:
    event_id = str(uuid4())
    created_at = datetime.now(timezone.utc)
    integrity_scope = _event_integrity_scope(channel_id)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"), {"scope": integrity_scope})
    latest_integrity_event = (
        await db.execute(
            text(
                """
                SELECT event_hash, created_at
                FROM events
                WHERE integrity_scope = :scope
                  AND event_hash IS NOT NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"scope": integrity_scope},
        )
    ).mappings().first()
    previous_hash = latest_integrity_event["event_hash"] if latest_integrity_event is not None else None
    # Run this conditional step only when `latest_integrity_event is not None` is true.
    if latest_integrity_event is not None:
        previous_created_at = latest_integrity_event["created_at"]
        # Run this conditional step only when `_as_utc_datetime(created_at) <= _as_utc_datetime(previous_created_at)` is true.
        if _as_utc_datetime(created_at) <= _as_utc_datetime(previous_created_at):
            created_at = _as_utc_datetime(previous_created_at) + timedelta(microseconds=1)
    event_hash = _compute_event_hash(
        event_id=event_id,
        channel_id=channel_id,
        actor_user_id=None,
        event_type=event_type,
        payload=payload,
        created_at=created_at,
        previous_hash=previous_hash,
        integrity_scope=integrity_scope,
    )
    await db.execute(
        text(
            """
            INSERT INTO events (
                id,
                channel_id,
                actor_user_id,
                event_type,
                payload,
                created_at,
                previous_hash,
                event_hash,
                hash_algorithm,
                integrity_version,
                integrity_scope
            )
            VALUES (
                :event_id,
                :channel_id,
                NULL,
                :event_type,
                CAST(:payload AS jsonb),
                :created_at,
                :previous_hash,
                :event_hash,
                :hash_algorithm,
                :integrity_version,
                :integrity_scope
            )
            """
        ),
        {
            "event_id": event_id,
            "channel_id": channel_id,
            "event_type": event_type,
            "payload": json.dumps(payload, default=str),
            "created_at": created_at,
            "previous_hash": previous_hash,
            "event_hash": event_hash,
            "hash_algorithm": HASH_ALGORITHM,
            "integrity_version": INTEGRITY_VERSION,
            "integrity_scope": integrity_scope,
        },
    )
