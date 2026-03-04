from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.utils import utcnow
from app.db.models import (
    Channel,
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
        channel = await db.get(Channel, channel_id)
        if not channel or channel.deleted_at is not None:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": sender_id})
        role = membership.role if membership else None
        if not can_publish(role):
            raise AppError("forbidden", 403, code="FORBIDDEN")

        if req.client_msg_id is not None:
            existing = await db.execute(
                select(Message).where(
                    Message.channel_id == channel_id,
                    Message.sender_user_id == sender_id,
                    Message.client_msg_id == req.client_msg_id,
                )
            )
            existing_message = existing.scalar_one_or_none()
            if existing_message:
                return existing_message

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
            client_msg_id=req.client_msg_id,
        )
        db.add(message)
        await db.flush()

        payload = {
            "type": "message",
            "message_id": str(message.id),
            "channel_id": str(channel_id),
            "sender_user_id": str(sender_id),
            "seq_id": seq_id,
            "content_type": content_type.value,
            "content_text": message.content_text,
            "content_json": message.content_json,
            "client_msg_id": str(message.client_msg_id) if message.client_msg_id else None,
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
    async def get_message(db: AsyncSession, channel_id: UUID, user_id: UUID, message_id: UUID) -> Message:
        await MessageService._assert_can_read(db, channel_id, user_id)
        message = await db.get(Message, message_id)
        if not message or message.channel_id != channel_id:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        return message

    @staticmethod
    async def list_messages(
        db: AsyncSession,
        channel_id: UUID,
        user_id: UUID,
        before_seq_id: int | None,
        after_seq_id: int | None,
        limit: int,
    ) -> tuple[list[Message], int | None, int | None, bool]:
        await MessageService._assert_can_read(db, channel_id, user_id)
        if before_seq_id is not None and after_seq_id is not None:
            raise AppError("use either before_seq_id or after_seq_id, not both", 422, code="VALIDATION_ERROR")

        stmt = select(Message).where(Message.channel_id == channel_id)
        if before_seq_id is not None:
            stmt = stmt.where(Message.seq_id < before_seq_id).order_by(Message.seq_id.desc())
        elif after_seq_id is not None:
            stmt = stmt.where(Message.seq_id > after_seq_id).order_by(Message.seq_id.asc())
        else:
            stmt = stmt.order_by(Message.seq_id.desc())

        rows = await db.execute(stmt.limit(limit + 1))
        values = list(rows.scalars().all())
        has_more = len(values) > limit
        page = values[:limit]

        next_before_seq_id = page[-1].seq_id if page and (before_seq_id is not None or after_seq_id is None) else None
        next_after_seq_id = page[-1].seq_id if page and after_seq_id is not None else None
        return page, next_before_seq_id, next_after_seq_id, has_more

    @staticmethod
    async def messages_around(db: AsyncSession, channel_id: UUID, user_id: UUID, seq_id: int, limit: int) -> list[Message]:
        await MessageService._assert_can_read(db, channel_id, user_id)
        side = max(1, limit // 2)
        left_rows = await db.execute(
            select(Message)
            .where(Message.channel_id == channel_id, Message.seq_id < seq_id)
            .order_by(Message.seq_id.desc())
            .limit(side)
        )
        center_rows = await db.execute(
            select(Message).where(Message.channel_id == channel_id, Message.seq_id == seq_id).limit(1)
        )
        right_rows = await db.execute(
            select(Message)
            .where(Message.channel_id == channel_id, Message.seq_id > seq_id)
            .order_by(Message.seq_id.asc())
            .limit(side)
        )
        left = list(reversed(left_rows.scalars().all()))
        center = list(center_rows.scalars().all())
        right = list(right_rows.scalars().all())
        return left + center + right

    @staticmethod
    async def mark_seen(db: AsyncSession, channel_id: UUID, user_id: UUID, req: SeenRequest) -> UserChannelState:
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})
        role = membership.role if membership else None
        if role not in {MembershipRole.owner, MembershipRole.admin, MembershipRole.member, MembershipRole.pending}:
            raise AppError("forbidden", 403, code="FORBIDDEN")

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

    @staticmethod
    async def _assert_can_read(db: AsyncSession, channel_id: UUID, user_id: UUID) -> MembershipRole:
        channel = await db.get(Channel, channel_id)
        if not channel or channel.deleted_at is not None:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})
        role = membership.role if membership else None
        if not can_read(role):
            raise AppError("forbidden", 403, code="FORBIDDEN")
        return role
