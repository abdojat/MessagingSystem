# Project Overview

## What This Project Is
Distributed Messaging System Based on a Publish/Subscribe model for channel-based communication.

Core capabilities:
- Channel/topic creation and management.
- Membership-aware publish and read permissions.
- Realtime subscriber delivery.
- Persistent message/event storage.
- Security controls (JWT auth, authorization, encryption-at-rest).

## Why Publish/Subscribe
Pub/Sub decouples producers from consumers:
- Publishers send once to a channel.
- Subscribers receive automatically when authorized.
- Messaging scales better than direct point-to-point flows.

## Architecture Summary
- `backend` (FastAPI): API, auth/authz, encryption, persistence orchestration.
- `worker` (Python): outbox polling and AMQP/Redis fanout tasks.
- `postgres`: durable storage for users, channels, memberships, messages, outbox, events.
- `rabbitmq`: pub/sub broker for routing events/messages.
- `redis`: realtime fanout and WebSocket support.
- `frontend` (Next.js): demo UI for login, channels, publish/subscribe, event log.

## Message Flow
1. Client publishes to `POST /v1/channels/{channel_id}/messages`.
2. Backend validates JWT + membership permissions.
3. Message content is encrypted with Fernet before DB persistence.
4. Encrypted payload is written to `messages` and `outbox` in Postgres.
5. Worker relays outbox events through RabbitMQ and Redis.
6. Authorized subscribers receive updates via WebSocket and can retrieve plaintext through authorized REST/API responses.

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

## Official Requirement Status
All five official requirements are implemented, with backend regression tests and a demo verifier script that exercise the main flow (see `docs/REQUIREMENTS_MAPPING.md`).
