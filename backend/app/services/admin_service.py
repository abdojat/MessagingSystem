from uuid import UUID

import aio_pika
from sqlalchemy import String, and_, case, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.utils import utcnow
from app.db.models import (
    Channel,
    ChannelMembership,
    Event,
    MembershipRole,
    Message,
    Outbox,
    OutboxStatus,
    User,
    UserSession,
)
from app.mq.publisher import bind_user_channel
from app.schemas.admin import (
    AdminChannelItem,
    AdminEventItem,
    AdminOverviewResponse,
    AdminUserItem,
)
from app.services.event_service import log_event
from app.services.outbox_service import enqueue_channel_event_outbox


# Groups the admin business operations; API route handlers call it to enforce application business rules.
class AdminService:
    EVENT_CATEGORY_PREFIXES = {
        "security": ("security.",),
        "channels": ("channel.",),
        "messages": ("message.",),
        "memberships": ("membership.", "member.", "invite."),
        "uploads": ("upload.",),
        "delivery": ("broker.",),
        "administration": ("superadmin.",),
        "system": ("system.", "user."),
    }

    SAFE_EVENT_DETAIL_KEYS_BY_PREFIX = {
        "channel": {
            "channel_id", "channel_slug", "join_mode", "name", "requested_slug",
            "resolved_slug", "superadmin_override", "visibility",
        },
        "message": {"attachment_count", "channel_id", "content_type", "message_id", "reason", "seq_id"},
        "membership": {"channel_id", "role", "target_user_id", "user_id"},
        "member": {"channel_id", "role", "target_user_id"},
        "invite": {"channel_id", "invite_id", "target_user_id", "user_id"},
        "upload": {
            "actual_size_bytes", "content_type", "expected_size_bytes", "filename",
            "has_checksum", "reason", "size_bytes", "upload_id",
        },
        "security": {"channel_id", "identity", "reason", "upload_id"},
        "broker": {
            "attempt_count", "channel_id", "manual_retry", "max_attempts", "outbox_id",
            "previous_attempt_count", "previous_status", "reason", "retry_in_seconds",
        },
        "superadmin": {
            "channel_id", "channel_slug", "revoked_sessions", "target_user_id",
            "target_username", "user_id", "username",
        },
        "user": {"user_id", "username"},
    }

    # Escapes like; API route handlers call it to enforce application business rules.
    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    # Implements the safe event details operation; API route handlers call it to enforce application business rules.
    @staticmethod
    def _safe_event_details(event_type: str, payload: dict) -> dict[str, str | int | bool | None]:
        """Return a small display-only projection; never expose raw audit payloads."""
        projected: dict[str, str | int | bool | None] = {}
        prefix = event_type.split(".", 1)[0]
        allowed_keys = AdminService.SAFE_EVENT_DETAIL_KEYS_BY_PREFIX.get(prefix, set())
        # Process each `key` from `allowed_keys` to apply this step to the full collection.
        for key in allowed_keys:
            value = payload.get(key)
            # Run this conditional step only when `isinstance(value, (str, int, bool)) or (value is None and key in payl...` is true.
            if isinstance(value, (str, int, bool)) or value is None and key in payload:
                projected[key] = value[:160] if isinstance(value, str) else value

        # Run this conditional step only when `event_type.startswith('message.')` is true.
        if event_type.startswith("message."):
            message_id = payload.get("message_id") or payload.get("id")
            # Run this conditional step only when `isinstance(message_id, str)` is true.
            if isinstance(message_id, str):
                projected["message_id"] = message_id[:160]
            attachments = payload.get("attachments")
            # Run this conditional step only when `isinstance(attachments, list)` is true.
            if isinstance(attachments, list):
                projected["attachment_count"] = len(attachments)

        permissions = payload.get("admin_permissions")
        # Run this conditional step only when `prefix == 'member' and isinstance(permissions, dict)` is true.
        if prefix == "member" and isinstance(permissions, dict):
            enabled = sorted(str(key) for key, value in permissions.items() if value is True)
            projected["permissions"] = ", ".join(enabled)[:160] if enabled else "none"

        return projected

    # Implements the payload uuid operation; API route handlers call it to enforce application business rules.
    @staticmethod
    def _payload_uuid(payload: dict, *keys: str) -> UUID | None:
        # Process each `key` from `keys` to apply this step to the full collection.
        for key in keys:
            value = payload.get(key)
            # Skip the current item when `value is None` and continue processing the rest.
            if value is None:
                continue
            # Attempt this operation and handle expected failures in the exception branches below.
            try:
                return UUID(str(value))
            # Handle `(TypeError, ValueError)` here so this workflow can recover or report the failure consistently.
            except (TypeError, ValueError):
                continue
        return None

    # Resolves event channel ids; API route handlers call it to enforce application business rules.
    @staticmethod
    async def _resolve_event_channel_ids(db: AsyncSession, events: list[Event]) -> dict[UUID, UUID]:
        """Resolve display context without rewriting immutable historical audit rows."""
        resolved: dict[UUID, UUID] = {}
        message_refs: dict[UUID, list[UUID]] = {}
        outbox_refs: dict[UUID, list[UUID]] = {}
        upload_refs: dict[UUID, list[UUID]] = {}

        # Process each `event` from `events` to apply this step to the full collection.
        for event in events:
            # Run this conditional step only when `event.channel_id is not None` is true.
            if event.channel_id is not None:
                resolved[event.id] = event.channel_id
                continue

            payload = event.payload if isinstance(event.payload, dict) else {}
            direct_channel_id = AdminService._payload_uuid(payload, "channel_id")
            # Run this conditional step only when `direct_channel_id is not None` is true.
            if direct_channel_id is not None:
                resolved[event.id] = direct_channel_id
                continue

            message_id = AdminService._payload_uuid(payload, "message_id", "id")
            outbox_id = AdminService._payload_uuid(payload, "outbox_id")
            upload_id = AdminService._payload_uuid(payload, "upload_id")
            # Choose the appropriate path based on whether `message_id is not None` is true.
            if message_id is not None:
                message_refs.setdefault(message_id, []).append(event.id)
            # Choose the appropriate path based on whether `outbox_id is not None` is true.
            elif outbox_id is not None:
                outbox_refs.setdefault(outbox_id, []).append(event.id)
            # Run this conditional step only when `upload_id is not None` is true.
            elif upload_id is not None:
                upload_refs.setdefault(upload_id, []).append(event.id)

        # Run this conditional step only when `message_refs` is true.
        if message_refs:
            rows = await db.execute(select(Message.id, Message.channel_id).where(Message.id.in_(message_refs)))
            # Process each `(message_id, resolved_channel_id)` from `rows.all()` to apply this step to the full collection.
            for message_id, resolved_channel_id in rows.all():
                # Process each `event_id` from `message_refs.get(message_id, [])` to apply this step to the full collection.
                for event_id in message_refs.get(message_id, []):
                    resolved[event_id] = resolved_channel_id

        # Run this conditional step only when `outbox_refs` is true.
        if outbox_refs:
            rows = await db.execute(select(Outbox.id, Outbox.channel_id).where(Outbox.id.in_(outbox_refs)))
            # Process each `(outbox_id, resolved_channel_id)` from `rows.all()` to apply this step to the full collection.
            for outbox_id, resolved_channel_id in rows.all():
                # Process each `event_id` from `outbox_refs.get(outbox_id, [])` to apply this step to the full collection.
                for event_id in outbox_refs.get(outbox_id, []):
                    resolved[event_id] = resolved_channel_id

        # Run this conditional step only when `upload_refs` is true.
        if upload_refs:
            attachment_filters = [
                cast(Message.attachments, String).contains(str(upload_id)) for upload_id in upload_refs
            ]
            rows = await db.execute(
                select(Message.channel_id, Message.attachments)
                .where(Message.attachments.is_not(None), or_(*attachment_filters))
                .order_by(Message.created_at.desc())
            )
            upload_channels: dict[UUID, set[UUID]] = {}
            # Process each `(resolved_channel_id, attachments)` from `rows.all()` to apply this step to the full collection.
            for resolved_channel_id, attachments in rows.all():
                # Skip the current item when `not isinstance(attachments, list)` and continue processing the rest.
                if not isinstance(attachments, list):
                    continue
                # Process each `attachment` from `attachments` to apply this step to the full collection.
                for attachment in attachments:
                    # Skip the current item when `not isinstance(attachment, dict)` and continue processing the rest.
                    if not isinstance(attachment, dict):
                        continue
                    upload_id = AdminService._payload_uuid(attachment, "file_id")
                    # Run this conditional step only when `upload_id in upload_refs` is true.
                    if upload_id in upload_refs:
                        upload_channels.setdefault(upload_id, set()).add(resolved_channel_id)
            # Process each `(upload_id, candidate_channel_ids)` from `upload_channels.items()` to apply this step to the full collection.
            for upload_id, candidate_channel_ids in upload_channels.items():
                # Skip the current item when `len(candidate_channel_ids) != 1` and continue processing the rest.
                if len(candidate_channel_ids) != 1:
                    continue
                resolved_channel_id = next(iter(candidate_channel_ids))
                # Process each `event_id` from `upload_refs[upload_id]` to apply this step to the full collection.
                for event_id in upload_refs[upload_id]:
                    resolved[event_id] = resolved_channel_id

        return resolved

    # Implements the overview operation; API route handlers call it to enforce application business rules.
    @staticmethod
    async def overview(db: AsyncSession) -> AdminOverviewResponse:
        # Counts rows matching a database query; API route handlers call it to enforce application business rules.
        async def count(stmt) -> int:
            return int((await db.execute(stmt)).scalar_one() or 0)

        delivery_failure_statuses = [
            OutboxStatus.failed,
            OutboxStatus.retry_scheduled,
            OutboxStatus.dead_lettered,
        ]
        return AdminOverviewResponse(
            total_users=await count(select(func.count(User.id))),
            active_users=await count(select(func.count(User.id)).where(User.is_active.is_(True))),
            total_channels=await count(select(func.count(Channel.id))),
            active_channels=await count(select(func.count(Channel.id)).where(Channel.deleted_at.is_(None))),
            total_messages=await count(select(func.count(Message.id))),
            total_events=await count(select(func.count(Event.id))),
            delivery_failures=await count(select(func.count(Outbox.id)).where(Outbox.status.in_(delivery_failure_statuses))),
        )

    # Lists users; API route handlers call it to enforce application business rules.
    @staticmethod
    async def list_users(
        db: AsyncSession,
        *,
        q: str | None,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AdminUserItem], int]:
        filters = []
        # Run this conditional step only when `q` is true.
        if q:
            term = q.strip().removeprefix("@")
            escaped = AdminService._escape_like(term)
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    User.username.ilike(pattern, escape="\\"),
                    User.email.ilike(pattern, escape="\\"),
                    User.display_name.ilike(pattern, escape="\\"),
                )
            )
        # Run this conditional step only when `is_active is not None` is true.
        if is_active is not None:
            filters.append(User.is_active.is_(is_active))

        active_sessions = (
            select(UserSession.user_id, func.count(UserSession.id).label("active_session_count"))
            .where(UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow())
            .group_by(UserSession.user_id)
            .subquery()
        )
        stmt = select(User, func.coalesce(active_sessions.c.active_session_count, 0)).outerjoin(
            active_sessions, active_sessions.c.user_id == User.id
        )
        total_stmt = select(func.count(User.id))
        # Run this conditional step only when `filters` is true.
        if filters:
            stmt = stmt.where(and_(*filters))
            total_stmt = total_stmt.where(and_(*filters))

        ordering = [User.created_at.desc(), User.id.desc()]
        # Run this conditional step only when `q and q.strip()` is true.
        if q and q.strip():
            term = q.strip().removeprefix("@")
            escaped = AdminService._escape_like(term)
            prefix = f"{escaped}%"
            ordering = [
                case(
                    (func.lower(User.username) == term.lower(), 0),
                    (User.username.ilike(prefix, escape="\\"), 1),
                    (User.display_name.ilike(prefix, escape="\\"), 2),
                    (User.email.ilike(prefix, escape="\\"), 3),
                    else_=4,
                ),
                User.created_at.desc(),
                User.id.desc(),
            ]
        rows = (await db.execute(stmt.order_by(*ordering).offset(offset).limit(limit))).all()
        total = int((await db.execute(total_stmt)).scalar_one() or 0)
        return [
            AdminUserItem(
                id=user.id,
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                is_superadmin=user.is_superadmin,
                is_active=user.is_active,
                active_session_count=int(session_count or 0),
                created_at=user.created_at,
                updated_at=user.updated_at,
                deactivated_at=user.deactivated_at,
                deactivated_by_user_id=user.deactivated_by_user_id,
            )
            for user, session_count in rows
        ], total

    # Sets user active; API route handlers call it to enforce application business rules.
    @staticmethod
    async def set_user_active(db: AsyncSession, actor: User, target_user_id: UUID, is_active: bool) -> int:
        target = await db.get(User, target_user_id)
        # Reject the operation when `not target` to keep invalid state from progressing.
        if not target:
            raise AppError("user not found", 404, code="USER_NOT_FOUND")
        # Reject the operation when `target.id == actor.id` to keep invalid state from progressing.
        if target.id == actor.id:
            raise AppError("a superadmin cannot change their own account status", 409, code="SELF_ADMIN_ACTION")
        # Reject the operation when `target.is_superadmin` to keep invalid state from progressing.
        if target.is_superadmin:
            raise AppError("other superadmin accounts cannot be changed here", 403, code="PROTECTED_SUPERADMIN")
        # Return early when `target.is_active == is_active` because the remaining work is not applicable.
        if target.is_active == is_active:
            return 0

        target.is_active = is_active
        target.deactivated_at = None if is_active else utcnow()
        target.deactivated_by_user_id = None if is_active else actor.id
        revoked_count = 0
        # Run this conditional step only when `not is_active` is true.
        if not is_active:
            result = await db.execute(
                update(UserSession)
                .where(UserSession.user_id == target.id, UserSession.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            revoked_count = int(result.rowcount or 0)

        await log_event(
            db,
            "superadmin.user_reactivated" if is_active else "superadmin.user_deactivated",
            {
                "target_user_id": str(target.id),
                "target_username": target.username,
                "revoked_sessions": revoked_count,
            },
            actor_user_id=actor.id,
        )
        await db.commit()
        return revoked_count

    # Revokes user sessions; API route handlers call it to enforce application business rules.
    @staticmethod
    async def revoke_user_sessions(db: AsyncSession, actor: User, target_user_id: UUID) -> int:
        target = await db.get(User, target_user_id)
        # Reject the operation when `not target` to keep invalid state from progressing.
        if not target:
            raise AppError("user not found", 404, code="USER_NOT_FOUND")
        # Reject the operation when `target.is_superadmin and target.id != actor.id` to keep invalid state from progressing.
        if target.is_superadmin and target.id != actor.id:
            raise AppError("other superadmin sessions cannot be revoked here", 403, code="PROTECTED_SUPERADMIN")
        result = await db.execute(
            update(UserSession)
            .where(UserSession.user_id == target.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        count = int(result.rowcount or 0)
        await log_event(
            db,
            "superadmin.user_sessions_revoked",
            {"target_user_id": str(target.id), "target_username": target.username, "revoked_sessions": count},
            actor_user_id=actor.id,
        )
        await db.commit()
        return count

    # Lists channels; API route handlers call it to enforce application business rules.
    @staticmethod
    async def list_channels(
        db: AsyncSession,
        *,
        q: str | None,
        include_deleted: bool,
        state: str | None,
        visibility: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AdminChannelItem], int]:
        member_counts = (
            select(ChannelMembership.channel_id, func.count(ChannelMembership.user_id).label("member_count"))
            .where(ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]))
            .group_by(ChannelMembership.channel_id)
            .subquery()
        )
        message_counts = (
            select(Message.channel_id, func.count(Message.id).label("message_count"))
            .group_by(Message.channel_id)
            .subquery()
        )
        filters = []
        # Choose the appropriate path based on whether `state == 'active' or (not include_deleted and state is None)` is true.
        if state == "active" or (not include_deleted and state is None):
            filters.append(Channel.deleted_at.is_(None))
        # Run this conditional step only when `state == 'suspended'` is true.
        elif state == "suspended":
            filters.append(Channel.deleted_at.is_not(None))
        # Run this conditional step only when `visibility` is true.
        if visibility:
            filters.append(Channel.visibility == visibility)
        # Run this conditional step only when `q` is true.
        if q:
            term = q.strip()
            identifier_term = term[1:] if term.startswith(("#", "@")) else term
            escaped = AdminService._escape_like(term)
            identifier_escaped = AdminService._escape_like(identifier_term)
            pattern = f"%{escaped}%"
            identifier_pattern = f"%{identifier_escaped}%"
            filters.append(
                or_(
                    Channel.name.ilike(pattern, escape="\\"),
                    Channel.channel_slug.ilike(identifier_pattern, escape="\\"),
                    User.username.ilike(identifier_pattern, escape="\\"),
                )
            )

        stmt = (
            select(
                Channel,
                User.username,
                func.coalesce(member_counts.c.member_count, 0),
                func.coalesce(message_counts.c.message_count, 0),
            )
            .join(User, User.id == Channel.owner_user_id)
            .outerjoin(member_counts, member_counts.c.channel_id == Channel.id)
            .outerjoin(message_counts, message_counts.c.channel_id == Channel.id)
        )
        total_stmt = select(func.count(Channel.id)).join(User, User.id == Channel.owner_user_id)
        # Run this conditional step only when `filters` is true.
        if filters:
            stmt = stmt.where(and_(*filters))
            total_stmt = total_stmt.where(and_(*filters))
        ordering = [Channel.created_at.desc(), Channel.id.desc()]
        # Run this conditional step only when `q and q.strip()` is true.
        if q and q.strip():
            term = q.strip()
            identifier_term = term[1:] if term.startswith(("#", "@")) else term
            escaped = AdminService._escape_like(term)
            identifier_escaped = AdminService._escape_like(identifier_term)
            prefix = f"{escaped}%"
            identifier_prefix = f"{identifier_escaped}%"
            ordering = [
                case(
                    (func.lower(Channel.channel_slug) == identifier_term.lower(), 0),
                    (func.lower(Channel.name) == term.lower(), 1),
                    (Channel.channel_slug.ilike(identifier_prefix, escape="\\"), 2),
                    (Channel.name.ilike(prefix, escape="\\"), 3),
                    (User.username.ilike(identifier_prefix, escape="\\"), 4),
                    else_=5,
                ),
                Channel.created_at.desc(),
                Channel.id.desc(),
            ]
        rows = (await db.execute(stmt.order_by(*ordering).offset(offset).limit(limit))).all()
        total = int((await db.execute(total_stmt)).scalar_one() or 0)
        return [
            AdminChannelItem(
                id=channel.id,
                name=channel.name,
                channel_slug=channel.channel_slug,
                owner_user_id=channel.owner_user_id,
                owner_username=owner_username,
                visibility=channel.visibility.value,
                join_mode=channel.join_mode.value,
                member_count=int(member_count or 0),
                message_count=int(message_count or 0),
                created_at=channel.created_at,
                updated_at=channel.updated_at,
                deleted_at=channel.deleted_at,
            )
            for channel, owner_username, member_count, message_count in rows
        ], total

    # Lists events; API route handlers call it to enforce application business rules.
    @staticmethod
    async def list_events(
        db: AsyncSession,
        *,
        q: str | None,
        event_type: str | None,
        category: str | None,
        channel_id: UUID | None,
        actor_user_id: UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AdminEventItem], int]:
        filters = []
        # Run this conditional step only when `event_type` is true.
        if event_type:
            filters.append(func.lower(Event.event_type) == event_type.strip().lower())
        # Run this conditional step only when `category` is true.
        if category:
            prefixes = AdminService.EVENT_CATEGORY_PREFIXES.get(category, ())
            filters.append(or_(*(Event.event_type.startswith(prefix) for prefix in prefixes)))
        # Run this conditional step only when `channel_id` is true.
        if channel_id:
            filters.append(Event.channel_id == channel_id)
        # Run this conditional step only when `actor_user_id` is true.
        if actor_user_id:
            filters.append(Event.actor_user_id == actor_user_id)
        # Run this conditional step only when `q` is true.
        if q:
            term = q.strip()
            identifier_term = term[1:] if term.startswith(("#", "@")) else term
            escaped = AdminService._escape_like(term)
            identifier_escaped = AdminService._escape_like(identifier_term)
            pattern = f"%{escaped}%"
            identifier_pattern = f"%{identifier_escaped}%"
            filters.append(
                or_(
                    Event.event_type.ilike(pattern, escape="\\"),
                    User.username.ilike(identifier_pattern, escape="\\"),
                    Channel.name.ilike(identifier_pattern, escape="\\"),
                )
            )

        stmt = (
            select(Event, User.username, Channel.name, Channel.channel_slug)
            .outerjoin(User, User.id == Event.actor_user_id)
            .outerjoin(Channel, Channel.id == Event.channel_id)
        )
        total_stmt = (
            select(func.count(Event.id))
            .outerjoin(User, User.id == Event.actor_user_id)
            .outerjoin(Channel, Channel.id == Event.channel_id)
        )
        # Run this conditional step only when `filters` is true.
        if filters:
            stmt = stmt.where(and_(*filters))
            total_stmt = total_stmt.where(and_(*filters))
        ordering = [Event.created_at.desc(), Event.id.desc()]
        # Run this conditional step only when `q and q.strip()` is true.
        if q and q.strip():
            term = q.strip()
            identifier_term = term[1:] if term.startswith(("#", "@")) else term
            escaped = AdminService._escape_like(term)
            identifier_escaped = AdminService._escape_like(identifier_term)
            prefix = f"{escaped}%"
            identifier_prefix = f"{identifier_escaped}%"
            ordering = [
                case(
                    (func.lower(Event.event_type) == term.lower(), 0),
                    (Event.event_type.ilike(prefix, escape="\\"), 1),
                    (User.username.ilike(identifier_prefix, escape="\\"), 2),
                    (Channel.name.ilike(identifier_prefix, escape="\\"), 3),
                    else_=4,
                ),
                Event.created_at.desc(),
                Event.id.desc(),
            ]
        rows = (await db.execute(stmt.order_by(*ordering).offset(offset).limit(limit))).all()
        total = int((await db.execute(total_stmt)).scalar_one() or 0)
        resolved_channel_ids = await AdminService._resolve_event_channel_ids(db, [row[0] for row in rows])
        resolved_channel_context: dict[UUID, tuple[str, str]] = {}
        # Run this conditional step only when `resolved_channel_ids` is true.
        if resolved_channel_ids:
            channel_rows = await db.execute(
                select(Channel.id, Channel.name, Channel.channel_slug).where(
                    Channel.id.in_(set(resolved_channel_ids.values()))
                )
            )
            resolved_channel_context = {
                resolved_channel_id: (resolved_name, resolved_slug)
                for resolved_channel_id, resolved_name, resolved_slug in channel_rows.all()
            }
        return [
            AdminEventItem(
                id=event.id,
                channel_id=resolved_channel_ids.get(event.id),
                channel_name=(
                    resolved_channel_context.get(resolved_channel_ids.get(event.id), (channel_name, channel_slug))[0]
                ),
                channel_slug=(
                    resolved_channel_context.get(resolved_channel_ids.get(event.id), (channel_name, channel_slug))[1]
                ),
                actor_user_id=event.actor_user_id,
                actor_username=actor_username,
                event_type=event.event_type,
                details=AdminService._safe_event_details(event.event_type, event.payload),
                created_at=event.created_at,
                event_hash=event.event_hash,
                integrity_scope=event.integrity_scope,
            )
            for event, actor_username, channel_name, channel_slug in rows
        ], total

    # Restores channel; API route handlers call it to enforce application business rules.
    @staticmethod
    async def restore_channel(db: AsyncSession, amqp: aio_pika.RobustConnection, actor: User, channel_id: UUID) -> None:
        channel = await db.get(Channel, channel_id)
        # Reject the operation when `not channel` to keep invalid state from progressing.
        if not channel:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        # Reject the operation when `channel.deleted_at is None` to keep invalid state from progressing.
        if channel.deleted_at is None:
            raise AppError("channel is already active", 409, code="CONFLICT")

        channel.deleted_at = None
        await log_event(
            db,
            "superadmin.channel_restored",
            {"channel_id": str(channel.id), "channel_slug": channel.channel_slug},
            channel_id=channel.id,
            actor_user_id=actor.id,
        )
        await enqueue_channel_event_outbox(
            db,
            channel.id,
            channel.id,
            "channel_restored",
            {"type": "channel_restored", "channel_id": str(channel.id)},
        )
        await db.commit()

        usernames = (
            await db.execute(
                select(User.username)
                .join(ChannelMembership, ChannelMembership.user_id == User.id)
                .where(
                    ChannelMembership.channel_id == channel.id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                )
            )
        ).scalars().all()
        amqp_channel = await amqp.channel()
        # Protect this operation so its cleanup step runs even if processing fails.
        try:
            # Process each `username` from `usernames` to apply this step to the full collection.
            for username in usernames:
                await bind_user_channel(amqp_channel, username, channel.channel_slug)
        # Always run this cleanup path after the guarded operation finishes.
        finally:
            await amqp_channel.close()
