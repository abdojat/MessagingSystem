# Distributed Messaging System Based on Publish/Subscribe Model

University final-year project implementing a secure distributed channel messaging platform with FastAPI, PostgreSQL, RabbitMQ, Redis/WebSocket, worker processing, and Next.js frontend.

## Architecture Summary
- Backend API: FastAPI (`backend/`)
- Worker: outbox + broker fanout (`worker/`)
- Persistence: PostgreSQL
- Broker: RabbitMQ
- Realtime: Redis + WebSocket
- Frontend: Next.js (`frontend/`)
- Reliability: PostgreSQL outbox status tracking, worker retry/backoff, RabbitMQ DLQ, admin Delivery Monitor
- Integrity: tamper-evident event audit hash chain, verification API, backfill script, frontend Event Log badge/check

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

## Environment Variables
See `.env.example`.
Important:
- `DATABASE_URL`
- `RABBITMQ_URL`
- `REDIS_URL`
- `JWT_SECRET` (replace development default)
- `MESSAGE_ENCRYPTION_ENABLED=true`
- `MESSAGE_ENCRYPTION_KEY` (Fernet key)
- `OUTBOX_MAX_ATTEMPTS`
- `OUTBOX_INITIAL_RETRY_DELAY_SECONDS`
- `OUTBOX_RETRY_BACKOFF_MULTIPLIER`
- `OUTBOX_MAX_RETRY_DELAY_SECONDS`
- `NEXT_PUBLIC_API_BASE_URL`
- Keep `.env` local only; the repository tracks `.env.example` for documentation.

Development note:
- In `dev/test/local`, empty `MESSAGE_ENCRYPTION_KEY` uses a fallback key.
- For demo/prod-like runs, set a real key explicitly.
- Generate one with:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

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
5. User A publishes.
6. User B receives/reads.
7. Open the event log subpage from channel details.
8. Click Verify integrity and show the Audit integrity badge.
9. Open Delivery Monitor from the Profile page as a channel owner/admin.
10. Show unauthorized access denial on private channel.
11. Show private upload access is denied to a non-member.
12. Show ciphertext at rest:
```bash
docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"
```

## Final MVP Status
- Complete:
  - Authentication, authorization, membership management, channel CRUD, encrypted message storage, event logging, upload access checks, safe identifier validation, and backend regression tests.
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
- Upload storage paths are sanitized so raw filenames cannot escape the uploads directory.
- Unauthorized read/publish events logged.
- Event logs include tamper-evident hash-chain metadata for new events.
- Do not commit real secrets.

## Documentation
- [Project Overview](docs/PROJECT_OVERVIEW.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Demo Guide](docs/DEMO_GUIDE.md)
- [Requirements Mapping](docs/REQUIREMENTS_MAPPING.md)
- [Testing](docs/TESTING.md)
