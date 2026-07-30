import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import aio_pika
from fastapi import WebSocket
from redis.asyncio import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.core.encryption import decrypt_json_payload, decrypt_message
from app.core.utils import utcnow
from app.db.models import Channel, ChannelMembership, MembershipRole, Message, User
from app.mq.publisher import bind_user_channel, ensure_user_queue
from app.realtime.protocol import (
    WSResumePayload,
    WSSeenPayload,
    WSSubscribePayload,
    WSSyncPayload,
    WSUnsubscribePayload,
    build_envelope,
    build_error,
    parse_client_envelope,
)
from app.realtime.redis_pubsub import mark_user_offline, mark_user_online, user_pubsub_channel
from app.schemas.messages import SeenRequest
from app.services.message_service import MessageService

logger = logging.getLogger(__name__)


class WSManager:
    """Bridges authenticated WebSocket clients to Redis fanout and REST backfill."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: Redis, amqp: aio_pika.RobustConnection):
        self._session_factory = session_factory
        self._redis = redis
        self._amqp = amqp
        self._subscriptions: dict[int, set[str]] = {}
        self._connections: dict[UUID, dict[int, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: UUID, username: str, pre_accepted: bool = False) -> None:
        if not pre_accepted:
            await websocket.accept()
        await mark_user_online(self._redis, username)
        # Refresh broker bindings on connect so users who were offline during a
        # membership change still have the correct durable queues.
        await self._ensure_user_bindings(user_id, username)
        self._subscriptions[id(websocket)] = set(await self._member_channel_ids(user_id))
        self._connections.setdefault(user_id, {})[id(websocket)] = websocket

    async def disconnect(self, websocket: WebSocket, username: str) -> None:
        self._subscriptions.pop(id(websocket), None)
        for user_id, sockets in list(self._connections.items()):
            sockets.pop(id(websocket), None)
            if not sockets:
                self._connections.pop(user_id, None)
        await mark_user_offline(self._redis, username)

    async def disconnect_user(self, user_id: UUID, reason: str = "account deactivated") -> int:
        sockets = list(self._connections.get(user_id, {}).values())
        for websocket in sockets:
            try:
                await websocket.close(code=1008, reason=reason)
            except Exception:
                logger.exception("failed to close websocket for deactivated user", extra={"user_id": str(user_id)})
        return len(sockets)

    async def run_socket(self, websocket: WebSocket, user_id: UUID, username: str) -> None:
        await websocket.send_json(
            build_envelope(
                "hello",
                {
                    "server_time": utcnow().isoformat(),
                    "user_id": str(user_id),
                    "session_id": None,
                },
            )
        )

        redis_task = asyncio.create_task(self._redis_forward_loop(websocket, username))
        inbound_task = asyncio.create_task(self._inbound_loop(websocket, user_id))
        # The socket is alive while both loops are alive; if either side exits,
        # cancel the other side and let the route perform disconnect cleanup.
        done, pending = await asyncio.wait({redis_task, inbound_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception():
                raise task.exception()

    async def _member_channel_ids(self, user_id: UUID) -> list[str]:
        async with self._session_factory() as db:
            rows = await db.execute(
                select(ChannelMembership.channel_id).where(
                    ChannelMembership.user_id == user_id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                )
            )
            return [str(cid) for cid in rows.scalars().all()]

    async def _member_channel_slugs(self, user_id: UUID) -> list[str]:
        async with self._session_factory() as db:
            rows = await db.execute(
                select(Channel.channel_slug)
                .join(ChannelMembership, ChannelMembership.channel_id == Channel.id)
                .where(
                    ChannelMembership.user_id == user_id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                    Channel.deleted_at.is_(None),
                )
            )
            return [str(slug) for slug in rows.scalars().all()]

    async def _ensure_user_bindings(self, user_id: UUID, username: str) -> None:
        channel_slugs = await self._member_channel_slugs(user_id)
        amqp_channel = await self._amqp.channel()
        try:
            await ensure_user_queue(amqp_channel, username)
            for channel_slug in channel_slugs:
                await bind_user_channel(amqp_channel, username, channel_slug)
        finally:
            await amqp_channel.close()

    async def _send_history(
        self,
        websocket: WebSocket,
        user_id: UUID,
        channel_ids: list[str],
        from_seq_id: int | None = None,
        request_id: UUID | None = None,
    ) -> None:
        # WebSocket history is intentionally small; the REST sync endpoint remains
        # the durable path for larger missed-message backfills.
        async with self._session_factory() as db:
            sync_items: list[dict[str, Any]] = []
            sender_cache: dict[UUID, User | None] = {}
            for channel_id_raw in channel_ids:
                channel_id = UUID(channel_id_raw)
                stmt = select(Message).where(Message.channel_id == channel_id, Message.deleted_at.is_(None))
                if from_seq_id is not None:
                    stmt = stmt.where(Message.seq_id > from_seq_id)
                stmt = stmt.order_by(Message.seq_id.asc()).limit(100)
                rows = await db.execute(stmt)
                items = rows.scalars().all()
                for message in items:
                    sync_items.append(await self._message_payload(db, message, sender_cache))
            await websocket.send_json(
                build_envelope(
                    "sync",
                    {
                        "server_time": utcnow().isoformat(),
                        "channel_updates": [],
                        "membership_updates": [],
                        "messages": sync_items,
                    },
                    request_id=request_id,
                )
            )

    async def _message_payload(
        self,
        db: AsyncSession,
        m: Message,
        sender_cache: dict[UUID, User | None] | None = None,
    ) -> dict[str, Any]:
        is_deleted = m.deleted_at is not None
        content_text = None
        content_json = None
        if not is_deleted:
            # WebSocket payloads are decrypted only after the connection has
            # passed channel membership checks.
            if m.content_type.value == "text":
                content_text = decrypt_message(m.content_text) if m.content_text is not None else None
            elif m.content_type.value == "json":
                content_json = decrypt_json_payload(m.content_json)
            else:
                raise AppError("unsupported content type", 500, code="DECRYPTION_FAILED")

        sender: User | None
        if sender_cache is not None and m.sender_user_id in sender_cache:
            sender = sender_cache[m.sender_user_id]
        else:
            # Batch syncs reuse sender records so reconnect/backfill responses do
            # not issue one user lookup per message from the same sender.
            sender = await db.get(User, m.sender_user_id)
            if sender_cache is not None:
                sender_cache[m.sender_user_id] = sender

        return {
            "id": str(m.id),
            "channel_id": str(m.channel_id),
            "sender_user_id": str(m.sender_user_id),
            "sender_username": sender.username if sender else None,
            "sender_display_name": sender.display_name if sender else None,
            "sender_avatar_url": sender.avatar_url if sender else None,
            "seq_id": m.seq_id,
            "content_type": m.content_type.value,
            "content_text": content_text,
            "content_json": content_json,
            "reply_to_message_id": str(m.reply_to_message_id) if m.reply_to_message_id else None,
            "reply_to_seq_id": m.reply_to_seq_id,
            "attachments": None if is_deleted else m.attachments,
            "is_pinned": m.is_pinned,
            "client_msg_id": str(m.client_msg_id) if m.client_msg_id else None,
            "created_at": m.created_at.isoformat(),
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            "edited_at": m.edited_at.isoformat() if m.edited_at else None,
            "deleted_at": m.deleted_at.isoformat() if m.deleted_at else None,
            "reactions_summary": {"counts": {}, "my_reaction": []},
        }

    async def _inbound_loop(self, websocket: WebSocket, user_id: UUID) -> None:
        # Receive client commands continuously until the WebSocket disconnects.
        while True:
            raw = await websocket.receive_text()
            try:
                envelope = parse_client_envelope(json.loads(raw))
            except Exception as exc:
                await websocket.send_json(build_error("invalid envelope", "VALIDATION_ERROR", details={"error": str(exc)}))
                continue

            msg_type = envelope.type
            payload = envelope.payload or {}

            # Keep the realtime protocol explicit so unsupported client commands
            # return a structured validation error instead of being ignored.
            if msg_type == "ping":
                await websocket.send_json(build_envelope("pong", {}, request_id=envelope.request_id))
            elif msg_type == "auth":
                await websocket.send_json(build_envelope("hello", {"user_id": str(user_id), "session_id": None}, request_id=envelope.request_id))
            elif msg_type == "subscribe":
                await self._handle_subscribe(websocket, user_id, payload, envelope.request_id)
            elif msg_type == "unsubscribe":
                await self._handle_unsubscribe(websocket, payload, envelope.request_id)
            elif msg_type == "resume":
                await self._handle_resume(websocket, user_id, payload, envelope.request_id)
            elif msg_type == "sync":
                await self._handle_sync_request(websocket, payload, envelope.request_id)
            elif msg_type == "seen":
                await self._handle_seen(websocket, user_id, payload, envelope.request_id)
            else:
                await websocket.send_json(
                    build_error("unsupported message type", "VALIDATION_ERROR", envelope.request_id, details={"type": msg_type})
                )

    async def _handle_sync_request(self, websocket: WebSocket, payload: dict[str, Any], request_id: UUID | None) -> None:
        try:
            req = WSSyncPayload.model_validate(payload)
        except Exception as exc:
            await websocket.send_json(build_error("invalid sync payload", "VALIDATION_ERROR", request_id, {"error": str(exc)}))
            return
        await websocket.send_json(
            build_error(
                "use REST /sync for backfill",
                "SYNC_USE_REST",
                request_id,
                {"states": [state.model_dump(mode="json") for state in req.states]},
            )
        )

    async def _handle_seen(
        self,
        websocket: WebSocket,
        user_id: UUID,
        payload: dict[str, Any],
        request_id: UUID | None,
    ) -> None:
        try:
            req = WSSeenPayload.model_validate(payload)
        except Exception as exc:
            await websocket.send_json(build_error("invalid seen payload", "VALIDATION_ERROR", request_id, {"error": str(exc)}))
            return
        if req.last_seen_seq_id is None:
            await websocket.send_json(
                build_error(
                    "last_seen_seq_id is required",
                    "VALIDATION_ERROR",
                    request_id,
                    {"channel_id": str(req.channel_id)},
                )
            )
            return
        async with self._session_factory() as db:
            try:
                # WebSocket seen events require a sequence marker; message-id
                # resolution stays on the REST endpoint where richer validation fits.
                state = await MessageService.mark_seen(
                    db,
                    req.channel_id,
                    user_id,
                    SeenRequest(last_seen_seq_id=req.last_seen_seq_id, last_seen_at=req.last_seen_at),
                )
            except AppError as exc:
                await websocket.send_json(build_error(exc.message, exc.code, request_id, exc.details))
                return
        await websocket.send_json(
            build_envelope(
                "seen",
                {
                    "channel_id": str(state.channel_id),
                    "user_id": str(state.user_id),
                    "last_seen_message_id": str(state.last_seen_message_id) if state.last_seen_message_id else None,
                    "last_seen_seq_id": state.last_seen_seq_id,
                    "last_seen_at": state.last_seen_at.isoformat() if state.last_seen_at else None,
                    "unread_count": state.unread_count,
                },
                request_id=request_id,
            )
        )

    async def _handle_subscribe(self, websocket: WebSocket, user_id: UUID, payload: dict[str, Any], request_id: UUID | None) -> None:
        try:
            req = WSSubscribePayload.model_validate(payload)
        except Exception as exc:
            await websocket.send_json(build_error("invalid subscribe payload", "VALIDATION_ERROR", request_id, {"error": str(exc)}))
            return
        allowed = set(await self._member_channel_ids(user_id))
        wanted = {str(cid) for cid in req.channel_ids}
        # A client may ask for any channel id, but realtime subscriptions are
        # intersected with current membership before history is returned.
        granted = sorted(list(wanted & allowed))
        self._subscriptions[id(websocket)] = set(granted)
        await self._send_history(websocket, user_id, granted, from_seq_id=req.from_seq_id, request_id=request_id)

    async def _handle_unsubscribe(self, websocket: WebSocket, payload: dict[str, Any], request_id: UUID | None) -> None:
        try:
            req = WSUnsubscribePayload.model_validate(payload)
        except Exception as exc:
            await websocket.send_json(build_error("invalid unsubscribe payload", "VALIDATION_ERROR", request_id, {"error": str(exc)}))
            return
        current = self._subscriptions.get(id(websocket), set())
        for channel_id in req.channel_ids:
            current.discard(str(channel_id))
        self._subscriptions[id(websocket)] = current
        await websocket.send_json(
            build_envelope(
                "sync",
                {
                    "server_time": utcnow().isoformat(),
                    "channel_updates": [],
                    "membership_updates": [],
                    "messages": [],
                },
                request_id=request_id,
            )
        )

    async def _handle_resume(self, websocket: WebSocket, user_id: UUID, payload: dict[str, Any], request_id: UUID | None) -> None:
        try:
            req = WSResumePayload.model_validate(payload)
        except Exception as exc:
            await websocket.send_json(build_error("invalid resume payload", "VALIDATION_ERROR", request_id, {"error": str(exc)}))
            return
        limit = max(1, min(int(req.limit or 200), 500))
        allowed = set(await self._member_channel_ids(user_id))
        # Resume uses per-channel cursors so a reconnect can replay only messages
        # newer than the client's last seen sequence.
        async with self._session_factory() as db:
            items: list[dict[str, Any]] = []
            sender_cache: dict[UUID, User | None] = {}
            remaining = limit
            for cursor in req.channels:
                if str(cursor.channel_id) not in allowed:
                    continue
                if remaining <= 0:
                    break
                stmt = (
                    select(Message)
                    .where(
                        Message.channel_id == cursor.channel_id,
                        Message.deleted_at.is_(None),
                        Message.seq_id > (cursor.last_seen_seq_id or 0),
                    )
                    .order_by(Message.seq_id.asc())
                    .limit(remaining)
                )
                rows = await db.execute(stmt)
                for message in rows.scalars().all():
                    items.append(await self._message_payload(db, message, sender_cache))
                    remaining -= 1
                    if remaining <= 0:
                        break
            await websocket.send_json(
                build_envelope(
                    "sync",
                    {
                        "server_time": utcnow().isoformat(),
                        "since": req.since.isoformat() if req.since else None,
                        "channel_updates": [],
                        "membership_updates": [],
                        "messages": items,
                    },
                    request_id,
                )
            )

    async def _redis_forward_loop(self, websocket: WebSocket, username: str) -> None:
        channel_name = user_pubsub_channel(username)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel_name)
        try:
            # Forward Redis events continuously while this user's socket remains active.
            while True:
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                except RedisTimeoutError:
                    continue
                if message is None:
                    await asyncio.sleep(0)
                    continue
                payload_raw = message["data"]
                if isinstance(payload_raw, bytes):
                    payload_raw = payload_raw.decode("utf-8")
                try:
                    event = json.loads(payload_raw)
                except Exception:
                    continue
                try:
                    event = self._decrypt_event_payload(event)
                except AppError as exc:
                    logger.warning("failed to decrypt realtime event: %s", exc.code)
                    continue
                channel_id = str(event.get("channel_id") or "")
                event_type = str(event.get("type") or "event")
                subs = self._subscriptions.get(id(websocket), set())
                # Membership updates are delivered even when the channel was just
                # unsubscribed, because they tell the client why access changed.
                if event_type != "membership_update" and channel_id and subs and channel_id not in subs:
                    continue
                await websocket.send_json(build_envelope(event_type, event))
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.close()

    def _decrypt_event_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event, dict):
            return event
        event_type = str(event.get("type") or "")
        if event_type not in {"message", "message_updated"}:
            return event
        # RabbitMQ and Redis carry encrypted message content; plaintext is only
        # restored inside the authenticated WebSocket boundary.
        if event.get("deleted_at") is not None:
            event["content_text"] = None
            event["content_json"] = None
            return event
        content_type = event.get("content_type")
        if content_type == "text":
            encrypted = event.get("content_text")
            event["content_text"] = decrypt_message(str(encrypted)) if encrypted is not None else None
            event["content_json"] = None
            return event
        if content_type == "json":
            event["content_text"] = None
            event["content_json"] = decrypt_json_payload(event.get("content_json"))
            return event
        raise AppError("unsupported content type", 500, code="DECRYPTION_FAILED")
