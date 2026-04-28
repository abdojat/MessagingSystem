# Channels Stack (FastAPI + Next.js + Postgres + RabbitMQ + Redis)

Telegram-like backend with auth, channels, memberships, messages, invites, events, sync, uploads, websocket fanout, and a blank Next.js frontend starter.

## Run
```bash
cp .env.example .env
docker compose up --build
```

Data persistence:
- Uploaded files are stored in Docker volume `uploads_data` (mounted at `/data/uploads` in `backend`).
- They persist across `docker compose stop/start` and `docker compose down/up`.
- `docker compose down -v` removes volumes (`pg_data`, `rabbit_data`, `uploads_data`) and deletes stored files.

API docs:
- `http://localhost:8000/docs`
- Versioned API prefix: `/v1`
- Legacy unversioned routes remain available as temporary aliases.

Frontend:
- `http://localhost:3000`

## Migrations
```bash
docker compose run --rm backend sh -lc "alembic upgrade head"
```

## Environment Variables
- `DATABASE_URL`
- `RABBITMQ_URL`
- `REDIS_URL`
- `JWT_SECRET`
- `JWT_ACCESS_TTL_MIN`
- `JWT_REFRESH_TTL_DAYS`
- `CORS_ORIGINS` (comma-separated or JSON array, e.g. `http://localhost:3000,http://localhost:5173`)
- `UPLOAD_MAX_SIZE_BYTES` (supports up to `1073741824` bytes / 1GB)
- `UPLOADS_BASE_DIR` (docker volume path)
- `API_V1_PREFIX` (default `/v1`)
- `MESSAGE_ENCRYPTION_ENABLED` (default `true`; keep enabled outside local debugging)
- `MESSAGE_ENCRYPTION_KEY` (Fernet key; required in non-dev environments)
- `OUTBOX_POLL_INTERVAL`
- `WORKER_ONLINE_SCAN_INTERVAL`
- Frontend API base URL: `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000/v1`, applied at frontend image build time)

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
- `GET /v1/users/search?q=...&limit=...&cursor=...`
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
- `history` `{ "channel_id":"uuid", "items":[...], "is_truncated": true|false }` (optional)
- `message_updated`
- `reaction_updated`
- `membership_update`
- `channel_updated`
- `sync`
- `seen`
- `pong`
- `error` (same `{code,message,details}` shape in `payload`)

## Frontend Contracts

- All list endpoints are cursor-based unless messages, which are seq-based.
- Default pagination limits are conservative and clamped server-side.
- Cursor validation errors return `400` with code `PAGINATION_INVALID`.

Users:
- `GET /users/search`: `q` (required, trimmed), `limit` default `50` max `200`, `cursor`.
- Order is deterministic: username asc, then id asc.

Channels:
- `GET /channels`: `limit` default `50` max `200`, `cursor`, optional `q`, `visibility`, `scope=my|discover` (default `my`).
- `POST /channels`: `channel_slug` is optional; if omitted backend generates a URL-safe slug from `name` and resolves collisions with numeric suffixes.
- `my` scope lists only channels where caller has membership.
- `discover` scope lists public channels not yet joined.
- Stable order: `last_message_at desc nulls last, created_at desc, id desc`.
- `GET /channels/{id}/members`: `limit` default `50` max `200`, `cursor`, optional `role`, optional `q`.
- Stable order: role weight (`owner,admin,member,pending`), username asc, id asc.
- `GET /channels/{id}/requests`: same pagination contract, filtered to pending.
- `GET /channels/{id}/invites`: `limit` default `50` max `200`, `cursor`, optional `status=active|revoked|accepted|expired`, order `created_at desc, id desc`.
- `GET /channels/{id}/events`: `limit` default `50` max `200`, `cursor`, order `created_at desc, id desc`.

Messages:
- `GET /channels/{id}/messages`: seq pagination with `before_seq_id` and/or `after_seq_id`, `limit` default `50` max `200`, `order=asc|desc` default `desc`.
- If both `before_seq_id` and `after_seq_id` are provided, server applies a bounded window `(after_seq_id, before_seq_id)` and still honors `order`.
- Cursor progression precedence:
  - `order=desc`: page moves older and uses `next_before_seq_id`.
  - `order=asc`: page moves newer and uses `next_after_seq_id`.
- Response includes `{next_before_seq_id,next_after_seq_id,has_more,order}`.
- `GET /channels/{id}/messages/around`: `seq_id` required, `limit_before`/`limit_after` default `30` max `100`.

Idempotency and ordering:
- `POST /channels/{id}/messages` is idempotent on `(channel_id,sender_user_id,client_msg_id)`.
- Duplicate sends with same `client_msg_id` return the original message.
- `seq_id` is channel-local and strictly increasing; duplicates are prevented by DB constraints + transactional counter update.

Deleted message representation:
- `DELETE /channels/{id}/messages/{message_id}` returns `MessageResponse` with `deleted_at` set.
- When `deleted_at` is set, `content_text`, `content_json`, and `attachments` are always `null`.

Seen/unread semantics:
- `POST /channels/{id}/seen` requires exactly one of `last_seen_message_id` or `last_seen_seq_id`.
- If `last_seen_message_id` is sent, backend resolves and validates it inside the channel.
- `unread_count` is defined as: messages where `seq_id > last_seen_seq_id` and `deleted_at IS NULL`.

Invite token safety:
- Full invite token is only returned by `POST /channels/{channel_id}/invite`.
- Stored invite tokens are hashed in DB (`token_hash`); list endpoints expose only masked token fragments.

Sync and reconnect:
- `POST /sync` body supports `channels[{channel_id,last_seen_seq_id}]`, optional `since`, `limit` default `200` max `500`.
- Response shape: `{server_time, channel_updates, membership_updates, messages}`.
- `messages` are deterministic and sorted by `(channel_id, seq_id)`.
- WS is realtime-first; clients should use REST `/sync` for backfill.
- WS auth methods: query `token`, `Authorization: Bearer`, or first message `{"type":"auth","payload":{"token":"..."}}`.
- If auth is missing/invalid, socket is closed with policy violation.

Errors:
- Unified error payload: `{code,message,details}`.
- Core codes: `VALIDATION_ERROR`, `AUTH_INVALID`, `AUTH_EXPIRED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `RATE_LIMITED`, `INTERNAL_ERROR`.
- Domain codes include `INVITE_EXPIRED`, `INVITE_REVOKED`, `INVITE_INVALID`, `PAGINATION_INVALID`, and join/invite rule codes.

## Message Encryption

- Message payload encryption is application-layer using `cryptography.fernet` (authenticated encryption).
- At rest:
  - text messages are stored as encrypted token in `messages.content_text`
  - json messages are stored as encrypted token in `messages.content_json._enc_v1`
- In transit inside backend internals:
  - outbox payload for `message` and `message_updated` carries encrypted content, not plaintext.
- API and WebSocket responses decrypt content only for already authorized users.
- Key config:
  - set `MESSAGE_ENCRYPTION_KEY` in `.env`
  - generate key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  - in non-dev environments, missing/invalid key fails startup/requests with config error.
  - in `dev/test/local`, empty key uses a documented fallback key for local convenience only.

### Verify DB ciphertext manually

```bash
docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"
```

Expected:
- `content_text` should look like Fernet tokens (typically starts with `gAAAA`), not plaintext.
- json payload should be stored under `_enc_v1`, not raw business JSON.

## Tests (Minimal P0 Coverage)

Added backend tests cover:
- encryption round trip + ciphertext at rest + outbox not plaintext
- authz check for unauthorized publish/read on protected channel
- channel creation without `channel_slug`, server slug generation, slug collision handling
- event logging for channel creation and message publishing

Run:
```bash
cd backend
python -m pip install -e .
python -m pytest -q
```
