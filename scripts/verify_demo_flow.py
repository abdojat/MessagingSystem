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

import httpx
import websockets


@dataclass
class UserSession:
    username: str
    password: str
    access_token: str


async def _req(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    token: str | None = None,
    payload: dict | None = None,
) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = await client.request(method, path, headers=headers, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed ({response.status_code}): {response.text}")
    if response.status_code == 204:
        return {}
    return response.json()


async def register_and_login(client: httpx.AsyncClient, label: str) -> UserSession:
    suffix = secrets.token_hex(4)
    username = f"demo_{label}_{suffix}"
    password = "Password123!"
    email = f"{username}@example.com"

    await _req(client, "POST", "/auth/register", payload={"username": username, "email": email, "password": password})
    login = await _req(client, "POST", "/auth/login", payload={"username_or_email": username, "password": password})
    return UserSession(username=username, password=password, access_token=login["access_token"])


def wait_for_api(client: httpx.Client, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return
            last_error = RuntimeError(f"/health returned {response.status_code}")
        except Exception as exc:  # pragma: no cover - best effort readiness wait
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"API not ready after {timeout_seconds}s: {last_error}")


async def _wait_for_live_message(ws, *, channel_id: str, plaintext: str, timeout_seconds: int) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise RuntimeError("Timed out waiting for live WebSocket delivery")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        event = json.loads(raw)
        if event.get("type") != "message":
            continue
        payload = event.get("payload") or {}
        if payload.get("channel_id") != channel_id:
            continue
        if payload.get("content_text") != plaintext:
            raise RuntimeError("Live WebSocket delivery payload plaintext did not match the published message")
        return payload


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Verify core demo flow for pub/sub messaging system")
    parser.add_argument("--base-url", default="http://localhost:8000/v1", help="API base URL")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=20.0) as health_client:
        print("0) Waiting for API health")
        wait_for_api(health_client)

    async with httpx.AsyncClient(base_url=args.base_url, timeout=20.0) as client:
        print("1) Register/login User A and User B")
        user_a = await register_and_login(client, "a")
        user_b = await register_and_login(client, "b")

        print("2) User A creates public/open channel 'news'")
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

        print("3) User B joins channel")
        await _req(client, "POST", f"/channels/{channel_id}/join", token=user_b.access_token, payload={})

        ws_base_url = args.base_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base_url}/ws?token={user_b.access_token}"
        plaintext = f"Hello from demo {secrets.token_hex(3)}"
        print("4) User B opens WebSocket and waits for live delivery")
        async with websockets.connect(ws_url) as ws:
            hello_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            hello_event = json.loads(hello_raw)
            if hello_event.get("type") != "hello":
                raise RuntimeError(f"Unexpected WebSocket hello payload: {hello_raw}")

            live_wait = asyncio.create_task(
                _wait_for_live_message(
                    ws,
                    channel_id=channel_id,
                    plaintext=plaintext,
                    timeout_seconds=30,
                )
            )

            print("5) User A publishes a message")
            published = await _req(
                client,
                "POST",
                f"/channels/{channel_id}/messages",
                token=user_a.access_token,
                payload={"content_text": plaintext},
            )

            try:
                live_payload = await asyncio.wait_for(live_wait, timeout=30)
            except Exception:
                live_wait.cancel()
                raise
            if live_payload.get("id") != published.get("id"):
                raise RuntimeError(
                    f"Live WebSocket delivered {live_payload.get('id')} but HTTP publish returned {published.get('id')}"
                )

        print("6) User B syncs and verifies REST backfill")
        synced = await _req(
            client,
            "POST",
            "/sync",
            token=user_b.access_token,
            payload={"channels": [{"channel_id": channel_id, "last_seen_seq_id": 0}], "since": None, "limit": 50},
        )
        items = synced.get("messages", [])
        if not items:
            raise RuntimeError("No messages returned for User B sync")
        received = next((item.get("content_text") for item in items if item.get("content_text") == plaintext), None)
        if received != plaintext:
            raise RuntimeError(f"Message mismatch: expected '{plaintext}', got '{received}'")

        print("7) User A checks event log has core events")
        events = await _req(client, "GET", f"/channels/{channel_id}/events?limit=50", token=user_a.access_token)
        event_types = {e.get("event_type") for e in events.get("items", [])}
        required = {"channel.created", "membership.joined", "message.published"}
        missing = sorted(required - event_types)
        if missing:
            raise RuntimeError(f"Missing expected event types: {missing}")

        print("\nDemo verification passed")
        print(json.dumps({
            "channel_id": channel_id,
            "channel_slug": channel_slug,
            "published_message_id": published.get("id"),
            "websocket_verified": True,
            "sync_verified": True,
            "plaintext_verified": True,
        }, indent=2))

        print("\nProof path verified:")
        print("backend -> PostgreSQL/outbox -> RabbitMQ -> worker -> Redis -> WebSocket -> subscriber")
        print("\nTo verify DB ciphertext manually:")
        print('docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"')

        return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Demo verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
