# Phase-3 Channels Backend (FastAPI + Postgres + RabbitMQ + Redis)

Backend for a Telegram-like channel system with:
- JWT auth + refresh sessions
- channel lifecycle and membership RBAC
- invite links and previews
- message persistence + outbox fanout + websocket delivery
- audit events and cursor pagination

## Run
```bash
cp .env.example .env
docker compose up --build
```

API: `http://localhost:8000`  
Docs: `http://localhost:8000/docs`

If you changed migrations and see errors like `relation "channels" does not exist` or `relation "outbox" does not exist`, reset local data volume and start again:
```bash
docker compose down -v
docker compose up --build
```

## Auth + Session Endpoints
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /me`
- `GET /auth/sessions` (current user only)
- `DELETE /auth/sessions/{session_id}` (current user only)
- `POST /auth/logout_all` (revokes all current-user refresh sessions, including current session)

## Channel Endpoints
- `POST /channels`
- `GET /channels` (includes `my_role` + `permissions`)
- `GET /channels/{channel_id}` (includes `my_role` + `permissions`)
- `PATCH /channels/{channel_id}` (owner only)
- `DELETE /channels/{channel_id}` (owner only, soft delete)
- `GET /channels/{channel_id}/my-membership`
- `POST /channels/{channel_id}/join`
- `POST /channels/{channel_id}/leave`
- `GET /channels/{channel_id}/members`
- `GET /channels/{channel_id}/requests`

## Invite Endpoints
- `POST /channels/{channel_id}/invite`
- `GET /channels/{channel_id}/invites` (masked token only)
- `POST /channels/{channel_id}/invites/{invite_id}/revoke`
- `GET /invites/{token}` (preview)
- `POST /invites/{token}/accept`

Invite request validation:
- Generic link: `{"is_generic": true}`
- Targeted invite: exactly one of `invited_user_id` or `invited_email`

## Message Endpoints
- `POST /channels/{channel_id}/messages`
- `GET /channels/{channel_id}/messages/{message_id}`
- `GET /channels/{channel_id}/messages?before_seq_id=&after_seq_id=&limit=`
- `GET /channels/{channel_id}/messages/around?seq_id=&limit=`
- `POST /channels/{channel_id}/seen`

`GET /channels/{channel_id}/messages` response:
```json
{
  "items": [],
  "next_before_seq_id": 0,
  "next_after_seq_id": 0,
  "has_more": false
}
```

Rules:
- `before_seq_id`: returns `seq_id < before_seq_id`, ordered descending.
- `after_seq_id`: returns `seq_id > after_seq_id`, ordered ascending.
- provide only one of `before_seq_id` or `after_seq_id`.

## Events Endpoint
- `GET /channels/{channel_id}/events?cursor=&limit=` (owner/admin)

## WebSocket Protocol (`/ws`)
Server -> client:
- `hello`: `{"type":"hello","user_id":"...","server_time":"..."}`
- `history`: `{"type":"history","channel_id":"...","items":[Message],"is_truncated":false}`
- `message`: `{"type":"message","channel_id":"...","message":Message}`
- `membership_update`: `{"type":"membership_update","channel_id":"...","user_id":"...","new_role":"...","reason":"..."}`

Client -> server:
- `sync`: `{"type":"sync","states":[{"channel_id":"...","last_seen_seq_id":12,"last_seen_at":"..."}]}`
- `seen`: `{"type":"seen","channel_id":"...","last_seen_seq_id":12,"last_seen_at":"..."}`

Membership changes (`approve/remove/promote/demote` and related role updates) emit `membership_update`.

## Common Frontend Flow (curl)
```bash
# login
TOKENS=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username_or_email":"alice","password":"password123"}')
ACCESS=$(echo "$TOKENS" | jq -r .access_token)

# me
curl -s http://localhost:8000/me -H "Authorization: Bearer $ACCESS"

# list channels
CHANNELS=$(curl -s http://localhost:8000/channels -H "Authorization: Bearer $ACCESS")
CHANNEL_ID=$(echo "$CHANNELS" | jq -r '.[0].id')

# open channel details
curl -s http://localhost:8000/channels/$CHANNEL_ID -H "Authorization: Bearer $ACCESS"

# websocket connect (example helper)
python scripts/ws_client.py --url ws://localhost:8000 --token "$ACCESS"

# load history
curl -s "http://localhost:8000/channels/$CHANNEL_ID/messages?limit=20" \
  -H "Authorization: Bearer $ACCESS"

# publish
curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/messages \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"content_text":"hello from frontend","client_msg_id":"11111111-1111-1111-1111-111111111111"}'

# seen
curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/seen \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"last_seen_seq_id":20,"last_seen_at":"2026-03-04T10:00:00+00:00"}'
```

## Invite Flow (curl)
```bash
# owner creates invite
INVITE=$(curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/invite \
  -H "Authorization: Bearer $OWNER_ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"invited_email":"bob@example.com","expires_in_hours":24}')
TOKEN=$(echo "$INVITE" | jq -r .token)
INVITE_ID=$(echo "$INVITE" | jq -r .id)

# preview
curl -s http://localhost:8000/invites/$TOKEN

# accept
curl -s -X POST http://localhost:8000/invites/$TOKEN/accept \
  -H "Authorization: Bearer $BOB_ACCESS"

# optional revoke
curl -s -X POST http://localhost:8000/channels/$CHANNEL_ID/invites/$INVITE_ID/revoke \
  -H "Authorization: Bearer $OWNER_ACCESS"
```

## Tests
```bash
docker compose build backend
docker compose run --rm backend sh -lc "pip install pytest pytest-asyncio && pytest -q"
```
