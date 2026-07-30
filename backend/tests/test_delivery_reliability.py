import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parents[2] / "worker"))

from app.api.routes.delivery import delivery_stats
from app.core.errors import AppError
from app.core.utils import utcnow
from app.db.models import Event, Outbox, OutboxStatus
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.delivery_service import DeliveryService
from worker_app.core.config import Settings as WorkerSettings
from worker_app.outbox_runner import process_outbox_batch


class _FakeAmqpChannel:
    async def close(self) -> None:
        return None


class _FakeAmqpConnection:
    async def channel(self) -> _FakeAmqpChannel:
        return _FakeAmqpChannel()


class _FakeExchange:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.published: list[tuple[str, object]] = []

    async def publish(self, message: object, routing_key: str) -> None:
        if self.error is not None:
            raise self.error
        self.published.append((routing_key, message))


def _worker_settings() -> WorkerSettings:
    return WorkerSettings(
        outbox_max_attempts=5,
        outbox_initial_retry_delay_seconds=5,
        outbox_retry_backoff_multiplier=2,
        outbox_max_retry_delay_seconds=300,
    )


async def _create_channel(db_session, monkeypatch, owner_username: str = "deliver_owner"):
    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)
    owner = await AuthService.register(
        db_session,
        RegisterRequest(username=owner_username, email=f"{owner_username}@x.com", password="password123"),
    )
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name=f"{owner_username} channel", visibility="public", join_mode="open"),
        _FakeAmqpConnection(),
    )
    return owner, channel


async def _add_outbox(db_session, channel, *, status=OutboxStatus.pending, attempts=0, max_attempts=5) -> Outbox:
    row = Outbox(
        aggregate_type="message",
        aggregate_id=uuid4(),
        channel_id=channel.id,
        payload={"type": "message", "content_text": "encrypted-payload"},
        type="message",
        routing_key=f"channel.{channel.channel_slug}",
        status=status,
        attempts=attempts,
        max_attempts=max_attempts,
        last_error="previous error" if status == OutboxStatus.dead_lettered else None,
        dead_lettered_at=utcnow() if status == OutboxStatus.dead_lettered else None,
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.mark.asyncio
async def test_outbox_publish_success_marks_published(db_session, monkeypatch):
    _, channel = await _create_channel(db_session, monkeypatch, "deliver_success")
    outbox = await _add_outbox(db_session, channel)
    exchange = _FakeExchange()
    dead_letter_exchange = _FakeExchange()

    processed = await process_outbox_batch(db_session, exchange, dead_letter_exchange, _worker_settings())
    await db_session.refresh(outbox)

    assert processed == 1
    assert outbox.status == OutboxStatus.published
    assert outbox.published_at is not None
    assert outbox.last_error is None
    assert len(exchange.published) == 1
    assert dead_letter_exchange.published == []


@pytest.mark.asyncio
async def test_outbox_failure_schedules_retry_with_sanitized_error(db_session, monkeypatch):
    _, channel = await _create_channel(db_session, monkeypatch, "deliver_retry")
    outbox = await _add_outbox(db_session, channel, attempts=0, max_attempts=5)
    exchange = _FakeExchange(RuntimeError("connect failed amqp://guest:super-secret@rabbitmq:5672/?token=abc123"))
    dead_letter_exchange = _FakeExchange()

    processed = await process_outbox_batch(db_session, exchange, dead_letter_exchange, _worker_settings())
    await db_session.refresh(outbox)

    assert processed == 1
    assert outbox.status == OutboxStatus.retry_scheduled
    assert outbox.attempts == 1
    assert outbox.next_retry_at is not None
    assert "super-secret" not in (outbox.last_error or "")
    assert "token=abc123" not in (outbox.last_error or "")
    assert dead_letter_exchange.published == []
    events = (await db_session.execute(select(Event).where(Event.event_type == "broker.retry_scheduled"))).scalars().all()
    assert len(events) == 1
    assert events[0].event_hash is not None
    assert events[0].integrity_scope == f"channel:{channel.id}"


@pytest.mark.asyncio
async def test_outbox_failure_after_max_attempts_dead_letters(db_session, monkeypatch):
    _, channel = await _create_channel(db_session, monkeypatch, "deliver_dead")
    outbox = await _add_outbox(db_session, channel, attempts=4, max_attempts=5)
    exchange = _FakeExchange(RuntimeError("publisher confirm failed"))
    dead_letter_exchange = _FakeExchange()

    processed = await process_outbox_batch(db_session, exchange, dead_letter_exchange, _worker_settings())
    await db_session.refresh(outbox)

    assert processed == 1
    assert outbox.status == OutboxStatus.dead_lettered
    assert outbox.attempts == 5
    assert outbox.dead_lettered_at is not None
    assert len(dead_letter_exchange.published) == 1
    events = (await db_session.execute(select(Event).where(Event.event_type == "broker.dead_lettered"))).scalars().all()
    assert len(events) == 1
    assert events[0].event_hash is not None
    assert events[0].integrity_scope == f"channel:{channel.id}"


@pytest.mark.asyncio
async def test_admin_delivery_stats_are_scoped_to_channel_managers(db_session, monkeypatch):
    owner, channel = await _create_channel(db_session, monkeypatch, "deliver_stats")
    outsider = await AuthService.register(
        db_session,
        RegisterRequest(username="deliver_outsider", email="deliver_outsider@x.com", password="password123"),
    )
    await _add_outbox(db_session, channel, status=OutboxStatus.pending)
    await _add_outbox(db_session, channel, status=OutboxStatus.retry_scheduled, attempts=1)
    await _add_outbox(db_session, channel, status=OutboxStatus.dead_lettered, attempts=5)

    stats = await DeliveryService.get_stats(db_session, owner.id)

    assert stats.pending == 1
    assert stats.retry_scheduled == 1
    assert stats.dead_lettered == 1
    with pytest.raises(AppError) as service_error:
        await DeliveryService.get_stats(db_session, outsider.id)
    assert service_error.value.status_code == 403
    with pytest.raises(HTTPException) as route_error:
        await delivery_stats(db_session, outsider)
    assert route_error.value.status_code == 403


@pytest.mark.asyncio
async def test_manual_retry_resets_dead_lettered_outbox_and_logs_event(db_session, monkeypatch):
    owner, channel = await _create_channel(db_session, monkeypatch, "deliver_manual")
    outbox = await _add_outbox(
        db_session,
        channel,
        status=OutboxStatus.dead_lettered,
        attempts=5,
        max_attempts=5,
    )

    response = await DeliveryService.retry_one(db_session, owner.id, outbox.id)
    await db_session.refresh(outbox)

    assert response.retried_count == 1
    assert outbox.status == OutboxStatus.pending
    assert outbox.attempts == 0
    assert outbox.last_error is None
    assert outbox.dead_lettered_at is None
    events = (
        await db_session.execute(
            select(Event).where(Event.event_type == "broker.manual_retry_requested", Event.channel_id == channel.id)
        )
    ).scalars().all()
    assert len(events) == 1
