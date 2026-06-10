# Project Overview

## What This Project Is
Distributed Messaging System Based on a Publish/Subscribe model for channel-based communication.

Core capabilities:
- Channel/topic creation and management.
- Membership-aware publish and read permissions.
- Realtime subscriber delivery.
- Persistent message/event storage.
- Security controls (JWT auth, authorization, encryption-at-rest).
- Delivery reliability controls for outbox retry scheduling, dead-letter tracking, and admin retry.
- Tamper-evident audit log integrity using a per-scope SHA-256 hash chain.

## Why Publish/Subscribe
Pub/Sub decouples producers from consumers:
- Publishers send once to a channel.
- Subscribers receive automatically when authorized.
- Messaging scales better than direct point-to-point flows.

## Architecture Summary
- `backend` (FastAPI): API, auth/authz, encryption, persistence orchestration.
- `worker` (Python): outbox polling and AMQP/Redis fanout tasks.
- `postgres`: durable storage for users, channels, memberships, messages, outbox, events.
- `rabbitmq`: pub/sub broker for routing events/messages, plus a durable dead-letter queue for terminal delivery failures.
- `redis`: realtime fanout and WebSocket support.
- `frontend` (Next.js): demo UI for login, channels, publish/subscribe, event log, and delivery monitoring.

## Message Flow
1. Client publishes to `POST /v1/channels/{channel_id}/messages`.
2. Backend validates JWT + membership permissions.
3. Message content is encrypted with Fernet before DB persistence.
4. Encrypted payload is written to `messages` and `outbox` in Postgres.
5. Worker relays outbox events through RabbitMQ and Redis.
6. Successful broker publish marks the outbox row `published`.
7. Failed broker publish schedules retry with backoff, then marks `dead_lettered` after max attempts.
8. Channel owners/admins can inspect failed/dead-lettered deliveries and request manual retry.
9. Authorized subscribers receive updates via WebSocket and can retrieve plaintext through authorized REST/API responses.

## Security Model
- Passwords are hashed (Passlib).
- JWT signing secret is env-based (`JWT_SECRET`).
- Protected routes require auth dependencies.
- Channel actions are guarded by role/permission checks.
- Message content is encrypted at rest with `MESSAGE_ENCRYPTION_KEY`.
- Unauthorized publish/read attempts generate security event records.

## Event Logging
Channel events are stored in `events` and exposed via `GET /v1/channels/{id}/events`.
Frontend channel details page includes an Event Log panel (loading/error/empty/populated states).

Delivery reliability events include `broker.retry_scheduled`, `broker.dead_lettered`, and `broker.manual_retry_requested`. Stored errors are sanitized and should not contain secrets.

Event Integrity Upgrade v1 stores `previous_hash`, `event_hash`, `hash_algorithm`, `integrity_version`, and `integrity_scope` on new events. Channel events are chained under `channel:<channel_id>` and system events under `system`. Channel owners/admins can call `GET /v1/channels/{id}/events/integrity` from the frontend Event Log panel to show a Verified, Broken, Not initialized, or Checking state.

This is a tamper-evident audit mechanism for the university MVP. It is not a blockchain, not end-to-end trust, and not external notarization.

## Official Requirement Status
All five official requirements are implemented, with backend regression tests and a demo verifier script that exercise the main flow (see `docs/REQUIREMENTS_MAPPING.md`).
