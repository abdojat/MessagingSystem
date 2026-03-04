from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.utils import utcnow
from app.db.models import (
    Channel,
    ChannelCounter,
    ChannelMembership,
    ContentType,
    MembershipRole,
    Message,
    MessageReaction,
    PinnedMessage,
    Upload,
    UserChannelState,
    Event,
)
from app.schemas.messages import MessagePatchRequest, PublishMessageRequest, SeenRequest, SyncRequest, UploadCreateRequest
from app.services.event_service import log_event
from app.services.outbox_service import enqueue_channel_event_outbox, enqueue_message_outbox
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
            reply_to_message_id=req.reply_to_message_id,
            reply_to_seq_id=req.reply_to_seq_id,
            attachments=req.attachments,
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
        order: str | None = None,
    ) -> tuple[list[Message], int | None, int | None, bool]:
        await MessageService._assert_can_read(db, channel_id, user_id)
        if before_seq_id is not None and after_seq_id is not None:
            raise AppError("use either before_seq_id or after_seq_id, not both", 422, code="VALIDATION_ERROR")
        if order is None:
            order = "asc" if after_seq_id is not None else "desc"
        if order not in {"asc", "desc"}:
            raise AppError("order must be asc or desc", 422, code="VALIDATION_ERROR")

        stmt = select(Message).where(Message.channel_id == channel_id)
        stmt = stmt.where(Message.deleted_at.is_(None))
        if before_seq_id is not None:
            stmt = stmt.where(Message.seq_id < before_seq_id)
            stmt = stmt.order_by(Message.seq_id.asc() if order == "asc" else Message.seq_id.desc())
        elif after_seq_id is not None:
            stmt = stmt.where(Message.seq_id > after_seq_id)
            stmt = stmt.order_by(Message.seq_id.asc() if order == "asc" else Message.seq_id.desc())
        else:
            stmt = stmt.order_by(Message.seq_id.asc() if order == "asc" else Message.seq_id.desc())

        rows = await db.execute(stmt.limit(limit + 1))
        values = list(rows.scalars().all())
        has_more = len(values) > limit
        page = values[:limit]

        if not page:
            return page, None, None, has_more

        next_before_seq_id = None
        next_after_seq_id = None
        if before_seq_id is not None:
            next_before_seq_id = page[-1].seq_id
        elif after_seq_id is not None:
            next_after_seq_id = page[-1].seq_id
        elif order == "desc":
            next_before_seq_id = page[-1].seq_id
        else:
            next_after_seq_id = page[-1].seq_id
        return page, next_before_seq_id, next_after_seq_id, has_more

    @staticmethod
    async def messages_around(db: AsyncSession, channel_id: UUID, user_id: UUID, seq_id: int, limit: int) -> list[Message]:
        await MessageService._assert_can_read(db, channel_id, user_id)
        side = max(1, limit // 2)
        left_rows = await db.execute(
            select(Message)
            .where(Message.channel_id == channel_id, Message.seq_id < seq_id, Message.deleted_at.is_(None))
            .order_by(Message.seq_id.desc())
            .limit(side)
        )
        center_rows = await db.execute(
            select(Message).where(Message.channel_id == channel_id, Message.seq_id == seq_id, Message.deleted_at.is_(None)).limit(1)
        )
        right_rows = await db.execute(
            select(Message)
            .where(Message.channel_id == channel_id, Message.seq_id > seq_id, Message.deleted_at.is_(None))
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
            message = await db.get(Message, req.last_seen_message_id)
            if not message or message.channel_id != channel_id:
                raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
            state.last_seen_message_id = message.id
            state.last_seen_seq_id = message.seq_id
        if req.last_seen_seq_id is not None:
            state.last_seen_seq_id = req.last_seen_seq_id
            state.last_seen_message_id = None
        if req.last_seen_at is not None:
            state.last_seen_at = req.last_seen_at
        else:
            state.last_seen_at = utcnow()

        counter = await db.get(ChannelCounter, {"channel_id": channel_id})
        max_seq = int(counter.next_seq) if counter else 0
        seen_seq = int(state.last_seen_seq_id or 0)
        state.unread_count = max(0, max_seq - seen_seq)
        await enqueue_channel_event_outbox(
            db,
            uuid4(),
            channel_id,
            "seen",
            {
                "type": "seen",
                "channel_id": str(channel_id),
                "user_id": str(user_id),
                "last_seen_message_id": str(state.last_seen_message_id) if state.last_seen_message_id else None,
                "last_seen_seq_id": state.last_seen_seq_id,
                "unread_count": state.unread_count,
                "last_seen_at": (state.last_seen_at or utcnow()).isoformat(),
            },
        )

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

    @staticmethod
    async def edit_message(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        message_id: UUID,
        req: MessagePatchRequest,
    ) -> Message:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id)
        message = await db.get(Message, message_id)
        if not message or message.channel_id != channel_id or message.deleted_at is not None:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        if message.sender_user_id != actor_user_id and role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")

        message.content_type = ContentType.text if req.content_text is not None else ContentType.json
        message.content_text = req.content_text
        message.content_json = req.content_json
        message.edited_at = utcnow()
        message.updated_at = utcnow()
        await db.flush()
        await enqueue_message_outbox(
            db,
            message.id,
            channel_id,
            {
                "type": "message_updated",
                "op": "edit",
                "message_id": str(message.id),
                "channel_id": str(channel_id),
                "seq_id": message.seq_id,
                "content_type": message.content_type.value,
                "content_text": message.content_text,
                "content_json": message.content_json,
                "edited_at": message.edited_at.isoformat(),
                "updated_at": message.updated_at.isoformat(),
            },
        )
        await db.commit()
        await db.refresh(message)
        return message

    @staticmethod
    async def delete_message(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        message_id: UUID,
    ) -> Message:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id)
        message = await db.get(Message, message_id)
        if not message or message.channel_id != channel_id:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        if message.sender_user_id != actor_user_id and role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        if message.deleted_at is None:
            message.deleted_at = utcnow()
            message.updated_at = message.deleted_at
            await db.flush()
            await enqueue_message_outbox(
                db,
                message.id,
                channel_id,
                {
                    "type": "message_updated",
                    "op": "delete",
                    "message_id": str(message.id),
                    "channel_id": str(channel_id),
                    "seq_id": message.seq_id,
                    "deleted_at": message.deleted_at.isoformat(),
                    "updated_at": message.updated_at.isoformat(),
                },
            )
            await db.commit()
            await db.refresh(message)
        return message

    @staticmethod
    async def _reaction_summary(db: AsyncSession, message_id: UUID, actor_user_id: UUID) -> dict:
        rows = await db.execute(
            select(MessageReaction.emoji, func.count(MessageReaction.id))
            .where(MessageReaction.message_id == message_id)
            .group_by(MessageReaction.emoji)
        )
        mine_rows = await db.execute(
            select(MessageReaction.emoji).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == actor_user_id,
            )
        )
        return {
            "counts": {emoji: int(count) for emoji, count in rows.all()},
            "my_reaction": list(mine_rows.scalars().all()),
        }

    @staticmethod
    async def add_reaction(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID, emoji: str) -> dict:
        await MessageService._assert_can_read(db, channel_id, actor_user_id)
        message = await db.get(Message, message_id)
        if not message or message.channel_id != channel_id or message.deleted_at is not None:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        existing = await db.execute(
            select(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == actor_user_id,
                MessageReaction.emoji == emoji,
            )
        )
        if existing.scalar_one_or_none() is None:
            db.add(
                MessageReaction(
                    channel_id=channel_id,
                    message_id=message_id,
                    user_id=actor_user_id,
                    emoji=emoji,
                )
            )
            await db.flush()
            await enqueue_message_outbox(
                db,
                message.id,
                channel_id,
                {
                    "type": "reaction_updated",
                    "channel_id": str(channel_id),
                    "message_id": str(message_id),
                    "emoji": emoji,
                    "op": "add",
                    "user_id": str(actor_user_id),
                },
            )
            await db.commit()
        return await MessageService._reaction_summary(db, message_id, actor_user_id)

    @staticmethod
    async def remove_reaction(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID, emoji: str) -> dict:
        await MessageService._assert_can_read(db, channel_id, actor_user_id)
        message = await db.get(Message, message_id)
        if not message or message.channel_id != channel_id or message.deleted_at is not None:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        await db.execute(
            delete(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == actor_user_id,
                MessageReaction.emoji == emoji,
            )
        )
        await enqueue_message_outbox(
            db,
            message.id,
            channel_id,
            {
                "type": "reaction_updated",
                "channel_id": str(channel_id),
                "message_id": str(message_id),
                "emoji": emoji,
                "op": "remove",
                "user_id": str(actor_user_id),
            },
        )
        await db.commit()
        return await MessageService._reaction_summary(db, message_id, actor_user_id)

    @staticmethod
    async def pin_message(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID) -> None:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id)
        if role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        message = await db.get(Message, message_id)
        if not message or message.channel_id != channel_id:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        existing = await db.get(PinnedMessage, {"channel_id": channel_id, "message_id": message_id})
        if not existing:
            db.add(PinnedMessage(channel_id=channel_id, message_id=message_id, pinned_by_user_id=actor_user_id))
        message.is_pinned = True
        await db.flush()
        await enqueue_message_outbox(
            db,
            message.id,
            channel_id,
            {
                "type": "message_updated",
                "op": "pin",
                "channel_id": str(channel_id),
                "message_id": str(message_id),
                "seq_id": message.seq_id,
                "is_pinned": True,
            },
        )
        await db.commit()

    @staticmethod
    async def unpin_message(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID) -> None:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id)
        if role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        pin = await db.get(PinnedMessage, {"channel_id": channel_id, "message_id": message_id})
        if pin:
            await db.delete(pin)
        message = await db.get(Message, message_id)
        if message and message.channel_id == channel_id:
            message.is_pinned = False
            await db.flush()
            await enqueue_message_outbox(
                db,
                message.id,
                channel_id,
                {
                    "type": "message_updated",
                    "op": "unpin",
                    "channel_id": str(channel_id),
                    "message_id": str(message_id),
                    "seq_id": message.seq_id,
                    "is_pinned": False,
                },
            )
        await db.commit()

    @staticmethod
    async def list_pins(db: AsyncSession, channel_id: UUID, actor_user_id: UUID, limit: int = 50) -> list[Message]:
        await MessageService._assert_can_read(db, channel_id, actor_user_id)
        rows = await db.execute(
            select(Message)
            .join(PinnedMessage, and_(PinnedMessage.message_id == Message.id, PinnedMessage.channel_id == Message.channel_id))
            .where(Message.channel_id == channel_id)
            .order_by(PinnedMessage.created_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def create_upload(db: AsyncSession, actor_user_id: UUID, req: UploadCreateRequest) -> Upload:
        settings = get_settings()
        if req.size_bytes > settings.upload_max_size_bytes:
            raise AppError("file too large", 422, code="VALIDATION_ERROR")
        if "/" not in req.content_type:
            raise AppError("invalid content_type", 422, code="VALIDATION_ERROR")
        upload = Upload(
            owner_user_id=actor_user_id,
            filename=req.filename,
            content_type=req.content_type,
            size_bytes=req.size_bytes,
            checksum=req.checksum,
            storage_path=f"{actor_user_id}/{uuid4()}-{req.filename}",
            public_url=None,
        )
        db.add(upload)
        await db.commit()
        await db.refresh(upload)
        return upload

    @staticmethod
    async def sync(db: AsyncSession, actor_user_id: UUID, req: SyncRequest) -> dict:
        from app.services.channel_service import ChannelService

        channel_ids = [entry.channel_id for entry in req.channels]
        membership_rows = await db.execute(
            select(ChannelMembership.channel_id, ChannelMembership.role)
            .where(ChannelMembership.user_id == actor_user_id)
            .where(ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]))
        )
        membership_map = {cid: role for cid, role in membership_rows.all()}
        if channel_ids:
            selected = [cid for cid in channel_ids if cid in membership_map]
        else:
            selected = list(membership_map.keys())

        channels_payload: list[dict] = []
        messages_payload: list[Message] = []
        membership_updates: list[dict] = []
        remaining = req.limit
        for cid in selected:
            if remaining <= 0:
                break
            channel = await ChannelService.get_channel_or_404(db, cid)
            channels_payload.append(await ChannelService._enrich_channel_payload(db, channel, actor_user_id, membership_map[cid]))
            cursor = next((c for c in req.channels if c.channel_id == cid), None)
            seq_marker = cursor.last_seen_seq_id if cursor and cursor.last_seen_seq_id is not None else 0
            rows = await db.execute(
                select(Message)
                .where(Message.channel_id == cid, Message.seq_id > seq_marker, Message.deleted_at.is_(None))
                .order_by(Message.seq_id.asc())
                .limit(remaining)
            )
            chunk = list(rows.scalars().all())
            messages_payload.extend(chunk)
            remaining -= len(chunk)

        if req.since is not None:
            membership_rows = await db.execute(
                select(Event)
                .where(
                    Event.created_at >= req.since,
                    or_(
                        Event.event_type.like("membership.%"),
                        Event.event_type.like("member.%"),
                        Event.event_type == "invite.accepted",
                    ),
                )
                .order_by(Event.created_at.asc())
                .limit(max(1, req.limit))
            )
            for event in membership_rows.scalars().all():
                membership_updates.append(
                    {
                        "id": str(event.id),
                        "channel_id": str(event.channel_id) if event.channel_id else None,
                        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
                        "event_type": event.event_type,
                        "payload": event.payload,
                        "created_at": event.created_at.isoformat(),
                    }
                )

        return {
            "server_time": utcnow(),
            "channels": channels_payload,
            "membership_updates": membership_updates,
            "messages": messages_payload,
        }

    @staticmethod
    async def store_upload_content(
        db: AsyncSession,
        actor_user_id: UUID,
        file_id: UUID,
        content: bytes,
    ) -> Upload:
        settings = get_settings()
        upload = await db.get(Upload, file_id)
        if not upload or upload.owner_user_id != actor_user_id:
            raise AppError("upload not found", 404, code="NOT_FOUND")
        if len(content) != upload.size_bytes:
            raise AppError("uploaded size mismatch", 422, code="VALIDATION_ERROR")

        base_dir = Path(settings.uploads_base_dir)
        full_path = base_dir / upload.storage_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        upload.public_url = f"/v1/uploads/{upload.id}/content"
        await db.commit()
        await db.refresh(upload)
        return upload
