import asyncio
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import aio_pika
from fastapi import WebSocket
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.utils import utcnow
from app.db.models import ChannelMembership, MembershipRole, Message, UserChannelState
from app.mq.publisher import bind_user_channel
from app.realtime.protocol import (
    WSResumePayload,
    WSSubscribePayload,
    WSUnsubscribePayload,
    build_envelope,
    build_error,
    parse_client_envelope,
)
from app.realtime.redis_pubsub import mark_user_offline, mark_user_online, user_pubsub_channel

logger = logging.getLogger(__name__)


class WSManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: Redis, amqp: aio_pika.RobustConnection):
        self._session_factory = session_factory
        self._redis = redis
        self._amqp = amqp
        self._subscriptions: dict[int, set[str]] = {}

    async def connect(self, websocket: WebSocket, user_id: UUID, pre_accepted: bool = False) -> None:
        if not pre_accepted:
            await websocket.accept()
        await mark_user_online(self._redis, str(user_id))
        await self._ensure_user_bindings(user_id)
        self._subscriptions[id(websocket)] = set(await self._member_channel_ids(user_id))

    async def disconnect(self, websocket: WebSocket, user_id: UUID) -> None:
        self._subscriptions.pop(id(websocket), None)
        await mark_user_offline(self._redis, str(user_id))

    async def run_socket(self, websocket: WebSocket, user_id: UUID) -> None:
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

        redis_task = asyncio.create_task(self._redis_forward_loop(websocket, user_id))
        inbound_task = asyncio.create_task(self._inbound_loop(websocket, user_id))
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

    async def _ensure_user_bindings(self, user_id: UUID) -> None:
        channel_ids = await self._member_channel_ids(user_id)
        amqp_channel = await self._amqp.channel()
        try:
            for channel_id in channel_ids:
                await bind_user_channel(amqp_channel, str(user_id), channel_id)
        finally:
            await amqp_channel.close()

    async def _send_history(self, websocket: WebSocket, user_id: UUID, channel_ids: list[str], from_seq_id: int | None = None) -> None:
        async with self._session_factory() as db:
            for channel_id_raw in channel_ids:
                channel_id = UUID(channel_id_raw)
                stmt = select(Message).where(Message.channel_id == channel_id, Message.deleted_at.is_(None))
                if from_seq_id is not None:
                    stmt = stmt.where(Message.seq_id > from_seq_id)
                stmt = stmt.order_by(Message.seq_id.asc()).limit(100)
                rows = await db.execute(stmt)
                items = rows.scalars().all()
                if not items:
                    continue
                await websocket.send_json(
                    build_envelope(
                        "history",
                        {
                            "channel_id": channel_id_raw,
                            "items": [self._message_payload(m) for m in items],
                            "is_truncated": len(items) >= 100,
                        },
                    )
                )

    def _message_payload(self, m: Message) -> dict[str, Any]:
        return {
            "id": str(m.id),
            "channel_id": str(m.channel_id),
            "sender_user_id": str(m.sender_user_id),
            "seq_id": m.seq_id,
            "content_type": m.content_type.value,
            "content_text": m.content_text,
            "content_json": m.content_json,
            "reply_to_message_id": str(m.reply_to_message_id) if m.reply_to_message_id else None,
            "reply_to_seq_id": m.reply_to_seq_id,
            "attachments": m.attachments,
            "is_pinned": m.is_pinned,
            "client_msg_id": str(m.client_msg_id) if m.client_msg_id else None,
            "created_at": m.created_at.isoformat(),
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            "edited_at": m.edited_at.isoformat() if m.edited_at else None,
            "deleted_at": m.deleted_at.isoformat() if m.deleted_at else None,
        }

    async def _inbound_loop(self, websocket: WebSocket, user_id: UUID) -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                envelope = parse_client_envelope(json.loads(raw))
            except Exception as exc:
                await websocket.send_json(build_error("invalid envelope", "VALIDATION_ERROR", details={"error": str(exc)}))
                continue

            msg_type = envelope.type
            payload = envelope.payload or {}

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
            elif msg_type == "seen":
                await self._apply_seen(user_id, payload)
                await websocket.send_json(build_envelope("seen", payload, request_id=envelope.request_id))
            else:
                await websocket.send_json(
                    build_error("unsupported message type", "VALIDATION_ERROR", envelope.request_id, details={"type": msg_type})
                )

    async def _handle_subscribe(self, websocket: WebSocket, user_id: UUID, payload: dict[str, Any], request_id: UUID | None) -> None:
        try:
            req = WSSubscribePayload.model_validate(payload)
        except Exception as exc:
            await websocket.send_json(build_error("invalid subscribe payload", "VALIDATION_ERROR", request_id, {"error": str(exc)}))
            return
        allowed = set(await self._member_channel_ids(user_id))
        wanted = {str(cid) for cid in req.channel_ids}
        granted = sorted(list(wanted & allowed))
        self._subscriptions[id(websocket)] = set(granted)
        await self._send_history(websocket, user_id, granted, from_seq_id=req.from_seq_id)
        await websocket.send_json(build_envelope("subscribed", {"channel_ids": granted}, request_id=request_id))

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
        await websocket.send_json(build_envelope("unsubscribed", {"channel_ids": [str(cid) for cid in req.channel_ids]}, request_id=request_id))

    async def _handle_resume(self, websocket: WebSocket, user_id: UUID, payload: dict[str, Any], request_id: UUID | None) -> None:
        try:
            req = WSResumePayload.model_validate(payload)
        except Exception as exc:
            await websocket.send_json(build_error("invalid resume payload", "VALIDATION_ERROR", request_id, {"error": str(exc)}))
            return
        async with self._session_factory() as db:
            items: list[dict[str, Any]] = []
            for cursor in req.cursors:
                stmt = (
                    select(Message)
                    .where(
                        Message.channel_id == cursor.channel_id,
                        Message.deleted_at.is_(None),
                        Message.seq_id > (cursor.last_seen_seq_id or 0),
                    )
                    .order_by(Message.seq_id.asc())
                    .limit(100)
                )
                rows = await db.execute(stmt)
                for message in rows.scalars().all():
                    items.append(self._message_payload(message))
            await websocket.send_json(build_envelope("sync", {"items": items, "since": req.since.isoformat() if req.since else None}, request_id))

    async def _apply_seen(self, user_id: UUID, payload: dict[str, Any]) -> None:
        channel_id = UUID(str(payload["channel_id"]))
        seq_id = payload.get("last_seen_seq_id")
        async with self._session_factory() as db:
            state = await db.get(UserChannelState, {"channel_id": channel_id, "user_id": user_id})
            if not state:
                state = UserChannelState(channel_id=channel_id, user_id=user_id)
                db.add(state)
            if seq_id is not None:
                state.last_seen_seq_id = int(seq_id)
            raw_seen_at = payload.get("last_seen_at")
            if raw_seen_at is not None:
                try:
                    state.last_seen_at = datetime.fromisoformat(str(raw_seen_at))
                except ValueError:
                    state.last_seen_at = utcnow()
            else:
                state.last_seen_at = utcnow()
            await db.commit()

    async def _redis_forward_loop(self, websocket: WebSocket, user_id: UUID) -> None:
        channel_name = user_pubsub_channel(str(user_id))
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel_name)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                payload_raw = message["data"]
                if isinstance(payload_raw, bytes):
                    payload_raw = payload_raw.decode("utf-8")
                try:
                    event = json.loads(payload_raw)
                except Exception:
                    continue
                channel_id = str(event.get("channel_id") or "")
                subs = self._subscriptions.get(id(websocket), set())
                if channel_id and subs and channel_id not in subs:
                    continue
                event_type = str(event.get("type") or "event")
                await websocket.send_json(build_envelope(event_type, event))
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.close()
