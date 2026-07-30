from pathlib import Path
import hashlib
import logging
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.identifiers import extract_upload_id_from_url, normalize_upload_filename
from app.core.encryption import decrypt_json_payload, decrypt_message, encrypt_json_payload, encrypt_message
from app.core.utils import utcnow
from app.db.models import (
    Channel,
    ChannelMembership,
    ChannelVisibility,
    ContentType,
    MembershipRole,
    Message,
    MessageReaction,
    PinnedMessage,
    Upload,
    User,
    UserChannelState,
    Event,
)
from app.schemas.messages import AttachmentReference, MessagePatchRequest, PublishMessageRequest, SeenRequest, SyncRequest, UploadCreateRequest
from app.services.event_service import log_event
from app.services.outbox_service import enqueue_channel_event_outbox, enqueue_message_outbox
from app.services.rbac import can_publish, can_read

logger = logging.getLogger(__name__)


# Groups the message business operations; API route handlers call it to enforce application business rules.
class MessageService:
    # Implements the safe log event operation; API route handlers call it to enforce application business rules.
    @staticmethod
    async def _safe_log_event(
        db: AsyncSession,
        event_type: str,
        payload: dict,
        channel_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        commit: bool = False,
    ) -> None:
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            await log_event(db, event_type, payload, channel_id=channel_id, actor_user_id=actor_user_id)
            # Run this conditional step only when `commit` is true.
            if commit:
                await db.commit()
        # Handle `Exception` here so this workflow can recover or report the failure consistently.
        except Exception:
            await db.rollback()
            logger.warning("failed to log event %s", event_type, exc_info=True)

    # Decrypts message content; API route handlers call it to enforce application business rules.
    @staticmethod
    def _decrypt_message_content(message: Message) -> tuple[str | None, dict | None]:
        # Run this conditional step only when `message.content_type == ContentType.text` is true.
        if message.content_type == ContentType.text:
            # Return early when `message.content_text is None` because the remaining work is not applicable.
            if message.content_text is None:
                return None, None
            return decrypt_message(message.content_text), None
        # Return early when `message.content_type == ContentType.json` because the remaining work is not applicable.
        if message.content_type == ContentType.json:
            return None, decrypt_json_payload(message.content_json)
        raise AppError("unsupported content type", 500, code="DECRYPTION_FAILED")

    # Encrypts payload; API route handlers call it to enforce application business rules.
    @staticmethod
    def _encrypt_payload(req: PublishMessageRequest | MessagePatchRequest) -> tuple[str | None, dict | None]:
        # Return early when `req.content_text is not None` because the remaining work is not applicable.
        if req.content_text is not None:
            return encrypt_message(req.content_text), None
        # Return early when `req.content_json is not None` because the remaining work is not applicable.
        if req.content_json is not None:
            return None, encrypt_json_payload(req.content_json)
        return None, None

    # Serializes message; API route handlers call it to enforce application business rules.
    @staticmethod
    def _serialize_message(
        message: Message,
        *,
        sender_username: str | None = None,
        sender_display_name: str | None = None,
        sender_avatar_url: str | None = None,
    ) -> dict:
        is_deleted = message.deleted_at is not None
        content_text = None
        content_json = None
        # Run this conditional step only when `not is_deleted` is true.
        if not is_deleted:
            content_text, content_json = MessageService._decrypt_message_content(message)
        return {
            "id": str(message.id),
            "channel_id": str(message.channel_id),
            "sender_user_id": str(message.sender_user_id),
            "sender_username": sender_username,
            "sender_display_name": sender_display_name,
            "sender_avatar_url": sender_avatar_url,
            "seq_id": int(message.seq_id),
            "content_type": message.content_type.value,
            "content_text": content_text,
            "content_json": content_json,
            "reply_to_message_id": str(message.reply_to_message_id) if message.reply_to_message_id else None,
            "reply_to_seq_id": message.reply_to_seq_id,
            "attachments": None if is_deleted else message.attachments,
            "is_pinned": bool(message.is_pinned),
            "client_msg_id": str(message.client_msg_id) if message.client_msg_id else None,
            "created_at": message.created_at.isoformat() if message.created_at else utcnow().isoformat(),
            "updated_at": message.updated_at.isoformat() if message.updated_at else None,
            "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            "deleted_at": message.deleted_at.isoformat() if message.deleted_at else None,
            "reactions_summary": {"counts": {}, "my_reaction": []},
        }

    # Serializes message for outbox; API route handlers call it to enforce application business rules.
    @staticmethod
    def _serialize_message_for_outbox(
        message: Message,
        *,
        sender_username: str | None = None,
        sender_display_name: str | None = None,
        sender_avatar_url: str | None = None,
    ) -> dict:
        is_deleted = message.deleted_at is not None
        return {
            "id": str(message.id),
            "channel_id": str(message.channel_id),
            "sender_user_id": str(message.sender_user_id),
            "sender_username": sender_username,
            "sender_display_name": sender_display_name,
            "sender_avatar_url": sender_avatar_url,
            "seq_id": int(message.seq_id),
            "content_type": message.content_type.value,
            "content_text": None if is_deleted else message.content_text,
            "content_json": None if is_deleted else message.content_json,
            "reply_to_message_id": str(message.reply_to_message_id) if message.reply_to_message_id else None,
            "reply_to_seq_id": message.reply_to_seq_id,
            "attachments": None if is_deleted else message.attachments,
            "is_pinned": bool(message.is_pinned),
            "client_msg_id": str(message.client_msg_id) if message.client_msg_id else None,
            "created_at": message.created_at.isoformat() if message.created_at else utcnow().isoformat(),
            "updated_at": message.updated_at.isoformat() if message.updated_at else None,
            "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            "deleted_at": message.deleted_at.isoformat() if message.deleted_at else None,
            "reactions_summary": {"counts": {}, "my_reaction": []},
        }

    # Loads sender profile; API route handlers call it to enforce application business rules.
    @staticmethod
    async def _load_sender_profile(
        db: AsyncSession,
        sender_user_id: UUID,
    ) -> tuple[str | None, str | None, str | None]:
        sender = await db.get(User, sender_user_id)
        # Return early when `sender is None` because the remaining work is not applicable.
        if sender is None:
            return None, None, None
        return sender.username, sender.display_name, sender.avatar_url

    # Publishes message; API route handlers call it to enforce application business rules.
    @staticmethod
    async def publish_message(db: AsyncSession, channel_id: UUID, sender_id: UUID, req: PublishMessageRequest) -> Message:
        channel_row = await db.execute(select(Channel).where(Channel.id == channel_id).with_for_update())
        channel = channel_row.scalar_one_or_none()
        # Reject the operation when `not channel or channel.deleted_at is not None` to keep invalid state from progressing.
        if not channel or channel.deleted_at is not None:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": sender_id})
        role = membership.role if membership else None
        is_member_reply = role == MembershipRole.member and (
            req.reply_to_message_id is not None or req.reply_to_seq_id is not None
        )
        # Run this conditional step only when `not can_publish(role, membership.admin_permissions if membership else...` is true.
        if not can_publish(role, membership.admin_permissions if membership else None) and not is_member_reply:
            await MessageService._safe_log_event(
                db,
                "security.unauthorized_publish",
                {"channel_id": str(channel_id), "reason": "insufficient_permissions"},
                channel_id=channel_id,
                actor_user_id=sender_id,
                commit=True,
            )
            raise AppError("forbidden", 403, code="FORBIDDEN")

        # Run this conditional step only when `req.client_msg_id is not None` is true.
        if req.client_msg_id is not None:
            existing = await db.execute(
                select(Message).where(
                    Message.channel_id == channel_id,
                    Message.sender_user_id == sender_id,
                    Message.client_msg_id == req.client_msg_id,
                )
            )
            existing_message = existing.scalar_one_or_none()
            # Return early when `existing_message` because the remaining work is not applicable.
            if existing_message:
                return existing_message

        attachments = await MessageService._normalize_attachments(db, sender_id, req.attachments)
        reply_to_message_id, reply_to_seq_id = await MessageService._resolve_reply_target(
            db,
            channel_id,
            req.reply_to_message_id,
            req.reply_to_seq_id,
        )
        channel.last_seq_id = int(channel.last_seq_id or 0) + 1
        seq_id = int(channel.last_seq_id)
        await db.flush()

        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            encrypted_text, encrypted_json = MessageService._encrypt_payload(req)
        # Handle `AppError` here so this workflow can recover or report the failure consistently.
        except AppError:
            await MessageService._safe_log_event(
                db,
                "message.encryption_failed",
                {"channel_id": str(channel_id)},
                channel_id=channel_id,
                actor_user_id=sender_id,
            )
            raise
        content_type = ContentType.json if req.content_json is not None else ContentType.text
        message = Message(
            channel_id=channel_id,
            sender_user_id=sender_id,
            seq_id=seq_id,
            content_type=content_type,
            content_text=encrypted_text,
            content_json=encrypted_json,
            reply_to_message_id=reply_to_message_id,
            reply_to_seq_id=reply_to_seq_id,
            attachments=attachments,
            client_msg_id=req.client_msg_id,
        )
        db.add(message)
        await db.flush()

        sender_username, sender_display_name, sender_avatar_url = await MessageService._load_sender_profile(db, sender_id)
        payload = {
            "type": "message",
            **MessageService._serialize_message_for_outbox(
                message,
                sender_username=sender_username,
                sender_display_name=sender_display_name,
                sender_avatar_url=sender_avatar_url,
            ),
        }
        await enqueue_message_outbox(db, message.id, channel_id, payload)
        await log_event(
            db,
            "message.published",
            {
                "message_id": str(message.id),
                "channel_id": str(channel_id),
                "seq_id": seq_id,
                "content_type": content_type.value,
                "attachment_count": len(attachments or []),
                "reply_to_message_id": str(reply_to_message_id) if reply_to_message_id else None,
                "reply_to_seq_id": reply_to_seq_id,
            },
            channel_id=channel_id,
            actor_user_id=sender_id,
        )
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            await db.commit()
        # Handle `IntegrityError` here so this workflow can recover or report the failure consistently.
        except IntegrityError as exc:
            await db.rollback()
            # Run this conditional step only when `req.client_msg_id is not None` is true.
            if req.client_msg_id is not None:
                conflict = await db.execute(
                    select(Message).where(
                        Message.channel_id == channel_id,
                        Message.sender_user_id == sender_id,
                        Message.client_msg_id == req.client_msg_id,
                    )
                )
                existing_message = conflict.scalar_one_or_none()
                # Return early when `existing_message is not None` because the remaining work is not applicable.
                if existing_message is not None:
                    return existing_message
            raise AppError("message conflict", 409, code="CONFLICT") from exc
        await db.refresh(message)
        return message

    # Resolves reply target; API route handlers call it to enforce application business rules.
    @staticmethod
    async def _resolve_reply_target(
        db: AsyncSession,
        channel_id: UUID,
        reply_to_message_id: UUID | None,
        reply_to_seq_id: int | None,
    ) -> tuple[UUID | None, int | None]:
        # Return early when `reply_to_message_id is None and reply_to_seq_id is None` because the remaining work is not applicable.
        if reply_to_message_id is None and reply_to_seq_id is None:
            return None, None

        target: Message | None = None
        # Choose the appropriate path based on whether `reply_to_message_id is not None` is true.
        if reply_to_message_id is not None:
            target = await db.get(Message, reply_to_message_id)
            # Reject the operation when `target is None or target.channel_id != channel_id or target.deleted_a...` to keep invalid state from progressing.
            if target is None or target.channel_id != channel_id or target.deleted_at is not None:
                raise AppError("reply target not found", 404, code="MESSAGE_NOT_FOUND")
            # Reject the operation when `reply_to_seq_id is not None and int(target.seq_id) != int(reply_to_se...` to keep invalid state from progressing.
            if reply_to_seq_id is not None and int(target.seq_id) != int(reply_to_seq_id):
                raise AppError("reply target mismatch", 400, code="VALIDATION_ERROR")
        # Handle the alternate path after the preceding branch or loop does not produce a result.
        else:
            rows = await db.execute(
                select(Message).where(
                    Message.channel_id == channel_id,
                    Message.seq_id == int(reply_to_seq_id),
                    Message.deleted_at.is_(None),
                )
            )
            target = rows.scalar_one_or_none()
            # Reject the operation when `target is None` to keep invalid state from progressing.
            if target is None:
                raise AppError("reply target not found", 404, code="MESSAGE_NOT_FOUND")

        return target.id, int(target.seq_id)

    # Retrieves message; API route handlers call it to enforce application business rules.
    @staticmethod
    async def get_message(db: AsyncSession, channel_id: UUID, user_id: UUID, message_id: UUID) -> Message:
        await MessageService._assert_can_read(db, channel_id, user_id)
        message = await db.get(Message, message_id)
        # Reject the operation when `not message or message.channel_id != channel_id` to keep invalid state from progressing.
        if not message or message.channel_id != channel_id:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        return message

    # Lists messages; API route handlers call it to enforce application business rules.
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
        # Run this conditional step only when `order is None` is true.
        if order is None:
            order = "asc" if after_seq_id is not None else "desc"
        # Reject the operation when `order not in {'asc', 'desc'}` to keep invalid state from progressing.
        if order not in {"asc", "desc"}:
            raise AppError("order must be asc or desc", 400, code="VALIDATION_ERROR")

        stmt = select(Message).where(Message.channel_id == channel_id)
        stmt = stmt.where(Message.deleted_at.is_(None))
        # Run this conditional step only when `before_seq_id is not None` is true.
        if before_seq_id is not None:
            stmt = stmt.where(Message.seq_id < before_seq_id)
        # Run this conditional step only when `after_seq_id is not None` is true.
        if after_seq_id is not None:
            stmt = stmt.where(Message.seq_id > after_seq_id)
        stmt = stmt.order_by(Message.seq_id.asc() if order == "asc" else Message.seq_id.desc())

        rows = await db.execute(stmt.limit(limit + 1))
        values = list(rows.scalars().all())
        has_more = len(values) > limit
        page = values[:limit]

        # Return early when `not page` because the remaining work is not applicable.
        if not page:
            return page, None, None, has_more

        next_before_seq_id = None
        next_after_seq_id = None
        # Choose the appropriate path based on whether `order == 'desc'` is true.
        if order == "desc":
            next_before_seq_id = min(m.seq_id for m in page)
        # Handle the alternate path after the preceding branch or loop does not produce a result.
        else:
            next_after_seq_id = max(m.seq_id for m in page)
        return page, next_before_seq_id, next_after_seq_id, has_more

    # Implements the messages around operation; API route handlers call it to enforce application business rules.
    @staticmethod
    async def messages_around(
        db: AsyncSession,
        channel_id: UUID,
        user_id: UUID,
        seq_id: int,
        limit_before: int,
        limit_after: int,
    ) -> list[Message]:
        await MessageService._assert_can_read(db, channel_id, user_id)
        left_rows = await db.execute(
            select(Message)
            .where(Message.channel_id == channel_id, Message.seq_id < seq_id, Message.deleted_at.is_(None))
            .order_by(Message.seq_id.desc())
            .limit(limit_before)
        )
        center_rows = await db.execute(
            select(Message).where(Message.channel_id == channel_id, Message.seq_id == seq_id, Message.deleted_at.is_(None)).limit(1)
        )
        right_rows = await db.execute(
            select(Message)
            .where(Message.channel_id == channel_id, Message.seq_id > seq_id, Message.deleted_at.is_(None))
            .order_by(Message.seq_id.asc())
            .limit(limit_after)
        )
        left = list(reversed(left_rows.scalars().all()))
        center = list(center_rows.scalars().all())
        right = list(right_rows.scalars().all())
        return left + center + right

    # Marks seen; API route handlers call it to enforce application business rules.
    @staticmethod
    async def mark_seen(db: AsyncSession, channel_id: UUID, user_id: UUID, req: SeenRequest) -> UserChannelState:
        channel = await db.get(Channel, channel_id)
        # Reject the operation when `not channel or channel.deleted_at is not None` to keep invalid state from progressing.
        if not channel or channel.deleted_at is not None:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")

        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})
        role = membership.role if membership else None
        # Reject the operation when `role not in {MembershipRole.owner, MembershipRole.admin, MembershipRo...` to keep invalid state from progressing.
        if role not in {MembershipRole.owner, MembershipRole.admin, MembershipRole.member, MembershipRole.pending}:
            raise AppError("forbidden", 403, code="FORBIDDEN")

        state = await db.get(UserChannelState, {"channel_id": channel_id, "user_id": user_id})
        # Run this conditional step only when `not state` is true.
        if not state:
            state = UserChannelState(channel_id=channel_id, user_id=user_id)
            db.add(state)

        requested_seq: int | None = None
        requested_message_id: UUID | None = None
        clear_message_id = False
        # Run this conditional step only when `req.last_seen_message_id is not None` is true.
        if req.last_seen_message_id is not None:
            message = await db.get(Message, req.last_seen_message_id)
            # Reject the operation when `not message or message.channel_id != channel_id` to keep invalid state from progressing.
            if not message or message.channel_id != channel_id:
                raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
            requested_seq = int(message.seq_id)
            requested_message_id = message.id
        # Run this conditional step only when `req.last_seen_seq_id is not None` is true.
        if req.last_seen_seq_id is not None:
            requested_seq = int(req.last_seen_seq_id)
            clear_message_id = True

        # Reject the operation when `requested_seq is not None and requested_seq > int(channel.last_seq_id...` to keep invalid state from progressing.
        if requested_seq is not None and requested_seq > int(channel.last_seq_id or 0):
            raise AppError("last_seen_seq_id out of range", 400, code="VALIDATION_ERROR")

        current_seen_seq = int(state.last_seen_seq_id or 0)
        # Run this conditional step only when `requested_seq is not None and requested_seq >= current_seen_seq` is true.
        if requested_seq is not None and requested_seq >= current_seen_seq:
            state.last_seen_seq_id = requested_seq
            # Choose the appropriate path based on whether `clear_message_id` is true.
            if clear_message_id:
                state.last_seen_message_id = None
            # Handle the alternate path after the preceding branch or loop does not produce a result.
            else:
                state.last_seen_message_id = requested_message_id
        # Choose the appropriate path based on whether `req.last_seen_at is not None` is true.
        if req.last_seen_at is not None:
            state.last_seen_at = req.last_seen_at
        # Handle the alternate path after the preceding branch or loop does not produce a result.
        else:
            state.last_seen_at = utcnow()

        seen_seq = int(state.last_seen_seq_id or 0)
        unread_rows = await db.execute(
            select(func.count(Message.id)).where(
                Message.channel_id == channel_id,
                Message.deleted_at.is_(None),
                Message.seq_id > seen_seq,
                Message.reply_to_message_id.is_(None),
                Message.reply_to_seq_id.is_(None),
            )
        )
        state.unread_count = int(unread_rows.scalar_one() or 0)
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

    # Enforces can read; API route handlers call it to enforce application business rules.
    @staticmethod
    async def _assert_can_read(db: AsyncSession, channel_id: UUID, user_id: UUID) -> MembershipRole:
        channel = await db.get(Channel, channel_id)
        # Reject the operation when `not channel or channel.deleted_at is not None` to keep invalid state from progressing.
        if not channel or channel.deleted_at is not None:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": user_id})
        role = membership.role if membership else None
        # Run this conditional step only when `not can_read(role)` is true.
        if not can_read(role):
            await MessageService._safe_log_event(
                db,
                "security.unauthorized_read",
                {"channel_id": str(channel_id), "reason": "insufficient_permissions"},
                channel_id=channel_id,
                actor_user_id=user_id,
                commit=True,
            )
            raise AppError("forbidden", 403, code="FORBIDDEN")
        return role

    # Edits an existing message; API route handlers call it to enforce application business rules.
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
        # Reject the operation when `not message or message.channel_id != channel_id or message.deleted_at...` to keep invalid state from progressing.
        if not message or message.channel_id != channel_id or message.deleted_at is not None:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        # Reject the operation when `message.sender_user_id != actor_user_id and role not in {MembershipRo...` to keep invalid state from progressing.
        if message.sender_user_id != actor_user_id and role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")

        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            encrypted_text, encrypted_json = MessageService._encrypt_payload(req)
        # Handle `AppError` here so this workflow can recover or report the failure consistently.
        except AppError:
            await MessageService._safe_log_event(
                db,
                "message.encryption_failed",
                {"channel_id": str(channel_id), "message_id": str(message_id)},
                channel_id=channel_id,
                actor_user_id=actor_user_id,
            )
            raise
        message.content_type = ContentType.text if req.content_text is not None else ContentType.json
        message.content_text = encrypted_text
        message.content_json = encrypted_json
        message.edited_at = utcnow()
        message.updated_at = utcnow()
        await db.flush()
        sender_username, sender_display_name, sender_avatar_url = await MessageService._load_sender_profile(
            db,
            message.sender_user_id,
        )
        await enqueue_message_outbox(
            db,
            message.id,
            channel_id,
            {
                "type": "message_updated",
                **MessageService._serialize_message_for_outbox(
                    message,
                    sender_username=sender_username,
                    sender_display_name=sender_display_name,
                    sender_avatar_url=sender_avatar_url,
                ),
            },
        )
        await db.commit()
        await db.refresh(message)
        return message

    # Deletes message; API route handlers call it to enforce application business rules.
    @staticmethod
    async def delete_message(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        message_id: UUID,
    ) -> Message:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id)
        message = await db.get(Message, message_id)
        # Reject the operation when `not message or message.channel_id != channel_id` to keep invalid state from progressing.
        if not message or message.channel_id != channel_id:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        # Reject the operation when `message.sender_user_id != actor_user_id and role not in {MembershipRo...` to keep invalid state from progressing.
        if message.sender_user_id != actor_user_id and role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        # Run this conditional step only when `message.deleted_at is None` is true.
        if message.deleted_at is None:
            message.deleted_at = utcnow()
            message.updated_at = message.deleted_at
            message.content_text = None
            message.content_json = None
            await db.flush()
            sender_username, sender_display_name, sender_avatar_url = await MessageService._load_sender_profile(
                db,
                message.sender_user_id,
            )
            await enqueue_message_outbox(
                db,
                message.id,
                channel_id,
                {
                    "type": "message_updated",
                    **MessageService._serialize_message_for_outbox(
                        message,
                        sender_username=sender_username,
                        sender_display_name=sender_display_name,
                        sender_avatar_url=sender_avatar_url,
                    ),
                },
            )
            await db.commit()
            await db.refresh(message)
        return message

    # Implements the reaction summary operation; API route handlers call it to enforce application business rules.
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
            ).order_by(MessageReaction.emoji.asc())
        )
        return {
            "counts": {emoji: int(count) for emoji, count in rows.all()},
            "my_reaction": list(mine_rows.scalars().all()),
        }

    # Adds reaction; API route handlers call it to enforce application business rules.
    @staticmethod
    async def add_reaction(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID, emoji: str) -> dict:
        await MessageService._assert_can_read(db, channel_id, actor_user_id)
        message = await db.get(Message, message_id)
        # Reject the operation when `not message or message.channel_id != channel_id or message.deleted_at...` to keep invalid state from progressing.
        if not message or message.channel_id != channel_id or message.deleted_at is not None:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        existing = await db.execute(
            select(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == actor_user_id,
                MessageReaction.emoji == emoji,
            )
        )
        existing_reaction = existing.scalar_one_or_none()
        # Run this conditional step only when `existing_reaction is None` is true.
        if existing_reaction is None:
            db.add(
                MessageReaction(
                    channel_id=channel_id,
                    message_id=message_id,
                    user_id=actor_user_id,
                    emoji=emoji,
                )
            )
            await db.flush()
        summary = await MessageService._reaction_summary(db, message_id, actor_user_id)
        # Run this conditional step only when `existing_reaction is None` is true.
        if existing_reaction is None:
            await enqueue_message_outbox(
                db,
                message.id,
                channel_id,
                {
                    "type": "reaction_updated",
                    "channel_id": str(channel_id),
                    "message_id": str(message_id),
                    "reactions_summary": summary,
                },
            )
            await db.commit()
        return summary

    # Removes reaction; API route handlers call it to enforce application business rules.
    @staticmethod
    async def remove_reaction(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID, emoji: str) -> dict:
        await MessageService._assert_can_read(db, channel_id, actor_user_id)
        message = await db.get(Message, message_id)
        # Reject the operation when `not message or message.channel_id != channel_id or message.deleted_at...` to keep invalid state from progressing.
        if not message or message.channel_id != channel_id or message.deleted_at is not None:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        await db.execute(
            delete(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == actor_user_id,
                MessageReaction.emoji == emoji,
            )
        )
        summary = await MessageService._reaction_summary(db, message_id, actor_user_id)
        await enqueue_message_outbox(
            db,
            message.id,
            channel_id,
            {
                "type": "reaction_updated",
                "channel_id": str(channel_id),
                "message_id": str(message_id),
                "reactions_summary": summary,
            },
        )
        await db.commit()
        return summary

    # Pins a message for channel members; API route handlers call it to enforce application business rules.
    @staticmethod
    async def pin_message(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID) -> None:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id)
        # Reject the operation when `role not in {MembershipRole.owner, MembershipRole.admin}` to keep invalid state from progressing.
        if role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        message = await db.get(Message, message_id)
        # Reject the operation when `not message or message.channel_id != channel_id` to keep invalid state from progressing.
        if not message or message.channel_id != channel_id:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        existing = await db.get(PinnedMessage, {"channel_id": channel_id, "message_id": message_id})
        # Run this conditional step only when `not existing` is true.
        if not existing:
            db.add(PinnedMessage(channel_id=channel_id, message_id=message_id, pinned_by_user_id=actor_user_id))
        message.is_pinned = True
        await db.flush()
        sender_username, sender_display_name, sender_avatar_url = await MessageService._load_sender_profile(
            db,
            message.sender_user_id,
        )
        await enqueue_message_outbox(
            db,
            message.id,
            channel_id,
            {
                "type": "message_updated",
                **MessageService._serialize_message_for_outbox(
                    message,
                    sender_username=sender_username,
                    sender_display_name=sender_display_name,
                    sender_avatar_url=sender_avatar_url,
                ),
            },
        )
        await db.commit()

    # Removes a message from the channel pins; API route handlers call it to enforce application business rules.
    @staticmethod
    async def unpin_message(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID) -> None:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id)
        # Reject the operation when `role not in {MembershipRole.owner, MembershipRole.admin}` to keep invalid state from progressing.
        if role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        pin = await db.get(PinnedMessage, {"channel_id": channel_id, "message_id": message_id})
        # Run this conditional step only when `pin` is true.
        if pin:
            await db.delete(pin)
        message = await db.get(Message, message_id)
        # Run this conditional step only when `message and message.channel_id == channel_id` is true.
        if message and message.channel_id == channel_id:
            message.is_pinned = False
            await db.flush()
            sender_username, sender_display_name, sender_avatar_url = await MessageService._load_sender_profile(
                db,
                message.sender_user_id,
            )
            await enqueue_message_outbox(
                db,
                message.id,
                channel_id,
                {
                    "type": "message_updated",
                    **MessageService._serialize_message_for_outbox(
                        message,
                        sender_username=sender_username,
                        sender_display_name=sender_display_name,
                        sender_avatar_url=sender_avatar_url,
                    ),
                },
            )
        await db.commit()

    # Lists pins; API route handlers call it to enforce application business rules.
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

    # Creates upload; API route handlers call it to enforce application business rules.
    @staticmethod
    async def create_upload(db: AsyncSession, actor_user_id: UUID, req: UploadCreateRequest) -> Upload:
        settings = get_settings()
        # Reject the operation when `req.size_bytes > settings.upload_max_size_bytes` to keep invalid state from progressing.
        if req.size_bytes > settings.upload_max_size_bytes:
            raise AppError("file too large", 400, code="VALIDATION_ERROR")
        content_type = req.content_type.strip().lower()
        media_type = content_type.split(";", 1)[0].strip()
        # Reject the operation when `'/' not in media_type` to keep invalid state from progressing.
        if "/" not in media_type:
            raise AppError("invalid content_type", 400, code="VALIDATION_ERROR")
        allowed_prefixes = ("image/", "video/", "audio/", "text/")
        allowed_exact = {"application/json", "application/pdf"}
        # Reject the operation when `not (media_type.startswith(allowed_prefixes) or media_type in allowed...` to keep invalid state from progressing.
        if not (media_type.startswith(allowed_prefixes) or media_type in allowed_exact):
            raise AppError("content_type not allowed", 400, code="VALIDATION_ERROR")
        # Reject the operation when `media_type == 'image/svg+xml'` to keep invalid state from progressing.
        if media_type == "image/svg+xml":
            raise AppError("svg uploads are not allowed", 400, code="VALIDATION_ERROR")
        safe_filename = normalize_upload_filename(req.filename)
        upload = Upload(
            owner_user_id=actor_user_id,
            filename=req.filename,
            content_type=media_type,
            size_bytes=req.size_bytes,
            checksum=req.checksum,
            storage_path=f"{actor_user_id}/{uuid4()}-{safe_filename}",
            public_url=None,
        )
        db.add(upload)
        await db.flush()
        await log_event(
            db,
            "upload.created",
            {
                "upload_id": str(upload.id),
                "filename": upload.filename,
                "content_type": upload.content_type,
                "size_bytes": int(upload.size_bytes),
                "has_checksum": bool(upload.checksum),
            },
            actor_user_id=actor_user_id,
        )
        await db.commit()
        await db.refresh(upload)
        return upload

    # Returns missed channel data for client backfill; API route handlers call it to enforce application business rules.
    @staticmethod
    async def sync(db: AsyncSession, actor_user_id: UUID, req: SyncRequest) -> dict:
        from app.services.channel_service import ChannelService

        channel_state = {entry.channel_id: int(entry.last_seen_seq_id or 0) for entry in req.channels}
        channel_ids = list(channel_state.keys())
        membership_rows = await db.execute(
            select(ChannelMembership.channel_id, ChannelMembership.role)
            .where(ChannelMembership.user_id == actor_user_id)
            .where(ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]))
        )
        membership_map = {cid: role for cid, role in membership_rows.all()}
        # Choose the appropriate path based on whether `channel_ids` is true.
        if channel_ids:
            selected = sorted([cid for cid in channel_ids if cid in membership_map], key=lambda v: str(v))
        # Handle the alternate path after the preceding branch or loop does not produce a result.
        else:
            selected = sorted(list(membership_map.keys()), key=lambda v: str(v))

        channel_updates: list[dict] = []
        # Process each `cid` from `selected` to apply this step to the full collection.
        for cid in selected:
            patch = await ChannelService.get_channel_view(db, cid, actor_user_id)
            channel_updates.append(
                {
                    "channel_id": cid,
                    "patch": patch,
                    "updated_at": patch["updated_at"],
                }
            )

        messages_payload: list[Message] = []
        # Process each `cid` from `selected` to apply this step to the full collection.
        for cid in selected:
            seq_marker = channel_state.get(cid, 0)
            rows = await db.execute(
                select(Message)
                .where(Message.channel_id == cid, Message.seq_id > seq_marker, Message.deleted_at.is_(None))
                .order_by(Message.seq_id.asc())
            )
            messages_payload.extend(list(rows.scalars().all()))
        messages_payload = sorted(messages_payload, key=lambda m: (str(m.channel_id), int(m.seq_id)))[: req.limit]

        membership_updates: list[dict] = []
        # Run this conditional step only when `req.since is not None` is true.
        if req.since is not None:
            membership_event_rows = await db.execute(
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
            # Process each `event` from `membership_event_rows.scalars().all()` to apply this step to the full collection.
            for event in membership_event_rows.scalars().all():
                payload = event.payload or {}
                channel_id_raw = payload.get("channel_id") or event.channel_id
                user_id_raw = payload.get("user_id") or event.actor_user_id
                # Skip the current item when `not channel_id_raw or not user_id_raw` and continue processing the rest.
                if not channel_id_raw or not user_id_raw:
                    continue
                new_role = str(payload.get("new_role") or "none")
                membership_updates.append(
                    {
                        "channel_id": channel_id_raw,
                        "user_id": user_id_raw,
                        "new_role": new_role if new_role in {"owner", "admin", "member", "pending", "none"} else "none",
                        "reason": str(payload.get("reason") or event.event_type),
                        "updated_at": event.created_at,
                    }
                )

        return {
            "server_time": utcnow(),
            "channel_updates": channel_updates,
            "membership_updates": membership_updates,
            "messages": messages_payload,
        }

    # Stores upload content; API route handlers call it to enforce application business rules.
    @staticmethod
    async def store_upload_content(
        db: AsyncSession,
        actor_user_id: UUID,
        file_id: UUID,
        content: bytes,
    ) -> Upload:
        settings = get_settings()
        upload = await db.get(Upload, file_id)
        # Reject the operation when `not upload or upload.owner_user_id != actor_user_id` to keep invalid state from progressing.
        if not upload or upload.owner_user_id != actor_user_id:
            raise AppError("upload not found", 404, code="NOT_FOUND")
        # Run this conditional step only when `len(content) != upload.size_bytes` is true.
        if len(content) != upload.size_bytes:
            await MessageService._safe_log_event(
                db,
                "upload.store_failed",
                {
                    "upload_id": str(file_id),
                    "reason": "size_mismatch",
                    "expected_size_bytes": int(upload.size_bytes),
                    "actual_size_bytes": len(content),
                },
                actor_user_id=actor_user_id,
                commit=True,
            )
            raise AppError("uploaded size mismatch", 400, code="VALIDATION_ERROR")
        # Run this conditional step only when `upload.checksum` is true.
        if upload.checksum:
            digest = hashlib.sha256(content).hexdigest()
            # Run this conditional step only when `digest != upload.checksum` is true.
            if digest != upload.checksum:
                await MessageService._safe_log_event(
                    db,
                    "upload.store_failed",
                    {
                        "upload_id": str(file_id),
                        "reason": "checksum_mismatch",
                    },
                    actor_user_id=actor_user_id,
                    commit=True,
                )
                raise AppError("checksum mismatch", 400, code="VALIDATION_ERROR")

        full_path = MessageService._resolve_upload_path(settings.uploads_base_dir, upload.storage_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        upload.public_url = f"/v1/uploads/{upload.id}/content"
        await log_event(
            db,
            "upload.content_stored",
            {
                "upload_id": str(upload.id),
                "filename": upload.filename,
                "content_type": upload.content_type,
                "size_bytes": int(upload.size_bytes),
            },
            actor_user_id=actor_user_id,
        )
        await db.commit()
        await db.refresh(upload)
        return upload

    # Validates profile image upload reference; API route handlers call it to enforce application business rules.
    @staticmethod
    async def validate_profile_image_upload_reference(
        db: AsyncSession,
        actor_user_id: UUID,
        image_url: str | None,
        *,
        label: str = "image",
    ) -> None:
        upload_id = extract_upload_id_from_url(image_url)
        # Return early when `upload_id is None` because the remaining work is not applicable.
        if upload_id is None:
            return

        upload = await db.get(Upload, upload_id)
        # Reject the operation when `not upload or upload.owner_user_id != actor_user_id` to keep invalid state from progressing.
        if not upload or upload.owner_user_id != actor_user_id:
            raise AppError(f"{label} upload not found", 404, code="NOT_FOUND")
        content_type = (upload.content_type or "").lower()
        # Reject the operation when `not content_type.startswith('image/') or content_type == 'image/svg+xml'` to keep invalid state from progressing.
        if not content_type.startswith("image/") or content_type == "image/svg+xml":
            raise AppError(f"{label} upload must be a non-SVG image", 400, code="VALIDATION_ERROR")
        # Reject the operation when `not upload.public_url` to keep invalid state from progressing.
        if not upload.public_url:
            raise AppError(f"{label} upload content has not been stored", 400, code="VALIDATION_ERROR")

    # Validates avatar upload reference; API route handlers call it to enforce application business rules.
    @staticmethod
    async def validate_avatar_upload_reference(db: AsyncSession, actor_user_id: UUID, avatar_url: str | None) -> None:
        await MessageService.validate_profile_image_upload_reference(
            db,
            actor_user_id,
            avatar_url,
            label="avatar",
        )

    # Resolves upload path; API route handlers call it to enforce application business rules.
    @staticmethod
    def _resolve_upload_path(base_dir_value: str, storage_path: str) -> Path:
        base_dir = Path(base_dir_value).resolve()
        full_path = (base_dir / storage_path).resolve()
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            full_path.relative_to(base_dir)
        # Handle `ValueError` here so this workflow can recover or report the failure consistently.
        except ValueError as exc:
            raise AppError("upload not found", 404, code="NOT_FOUND") from exc
        return full_path

    # Checks whether the current user may read an upload; API route handlers call it to enforce application business rules.
    @staticmethod
    async def can_access_upload(db: AsyncSession, actor_user_id: UUID, file_id: UUID) -> bool:
        upload = await db.get(Upload, file_id)
        # Return early when `not upload` because the remaining work is not applicable.
        if not upload:
            return False
        # Return early when `upload.owner_user_id == actor_user_id` because the remaining work is not applicable.
        if upload.owner_user_id == actor_user_id:
            return True
        # Return early when `await MessageService._can_access_avatar_upload(db, actor_user_id, fil...` because the remaining work is not applicable.
        if await MessageService._can_access_avatar_upload(db, actor_user_id, file_id):
            return True
        memberships = await db.execute(
            select(ChannelMembership.channel_id).where(
                ChannelMembership.user_id == actor_user_id,
                ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
            )
        )
        member_channels = set(memberships.scalars().all())
        # Return early when `not member_channels` because the remaining work is not applicable.
        if not member_channels:
            return False
        rows = await db.execute(select(Message).where(Message.deleted_at.is_(None), Message.attachments.is_not(None)))
        file_id_raw = str(file_id)
        # Process each `message` from `rows.scalars().all()` to apply this step to the full collection.
        for message in rows.scalars().all():
            # Skip the current item when `message.channel_id not in member_channels` and continue processing the rest.
            if message.channel_id not in member_channels:
                continue
            # Process each `item` from `message.attachments or []` to apply this step to the full collection.
            for item in (message.attachments or []):
                item_file_id = str(item.get("file_id") or "")
                # Return early when `item_file_id == file_id_raw` because the remaining work is not applicable.
                if item_file_id == file_id_raw:
                    return True
        return False

    # Checks whether an avatar upload may be read; API route handlers call it to enforce application business rules.
    @staticmethod
    async def _can_access_avatar_upload(db: AsyncSession, actor_user_id: UUID, file_id: UUID) -> bool:
        file_id_raw = str(file_id)
        user_rows = await db.execute(
            select(User.avatar_url).where(
                User.avatar_url.is_not(None),
                User.avatar_url.contains(file_id_raw),
            )
        )
        # Return early when `any((extract_upload_id_from_url(avatar_url) == file_id for avatar_url...` because the remaining work is not applicable.
        if any(extract_upload_id_from_url(avatar_url) == file_id for avatar_url in user_rows.scalars().all()):
            return True

        channel_rows = await db.execute(
            select(Channel).where(
                Channel.deleted_at.is_(None),
                Channel.avatar_url.is_not(None),
                Channel.avatar_url.contains(file_id_raw),
            )
        )
        # Process each `channel` from `channel_rows.scalars().all()` to apply this step to the full collection.
        for channel in channel_rows.scalars().all():
            # Skip the current item when `extract_upload_id_from_url(channel.avatar_url) != file_id` and continue processing the rest.
            if extract_upload_id_from_url(channel.avatar_url) != file_id:
                continue
            # Return early when `channel.visibility == ChannelVisibility.public` because the remaining work is not applicable.
            if channel.visibility == ChannelVisibility.public:
                return True
            membership = await db.get(ChannelMembership, {"channel_id": channel.id, "user_id": actor_user_id})
            # Return early when `membership and membership.role in {MembershipRole.owner, MembershipRo...` because the remaining work is not applicable.
            if membership and membership.role in {MembershipRole.owner, MembershipRole.admin, MembershipRole.member}:
                return True
        return False

    # Normalizes attachments; API route handlers call it to enforce application business rules.
    @staticmethod
    async def _normalize_attachments(
        db: AsyncSession,
        actor_user_id: UUID,
        attachments: list[AttachmentReference | dict] | None,
    ) -> list[dict] | None:
        # Return early when `not attachments` because the remaining work is not applicable.
        if not attachments:
            return attachments
        # Reject the operation when `len(attachments) > 10` to keep invalid state from progressing.
        if len(attachments) > 10:
            raise AppError("too many attachments", 400, code="VALIDATION_ERROR")
        normalized: list[dict] = []
        seen_file_ids: set[UUID] = set()
        # Process each `raw_item` from `attachments` to apply this step to the full collection.
        for raw_item in attachments:
            file_id_raw = raw_item.file_id if isinstance(raw_item, AttachmentReference) else raw_item.get("file_id")
            # Reject the operation when `not file_id_raw` to keep invalid state from progressing.
            if not file_id_raw:
                raise AppError("attachment.file_id is required", 400, code="VALIDATION_ERROR")
            # Attempt this operation and handle expected failures in the exception branches below.
            try:
                file_id = UUID(str(file_id_raw))
            # Handle `ValueError` here so this workflow can recover or report the failure consistently.
            except ValueError as exc:
                raise AppError("invalid attachment file_id", 400, code="VALIDATION_ERROR") from exc
            # Reject the operation when `file_id in seen_file_ids` to keep invalid state from progressing.
            if file_id in seen_file_ids:
                raise AppError("duplicate attachment file_id", 400, code="VALIDATION_ERROR")
            seen_file_ids.add(file_id)
            upload = await db.get(Upload, file_id)
            # Reject the operation when `upload is None` to keep invalid state from progressing.
            if upload is None:
                raise AppError("attachment file not found", 404, code="NOT_FOUND")
            # Reject the operation when `upload.owner_user_id != actor_user_id` to keep invalid state from progressing.
            if upload.owner_user_id != actor_user_id:
                raise AppError("forbidden attachment", 403, code="FORBIDDEN")
            # Reject the operation when `not upload.public_url` to keep invalid state from progressing.
            if not upload.public_url:
                raise AppError("attachment content has not been uploaded", 400, code="VALIDATION_ERROR")
            normalized.append(
                {
                    "file_id": str(file_id),
                    "content_type": upload.content_type,
                    "filename": upload.filename,
                    "size_bytes": int(upload.size_bytes),
                    "url": f"/v1/uploads/{file_id}/content",
                }
            )
        return normalized
