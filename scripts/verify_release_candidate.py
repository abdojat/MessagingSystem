#!/usr/bin/env python
"""Deterministic Phase 12 release-candidate application verifier.

Run this against a disposable, fully running stack. The verifier creates only
application data. It never resets schemas, tampers with evidence, prints test
secrets, or invokes production maintenance commands.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
import websockets


@dataclass(slots=True)
class UserSession:
    user_id: str
    username: str
    email: str
    password: str
    access_token: str
    refresh_token: str


def step(message: str) -> None:
    print(f"[STEP] {message}")


def passed(message: str) -> None:
    print(f"[PASS] {message}")


def info(message: str) -> None:
    print(f"[INFO] {message}")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ws_url(base_url: str) -> str:
    parts = urlsplit(base_url.rstrip("/"))
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, f"{parts.path}/ws", "", ""))


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    content: bytes | None = None,
    content_type: str = "application/json",
) -> httpx.Response:
    headers = {"Content-Type": content_type}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request_kwargs: dict[str, Any] = {"headers": headers}
    if payload is not None:
        request_kwargs["json"] = payload
    elif content is not None:
        request_kwargs["content"] = content
    return await client.request(method, path, **request_kwargs)


async def json_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await request(client, method, path, token=token, payload=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed with status {response.status_code}")
    if response.status_code == 204:
        return {}
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"{method} {path} returned an unexpected response shape")
    return data


async def expect_status(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    expected: int | set[int],
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    content: bytes | None = None,
    content_type: str = "application/json",
    error_code: str | None = None,
) -> httpx.Response:
    response = await request(
        client,
        method,
        path,
        token=token,
        payload=payload,
        content=content,
        content_type=content_type,
    )
    statuses = {expected} if isinstance(expected, int) else expected
    if response.status_code not in statuses:
        raise RuntimeError(
            f"{method} {path} expected {sorted(statuses)}, got {response.status_code}"
        )
    if error_code:
        try:
            body = response.json()
            detail = body.get("detail")
            actual = body.get("code")
            if actual is None and isinstance(detail, dict):
                actual = detail.get("code")
        except (ValueError, AttributeError):
            actual = None
        if actual != error_code:
            raise RuntimeError(f"{method} {path} expected error code {error_code}, got {actual}")
    return response


async def wait_for_api(client: httpx.AsyncClient, timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_status: int | None = None
    while time.monotonic() < deadline:
        try:
            response = await client.get("/health")
            last_status = response.status_code
            if response.status_code == 200 and response.json() == {"status": "ok"}:
                return
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(1)
    raise RuntimeError(f"API did not become healthy; last status={last_status}")


async def register_and_login(
    client: httpx.AsyncClient,
    label: str,
    run_id: str,
    *,
    email: str | None = None,
) -> UserSession:
    username = f"release_{label}_{run_id}"
    password = f"P12!{secrets.token_urlsafe(18)}"
    email = email or f"{username}@example.com"
    registered = await json_request(
        client,
        "POST",
        "/auth/register",
        payload={"username": username, "email": email, "password": password},
    )
    login = await json_request(
        client,
        "POST",
        "/auth/login",
        payload={"username_or_email": username, "password": password},
    )
    return UserSession(
        user_id=str(registered["id"]),
        username=username,
        email=email,
        password=password,
        access_token=str(login["access_token"]),
        refresh_token=str(login["refresh_token"]),
    )


async def websocket_ticket(client: httpx.AsyncClient, user: UserSession) -> str:
    response = await json_request(client, "POST", "/auth/ws-ticket", token=user.access_token, payload={})
    return str(response["ticket"])


async def websocket_hello(socket: Any, timeout_seconds: int = 10) -> None:
    raw = await asyncio.wait_for(socket.recv(), timeout=timeout_seconds)
    payload = json.loads(raw)
    if payload.get("type") != "hello":
        raise RuntimeError("WebSocket did not return the expected hello frame")


async def subscribe(socket: Any, channel_id: str) -> None:
    request_id = str(uuid4())
    await socket.send(
        json.dumps(
            {
                "type": "subscribe",
                "request_id": request_id,
                "payload": {"channel_ids": [channel_id], "from_seq_id": 0},
                "ts": iso_now(),
            }
        )
    )
    deadline = asyncio.get_running_loop().time() + 15
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise RuntimeError("WebSocket subscribe acknowledgement timed out")
        event = json.loads(await asyncio.wait_for(socket.recv(), timeout=remaining))
        if str(event.get("request_id")) != request_id:
            continue
        if event.get("type") == "error":
            raise RuntimeError("WebSocket subscription was rejected")
        if event.get("type") == "sync":
            return


async def wait_for_message(socket: Any, channel_id: str, marker: str, timeout_seconds: int = 40) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise RuntimeError("Live WebSocket message delivery timed out")
        event = json.loads(await asyncio.wait_for(socket.recv(), timeout=remaining))
        if event.get("type") != "message":
            continue
        payload = event.get("payload") or {}
        if payload.get("channel_id") != channel_id:
            continue
        if payload.get("content_text") != marker:
            raise RuntimeError("Live WebSocket plaintext did not match the published message")
        return payload


async def poll_mailpit_token(mailpit_url: str, recipient: str, timeout_seconds: int = 30) -> str:
    token_pattern = re.compile(r"(?:#token=|%23token%3D)([A-Za-z0-9_-]{32,256})", re.IGNORECASE)
    deadline = time.monotonic() + timeout_seconds
    async with httpx.AsyncClient(base_url=mailpit_url.rstrip("/"), timeout=10) as client:
        while time.monotonic() < deadline:
            response = await client.get("/api/v1/messages", params={"limit": 100})
            response.raise_for_status()
            body = response.json()
            messages = body.get("messages", body if isinstance(body, list) else [])
            for message in messages:
                if recipient.lower() not in json.dumps(message).lower():
                    continue
                message_id = message.get("ID") or message.get("id")
                candidates = [json.dumps(message)]
                if message_id:
                    for path in (f"/api/v1/message/{message_id}", f"/view/{message_id}.txt", f"/view/{message_id}.html"):
                        detail = await client.get(path)
                        if detail.status_code == 200:
                            candidates.append(detail.text)
                for candidate in candidates:
                    match = token_pattern.search(candidate)
                    if match:
                        return match.group(1)
            await asyncio.sleep(0.5)
    raise RuntimeError("Timed out waiting for the disposable email-verification message")


async def poll_presence(redis: Redis, username: str, expected: bool, timeout_seconds: int = 10) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        current = bool(await redis.sismember("rt.online_users", username.lower()))
        if current is expected:
            return
        await asyncio.sleep(0.2)
    raise RuntimeError(f"Presence did not become {'online' if expected else 'offline'}")


async def verify_database_and_storage(
    *,
    message_id: str,
    message_marker: str,
    upload_id: str,
    upload_marker: bytes,
    uploads_base_dir: Path,
) -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for at-rest release verification")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            stored_message = (
                await connection.execute(
                    text("SELECT content_text, content_json FROM messages WHERE id = :id"),
                    {"id": UUID(message_id)},
                )
            ).one()
            message_storage = json.dumps([stored_message.content_text, stored_message.content_json])
            if message_marker in message_storage or "enc:v2:" not in message_storage:
                raise RuntimeError("Message storage was not a v2 ciphertext envelope")

            outbox_payloads = list(
                (
                    await connection.execute(
                        text("SELECT payload FROM outbox WHERE aggregate_id = :id ORDER BY created_at"),
                        {"id": UUID(message_id)},
                    )
                ).scalars().all()
            )
            if not outbox_payloads:
                raise RuntimeError("No message outbox row was persisted")
            outbox_storage = json.dumps(outbox_payloads)
            if message_marker in outbox_storage or "enc:v2:" not in outbox_storage:
                raise RuntimeError("Outbox did not retain the opaque encrypted message envelope")

            upload_row = (
                await connection.execute(
                    text(
                        "SELECT storage_path, storage_encryption_version, storage_key_id "
                        "FROM uploads WHERE id = :id"
                    ),
                    {"id": UUID(upload_id)},
                )
            ).one()
            if int(upload_row.storage_encryption_version) != 1 or not upload_row.storage_key_id:
                raise RuntimeError("Upload encryption metadata was not finalized")
    finally:
        await engine.dispose()

    configured_base = uploads_base_dir.resolve()
    stored_path = Path(str(upload_row.storage_path))
    full_path = stored_path if stored_path.is_absolute() else configured_base / stored_path
    resolved = full_path.resolve()
    if configured_base not in resolved.parents:
        raise RuntimeError("Upload storage path escaped the configured base directory")
    raw = resolved.read_bytes()
    if not raw.startswith(b"MSGUPENC") or upload_marker in raw:
        raise RuntimeError("Final upload storage was not the expected encrypted MSGUPENC format")


async def verify_outbox_published(message_id: str, timeout_seconds: int = 30) -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            async with engine.connect() as connection:
                statuses = list(
                    (
                        await connection.execute(
                            text("SELECT status::text FROM outbox WHERE aggregate_id = :id"),
                            {"id": UUID(message_id)},
                        )
                    ).scalars().all()
                )
            if "published" in statuses:
                return
            await asyncio.sleep(0.5)
        raise RuntimeError("Message outbox row did not reach published state")
    finally:
        await engine.dispose()


async def run(args: argparse.Namespace) -> int:
    run_id = secrets.token_hex(4)
    future_email = f"release_future_{run_id}@example.com"
    results: dict[str, bool] = {}

    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=30) as client:
        step("1) Health, identity, sessions, and invalid authentication")
        await wait_for_api(client)
        user_a = await register_and_login(client, "owner", run_id)
        user_c = await register_and_login(client, "outsider", run_id)
        user_d = await register_and_login(client, "admin", run_id)
        await expect_status(
            client,
            "POST",
            "/auth/login",
            401,
            payload={"username_or_email": user_a.username, "password": "definitely-wrong"},
        )
        await expect_status(client, "GET", "/me", 401)
        me = await json_request(client, "GET", "/me", token=user_a.access_token)
        if str(me.get("id")) != user_a.user_id:
            raise RuntimeError("Authenticated /me did not return User A")
        results["identity"] = True
        passed("registration, login, session-bound /me, and invalid-auth denial")

        step("2) Private channel, unresolved invite, real mailbox proof, and representative RBAC")
        channel = await json_request(
            client,
            "POST",
            "/channels",
            token=user_a.access_token,
            payload={
                "name": f"Release candidate {run_id}",
                "channel_slug": f"release_{run_id}",
                "description": "Phase 12 disposable release channel",
                "visibility": "private",
                "join_mode": "invite_only",
            },
        )
        channel_id = str(channel["id"])
        invitation = await json_request(
            client,
            "POST",
            f"/channels/{channel_id}/invite",
            token=user_a.access_token,
            payload={"invited_email": future_email, "is_generic": False, "expires_in_hours": 24},
        )
        user_b = await register_and_login(client, "member", run_id, email=future_email)
        await expect_status(
            client,
            "POST",
            f"/invites/{invitation['token']}/accept",
            403,
            token=user_b.access_token,
            payload={},
            error_code="EMAIL_VERIFICATION_REQUIRED",
        )
        if args.mailpit_url:
            await json_request(client, "POST", "/auth/email-verification/request", token=user_b.access_token, payload={})
            token = await poll_mailpit_token(args.mailpit_url, future_email)
            confirmation = await json_request(
                client,
                "POST",
                "/auth/email-verification/confirm",
                token=user_b.access_token,
                payload={"token": token},
            )
            if confirmation.get("status") != "verified":
                raise RuntimeError("Email verification did not complete")
            accepted = await json_request(
                client,
                "POST",
                f"/invites/{invitation['token']}/accept",
                token=user_b.access_token,
                payload={},
            )
            if accepted.get("role") != "member":
                raise RuntimeError("Verified invite acceptance did not create member role")
            results["email_invite"] = True
            passed("unresolved invite denied before and accepted after real captured mailbox verification")
        else:
            await json_request(
                client,
                "POST",
                f"/channels/{channel_id}/members/{user_b.user_id}/add",
                token=user_a.access_token,
                payload={},
            )
            results["email_invite"] = False
            info("email transport proof skipped; member added directly (pass --mailpit-url to verify it)")

        await json_request(
            client,
            "POST",
            f"/channels/{channel_id}/members/{user_d.user_id}/add",
            token=user_a.access_token,
            payload={},
        )
        promoted = await json_request(
            client,
            "POST",
            f"/channels/{channel_id}/members/{user_d.user_id}/promote",
            token=user_a.access_token,
            payload={},
        )
        if promoted.get("role") != "admin":
            raise RuntimeError("Representative admin promotion failed")
        await json_request(
            client,
            "PATCH",
            f"/channels/{channel_id}",
            token=user_a.access_token,
            payload={"description": "Phase 12 owner-managed release channel"},
        )
        await expect_status(
            client,
            "GET",
            f"/channels/{channel_id}/messages?limit=10",
            403,
            token=user_c.access_token,
        )
        results["rbac"] = True
        passed("owner/admin/member/outsider roles and private-read denial")

        step("3) PostgreSQL/outbox -> RabbitMQ -> worker -> Redis -> WebSocket")
        marker = f"FINAL_RELEASE_SECRET_MESSAGE_{secrets.token_hex(12)}"
        ticket = await websocket_ticket(client, user_b)
        async with websockets.connect(f"{ws_url(args.base_url)}?ticket={ticket}") as socket:
            await websocket_hello(socket)
            await subscribe(socket, channel_id)
            live_wait = asyncio.create_task(wait_for_message(socket, channel_id, marker))
            published = await json_request(
                client,
                "POST",
                f"/channels/{channel_id}/messages",
                token=user_a.access_token,
                payload={"content_text": marker},
            )
            live = await live_wait
            if str(live.get("id")) != str(published.get("id")):
                raise RuntimeError("Live message ID differed from the committed HTTP response")
        message_id = str(published["id"])
        await verify_outbox_published(message_id)
        messages = await json_request(
            client,
            "GET",
            f"/channels/{channel_id}/messages?limit=50",
            token=user_b.access_token,
        )
        if not any(item.get("content_text") == marker for item in messages.get("items", [])):
            raise RuntimeError("Authorized REST history did not return the exact message plaintext")
        results["live_delivery"] = True
        passed("committed message arrived live and the authoritative outbox reached published")

        step("4) Encrypted immutable attachment and protected download")
        upload_marker = f"FINAL_RELEASE_SECRET_UPLOAD_{secrets.token_hex(12)}".encode()
        upload = await json_request(
            client,
            "POST",
            "/uploads",
            token=user_a.access_token,
            payload={
                "filename": "release-proof.txt",
                "content_type": "text/plain",
                "size_bytes": len(upload_marker),
            },
        )
        upload_id = str(upload["file_id"])
        await expect_status(
            client,
            "PUT",
            f"/uploads/{upload_id}/content",
            200,
            token=user_a.access_token,
            content=upload_marker,
            content_type="text/plain",
        )
        await expect_status(
            client,
            "PUT",
            f"/uploads/{upload_id}/content",
            409,
            token=user_a.access_token,
            content=b"replacement-denied",
            content_type="text/plain",
            error_code="UPLOAD_IMMUTABLE",
        )
        await json_request(
            client,
            "POST",
            f"/channels/{channel_id}/messages",
            token=user_a.access_token,
            payload={"content_text": "release attachment", "attachments": [{"file_id": upload_id}]},
        )
        authorized = await request(
            client,
            "GET",
            f"/uploads/{upload_id}/content",
            token=user_b.access_token,
        )
        if authorized.status_code != 200 or authorized.content != upload_marker:
            raise RuntimeError("Authorized encrypted attachment download was not byte-exact")
        await expect_status(
            client,
            "GET",
            f"/uploads/{upload_id}/content",
            403,
            token=user_c.access_token,
        )
        await verify_database_and_storage(
            message_id=message_id,
            message_marker=marker,
            upload_id=upload_id,
            upload_marker=upload_marker,
            uploads_base_dir=Path(args.uploads_base_dir),
        )
        results["encryption"] = True
        results["upload_immutable"] = True
        passed("REST plaintext is exact; DB/outbox/upload storage contains encrypted envelopes and outsider access is denied")

        step("5) Disconnected sync/backfill without outsider leakage")
        offline_marker = f"FINAL_RELEASE_OFFLINE_{secrets.token_hex(10)}"
        await json_request(
            client,
            "POST",
            f"/channels/{channel_id}/messages",
            token=user_a.access_token,
            payload={"content_text": offline_marker},
        )
        synced = await json_request(
            client,
            "POST",
            "/sync",
            token=user_b.access_token,
            payload={"channels": [{"channel_id": channel_id, "last_seen_seq_id": 0}], "since": None, "limit": 100},
        )
        if not any(item.get("content_text") == offline_marker for item in synced.get("messages", [])):
            raise RuntimeError("Authorized sync did not recover the disconnected message")
        outsider_sync = await json_request(
            client,
            "POST",
            "/sync",
            token=user_c.access_token,
            payload={"channels": [{"channel_id": channel_id, "last_seen_seq_id": 0}], "since": None, "limit": 100},
        )
        if any(item.get("channel_id") == channel_id for item in outsider_sync.get("messages", [])):
            raise RuntimeError("Outsider sync leaked private-channel history")
        results["sync"] = True
        passed("offline history recovered for the member and remained absent for the outsider")

        step("6) Two-socket aggregate presence")
        redis_url = os.environ.get("REDIS_URL", "").strip()
        if not redis_url:
            raise RuntimeError("REDIS_URL is required for aggregate-presence verification")
        redis = Redis.from_url(redis_url, decode_responses=True)
        secondary_base = args.secondary_base_url or args.base_url
        first_ticket = await websocket_ticket(client, user_d)
        second_ticket = await websocket_ticket(client, user_d)
        first = await websockets.connect(f"{ws_url(args.base_url)}?ticket={first_ticket}")
        second = await websockets.connect(f"{ws_url(secondary_base)}?ticket={second_ticket}")
        try:
            await websocket_hello(first)
            await websocket_hello(second)
            await poll_presence(redis, user_d.username, True)
            await first.close()
            await poll_presence(redis, user_d.username, True)
            await second.close()
            await poll_presence(redis, user_d.username, False)
        finally:
            await first.close()
            await second.close()
            await redis.aclose()
        results["presence"] = True
        passed("closing one socket kept the user online; closing the final socket transitioned offline")

        step("7) Refresh rotation, replay-family revocation, and logout invalidation")
        rotated = await json_request(
            client,
            "POST",
            "/auth/refresh",
            payload={"refresh_token": user_c.refresh_token},
        )
        await expect_status(
            client,
            "POST",
            "/auth/refresh",
            401,
            payload={"refresh_token": user_c.refresh_token},
        )
        await expect_status(client, "GET", "/me", 401, token=str(rotated["access_token"]))
        relogin = await json_request(
            client,
            "POST",
            "/auth/login",
            payload={"username_or_email": user_c.username, "password": user_c.password},
        )
        await json_request(
            client,
            "POST",
            "/auth/logout",
            payload={"refresh_token": relogin["refresh_token"]},
        )
        await expect_status(client, "GET", "/me", 401, token=str(relogin["access_token"]))
        results["session_security"] = True
        passed("refresh rotated, stale replay revoked the family, and logout invalidated its session")

        step("8) Audit events, hash-chain integrity, and removed-member denial")
        events = await json_request(
            client,
            "GET",
            f"/channels/{channel_id}/events?limit=200",
            token=user_a.access_token,
        )
        event_types = {item.get("event_type") for item in events.get("items", [])}
        required_events = {"channel.created", "membership.added", "member.promoted", "message.published"}
        missing = sorted(required_events - event_types)
        if missing:
            raise RuntimeError(f"Channel audit log omitted expected event types: {missing}")
        integrity = await json_request(
            client,
            "GET",
            f"/channels/{channel_id}/events/integrity",
            token=user_a.access_token,
        )
        if integrity.get("valid") is not True:
            raise RuntimeError("Fresh channel audit hash chain did not verify")
        await json_request(
            client,
            "DELETE",
            f"/channels/{channel_id}/members/{user_b.user_id}",
            token=user_a.access_token,
        )
        await expect_status(
            client,
            "GET",
            f"/channels/{channel_id}/messages?limit=10",
            403,
            token=user_b.access_token,
        )
        results["audit"] = True
        results["removed_member_denied"] = True
        passed("required events and hash chain verified; removed identity lost protected history access")

    print("\n[PASS] Phase 12 release-candidate application verification passed")
    print(json.dumps(results, indent=2, sort_keys=True))
    print("[INFO] No plaintext marker, credential, or signing private key was printed.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the complete disposable release-candidate application flow")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument(
        "--secondary-base-url",
        default=None,
        help="Optional second backend URL for a live cross-backend presence proof",
    )
    parser.add_argument(
        "--mailpit-url",
        default=None,
        help="Optional disposable Mailpit HTTP API URL; enables real email/invite verification",
    )
    parser.add_argument("--uploads-base-dir", default=os.environ.get("UPLOADS_BASE_DIR", "/data/uploads"))
    return parser.parse_args()


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] Release-candidate verification failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        raise SystemExit(1)
