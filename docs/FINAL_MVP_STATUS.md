# Final MVP Status

## What Is Complete
- User authentication with password hashing, JWT access/refresh tokens, and session revocation.
- Channel/topic creation, listing, updates, joins, leaves, invites, approvals, role changes, and member removal.
- Publish/subscribe message persistence with PostgreSQL as the source of truth.
- Event logging for the key channel, membership, message, and security flows.
- Tamper-evident audit log integrity for new events through a per-scope SHA-256 hash chain.
- Message encryption at rest on the server side.
- Private upload download protection with authentication and authorization checks.
- Safe identifier validation for usernames, channel slugs, and broker-facing routing identifiers.
- Docker Compose run path for PostgreSQL, RabbitMQ, Redis, backend, worker, and frontend.
- Backend P0 regression tests for the main security and demo-flow behavior.
- Verified during Delivery Reliability Upgrade v1: Docker-backed backend tests passed, frontend typecheck passed, Docker Compose config passed, and a temporary-database Alembic upgrade to head passed.
- Verified during Stabilization Pass on 2026-06-10: Docker Compose config passed, Docker stack rebuilt and was healthy, Docker-backed backend tests passed, frontend typecheck passed, Docker frontend build passed, upgraded demo verifier passed, and Docker-network event-integrity dry-run passed.
- Verified during Stabilization Pass 2 on 2026-06-10: Docker Compose config passed, Docker stack rebuilt and stayed healthy, Docker-backed backend tests passed (`37 passed, 2 warnings`), frontend typecheck passed, main demo verifier passed, approval-required membership verifier passed with live WebSocket delivery, Docker event-integrity dry-run passed, delivery reliability verifier passed, container compileall passed, and `git diff --check` reported no whitespace errors beyond line-ending notices.
- Delivery reliability tracking for the outbox, including retry scheduling, dead-letter status, RabbitMQ DLQ topology, admin APIs, and a frontend Delivery Monitor.
- Event integrity verification through `GET /v1/channels/{id}/events/integrity` and the frontend Event Log badge/check.

## What Is Mostly Complete
- Distributed delivery through PostgreSQL outbox, RabbitMQ, worker dispatch, Redis fanout, and WebSocket push.
- REST sync/backfill for users who miss realtime delivery.
- The demo verifier exercises the live WebSocket path, the join-after-connect subscribe/resync path, event-integrity verification, and REST backfill.
- The approval verifier exercises a private approval-required channel where User B opens a WebSocket while pending, receives the approval membership update, subscribes/resyncs, receives User A's next message live, and confirms REST backfill.
- Dead-letter mirroring to RabbitMQ is best-effort; PostgreSQL outbox status remains the source of truth.

## New Reliability Enhancement
- Outbox rows now track `pending`, `publishing`, `published`, `retry_scheduled`, `failed`, and `dead_lettered` states.
- The worker marks successful broker publishes as `published`.
- Failed broker publishes are retried with configurable exponential backoff and marked `dead_lettered` after max attempts.
- Channel owners/admins can inspect scoped delivery stats and failed/dead-lettered rows through `/v1/admin/delivery/*` and the frontend Delivery Monitor.
- Manual retry resets failed/dead-lettered rows to `pending` and logs `broker.manual_retry_requested`.
- `scripts/verify_delivery_reliability.py` gives a reproducible supervisor proof of normal worker publishing plus controlled dead-letter listing and manual retry. It does not claim full broker-outage CI coverage.

## New Integrity Enhancement
- New audit events store `previous_hash`, `event_hash`, `hash_algorithm`, `integrity_version`, and `integrity_scope`.
- Channel event logs are chained per `channel:<channel_id>`; system events use a separate `system` chain.
- The frontend Event Log page can verify channel audit integrity and show Verified, Broken, Not initialized, or Checking.
- `scripts/backfill_event_integrity.py` can initialize legacy event rows explicitly.

## Still Not Production-Certified
- The reliability layer improves observability and retry behavior, but it is still MVP-grade.
- The tests mock AMQP publish failures for deterministic status-transition coverage; a full CI broker-failure scenario is still future work.
- The DLQ mirror depends on RabbitMQ being available at the time of dead-letter handling.
- Event integrity is tamper-evident but not externally notarized. A fully privileged database operator could recompute hashes after rewriting rows unless hashes are anchored outside PostgreSQL.
- Legacy rows need explicit backfill before the verifier can report them as initialized.

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
docker compose config
docker compose up -d --build
docker compose ps -a
docker compose run --rm backend sh -lc "cd /app && PYTHONPATH=/app pytest -q"
cd frontend
npm run typecheck
cd ..
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
python scripts/verify_approval_flow.py --base-url http://localhost:8000/v1
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/verify_delivery_reliability.py --base-url http://localhost:8000/v1"
```
Optional host backfill command, only when local PostgreSQL credentials match the Docker database:
```bash
python scripts/backfill_event_integrity.py --dry-run
```
