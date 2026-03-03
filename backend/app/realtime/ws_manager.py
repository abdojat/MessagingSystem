import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

import aio_pika
from fastapi import WebSocket
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.utils import utcnow
from app.db.models import ChannelMembership, MembershipRole, Message, UserChannelState
from app.mq.publisher import bind_user_channel
from app.realtime.redis_pubsub import mark_user_offline, mark_user_online, user_pubsub_channel

logger = logging.getLogger(__name__)


class WSManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: Redis, amqp: aio_pika.RobustConnection):
        self._session_factory = session_factory
        self._redis = redis
        self._amqp = amqp
        self._sockets: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, user_id: UUID) -> None:
        await websocket.accept()
        uid = str(user_id)
        self._sockets[uid].add(websocket)
        await mark_user_online(self._redis, uid)
        await self._ensure_user_bindings(user_id)

    async def disconnect(self, websocket: WebSocket, user_id: UUID) -> None:
        uid = str(user_id)
        self._sockets[uid].discard(websocket)
        if not self._sockets[uid]:
            self._sockets.pop(uid, None)
            await mark_user_offline(self._redis, uid)

    async def run_socket(self, websocket: WebSocket, user_id: UUID) -> None:
        await websocket.send_json({"type": "hello", "user_id": str(user_id)})
        await self._send_history(websocket, user_id, overrides=None)

        redis_task = asyncio.create_task(self._redis_forward_loop(websocket, user_id))
        inbound_task = asyncio.create_task(self._inbound_loop(websocket, user_id))
        done, pending = await asyncio.wait({redis_task, inbound_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception():
                raise task.exception()

    async def _ensure_user_bindings(self, user_id: UUID) -> None:
        async with self._session_factory() as db:
            rows = await db.execute(
                select(ChannelMembership.channel_id).where(
                    ChannelMembership.user_id == user_id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                )
            )
            channel_ids = [str(cid) for cid in rows.scalars().all()]

        amqp_channel = await self._amqp.channel()
        try:
            for channel_id in channel_ids:
                await bind_user_channel(amqp_channel, str(user_id), channel_id)
        finally:
            await amqp_channel.close()

    async def _send_history(
        self,
        websocket: WebSocket,
        user_id: UUID,
        overrides: dict[str, dict[str, Any]] | None,
    ) -> None:
        settings = get_settings()
        async with self._session_factory() as db:
            rows = await db.execute(
                select(ChannelMembership.channel_id).where(
                    ChannelMembership.user_id == user_id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                )
            )
            channel_ids = rows.scalars().all()
            for channel_id in channel_ids:
                state = await db.get(UserChannelState, {"channel_id": channel_id, "user_id": user_id})
                last_seq = state.last_seen_seq_id if state else 0
                last_seen_at = state.last_seen_at if state else None
                if overrides and str(channel_id) in overrides:
                    override = overrides[str(channel_id)]
                    if override.get("last_seen_seq_id") is not None:
                        last_seq = int(override["last_seen_seq_id"])
                    if override.get("last_seen_at") is not None:
                        last_seen_at = override["last_seen_at"]

                stmt = select(Message).where(Message.channel_id == channel_id)
                if last_seq:
                    stmt = stmt.where(Message.seq_id > last_seq)
                elif last_seen_at:
                    stmt = stmt.where(Message.created_at > last_seen_at)
                stmt = stmt.order_by(Message.seq_id.asc()).limit(settings.ws_history_batch_limit)
                msg_rows = await db.execute(stmt)
                messages = msg_rows.scalars().all()
                if not messages:
                    continue
                payload = {
                    "type": "history",
                    "channel_id": str(channel_id),
                    "messages": [
                        {
                            "id": str(m.id),
                            "channel_id": str(m.channel_id),
                            "sender_user_id": str(m.sender_user_id),
                            "seq_id": m.seq_id,
                            "content_type": m.content_type.value,
                            "content_text": m.content_text,
                            "content_json": m.content_json,
                            "created_at": m.created_at.isoformat(),
                        }
                        for m in messages
                    ],
                }
                await websocket.send_json(payload)

    async def _inbound_loop(self, websocket: WebSocket, user_id: UUID) -> None:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")
            if msg_type == "sync":
                overrides: dict[str, dict[str, Any]] = {}
                for entry in data.get("states", []):
                    if "channel_id" not in entry:
                        continue
                    cid = str(entry["channel_id"])
                    payload: dict[str, Any] = {}
                    if entry.get("last_seen_seq_id") is not None:
                        payload["last_seen_seq_id"] = int(entry["last_seen_seq_id"])
                    if entry.get("last_seen_at") is not None:
                        try:
                            payload["last_seen_at"] = datetime.fromisoformat(entry["last_seen_at"])
                        except ValueError:
                            pass
                    overrides[cid] = payload
                await self._send_history(websocket, user_id, overrides)
            elif msg_type == "seen":
                await self._apply_seen(user_id, data)

    async def _apply_seen(self, user_id: UUID, data: dict[str, Any]) -> None:
        channel_id = UUID(data["channel_id"])
        seq_id = data.get("last_seen_seq_id")
        async with self._session_factory() as db:
            state = await db.get(UserChannelState, {"channel_id": channel_id, "user_id": user_id})
            if not state:
                state = UserChannelState(channel_id=channel_id, user_id=user_id)
                db.add(state)
            if seq_id is not None:
                state.last_seen_seq_id = int(seq_id)
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
                payload = message["data"]
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                await websocket.send_text(payload)
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.close()
