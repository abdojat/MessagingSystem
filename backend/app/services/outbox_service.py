from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.identifiers import normalize_channel_slug, normalize_username
from app.db.models import (
    BrokerBindingState,
    Channel,
    ChannelMembership,
    MembershipRole,
    Outbox,
    OutboxStatus,
    User,
)


APPROVED_BROKER_ROLES = {MembershipRole.owner, MembershipRole.admin, MembershipRole.member}


async def _get_channel_delivery_state(db: AsyncSession, channel_id: UUID) -> tuple[str, int]:
    # A shared row lock gives message/channel events a generation that is
    # linearly ordered with membership transitions, which take an exclusive
    # lock before incrementing the same channel row.
    row = await db.execute(
        select(Channel.channel_slug, Channel.membership_generation)
        .where(Channel.id == channel_id)
        .with_for_update(read=True)
    )
    data = row.one_or_none()
    if data is None:
        raise ValueError(f"channel not found for outbox routing: {channel_id}")
    return normalize_channel_slug(str(data.channel_slug)), int(data.membership_generation)


def _payload_with_membership_generation(payload: dict, generation: int) -> dict:
    enriched = dict(payload)
    enriched["membership_generation"] = generation
    return enriched


async def _get_username(db: AsyncSession, user_id: UUID) -> str:
    row = await db.execute(select(User.username).where(User.id == user_id))
    username = row.scalar_one_or_none()
    if username is None:
        raise ValueError(f"user not found for outbox routing: {user_id}")
    return normalize_username(str(username))


async def enqueue_message_outbox(
    db: AsyncSession,
    message_id: UUID,
    channel_id: UUID,
    payload: dict,
) -> Outbox:
    settings = get_settings()
    channel_slug, membership_generation = await _get_channel_delivery_state(db, channel_id)
    row = Outbox(
        aggregate_type="message",
        aggregate_id=message_id,
        channel_id=channel_id,
        payload=_payload_with_membership_generation(payload, membership_generation),
        type=str(payload.get("type", "message")),
        routing_key=f"channel.{channel_slug}",
        status=OutboxStatus.pending,
        max_attempts=settings.outbox_max_attempts,
    )
    db.add(row)
    await db.flush()
    return row


async def enqueue_channel_event_outbox(
    db: AsyncSession,
    aggregate_id: UUID,
    channel_id: UUID,
    event_type: str,
    payload: dict,
) -> Outbox:
    settings = get_settings()
    channel_slug, membership_generation = await _get_channel_delivery_state(db, channel_id)
    row = Outbox(
        aggregate_type=event_type,
        aggregate_id=aggregate_id,
        channel_id=channel_id,
        payload=_payload_with_membership_generation(payload, membership_generation),
        type=event_type,
        routing_key=f"channel.{channel_slug}",
        status=OutboxStatus.pending,
        max_attempts=settings.outbox_max_attempts,
    )
    db.add(row)
    await db.flush()
    return row


async def enqueue_user_event_outbox(
    db: AsyncSession,
    aggregate_id: UUID,
    channel_id: UUID,
    user_id: UUID,
    event_type: str,
    payload: dict,
) -> Outbox:
    settings = get_settings()
    username = await _get_username(db, user_id)
    _, membership_generation = await _get_channel_delivery_state(db, channel_id)
    row = Outbox(
        aggregate_type=event_type,
        aggregate_id=aggregate_id,
        channel_id=channel_id,
        payload=_payload_with_membership_generation(payload, membership_generation),
        type=event_type,
        routing_key=f"user.{username}",
        status=OutboxStatus.pending,
        max_attempts=settings.outbox_max_attempts,
    )
    db.add(row)
    await db.flush()
    return row


async def enqueue_broker_binding_outbox(
    db: AsyncSession,
    channel_id: UUID,
    user_id: UUID,
    action: str,
) -> Outbox:
    if action not in {"bind", "unbind"}:
        raise ValueError("broker binding action must be bind or unbind")

    # The caller's action is retained only as a compatibility/sanity input.
    # Desired state is always derived from current PostgreSQL authorization,
    # never trusted from the historical command.
    channel_row = await db.execute(select(Channel).where(Channel.id == channel_id).with_for_update())
    channel = channel_row.scalar_one_or_none()
    if channel is None:
        raise ValueError(f"channel not found for broker binding state: {channel_id}")
    membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})
    desired_bound = bool(
        channel.deleted_at is None and membership is not None and membership.role in APPROVED_BROKER_ROLES
    )
    routing_key = f"channel.{normalize_channel_slug(channel.channel_slug)}"

    state_row = await db.execute(
        select(BrokerBindingState)
        .where(BrokerBindingState.channel_id == channel_id, BrokerBindingState.user_id == user_id)
        .with_for_update()
    )
    state = state_row.scalar_one_or_none()
    if state is None:
        state = BrokerBindingState(
            channel_id=channel_id,
            user_id=user_id,
            generation=1,
            desired_bound=desired_bound,
            desired_routing_key=routing_key,
            routing_keys=[routing_key],
            reconciled_generation=0,
        )
        db.add(state)
    else:
        known_keys = [str(key) for key in (state.routing_keys or []) if str(key)]
        if state.desired_routing_key and state.desired_routing_key not in known_keys:
            known_keys.append(state.desired_routing_key)
        if routing_key not in known_keys:
            known_keys.append(routing_key)
        state.generation = int(state.generation) + 1
        state.desired_bound = desired_bound
        state.desired_routing_key = routing_key
        state.routing_keys = known_keys
    await db.flush()

    return await _enqueue_broker_binding_snapshot(db, state)


async def _enqueue_broker_binding_snapshot(db: AsyncSession, state: BrokerBindingState) -> Outbox:
    settings = get_settings()
    row = Outbox(
        aggregate_type="broker_binding",
        aggregate_id=state.user_id,
        channel_id=state.channel_id,
        payload={
            "type": "broker_binding",
            "schema_version": 1,
            "generation": int(state.generation),
            "user_id": str(state.user_id),
            "channel_id": str(state.channel_id),
        },
        type="broker_binding.reconcile",
        # The worker intercepts broker_binding rows instead of publishing this
        # routing key as an application event.
        routing_key="broker.binding",
        status=OutboxStatus.pending,
        max_attempts=settings.outbox_max_attempts,
    )
    db.add(row)
    await db.flush()
    return row


async def bump_channel_membership_generation(db: AsyncSession, channel_id: UUID) -> int:
    """Serialize and version a channel authorization change in its transaction."""

    row = await db.execute(select(Channel).where(Channel.id == channel_id).with_for_update())
    channel = row.scalar_one_or_none()
    if channel is None:
        raise ValueError(f"channel not found for membership generation: {channel_id}")
    channel.membership_generation = int(channel.membership_generation or 0) + 1
    await db.flush()
    return int(channel.membership_generation)


async def enqueue_user_broker_binding_reconciliation(db: AsyncSession, user_id: UUID) -> int:
    """Re-enqueue current desired states, including stale undesired bindings."""

    membership_channels = set(
        (
            await db.execute(
                select(ChannelMembership.channel_id).where(ChannelMembership.user_id == user_id)
            )
        ).scalars().all()
    )
    existing_channels = set(
        (
            await db.execute(
                select(BrokerBindingState.channel_id).where(BrokerBindingState.user_id == user_id)
            )
        ).scalars().all()
    )
    created: set[UUID] = set()
    for channel_id in sorted(membership_channels - existing_channels, key=str):
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})
        action = "bind" if membership and membership.role in APPROVED_BROKER_ROLES else "unbind"
        await enqueue_broker_binding_outbox(db, channel_id, user_id, action)
        created.add(channel_id)

    states = (
        await db.execute(
            select(BrokerBindingState)
            .where(BrokerBindingState.user_id == user_id)
            .order_by(BrokerBindingState.channel_id)
            .with_for_update()
        )
    ).scalars().all()
    count = len(created)
    for state in states:
        if state.channel_id in created:
            continue
        await _enqueue_broker_binding_snapshot(db, state)
        count += 1
    return count


async def enqueue_all_broker_binding_reconciliation(db: AsyncSession) -> int:
    """Operator repair path that derives every known binding from PostgreSQL."""

    missing_pairs = (
        await db.execute(
            select(ChannelMembership.channel_id, ChannelMembership.user_id)
            .outerjoin(
                BrokerBindingState,
                and_(
                    BrokerBindingState.channel_id == ChannelMembership.channel_id,
                    BrokerBindingState.user_id == ChannelMembership.user_id,
                ),
            )
            .where(BrokerBindingState.channel_id.is_(None))
            .order_by(ChannelMembership.channel_id, ChannelMembership.user_id)
        )
    ).all()
    created: set[tuple[UUID, UUID]] = set()
    for channel_id, user_id in missing_pairs:
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})
        action = "bind" if membership and membership.role in APPROVED_BROKER_ROLES else "unbind"
        await enqueue_broker_binding_outbox(db, channel_id, user_id, action)
        created.add((channel_id, user_id))

    states = (
        await db.execute(
            select(BrokerBindingState)
            .order_by(BrokerBindingState.channel_id, BrokerBindingState.user_id)
            .with_for_update()
        )
    ).scalars().all()
    count = len(created)
    for state in states:
        if (state.channel_id, state.user_id) in created:
            continue
        await _enqueue_broker_binding_snapshot(db, state)
        count += 1
    return count
