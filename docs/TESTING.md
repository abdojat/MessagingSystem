# Testing and Release Verification

Tests are organized around the supervisor-visible MVP flow and the security/reliability regressions accumulated during implementation. Historical per-phase counts remain in [`reports/security/`](../reports/security/README.md); this guide contains current commands only.

## Test prerequisites

- Docker and Docker Compose v2 for canonical/reproducible checks.
- Python 3.11+ with `backend/requirements.lock` installed for host backend tests.
- Node.js 22/npm for host frontend validation.
- A reachable PostgreSQL database for the complete backend suite; Phase 10 presence tests additionally use `PHASE10_TEST_REDIS_URL` for real Redis behavior.

The safest complete wrapper creates uniquely named disposable PostgreSQL/Redis containers:

```bash
python scripts/verify_release.py
```

## Backend full suite

Host environment:

```bash
cd backend
python -B -m pytest -q
```

Development Compose environment:

```bash
docker compose run --rm backend python -B -m pytest -q
```

Use that Compose command only with a disposable database. The backend fixtures
truncate application tables between cases, so the normal development database
must not contain data that needs to be retained. Prefer `verify_release.py` for
the safe complete check because it creates uniquely named temporary services.

The latest measured result is recorded in [Stabilization Status](STABILIZATION_STATUS.md) and [Final Repository Handoff](../FINAL_REPOSITORY_HANDOFF.md). An exact count is evidence, not a test assertion.

## Focused regression groups

Run from `backend/` with the same PostgreSQL/Redis environment as the full suite:

```bash
python -B -m pytest -q \
  tests/security/test_post_phase7_repairs.py \
  tests/security/test_phase8_production_hardening.py \
  tests/security/test_phase9_data_protection.py \
  tests/security/test_phase10_identity_presence.py \
  tests/security/test_phase11_merkle_integrity.py \
  tests/security/test_merkle_checkpointer.py
```

Important coverage groups:

| Concern | Test evidence |
|---|---|
| Registration, login, sessions, replay/revocation | `tests/security/test_phase2_auth_hardening.py`, `test_phase8_production_hardening.py` |
| Browser cookie/Origin/CSRF and WebSocket tickets | `tests/security/test_phase8_production_hardening.py` |
| Invite identity and concurrency | `tests/security/test_phase5_medium_hardening.py`, `test_phase6_medium_hardening.py`, `test_phase10_identity_presence.py` |
| Routing identifiers, uploads, read/write rate separation, download concurrency, and authorization repairs | `tests/test_p0_requirements.py`, `tests/security/test_phase6_medium_hardening.py`, `tests/security/test_post_phase7_repairs.py` |
| Retained-data attachment migration shapes | `tests/security/test_phase3_abuse_hardening.py::test_attachment_migration_backfill_skips_json_null_and_non_array_legacy_values` |
| Retained RabbitMQ user-queue topology migration | `tests/security/test_phase3_abuse_hardening.py::test_worker_migrates_only_legacy_unbounded_managed_user_queue`, `test_worker_does_not_delete_user_queue_for_unrecognized_topology_mismatch` |
| Outbox retry/dead-letter and broker projections | `tests/test_delivery_reliability.py`, Phase 3/4/7 regressions |
| Message/upload encryption, migration, and rotation | `tests/security/test_phase9_data_protection.py` |
| Distributed presence and email verification | `tests/security/test_phase10_identity_presence.py` |
| Event hash chains | `tests/test_event_integrity.py` |
| Merkle roots, proofs, signatures, chain, tamper, anchors, concurrency, API | `tests/security/test_phase11_merkle_integrity.py` |
| Automatic checkpoint scheduling/configuration, bounded drain, transient retry, shutdown, CLI compatibility, pending UI projection | `tests/security/test_merkle_checkpointer.py` |

## Frontend validation

The repository has no lint script and no automated browser suite. The supported reproducible checks are:

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

`scripts/verify_release.py` also parses the English and Arabic catalogs and verifies identical key/placeholder sets.

## Worker and Python validation

There is no separate worker test suite. Worker behavior is covered through backend/reliability tests and live verifier scenarios. Validate syntax and the canonical image:

```bash
python -B -m compileall -q backend/app backend/alembic scripts worker/worker_app
docker build -f worker/Dockerfile .
```

The canonical backend image is built by the release verifier and can be built directly with:

```bash
docker build -f backend/Dockerfile .
```

## Safe release verifier

```bash
python scripts/verify_release.py
```

It performs:

- canonical backend image build;
- disposable PostgreSQL/Redis startup;
- complete backend test suite;
- Alembic single-head check;
- frontend typecheck and production build;
- English/Arabic locale key and placeholder parity;
- development and hardened Compose renders;
- containerized hardened Nginx syntax validation.

It does not touch application volumes. Production Compose rendering is optional and uses an operator-supplied environment only for configuration interpolation:

```bash
python scripts/verify_release.py --production-env-file .env.production
```

Options `--skip-backend` and `--skip-frontend-build` are convenience flags for partial local iteration, not final acceptance.

## Data-creating application verifiers

Start an intended disposable application stack before running these commands.

Main supervisor publish/subscribe path:

```bash
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```

It verifies registration/login, channel creation/join, join-after-connect subscription, live WebSocket delivery when available, REST sync recovery, event integrity, and outsider denial for private upload access.

Approval-required join path:

```bash
python scripts/verify_approval_flow.py --base-url http://localhost:8000/v1
```

Delivery state path from inside the backend container:

```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/verify_delivery_reliability.py --base-url http://localhost:8000/v1"
```

Comprehensive release-candidate scenario:

```bash
python scripts/verify_release_candidate.py --base-url http://localhost:8000/v1
```

This script creates users, channels, messages, uploads, sessions, and audit evidence. Run it only against disposable data. Optional `--secondary-base-url`, `--mailpit-url`, and `--uploads-base-dir` enable cross-backend presence, captured SMTP, and direct encrypted-upload inspection when those fixtures exist.

## Merkle demonstration

For the automatic service, configure a short non-production interval if desired
(minimum 10 seconds), generate several audit events, and watch:

```bash
docker compose logs -f merkle-checkpointer
python -m app.db.merkle_tool status
```

The expected transition is `pending checkpoint > 0`, followed by one or more
bounded checkpoint creation logs and `pending checkpoint: 0`. The Superadmin
table changes the affected rows from **Pending checkpoint** to **Verify Merkle
proof** without per-row proof requests.

The script requires a reachable PostgreSQL database and an explicit matching Ed25519 signing/private-key environment:

```bash
python scripts/demo_merkle_integrity.py
```

The recommended isolated Compose invocation is in [Deployment](DEPLOYMENT.md#merkle-supervisor-demo). Expected labels are:

```text
Event hash:              PASS
Merkle inclusion:        PASS
Checkpoint hash:         PASS
Ed25519 signature:       PASS
Checkpoint chain:        PASS
Tampered proof:           FAILED (expected)
```

The script creates dedicated demo events and modifies only an in-memory proof copy for the failure check.

## Compose, Nginx, and migrations

```bash
docker compose config --quiet
docker compose -f docker-compose.hardened.yml config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
```

Containerized hardened Nginx syntax is part of `verify_release.py`. Production Nginx syntax also requires the fully rendered environment and readable TLS mounts.

Migration acceptance requires:

```bash
cd backend
python -m alembic heads
python -m alembic current
python -m alembic upgrade head
```

Final verification uses an empty disposable PostgreSQL database and confirms the one head `0024_phase11_merkle_audit`. The Phase 3 attachment backfill regression also executes the exact migration SQL and verifies that JSON `null` and non-array legacy values are skipped while valid attachment arrays are normalized. A retained development database at revision `0016_backfill_owner_memberships` was also verified upgrading through `0024_phase11_merkle_audit` without deleting its application data.

## Manual acceptance

The final manual proof should show:

1. User A registers/logs in and creates a private channel.
2. User B joins/is approved and receives User A's message live.
3. The same message remains available after refresh/offline sync.
4. User C cannot read the private channel or attachment.
5. Event/activity records exist and the channel hash chain verifies.
6. PostgreSQL/upload storage contains ciphertext while authorized API download returns original data.
7. A pending hashed event automatically becomes a signed Merkle checkpoint; its inclusion proof verifies and a tampered proof copy fails.

Use [Demo Guide](DEMO_GUIDE.md) and [Final Demo Checklist](FINAL_DEMO_CHECKLIST.md).

## Remaining testing limitations

- No automated real-browser end-to-end suite or visual RTL regression suite.
- No sustained load, slow-reader, or multi-worker outage certification.
- External SMTP provider delivery/bounce behavior is not automated; local capture and configuration checks cover the application boundary.
- RabbitMQ/Redis failures have deterministic regression coverage, but a complete live outage matrix is not a routine CI job.
