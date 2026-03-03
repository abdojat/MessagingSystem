from datetime import timedelta
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
    MembershipRole,
)
from app.mq.publisher import bind_user_channel, unbind_user_channel
from app.schemas.channels import ChannelCreateRequest, InviteRequest, JoinRequest
from app.services.event_service import log_event
from app.services.rbac import can_approve, can_demote, can_invite, can_promote, can_remove


class ChannelService:
    @staticmethod
    async def get_membership(db: AsyncSession, channel_id: UUID, user_id: UUID) -> ChannelMembership | None:
        return await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})

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
    async def list_channels(db: AsyncSession, user_id: UUID) -> list[Channel]:
        rows = await db.execute(
            select(Channel)
            .outerjoin(
                ChannelMembership,
                and_(ChannelMembership.channel_id == Channel.id, ChannelMembership.user_id == user_id),
            )
            .where(or_(Channel.visibility == ChannelVisibility.public, ChannelMembership.user_id.is_not(None)))
            .order_by(Channel.created_at.desc())
        )
        return list(rows.scalars().unique().all())

    @staticmethod
    async def get_channel_or_404(db: AsyncSession, channel_id: UUID) -> Channel:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise AppError("channel not found", 404)
        return channel

    @staticmethod
    async def join_channel(
        db: AsyncSession,
        amqp: aio_pika.RobustConnection,
        channel_id: UUID,
        user_id: UUID,
        req: JoinRequest,
    ) -> ChannelMembership:
        channel = await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, user_id)
        if membership:
            return membership

        if channel.visibility == ChannelVisibility.public and channel.join_mode == ChannelJoinMode.open:
            membership = ChannelMembership(
                channel_id=channel_id,
                user_id=user_id,
                role=MembershipRole.member,
                approved_at=utcnow(),
                created_by_user_id=user_id,
            )
        elif channel.join_mode == ChannelJoinMode.approval_required:
            membership = ChannelMembership(
                channel_id=channel_id,
                user_id=user_id,
                role=MembershipRole.pending,
                created_by_user_id=user_id,
            )
        elif channel.join_mode == ChannelJoinMode.invite_only:
            if not req.invite_token:
                raise AppError("invite token required", 403)
            invite = await ChannelService._validate_invite(db, channel_id, req.invite_token, user_id)
            invite.accepted_at = utcnow()
            membership = ChannelMembership(
                channel_id=channel_id,
                user_id=user_id,
                role=MembershipRole.member,
                approved_at=utcnow(),
                created_by_user_id=invite.created_by_user_id,
            )
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
        await db.commit()

        if membership.role in {MembershipRole.owner, MembershipRole.admin, MembershipRole.member}:
            amqp_channel = await amqp.channel()
            try:
                await bind_user_channel(amqp_channel, str(user_id), str(channel_id))
            finally:
                await amqp_channel.close()
        return membership

    @staticmethod
    async def create_invite(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        req: InviteRequest,
    ) -> ChannelInvite:
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
            {"channel_id": str(channel_id), "token": token},
            channel_id=channel_id,
            actor_user_id=actor_user_id,
        )
        await db.commit()
        await db.refresh(invite)
        return invite

    @staticmethod
    async def accept_invite(
        db: AsyncSession,
        amqp: aio_pika.RobustConnection,
        token: str,
        user_id: UUID,
    ) -> ChannelMembership:
        result = await db.execute(select(ChannelInvite).where(ChannelInvite.token == token))
        invite = result.scalar_one_or_none()
        if not invite:
            raise AppError("invite not found", 404)
        if invite.revoked_at or invite.accepted_at or invite.expires_at < utcnow():
            raise AppError("invite invalid", 400)
        if invite.invited_user_id and invite.invited_user_id != user_id:
            raise AppError("invite not for user", 403)

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
        await db.commit()

        amqp_channel = await amqp.channel()
        try:
            await bind_user_channel(amqp_channel, str(user_id), str(invite.channel_id))
        finally:
            await amqp_channel.close()
        return membership

    @staticmethod
    async def approve_member(db: AsyncSession, amqp: aio_pika.RobustConnection, channel_id: UUID, actor_id: UUID, target_id: UUID) -> ChannelMembership:
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
        await db.commit()

        amqp_channel = await amqp.channel()
        try:
            await unbind_user_channel(amqp_channel, str(target_id), str(channel_id))
        finally:
            await amqp_channel.close()

    @staticmethod
    async def _validate_invite(db: AsyncSession, channel_id: UUID, token: str, user_id: UUID) -> ChannelInvite:
        result = await db.execute(select(ChannelInvite).where(ChannelInvite.channel_id == channel_id, ChannelInvite.token == token))
        invite = result.scalar_one_or_none()
        if not invite:
            raise AppError("invalid invite", 400)
        if invite.revoked_at or invite.accepted_at or invite.expires_at < utcnow():
            raise AppError("invite expired or used", 400)
        if invite.invited_user_id and invite.invited_user_id != user_id:
            raise AppError("invite is not for this user", 403)
        return invite
