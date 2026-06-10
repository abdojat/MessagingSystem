import enum
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event

HASH_ALGORITHM = "sha256"
INTEGRITY_VERSION = 1


def integrity_scope_for_event(channel_id: UUID | None) -> str:
    if channel_id is None:
        return "system"
    return f"channel:{channel_id}"


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = _as_utc_datetime(value)
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical_value(value[key]) for key in sorted(value.keys(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def canonical_event_payload(event: Event) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "channel_id": str(event.channel_id) if event.channel_id is not None else None,
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id is not None else None,
        "event_type": event.event_type,
        "created_at": _canonical_value(event.created_at),
        "payload": _canonical_value(event.payload or {}),
        "previous_hash": event.previous_hash,
        "integrity_version": event.integrity_version,
        "integrity_scope": event.integrity_scope,
    }


def canonical_event_json(event: Event) -> str:
    return json.dumps(canonical_event_payload(event), sort_keys=True, separators=(",", ":"), default=str)


def compute_event_hash(event: Event) -> str:
    return hashlib.sha256(canonical_event_json(event).encode("utf-8")).hexdigest()


class EventIntegrityService:
    @staticmethod
    def scope_for_event(channel_id: UUID | None) -> str:
        return integrity_scope_for_event(channel_id)

    @staticmethod
    async def lock_scope(db: AsyncSession, scope: str) -> None:
        bind = db.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"), {"scope": scope})

    @staticmethod
    async def attach_integrity(db: AsyncSession, event: Event, scope: str | None = None) -> Event:
        resolved_scope = scope or integrity_scope_for_event(event.channel_id)
        latest = await EventIntegrityService._latest_integrity_event(db, resolved_scope)
        previous_hash = latest.event_hash if latest is not None else None
        if latest is not None and _as_utc_datetime(event.created_at) <= _as_utc_datetime(latest.created_at):
            event.created_at = _as_utc_datetime(latest.created_at) + timedelta(microseconds=1)
            await db.flush()
        event.previous_hash = previous_hash
        event.hash_algorithm = HASH_ALGORITHM
        event.integrity_version = INTEGRITY_VERSION
        event.integrity_scope = resolved_scope
        event.event_hash = compute_event_hash(event)
        return event

    @staticmethod
    async def _latest_integrity_event(db: AsyncSession, scope: str) -> Event | None:
        row = await db.execute(
            select(Event)
            .where(Event.integrity_scope == scope, Event.event_hash.is_not(None))
            .order_by(Event.created_at.desc(), Event.id.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()

    @staticmethod
    async def verify_channel_scope(db: AsyncSession, channel_id: UUID) -> dict[str, Any]:
        scope = integrity_scope_for_event(channel_id)
        rows = await db.execute(
            select(Event)
            .where(
                or_(
                    Event.integrity_scope == scope,
                    and_(Event.channel_id == channel_id, Event.integrity_scope.is_(None)),
                )
            )
            .order_by(Event.created_at.asc(), Event.id.asc())
        )
        return EventIntegrityService.verify_events(scope, list(rows.scalars().all()))

    @staticmethod
    def verify_events(scope: str, events: list[Event]) -> dict[str, Any]:
        checked_events = 0
        previous_hash: str | None = None
        previous_event_id: str | None = None
        first_event_id = str(events[0].id) if events else None
        last_event_id = str(events[-1].id) if events else None

        for event in events:
            checked_events += 1

            if (
                event.event_hash is None
                or event.integrity_scope is None
                or event.hash_algorithm is None
                or event.integrity_version is None
            ):
                return EventIntegrityService._invalid_result(
                    scope,
                    checked_events,
                    event,
                    "missing_hash",
                    previous_event_id,
                    previous_hash,
                    first_event_id,
                    last_event_id,
                )
            if event.integrity_scope != scope:
                return EventIntegrityService._invalid_result(
                    scope,
                    checked_events,
                    event,
                    "integrity_scope_mismatch",
                    previous_event_id,
                    previous_hash,
                    first_event_id,
                    last_event_id,
                    expected_hash=scope,
                    actual_hash=event.integrity_scope,
                )
            if event.hash_algorithm != HASH_ALGORITHM:
                return EventIntegrityService._invalid_result(
                    scope,
                    checked_events,
                    event,
                    "unsupported_algorithm",
                    previous_event_id,
                    previous_hash,
                    first_event_id,
                    last_event_id,
                    expected_hash=HASH_ALGORITHM,
                    actual_hash=event.hash_algorithm,
                )
            if event.integrity_version != INTEGRITY_VERSION:
                return EventIntegrityService._invalid_result(
                    scope,
                    checked_events,
                    event,
                    "unsupported_integrity_version",
                    previous_event_id,
                    previous_hash,
                    first_event_id,
                    last_event_id,
                    expected_hash=str(INTEGRITY_VERSION),
                    actual_hash=str(event.integrity_version),
                )
            if event.previous_hash != previous_hash:
                return EventIntegrityService._invalid_result(
                    scope,
                    checked_events,
                    event,
                    "previous_hash_mismatch",
                    previous_event_id,
                    previous_hash,
                    first_event_id,
                    last_event_id,
                    expected_hash=previous_hash,
                    actual_hash=event.previous_hash,
                )

            expected_hash = compute_event_hash(event)
            if event.event_hash != expected_hash:
                return EventIntegrityService._invalid_result(
                    scope,
                    checked_events,
                    event,
                    "hash_mismatch",
                    previous_event_id,
                    previous_hash,
                    first_event_id,
                    last_event_id,
                    expected_hash=expected_hash,
                    actual_hash=event.event_hash,
                )

            previous_hash = event.event_hash
            previous_event_id = str(event.id)

        return {
            "scope": scope,
            "valid": True,
            "checked_events": checked_events,
            "broken_event_id": None,
            "reason": None,
            "expected_hash": None,
            "actual_hash": None,
            "previous_event_id": previous_event_id,
            "last_valid_hash": previous_hash,
            "first_event_id": first_event_id,
            "last_event_id": last_event_id,
            "hash_algorithm": HASH_ALGORITHM,
            "integrity_version": INTEGRITY_VERSION,
        }

    @staticmethod
    def _invalid_result(
        scope: str,
        checked_events: int,
        event: Event,
        reason: str,
        previous_event_id: str | None,
        last_valid_hash: str | None,
        first_event_id: str | None,
        last_event_id: str | None,
        *,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
    ) -> dict[str, Any]:
        return {
            "scope": scope,
            "valid": False,
            "checked_events": checked_events,
            "broken_event_id": str(event.id),
            "reason": reason,
            "expected_hash": expected_hash,
            "actual_hash": actual_hash,
            "previous_event_id": previous_event_id,
            "last_valid_hash": last_valid_hash,
            "first_event_id": first_event_id,
            "last_event_id": last_event_id,
            "hash_algorithm": HASH_ALGORITHM,
            "integrity_version": INTEGRITY_VERSION,
        }
