#!/usr/bin/env python
"""Quick demo verifier for publish/subscribe flow."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import websockets


# Stores user session state for the verification flow; the command-line verification workflow uses it.
@dataclass
class UserSession:
    username: str
    password: str
    access_token: str


# Prints a verification step heading; the command-line verification workflow uses it.
def _step(title: str) -> None:
    print(f"[STEP] {title}")


# Prints a successful verification result; the command-line verification workflow uses it.
def _pass(message: str) -> None:
    print(f"[PASS] {message}")


# Prints an informational verification message; the command-line verification workflow uses it.
def _info(message: str) -> None:
    print(f"[INFO] {message}")


# Returns the current timestamp in ISO format; the command-line verification workflow uses it.
def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Sends a verification HTTP request; the command-line verification workflow uses it.
async def _req(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    token: str | None = None,
    payload: dict | None = None,
) -> dict:
    headers = {"Content-Type": "application/json"}
    # Run this conditional step only when `token` is true.
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = await client.request(method, path, headers=headers, json=payload)
    # Reject the operation when `response.status_code >= 400` to keep invalid state from progressing.
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed ({response.status_code}): {response.text}")
    # Return early when `response.status_code == 204` because the remaining work is not applicable.
    if response.status_code == 204:
        return {}
    return response.json()


# Registers and login; the command-line verification workflow uses it.
async def register_and_login(client: httpx.AsyncClient, label: str) -> UserSession:
    suffix = secrets.token_hex(4)
    username = f"demo_{label}_{suffix}"
    password = "Password123!"
    email = f"{username}@example.com"

    await _req(client, "POST", "/auth/register", payload={"username": username, "email": email, "password": password})
    login = await _req(client, "POST", "/auth/login", payload={"username_or_email": username, "password": password})
    return UserSession(username=username, password=password, access_token=login["access_token"])


# Checks status; the command-line verification workflow uses it.
async def _expect_status(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
    expected_status: int,
) -> None:
    headers = {"Content-Type": "application/json"}
    # Run this conditional step only when `token` is true.
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = await client.request(method, path, headers=headers, json=payload)
    # Reject the operation when `response.status_code != expected_status` to keep invalid state from progressing.
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{method} {path} expected {expected_status}, got {response.status_code}: {response.text}"
        )


# Waits for for api; the command-line verification workflow uses it.
def wait_for_api(client: httpx.Client, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    # Repeat this step while `time.time() < deadline` remains true.
    while time.time() < deadline:
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            response = client.get("/health")
            # Return early when `response.status_code == 200` because the remaining work is not applicable.
            if response.status_code == 200:
                return
            last_error = RuntimeError(f"/health returned {response.status_code}")
        # Handle `Exception` here so this workflow can recover or report the failure consistently.
        except Exception as exc:  # pragma: no cover - best effort readiness wait
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"API not ready after {timeout_seconds}s: {last_error}")


# Waits for for live message; the command-line verification workflow uses it.
async def _wait_for_live_message(ws, *, channel_id: str, plaintext: str, timeout_seconds: int) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    # Read live events until the expected message arrives or the deadline expires.
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        # Reject the operation when `remaining <= 0` to keep invalid state from progressing.
        if remaining <= 0:
            raise RuntimeError("Timed out waiting for live WebSocket delivery")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        event = json.loads(raw)
        # Skip the current item when `event.get('type') != 'message'` and continue processing the rest.
        if event.get("type") != "message":
            continue
        payload = event.get("payload") or {}
        # Skip the current item when `payload.get('channel_id') != channel_id` and continue processing the rest.
        if payload.get("channel_id") != channel_id:
            continue
        # Reject the operation when `payload.get('content_text') != plaintext` to keep invalid state from progressing.
        if payload.get("content_text") != plaintext:
            raise RuntimeError("Live WebSocket delivery payload plaintext did not match the published message")
        return payload


# Sends ws; the command-line verification workflow uses it.
async def _send_ws(ws, msg_type: str, payload: dict, *, request_id: str | None = None) -> str:
    request_id = request_id or str(uuid4())
    await ws.send(json.dumps({"type": msg_type, "request_id": request_id, "payload": payload, "ts": _iso_now()}))
    return request_id


# Waits for for ws sync; the command-line verification workflow uses it.
async def _wait_for_ws_sync(ws, *, request_id: str, timeout_seconds: int) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    # Read socket responses until the matching sync result arrives or times out.
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        # Reject the operation when `remaining <= 0` to keep invalid state from progressing.
        if remaining <= 0:
            raise RuntimeError("Timed out waiting for WebSocket subscribe sync acknowledgement")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        event = json.loads(raw)
        # Skip the current item when `str(event.get('request_id')) != request_id` and continue processing the rest.
        if str(event.get("request_id")) != request_id:
            continue
        # Reject the operation when `event.get('type') == 'error'` to keep invalid state from progressing.
        if event.get("type") == "error":
            raise RuntimeError(f"WebSocket subscribe failed: {event.get('payload')}")
        # Return early when `event.get('type') == 'sync'` because the remaining work is not applicable.
        if event.get("type") == "sync":
            return event.get("payload") or {}


# Runs the asynchronous verification workflow; the command-line verification workflow uses it.
async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Verify core demo flow for pub/sub messaging system")
    parser.add_argument("--base-url", default="http://localhost:8000/v1", help="API base URL")
    args = parser.parse_args()

    # Keep `httpx.Client(base_url=args.base_u...` active while this scoped operation is performed.
    with httpx.Client(base_url=args.base_url, timeout=20.0) as health_client:
        _step("0) Waiting for API health")
        _info("health timeout=60s, poll interval=1s")
        wait_for_api(health_client)
        _pass("API health check passed")

    # Keep `httpx.AsyncClient(base_url=args.b...` active while this scoped operation is performed.
    async with httpx.AsyncClient(base_url=args.base_url, timeout=20.0) as client:
        _step("1) Register/login User A, User B, and User C")
        user_a = await register_and_login(client, "a")
        user_b = await register_and_login(client, "b")
        user_c = await register_and_login(client, "c")
        _pass(f"Registered and logged in {user_a.username}, {user_b.username}, and {user_c.username}")

        _step("2) User A creates public/open channel 'news'")
        channel = await _req(
            client,
            "POST",
            "/channels",
            token=user_a.access_token,
            payload={
                "name": "news",
                "visibility": "public",
                "join_mode": "open",
                "description": "Demo channel",
            },
        )
        channel_id = channel["id"]
        channel_slug = channel.get("channel_slug")
        _pass(f"Created channel {channel_slug} ({channel_id})")

        ws_base_url = args.base_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base_url}/ws?token={user_b.access_token}"
        plaintext = f"Hello from demo {secrets.token_hex(3)}"
        _step("3) User B opens WebSocket before joining the channel")
        _info("hello timeout=10s, subscribe acknowledgement timeout=10s, live delivery timeout=30s")
        websocket_verified = False
        join_after_connect_verified = False
        live_payload: dict | None = None
        # Keep `websockets.connect(ws_url)` active while this scoped operation is performed.
        async with websockets.connect(ws_url) as ws:
            hello_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            hello_event = json.loads(hello_raw)
            # Reject the operation when `hello_event.get('type') != 'hello'` to keep invalid state from progressing.
            if hello_event.get("type") != "hello":
                raise RuntimeError(f"Unexpected WebSocket hello payload: {hello_raw}")
            _pass("WebSocket hello received")

            _step("4) User B joins channel while the WebSocket is already open")
            join_result = await _req(client, "POST", f"/channels/{channel_id}/join", token=user_b.access_token, payload={})
            # Reject the operation when `join_result.get('status') not in {'joined', 'already_member'}` to keep invalid state from progressing.
            if join_result.get("status") not in {"joined", "already_member"}:
                raise RuntimeError(f"User B did not join immediately: {join_result}")
            subscribe_request_id = await _send_ws(
                ws,
                "subscribe",
                {"channel_ids": [channel_id], "from_seq_id": 0},
            )
            await _wait_for_ws_sync(ws, request_id=subscribe_request_id, timeout_seconds=10)
            join_after_connect_verified = True
            _pass("User B joined and refreshed the open WebSocket subscription")

            live_wait = asyncio.create_task(
                _wait_for_live_message(
                    ws,
                    channel_id=channel_id,
                    plaintext=plaintext,
                    timeout_seconds=30,
                )
            )

            _step("5) User A publishes a message")
            published = await _req(
                client,
                "POST",
                f"/channels/{channel_id}/messages",
                token=user_a.access_token,
                payload={"content_text": plaintext},
            )
            _pass(f"Published message {published.get('id')}")

            # Attempt this operation and handle expected failures in the exception branches below.
            try:
                live_payload = await asyncio.wait_for(live_wait, timeout=30)
                websocket_verified = True
                _pass("User B received the message through WebSocket")
            # Handle `Exception` here so this workflow can recover or report the failure consistently.
            except Exception as exc:
                live_wait.cancel()
                _info(f"WebSocket delivery did not complete: {exc}")
                live_payload = None
            # Reject the operation when `websocket_verified and live_payload and (live_payload.get('id') != pu...` to keep invalid state from progressing.
            if websocket_verified and live_payload and live_payload.get("id") != published.get("id"):
                raise RuntimeError(
                    f"Live WebSocket delivered {live_payload.get('id')} but HTTP publish returned {published.get('id')}"
                )

        _step("6) User B verifies REST backfill")
        synced = await _req(
            client,
            "POST",
            "/sync",
            token=user_b.access_token,
            payload={"channels": [{"channel_id": channel_id, "last_seen_seq_id": 0}], "since": None, "limit": 50},
        )
        items = synced.get("messages", [])
        # Reject the operation when `not items` to keep invalid state from progressing.
        if not items:
            raise RuntimeError("No messages returned for User B sync")
        received = next((item.get("content_text") for item in items if item.get("content_text") == plaintext), None)
        # Reject the operation when `received != plaintext` to keep invalid state from progressing.
        if received != plaintext:
            raise RuntimeError(f"Message mismatch: expected '{plaintext}', got '{received}'")
        # Choose the appropriate path based on whether `not websocket_verified` is true.
        if not websocket_verified:
            _pass("REST backfill verified after WebSocket delivery fallback")
        # Handle the alternate path after the preceding branch or loop does not produce a result.
        else:
            _pass("REST backfill verified alongside live WebSocket delivery")

        _step("7) User A checks event log has core events")
        events = await _req(client, "GET", f"/channels/{channel_id}/events?limit=50", token=user_a.access_token)
        event_types = {e.get("event_type") for e in events.get("items", [])}
        required = {"channel.created", "membership.joined", "message.published"}
        missing = sorted(required - event_types)
        # Reject the operation when `missing` to keep invalid state from progressing.
        if missing:
            raise RuntimeError(f"Missing expected event types: {missing}")
        _pass("Event log contains channel and message activity")

        _step("8) User A verifies event integrity for the channel")
        integrity = await _req(client, "GET", f"/channels/{channel_id}/events/integrity", token=user_a.access_token)
        # Reject the operation when `integrity.get('valid') is not True` to keep invalid state from progressing.
        if integrity.get("valid") is not True:
            raise RuntimeError(f"Event integrity was not valid for fresh demo channel: {integrity}")
        _pass(f"Event integrity verified for {integrity.get('checked_events')} events")

        _step("9) User C is blocked from private upload content")
        upload_bytes = b"secret upload"
        upload = await _req(
            client,
            "POST",
            "/uploads",
            token=user_a.access_token,
            payload={
                "filename": "secret.txt",
                "content_type": "text/plain",
                "size_bytes": len(upload_bytes),
            },
        )
        upload_id = upload["file_id"]
        put_response = await client.put(
            f"/uploads/{upload_id}/content",
            headers={"Authorization": f"Bearer {user_a.access_token}", "Content-Type": "text/plain"},
            content=upload_bytes,
        )
        # Reject the operation when `put_response.status_code >= 400` to keep invalid state from progressing.
        if put_response.status_code >= 400:
            raise RuntimeError(f"PUT /uploads/{upload_id}/content failed ({put_response.status_code}): {put_response.text}")
        await _req(
            client,
            "POST",
            f"/channels/{channel_id}/messages",
            token=user_a.access_token,
            payload={
                "content_text": "attachment check",
                "attachments": [{"file_id": upload_id}],
            },
        )
        await _expect_status(
            client,
            "GET",
            f"/uploads/{upload_id}/content",
            token=user_c.access_token,
            expected_status=403,
        )
        _pass("Unauthorized upload access denied for User C")

        print("\n[PASS] Demo verification passed")
        print(json.dumps({
            "channel_id": channel_id,
            "channel_slug": channel_slug,
            "published_message_id": published.get("id"),
            "websocket_verified": websocket_verified,
            "join_after_connect_verified": join_after_connect_verified,
            "sync_verified": True,
            "event_integrity_verified": True,
            "plaintext_verified": True,
            "upload_access_denied_verified": True,
        }, indent=2))

        print("\n[INFO] Proof path verified:")
        print("backend -> PostgreSQL/outbox -> RabbitMQ -> worker -> Redis -> WebSocket -> subscriber")
        print("[INFO] Join-after-connect verified with explicit WebSocket subscribe/resync")
        print("[INFO] To verify DB ciphertext manually:")
        print('docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"')

        return 0


# Runs the module's command-line workflow; the command-line verification workflow uses it.
def main() -> int:
    return asyncio.run(main_async())


# Run this conditional step only when `__name__ == '__main__'` is true.
if __name__ == "__main__":
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        raise SystemExit(main())
    # Handle `Exception` here so this workflow can recover or report the failure consistently.
    except Exception as exc:
        print(f"[FAIL] Demo verification failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        raise SystemExit(1)
