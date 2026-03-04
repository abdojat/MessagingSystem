import uuid
from datetime import datetime, timedelta
from uuid import UUID

import aio_pika
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.utils import make_invite_token, utcnow
from app.db.models import (
    Channel,
    ChannelCounter,
    ChannelInvite,
    ChannelJoinMode,
    ChannelMembership,
    ChannelVisibility,
    Event,
    MembershipRole,
    User,
)
from app.mq.publisher import bind_user_channel, unbind_user_channel
from app.schemas.channels import ChannelCreateRequest, ChannelPatchRequest, InviteRequest, JoinRequest
from app.services.event_service import log_event
from app.services.outbox_service import enqueue_channel_event_outbox
from app.services.rbac import can_approve, can_demote, can_invite, can_promote, can_publish, can_remove

MEMBERSHIP_CURSOR_SEP = "|"
ALLOWED_MEMBER_ROLES = {MembershipRole.owner, MembershipRole.admin, MembershipRole.member, MembershipRole.pending}


class ChannelService:
    @staticmethod
    async def get_membership(db: AsyncSession, channel_id: UUID, user_id: UUID) -> ChannelMembership | None:
        return await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})

    @staticmethod
    def build_permissions(role: MembershipRole | None) -> dict[str, bool]:
        is_manage_members = role in {MembershipRole.owner, MembershipRole.admin}
        return {
            "can_publish": can_publish(role),
            "can_invite": can_invite(role),
            "can_approve": can_approve(role),
            "can_manage_members": is_manage_members,
        }

    @staticmethod
    def build_channel_payload(channel: Channel, role: MembershipRole | None) -> dict:
        return {
            "id": channel.id,
            "owner_user_id": channel.owner_user_id,
            "name": channel.name,
            "visibility": channel.visibility,
            "join_mode": channel.join_mode,
            "created_at": channel.created_at,
            "my_role": role if role is not None else "none",
            "permissions": ChannelService.build_permissions(role),
        }

    @staticmethod
    async def create_channel(db: AsyncSession, owner_user_id: UUID, req: ChannelCreateRequest, amqp: aio_pika.RobustConnection) -> Channel:
        channel = Channel(
            owner_user_id=owner_user_id,
            name=req.name,
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
        await db.commit()
        await db.refresh(channel)

        amqp_channel = await amqp.channel()
        try:
            await bind_user_channel(amqp_channel, str(owner_user_id), str(channel.id))
        finally:
            await amqp_channel.close()
        return channel

    @staticmethod
    async def list_channels(db: AsyncSession, user_id: UUID) -> list[dict]:
        rows = await db.execute(
            select(Channel, ChannelMembership.role)
            .outerjoin(
                ChannelMembership,
                and_(ChannelMembership.channel_id == Channel.id, ChannelMembership.user_id == user_id),
            )
            .where(Channel.deleted_at.is_(None))
            .where(or_(Channel.visibility == ChannelVisibility.public, ChannelMembership.user_id.is_not(None)))
            .order_by(Channel.created_at.desc())
        )
        return [ChannelService.build_channel_payload(channel, role) for channel, role in rows.all()]

    @staticmethod
    async def get_channel_or_404(db: AsyncSession, channel_id: UUID) -> Channel:
        channel = await db.get(Channel, channel_id)
        if not channel or channel.deleted_at is not None:
            raise AppError("channel not found", 404)
        return channel

    @staticmethod
    async def get_channel_view(db: AsyncSession, channel_id: UUID, user_id: UUID) -> dict:
        channel = await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, user_id)
        role = membership.role if membership else None
        if channel.visibility == ChannelVisibility.private and role is None:
            raise AppError("forbidden", 403)
        return ChannelService.build_channel_payload(channel, role)

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
        if not membership or membership.role != MembershipRole.owner:
            raise AppError("forbidden", 403)

        if req.name is not None:
            channel.name = req.name
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
            "channel_update",
            {
                "type": "channel_update",
                "channel_id": str(channel_id),
                "name": channel.name,
                "visibility": channel.visibility.value,
                "join_mode": channel.join_mode.value,
            },
        )
        await db.commit()
        await db.refresh(channel)
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
            raise AppError("forbidden", 403)

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
                select(ChannelMembership.user_id).where(
                    ChannelMembership.channel_id == channel_id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                )
            )
            for uid in rows.scalars().all():
                await unbind_user_channel(amqp_channel, str(uid), str(channel_id))
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
            raise AppError("join not allowed", 403)

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
            amqp_channel = await amqp.channel()
            try:
                await bind_user_channel(amqp_channel, str(user_id), str(channel_id))
            finally:
                await amqp_channel.close()
        return (status, membership, message)

    @staticmethod
    async def create_invite(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        req: InviteRequest,
    ) -> ChannelInvite:
        await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, actor_user_id)
        if not can_invite(membership.role if membership else None):
            raise AppError("forbidden", 403)

        token = make_invite_token()
        invite = ChannelInvite(
            channel_id=channel_id,
            invited_user_id=req.invited_user_id,
            invited_email=req.invited_email,
            token=token,
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
        return invite

    @staticmethod
    async def list_invites(db: AsyncSession, channel_id: UUID, actor_user_id: UUID) -> list[ChannelInvite]:
        await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, actor_user_id)
        if not membership or membership.role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403)
        rows = await db.execute(
            select(ChannelInvite).where(ChannelInvite.channel_id == channel_id).order_by(ChannelInvite.created_at.desc())
        )
        return list(rows.scalars().all())

    @staticmethod
    async def revoke_invite(db: AsyncSession, channel_id: UUID, invite_id: UUID, actor_user_id: UUID) -> ChannelInvite:
        await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, actor_user_id)
        if not membership or membership.role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403)
        invite = await db.get(ChannelInvite, invite_id)
        if not invite or invite.channel_id != channel_id:
            raise AppError("invite not found", 404)
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
        row = await db.execute(
            select(ChannelInvite, Channel)
            .join(Channel, Channel.id == ChannelInvite.channel_id)
            .where(ChannelInvite.token == token)
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
        user = await db.get(User, user_id)
        if not user:
            raise AppError("user not found", 404)
        result = await db.execute(
            select(ChannelInvite, Channel)
            .join(Channel, Channel.id == ChannelInvite.channel_id)
            .where(ChannelInvite.token == token)
        )
        data = result.first()
        if not data:
            raise AppError("invite not found", 404)
        invite, channel = data
        if channel.deleted_at is not None:
            raise AppError("channel not found", 404)
        if invite.revoked_at or invite.expires_at < utcnow():
            raise AppError("invite invalid", 400)
        if invite.accepted_at:
            existing = await ChannelService.get_membership(db, invite.channel_id, user_id)
            if existing and existing.role in {MembershipRole.owner, MembershipRole.admin, MembershipRole.member}:
                return existing
            raise AppError("invite already accepted", 409)
        if invite.invited_user_id and invite.invited_user_id != user_id:
            raise AppError("invite not for user", 403)
        if invite.invited_email and user.email != invite.invited_email:
            raise AppError("invite email mismatch", 403)

        membership = await ChannelService.get_membership(db, invite.channel_id, user_id)
        if membership:
            membership.role = MembershipRole.member
            membership.approved_at = utcnow()
        else:
            membership = ChannelMembership(
                channel_id=invite.channel_id,
                user_id=user_id,
                role=MembershipRole.member,
                approved_at=utcnow(),
                created_by_user_id=invite.created_by_user_id,
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
            await bind_user_channel(amqp_channel, str(user_id), str(invite.channel_id))
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
            raise AppError("membership not found", 404)
        if not can_approve(actor.role):
            raise AppError("forbidden", 403)
        if target.role != MembershipRole.pending:
            raise AppError("target is not pending", 400)

        target.role = MembershipRole.member
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

        amqp_channel = await amqp.channel()
        try:
            await bind_user_channel(amqp_channel, str(target_id), str(channel_id))
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
        if not actor or actor.role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403)

        target = await ChannelService.get_membership(db, channel_id, target_id)
        if target:
            target.role = MembershipRole.member
            target.approved_at = utcnow()
        else:
            target = ChannelMembership(
                channel_id=channel_id,
                user_id=target_id,
                role=MembershipRole.member,
                approved_at=utcnow(),
                created_by_user_id=actor_id,
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

        amqp_channel = await amqp.channel()
        try:
            await bind_user_channel(amqp_channel, str(target_id), str(channel_id))
        finally:
            await amqp_channel.close()
        return target

    @staticmethod
    async def promote_member(db: AsyncSession, channel_id: UUID, actor_id: UUID, target_id: UUID) -> ChannelMembership:
        actor = await ChannelService.get_membership(db, channel_id, actor_id)
        target = await ChannelService.get_membership(db, channel_id, target_id)
        if not actor or not target:
            raise AppError("membership not found", 404)
        if not can_promote(actor.role, target.role):
            raise AppError("forbidden", 403)
        target.role = MembershipRole.admin
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
            raise AppError("membership not found", 404)
        if not can_demote(actor.role, target.role):
            raise AppError("forbidden", 403)
        target.role = MembershipRole.member
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
    async def remove_member(db: AsyncSession, amqp: aio_pika.RobustConnection, channel_id: UUID, actor_id: UUID, target_id: UUID) -> None:
        actor = await ChannelService.get_membership(db, channel_id, actor_id)
        target = await ChannelService.get_membership(db, channel_id, target_id)
        if not actor or not target:
            raise AppError("membership not found", 404)
        if not can_remove(actor.role, target.role):
            raise AppError("forbidden", 403)

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

        amqp_channel = await amqp.channel()
        try:
            await unbind_user_channel(amqp_channel, str(target_id), str(channel_id))
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
            raise AppError("membership not found", 404)
        if membership.role == MembershipRole.owner:
            raise AppError("owner cannot leave channel without transferring ownership", 409)
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

        amqp_channel = await amqp.channel()
        try:
            await unbind_user_channel(amqp_channel, str(user_id), str(channel_id))
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
        stmt = (
            select(ChannelMembership, User)
            .join(User, User.id == ChannelMembership.user_id)
            .where(ChannelMembership.channel_id == channel_id)
            .where(ChannelMembership.role.in_(list(ALLOWED_MEMBER_ROLES)))
            .order_by(ChannelMembership.created_at.desc(), ChannelMembership.user_id.desc())
        )
        if role is not None:
            stmt = stmt.where(ChannelMembership.role == role)
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(or_(User.username.ilike(pattern), User.email.ilike(pattern)))
        if cursor:
            cursor_created_at, cursor_user_id = ChannelService._decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    ChannelMembership.created_at < cursor_created_at,
                    and_(
                        ChannelMembership.created_at == cursor_created_at,
                        ChannelMembership.user_id < cursor_user_id,
                    ),
                )
            )
        rows = await db.execute(stmt.limit(limit + 1))
        values = rows.all()
        has_more = len(values) > limit
        page = values[:limit]
        next_cursor = None
        if has_more and page:
            last_membership = page[-1][0]
            next_cursor = ChannelService._encode_cursor(last_membership.created_at, last_membership.user_id)
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
        if not membership or membership.role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403)

    @staticmethod
    async def _validate_invite(db: AsyncSession, channel_id: UUID, token: str, user_id: UUID) -> ChannelInvite:
        user = await db.get(User, user_id)
        if not user:
            raise AppError("user not found", 404)
        row = await db.execute(
            select(ChannelInvite).where(ChannelInvite.channel_id == channel_id, ChannelInvite.token == token)
        )
        invite = row.scalar_one_or_none()
        if not invite:
            raise AppError("invalid invite", 400)
        if invite.revoked_at or invite.accepted_at or invite.expires_at < utcnow():
            raise AppError("invite expired or used", 400)
        if invite.invited_user_id and invite.invited_user_id != user_id:
            raise AppError("invite is not for this user", 403)
        if invite.invited_email and invite.invited_email != user.email:
            raise AppError("invite is not for this email", 403)
        return invite

    @staticmethod
    async def _enqueue_membership_update(
        db: AsyncSession,
        channel_id: UUID,
        user_id: UUID,
        role: MembershipRole | None,
        reason: str,
    ) -> None:
        await enqueue_channel_event_outbox(
            db,
            uuid.uuid4(),
            channel_id,
            "membership_update",
            {
                "type": "membership_update",
                "channel_id": str(channel_id),
                "user_id": str(user_id),
                "new_role": role.value if role else "none",
                "reason": reason,
            },
        )

    @staticmethod
    def mask_token(token: str) -> str:
        if len(token) <= 8:
            return "*" * len(token)
        return f"{token[:4]}...{token[-4:]}"

    @staticmethod
    def _encode_cursor(created_at: datetime, entity_id: UUID) -> str:
        return f"{created_at.isoformat()}{MEMBERSHIP_CURSOR_SEP}{entity_id}"

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            created_raw, id_raw = cursor.split(MEMBERSHIP_CURSOR_SEP, 1)
            return datetime.fromisoformat(created_raw), UUID(id_raw)
        except (ValueError, TypeError) as exc:
            raise AppError("invalid cursor", 422) from exc
