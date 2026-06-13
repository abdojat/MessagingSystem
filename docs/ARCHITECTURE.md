# Architecture

## Component Responsibilities
- Backend (FastAPI)
  - Exposes REST + WebSocket endpoints.
  - Enforces authentication/authorization.
  - Encrypts/decrypts message content.
  - Persists domain data and emits outbox/event entries.
- Worker
  - Polls outbox entries.
  - Publishes routing events to RabbitMQ.
  - Tracks delivery attempts, retry scheduling, and dead-letter transitions.
  - Supports realtime fanout integration.
- RabbitMQ
  - Broker for publish/subscribe routing across services.
  - Includes a durable dead-letter exchange/queue for operational visibility.
- Redis + WebSocket
  - Low-latency delivery path for active subscribers.
  - Targeted membership updates are allowed through the socket even when the new channel is not yet in the socket subscription set, so approval-after-connect can refresh and subscribe safely.
- PostgreSQL
  - Source of truth for users, channels, memberships, messages, outbox, and events.
- Frontend (Next.js)
  - User workflows: auth, channels, join/leave, publish/read, event logs.
  - Delivery Monitor for channel owners/admins to inspect and retry failed outbox delivery.
  - Event Log integrity check for channel owners/admins.

## High-Level Architecture
```mermaid
flowchart LR
  FE[Next.js Frontend] -->|REST + JWT| BE[FastAPI Backend]
  FE -->|WebSocket| BE

  BE -->|SQLAlchemy| PG[(PostgreSQL)]
  BE -->|Publish events| RMQ[(RabbitMQ)]
  BE -->|Realtime fanout| REDIS[(Redis)]

  WK[Worker] -->|Poll outbox| PG
  WK -->|AMQP publish| RMQ
  WK -->|Mirror dead letters| DLQ[(RabbitMQ DLQ)]
  WK -->|Redis fanout support| REDIS
```

## Message Lifecycle
```mermaid
sequenceDiagram
  participant C as Client
  participant FE as Frontend
  participant BE as Backend
  participant PG as PostgreSQL
  participant WK as Worker
  participant MQ as RabbitMQ
  participant R as Redis/WebSocket

  C->>FE: Publish message
  FE->>BE: POST /v1/channels/{id}/messages (JWT)
  BE->>BE: AuthN + membership AuthZ check
  BE->>BE: Encrypt message payload (Fernet)
  BE->>PG: Save encrypted message + outbox + event log
  BE-->>FE: 201 message response (decrypted for authorized caller)

  WK->>PG: Poll outbox
  WK->>MQ: Publish broker event
  alt AMQP publish succeeds
    WK->>PG: Mark outbox published
  else AMQP publish fails
    WK->>PG: Increment attempts and schedule retry
    WK->>PG: Mark dead_lettered after max attempts
    WK->>MQ: Mirror terminal failure to DLQ when possible
  end
  WK->>R: Push realtime fanout
  R-->>C: Subscriber receives update

  C->>FE: Open messages/events
  FE->>BE: GET messages/events (JWT)
  BE->>BE: AuthZ check + decrypt authorized message content
  BE-->>FE: Plaintext response for authorized users
```

## Event Logging Points
- `channel.created`
- `membership.*` events
- `message.published`
- `security.unauthorized_publish`
- `security.unauthorized_read`
- `broker.retry_scheduled`
- `broker.dead_lettered`
- `broker.manual_retry_requested`

Events are stored in the `events` table and shown in the frontend event-log subpage under channel details.

## Event Log Integrity
Event Integrity Upgrade v1 adds a tamper-evident hash chain to the audit log.

- New event columns: `previous_hash`, `event_hash`, `hash_algorithm`, `integrity_version`, and `integrity_scope`.
- Channel-scoped events use `integrity_scope = "channel:<channel_id>"`.
- Non-channel events use the separate `system` scope.
- New backend events created through `log_event` and worker-created broker delivery events receive SHA-256 hashes.
- The canonical hash payload includes stable event fields: event id, channel id, actor user id, event type, created timestamp, event payload, previous hash, integrity version, and integrity scope.
- Canonical JSON is serialized with sorted keys and compact separators before SHA-256 hashing.
- `GET /v1/channels/{channel_id}/events/integrity` verifies the chain for a channel and returns only summary status, counts, hashes, and the first broken event id if any.
- The frontend Event Log page includes an Audit Integrity badge and a Verify Integrity button.

This is a practical hash-chain integrity layer, not a blockchain and not external notarization. It detects later modification, insertion, reordering, and deletion that breaks links between remaining events, but tail truncation requires an external remembered last hash to prove. A database administrator who can rewrite all event rows and hashes can still forge a new chain. Existing legacy events need `python scripts/backfill_event_integrity.py` before they can verify as initialized.

## Delivery Reliability
- PostgreSQL remains the source of truth for outbox state.
- Outbox records now track `pending`, `publishing`, `published`, `retry_scheduled`, `failed`, and `dead_lettered` states, along with attempts, max attempts, next retry time, last sanitized error, publish time, and dead-letter time.
- The worker polls only due records (`pending` and due `retry_scheduled`) so failures are not hammered in a tight loop.
- Failed publishes use exponential backoff with environment-controlled defaults (`OUTBOX_MAX_ATTEMPTS`, retry delay, multiplier, and cap).
- After max attempts, the worker marks the row `dead_lettered` in PostgreSQL and tries to mirror the payload to RabbitMQ `ex.channels.dlx` / `q.dead.messages`.
- The admin delivery APIs and frontend Delivery Monitor are scoped to channels the current user manages.
- The DLQ is operational evidence only; the database status is the authoritative record.
- `scripts/verify_delivery_reliability.py` provides a supervisor-facing proof of the normal worker publish path plus a controlled dead-letter/manual retry path. It does not replace a future full broker-outage CI test.
