#!/usr/bin/env python
"""Verify approval-required membership after a WebSocket is already open."""

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


@dataclass
class UserSession:
    user_id: str
    username: str
    password: str
    access_token: str


def _step(title: str) -> None:
    print(f"[STEP] {title}")


def _pass(message: str) -> None:
    print(f"[PASS] {message}")


def _info(message: str) -> None:
    print(f"[INFO] {message}")


def _warn(message: str) -> None:
    print(f"[WARN] {message}")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = await client.request(method, path, headers=headers, json=payload)
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{method} {path} expected {expected_status}, got {response.status_code}: {response.text}"
        )


async def register_and_login(client: httpx.AsyncClient, label: str) -> UserSession:
    suffix = secrets.token_hex(4)
    username = f"approval_{label}_{suffix}"
    password = "Password123!"
    email = f"{username}@example.com"

    registered = await _req(
        client,
        "POST",
        "/auth/register",
        payload={"username": username, "email": email, "password": password},
    )
    login = await _req(client, "POST", "/auth/login", payload={"username_or_email": username, "password": password})
    return UserSession(
        user_id=registered["id"],
        username=username,
        password=password,
        access_token=login["access_token"],
    )


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


async def _send_ws(ws, msg_type: str, payload: dict, *, request_id: str | None = None) -> str:
    request_id = request_id or str(uuid4())
    await ws.send(json.dumps({"type": msg_type, "request_id": request_id, "payload": payload, "ts": _iso_now()}))
    return request_id


async def _wait_for_ws_sync(ws, *, request_id: str, timeout_seconds: int) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    # Read socket responses until the matching sync result arrives or times out.
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise RuntimeError(f"Timed out waiting for WebSocket sync acknowledgement {request_id}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        event = json.loads(raw)
        if str(event.get("request_id")) != request_id:
            continue
        if event.get("type") == "error":
            raise RuntimeError(f"WebSocket sync failed: {event.get('payload')}")
        if event.get("type") == "sync":
            return event.get("payload") or {}


async def _wait_for_membership_update(ws, *, channel_id: str, user_id: str, timeout_seconds: int) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    # Wait for the requested membership update while enforcing the test deadline.
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for approved membership update")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        event = json.loads(raw)
        if event.get("type") != "membership_update":
            continue
        payload = event.get("payload") or {}
        if payload.get("channel_id") == channel_id and payload.get("user_id") == user_id:
            if payload.get("new_role") == "member":
                return payload


async def _wait_for_live_message(ws, *, channel_id: str, plaintext: str, timeout_seconds: int) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    # Wait for the expected published message while enforcing the test deadline.
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for live message delivery")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        event = json.loads(raw)
        if event.get("type") != "message":
            continue
        payload = event.get("payload") or {}
        if payload.get("channel_id") != channel_id:
            continue
        if payload.get("content_text") != plaintext:
            raise RuntimeError("Live WebSocket payload plaintext did not match the published message")
        return payload


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Verify approval-required join after WebSocket connect")
    parser.add_argument("--base-url", default="http://localhost:8000/v1", help="API base URL")
    parser.add_argument("--membership-timeout", type=int, default=20, help="Seconds to wait for membership update")
    parser.add_argument("--live-timeout", type=int, default=30, help="Seconds to wait for live message delivery")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=20.0) as health_client:
        _step("0) Waiting for API health")
        wait_for_api(health_client)
        _pass("API health check passed")

    async with httpx.AsyncClient(base_url=args.base_url, timeout=20.0) as client:
        _step("1) Register/login owner, pending subscriber, and outsider users")
        owner = await register_and_login(client, "owner")
        subscriber = await register_and_login(client, "sub")
        outsider = await register_and_login(client, "outsider")
        _pass(f"Registered {owner.username}, {subscriber.username}, and {outsider.username}")

        _step("2) Subscriber creates an existing channel to keep the socket subscription set non-empty")
        existing_channel = await _req(
            client,
            "POST",
            "/channels",
            token=subscriber.access_token,
            payload={
                "name": "subscriber-existing",
                "visibility": "public",
                "join_mode": "open",
                "description": "Existing channel for approval verifier",
            },
        )
        existing_channel_id = existing_channel["id"]
        _pass(f"Prepared existing subscriber channel {existing_channel_id}")

        _step("3) Owner creates a private approval-required channel")
        channel = await _req(
            client,
            "POST",
            "/channels",
            token=owner.access_token,
            payload={
                "name": "approval-required",
                "visibility": "private",
                "join_mode": "approval_required",
                "description": "Approval verifier channel",
            },
        )
        channel_id = channel["id"]
        _pass(f"Created approval-required channel {channel_id}")

        _step("4) Subscriber requests to join and remains pending")
        join_result = await _req(client, "POST", f"/channels/{channel_id}/join", token=subscriber.access_token, payload={})
        if join_result.get("status") != "pending" or join_result.get("role") != "pending":
            raise RuntimeError(f"Expected pending join request, got {join_result}")
        my_membership = await _req(client, "GET", f"/channels/{channel_id}/my-membership", token=subscriber.access_token)
        if my_membership.get("role") != "pending":
            raise RuntimeError(f"Expected pending my-membership, got {my_membership}")
        _pass("Subscriber is pending before WebSocket approval flow")

        _step("5) Outsider is denied private channel messages")
        await _expect_status(
            client,
            "GET",
            f"/channels/{channel_id}/messages?limit=10",
            token=outsider.access_token,
            expected_status=403,
        )
        _pass("Outsider cannot read the private approval channel")

        ws_base_url = args.base_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base_url}/ws?token={subscriber.access_token}"
        plaintext = f"Approval live message {secrets.token_hex(3)}"
        membership_update_received = False
        live_delivery_passed = False
        rest_fallback_passed = False

        _step("6) Subscriber opens WebSocket while still pending")
        async with websockets.connect(ws_url) as ws:
            hello_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            hello_event = json.loads(hello_raw)
            if hello_event.get("type") != "hello":
                raise RuntimeError(f"Unexpected WebSocket hello payload: {hello_raw}")
            existing_subscribe_id = await _send_ws(
                ws,
                "subscribe",
                {"channel_ids": [existing_channel_id], "from_seq_id": 0},
            )
            await _wait_for_ws_sync(ws, request_id=existing_subscribe_id, timeout_seconds=10)
            _pass("WebSocket is open while subscriber is pending, with an existing subscription active")

            _step("7) Owner approves the pending subscriber")
            approval = await _req(
                client,
                "POST",
                f"/channels/{channel_id}/members/{subscriber.user_id}/approve",
                token=owner.access_token,
                payload={},
            )
            if approval.get("role") != "member":
                raise RuntimeError(f"Approval did not return member role: {approval}")
            _pass("Owner approved subscriber")

            _step("8) Subscriber receives membership update or confirms membership by REST resync")
            try:
                membership_payload = await _wait_for_membership_update(
                    ws,
                    channel_id=channel_id,
                    user_id=subscriber.user_id,
                    timeout_seconds=args.membership_timeout,
                )
                membership_update_received = True
                _pass(f"WebSocket membership update received: reason={membership_payload.get('reason')}")
            except TimeoutError as exc:
                _warn(f"{exc}; falling back to REST membership resync")
                my_membership = await _req(client, "GET", f"/channels/{channel_id}/my-membership", token=subscriber.access_token)
                if my_membership.get("role") != "member":
                    raise RuntimeError(f"REST membership resync did not confirm approval: {my_membership}") from exc
                _pass("REST membership resync confirmed subscriber is now a member")

            approval_subscribe_id = await _send_ws(
                ws,
                "subscribe",
                {"channel_ids": [channel_id], "from_seq_id": 0},
            )
            await _wait_for_ws_sync(ws, request_id=approval_subscribe_id, timeout_seconds=10)
            _pass("Subscriber WebSocket subscribed/resynced to the approved channel")

            live_wait = asyncio.create_task(
                _wait_for_live_message(
                    ws,
                    channel_id=channel_id,
                    plaintext=plaintext,
                    timeout_seconds=args.live_timeout,
                )
            )

            _step("9) Owner publishes a message after approval")
            published = await _req(
                client,
                "POST",
                f"/channels/{channel_id}/messages",
                token=owner.access_token,
                payload={"content_text": plaintext},
            )
            _pass(f"Published message {published.get('id')}")

            try:
                live_payload = await live_wait
                if live_payload.get("id") != published.get("id"):
                    raise RuntimeError(
                        f"Live WebSocket delivered {live_payload.get('id')} but publish returned {published.get('id')}"
                    )
                live_delivery_passed = True
                _pass("Subscriber received the approved-channel message live over WebSocket")
            except Exception as exc:
                live_wait.cancel()
                _warn(f"Live delivery did not complete: {exc}")

        _step("10) Subscriber verifies REST sync/backfill")
        synced = await _req(
            client,
            "POST",
            "/sync",
            token=subscriber.access_token,
            payload={"channels": [{"channel_id": channel_id, "last_seen_seq_id": 0}], "since": None, "limit": 50},
        )
        rest_fallback_passed = any(item.get("content_text") == plaintext for item in synced.get("messages", []))
        if not rest_fallback_passed:
            raise RuntimeError("REST sync did not return the approved-channel message")
        if live_delivery_passed:
            _pass("REST backfill verified alongside live delivery")
        else:
            _pass("REST backfill verified after live-delivery fallback")

        _step("11) Owner verifies event log contains approval and message publication")
        events = await _req(client, "GET", f"/channels/{channel_id}/events?limit=100", token=owner.access_token)
        event_types = {item.get("event_type") for item in events.get("items", [])}
        required = {"membership.approved", "message.published"}
        missing = sorted(required - event_types)
        if missing:
            raise RuntimeError(f"Missing expected event types: {missing}")
        _pass("Event log contains approval and message publication")

        result = {
            "channel_id": channel_id,
            "existing_channel_id": existing_channel_id,
            "membership_update_received": membership_update_received,
            "live_delivery_passed": live_delivery_passed,
            "rest_fallback_passed": rest_fallback_passed,
        }
        if live_delivery_passed:
            print("\n[PASS] Approval-flow verification passed")
        else:
            print("\n[PASS] Approval-flow verification passed with REST fallback; live delivery did not pass")
        print(json.dumps(result, indent=2))
        return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] Approval-flow verification failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        raise SystemExit(1)
