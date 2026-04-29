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
  - Supports realtime fanout integration.
- RabbitMQ
  - Broker for publish/subscribe routing across services.
- Redis + WebSocket
  - Low-latency delivery path for active subscribers.
- PostgreSQL
  - Source of truth for users, channels, memberships, messages, outbox, and events.
- Frontend (Next.js)
  - User workflows: auth, channels, join/leave, publish/read, event logs.

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

Events are stored in `events` table and shown in frontend channel details.
