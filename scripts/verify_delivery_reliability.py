#!/usr/bin/env python
"""Supervisor-friendly delivery reliability verifier.

This script proves the normal outbox->worker publish path through the API and
uses one controlled PostgreSQL outbox row to prove dead-letter listing and
manual retry behavior. It is not a full RabbitMQ outage simulation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx


ROOT = Path(__file__).resolve().parents[1]


def _backend_dir() -> Path:
    for candidate in (ROOT / "backend", Path("/app"), Path.cwd()):
        if (candidate / "app" / "db" / "models.py").exists():
            return candidate
    return ROOT / "backend"


BACKEND_DIR = _backend_dir()
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _read_dotenv_value(name: str) -> str | None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def _running_inside_container() -> bool:
    return Path("/.dockerenv").exists()


def _host_adjusted_database_url(database_url: str) -> str:
    if _running_inside_container():
        return database_url
    return database_url.replace("@postgres:", "@127.0.0.1:").replace("@postgres/", "@127.0.0.1/")


def _prepare_database_url() -> None:
    database_url = os.environ.get("DATABASE_URL") or _read_dotenv_value("DATABASE_URL")
    if not database_url:
        database_url = "postgresql+asyncpg://postgres:postgres@postgres:5432/channels"
    os.environ["DATABASE_URL"] = _host_adjusted_database_url(database_url)


def _mask_url(value: str) -> str:
    if "://" not in value or "@" not in value:
        return value
    scheme, rest = value.split("://", 1)
    credentials, host = rest.split("@", 1)
    if ":" in credentials:
        user, _ = credentials.split(":", 1)
        return f"{scheme}://{user}:***@{host}"
    return f"{scheme}://***@{host}"


_prepare_database_url()

from app.core.utils import utcnow  # noqa: E402
from app.db.models import Outbox, OutboxStatus  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


@dataclass
class UserSession:
    user_id: str
    username: str
    access_token: str


def _step(title: str) -> None:
    print(f"[STEP] {title}")


def _pass(message: str) -> None:
    print(f"[PASS] {message}")


def _info(message: str) -> None:
    print(f"[INFO] {message}")


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
    expected_status: int,
) -> None:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = await client.request(method, path, headers=headers)
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{method} {path} expected {expected_status}, got {response.status_code}: {response.text}"
        )


async def register_and_login(client: httpx.AsyncClient, label: str) -> UserSession:
    suffix = secrets.token_hex(4)
    username = f"delivery_{label}_{suffix}"
    password = "Password123!"
    email = f"{username}@example.com"
    registered = await _req(
        client,
        "POST",
        "/auth/register",
        payload={"username": username, "email": email, "password": password},
    )
    login = await _req(client, "POST", "/auth/login", payload={"username_or_email": username, "password": password})
    return UserSession(user_id=registered["id"], username=username, access_token=login["access_token"])


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


async def _wait_for_published_count(
    client: httpx.AsyncClient,
    token: str,
    *,
    minimum: int,
    timeout_seconds: int,
) -> dict:
    deadline = time.time() + timeout_seconds
    latest: dict | None = None
    while time.time() < deadline:
        latest = await _req(client, "GET", "/admin/delivery/stats", token=token)
        if int(latest.get("published") or 0) >= minimum:
            return latest
        await asyncio.sleep(1)
    raise RuntimeError(f"Timed out waiting for published delivery count >= {minimum}; latest={latest}")


async def _insert_controlled_dead_letter(channel_id: str, channel_slug: str) -> str:
    async with SessionLocal() as db:
        row = Outbox(
            aggregate_type="delivery_probe",
            aggregate_id=uuid4(),
            channel_id=UUID(channel_id),
            payload={
                "type": "delivery_probe",
                "probe_id": str(uuid4()),
                "note": "controlled verifier row; not a user message",
            },
            type="delivery_probe",
            routing_key=f"channel.{channel_slug}",
            status=OutboxStatus.dead_lettered,
            attempts=5,
            max_attempts=5,
            last_error="controlled verifier dead-letter row",
            dead_lettered_at=utcnow(),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return str(row.id)


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Verify delivery reliability proof path")
    parser.add_argument("--base-url", default="http://localhost:8000/v1", help="API base URL")
    parser.add_argument("--publish-timeout", type=int, default=60, help="Seconds to wait for worker publish")
    args = parser.parse_args()

    _info(f"Using DATABASE_URL={_mask_url(os.environ.get('DATABASE_URL', ''))}")
    _info("For the canonical Docker run, use:")
    _info('docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/verify_delivery_reliability.py --base-url http://localhost:8000/v1"')

    with httpx.Client(base_url=args.base_url, timeout=20.0) as health_client:
        _step("0) Waiting for API health")
        wait_for_api(health_client)
        _pass("API health check passed")

    async with httpx.AsyncClient(base_url=args.base_url, timeout=20.0) as client:
        _step("1) Register/login channel owner and outsider")
        owner = await register_and_login(client, "owner")
        outsider = await register_and_login(client, "outsider")
        _pass(f"Registered {owner.username} and {outsider.username}")

        _step("2) Owner creates a delivery verifier channel")
        channel = await _req(
            client,
            "POST",
            "/channels",
            token=owner.access_token,
            payload={
                "name": "delivery-verifier",
                "visibility": "public",
                "join_mode": "open",
                "description": "Delivery verifier channel",
            },
        )
        channel_id = channel["id"]
        channel_slug = channel["channel_slug"]
        _pass(f"Created channel {channel_slug} ({channel_id})")

        _step("3) Owner publishes a message and worker marks the outbox published")
        before_stats = await _req(client, "GET", "/admin/delivery/stats", token=owner.access_token)
        published_before = int(before_stats.get("published") or 0)
        message_text = f"Delivery reliability probe {secrets.token_hex(3)}"
        published = await _req(
            client,
            "POST",
            f"/channels/{channel_id}/messages",
            token=owner.access_token,
            payload={"content_text": message_text},
        )
        after_stats = await _wait_for_published_count(
            client,
            owner.access_token,
            minimum=published_before + 1,
            timeout_seconds=args.publish_timeout,
        )
        _pass(f"Outbox publish completed for message {published.get('id')}")

        _step("4) Controlled dead-letter row is visible in Delivery Monitor API")
        # Insert a controlled dead-letter row instead of forcing a real broker
        # outage; the verifier proves the monitor and manual retry behavior.
        controlled_outbox_id = await _insert_controlled_dead_letter(channel_id, channel_slug)
        dead_lettered = await _req(client, "GET", "/admin/delivery/dead-lettered?limit=100", token=owner.access_token)
        if not any(item.get("id") == controlled_outbox_id for item in dead_lettered.get("items", [])):
            raise RuntimeError(f"Controlled dead-letter row {controlled_outbox_id} was not listed")
        _pass(f"Controlled dead-letter row listed: {controlled_outbox_id}")

        _step("5) Manual retry resets the controlled row to pending")
        retry = await _req(
            client,
            "POST",
            f"/admin/delivery/{controlled_outbox_id}/retry",
            token=owner.access_token,
            payload={},
        )
        if retry.get("retried_count") != 1:
            raise RuntimeError(f"Manual retry did not reset the controlled row: {retry}")
        retry_item = retry.get("items", [{}])[0]
        if retry_item.get("status") != "pending":
            raise RuntimeError(f"Manual retry item was not pending after reset: {retry_item}")
        _pass("Manual retry endpoint reset dead-lettered row to pending")

        _step("6) Outsider cannot read delivery monitor stats")
        await _expect_status(
            client,
            "GET",
            "/admin/delivery/stats",
            token=outsider.access_token,
            expected_status=403,
        )
        _pass("Delivery monitor authorization denied outsider access")

        print("\n[PASS] Delivery reliability verification passed")
        print(
            json.dumps(
                {
                    "channel_id": channel_id,
                    "published_message_id": published.get("id"),
                    "published_before": published_before,
                    "published_after": int(after_stats.get("published") or 0),
                    "controlled_dead_lettered_outbox_id": controlled_outbox_id,
                    "manual_retry_status": retry_item.get("status"),
                    "proof_scope": "normal worker publish plus controlled DB dead-letter/manual retry",
                    "not_proved": "full RabbitMQ outage CI scenario",
                },
                indent=2,
            )
        )
        return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] Delivery reliability verification failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        print("[INFO] Check DATABASE_URL credentials or run the canonical Docker command printed above.", file=sys.stderr)
        raise SystemExit(1)
