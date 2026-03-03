# Phase-3 Channels Backend (FastAPI + Postgres + RabbitMQ + Redis)

A complete local backend for a Telegram-like channels system with:
- FastAPI REST + WebSocket
- Postgres persistence with Alembic migrations
- RabbitMQ topic routing (`ex.channels`)
- Redis Pub/Sub fanout to websocket users
- JWT auth (access + refresh) with refresh session revocation
- RBAC (`owner`, `admin`, `member`, `pending`)
- Outbox pattern for durable message publish
- Reconnect catch-up using `last_seen_seq_id` and `last_seen_at`
- Private onboarding modes: direct-add, invite-only, approval-required

## Architecture (brief)
1. API publishes messages transactionally: `messages` + `outbox` in same DB transaction.
2. Worker outbox loop reads pending outbox rows and publishes to RabbitMQ `ex.channels` with routing key `channel.<channel_id>`.
3. User queues are durable (`user.<user_id>`), bound to channel routing keys for approved memberships.
4. Worker consumes `user.<user_id>` queues for online users and publishes to Redis channel `rt.user.<user_id>`.
5. Backend websocket manager subscribes to Redis `rt.user.<user_id>` and forwards to sockets.

## Repository
- `backend/`: FastAPI app + Alembic + tests
- `worker/`: outbox publisher and AMQP->Redis fanout loops
- `scripts/seed_demo.py`: demo data/bootstrap
- `scripts/ws_client.py`: simple websocket client

## Prerequisites
- Docker + Docker Compose
- (Optional) local Python for running scripts from host

## Run Locally
1. Copy env file:
```bash
cp .env.example .env
```
2. Build and run:
```bash
docker compose up --build
```
3. API: `http://localhost:8000`
4. OpenAPI: `http://localhost:8000/docs`
5. RabbitMQ management UI: `http://localhost:15672` (`guest` / `guest`)

## Migrations
Backend container runs `alembic upgrade head` automatically on startup.

Manual run:
```bash
docker compose run --rm backend alembic upgrade head
```

## Seed Demo
After stack is up:
```bash
python scripts/seed_demo.py
```
It creates demo users/channels and exercises:
- public open join
- private approval flow
- private invite-only flow
- message publish/history

## REST Examples (curl)

### Register / Login
```bash
curl -s -X POST http://localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"password123"}'

TOKENS=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username_or_email":"alice","password":"password123"}')
ACCESS=$(echo "$TOKENS" | jq -r .access_token)
REFRESH=$(echo "$TOKENS" | jq -r .refresh_token)
```

### Refresh / Logout
```bash
curl -s -X POST http://localhost:8000/auth/refresh \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}"

curl -s -X POST http://localhost:8000/auth/logout \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}"
```

### Create Channel
```bash
CHANNEL=$(curl -s -X POST http://localhost:8000/channels \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"eng","visibility":"private","join_mode":"approval_required"}')
CHANNEL_ID=$(echo "$CHANNEL" | jq -r .id)
```

### Join / Approve / Direct-Add / Invite / Accept
```bash
# Join request (approval_required => pending)
curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/join \
  -H "Authorization: Bearer $ACCESS_OTHER" \
  -H 'Content-Type: application/json' \
  -d '{}'

# Approve pending user
curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/members/$USER_ID/approve \
  -H "Authorization: Bearer $ACCESS"

# Direct-add user (owner/admin)
curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/members/$USER_ID/add \
  -H "Authorization: Bearer $ACCESS"

# Invite-only token creation
INVITE=$(curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/invite \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"invited_user_id":"'$USER_ID'","expires_in_hours":24}')
TOKEN=$(echo "$INVITE" | jq -r .token)

# Accept invite
curl -s -X POST http://localhost:8000/invites/$TOKEN/accept \
  -H "Authorization: Bearer $ACCESS_OTHER"
```

### Publish / History / Seen
```bash
curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/messages \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"content_text":"hello"}'

curl -s "http://localhost:8000/channels/$CHANNEL_ID/messages?limit=20" \
  -H "Authorization: Bearer $ACCESS"

curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/seen \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"last_seen_seq_id":10,"last_seen_at":"2026-03-03T12:00:00+00:00"}'
```

## WebSocket Example
Endpoint: `GET /ws?token=<access_token>` (also supports `Authorization: Bearer` header).

Run helper client:
```bash
pip install websockets
python scripts/ws_client.py --url ws://localhost:8000 --token "$ACCESS"
```

Inbound WS messages supported:
```json
{"type":"sync","states":[{"channel_id":"...","last_seen_seq_id":22,"last_seen_at":"2026-03-03T10:00:00+00:00"}]}
```
```json
{"type":"seen","channel_id":"...","last_seen_seq_id":22,"last_seen_at":"2026-03-03T10:00:00+00:00"}
```

## Tests
Run:
```bash
docker compose run --rm backend pytest -q
```
Includes minimal tests for:
- auth login + refresh happy path
- publish RBAC restriction
- join mode behavior

## Notes
- Passwords use bcrypt via `passlib`.
- Refresh tokens are stored hashed (`sha256`) in `user_sessions`.
- Message ordering is strict per-channel using `channel_counters.next_seq`.
- Outbox retries use exponential backoff and preserve errors in `outbox.last_error`.
