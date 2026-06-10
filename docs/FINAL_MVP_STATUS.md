# Final MVP Status

## What Is Complete
- User authentication with password hashing, JWT access/refresh tokens, and session revocation.
- Channel/topic creation, listing, updates, joins, leaves, invites, approvals, role changes, and member removal.
- Publish/subscribe message persistence with PostgreSQL as the source of truth.
- Event logging for the key channel, membership, message, and security flows.
- Message encryption at rest on the server side.
- Private upload download protection with authentication and authorization checks.
- Safe identifier validation for usernames, channel slugs, and broker-facing routing identifiers.
- Docker Compose run path for PostgreSQL, RabbitMQ, Redis, backend, worker, and frontend.
- Backend P0 regression tests for the main security and demo-flow behavior.
- Verified during Delivery Reliability Upgrade v1: Docker-backed backend tests passed, frontend typecheck passed, Docker Compose config passed, and a temporary-database Alembic upgrade to head passed.
- Delivery reliability tracking for the outbox, including retry scheduling, dead-letter status, RabbitMQ DLQ topology, admin APIs, and a frontend Delivery Monitor.

## What Is Mostly Complete
- Distributed delivery through PostgreSQL outbox, RabbitMQ, worker dispatch, Redis fanout, and WebSocket push.
- REST sync/backfill for users who miss realtime delivery.
- The demo verifier exercises the live WebSocket path when it is available and otherwise still proves the message via REST backfill.
- Dead-letter mirroring to RabbitMQ is best-effort; PostgreSQL outbox status remains the source of truth.

## New Reliability Enhancement
- Outbox rows now track `pending`, `publishing`, `published`, `retry_scheduled`, `failed`, and `dead_lettered` states.
- The worker marks successful broker publishes as `published`.
- Failed broker publishes are retried with configurable exponential backoff and marked `dead_lettered` after max attempts.
- Channel owners/admins can inspect scoped delivery stats and failed/dead-lettered rows through `/v1/admin/delivery/*` and the frontend Delivery Monitor.
- Manual retry resets failed/dead-lettered rows to `pending` and logs `broker.manual_retry_requested`.

## Still Not Production-Certified
- The reliability layer improves observability and retry behavior, but it is still MVP-grade.
- The tests mock AMQP publish failures for deterministic status-transition coverage; a full CI broker-failure scenario is still future work.
- The DLQ mirror depends on RabbitMQ being available at the time of dead-letter handling.

## What Is Demo-Grade
- Browser-managed token storage and WebSocket token transport.
- This is acceptable for a university demo, but it is not production-grade session security.

## Future Work
- Dedicated broker/WebSocket integration tests in CI.
- Full RabbitMQ outage/DLQ integration tests in CI.
- Frontend automated smoke coverage.
- Stronger production session handling with httpOnly cookies and CSRF-aware flows.
- Optional operational dashboards or extra advanced features only if the supervisor explicitly wants them.

## Exact Verification Commands
```bash
git status --short
git ls-files | Select-String -Pattern '(^|/)\\.env$|\\.env$'
python -m pytest -q
cd frontend
npm run typecheck
cd ..
docker compose config
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```

If the stack is not already running, start it with:

```bash
docker compose up -d --build
```
