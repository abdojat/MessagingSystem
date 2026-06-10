# Stabilization Status

Last updated: 2026-06-10

## Summary

This pass focused on demo determinism for the distributed publish/subscribe path. The main code change fixes the join-after-WebSocket-connect edge case by making socket subscriptions refresh explicitly after membership changes and by keeping idle Redis pub/sub timeouts from closing healthy WebSockets.

## Areas Checked

| Area | Status | Evidence | Remaining risk | Next action |
| ---- | ------ | -------- | -------------- | ----------- |
| Repository/docs baseline | Checked | Reviewed README, architecture, demo, final checklist/status, requirements, security, testing docs, verifier script, backend tests, worker outbox code, WebSocket manager, and frontend WebSocket hook | Docs still depend on manual discipline during final demo | Keep this file updated after further stabilization |
| Docker Compose path | Passed | `docker compose config` passed; `docker compose up -d --build` rebuilt backend, worker, and frontend; `docker compose ps -a` showed backend/postgres/rabbitmq/redis healthy and worker/frontend running | Compose config output includes local `.env` values; do not paste secrets into reports | Keep `.env` local and rotate demo secrets before any public deployment |
| Backend tests | Passed | `docker compose run --rm backend sh -lc "cd /app && PYTHONPATH=/app pytest -q"` -> `37 passed, 2 warnings` | Tests do not run a real broker-outage CI scenario | Add one broker/WebSocket integration job later if time allows |
| Local backend tests | Passed with skips | `cd backend && python -m pytest -q` -> `20 passed, 17 skipped` because local DB-dependent tests are skipped outside the Docker DB path | Local result is weaker than Docker-backed result | Prefer Docker-backed backend tests for final demo readiness |
| Frontend checks | Passed | `cd frontend && npm run typecheck` passed; Docker frontend build completed during `docker compose up -d --build` | No frontend e2e smoke suite | Add a small Playwright smoke only if time remains |
| Demo verifier | Passed | `python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1` passed after fixes; verified join-after-connect subscribe/resync, live WebSocket delivery, REST backfill, event log, event integrity, and unauthorized upload denial | Scripted verifier is not a full CI replacement | Run it immediately before supervisor review |
| Event integrity dry-run | Passed through Docker network | `docker compose run --rm -v "${PWD}/scripts:/scripts:ro" backend sh -lc "cd /app && PYTHONPATH=/app python /scripts/backfill_event_integrity.py --dry-run"` -> `scopes: 2`, `events_seen: 6`, `events_updated: 0`, `existing_kept: 6`, `conflicts: 0` | Direct host command failed on this machine with PostgreSQL `InvalidPasswordError`; Docker-network command is reliable here | Use Docker-network dry-run for final demo if host DB auth is inconsistent |
| Join-after-connect edge case | Fixed and verified | `backend/app/realtime/ws_manager.py`, `frontend/src/hooks/use-websocket.tsx`, `frontend/src/hooks/use-channels.ts`, and upgraded verifier | Approval flows rely on targeted membership events plus frontend subscribe/resync; no browser e2e test yet | Add an approval-specific scripted check if supervisor asks |
| Delivery reliability docs | Checked | Existing docs correctly state PostgreSQL outbox is authoritative and RabbitMQ DLQ is operational evidence | Full broker-outage CI remains future work | Keep wording as MVP-grade reliability, not production certification |
| Security honesty | Checked | `docs/SECURITY.md` still documents JS-managed access cookie, localStorage refresh token, and WebSocket URL token as demo-grade; added socket membership refresh note | Session storage remains non-production | Do not claim production-grade session security |

## Commands Run

| Command | Result | Pass/fail | Notes |
| ------- | ------ | --------- | ----- |
| `docker compose config` | Compose rendered successfully | Pass | Output reviewed; secret values not repeated here |
| `docker compose up -d --build` | Stack rebuilt and started | Pass | Backend and dependency health gates passed; frontend production build passed |
| `docker compose ps -a` | Services listed | Pass | Backend/postgres/rabbitmq/redis healthy; worker and frontend running |
| `docker compose run --rm backend sh -lc "cd /app && PYTHONPATH=/app pytest -q"` | `37 passed, 2 warnings` | Pass | Final Docker-backed backend test run |
| `cd frontend && npm run typecheck` | TypeScript completed with no errors | Pass | Also covered by Docker frontend build |
| `python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1` | Demo verification passed | Pass | Final run verified live WebSocket and REST sync after join-after-connect |
| `python scripts/backfill_event_integrity.py --dry-run` | Failed with `InvalidPasswordError` on host-local PostgreSQL | Fail on this machine | Use Docker-network fallback below when host DB auth differs |
| `docker compose run --rm -v "${PWD}/scripts:/scripts:ro" backend sh -lc "cd /app && PYTHONPATH=/app python /scripts/backfill_event_integrity.py --dry-run"` | Dry-run completed with no conflicts | Pass | Reliable path against the Docker database |
| `python -m compileall backend\app\realtime\ws_manager.py scripts\verify_demo_flow.py scripts\backfill_event_integrity.py` | Compilation completed | Pass | Syntax sanity check for edited Python files |
| `git diff --check` | No whitespace errors | Pass | Only line-ending warnings from Git were shown |

## Files Changed

| File | Why changed |
| ---- | ----------- |
| `backend/app/realtime/ws_manager.py` | Ensures user queues are bound on socket connect, echoes subscribe request IDs in sync responses, and prevents idle Redis pub/sub timeouts from closing healthy WebSockets |
| `frontend/src/hooks/use-channels.ts` | Sends explicit WebSocket subscribe after successful join and refreshes channel/message caches |
| `frontend/src/hooks/use-websocket.tsx` | Handles membership updates for the current user by subscribing/unsubscribing and refreshing relevant caches |
| `frontend/src/types/api.ts` | Adds typed join and membership action response shapes used by hooks |
| `scripts/verify_demo_flow.py` | Verifies join-after-connect, subscribe acknowledgement, live WebSocket delivery, REST backfill, event log, event integrity, and upload denial with clearer PASS/FAIL output |
| `scripts/backfill_event_integrity.py` | Makes host-side demo runs translate the default Compose DB host to `127.0.0.1` when no explicit `DATABASE_URL` is set |
| `README.md` | Documents upgraded verifier coverage and Docker-network backfill fallback |
| `docs/DEMO_GUIDE.md` | Adds join-after-connect verifier note and event-integrity dry-run fallback |
| `docs/TESTING.md` | Updates verifier coverage and warns not to run DB-resetting backend tests concurrently with the live verifier |
| `docs/FINAL_MVP_STATUS.md` | Records this stabilization pass and updated verification scope |
| `docs/SECURITY.md` | Documents explicit WebSocket membership refresh while keeping token storage described as demo-grade |
| `docs/REQUIREMENTS_MAPPING.md` | Updates pub/sub evidence to mention the stronger verifier path |
| `docs/STABILIZATION_STATUS.md` | New progress report for supervisor review |

## Demo Readiness

Status: Mostly ready for supervisor demo.

The Docker path, backend tests, frontend typecheck/build, upgraded full-stack verifier, and Docker-network event-integrity dry-run passed in this environment. The demo remains MVP-grade, not production-ready.

## Remaining Risks

- Direct host execution of `python scripts/backfill_event_integrity.py --dry-run` failed on this machine with PostgreSQL password authentication; the Docker-network fallback passed and should be used for the final demo if the host has a conflicting PostgreSQL setup.
- Backend tests and the live demo verifier should not be run concurrently against the same Docker database because the tests reset state.
- There is still no full CI broker-outage/DLQ integration scenario.
- Frontend token storage remains demo-grade.
- There is no automated browser e2e test for approval-based membership refresh.

## Recommended Next Step

Run a second stabilization pass focused on one approval-required channel demo: User B opens WebSocket while pending, User A approves B, B receives the membership update, B subscribes/resyncs, then B receives User A's next message live.
