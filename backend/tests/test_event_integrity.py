import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes.events import verify_channel_event_integrity
from app.db.models import Event
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest, JoinRequest
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.event_integrity_service import EventIntegrityService


class _FakeAmqpChannel:
    async def close(self) -> None:
        return None


class _FakeAmqpConnection:
    async def channel(self) -> _FakeAmqpChannel:
        return _FakeAmqpChannel()


async def _create_open_channel(db_session, monkeypatch, owner_username: str = "integrity_owner"):
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


async def _channel_events(db_session, channel_id):
    rows = await db_session.execute(
        select(Event).where(Event.channel_id == channel_id).order_by(Event.created_at.asc(), Event.id.asc())
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_new_events_receive_hash_chain_metadata(db_session, monkeypatch):
    owner, channel = await _create_open_channel(db_session, monkeypatch)
    subscriber = await AuthService.register(
        db_session,
        RegisterRequest(username="integrity_sub", email="integrity_sub@x.com", password="password123"),
    )
    await ChannelService.join_channel(db_session, _FakeAmqpConnection(), channel.id, subscriber.id, JoinRequest())

    events = await _channel_events(db_session, channel.id)

    assert len(events) >= 2
    assert events[0].previous_hash is None
    assert events[0].event_hash is not None
    assert events[0].hash_algorithm == "sha256"
    assert events[0].integrity_version == 1
    assert events[0].integrity_scope == f"channel:{channel.id}"
    assert events[1].previous_hash == events[0].event_hash
    assert events[1].event_hash is not None


@pytest.mark.asyncio
async def test_integrity_verification_returns_valid_for_unchanged_chain(db_session, monkeypatch):
    _, channel = await _create_open_channel(db_session, monkeypatch, "integrity_valid")

    result = await EventIntegrityService.verify_channel_scope(db_session, channel.id)

    assert result["valid"] is True
    assert result["checked_events"] >= 1
    assert result["last_valid_hash"]
    assert result["broken_event_id"] is None


@pytest.mark.asyncio
async def test_integrity_verification_detects_payload_tampering(db_session, monkeypatch):
    _, channel = await _create_open_channel(db_session, monkeypatch, "integrity_payload")
    events = await _channel_events(db_session, channel.id)
    event = events[0]
    event.payload = {**(event.payload or {}), "tampered": True}
    await db_session.commit()

    result = await EventIntegrityService.verify_channel_scope(db_session, channel.id)

    assert result["valid"] is False
    assert result["reason"] == "hash_mismatch"
    assert result["broken_event_id"] == str(event.id)


@pytest.mark.asyncio
async def test_integrity_verification_detects_event_type_tampering(db_session, monkeypatch):
    _, channel = await _create_open_channel(db_session, monkeypatch, "integrity_type")
    events = await _channel_events(db_session, channel.id)
    event = events[0]
    event.event_type = "channel.created.tampered"
    await db_session.commit()

    result = await EventIntegrityService.verify_channel_scope(db_session, channel.id)

    assert result["valid"] is False
    assert result["reason"] == "hash_mismatch"
    assert result["broken_event_id"] == str(event.id)


@pytest.mark.asyncio
async def test_integrity_verification_detects_previous_hash_tampering(db_session, monkeypatch):
    _, channel = await _create_open_channel(db_session, monkeypatch, "integrity_previous")
    subscriber = await AuthService.register(
        db_session,
        RegisterRequest(username="integrity_prev_sub", email="integrity_prev_sub@x.com", password="password123"),
    )
    await ChannelService.join_channel(db_session, _FakeAmqpConnection(), channel.id, subscriber.id, JoinRequest())
    events = await _channel_events(db_session, channel.id)
    event = events[1]
    event.previous_hash = "0" * 64
    await db_session.commit()

    result = await EventIntegrityService.verify_channel_scope(db_session, channel.id)

    assert result["valid"] is False
    assert result["reason"] == "previous_hash_mismatch"
    assert result["broken_event_id"] == str(event.id)


@pytest.mark.asyncio
async def test_integrity_verification_reports_legacy_missing_hash(db_session, monkeypatch):
    _, channel = await _create_open_channel(db_session, monkeypatch, "integrity_legacy")
    events = await _channel_events(db_session, channel.id)
    event = events[0]
    event.previous_hash = None
    event.event_hash = None
    event.hash_algorithm = None
    event.integrity_version = None
    event.integrity_scope = None
    await db_session.commit()

    result = await EventIntegrityService.verify_channel_scope(db_session, channel.id)

    assert result["valid"] is False
    assert result["reason"] == "missing_hash"
    assert result["broken_event_id"] == str(event.id)


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_verify_channel_event_integrity(db_session, monkeypatch):
    _, channel = await _create_open_channel(db_session, monkeypatch, "integrity_authz")
    outsider = await AuthService.register(
        db_session,
        RegisterRequest(username="integrity_outsider", email="integrity_outsider@x.com", password="password123"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await verify_channel_event_integrity(channel.id, db_session, outsider)

    assert exc_info.value.status_code == 403
