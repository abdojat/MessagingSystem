# Distributed Messaging System Based on Publish/Subscribe Model

University final-year project implementing a secure distributed channel messaging platform with FastAPI, PostgreSQL, RabbitMQ, Redis/WebSocket, worker processing, and Next.js frontend.

## Architecture Summary
- Backend API: FastAPI (`backend/`)
- Worker: outbox + broker fanout (`worker/`)
- Persistence: PostgreSQL
- Broker: RabbitMQ
- Realtime: Redis + WebSocket
- Frontend: Next.js (`frontend/`)
- Recommended hardened HTTP path: Nginx (`docker-compose.hardened.yml`) in front of the unexposed backend/frontend
- Production-oriented path: TLS Nginx edge plus private authenticated state services, one-shot migrations, runtime PostgreSQL role, and restricted non-root application containers (`docker-compose.production.yml`)
- Reliability: PostgreSQL outbox status tracking, worker retry/backoff, RabbitMQ DLQ, admin Delivery Monitor
- Abuse resistance: atomic Redis/local-fallback rate limits, WebSocket frame/command/history budgets, message/protocol bounds, account quotas, bounded RabbitMQ user queues, and paced Redis fanout retries
- Integrity: tamper-evident event audit hash chain, verification API, backfill script, frontend Event Log badge/check
- Data protection: versioned message encryption, authenticated chunked upload storage, bounded migration/status tooling, and explicit historical-key rotation
- Platform administration: environment-bootstrapped superadmin, global audit view, user/session controls, channel suspension/restoration, and global delivery recovery

## Services
- `postgres` (5432)
- `rabbitmq` (5672, 15672)
- `redis` (6379)
- `backend` (8000)
- `worker`
- `frontend` (3000)

## Quick Start
```bash
cp .env.example .env
# For non-development data, generate a 32-byte master key, assign a safe key ID,
# and place both values in DATA_ENCRYPTION_* in the untracked .env:
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

docker compose config
docker compose up -d --build
docker compose ps -a
```

For the deterministic supervisor sequence, use the [Golden Demo Path](docs/DEMO_GUIDE.md#golden-demo-path).

The command above remains the convenient direct-port development path. For the
repository's recommended proxy-bounded path, expose only Nginx on port 8080:

```bash
docker compose -f docker-compose.hardened.yml config
docker compose -f docker-compose.hardened.yml up -d --build
```

Open `http://localhost:8080`. This separate path keeps PostgreSQL, RabbitMQ,
Redis, backend, and frontend ports inside the Docker network. It adds request
body/header bounds, connection limits, buffering, and inactivity timeouts; it
does not add TLS or make the full deployment production-ready.

### Production-oriented single-host path

`docker-compose.production.yml` is separate from both local workflows. Copy
`.env.production.example` to an untracked `.env.production`, replace every
placeholder with a URL-safe random value, and supply a TLS certificate/private
key from operator-controlled paths. Then run:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yml ps -a
```

Only host ports 80/443 are published. HTTP redirects to HTTPS. PostgreSQL,
RabbitMQ, Redis, backend, worker, and frontend remain private. The one-shot
`migrate` service applies Alembic/schema repair and grants the non-superuser
runtime role before backend/worker start; normal backend startup runs only
Uvicorn. Initial superadmin provisioning is explicit:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml \
  --profile bootstrap run --rm bootstrap-superadmin
```

Do not retain `SUPERADMIN_PASSWORD` after provisioning. TLS files and
`.env.production` must remain untracked. This profile is production-oriented
for the single-host university MVP; it is not an HA, managed-KMS, or
enterprise-orchestrated deployment.

## Environment Variables
See `.env.example`.
Important:
- `DATABASE_URL`
- `RABBITMQ_URL`
- `REDIS_URL`
- `JWT_SECRET` (replace the development default; only `dev`, `development`, `local`, and `test` allow placeholders; every other environment label requires a strong deployment secret)
- `JWT_ACCESS_TTL_MIN` (default `30`), `JWT_REFRESH_TTL_DAYS` (idle lifetime, default `14`), and `SESSION_ABSOLUTE_TTL_DAYS` (non-sliding maximum, default `30`)
- `WS_TICKET_TTL_SECONDS` (single-use Redis-backed WebSocket ticket lifetime, default `30` seconds)
- `WS_MAX_INBOUND_MESSAGE_BYTES` (default `16384`; enforced by Docker Uvicorn and again before application JSON parsing)
- `WS_COMMAND_BUDGET_CAPACITY`, `WS_COMMAND_BUDGET_REFILL_PER_SECOND`, `WS_HISTORY_BUDGET_CAPACITY`, `WS_HISTORY_BUDGET_REFILL_PER_SECOND`, and `WS_HISTORY_BATCH_LIMIT` (per-socket weighted work and history-row bounds)
- `DATA_ENCRYPTION_ACTIVE_KEY_ID` (safe ID for all new message/upload writes)
- `DATA_ENCRYPTION_KEYS` (JSON object containing at most 32 historical/current URL-safe base64 32-byte master keys)
- `MESSAGE_ENCRYPTION_KEY` (deprecated legacy-v1 Fernet decryption/migration key only; new writes never use it)
- `ALLOW_LEGACY_PLAINTEXT_MESSAGES`, `ALLOW_LEGACY_PLAINTEXT_UPLOADS` (explicit migration-window compatibility; production-like environments reject `true`)
- `UPLOAD_MAX_SIZE_BYTES` (defaults to 25 MiB; upload bodies are streamed and bounded by this value)
- `API_REQUEST_BODY_MAX_BYTES` (defaults to 128 KiB for ordinary `POST`/`PUT`/`PATCH`/`DELETE` bodies; the protected upload-content `PUT` keeps its separate streaming limit)
- `MESSAGE_TEXT_MAX_BYTES`, `MESSAGE_JSON_MAX_BYTES`, `MESSAGE_JSON_MAX_DEPTH` (validated before encryption/outbox work)
- `RATE_LIMIT_*` grouped auth/search/message/media/channel/WebSocket/sync/admin limits; `RATE_LIMIT_LOCAL_MAX_KEYS` bounds the fail-closed per-process sensitive fallback used when Redis is unavailable
- `MAX_CHANNELS_OWNED_PER_USER`, `MAX_ACTIVE_INVITES_PER_USER`, `MAX_UPLOADS_PER_USER_PER_DAY`, `MAX_PENDING_UPLOADS_PER_USER`, `MAX_STORED_UPLOAD_BYTES_PER_USER`, and `MAX_WEBSOCKET_CONNECTIONS_PER_USER`
- `MAX_CONCURRENT_DOWNLOADS_PER_USER` (3), `MAX_CONCURRENT_DOWNLOADS_PER_IP` (12), and `MAX_CONCURRENT_DOWNLOADS_GLOBAL` (100) atomically bound protected streams in each backend process
- `TRUSTED_PROXY_CIDRS` is empty in direct mode; set it only to explicit proxy peers that overwrite `X-Forwarded-For` (the hardened Compose file supplies its fixed proxy `/32`)
- `AUTH_COOKIE_SECURE` is derived safely from `ENVIRONMENT` when omitted; production-like environments use Secure `__Host-` refresh/CSRF cookies and reject an explicit false value
- `TRUSTED_HOSTS` controls FastAPI Host validation; production Compose also rejects unknown hosts at Nginx
- `ENABLE_API_DOCS` defaults on only for explicit development/test environments and off for production-like environments
- `WS_MEMBERSHIP_AUTH_CACHE_TTL_SECONDS` (default `1.0`; short fallback window for matching/older realtime membership generations)
- `RABBIT_USER_QUEUE_EXPIRES_MS`, `RABBIT_USER_QUEUE_MESSAGE_TTL_MS`, `RABBIT_USER_QUEUE_MAX_LENGTH`; PostgreSQL/REST sync remains authoritative after realtime queue expiry/eviction
- `REDIS_FANOUT_MAX_ATTEMPTS`, `REDIS_FANOUT_INITIAL_RETRY_DELAY_SECONDS`, `REDIS_FANOUT_MAX_RETRY_DELAY_SECONDS`
- `OUTBOX_MAX_ATTEMPTS`
- `OUTBOX_INITIAL_RETRY_DELAY_SECONDS`
- `OUTBOX_RETRY_BACKOFF_MULTIPLIER`
- `OUTBOX_MAX_RETRY_DELAY_SECONDS`
- `NEXT_PUBLIC_API_BASE_URL`
- `SUPERADMIN_USERNAME`, `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD` (optional bootstrap; password must be at least 12 characters)
- Keep `.env` local only; the repository tracks `.env.example` for documentation.

Development note:
- In explicit `dev`, `development`, `local`, and `test`, an empty data key ring uses a deterministic development-only master key and logs a warning. Never use that fallback for deployment data.
- Every other environment label, including unknown deployment aliases, is production-like: startup rejects missing/default/weak JWT secrets, missing/invalid data key rings, unknown active IDs, and plaintext-compatibility flags.
- Access JWTs are bound to their database session. Logout, explicit revocation, logout-all, replay detection, absolute expiry, and account deactivation invalidate later HTTP authentication immediately.
- WebSocket clients obtain a short-lived, one-time opaque ticket with `POST /auth/ws-ticket`; long-lived access JWTs are not accepted in WebSocket URLs. Redis control events close matching sockets across backend instances when Redis is available.
- Browser clients use `/auth/browser/login`, `/refresh`, `/logout`, and `/csrf`: the access JWT exists only in the in-memory Zustand store, the rotating refresh JWT is an HttpOnly cookie, and refresh/logout require an allowed Origin plus a constant-time double-submit CSRF check. Legacy JSON token endpoints remain available for scripts and non-browser clients.
- Established sockets use per-socket weighted command and history-row token buckets. Subscribe/resume history is capped globally per command, identical subscribe/cursor requests do not refetch history, and inbound dispatch remains one command at a time. These budgets are per backend process/socket, not a distributed global quota.
- Generic invite links are reusable until revoked, expired, or their channel is deleted. Targeted invites are one-use and accept/revoke/delete ordering is serialized through PostgreSQL row locks. Existing-account email targets resolve once to immutable `user_id`; unresolved pre-registration email targets require verified ownership of the normalized email. Changing an account email clears verification. The repository intentionally does not implement email delivery/verification issuance, so a deployment must supply that trusted completion flow before unresolved email invites can be accepted.
- Membership topology is stored as versioned desired state in PostgreSQL and snapshotted through the outbox. The worker locks the user/channel state, rejects stale generations, re-derives current authorization, removes obsolete slug bindings, and retries a complete idempotent projection. Run `python -m app.db.reconcile_broker_bindings` in the backend environment to enqueue a full repair from PostgreSQL.
- Security-sensitive database writes follow the documented global lock order in [`backend/docs/LOCK_ORDERING.md`](backend/docs/LOCK_ORDERING.md). Worker retry/dead-letter state commits before its best-effort diagnostic event transaction, avoiding the historical binding-row/event-advisory inversion.
- RabbitMQ user queues are bounded realtime buffers (expiry, message TTL, maximum length). Missed or evicted events are recovered through PostgreSQL-backed REST sync.
For development/demo Compose, set `SUPERADMIN_USERNAME` and a unique 12+ character `SUPERADMIN_PASSWORD` in the untracked `.env` before startup. Production does not bootstrap during backend startup; use the explicit profile command above. `SUPERADMIN_EMAIL` is optional. Bootstrap never resets a password or auto-promotes an existing normal account.

## Migrations
```bash
docker compose run --rm backend sh -lc "alembic upgrade head"
```

Migration `0022_phase9_upload_encryption` adds upload storage version/key-ID
metadata only. It never decrypts data. During an intentional legacy migration
window, enable the relevant compatibility flag and run the bounded operator
commands from the backend environment:

```bash
python -m app.db.crypto_tool status
python -m app.db.crypto_tool migrate-messages
python -m app.db.crypto_tool migrate-uploads
python -m app.db.crypto_tool rotate-messages --to-key-id key-2026-08
python -m app.db.crypto_tool rotate-uploads --to-key-id key-2026-08
python -m app.db.crypto_tool status
```

Production server processes deliberately cannot enable either plaintext flag.
For a one-time plaintext conversion, run only the CLI in an isolated,
non-listening maintenance container/process that mounts the same database and
upload volume, explicitly selects `ENVIRONMENT=local`, supplies the real key
ring, and enables only the required compatibility flag. Never start Uvicorn or
the worker with that maintenance environment. Return to `ENVIRONMENT=production`
and both flags `false` immediately after status reports no plaintext rows/files.

Change the active ID before rotation so new writes immediately use the target.
Remove an old key only after status reports no message/upload references and no
unknown, unreadable, missing, invalid, or metadata-mismatch state. Workers route
encrypted payloads opaquely. Every supplied Compose profile gives the worker
only database/broker/fanout settings, not JWT, legacy-Fernet, or data-at-rest
keys.

## Tests
Docker backend tests (verified):
```bash
docker compose run --rm backend sh -lc "cd /app && PYTHONPATH=/app pytest -q"
```

Local backend tests:
```bash
cd backend
python -m pytest -q
```
If local PostgreSQL is unreachable for `DATABASE_URL`, tests may be skipped.

## Frontend Checks
Supported scripts:
```bash
cd frontend
npm install
npm run typecheck
npm run build
```
Notes:
- `npm run lint` is not defined in this repo.
- Local Windows build may hit a Node dependency issue (`caniuse-lite/...`).
- Docker frontend build is verified and recommended for demo readiness.

## Demo Verification Script
```bash
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```
The script verifies register/login, channel creation, join, live WebSocket delivery when available, REST sync backfill, event log entries, and an unauthorized upload access check.
It now opens User B's WebSocket before joining, explicitly subscribes after the join, verifies event integrity for the fresh demo channel, and remains the strongest repo-level proof of the distributed publish/subscribe path currently available.

Event integrity checks:
```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app pytest tests/test_event_integrity.py -q"
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"
```
Canonical real backfill, when you intentionally want to initialize legacy events:
```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py"
```
Host execution (`python scripts/backfill_event_integrity.py --dry-run`) is optional and depends on local PostgreSQL credentials matching the Docker database.

Delivery reliability checks:
```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app pytest tests/test_delivery_reliability.py -q"
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/verify_delivery_reliability.py --base-url http://localhost:8000/v1"
docker compose exec postgres psql -U postgres -d channels -c "select status, count(*) from outbox group by status order by status;"
```
The verifier proves normal worker publish plus a controlled dead-letter/manual retry path; it does not claim full broker-outage CI coverage.

Approval-required membership verifier:
```bash
python scripts/verify_approval_flow.py --base-url http://localhost:8000/v1
```
This opens User B's WebSocket while pending, approves User B, verifies membership update or REST resync, then checks live delivery and REST backfill.

## Manual Demo Flow
1. User A register/login.
2. User B register/login.
3. User A creates channel.
4. User B joins/subscribes.
5. User A publishes a text message.
6. User A uses the paperclip composer button to publish a photo, video, or audio file, with or without caption text.
7. User B receives/reads the text and media messages.
8. Open the event log subpage from channel details.
9. Click Verify integrity and show the Audit integrity badge.
10. Open Delivery Monitor from the Profile page as a channel owner/admin.
11. Show unauthorized access denial on private channel.
12. Show private upload access is denied to a non-member.
13. Show ciphertext at rest:
```bash
docker compose exec postgres psql -U postgres -d channels -c "select id, left(content_text, 32), content_json from messages order by created_at desc limit 5;"
docker compose exec backend sh -lc "cd /app && python -m app.db.crypto_tool status"
```

## Final MVP Status
- Complete:
  - Authentication, authorization, membership management, channel CRUD, encrypted message storage, media attachments for photos/videos/audio, event logging, upload access checks, safe identifier validation, and backend regression tests.
- Mostly complete:
  - Distributed pub/sub delivery through PostgreSQL outbox, RabbitMQ, worker processing, Redis fanout, and WebSocket push. The live flow is exercised by the demo verifier and approval verifier, including join-after-connect and approval-after-connect WebSocket resubscribe paths, but there is still no broad CI suite around it.
  - Delivery reliability monitoring with retry scheduling, dead-letter status, admin APIs, frontend Delivery Monitor, and a controlled verifier for normal publish plus manual retry. Full broker-outage CI coverage remains future work.
  - Event audit integrity with a per-scope SHA-256 hash chain. This is tamper-evident, not external notarization; legacy rows need explicit backfill before they verify as initialized.
- Production-oriented browser boundary:
  - Browser access tokens are memory-only, refresh tokens are rotating HttpOnly cookies, refresh/logout use Origin plus double-submit CSRF validation, and WebSockets continue to use one-time opaque tickets. The legacy JSON token API remains available for non-browser clients.
- Future work:
  - Frontend automated browser smoke tests, richer operational observability, managed secret/KMS integration, HA/backups, and advanced features beyond the MVP.

## Final Submission Docs
- [Final MVP Status](docs/FINAL_MVP_STATUS.md)
- [Final Demo Checklist](docs/FINAL_DEMO_CHECKLIST.md)
- [Security](docs/SECURITY.md)
- [Testing](docs/TESTING.md)
- [Requirements Mapping](docs/REQUIREMENTS_MAPPING.md)
- [Repository Assessment](REPOSITORY_ASSESSMENT.md)

## Security Notes
- Password hashing enabled.
- JWT auth on protected routes.
- Membership/permission authorization checks.
- Message encryption v2 uses an explicit key ID plus domain-separated Fernet; historical configured keys remain readable during rotation.
- Private uploads require authentication and channel/ownership checks before download.
- New upload files contain only chunked AES-256-GCM authenticated ciphertext. Authorized downloads decrypt in bounded 64 KiB chunks while retaining the existing atomic per-user/per-client-IP/process-global lease; encrypted byte ranges are explicitly rejected.
- Message attachments support protected photo, video, and audio publishing through the existing upload API.
- Profile/channel avatar uploads and profile chat wallpaper uploads use validated image references and protected authenticated media loading.
- Upload storage paths are sanitized so raw filenames cannot escape the uploads directory.
- Unauthorized read/publish events logged.
- Sensitive abuse-prone endpoints remain locally bounded during a Redis rate-limit outage; ordinary paginated reads stay available.
- Message text/JSON, reaction values, REST sync arrays, and WebSocket subscribe/resume/sync arrays have explicit limits.
- REST `/sync` uses one global message-row budget: each channel query has `LIMIT remaining`, so Python message materialization never exceeds the requested page limit.
- Event logs include tamper-evident hash-chain metadata for new events.
- Do not commit real secrets.

## Documentation
- [Project Overview](docs/PROJECT_OVERVIEW.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Demo Guide](docs/DEMO_GUIDE.md)
- [Requirements Mapping](docs/REQUIREMENTS_MAPPING.md)
- [Testing](docs/TESTING.md)
