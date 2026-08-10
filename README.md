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
- Reliability: PostgreSQL outbox status tracking, worker retry/backoff, RabbitMQ DLQ, admin Delivery Monitor
- Abuse resistance: atomic Redis/local-fallback rate limits, WebSocket frame/command/history budgets, message/protocol bounds, account quotas, bounded RabbitMQ user queues, and paced Redis fanout retries
- Integrity: tamper-evident event audit hash chain, verification API, backfill script, frontend Event Log badge/check
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
# set MESSAGE_ENCRYPTION_KEY in .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

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
- `MESSAGE_ENCRYPTION_ENABLED=true`
- `MESSAGE_ENCRYPTION_KEY` (Fernet key)
- `UPLOAD_MAX_SIZE_BYTES` (defaults to 25 MiB; upload bodies are streamed and bounded by this value)
- `API_REQUEST_BODY_MAX_BYTES` (defaults to 128 KiB for ordinary `POST`/`PUT`/`PATCH`/`DELETE` bodies; the protected upload-content `PUT` keeps its separate streaming limit)
- `MESSAGE_TEXT_MAX_BYTES`, `MESSAGE_JSON_MAX_BYTES`, `MESSAGE_JSON_MAX_DEPTH` (validated before encryption/outbox work)
- `RATE_LIMIT_*` grouped auth/search/message/media/channel/WebSocket/sync/admin limits; `RATE_LIMIT_LOCAL_MAX_KEYS` bounds the fail-closed per-process sensitive fallback used when Redis is unavailable
- `MAX_CHANNELS_OWNED_PER_USER`, `MAX_ACTIVE_INVITES_PER_USER`, `MAX_UPLOADS_PER_USER_PER_DAY`, `MAX_PENDING_UPLOADS_PER_USER`, `MAX_STORED_UPLOAD_BYTES_PER_USER`, and `MAX_WEBSOCKET_CONNECTIONS_PER_USER`
- `MAX_CONCURRENT_DOWNLOADS_PER_USER` (3), `MAX_CONCURRENT_DOWNLOADS_PER_IP` (12), and `MAX_CONCURRENT_DOWNLOADS_GLOBAL` (100) atomically bound protected streams in each backend process
- `TRUSTED_PROXY_CIDRS` is empty in direct mode; set it only to explicit proxy peers that overwrite `X-Forwarded-For` (the hardened Compose file supplies its fixed proxy `/32`)
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
- In `dev`, `development`, `local`, and `test`, an empty `MESSAGE_ENCRYPTION_KEY` uses a fallback key.
- Every other environment label, including unknown deployment aliases, is production-like: startup rejects missing/default/weak JWT secrets and a missing or invalid Fernet key while message encryption is enabled.
- Access JWTs are bound to their database session. Logout, explicit revocation, logout-all, replay detection, absolute expiry, and account deactivation invalidate later HTTP authentication immediately.
- WebSocket clients obtain a short-lived, one-time opaque ticket with `POST /auth/ws-ticket`; long-lived access JWTs are not accepted in WebSocket URLs. Redis control events close matching sockets across backend instances when Redis is available.
- Established sockets use per-socket weighted command and history-row token buckets. Subscribe/resume history is capped globally per command, identical subscribe/cursor requests do not refetch history, and inbound dispatch remains one command at a time. These budgets are per backend process/socket, not a distributed global quota.
- Generic invite links are reusable until revoked, expired, or their channel is deleted. Targeted invites are one-use and accept/revoke/delete ordering is serialized through PostgreSQL row locks. Existing-account email targets resolve once to immutable `user_id`; unresolved pre-registration email targets require verified ownership of the normalized email. Changing an account email clears verification. The repository intentionally does not implement email delivery/verification issuance, so a deployment must supply that trusted completion flow before unresolved email invites can be accepted.
- Membership topology is stored as versioned desired state in PostgreSQL and snapshotted through the outbox. The worker locks the user/channel state, rejects stale generations, re-derives current authorization, removes obsolete slug bindings, and retries a complete idempotent projection. Run `python -m app.db.reconcile_broker_bindings` in the backend environment to enqueue a full repair from PostgreSQL.
- Security-sensitive database writes follow the documented global lock order in [`backend/docs/LOCK_ORDERING.md`](backend/docs/LOCK_ORDERING.md). Worker retry/dead-letter state commits before its best-effort diagnostic event transaction, avoiding the historical binding-row/event-advisory inversion.
- RabbitMQ user queues are bounded realtime buffers (expiry, message TTL, maximum length). Missed or evicted events are recovered through PostgreSQL-backed REST sync.
- Generate one with:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

To create the initial superadmin, set `SUPERADMIN_USERNAME` and a unique 12+ character `SUPERADMIN_PASSWORD` in the untracked `.env` before startup. `SUPERADMIN_EMAIL` is optional. Startup creates the account once and never resets its password or auto-promotes an existing normal account. After login, open `/app/admin` or use the shield link in the sidebar. Remove the bootstrap password from `.env` after the account has been created if automatic recreation is not needed.

## Migrations
```bash
docker compose run --rm backend sh -lc "alembic upgrade head"
```

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
docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"
```

## Final MVP Status
- Complete:
  - Authentication, authorization, membership management, channel CRUD, encrypted message storage, media attachments for photos/videos/audio, event logging, upload access checks, safe identifier validation, and backend regression tests.
- Mostly complete:
  - Distributed pub/sub delivery through PostgreSQL outbox, RabbitMQ, worker processing, Redis fanout, and WebSocket push. The live flow is exercised by the demo verifier and approval verifier, including join-after-connect and approval-after-connect WebSocket resubscribe paths, but there is still no broad CI suite around it.
  - Delivery reliability monitoring with retry scheduling, dead-letter status, admin APIs, frontend Delivery Monitor, and a controlled verifier for normal publish plus manual retry. Full broker-outage CI coverage remains future work.
  - Event audit integrity with a per-scope SHA-256 hash chain. This is tamper-evident, not external notarization; legacy rows need explicit backfill before they verify as initialized.
- Demo-grade:
  - Frontend token handling. Access tokens are kept in a JavaScript-managed cookie and refresh tokens are kept in `localStorage`, which is acceptable for a university demo but not production-grade session security.
- Future work:
  - Frontend automated smoke tests, richer operational observability, a cleaner production session strategy, and any advanced features beyond the MVP.

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
- Message encryption at rest (Fernet).
- Private uploads require authentication and channel/ownership checks before download.
- Protected downloads use chunked `FileResponse` streaming and one atomic per-user/per-client-IP/process-global lease. `docker-compose.hardened.yml` adds Nginx connection, body/header, buffering, and inactivity bounds; application counters remain per backend replica and stock Nginx does not guarantee a minimum downstream throughput.
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
