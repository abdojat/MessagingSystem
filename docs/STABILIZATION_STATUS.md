# Stabilization Status

Last updated: 2026-06-16

## Summary

This status file now includes the 2026-06-16 media publishing pass. The latest pass adds protected photo/video/audio message attachments, attachment-only publish support, authenticated frontend playback, and regression tests while preserving private upload controls.

## Media Publishing Pass - 2026-06-16

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Attachment-only media publish | Passed | `backend/app/schemas/messages.py` allows attachments as message content; `backend/app/services/message_service.py` stores attachment-only messages as text-type messages with no text body; covered by `test_media_attachments_can_be_published_without_text_and_synced` | Existing `content_type` enum still has `text/json`; media type is carried by attachment metadata, not by the message content type | Keep this explanation in demo/report notes if asked why the message row says `text` |
| Stored-upload requirement | Passed | `MessageService._normalize_attachments` rejects attachment references whose upload bytes have not been stored; covered by `test_publishing_attachment_requires_stored_upload_content` | Upload metadata can still exist without content if the user abandons an upload before publishing | Add cleanup for abandoned upload records only if needed |
| Frontend media composer/playback | Passed | `frontend/src/components/features/chat/pages/channel-view.tsx` supports paperclip selection for `image/*`, `video/*`, and `audio/*`, uploads through `/v1/uploads`, and renders protected image/video/audio media with authenticated requests; `npm run typecheck` passed | No browser e2e test verifies actual media playback pixels/audio | Manually publish a small photo, video, and audio clip during final UI rehearsal |
| Focused verification | Passed | `python -m pytest backend\tests\test_p0_requirements.py -q` -> `31 passed, 10 skipped`; `cd frontend && npm run typecheck` passed; `docker compose up -d --build` completed; `GET /health` returned database/Redis/RabbitMQ OK; frontend returned HTTP 200 | Local backend test skips depend on database availability; no browser e2e test has clicked through media playback | Run the manual UI media step in the already-started stack before supervisor review |

## Avatar/Image Audit - 2026-06-15

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Avatar URL validation | Passed | `backend/app/core/identifiers.py`, `backend/app/schemas/users.py`, and `backend/app/schemas/channels.py` reject unsafe schemes and malformed protected upload paths; covered by `test_avatar_url_validation_rejects_unsafe_values` and `test_avatar_url_validation_accepts_safe_values` | Existing legacy database rows are not automatically rewritten by this validation | If legacy unsafe avatar rows exist, clean them with an explicit migration/script before final demo |
| Avatar upload authorization | Passed | `backend/app/services/message_service.py` validates owned, stored, non-SVG image uploads before profile/channel avatar updates; `can_access_upload` now recognizes profile avatars, public channel avatars, and private channel avatars with membership checks | External `http(s)` avatar URLs are allowed and depend on the external host staying available | Prefer uploaded avatars for the supervisor demo |
| Authenticated frontend image rendering | Passed | `frontend/src/components/shared/AuthenticatedImage.tsx`, `frontend/src/components/ui/avatar.tsx`, sidebar, channel view, channel details, and profile preview path; frontend typecheck passed | No browser e2e test verifies actual rendered pixels | Manually check profile avatar, channel avatar, sidebar avatar, and message sender avatar during demo |
| Regression tests | Passed | `python -m pytest -q` -> `31 passed, 20 skipped`; focused P0 run -> `31 passed, 8 skipped` | PostgreSQL-dependent tests still skip if the configured test database is unreachable | Use Docker-backed tests for final verification if local DB credentials are inconsistent |
| Upload audit event | Passed | Unauthorized upload download attempts now log `security.unauthorized_upload_access`; covered by `test_upload_download_requires_channel_membership` | Event logging is best-effort and depends on database availability | Keep event-log evidence visible in demo guide/status notes |

## Stabilization Pass 2 — Approval Flow, Backfill, Delivery Reliability

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Event-integrity backfill command | Docker canonical path passed; host path fails clearly | `docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"` -> latest run: `scopes: 5`, `events_seen: 16`, `events_updated: 0`, `existing_kept: 16`, `conflicts: 0`; host `python scripts/backfill_event_integrity.py --dry-run` failed with `InvalidPasswordError` and printed the Docker fallback | Host PostgreSQL credentials may differ from the Docker database | Use Docker `exec backend` dry-run for final demo; run real backfill only when intentionally initializing legacy rows |
| Approval-required membership after WebSocket connect | Passed | `python scripts/verify_approval_flow.py --base-url http://localhost:8000/v1` verified pending join, WebSocket open while pending with an existing subscription, approval membership update, explicit subscribe/resync, live delivery, REST backfill, event log, and outsider denial | No browser e2e test for the approval UI | Keep the script in the golden demo path; add Playwright only if time remains |
| Delivery reliability proof | Passed with scoped proof | `docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/verify_delivery_reliability.py --base-url http://localhost:8000/v1"` verified worker-published outbox count, controlled dead-letter listing, manual retry reset to pending, and outsider authorization denial | Still no full broker-outage CI; controlled row is not a real RabbitMQ outage | Keep wording honest; add a broker-outage runbook or CI job later |
| Golden demo path | Updated and runnable | `docs/DEMO_GUIDE.md` now has a Golden Demo Path; `README.md` links to it; stack rebuilt with scripts copied into backend image | Clean reset deletes local demo data if used | Keep destructive reset clearly labeled and run verifiers after backend tests |
| Ciphertext-at-rest proof | Passed | `docker compose exec postgres psql ... left(content_text, 12) ...` returned `gAAAA...` prefixes for recent messages | Query is a spot check, not a formal encryption audit | Use it as a supervisor demonstration, not a production security proof |

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

Package the final submission materials: final report, screenshots, and a short supervisor script that follows the Golden Demo Path exactly.
