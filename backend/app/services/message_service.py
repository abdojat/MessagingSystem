from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path
from datetime import timedelta
import hashlib
import logging
import os
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
    MessageAttachment,
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
from app.core.payload_limits import PROTOCOL_CHANNEL_ARRAY_MAX, normalize_reaction

logger = logging.getLogger(__name__)


class MessageService:
    """Owns message persistence, encryption, upload policy, and delivery outbox records."""

    @staticmethod
    async def _safe_log_event(
        db: AsyncSession,
        event_type: str,
        payload: dict,
        channel_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        commit: bool = False,
    ) -> None:
        # Security/audit events are useful, but a failed audit write should not
        # hide the original authorization or validation error from the caller.
        try:
            await log_event(db, event_type, payload, channel_id=channel_id, actor_user_id=actor_user_id)
            if commit:
                await db.commit()
        except Exception:
            await db.rollback()
            logger.warning("failed to log event %s", event_type, exc_info=True)

    @staticmethod
    def _decrypt_message_content(message: Message) -> tuple[str | None, dict | None]:
        if message.content_type == ContentType.text:
            if message.content_text is None:
                return None, None
            return decrypt_message(message.content_text), None
        if message.content_type == ContentType.json:
            return None, decrypt_json_payload(message.content_json)
        raise AppError("unsupported content type", 500, code="DECRYPTION_FAILED")

    @staticmethod
    def _encrypt_payload(req: PublishMessageRequest | MessagePatchRequest) -> tuple[str | None, dict | None]:
        if req.content_text is not None:
            return encrypt_message(req.content_text), None
        if req.content_json is not None:
            return None, encrypt_json_payload(req.content_json)
        return None, None

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
        if not is_deleted:
            # Outbox and REST responses both expose plaintext only after service
            # authorization has succeeded; deleted messages stay as tombstones.
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

    @staticmethod
    def _serialize_message_for_outbox(
        message: Message,
        *,
        sender_username: str | None = None,
        sender_display_name: str | None = None,
        sender_avatar_url: str | None = None,
    ) -> dict:
        is_deleted = message.deleted_at is not None
        # Outbox payloads carry encrypted content because the worker and broker
        # should not need plaintext access to fan messages out to subscribers.
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

    @staticmethod
    async def _load_sender_profile(
        db: AsyncSession,
        sender_user_id: UUID,
    ) -> tuple[str | None, str | None, str | None]:
        sender = await db.get(User, sender_user_id)
        if sender is None:
            return None, None, None
        return sender.username, sender.display_name, sender.avatar_url

    @staticmethod
    async def publish_message(db: AsyncSession, channel_id: UUID, sender_id: UUID, req: PublishMessageRequest) -> Message:
        # Lock the channel row while assigning seq_id so each channel keeps a
        # stable per-topic ordering without requiring global message ordering.
        channel_row = await db.execute(select(Channel).where(Channel.id == channel_id).with_for_update())
        channel = channel_row.scalar_one_or_none()
        if not channel or channel.deleted_at is not None:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        membership = await db.get(ChannelMembership, {"channel_id": channel_id, "user_id": sender_id})
        role = membership.role if membership else None
        is_member_reply = role == MembershipRole.member and (
            req.reply_to_message_id is not None or req.reply_to_seq_id is not None
        )
        # Members can reply even when normal publishing is reserved for admins,
        # which keeps moderated channels usable for threaded responses.
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

        if req.client_msg_id is not None:
            # Client message ids make retries idempotent when a browser resends
            # after losing the HTTP response.
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

        try:
            encrypted_text, encrypted_json = MessageService._encrypt_payload(req)
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
        for attachment in attachments or []:
            db.add(
                MessageAttachment(
                    message_id=message.id,
                    channel_id=channel_id,
                    upload_id=UUID(str(attachment["file_id"])),
                )
            )
        if attachments:
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
        # Message, encrypted payload, delivery outbox, and audit log commit
        # together; the worker publishes only after this source-of-truth write.
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            if req.client_msg_id is not None:
                conflict = await db.execute(
                    select(Message).where(
                        Message.channel_id == channel_id,
                        Message.sender_user_id == sender_id,
                        Message.client_msg_id == req.client_msg_id,
                    )
                )
                existing_message = conflict.scalar_one_or_none()
                if existing_message is not None:
                    return existing_message
            raise AppError("message conflict", 409, code="CONFLICT") from exc
        await db.refresh(message)
        return message

    @staticmethod
    async def _resolve_reply_target(
        db: AsyncSession,
        channel_id: UUID,
        reply_to_message_id: UUID | None,
        reply_to_seq_id: int | None,
    ) -> tuple[UUID | None, int | None]:
        if reply_to_message_id is None and reply_to_seq_id is None:
            return None, None

        target: Message | None = None
        if reply_to_message_id is not None:
            target = await db.get(Message, reply_to_message_id)
            if target is None or target.channel_id != channel_id or target.deleted_at is not None:
                raise AppError("reply target not found", 404, code="MESSAGE_NOT_FOUND")
            if reply_to_seq_id is not None and int(target.seq_id) != int(reply_to_seq_id):
                raise AppError("reply target mismatch", 400, code="VALIDATION_ERROR")
        else:
            rows = await db.execute(
                select(Message).where(
                    Message.channel_id == channel_id,
                    Message.seq_id == int(reply_to_seq_id),
                    Message.deleted_at.is_(None),
                )
            )
            target = rows.scalar_one_or_none()
            if target is None:
                raise AppError("reply target not found", 404, code="MESSAGE_NOT_FOUND")

        return target.id, int(target.seq_id)

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
        if order is None:
            order = "asc" if after_seq_id is not None else "desc"
        if order not in {"asc", "desc"}:
            raise AppError("order must be asc or desc", 400, code="VALIDATION_ERROR")

        # Message history is paged by per-channel sequence numbers because they
        # are stable across refreshes and simpler to reason about than timestamps.
        stmt = select(Message).where(Message.channel_id == channel_id)
        stmt = stmt.where(Message.deleted_at.is_(None))
        if before_seq_id is not None:
            stmt = stmt.where(Message.seq_id < before_seq_id)
        if after_seq_id is not None:
            stmt = stmt.where(Message.seq_id > after_seq_id)
        stmt = stmt.order_by(Message.seq_id.asc() if order == "asc" else Message.seq_id.desc())

        rows = await db.execute(stmt.limit(limit + 1))
        values = list(rows.scalars().all())
        has_more = len(values) > limit
        page = values[:limit]

        if not page:
            return page, None, None, has_more

        # Return the next cursor matching the requested direction so clients can
        # page older and newer history without guessing from item order.
        next_before_seq_id = None
        next_after_seq_id = None
        if order == "desc":
            next_before_seq_id = min(m.seq_id for m in page)
        else:
            next_after_seq_id = max(m.seq_id for m in page)
        return page, next_before_seq_id, next_after_seq_id, has_more

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

    @staticmethod
    async def mark_seen(db: AsyncSession, channel_id: UUID, user_id: UUID, req: SeenRequest) -> UserChannelState:
        # Seen/unread state is derived from private message history, so it uses
        # the same approved-reader check as history, sync, and WebSocket resume.
        await MessageService._assert_can_read(
            db,
            channel_id,
            user_id,
            lock_channel=True,
            lock_membership=True,
        )
        channel = await db.get(Channel, channel_id)
        if channel is None:  # Defensive; _assert_can_read already checks this.
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")

        state_rows = await db.execute(
            select(UserChannelState)
            .where(UserChannelState.channel_id == channel_id, UserChannelState.user_id == user_id)
            .with_for_update()
        )
        state = state_rows.scalar_one_or_none()

        requested_seq: int | None = None
        requested_message_id: UUID | None = None
        clear_message_id = False
        if req.last_seen_message_id is not None:
            message = await db.get(Message, req.last_seen_message_id)
            if not message or message.channel_id != channel_id:
                raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
            requested_seq = int(message.seq_id)
            requested_message_id = message.id
        if req.last_seen_seq_id is not None:
            requested_seq = int(req.last_seen_seq_id)
            clear_message_id = True

        if requested_seq is not None and requested_seq > int(channel.last_seq_id or 0):
            raise AppError("last_seen_seq_id out of range", 400, code="VALIDATION_ERROR")

        if requested_seq is None:
            raise AppError("seen marker is required", 400, code="VALIDATION_ERROR")

        current_seen_seq = int(state.last_seen_seq_id or 0) if state is not None else -1
        # Seen markers only move forward, so an older client cannot erase unread
        # progress that was recorded by a newer tab or device.
        if state is not None and requested_seq <= current_seen_seq:
            return state

        if state is None:
            state = UserChannelState(channel_id=channel_id, user_id=user_id)
            db.add(state)

        state.last_seen_seq_id = requested_seq
        if clear_message_id:
            state.last_seen_message_id = None
        else:
            state.last_seen_message_id = requested_message_id
        if req.last_seen_at is not None:
            state.last_seen_at = req.last_seen_at
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

    @staticmethod
    async def _assert_can_read(
        db: AsyncSession,
        channel_id: UUID,
        user_id: UUID,
        *,
        lock_channel: bool = False,
        lock_membership: bool = False,
    ) -> MembershipRole:
        channel_stmt = select(Channel).where(Channel.id == channel_id)
        if lock_channel:
            channel_stmt = channel_stmt.with_for_update(read=True)
        channel = (await db.execute(channel_stmt)).scalar_one_or_none()
        if not channel or channel.deleted_at is not None:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        membership_stmt = select(ChannelMembership).where(
            ChannelMembership.channel_id == channel_id,
            ChannelMembership.user_id == user_id,
        )
        if lock_membership:
            membership_stmt = membership_stmt.with_for_update()
        membership = (await db.execute(membership_stmt)).scalar_one_or_none()
        role = membership.role if membership else None
        if not can_read(role):
            # Private channel probing is recorded as a security event for the
            # event-log requirement and for supervisor-demo visibility.
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

    @staticmethod
    async def edit_message(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        message_id: UUID,
        req: MessagePatchRequest,
    ) -> Message:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id, lock_channel=True)
        message_rows = await db.execute(
            select(Message).where(Message.id == message_id).with_for_update()
        )
        message = message_rows.scalar_one_or_none()
        if not message or message.channel_id != channel_id or message.deleted_at is not None:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        if message.sender_user_id != actor_user_id and role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")

        try:
            # Edits reuse the same encryption path as publishing so stored
            # message bodies keep one at-rest format.
            encrypted_text, encrypted_json = MessageService._encrypt_payload(req)
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
        # Message edits are sent through the outbox like new publications so
        # realtime subscribers and REST history converge on the same payload.
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

    @staticmethod
    async def delete_message(
        db: AsyncSession,
        channel_id: UUID,
        actor_user_id: UUID,
        message_id: UUID,
    ) -> Message:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id, lock_channel=True)
        message = (
            await db.execute(select(Message).where(Message.id == message_id).with_for_update())
        ).scalar_one_or_none()
        if not message or message.channel_id != channel_id:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        if message.sender_user_id != actor_user_id and role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        if message.deleted_at is None:
            # Deletion is a tombstone: content is removed from future reads while
            # the sequence number and reply relationships stay stable.
            message.deleted_at = utcnow()
            message.updated_at = message.deleted_at
            message.content_text = None
            message.content_json = None
            await db.flush()
            sender_username, sender_display_name, sender_avatar_url = await MessageService._load_sender_profile(
                db,
                message.sender_user_id,
            )
            # Subscribers receive the tombstone through the same update path used
            # for edits, which keeps client cache handling simple.
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

    @staticmethod
    async def _reaction_summary(db: AsyncSession, message_id: UUID, actor_user_id: UUID) -> dict:
        return (await MessageService._reaction_summaries(db, [message_id], actor_user_id))[message_id]

    @staticmethod
    async def _reaction_summaries(
        db: AsyncSession,
        message_ids: list[UUID],
        actor_user_id: UUID,
    ) -> dict[UUID, dict]:
        unique_ids = list(dict.fromkeys(message_ids))
        summaries = {message_id: {"counts": {}, "my_reaction": []} for message_id in unique_ids}
        if not unique_ids:
            return summaries
        rows = await db.execute(
            select(MessageReaction.message_id, MessageReaction.emoji, func.count(MessageReaction.id))
            .where(MessageReaction.message_id.in_(unique_ids))
            .group_by(MessageReaction.message_id, MessageReaction.emoji)
        )
        mine_rows = await db.execute(
            select(MessageReaction.message_id, MessageReaction.emoji).where(
                MessageReaction.message_id.in_(unique_ids),
                MessageReaction.user_id == actor_user_id,
            ).order_by(MessageReaction.message_id.asc(), MessageReaction.emoji.asc())
        )
        for message_id, emoji, count in rows.all():
            summaries[message_id]["counts"][emoji] = int(count)
        for message_id, emoji in mine_rows.all():
            summaries[message_id]["my_reaction"].append(emoji)
        return summaries

    @staticmethod
    async def add_reaction(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID, emoji: str) -> dict:
        try:
            emoji = normalize_reaction(emoji)
        except ValueError as exc:
            raise AppError(str(exc), 400, code="VALIDATION_ERROR") from exc
        await MessageService._assert_can_read(db, channel_id, actor_user_id, lock_channel=True)
        message_rows = await db.execute(
            select(Message).where(Message.id == message_id).with_for_update()
        )
        message = message_rows.scalar_one_or_none()
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
        if existing_reaction is None:
            distinct_rows = await db.execute(
                select(MessageReaction.emoji).where(MessageReaction.message_id == message_id).distinct()
            )
            distinct_emoji = set(distinct_rows.scalars().all())
            if (
                emoji not in distinct_emoji
                and len(distinct_emoji) >= get_settings().max_distinct_reactions_per_message
            ):
                raise AppError("message reaction variety quota exceeded", 409, code="REACTION_QUOTA_EXCEEDED")
            # Reactions are idempotent per user/message/emoji; duplicate taps
            # should return the current summary without creating another row.
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
        if existing_reaction is None:
            # Only a real state change is broadcast, keeping reaction update
            # traffic quiet for duplicate client retries.
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

    @staticmethod
    async def remove_reaction(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID, emoji: str) -> dict:
        try:
            emoji = normalize_reaction(emoji)
        except ValueError as exc:
            raise AppError(str(exc), 400, code="VALIDATION_ERROR") from exc
        await MessageService._assert_can_read(db, channel_id, actor_user_id, lock_channel=True)
        message = (
            await db.execute(select(Message).where(Message.id == message_id).with_for_update())
        ).scalar_one_or_none()
        if not message or message.channel_id != channel_id or message.deleted_at is not None:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        delete_result = await db.execute(
            delete(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == actor_user_id,
                MessageReaction.emoji == emoji,
            )
        )
        summary = await MessageService._reaction_summary(db, message_id, actor_user_id)
        if int(delete_result.rowcount or 0) > 0:
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

    @staticmethod
    async def pin_message(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID) -> None:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id, lock_channel=True)
        if role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        message = (
            await db.execute(select(Message).where(Message.id == message_id).with_for_update())
        ).scalar_one_or_none()
        if not message or message.channel_id != channel_id:
            raise AppError("message not found", 404, code="MESSAGE_NOT_FOUND")
        existing = await db.get(PinnedMessage, {"channel_id": channel_id, "message_id": message_id})
        if not existing:
            # The separate pin row records who pinned it, while the denormalized
            # message flag keeps list rendering cheap.
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

    @staticmethod
    async def unpin_message(db: AsyncSession, channel_id: UUID, message_id: UUID, actor_user_id: UUID) -> None:
        role = await MessageService._assert_can_read(db, channel_id, actor_user_id, lock_channel=True)
        if role not in {MembershipRole.owner, MembershipRole.admin}:
            raise AppError("forbidden", 403, code="FORBIDDEN")
        message = (
            await db.execute(select(Message).where(Message.id == message_id).with_for_update())
        ).scalar_one_or_none()
        pin = await db.get(PinnedMessage, {"channel_id": channel_id, "message_id": message_id})
        if pin:
            await db.delete(pin)
        if message and message.channel_id == channel_id:
            # Missing message rows are tolerated during unpin so cleanup remains
            # idempotent, but existing messages still broadcast their new state.
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
            raise AppError("file too large", 400, code="VALIDATION_ERROR")
        content_type = req.content_type.strip().lower()
        media_type = content_type.split(";", 1)[0].strip()
        if "/" not in media_type:
            raise AppError("invalid content_type", 400, code="VALIDATION_ERROR")
        allowed_prefixes = ("image/", "video/", "audio/", "text/")
        allowed_exact = {"application/json", "application/pdf"}
        if not (media_type.startswith(allowed_prefixes) or media_type in allowed_exact):
            raise AppError("content_type not allowed", 400, code="VALIDATION_ERROR")
        if media_type == "image/svg+xml":
            raise AppError("svg uploads are not allowed", 400, code="VALIDATION_ERROR")
        await db.execute(select(User).where(User.id == actor_user_id).with_for_update())
        quota_rows = await db.execute(
            select(
                func.count(Upload.id).filter(Upload.created_at >= utcnow() - timedelta(days=1)),
                func.count(Upload.id).filter(Upload.public_url.is_(None)),
                func.coalesce(func.sum(Upload.size_bytes), 0),
            ).where(Upload.owner_user_id == actor_user_id)
        )
        uploads_today, pending_uploads, reserved_bytes = quota_rows.one()
        if int(uploads_today or 0) >= settings.max_uploads_per_user_per_day:
            raise AppError("daily upload quota exceeded", 429, code="RESOURCE_QUOTA_EXCEEDED")
        if int(pending_uploads or 0) >= settings.max_pending_uploads_per_user:
            raise AppError("pending upload quota exceeded", 429, code="RESOURCE_QUOTA_EXCEEDED")
        if int(reserved_bytes or 0) + req.size_bytes > settings.max_stored_upload_bytes_per_user:
            raise AppError("upload storage quota exceeded", 429, code="RESOURCE_QUOTA_EXCEEDED")
        safe_filename = normalize_upload_filename(req.filename)
        # The display filename is preserved, but storage uses a normalized path
        # under the user's id to avoid path traversal and accidental collisions.
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

    @staticmethod
    async def sync(db: AsyncSession, actor_user_id: UUID, req: SyncRequest) -> dict:
        from app.services.channel_service import ChannelService

        # REST sync is the durable backfill path for missed WebSocket messages;
        # requested channels are intersected with memberships before any data is read.
        channel_state = {entry.channel_id: int(entry.last_seen_seq_id or 0) for entry in req.channels}
        channel_ids = list(channel_state.keys())
        membership_rows = await db.execute(
            select(ChannelMembership.channel_id, ChannelMembership.role)
            .where(ChannelMembership.user_id == actor_user_id)
            .where(ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]))
        )
        membership_map = {cid: role for cid, role in membership_rows.all()}
        if channel_ids:
            selected = sorted([cid for cid in channel_ids if cid in membership_map], key=lambda v: str(v))
        else:
            selected = sorted(list(membership_map.keys()), key=lambda v: str(v))[:PROTOCOL_CHANNEL_ARRAY_MAX]

        channel_updates: list[dict] = []
        for cid in selected:
            patch = await ChannelService.get_channel_view(db, cid, actor_user_id)
            channel_updates.append(
                {
                    "channel_id": cid,
                    "patch": patch,
                    "updated_at": patch["updated_at"],
                }
            )

        # Preserve the existing deterministic (channel UUID, sequence) order,
        # while treating req.limit as one global materialization budget. Every
        # per-channel query receives only the remaining budget and has a SQL
        # LIMIT, so at most req.limit Message objects enter Python.
        messages_payload: list[Message] = []
        remaining = int(req.limit)
        for cid in selected:
            if remaining <= 0:
                break
            seq_marker = channel_state.get(cid, 0)
            channel_page = await MessageService._fetch_sync_message_page(
                db,
                cid,
                seq_marker,
                remaining,
            )
            messages_payload.extend(channel_page)
            remaining -= len(channel_page)

        membership_updates: list[dict] = []
        if req.since is not None:
            actor_user_id_raw = str(actor_user_id)
            event_visibility = [
                Event.payload["user_id"].as_string() == actor_user_id_raw,
                Event.payload["target_user_id"].as_string() == actor_user_id_raw,
            ]
            if membership_map:
                event_visibility.append(Event.channel_id.in_(list(membership_map.keys())))
            membership_event_rows = await db.execute(
                select(Event)
                .where(
                    Event.created_at >= req.since,
                    or_(
                        Event.event_type.like("membership.%"),
                        Event.event_type.like("member.%"),
                        Event.event_type == "invite.accepted",
                    ),
                    or_(*event_visibility),
                )
                .order_by(Event.created_at.asc())
                .limit(max(1, req.limit))
            )
            for event in membership_event_rows.scalars().all():
                payload = event.payload or {}
                channel_id_raw = payload.get("channel_id") or event.channel_id
                user_id_raw = payload.get("user_id") or payload.get("target_user_id")
                if not channel_id_raw or not user_id_raw:
                    continue
                try:
                    channel_id_value = UUID(str(channel_id_raw))
                    target_user_id = UUID(str(user_id_raw))
                except (TypeError, ValueError):
                    continue
                # Keep this post-query authorization check as defense in depth
                # for legacy or malformed event payloads.
                if channel_id_value not in membership_map and target_user_id != actor_user_id:
                    continue
                new_role = MessageService._membership_event_new_role(event.event_type, payload)
                membership_updates.append(
                    {
                        "channel_id": channel_id_value,
                        "user_id": target_user_id,
                        "new_role": new_role,
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

    @staticmethod
    async def _fetch_sync_message_page(
        db: AsyncSession,
        channel_id: UUID,
        after_seq_id: int,
        limit: int,
    ) -> list[Message]:
        bounded_limit = max(1, int(limit))
        rows = await db.execute(
            select(Message)
            .where(
                Message.channel_id == channel_id,
                Message.seq_id > int(after_seq_id),
                Message.deleted_at.is_(None),
            )
            .order_by(Message.seq_id.asc(), Message.id.asc())
            .limit(bounded_limit)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def store_upload_content(
        db: AsyncSession,
        actor_user_id: UUID,
        file_id: UUID,
        content: AsyncIterable[bytes] | bytes | bytearray | memoryview,
    ) -> Upload:
        settings = get_settings()
        upload_result = await db.execute(select(Upload).where(Upload.id == file_id).with_for_update())
        upload = upload_result.scalar_one_or_none()
        # A user may only provide bytes for an upload record they created; later
        # reads are authorized through ownership or message/channel membership.
        if not upload or upload.owner_user_id != actor_user_id:
            raise AppError("upload not found", 404, code="NOT_FOUND")

        full_path = MessageService._resolve_upload_path(settings.uploads_base_dir, upload.storage_path)
        # The upload path resolver enforces containment; creating parents here is
        # only for the generated storage layout, not user-controlled directories.
        full_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = full_path.with_name(f".{full_path.name}.{uuid4()}.uploading")
        expected_size = int(upload.size_bytes)
        configured_max = max(1, int(settings.upload_max_size_bytes))
        total_size = 0
        digest = hashlib.sha256()
        finalized_here = False
        failure_reason = "storage_error"

        try:
            # public_url is the existing persisted lifecycle marker: None means
            # pending and a protected content URL means successfully finalized.
            if upload.public_url or full_path.exists():
                failure_reason = "already_stored"
                raise AppError("upload content is already stored", 409, code="UPLOAD_IMMUTABLE")
            if expected_size > configured_max:
                failure_reason = "configured_size_exceeded"
                raise AppError("file too large", 413, code="PAYLOAD_TOO_LARGE")

            with temp_path.open("xb") as destination:
                async for received in MessageService._iter_upload_chunks(content):
                    if not isinstance(received, (bytes, bytearray, memoryview)):
                        failure_reason = "invalid_stream_chunk"
                        raise AppError("invalid upload stream", 400, code="VALIDATION_ERROR")
                    # Keep write/hash operations bounded even if an ASGI server
                    # supplies an unusually large receive chunk.
                    view = memoryview(received)
                    for offset in range(0, len(view), 64 * 1024):
                        chunk = view[offset : offset + 64 * 1024]
                        next_total = total_size + len(chunk)
                        if next_total > configured_max:
                            failure_reason = "configured_size_exceeded"
                            raise AppError("file too large", 413, code="PAYLOAD_TOO_LARGE")
                        if next_total > expected_size:
                            failure_reason = "size_mismatch"
                            raise AppError("uploaded size mismatch", 400, code="VALIDATION_ERROR")
                        destination.write(chunk)
                        digest.update(chunk)
                        total_size = next_total
                destination.flush()
                os.fsync(destination.fileno())

            if total_size != expected_size:
                failure_reason = "size_mismatch"
                raise AppError("uploaded size mismatch", 400, code="VALIDATION_ERROR")
            if upload.checksum and digest.hexdigest().lower() != upload.checksum.strip().lower():
                failure_reason = "checksum_mismatch"
                raise AppError("checksum mismatch", 400, code="VALIDATION_ERROR")

            # A same-directory hard link atomically exposes only the complete
            # file and fails rather than overwriting an existing finalized path.
            try:
                os.link(temp_path, full_path)
            except FileExistsError as exc:
                failure_reason = "already_stored"
                raise AppError("upload content is already stored", 409, code="UPLOAD_IMMUTABLE") from exc
            finalized_here = True
            temp_path.unlink()

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
        except AppError:
            if finalized_here:
                full_path.unlink(missing_ok=True)
            # Discard any pending lifecycle mutation before the failure event is
            # written in a fresh transaction.
            await db.rollback()
            await MessageService._safe_log_event(
                db,
                "upload.store_failed",
                {
                    "upload_id": str(file_id),
                    "reason": failure_reason,
                    "expected_size_bytes": expected_size,
                    "actual_size_bytes": total_size,
                },
                actor_user_id=actor_user_id,
                commit=True,
            )
            raise
        except Exception as exc:
            if finalized_here:
                full_path.unlink(missing_ok=True)
            await db.rollback()
            await MessageService._safe_log_event(
                db,
                "upload.store_failed",
                {
                    "upload_id": str(file_id),
                    "reason": failure_reason,
                    "expected_size_bytes": expected_size,
                    "actual_size_bytes": total_size,
                },
                actor_user_id=actor_user_id,
                commit=True,
            )
            raise AppError("failed to store upload", 500, code="UPLOAD_STORE_FAILED") from exc
        finally:
            temp_path.unlink(missing_ok=True)

        await db.refresh(upload)
        return upload

    @staticmethod
    async def _iter_upload_chunks(
        content: AsyncIterable[bytes] | bytes | bytearray | memoryview,
    ) -> AsyncIterator[bytes | bytearray | memoryview]:
        if isinstance(content, (bytes, bytearray, memoryview)):
            view = memoryview(content)
            for offset in range(0, len(view), 64 * 1024):
                yield view[offset : offset + 64 * 1024]
            return
        async for chunk in content:
            yield chunk

    @staticmethod
    def _membership_event_new_role(event_type: str, payload: dict) -> str:
        explicit_role = str(payload.get("new_role") or payload.get("role") or "").lower()
        if explicit_role in {"owner", "admin", "member", "pending", "none"}:
            return explicit_role
        inferred_roles = {
            "invite.accepted": "member",
            "membership.added": "member",
            "membership.approved": "member",
            "member.promoted": "admin",
            "member.demoted": "member",
            "member.permissions.updated": "admin",
            "member.removed": "none",
            "membership.left": "none",
        }
        return inferred_roles.get(event_type, "none")

    @staticmethod
    async def validate_profile_image_upload_reference(
        db: AsyncSession,
        actor_user_id: UUID,
        image_url: str | None,
        *,
        label: str = "image",
    ) -> None:
        upload_id = extract_upload_id_from_url(image_url)
        if upload_id is None:
            return

        upload = await db.get(Upload, upload_id)
        if not upload or upload.owner_user_id != actor_user_id:
            raise AppError(f"{label} upload not found", 404, code="NOT_FOUND")
        content_type = (upload.content_type or "").lower()
        if not content_type.startswith("image/") or content_type == "image/svg+xml":
            raise AppError(f"{label} upload must be a non-SVG image", 400, code="VALIDATION_ERROR")
        if not upload.public_url:
            raise AppError(f"{label} upload content has not been stored", 400, code="VALIDATION_ERROR")

    @staticmethod
    async def validate_avatar_upload_reference(db: AsyncSession, actor_user_id: UUID, avatar_url: str | None) -> None:
        await MessageService.validate_profile_image_upload_reference(
            db,
            actor_user_id,
            avatar_url,
            label="avatar",
        )

    @staticmethod
    def _resolve_upload_path(base_dir_value: str, storage_path: str) -> Path:
        base_dir = Path(base_dir_value).resolve()
        full_path = (base_dir / storage_path).resolve()
        # Storage paths come from the database, but this guard still prevents a
        # corrupt row from escaping the configured uploads directory.
        try:
            full_path.relative_to(base_dir)
        except ValueError as exc:
            raise AppError("upload not found", 404, code="NOT_FOUND") from exc
        return full_path

    @staticmethod
    async def can_access_upload(db: AsyncSession, actor_user_id: UUID, file_id: UUID) -> bool:
        upload = await db.get(Upload, file_id)
        if not upload:
            return False
        if upload.owner_user_id == actor_user_id:
            return True
        if await MessageService._can_access_avatar_upload(db, actor_user_id, file_id):
            return True
        # Attachment authorization follows the normalized, indexed relation;
        # it does not scan or deserialize arbitrary message history.
        access_row = await db.execute(
            select(MessageAttachment.upload_id)
            .join(
                ChannelMembership,
                and_(
                    ChannelMembership.channel_id == MessageAttachment.channel_id,
                    ChannelMembership.user_id == actor_user_id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                ),
            )
            .join(Message, Message.id == MessageAttachment.message_id)
            .join(Channel, Channel.id == MessageAttachment.channel_id)
            .where(
                MessageAttachment.upload_id == file_id,
                Message.deleted_at.is_(None),
                Channel.deleted_at.is_(None),
            )
            .limit(1)
        )
        return access_row.scalar_one_or_none() is not None

    @staticmethod
    async def _can_access_avatar_upload(db: AsyncSession, actor_user_id: UUID, file_id: UUID) -> bool:
        file_id_raw = str(file_id)
        user_rows = await db.execute(
            select(User.avatar_url).where(
                User.avatar_url.is_not(None),
                User.avatar_url.contains(file_id_raw),
            )
        )
        if any(extract_upload_id_from_url(avatar_url) == file_id for avatar_url in user_rows.scalars().all()):
            return True

        channel_rows = await db.execute(
            select(Channel).where(
                Channel.deleted_at.is_(None),
                Channel.avatar_url.is_not(None),
                Channel.avatar_url.contains(file_id_raw),
            )
        )
        for channel in channel_rows.scalars().all():
            if extract_upload_id_from_url(channel.avatar_url) != file_id:
                continue
            if channel.visibility == ChannelVisibility.public:
                return True
            membership = await db.get(ChannelMembership, {"channel_id": channel.id, "user_id": actor_user_id})
            if membership and membership.role in {MembershipRole.owner, MembershipRole.admin, MembershipRole.member}:
                return True
        return False

    @staticmethod
    async def _normalize_attachments(
        db: AsyncSession,
        actor_user_id: UUID,
        attachments: list[AttachmentReference | dict] | None,
    ) -> list[dict] | None:
        if not attachments:
            return attachments
        if len(attachments) > 10:
            raise AppError("too many attachments", 400, code="VALIDATION_ERROR")
        normalized: list[dict] = []
        seen_file_ids: set[UUID] = set()
        # Attachments must point to uploaded content owned by the publisher before
        # they can be linked into channel message history.
        for raw_item in attachments:
            file_id_raw = raw_item.file_id if isinstance(raw_item, AttachmentReference) else raw_item.get("file_id")
            if not file_id_raw:
                raise AppError("attachment.file_id is required", 400, code="VALIDATION_ERROR")
            try:
                file_id = UUID(str(file_id_raw))
            except ValueError as exc:
                raise AppError("invalid attachment file_id", 400, code="VALIDATION_ERROR") from exc
            if file_id in seen_file_ids:
                raise AppError("duplicate attachment file_id", 400, code="VALIDATION_ERROR")
            seen_file_ids.add(file_id)
            upload = await db.get(Upload, file_id)
            if upload is None:
                raise AppError("attachment file not found", 404, code="NOT_FOUND")
            if upload.owner_user_id != actor_user_id:
                raise AppError("forbidden attachment", 403, code="FORBIDDEN")
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
