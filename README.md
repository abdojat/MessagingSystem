# Channels Backend (FastAPI + Postgres + RabbitMQ + Redis)

Telegram-like backend with auth, channels, memberships, messages, invites, events, sync, uploads, and websocket fanout.

## Run
```bash
cp .env.example .env
docker compose up --build
```

API docs:
- `http://localhost:8000/docs`
- Versioned API prefix: `/v1`
- Legacy unversioned routes remain available as temporary aliases.

## Migrations
```bash
docker compose run --rm backend sh -lc "alembic upgrade head"
```

## Seed Demo Data
```bash
python scripts/seed_demo.py
```

## Tests
```bash
docker compose run --rm backend sh -lc "pytest -q"
```

## Environment Variables
- `DATABASE_URL`
- `RABBITMQ_URL`
- `REDIS_URL`
- `JWT_SECRET`
- `JWT_ACCESS_TTL_MIN`
- `JWT_REFRESH_TTL_DAYS`
- `CORS_ORIGINS` (JSON array, e.g. `["http://localhost:3000","http://localhost:5173"]`)
- `UPLOAD_MAX_SIZE_BYTES` (supports up to `1073741824` bytes / 1GB)
- `UPLOADS_BASE_DIR` (docker volume path)
- `API_V1_PREFIX` (default `/v1`)
- `OUTBOX_POLL_INTERVAL`
- `WORKER_ONLINE_SCAN_INTERVAL`

## Key Endpoints (`/v1`)

Auth:
- `POST /v1/auth/register`
- `POST /v1/auth/login`
- `POST /v1/auth/refresh`
- `POST /v1/auth/logout`
- `GET /v1/auth/sessions`
- `DELETE /v1/auth/sessions/{session_id}`
- `POST /v1/auth/logout_all`
- `GET /v1/me`

Users:
- `GET /v1/users/search?query=...&limit=...&cursor=...`
- `GET /v1/users/{user_id}`

Channels:
- `POST /v1/channels`
- `GET /v1/channels?limit=...&cursor=...`
- `GET /v1/channels/{channel_id}`
- `PATCH /v1/channels/{channel_id}`
- `DELETE /v1/channels/{channel_id}`
- `GET /v1/channels/{channel_id}/stats`
- `GET /v1/channels/{channel_id}/members`
- `GET /v1/channels/{channel_id}/requests`
- `POST /v1/channels/{channel_id}/join`
- `POST /v1/channels/{channel_id}/leave`

Invites:
- `POST /v1/channels/{channel_id}/invite`
- `GET /v1/channels/{channel_id}/invites`
- `POST /v1/channels/{channel_id}/invites/{invite_id}/revoke`
- `GET /v1/invites/{token}`
- `POST /v1/invites/{token}/accept`

Messages:
- `POST /v1/channels/{channel_id}/messages`
- `GET /v1/channels/{channel_id}/messages`
- `GET /v1/channels/{channel_id}/messages/{message_id}`
- `PATCH /v1/channels/{channel_id}/messages/{message_id}`
- `DELETE /v1/channels/{channel_id}/messages/{message_id}`
- `POST /v1/channels/{channel_id}/messages/{message_id}/reactions`
- `DELETE /v1/channels/{channel_id}/messages/{message_id}/reactions/{emoji}`
- `POST /v1/channels/{channel_id}/pins/{message_id}`
- `DELETE /v1/channels/{channel_id}/pins/{message_id}`
- `GET /v1/channels/{channel_id}/pins`
- `POST /v1/channels/{channel_id}/seen`

Uploads:
- `POST /v1/uploads`
- `PUT /v1/uploads/{file_id}/content`
- `GET /v1/uploads/{file_id}/content`

Sync:
- `POST /v1/sync`

Health:
- `GET /v1/health`

## Example curl
```bash
# login
TOKENS=$(curl -s -X POST http://localhost:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username_or_email":"alice","password":"password123"}')
ACCESS=$(echo "$TOKENS" | jq -r .access_token)

# list channels (frontend-ready summary)
curl -s "http://localhost:8000/v1/channels?limit=20" \
  -H "Authorization: Bearer $ACCESS"

# idempotent message send
curl -s -X POST http://localhost:8000/v1/channels/$CHANNEL_ID/messages \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"content_text":"hello","client_msg_id":"11111111-1111-1111-1111-111111111111"}'

# sync
curl -s -X POST http://localhost:8000/v1/sync \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"channels":[{"channel_id":"'$CHANNEL_ID'","last_seen_seq_id":5}],"since":null,"limit":200}'

# seen marker (exactly one of last_seen_seq_id / last_seen_message_id)
curl -s -X POST http://localhost:8000/v1/channels/$CHANNEL_ID/seen \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"last_seen_seq_id":10}'
```

## WebSocket (`/ws` and `/v1/ws`)

Envelope (client and server):
```json
{
  "type": "string",
  "request_id": "uuid|null",
  "payload": {},
  "ts": "2026-03-04T12:00:00+00:00"
}
```

Client -> server types:
- `auth` `{ "token": "jwt" }` (only needed when no query/header token used)
- `subscribe` `{ "channel_ids": ["uuid"], "from_seq_id": 10 }`
- `unsubscribe` `{ "channel_ids": ["uuid"] }`
- `resume` `{ "channels": [{"channel_id":"uuid","last_seen_seq_id":123}], "since": null }`
- `seen` `{ "channel_id":"uuid","last_seen_seq_id":10 }`
- `ping` `{}`

Server -> client types:
- `hello`
- `message`
- `message_updated`
- `reaction_updated`
- `membership_update`
- `channel_updated`
- `sync`
- `seen`
- `pong`
- `error` (same `{code,message,details}` shape in `payload`)
