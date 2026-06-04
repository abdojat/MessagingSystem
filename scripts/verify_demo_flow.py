#!/usr/bin/env python
"""Quick demo verifier for publish/subscribe flow."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from dataclasses import dataclass

import httpx


@dataclass
class UserSession:
    username: str
    password: str
    access_token: str


def _req(client: httpx.Client, method: str, path: str, token: str | None = None, payload: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, path, headers=headers, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed ({response.status_code}): {response.text}")
    if response.status_code == 204:
        return {}
    return response.json()


def register_and_login(client: httpx.Client, label: str) -> UserSession:
    suffix = secrets.token_hex(4)
    username = f"demo_{label}_{suffix}"
    password = "Password123!"
    email = f"{username}@example.com"

    _req(client, "POST", "/auth/register", payload={"username": username, "email": email, "password": password})
    login = _req(client, "POST", "/auth/login", payload={"username_or_email": username, "password": password})
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify core demo flow for pub/sub messaging system")
    parser.add_argument("--base-url", default="http://localhost:8000/v1", help="API base URL")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=20.0) as client:
        print("0) Waiting for API health")
        wait_for_api(client)

        print("1) Register/login User A and User B")
        user_a = register_and_login(client, "a")
        user_b = register_and_login(client, "b")

        print("2) User A creates public/open channel 'news'")
        channel = _req(
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
        _req(client, "POST", f"/channels/{channel_id}/join", token=user_b.access_token, payload={})

        print("4) User A publishes a message")
        plaintext = f"Hello from demo {secrets.token_hex(3)}"
        published = _req(
            client,
            "POST",
            f"/channels/{channel_id}/messages",
            token=user_a.access_token,
            payload={"content_text": plaintext},
        )

        print("5) User B syncs and verifies plaintext")
        synced = _req(
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

        print("6) User A checks event log has core events")
        events = _req(client, "GET", f"/channels/{channel_id}/events?limit=50", token=user_a.access_token)
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
            "plaintext_verified": True,
        }, indent=2))

        print("\nTo verify DB ciphertext manually:")
        print('docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"')

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Demo verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
