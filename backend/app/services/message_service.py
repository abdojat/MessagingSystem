from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.utils import utcnow
from app.db.models import (
    ChannelCounter,
    ChannelMembership,
    ContentType,
    MembershipRole,
    Message,
    UserChannelState,
)
from app.schemas.messages import PublishMessageRequest, SeenRequest
from app.services.event_service import log_event
from app.services.outbox_service import enqueue_message_outbox
from app.services.rbac import can_publish, can_read


class MessageService:
    @staticmethod
    async def publish_message(db: AsyncSession, channel_id: UUID, sender_id: UUID, req: PublishMessageRequest) -> Message:
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": sender_id})
        role = membership.role if membership else None
        if not can_publish(role):
            raise AppError("forbidden", 403)

        seq_result = await db.execute(
            update(ChannelCounter)
            .where(ChannelCounter.channel_id == channel_id)
            .values(next_seq=ChannelCounter.next_seq + 1)
            .returning(ChannelCounter.next_seq)
        )
        seq_id = seq_result.scalar_one_or_none()
        if seq_id is None:
            raise AppError("channel counter missing", 500)

        content_type = ContentType.text if req.content_text is not None else ContentType.json
        message = Message(
            channel_id=channel_id,
            sender_user_id=sender_id,
            seq_id=seq_id,
            content_type=content_type,
            content_text=req.content_text,
            content_json=req.content_json,
        )
        db.add(message)
        await db.flush()

        payload = {
            "message_id": str(message.id),
            "channel_id": str(channel_id),
            "sender_user_id": str(sender_id),
            "seq_id": seq_id,
            "content_type": content_type.value,
            "content_text": message.content_text,
            "content_json": message.content_json,
            "created_at": message.created_at.isoformat() if message.created_at else utcnow().isoformat(),
        }
        await enqueue_message_outbox(db, message.id, channel_id, payload)
        await log_event(
            db,
            "message.published",
            payload,
            channel_id=channel_id,
            actor_user_id=sender_id,
        )
        await db.commit()
        await db.refresh(message)
        return message

    @staticmethod
    async def list_messages(db: AsyncSession, channel_id: UUID, user_id: UUID, before_seq_id: int | None, limit: int) -> list[Message]:
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})
        role = membership.role if membership else None
        if not can_read(role):
            raise AppError("forbidden", 403)

        stmt = select(Message).where(Message.channel_id == channel_id)
        if before_seq_id is not None:
            stmt = stmt.where(Message.seq_id < before_seq_id)
        stmt = stmt.order_by(Message.seq_id.desc()).limit(limit)
        rows = await db.execute(stmt)
        return list(rows.scalars().all())

    @staticmethod
    async def mark_seen(db: AsyncSession, channel_id: UUID, user_id: UUID, req: SeenRequest) -> UserChannelState:
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})
        role = membership.role if membership else None
        if role is None:
            raise AppError("not a member", 403)

        state = await db.get(UserChannelState, {"channel_id": channel_id, "user_id": user_id})
        if not state:
            state = UserChannelState(channel_id=channel_id, user_id=user_id)
            db.add(state)

        if req.last_seen_message_id is not None:
            state.last_seen_message_id = req.last_seen_message_id
        if req.last_seen_seq_id is not None:
            state.last_seen_seq_id = req.last_seen_seq_id
        if req.last_seen_at is not None:
            state.last_seen_at = req.last_seen_at
        else:
            state.last_seen_at = utcnow()

        if state.last_seen_seq_id is not None:
            unread_result = await db.execute(
                select(func.count(Message.id)).where(
                    Message.channel_id == channel_id,
                    Message.seq_id > state.last_seen_seq_id,
                )
            )
            state.unread_count = int(unread_result.scalar_one())

        await db.commit()
        await db.refresh(state)
        return state
