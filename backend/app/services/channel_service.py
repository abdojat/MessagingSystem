import uuid
import base64
import re
from datetime import datetime, timedelta
from uuid import UUID

import aio_pika
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.identifiers import SAFE_IDENTIFIER_MAX_LENGTH, normalize_channel_slug, normalize_username
from app.core.encryption import decrypt_json_payload, decrypt_message
from app.core.utils import make_invite_token, sha256_hex, utcnow
from app.db.models import (
    Channel,
    ChannelCounter,
    ChannelInvite,
    ChannelJoinMode,
    ChannelMembership,
    ChannelVisibility,
    Event,
    MembershipRole,
    Message,
    UserChannelState,
    User,
)
from app.mq.publisher import bind_user_channel, unbind_user_channel
from app.schemas.channels import AdminPermissionsUpdateRequest, ChannelCreateRequest, ChannelPatchRequest, InviteRequest, JoinRequest
from app.services.event_service import log_event
from app.services.outbox_service import enqueue_channel_event_outbox, enqueue_user_event_outbox
from app.services.rbac import (
    build_permissions as build_rbac_permissions,
    can_approve,
    can_demote,
    can_invite,
    can_promote,
    can_remove,
    normalize_admin_permissions,
)

MEMBERSHIP_CURSOR_SEP = "|"
ALLOWED_MEMBER_ROLES = {MembershipRole.owner, MembershipRole.admin, MembershipRole.member, MembershipRole.pending}
ROLE_WEIGHT = {
    MembershipRole.owner: 0,
    MembershipRole.admin: 1,
    MembershipRole.member: 2,
    MembershipRole.pending: 3,
}


class ChannelService:
    @staticmethod
    def _slugify(raw: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
        normalized = re.sub(r"-{2,}", "-", normalized)
        if not normalized:
            return "channel"
        if len(normalized) < 3:
            normalized = f"{normalized}-channel"
        normalized = normalized[:SAFE_IDENTIFIER_MAX_LENGTH].strip("-")
        return normalized or "channel"

    @staticmethod
    async def _next_available_slug(db: AsyncSession, base_slug: str) -> str:
        base = base_slug[:SAFE_IDENTIFIER_MAX_LENGTH] or "channel"
        candidate = base
        suffix = 2
        while True:
            exists_row = await db.execute(select(Channel.id).where(Channel.channel_slug == candidate).limit(1))
            if exists_row.scalar_one_or_none() is None:
                return candidate
            suffix_token = f"-{suffix}"
            candidate = f"{base[: max(1, SAFE_IDENTIFIER_MAX_LENGTH - len(suffix_token))]}{suffix_token}"
            suffix += 1

    @staticmethod
    def _decrypted_message_payload(message: Message) -> tuple[str | None, dict | None]:
        if message.deleted_at is not None:
            return None, None
        if message.content_type.value == "text":
            return decrypt_message(message.content_text) if message.content_text is not None else None, None
        if message.content_type.value == "json":
            return None, decrypt_json_payload(message.content_json)
        raise AppError("unsupported content type", 500, code="DECRYPTION_FAILED")

    @staticmethod
    async def get_membership(db: AsyncSession, channel_id: UUID, user_id: UUID) -> ChannelMembership | None:
        return await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})

    @staticmethod
    def membership_permissions(membership: ChannelMembership | None) -> dict[str, bool]:
        if membership is None:
            return ChannelService.build_permissions(None)
        return ChannelService.build_permissions(membership.role, membership.admin_permissions)

    @staticmethod
    def build_permissions(
        role: MembershipRole | None,
        admin_permissions: dict | None = None,
        channel: Channel | None = None,
    ) -> dict[str, bool]:
        _ = channel
        return build_rbac_permissions(role, admin_permissions)

    @staticmethod
    def build_channel_payload(channel: Channel, role: MembershipRole | None, admin_permissions: dict | None = None) -> dict:
        my_role: MembershipRole | str = role if role is not None else "none"
        return {
            "id": channel.id,
            "owner_user_id": channel.owner_user_id,
            "name": channel.name,
            "channel_slug": channel.channel_slug,
            "description": channel.description,
            "avatar_url": channel.avatar_url,
            "visibility": channel.visibility,
            "join_mode": channel.join_mode,
            "created_at": channel.created_at,
            "updated_at": channel.updated_at,
            "deleted_at": channel.deleted_at,
            "member_count": 0,
            "pending_count": 0,
            "last_message": None,
            "last_message_at": None,
            "my_last_seen_seq_id": None,
            "unread_count": 0,
            "my_role": my_role,
            "permissions": ChannelService.build_permissions(role, admin_permissions, channel),
        }

    @staticmethod
    def compute_my_role_and_permissions(
        channel: Channel,
        role: MembershipRole | None,
        admin_permissions: dict | None = None,
    ) -> tuple[MembershipRole | str, dict[str, bool]]:
        my_role: MembershipRole | str = role if role is not None else "none"
        return my_role, ChannelService.build_permissions(role, admin_permissions, channel)

    @staticmethod
    async def create_channel(db: AsyncSession, owner_user_id: UUID, req: ChannelCreateRequest, amqp: aio_pika.RobustConnection) -> Channel:
        provided_slug = normalize_channel_slug(req.channel_slug) if req.channel_slug else ""
        slug_base = provided_slug if provided_slug else ChannelService._slugify(req.name)
        slug = await ChannelService._next_available_slug(db, slug_base)
        channel = Channel(
            owner_user_id=owner_user_id,
            name=req.name,
            channel_slug=slug,
            description=req.description,
            avatar_url=req.avatar_url,
            visibility=req.visibility,
            join_mode=req.join_mode,
        )
        db.add(channel)
        await db.flush()

        db.add(ChannelCounter(channel_id=channel.id, next_seq=0))
        db.add(
            ChannelMembership(
                channel_id=channel.id,
                user_id=owner_user_id,
                role=MembershipRole.owner,
                created_by_user_id=owner_user_id,
                approved_at=utcnow(),
            )
        )
        await log_event(
            db,
            "channel.created",
            {"channel_id": str(channel.id), "name": channel.name},
            channel_id=channel.id,
            actor_user_id=owner_user_id,
        )
        if slug != slug_base:
            await log_event(
                db,
                "channel.slug_collision_resolved",
                {"requested_slug": slug_base, "resolved_slug": slug},
                channel_id=channel.id,
                actor_user_id=owner_user_id,
            )
        await db.commit()
        await db.refresh(channel)

        owner = await db.get(User, owner_user_id)
        if owner is None:
            raise AppError("owner not found", 404, code="USER_NOT_FOUND")

        amqp_channel = await amqp.channel()
        try:
            await bind_user_channel(amqp_channel, owner.username, channel.channel_slug)
        finally:
            await amqp_channel.close()
        return channel

    @staticmethod
    async def list_channels(
        db: AsyncSession,
        user_id: UUID,
        cursor: str | None,
        limit: int,
        q: str | None = None,
        visibility: ChannelVisibility | None = None,
        scope: str = "my",
    ) -> tuple[list[dict], str | None, bool]:
        last_message_sq = (
            select(Message.channel_id, func.max(Message.created_at).label("last_message_at"))
            .where(Message.deleted_at.is_(None))
            .group_by(Message.channel_id)
            .subquery()
        )
        stmt = (
            select(Channel, ChannelMembership.role, ChannelMembership.admin_permissions, last_message_sq.c.last_message_at)
            .outerjoin(
                ChannelMembership,
                and_(ChannelMembership.channel_id == Channel.id, ChannelMembership.user_id == user_id),
            )
            .outerjoin(last_message_sq, last_message_sq.c.channel_id == Channel.id)
            .where(Channel.deleted_at.is_(None))
            .order_by(
                last_message_sq.c.last_message_at.desc().nulls_last(),
                Channel.created_at.desc(),
                Channel.id.desc(),
            )
        )
        if scope == "my":
            stmt = stmt.where(ChannelMembership.user_id.is_not(None))
        elif scope == "discover":
            stmt = stmt.where(Channel.visibility == ChannelVisibility.public).where(ChannelMembership.user_id.is_(None))
        else:
            raise AppError("scope must be my or discover", 400, code="VALIDATION_ERROR")
        if visibility is not None:
            stmt = stmt.where(Channel.visibility == visibility)
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(Channel.name.ilike(pattern))
        if cursor:
            cursor_last_message_at, cursor_created_at, cursor_channel_id = ChannelService._decode_channel_cursor(cursor)
            if cursor_last_message_at is None:
                stmt = stmt.where(last_message_sq.c.last_message_at.is_(None)).where(
                    or_(
                        Channel.created_at < cursor_created_at,
                        and_(Channel.created_at == cursor_created_at, Channel.id < cursor_channel_id),
                    )
                )
            else:
                stmt = stmt.where(
                    or_(
                        and_(
                            last_message_sq.c.last_message_at.is_not(None),
                            last_message_sq.c.last_message_at < cursor_last_message_at,
                        ),
                        and_(
                            last_message_sq.c.last_message_at == cursor_last_message_at,
                            or_(
                                Channel.created_at < cursor_created_at,
                                and_(Channel.created_at == cursor_created_at, Channel.id < cursor_channel_id),
                            ),
                        ),
                        last_message_sq.c.last_message_at.is_(None),
                    )
                )
        rows = await db.execute(stmt.limit(limit + 1))
        all_rows = rows.all()
        has_more = len(all_rows) > limit
        page = all_rows[:limit]
        items = await ChannelService._enrich_channel_payload_batch(
            db,
            [(channel, role, admin_permissions) for channel, role, admin_permissions, _ in page],
            user_id,
        )
        next_cursor = None
        if has_more and page:
            last_channel, _, _, last_message_at = page[-1]
            next_cursor = ChannelService._encode_channel_cursor(
                last_message_at,
                last_channel.created_at,
                last_channel.id,
            )
        return items, next_cursor, has_more

    @staticmethod
    async def _enrich_channel_payload_batch(
        db: AsyncSession,
        channel_rows: list[tuple[Channel, MembershipRole | None, dict | None]],
        user_id: UUID,
    ) -> list[dict]:
        if not channel_rows:
            return []
        channels_by_id = {channel.id: channel for channel, _, _ in channel_rows}
        roles_by_id = {channel.id: role for channel, role, _ in channel_rows}
        admin_permissions_by_id = {channel.id: admin_permissions for channel, _, admin_permissions in channel_rows}
        channel_ids = list(channels_by_id.keys())

        payloads = {
            channel_id: ChannelService.build_channel_payload(
                channels_by_id[channel_id],
                roles_by_id[channel_id],
                admin_permissions_by_id[channel_id],
            )
            for channel_id in channel_ids
        }

        member_rows = await db.execute(
            select(ChannelMembership.channel_id, func.count(ChannelMembership.user_id))
            .where(
                ChannelMembership.channel_id.in_(channel_ids),
                ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
            )
            .group_by(ChannelMembership.channel_id)
        )
        for channel_id, count in member_rows.all():
            payloads[channel_id]["member_count"] = int(count or 0)

        pending_rows = await db.execute(
            select(ChannelMembership.channel_id, func.count(ChannelMembership.user_id))
            .where(
                ChannelMembership.channel_id.in_(channel_ids),
                ChannelMembership.role == MembershipRole.pending,
            )
            .group_by(ChannelMembership.channel_id)
        )
        pending_map = {cid: int(count or 0) for cid, count in pending_rows.all()}
        for channel_id in channel_ids:
            role = roles_by_id.get(channel_id)
            permissions = ChannelService.build_permissions(role, admin_permissions_by_id.get(channel_id))
            payloads[channel_id]["pending_count"] = pending_map.get(channel_id, 0) if permissions["can_manage_members"] else 0

        max_seq_sq = (
            select(Message.channel_id, func.max(Message.seq_id).label("max_seq"))
            .where(Message.channel_id.in_(channel_ids), Message.deleted_at.is_(None))
            .group_by(Message.channel_id)
            .subquery()
        )
        last_rows = await db.execute(
            select(Message)
            .join(
                max_seq_sq,
                and_(Message.channel_id == max_seq_sq.c.channel_id, Message.seq_id == max_seq_sq.c.max_seq),
            )
            .order_by(Message.channel_id.asc())
        )
        last_messages = last_rows.scalars().all()
        sender_ids = {message.sender_user_id for message in last_messages}
        sender_profiles: dict[UUID, User] = {}
        if sender_ids:
            sender_rows = await db.execute(select(User).where(User.id.in_(sender_ids)))
            sender_profiles = {sender.id: sender for sender in sender_rows.scalars().all()}

        for last_message in last_messages:
            sender = sender_profiles.get(last_message.sender_user_id)
            content_text, content_json = ChannelService._decrypted_message_payload(last_message)
            payloads[last_message.channel_id]["last_message"] = {
                "id": last_message.id,
                "channel_id": last_message.channel_id,
                "sender_user_id": last_message.sender_user_id,
                "sender_username": sender.username if sender else None,
                "sender_display_name": sender.display_name if sender else None,
                "sender_avatar_url": sender.avatar_url if sender else None,
                "seq_id": last_message.seq_id,
                "content_type": last_message.content_type.value,
                "content_text": content_text,
                "content_json": content_json,
                "reply_to_message_id": last_message.reply_to_message_id,
                "reply_to_seq_id": last_message.reply_to_seq_id,
                "attachments": last_message.attachments,
                "is_pinned": last_message.is_pinned,
                "client_msg_id": last_message.client_msg_id,
                "created_at": last_message.created_at,
                "updated_at": last_message.updated_at,
                "edited_at": last_message.edited_at,
                "deleted_at": last_message.deleted_at,
                "reactions_summary": {"counts": {}, "my_reaction": []},
            }
            payloads[last_message.channel_id]["last_message_at"] = last_message.created_at

        state_rows = await db.execute(
            select(UserChannelState.channel_id, UserChannelState.last_seen_seq_id)
            .where(UserChannelState.user_id == user_id, UserChannelState.channel_id.in_(channel_ids))
        )
        seen_map = {cid: int(seq or 0) for cid, seq in state_rows.all()}
        for channel_id in channel_ids:
            payloads[channel_id]["my_last_seen_seq_id"] = seen_map.get(channel_id)

        state_sq = (
            select(UserChannelState.channel_id, UserChannelState.last_seen_seq_id)
            .where(UserChannelState.user_id == user_id, UserChannelState.channel_id.in_(channel_ids))
            .subquery()
        )
        unread_rows = await db.execute(
            select(Message.channel_id, func.count(Message.id))
            .outerjoin(state_sq, state_sq.c.channel_id == Message.channel_id)
            .where(
                Message.channel_id.in_(channel_ids),
                Message.deleted_at.is_(None),
                Message.seq_id > func.coalesce(state_sq.c.last_seen_seq_id, 0),
                Message.reply_to_message_id.is_(None),
                Message.reply_to_seq_id.is_(None),
            )
            .group_by(Message.channel_id)
        )
        unread_map = {cid: int(count or 0) for cid, count in unread_rows.all()}
        for channel_id in channel_ids:
            payloads[channel_id]["unread_count"] = unread_map.get(channel_id, 0)

        return [payloads[channel.id] for channel, _, _ in channel_rows]

    @staticmethod
    async def get_channel_or_404(db: AsyncSession, channel_id: UUID) -> Channel:
        channel = await db.get(Channel, channel_id)
        if not channel or channel.deleted_at is not None:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        return channel

    @staticmethod
    async def _get_channel_with_role(
        db: AsyncSession,
        channel_id: UUID,
        user_id: UUID,
    ) -> tuple[Channel | None, MembershipRole | None, dict | None]:
        row = await db.execute(
            select(Channel, ChannelMembership.role, ChannelMembership.admin_permissions)
            .outerjoin(
                ChannelMembership,
                and_(ChannelMembership.channel_id == Channel.id, ChannelMembership.user_id == user_id),
            )
            .where(Channel.id == channel_id)
            .where(Channel.deleted_at.is_(None))
        )
        data = row.first()
        if not data:
            return None, None, None
        return data[0], data[1], data[2]

    @staticmethod
    async def get_channel_view(db: AsyncSession, channel_id: UUID, user_id: UUID) -> dict:
        channel, role, admin_permissions = await ChannelService._get_channel_with_role(db, channel_id, user_id)
        if not channel:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        if channel.visibility == ChannelVisibility.private and role is None:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        return await ChannelService._enrich_channel_payload(db, channel, user_id, role, admin_permissions)

    @staticmethod
    async def update_channel(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        req: ChannelPatchRequest,
        amqp: aio_pika.RobustConnection,
    ) -> Channel:
        channel = await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, actor_user_id)
        if not ChannelService.membership_permissions(membership)["can_edit_channel"]:
            raise AppError("forbidden", 403, code="FORBIDDEN")

        old_channel_slug = channel.channel_slug
        provided_fields = req.model_fields_set
        if req.name is not None:
            channel.name = req.name
        if req.channel_slug is not None:
            channel.channel_slug = req.channel_slug
        if "description" in provided_fields:
            channel.description = req.description
        if "avatar_url" in provided_fields:
            channel.avatar_url = req.avatar_url
        if req.visibility is not None:
            channel.visibility = req.visibility
        if req.join_mode is not None:
            channel.join_mode = req.join_mode

        await log_event(
            db,
            "channel.updated",
            {
                "channel_id": str(channel_id),
                "name": channel.name,
                "channel_slug": channel.channel_slug,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "visibility": channel.visibility.value,
                "join_mode": channel.join_mode.value,
            },
            channel_id=channel_id,
            actor_user_id=actor_user_id,
        )
        await enqueue_channel_event_outbox(
            db,
            uuid.uuid4(),
            channel_id,
            "channel_updated",
            {
                "type": "channel_updated",
                "channel_id": str(channel_id),
                "patch": {
                    "name": channel.name,
                    "channel_slug": channel.channel_slug,
                    "description": channel.description,
                    "avatar_url": channel.avatar_url,
                    "visibility": channel.visibility.value,
                    "join_mode": channel.join_mode.value,
                },
            },
        )
        await db.commit()
        await db.refresh(channel)

        if old_channel_slug != channel.channel_slug:
            member_rows = await db.execute(
                select(User.username)
                .join(ChannelMembership, ChannelMembership.user_id == User.id)
                .where(
                    ChannelMembership.channel_id == channel_id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                )
            )
            usernames = list(member_rows.scalars().all())
            amqp_channel = await amqp.channel()
            try:
                for username in usernames:
                    await unbind_user_channel(amqp_channel, username, old_channel_slug)
                    await bind_user_channel(amqp_channel, username, channel.channel_slug)
            finally:
                await amqp_channel.close()
        return channel

    @staticmethod
    async def delete_channel(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        amqp: aio_pika.RobustConnection,
    ) -> None:
        channel = await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, actor_user_id)
        if not membership or membership.role != MembershipRole.owner:
            raise AppError("forbidden", 403, code="FORBIDDEN")

        channel.deleted_at = utcnow()
        await log_event(
            db,
            "channel.deleted",
            {"channel_id": str(channel_id)},
            channel_id=channel_id,
            actor_user_id=actor_user_id,
        )
        await enqueue_channel_event_outbox(
            db,
            uuid.uuid4(),
            channel_id,
            "channel_deleted",
            {"type": "channel_deleted", "channel_id": str(channel_id)},
        )
        await db.commit()

        amqp_channel = await amqp.channel()
        try:
            rows = await db.execute(
                select(User.username)
                .join(ChannelMembership, ChannelMembership.user_id == User.id)
                .where(
                    ChannelMembership.channel_id == channel_id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                )
            )
            for username in rows.scalars().all():
                await unbind_user_channel(amqp_channel, username, channel.channel_slug)
        finally:
            await amqp_channel.close()

    @staticmethod
    async def join_channel(
        db: AsyncSession,
        amqp: aio_pika.RobustConnection,
        channel_id: UUID,
        user_id: UUID,
        req: JoinRequest,
    ) -> tuple[str, ChannelMembership | None, str]:
        channel = await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, user_id)
        if membership:
            return ("already_member", membership, "user already has membership")

        if channel.join_mode == ChannelJoinMode.invite_only:
            if not req.invite_token:
                return ("requires_invite", None, "invite token required for invite_only channels")
            invite = await ChannelService._validate_invite(db, channel_id, req.invite_token, user_id)
            invite.accepted_at = utcnow()
            membership = ChannelMembership(
                channel_id=channel_id,
                user_id=user_id,
                role=MembershipRole.member,
                approved_at=utcnow(),
                created_by_user_id=invite.created_by_user_id,
                invited_by_user_id=invite.created_by_user_id,
            )
            status = "joined"
            message = "joined via invite token"
        elif channel.join_mode == ChannelJoinMode.approval_required:
            membership = ChannelMembership(
                channel_id=channel_id,
                user_id=user_id,
                role=MembershipRole.pending,
                created_by_user_id=user_id,
            )
            status = "pending"
            message = "join request pending approval"
        elif channel.join_mode == ChannelJoinMode.open:
            membership = ChannelMembership(
                channel_id=channel_id,
                user_id=user_id,
                role=MembershipRole.member,
                approved_at=utcnow(),
                created_by_user_id=user_id,
            )
            status = "joined"
            message = "joined channel"
        else:
            raise AppError("join not allowed", 403, code="FORBIDDEN")

        db.add(membership)
        await log_event(
            db,
            "membership.joined",
            {"channel_id": str(channel_id), "user_id": str(user_id), "role": membership.role.value},
            channel_id=channel_id,
            actor_user_id=user_id,
        )
        await ChannelService._enqueue_membership_update(
            db,
            channel_id,
            user_id,
            membership.role,
            reason="join",
        )
        await db.commit()

        if membership.role in {MembershipRole.owner, MembershipRole.admin, MembershipRole.member}:
            username = await ChannelService._require_username(db, user_id)
            amqp_channel = await amqp.channel()
            try:
                await bind_user_channel(amqp_channel, username, channel.channel_slug)
            finally:
                await amqp_channel.close()
        return (status, membership, message)

    @staticmethod
    async def create_invite(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        req: InviteRequest,
    ) -> tuple[ChannelInvite, str]:
        await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, actor_user_id)
        if not membership or not can_invite(membership.role, membership.admin_permissions):
            raise AppError("forbidden", 403, code="FORBIDDEN")

        token = make_invite_token()
        token_hash = sha256_hex(token)
        invite = ChannelInvite(
            channel_id=channel_id,
            invited_user_id=req.invited_user_id,
            invited_email=req.invited_email,
            token_hash=token_hash,
            token_mask_prefix=token[:4],
            token_mask_suffix=token[-4:],
            created_by_user_id=actor_user_id,
            expires_at=utcnow() + timedelta(hours=req.expires_in_hours),
        )
        db.add(invite)
        await log_event(
            db,
            "invite.created",
            {"channel_id": str(channel_id), "invite_id": str(invite.id)},
            channel_id=channel_id,
            actor_user_id=actor_user_id,
        )
        await db.commit()
        await db.refresh(invite)
        return invite, token

    @staticmethod
    async def list_invites(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        cursor: str | None = None,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[ChannelInvite], str | None, bool]:
        await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, actor_user_id)
        if not membership or not can_invite(membership.role, membership.admin_permissions):
            raise AppError("forbidden", 403, code="FORBIDDEN")
        stmt = select(ChannelInvite).where(ChannelInvite.channel_id == channel_id)
        now = utcnow()
        if status == "active":
            stmt = stmt.where(ChannelInvite.revoked_at.is_(None), ChannelInvite.accepted_at.is_(None), ChannelInvite.expires_at >= now)
        elif status == "revoked":
            stmt = stmt.where(ChannelInvite.revoked_at.is_not(None))
        elif status == "accepted":
            stmt = stmt.where(ChannelInvite.accepted_at.is_not(None))
        elif status == "expired":
            stmt = stmt.where(ChannelInvite.expires_at < now, ChannelInvite.revoked_at.is_(None), ChannelInvite.accepted_at.is_(None))
        elif status is not None:
            raise AppError("invalid invite status", 400, code="VALIDATION_ERROR")
        stmt = stmt.order_by(ChannelInvite.created_at.desc(), ChannelInvite.id.desc())
        if cursor:
            cursor_created_at, cursor_invite_id = ChannelService._decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    ChannelInvite.created_at < cursor_created_at,
                    and_(ChannelInvite.created_at == cursor_created_at, ChannelInvite.id < cursor_invite_id),
                )
            )
        rows = await db.execute(stmt.limit(limit + 1))
        values = list(rows.scalars().all())
        has_more = len(values) > limit
        page = values[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = ChannelService._encode_cursor(last.created_at, last.id)
        return page, next_cursor, has_more

    @staticmethod
    async def revoke_invite(db: AsyncSession, channel_id: UUID, invite_id: UUID, actor_user_id: UUID) -> ChannelInvite:
        await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, actor_user_id)
        if not membership or not can_invite(membership.role, membership.admin_permissions):
            raise AppError("forbidden", 403, code="FORBIDDEN")
        invite = await db.get(ChannelInvite, invite_id)
        if not invite or invite.channel_id != channel_id:
            raise AppError("invite not found", 404, code="INVITE_INVALID")
        if invite.revoked_at is None:
            invite.revoked_at = utcnow()
            await log_event(
                db,
                "invite.revoked",
                {"channel_id": str(channel_id), "invite_id": str(invite_id)},
                channel_id=channel_id,
                actor_user_id=actor_user_id,
            )
            await db.commit()
            await db.refresh(invite)
        return invite

    @staticmethod
    async def get_invite_preview(db: AsyncSession, token: str) -> dict:
        token_hash = sha256_hex(token)
        row = await db.execute(
            select(ChannelInvite, Channel)
            .join(Channel, Channel.id == ChannelInvite.channel_id)
            .where(ChannelInvite.token_hash == token_hash)
        )
        data = row.first()
        if not data:
            return {"is_valid": False, "reason": "not_found"}
        invite, channel = data
        if channel.deleted_at is not None:
            return {"is_valid": False, "reason": "channel_deleted"}
        now = utcnow()
        if invite.revoked_at is not None:
            return {"is_valid": False, "reason": "revoked"}
        if invite.accepted_at is not None:
            return {"is_valid": False, "reason": "accepted"}
        if invite.expires_at < now:
            return {"is_valid": False, "reason": "expired"}
        return {
            "is_valid": True,
            "channel": {"id": channel.id, "name": channel.name, "visibility": channel.visibility},
            "expires_at": invite.expires_at,
            "invited_email": invite.invited_email,
            "invited_user_id": invite.invited_user_id,
        }

    @staticmethod
    async def accept_invite(
        db: AsyncSession,
        amqp: aio_pika.RobustConnection,
        token: str,
        user_id: UUID,
    ) -> ChannelMembership:
        token_hash = sha256_hex(token)
        user = await db.get(User, user_id)
        if not user:
            raise AppError("user not found", 404)
        result = await db.execute(
            select(ChannelInvite, Channel)
            .join(Channel, Channel.id == ChannelInvite.channel_id)
            .where(ChannelInvite.token_hash == token_hash)
        )
        data = result.first()
        if not data:
            raise AppError("invite not found", 404, code="INVITE_INVALID")
        invite, channel = data
        if channel.deleted_at is not None:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        if invite.revoked_at:
            raise AppError("invite revoked", 400, code="INVITE_REVOKED")
        if invite.expires_at < utcnow():
            raise AppError("invite expired", 400, code="INVITE_EXPIRED")
        if invite.accepted_at:
            existing = await ChannelService.get_membership(db, invite.channel_id, user_id)
            if existing and existing.role in {MembershipRole.owner, MembershipRole.admin, MembershipRole.member}:
                return existing
            raise AppError("invite already accepted", 409, code="INVITE_ALREADY_ACCEPTED")
        if invite.invited_user_id and invite.invited_user_id != user_id:
            raise AppError("invite not for user", 403, code="FORBIDDEN")
        if invite.invited_email and user.email != invite.invited_email:
            raise AppError("invite email mismatch", 403, code="FORBIDDEN")

        membership = await ChannelService.get_membership(db, invite.channel_id, user_id)
        if membership:
            membership.role = MembershipRole.member
            membership.admin_permissions = None
            membership.approved_at = utcnow()
        else:
            membership = ChannelMembership(
                channel_id=invite.channel_id,
                user_id=user_id,
                role=MembershipRole.member,
                approved_at=utcnow(),
                created_by_user_id=invite.created_by_user_id,
                invited_by_user_id=invite.created_by_user_id,
            )
            db.add(membership)

        invite.accepted_at = utcnow()
        await log_event(
            db,
            "invite.accepted",
            {"channel_id": str(invite.channel_id), "user_id": str(user_id)},
            channel_id=invite.channel_id,
            actor_user_id=user_id,
        )
        await ChannelService._enqueue_membership_update(
            db,
            invite.channel_id,
            user_id,
            MembershipRole.member,
            reason="invite_accepted",
        )
        await db.commit()

        amqp_channel = await amqp.channel()
        try:
            await bind_user_channel(amqp_channel, user.username, channel.channel_slug)
        finally:
            await amqp_channel.close()
        return membership

    @staticmethod
    async def approve_member(
        db: AsyncSession,
        amqp: aio_pika.RobustConnection,
        channel_id: UUID,
        actor_id: UUID,
        target_id: UUID,
    ) -> ChannelMembership:
        actor = await ChannelService.get_membership(db, channel_id, actor_id)
        target = await ChannelService.get_membership(db, channel_id, target_id)
        if not actor or not target:
            raise AppError("membership not found", 404, code="MEMBERSHIP_NOT_FOUND")
        if not can_approve(actor.role, actor.admin_permissions):
            raise AppError("forbidden", 403, code="FORBIDDEN")
        if target.role != MembershipRole.pending:
            raise AppError("target is not pending", 400)

        target.role = MembershipRole.member
        target.admin_permissions = None
        target.approved_at = utcnow()
        await log_event(
            db,
            "membership.approved",
            {"channel_id": str(channel_id), "target_user_id": str(target_id)},
            channel_id=channel_id,
            actor_user_id=actor_id,
        )
        await ChannelService._enqueue_membership_update(
            db,
            channel_id,
            target_id,
            MembershipRole.member,
            reason="approved",
        )
        await db.commit()

        target_username = await ChannelService._require_username(db, target_id)
        channel_slug = await ChannelService._require_channel_slug(db, channel_id)
        amqp_channel = await amqp.channel()
        try:
            await bind_user_channel(amqp_channel, target_username, channel_slug)
        finally:
            await amqp_channel.close()
        return target

    @staticmethod
    async def add_member_direct(
        db: AsyncSession,
        amqp: aio_pika.RobustConnection,
        channel_id: UUID,
        actor_id: UUID,
        target_id: UUID,
    ) -> ChannelMembership:
        actor = await ChannelService.get_membership(db, channel_id, actor_id)
        if not ChannelService.membership_permissions(actor)["can_manage_members"]:
            raise AppError("forbidden", 403, code="FORBIDDEN")

        target = await ChannelService.get_membership(db, channel_id, target_id)
        if target:
            target.role = MembershipRole.member
            target.admin_permissions = None
            target.approved_at = utcnow()
        else:
            target = ChannelMembership(
                channel_id=channel_id,
                user_id=target_id,
                role=MembershipRole.member,
                approved_at=utcnow(),
                created_by_user_id=actor_id,
                invited_by_user_id=actor_id,
            )
            db.add(target)
        await log_event(
            db,
            "membership.added",
            {"channel_id": str(channel_id), "target_user_id": str(target_id)},
            channel_id=channel_id,
            actor_user_id=actor_id,
        )
        await ChannelService._enqueue_membership_update(
            db,
            channel_id,
            target_id,
            MembershipRole.member,
            reason="added",
        )
        await db.commit()

        target_username = await ChannelService._require_username(db, target_id)
        channel_slug = await ChannelService._require_channel_slug(db, channel_id)
        amqp_channel = await amqp.channel()
        try:
            await bind_user_channel(amqp_channel, target_username, channel_slug)
        finally:
            await amqp_channel.close()
        return target

    @staticmethod
    async def promote_member(db: AsyncSession, channel_id: UUID, actor_id: UUID, target_id: UUID) -> ChannelMembership:
        actor = await ChannelService.get_membership(db, channel_id, actor_id)
        target = await ChannelService.get_membership(db, channel_id, target_id)
        if not actor or not target:
            raise AppError("membership not found", 404, code="MEMBERSHIP_NOT_FOUND")
        if not can_promote(actor.role, target.role):
            raise AppError("forbidden", 403, code="FORBIDDEN")
        target.role = MembershipRole.admin
        target.admin_permissions = normalize_admin_permissions(target.admin_permissions)
        await log_event(
            db,
            "member.promoted",
            {"channel_id": str(channel_id), "target_user_id": str(target_id)},
            channel_id=channel_id,
            actor_user_id=actor_id,
        )
        await ChannelService._enqueue_membership_update(
            db,
            channel_id,
            target_id,
            MembershipRole.admin,
            reason="promoted",
        )
        await db.commit()
        return target

    @staticmethod
    async def demote_member(db: AsyncSession, channel_id: UUID, actor_id: UUID, target_id: UUID) -> ChannelMembership:
        actor = await ChannelService.get_membership(db, channel_id, actor_id)
        target = await ChannelService.get_membership(db, channel_id, target_id)
        if not actor or not target:
            raise AppError("membership not found", 404, code="MEMBERSHIP_NOT_FOUND")
        if not can_demote(actor.role, target.role):
            raise AppError("forbidden", 403, code="FORBIDDEN")
        target.role = MembershipRole.member
        target.admin_permissions = None
        await log_event(
            db,
            "member.demoted",
            {"channel_id": str(channel_id), "target_user_id": str(target_id)},
            channel_id=channel_id,
            actor_user_id=actor_id,
        )
        await ChannelService._enqueue_membership_update(
            db,
            channel_id,
            target_id,
            MembershipRole.member,
            reason="demoted",
        )
        await db.commit()
        return target

    @staticmethod
    async def update_admin_permissions(
        db: AsyncSession,
        channel_id: UUID,
        actor_id: UUID,
        target_id: UUID,
        req: AdminPermissionsUpdateRequest,
    ) -> ChannelMembership:
        actor = await ChannelService.get_membership(db, channel_id, actor_id)
        target = await ChannelService.get_membership(db, channel_id, target_id)
        if not actor or not target:
            raise AppError("membership not found", 404, code="MEMBERSHIP_NOT_FOUND")
        if actor.role != MembershipRole.owner:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        if target.role != MembershipRole.admin:
            raise AppError("target user must be an admin", 400, code="VALIDATION_ERROR")

        current_permissions = normalize_admin_permissions(target.admin_permissions)
        if req.can_publish is not None:
            current_permissions["can_publish"] = req.can_publish
        if req.can_invite is not None:
            current_permissions["can_invite"] = req.can_invite
        if req.can_approve is not None:
            current_permissions["can_approve"] = req.can_approve
        if req.can_manage_members is not None:
            current_permissions["can_manage_members"] = req.can_manage_members
        if req.can_edit_channel is not None:
            current_permissions["can_edit_channel"] = req.can_edit_channel
        target.admin_permissions = current_permissions

        await log_event(
            db,
            "member.permissions.updated",
            {
                "channel_id": str(channel_id),
                "target_user_id": str(target_id),
                "admin_permissions": current_permissions,
            },
            channel_id=channel_id,
            actor_user_id=actor_id,
        )
        await ChannelService._enqueue_membership_update(
            db,
            channel_id,
            target_id,
            MembershipRole.admin,
            reason="admin_permissions_updated",
        )
        await db.commit()
        return target

    @staticmethod
    async def remove_member(db: AsyncSession, amqp: aio_pika.RobustConnection, channel_id: UUID, actor_id: UUID, target_id: UUID) -> None:
        actor = await ChannelService.get_membership(db, channel_id, actor_id)
        target = await ChannelService.get_membership(db, channel_id, target_id)
        if not actor or not target:
            raise AppError("membership not found", 404, code="MEMBERSHIP_NOT_FOUND")
        if not ChannelService.membership_permissions(actor)["can_manage_members"]:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        if not can_remove(actor.role, target.role):
            raise AppError("forbidden", 403, code="FORBIDDEN")

        await db.delete(target)
        await log_event(
            db,
            "member.removed",
            {"channel_id": str(channel_id), "target_user_id": str(target_id)},
            channel_id=channel_id,
            actor_user_id=actor_id,
        )
        await ChannelService._enqueue_membership_update(
            db,
            channel_id,
            target_id,
            None,
            reason="removed",
        )
        await db.commit()

        target_username = await ChannelService._require_username(db, target_id)
        channel_slug = await ChannelService._require_channel_slug(db, channel_id)
        amqp_channel = await amqp.channel()
        try:
            await unbind_user_channel(amqp_channel, target_username, channel_slug)
        finally:
            await amqp_channel.close()

    @staticmethod
    async def leave_channel(
        db: AsyncSession,
        amqp: aio_pika.RobustConnection,
        channel_id: UUID,
        user_id: UUID,
    ) -> None:
        membership = await ChannelService.get_membership(db, channel_id, user_id)
        if not membership:
            raise AppError("membership not found", 404, code="MEMBERSHIP_NOT_FOUND")
        if membership.role == MembershipRole.owner:
            raise AppError("owner cannot leave channel without transferring ownership", 409, code="OWNER_CANNOT_LEAVE")
        await db.delete(membership)
        await log_event(
            db,
            "membership.left",
            {"channel_id": str(channel_id), "user_id": str(user_id)},
            channel_id=channel_id,
            actor_user_id=user_id,
        )
        await ChannelService._enqueue_membership_update(
            db,
            channel_id,
            user_id,
            None,
            reason="left",
        )
        await db.commit()

        username = await ChannelService._require_username(db, user_id)
        channel_slug = await ChannelService._require_channel_slug(db, channel_id)
        amqp_channel = await amqp.channel()
        try:
            await unbind_user_channel(amqp_channel, username, channel_slug)
        finally:
            await amqp_channel.close()

    @staticmethod
    async def list_members(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        role: MembershipRole | None,
        q: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[tuple[ChannelMembership, User]], str | None, bool]:
        await ChannelService._assert_manage_membership_access(db, channel_id, actor_user_id)
        role_order = case(
            (ChannelMembership.role == MembershipRole.owner, 0),
            (ChannelMembership.role == MembershipRole.admin, 1),
            (ChannelMembership.role == MembershipRole.member, 2),
            else_=3,
        )
        stmt = (
            select(ChannelMembership, User)
            .join(User, User.id == ChannelMembership.user_id)
            .where(ChannelMembership.channel_id == channel_id)
            .where(ChannelMembership.role.in_(list(ALLOWED_MEMBER_ROLES)))
            .order_by(role_order.asc(), func.lower(User.username).asc(), User.id.asc())
        )
        if role is not None:
            stmt = stmt.where(ChannelMembership.role == role)
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(or_(User.username.ilike(pattern), User.display_name.ilike(pattern), User.email.ilike(pattern)))
        if cursor:
            cursor_role_weight, cursor_username, cursor_user_id = ChannelService._decode_member_cursor(cursor)
            stmt = stmt.where(
                or_(
                    role_order > cursor_role_weight,
                    and_(
                        role_order == cursor_role_weight,
                        or_(
                            func.lower(User.username) > cursor_username,
                            and_(func.lower(User.username) == cursor_username, User.id > cursor_user_id),
                        ),
                    ),
                )
            )
        rows = await db.execute(stmt.limit(limit + 1))
        values = rows.all()
        has_more = len(values) > limit
        page = values[:limit]
        next_cursor = None
        if has_more and page:
            last_membership, last_user = page[-1]
            next_cursor = ChannelService._encode_member_cursor(
                last_membership.role,
                last_user.username,
                last_user.id,
            )
        return page, next_cursor, has_more

    @staticmethod
    async def list_pending_requests(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[tuple[ChannelMembership, User]], str | None, bool]:
        return await ChannelService.list_members(
            db=db,
            channel_id=channel_id,
            actor_user_id=actor_user_id,
            role=MembershipRole.pending,
            q=None,
            cursor=cursor,
            limit=limit,
        )

    @staticmethod
    async def get_events(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[Event], str | None, bool]:
        await ChannelService._assert_manage_membership_access(db, channel_id, actor_user_id)
        stmt = select(Event).where(Event.channel_id == channel_id).order_by(Event.created_at.desc(), Event.id.desc())
        if cursor:
            cursor_created_at, cursor_event_id = ChannelService._decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    Event.created_at < cursor_created_at,
                    and_(Event.created_at == cursor_created_at, Event.id < cursor_event_id),
                )
            )
        rows = await db.execute(stmt.limit(limit + 1))
        values = list(rows.scalars().all())
        has_more = len(values) > limit
        page = values[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = ChannelService._encode_cursor(last.created_at, last.id)
        return page, next_cursor, has_more

    @staticmethod
    async def _assert_manage_membership_access(db: AsyncSession, channel_id: UUID, actor_user_id: UUID) -> None:
        await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, actor_user_id)
        if not ChannelService.membership_permissions(membership)["can_manage_members"]:
            raise AppError("forbidden", 403, code="FORBIDDEN")

    @staticmethod
    async def _require_username(db: AsyncSession, user_id: UUID) -> str:
        user = await db.get(User, user_id)
        if user is None:
            raise AppError("user not found", 404, code="USER_NOT_FOUND")
        return normalize_username(user.username)

    @staticmethod
    async def _require_channel_slug(db: AsyncSession, channel_id: UUID) -> str:
        channel = await ChannelService.get_channel_or_404(db, channel_id)
        return normalize_channel_slug(channel.channel_slug)

    @staticmethod
    async def _validate_invite(db: AsyncSession, channel_id: UUID, token: str, user_id: UUID) -> ChannelInvite:
        token_hash = sha256_hex(token)
        user = await db.get(User, user_id)
        if not user:
            raise AppError("invalid invite", 404, code="INVITE_INVALID")
        row = await db.execute(
            select(ChannelInvite).where(ChannelInvite.channel_id == channel_id, ChannelInvite.token_hash == token_hash)
        )
        invite = row.scalar_one_or_none()
        if not invite:
            raise AppError("invalid invite", 400, code="INVITE_INVALID")
        if invite.revoked_at:
            raise AppError("invite revoked", 400, code="INVITE_REVOKED")
        if invite.accepted_at:
            raise AppError("invite already accepted", 409, code="INVITE_ALREADY_ACCEPTED")
        if invite.expires_at < utcnow():
            raise AppError("invite expired", 400, code="INVITE_EXPIRED")
        if invite.invited_user_id and invite.invited_user_id != user_id:
            raise AppError("invite is not for this user", 403, code="FORBIDDEN")
        if invite.invited_email and invite.invited_email != user.email:
            raise AppError("invite is not for this email", 403, code="FORBIDDEN")
        return invite

    @staticmethod
    async def _enqueue_membership_update(
        db: AsyncSession,
        channel_id: UUID,
        user_id: UUID,
        role: MembershipRole | None,
        reason: str,
    ) -> None:
        target_payload = {
            "type": "membership_update",
            "channel_id": str(channel_id),
            "user_id": str(user_id),
            "new_role": role.value if role else "none",
            "reason": reason,
        }
        await enqueue_channel_event_outbox(
            db,
            uuid.uuid4(),
            channel_id,
            "membership_update",
            target_payload,
        )
        await enqueue_user_event_outbox(
            db,
            uuid.uuid4(),
            channel_id,
            user_id,
            "membership_update_target",
            target_payload,
        )

    @staticmethod
    def mask_token(prefix: str, suffix: str) -> str:
        safe_prefix = (prefix or "****")[:4]
        safe_suffix = (suffix or "****")[-4:]
        return f"{safe_prefix}...{safe_suffix}"

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
            created_raw, id_raw = decoded.split(MEMBERSHIP_CURSOR_SEP, 1)
            return datetime.fromisoformat(created_raw), UUID(id_raw)
        except (ValueError, TypeError) as exc:
            raise AppError("invalid cursor", 400, code="PAGINATION_INVALID") from exc

    @staticmethod
    def _encode_cursor(created_at: datetime, entity_id: UUID) -> str:
        raw = f"{created_at.isoformat()}{MEMBERSHIP_CURSOR_SEP}{entity_id}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _encode_member_cursor(role: MembershipRole, username: str, user_id: UUID) -> str:
        raw = f"{ROLE_WEIGHT[role]}{MEMBERSHIP_CURSOR_SEP}{username.lower()}{MEMBERSHIP_CURSOR_SEP}{user_id}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _decode_member_cursor(cursor: str) -> tuple[int, str, UUID]:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
            role_raw, username_raw, user_id_raw = decoded.split(MEMBERSHIP_CURSOR_SEP, 2)
            return int(role_raw), username_raw, UUID(user_id_raw)
        except (ValueError, TypeError) as exc:
            raise AppError("invalid cursor", 400, code="PAGINATION_INVALID") from exc

    @staticmethod
    def _encode_channel_cursor(last_message_at: datetime | None, created_at: datetime, channel_id: UUID) -> str:
        last_raw = last_message_at.isoformat() if last_message_at else ""
        raw = f"{last_raw}{MEMBERSHIP_CURSOR_SEP}{created_at.isoformat()}{MEMBERSHIP_CURSOR_SEP}{channel_id}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _decode_channel_cursor(cursor: str) -> tuple[datetime | None, datetime, UUID]:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
            last_raw, created_raw, channel_raw = decoded.split(MEMBERSHIP_CURSOR_SEP, 2)
            last = datetime.fromisoformat(last_raw) if last_raw else None
            return last, datetime.fromisoformat(created_raw), UUID(channel_raw)
        except (ValueError, TypeError) as exc:
            raise AppError("invalid cursor", 400, code="PAGINATION_INVALID") from exc

    @staticmethod
    async def _enrich_channel_payload(
        db: AsyncSession,
        channel: Channel,
        user_id: UUID,
        role: MembershipRole | None,
        admin_permissions: dict | None = None,
    ) -> dict:
        payload = ChannelService.build_channel_payload(channel, role, admin_permissions)

        members_result = await db.execute(
            select(func.count(ChannelMembership.user_id)).where(
                ChannelMembership.channel_id == channel.id,
                ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
            )
        )
        pending_result = await db.execute(
            select(func.count(ChannelMembership.user_id)).where(
                ChannelMembership.channel_id == channel.id,
                ChannelMembership.role == MembershipRole.pending,
            )
        )
        payload["member_count"] = int(members_result.scalar_one() or 0)
        payload["pending_count"] = (
            int(pending_result.scalar_one() or 0)
            if ChannelService.build_permissions(role, admin_permissions)["can_manage_members"]
            else 0
        )

        last_msg_result = await db.execute(
            select(Message)
            .where(Message.channel_id == channel.id, Message.deleted_at.is_(None))
            .order_by(Message.seq_id.desc())
            .limit(1)
        )
        last_message = last_msg_result.scalar_one_or_none()
        if last_message:
            sender = await db.get(User, last_message.sender_user_id)
            content_text, content_json = ChannelService._decrypted_message_payload(last_message)
            payload["last_message"] = {
                "id": last_message.id,
                "channel_id": last_message.channel_id,
                "sender_user_id": last_message.sender_user_id,
                "sender_username": sender.username if sender else None,
                "sender_display_name": sender.display_name if sender else None,
                "sender_avatar_url": sender.avatar_url if sender else None,
                "seq_id": last_message.seq_id,
                "content_type": last_message.content_type.value,
                "content_text": content_text,
                "content_json": content_json,
                "reply_to_message_id": last_message.reply_to_message_id,
                "reply_to_seq_id": last_message.reply_to_seq_id,
                "attachments": last_message.attachments,
                "is_pinned": last_message.is_pinned,
                "client_msg_id": last_message.client_msg_id,
                "created_at": last_message.created_at,
                "updated_at": last_message.updated_at,
                "edited_at": last_message.edited_at,
                "deleted_at": last_message.deleted_at,
                "reactions_summary": {"counts": {}, "my_reaction": []},
            }
            payload["last_message_at"] = last_message.created_at

        state = await db.get(UserChannelState, {"channel_id": channel.id, "user_id": user_id})
        payload["my_last_seen_seq_id"] = state.last_seen_seq_id if state else None
        seen_seq = int(state.last_seen_seq_id) if state and state.last_seen_seq_id is not None else 0
        unread_result = await db.execute(
            select(func.count(Message.id)).where(
                Message.channel_id == channel.id,
                Message.deleted_at.is_(None),
                Message.seq_id > seen_seq,
                Message.reply_to_message_id.is_(None),
                Message.reply_to_seq_id.is_(None),
            )
        )
        payload["unread_count"] = int(unread_result.scalar_one() or 0)
        return payload

    @staticmethod
    async def get_channel_stats(db: AsyncSession, channel_id: UUID, user_id: UUID) -> dict:
        channel = await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, user_id)
        if channel.visibility == ChannelVisibility.private and membership is None:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        member_count_result = await db.execute(
            select(func.count(ChannelMembership.user_id)).where(
                ChannelMembership.channel_id == channel_id,
                ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
            )
        )
        pending_count_result = await db.execute(
            select(func.count(ChannelMembership.user_id)).where(
                ChannelMembership.channel_id == channel_id,
                ChannelMembership.role == MembershipRole.pending,
            )
        )
        message_count_result = await db.execute(
            select(func.count(Message.id)).where(Message.channel_id == channel_id, Message.deleted_at.is_(None))
        )
        last_message_result = await db.execute(
            select(Message.created_at)
            .where(Message.channel_id == channel_id, Message.deleted_at.is_(None))
            .order_by(Message.seq_id.desc())
            .limit(1)
        )
        return {
            "channel_id": channel_id,
            "member_count": int(member_count_result.scalar_one() or 0),
            "pending_count": int(pending_count_result.scalar_one() or 0),
            "message_count": int(message_count_result.scalar_one() or 0),
            "last_message_at": last_message_result.scalar_one_or_none(),
        }

