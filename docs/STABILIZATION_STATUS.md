# Stabilization Status

Last updated: 2026-08-11

## Summary

Security Hardening Phase 10 closes the deferred mailbox-verification and multi-socket presence gaps without changing the Phase 8/9 browser/session, encryption, broker-generation, membership, sync, or deployment boundaries. Provider-independent SMTP verification is bound to the exact authenticated user's current email, and Redis connection leases now make aggregate presence correct across tabs, sessions, backend processes, and crash expiry. External KMS/HSM custody, automatic key rotation scheduling, physical secure erasure, backup lifecycle, cross-host HA, and production load/browser automation remain deferred.

## Security Hardening Phase 10 - 2026-08-11

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| P10-01 mailbox verification | Confirmed and fixed | Migration `0023`; hash-only one-use challenges; exact email snapshot; authenticated request/confirm; user/challenge row locks; email-change revocation; capture/console + threaded generic SMTP; TLS/HTTPS production validation; profile controls and fragment page; real invite-unlock regression | Delivery depends on operator SMTP/provider availability; no provider bounce webhook or recovery/MFA system | Configure a real TLS SMTP provider and HTTPS public URL before production verification is enabled |
| P10-02 distributed presence | Confirmed and fixed | Random per-socket IDs; per-user Redis ZSET leases; global due index; atomic Lua connect/heartbeat/disconnect/reap; worker-facing online set compatibility; bounded heartbeat and duplicate-safe reaper; multi-instance/live Redis regressions | Presence can be temporarily stale/unknown during Redis outage; it intentionally has no authorization role | Monitor Redis and keep lease/refresh/reaper values proportional to deployment latency |
| Validation | Full automated and live regression passed | Phase 10 `25 passed, 1 warning`; requested Phase 2/5/6/8/9/post-repair group with Phase 10 `150 passed, 1 warning`; complete backend `312 passed, 1 warning`; fresh `->0023`; representative `0022->0023`; frontend typecheck/build; 825-key locale alignment; all three Compose renders; local SMTP sink delivery; isolated hardened full broker/WebSocket demo; authorized encrypted download/ciphertext/logout check; Nginx syntax | Existing dependency and Next.js deprecation notices; SMTP was not tested against an external provider/TLS mailbox; no browser automation or load certification | Preserve the focused suite and Phase 10 report as submission evidence; rehearse with deployment SMTP before production use |

## Security Hardening Phase 9 - 2026-08-11

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| P9-01 message key rotation | Fixed and regression-tested | Bounded 32-key ring, explicit active ID, HKDF message domain, strict text/JSON v2 envelopes, historical-key reads, status/migration/rotation commands, and key-removal proof | Keys remain environment-injected; operator rotation is manual | Run status before/after every deployment rotation and remove old keys only at zero references/errors |
| P9-02 plaintext fallback | Fixed fail-closed for production | Legacy-v1 has a dedicated deprecated key; plaintext reads require explicit compatibility; production rejects the compatibility flag; unknown/tampered envelopes fail | Intentional migration windows temporarily permit known historical plaintext | Keep windows short, migrate in bounded batches, verify zero plaintext, then disable flags |
| P9-03 upload plaintext storage | Fixed for new writes and migratable history | AES-256-GCM 64 KiB frames, authenticated header/AAD, encrypted-only temp/final paths, logical checksum/size semantics, authorized bounded decrypt response, 416 encrypted Range policy | Backend can decrypt; no secure-erasure guarantee for media/backups | Encrypt volumes/backups and apply retention/lifecycle policy |
| P9-04 operations/schema | Implemented | Migration 0022 metadata/constraint/index; `crypto_tool` status/migrate/rotate; idempotent batches; file-replaced/DB-version-0 repair; production worker receives no data keys | No external KMS or automatic scheduler | Integrate an external KMS only in a future deployment phase if required |
| Validation | Passed full automated and live checks | Phase 9 `35 passed`; prior Phase 1/4/6/7/8 subset `95 passed`; complete backend `287 passed, 1 warning`; frontend typecheck/build; all three Compose renders; fresh `->0022`; representative `0021->0022`; live production-profile pub/sub demo; plaintext-marker absence; exact download; 416 Range; idempotent migrations; worker key isolation | Existing passlib/argon2 and Next.js middleware-name deprecation notices; no KMS/HA/load/browser automation | Preserve the verifier and focused storage/key-removal regressions in final submission evidence |

## Security Hardening Phase 8 - 2026-08-11

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Browser session boundary | Fixed and regression-tested | New browser login/refresh/logout/CSRF routes use rotating `HttpOnly`, `Secure`, `SameSite` refresh cookies, readable CSRF cookies, exact-Origin checks, double-submit validation, and existing refresh-family replay/revocation logic; the frontend keeps access tokens in memory only | No automated browser end-to-end suite; access tokens remain readable to running JavaScript by design | Add a Playwright smoke test if CI scope permits |
| Production configuration | Fixed fail-safe | Production rejects wildcard/non-HTTPS CORS, wildcard/empty trusted hosts, explicitly insecure auth cookies, weak secrets, and plain-HTTP external profile media; API docs are disabled by default | Certificate issuance/renewal and secret rotation are operator responsibilities | Use a real DNS name, trusted certificate, and secret manager for public deployment |
| Production deployment boundary | Implemented and live-validated for a single host | `docker-compose.production.yml` separates migrations from Uvicorn, uses admin/runtime database roles, authenticated RabbitMQ/Redis, internal networks, TLS Nginx, non-root/read-only app containers, dropped capabilities, and no direct infrastructure host bindings | Not a multi-host HA/Kubernetes design; proxy CSP retains framework-required inline script/style allowances | Keep this profile distinct from the explicitly development/demo Compose files |
| Live validation | Passed | Phase 8 `13 passed`; Phase 1-8 plus post-Phase-7 `128 passed, 1 warning`; complete backend `252 passed, 1 warning`; frontend typecheck/build; all Compose renders; production image builds; TLS redirect/headers/host/docs/health checks; default credential rejection; least-privilege database denial; full broker/Redis/WebSocket verifier | Self-signed disposable TLS was used; no public CA trust, browser automation, broker-outage, or load certification | Repeat with deployment-owned secrets and a trusted certificate before Internet exposure |

## Post-Phase-7 Targeted Security Repair - 2026-08-11

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Proxied WebSocket client-IP isolation (R7-01) | Confirmed and fixed | `_run_websocket()` uses the shared `HTTPConnection` resolver; direct/untrusted/trusted/malformed cases, distinct proxy-client keys, and bucket isolation are covered in `test_post_phase7_repairs.py` | Redis-outage fallback and per-socket quotas remain per backend process; no live multi-client proxy flood was run | Keep the fixed Nginx `/32` and sanitized single forwarding header aligned with `TRUSTED_PROXY_CIDRS` |
| Explicit environment requirement (R7-02) | Confirmed and fixed | `Settings.environment` has no default; missing/empty fail; explicit dev/test labels work; unknown labels remain strict; missing environment cannot reach the deterministic development data-key fallback | Phase 9 supplies rotation tooling, but external KMS custody remains outside scope | Keep `ENVIRONMENT` explicit in every local/deployment environment and retain `.env.example` guidance |
| Validation | Passed | Focused repair `21 passed`; Phase 6–7 `42 passed, 1 warning`; complete backend `239 passed, 1 warning`; frontend typecheck; direct/hardened Compose render; `git diff --check` | Existing passlib/argon2 warning; deterministic component tests are not a live proxy/load certification | Run the normal supervisor demo; treat production hardening as a separate phase |

## Security Hardening Phase 7 - 2026-08-10

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Database/advisory lock order (P5V-03) | Fixed for reviewed application/worker paths | Global order documented; channel/dependent/topology/event paths normalized; worker commits status before separate diagnostic event; real PostgreSQL historical-cycle and channel/member tests pass | Unrelated PostgreSQL contention remains possible; no live RabbitMQ outage or broad stress test | Monitor SQLSTATE `40P01`/`40001` and add live broker/load coverage before scaled deployment |
| Auth/raw body bounds (P5V-04) | Fixed at schema and ASGI boundaries | 255-character identity, 256-character password, 2 KiB token, 128 KiB ordinary body; digest limiter keys; bounded audit prefix/hash; upload `PUT` stays streamed | Proxy/application configuration must remain aligned; per-process rate fallback remains | Keep limits documented and add ingress observability in the production phase |
| Attachment relation integrity (AV-09) | Fixed and PostgreSQL-enforced | Migration 0021 normalizes historical rows and adds composite FK to authoritative `(message_id, channel_id)`; active/outsider/deleted-channel tests pass | Downgrade retains normalized historical values; attachments remain server-readable/unencrypted | Preserve the composite invariant in future schema changes |
| Unknown environments (AV-10) | Fixed fail-safe | Only dev/development/local/test are development-like; production/staging/live/release/prod-eu/foo placeholder tests fail | AV-11 secret delivery/KMS/rotation is not implemented | Complete deployment secret management in the production phase |
| Validation | Passed | Phase 7 `23 passed`; Phase 1–6 security `117 passed`; complete backend `218 passed, 1 warning`; fresh/upgrade migrations; frontend typecheck; direct/hardened Compose render | Existing passlib/argon2 warning; Rabbit failure is mocked and concurrency uses PostgreSQL without live Rabbit | Run the live demo and a controlled Rabbit outage before deployment claims |

## Security Hardening Phase 6 - 2026-08-10

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Email-targeted invite identity (P5V-01) | Fixed and completed by Phase 10 mailbox proof | Existing addresses resolve to authoritative `invited_user_id`; unresolved addresses require exact normalized email plus `email_verified_at`; migration 0020 retains identity semantics; migration 0023 and authenticated hash-only challenges provide genuine proof; email change revokes proof/tokens; denial-before and acceptance-after verification pass | SMTP availability remains operational; existing-user and generic invitations intentionally do not require verification | Keep production SMTP/TLS health visible and preserve exact email-snapshot checks |
| Aggregate protected downloads (P5V-02) | Fixed per backend process with proxy-bounded recommended path | One atomic user/IP/global limiter; bounded active-key state; idempotent normal/cancel/send/stat/constructor cleanup; DB session closes before stream; trusted-proxy `/32`; Nginx body/header/connection/buffering/inactivity controls; only proxy port published in hardened Compose | Application/global counters are per replica; Nginx `send_timeout` is inactivity-only; no live many-account slow-reader load run | Add coordinated ingress/distributed accounting and controlled TCP/load testing before any scaled deployment claim |
| Migration | Passed | Fresh upgrade to `0020`; 0019 upgrade preserved user-ID/generic invites, bound an existing email owner, left future email unresolved, and kept every historical email unverified | Case/whitespace-insensitive duplicate historical users make the migration fail for manual resolution rather than choosing an owner | Audit/resolve any such duplicates before upgrading an unusual legacy database |
| Validation | Passed | Phase 6 `19 passed`; Phase 1–5 security `98 passed`; complete backend `195 passed, 1 warning`; frontend typecheck; direct/hardened Compose render; containerized `nginx -t` | Existing passlib/argon2 warning; application tests are not live TCP/proxy load tests | Run the chosen Compose path and demo verifier before supervisor presentation |

## Security Hardening Phase 5 - 2026-08-10

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Established WebSocket abuse control (AV-04) | Fixed and deterministically verified | 16 KiB Uvicorn/application bound; weighted per-socket command bucket; total 100-row command cap; 300-row history bucket; duplicate-subscribe suppression; one dispatch lock; cleanup/isolation regressions | Budgets and five-socket quota are per backend process/socket; no live five-socket multi-backend load run | Add live load/metrics only if deployment scale requires it |
| Deleted-channel attachments (AV-05) | Fixed and PostgreSQL-verified | Channel-derived query now requires `Channel.deleted_at IS NULL`; tests cover owner/admin/member/pending/removed/outsider/superadmin, delete/restore, upload owner, route denial, and deleted message | Upload owner intentionally retains their own upload; AV-09 relation consistency remains separate and open | Preserve the explicit lifecycle; address AV-09 separately |
| Invite lifecycle (AV-06) | Fixed and two-session verified | Channel-then-invite row locks; targeted one-use; reusable generic links; accept/revoke winner tests; concurrent generic accepts; expiry/deletion/revoke denial; frontend wording synchronized | Channel-row serialization is intentionally conservative; no schema migration or separate invite-redemption table | Keep audit events as the generic redemption record for this MVP |
| Redis limiter failure architecture (AV-07) | Fixed and deterministically verified | One Lua `INCR`/TTL operation; bounded dict+expiry heap; no active eviction; new sensitive keys denied at saturation; churn/recovery/low-risk regressions | Fallback remains per process and live Redis outage/recovery was not induced | Add multi-instance outage/load testing and metrics later |
| Validation | Passed | Phase 5 `18 passed`; Phase 1–4 security `80 passed`; complete backend `176 passed, 1 warning` against disposable PostgreSQL 16 | Existing passlib/argon2 warning; Redis/WebSocket outage/load behavior is simulated | Run Docker config, frontend typecheck, diff checks, and live demo before supervisor presentation |

## Security Hardening Phase 4 - 2026-08-10

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Broker authorization ordering | Fixed and deterministically verified | `broker_binding_states` generation/desired state; worker row lock and current DB authorization check; old-bind/new-unbind and inverse tests; duplicate/crash retry tests | No live multi-worker RabbitMQ ordering run; exhausted current reconcile rows still require reconnect, manual retry, or the global repair command | Add a live Rabbit outage/order scenario in a later integration phase |
| WebSocket final delivery | Fixed with bounded cache | Channel `membership_generation` is copied to outbox events; newer/legacy events re-check PostgreSQL before decryption; missed-removal and active-member regressions pass | Matching/older queued events may use the cache for up to one second by default; Redis-loss test is simulated | Measure only if stricter zero-window treatment for pre-removal queued messages is required |
| REST sync work | Fixed and verified | Per-channel `LIMIT remaining`; 10,000-row/limit-100 test materializes 100; 100-channel/limit-500 test materializes 500; deterministic ordering/cursor/auth tests | Up to 100 bounded message queries and channel metadata queries remain possible | Consider one global SQL/keyset query only if measured latency requires it |
| Protected downloads | Fixed and verified | Starlette `FileResponse`; no `read_bytes`; multi-chunk body; authorization-before-stream; per-user lease; cancellation cleanup | Concurrency is per backend process; proxy bandwidth/IP/timeout policy is external | Add reverse-proxy limits in a production profile |
| Migration | Passed | Fresh upgrade through `0019`; upgrade from 0018 with active and removed historical pairs retained old/current keys and enqueued current reconciliation | Unknown legacy Rabbit bindings with no membership or historical outbox evidence cannot be enumerated through AMQP | Keep the documented one-time legacy queue recreate/reset procedure |
| Validation | Passed | Phase 4 `15 passed`; Phase 3 `19 passed`; Phase 1 `27 passed`; complete backend `158 passed, 1 warning`; fresh and Phase-3-to-Phase-4 migrations passed | Existing passlib/argon2 warning remains; frontend unchanged | Run the live Docker demo/verifiers before supervisor presentation |

## Security Hardening Phase 3 - 2026-08-10

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Rate limits and quotas | Fixed and verified | Grouped auth/search/message/media/channel/WebSocket/sync/admin policies; capped local Redis-outage fallback; channel/invite/upload/WebSocket quotas; focused threshold and boundary regressions | Emergency limiter and WebSocket count are per process without Redis/distributed coordination | Add metrics and distributed load testing only if deployment scale requires it |
| Payload/protocol amplification | Fixed and verified | 64 KiB text/JSON defaults, JSON depth 20, 100-entry REST/WS arrays, constrained reaction emoji/cardinality, idempotent seen/reaction events | HTTP server/proxy-wide body limit is still deployment-specific | Keep application validation and add reverse-proxy request limits in a production deployment |
| Query scaling | Fixed and verified | 25-message rendering uses two reaction queries plus one sender query; indexed `message_attachments` lookup replaces message-history JSON scanning; migration backfill validated with a historical row | Avatar URL reference lookup still uses bounded string matching and is separate from message attachment authorization | Normalize profile/channel media references later only if measured data volume justifies it |
| Broker consistency | Fixed with durable retry | Membership changes enqueue idempotent bind/unbind desired state in the existing outbox; simulated Rabbit failure leaves DB removal authoritative and command `retry_scheduled` | No live RabbitMQ outage/recovery integration run; exhausted binding commands still require operator retry/reconciliation | Add one live broker-outage test and a small reconciliation command in Phase 4 |
| Queue/Redis outage behavior | Fixed and unit verified | Queue expiry/TTL/max-length arguments match backend/worker; Redis fanout uses bounded exponential attempts plus delayed NACK/requeue | Existing legacy queues must be recreated once because RabbitMQ queue arguments are immutable; live outage behavior is not integration-tested | Reset/recreate demo queues before the next full-stack run and add broker metrics/alerts later |
| Validation | Passed | Fresh migration to `0018`; historical attachment backfill check; Phase 3 `19 passed`; full backend `143 passed`; one existing passlib/argon2 warning | Frontend was unchanged, and no real broker/Redis outage was simulated | Run the live demo/verifier after recreating legacy queues before supervisor presentation |

## Security Hardening Phase 2 - 2026-08-10

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| HTTP access/session binding | Fixed and verified | Access JWT `sid`; one-query user/session resolution; logout, explicit revoke, logout-all, nonexistent/legacy `sid`, idle expiry, absolute expiry, and Session A/B isolation regressions | Every protected request performs a database lookup; correctness is prioritized and the query is indexed, but a carefully invalidated cache may be useful at higher scale | Measure before adding cache complexity |
| Refresh replay and lifetime | Fixed and verified | Unique refresh `jti`, row-locked rotation, signed stale-token detection, family revocation, `security.refresh_replay_detected`, and migration `0017_auth_session_hardening` | Replay after the old JWT itself expires is rejected as expired rather than classified as replay | Retain current minimal family model unless OAuth-grade requirements emerge |
| WebSocket authentication | Fixed and verified | `POST /auth/ws-ticket`, cryptographically random 30-second default ticket, hashed Redis key, atomic `GETDEL`, access-JWT URL rejection, and socket authentication-expiry task | Redis is required to issue/consume tickets; at Phase 2 the browser session was JavaScript-managed, superseded by the Phase 8 cookie/CSRF flow | Retain one-time tickets and the Phase 8 browser-session boundary |
| Distributed revocation | Fixed with documented failure semantics | Local close plus minimal Redis `user_id`/`session_id`/reason event; listener on every backend; duplicate events are harmless; no token is published | If Redis is unavailable, a remote already-open socket can remain until captured auth expiry; database revocation still blocks later HTTP/refresh/ticket/reconnect | Add a two-backend integration test and Redis outage observability |
| Validation | Passed | Fresh migration plus existing-session backfill round trip; Phase 2 `19 passed`; relevant Phase 1/superadmin regressions `36 passed`; full backend `124 passed`; frontend typecheck and `git diff --check` passed | One existing passlib/argon2 deprecation warning; no browser e2e or real two-backend test | Add CI coverage only if schedule permits |

## Security Hardening Phase 1 - 2026-08-10

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| `/sync` membership privacy | Fixed and verified | `MessageService.sync` limits event backfill to approved current channels or events targeting the caller; regressions cover cross-channel denial, outsider denial, and removed-user notification | Event payload targeting remains an application convention that future membership event types must preserve | Keep new membership event payloads on `user_id` or `target_user_id` and extend the regression mapping when adding event types |
| Upload storage | Superseded and strengthened by Phase 9 | PUT retains bounded hash/size, cleanup, row lock, immutability, and atomic finalization while finalized paths now contain chunked authenticated ciphertext | Server-authorized decryption remains; storage/backups need lifecycle controls | Follow the Phase 9 migration/status procedure for historical files |
| Production secrets | Superseded and strengthened by Phases 8/9 | Production validates strong JWT plus bounded data key ring/active ID and forbids plaintext compatibility; `.env.production.example` contains placeholders/generation guidance | No external KMS/HSM or automatic scheduler | Use deployment-owned secrets and explicit Phase 9 rotation commands |
| WebSocket subscriptions | Fixed and verified | Empty subscription sets deny ordinary channel events and untargeted membership changes; self-targeted removal still arrives and drops local access | Full RabbitMQ -> Redis -> WebSocket integration is still script/manual coverage rather than CI | Add one real broker-path CI integration scenario |
| Pending-member RBAC | Fixed and verified | Pending users are denied seen state and private statistics; history, sync, and WebSocket resume/subscription remain approved-role-only | Public discovery metadata remains intentionally visible for public channels | Keep `can_read` as the source of truth for any new read-derived endpoint |
| Validation | Passed | Phase 1 file: `27 passed`; focused legacy upload/sync group: `29 passed`; full backend: `105 passed`; `docker compose config --quiet` and `git diff --check` passed | Ruff/mypy/pyright are not installed; one existing passlib/argon2 deprecation warning remains | Add a lightweight configured linter/type checker in CI if desired |

## Sidebar Channel Visibility Fix - 2026-08-04

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Owned/joined sidebar channels | Fixed and preserved through Phase 9 | An unreadable optional last preview is omitted while channel metadata remains visible. Phase 9 now selects historical v2 keys explicitly and the regression removes the referenced key to prove the graceful path. | Data remains unreadable after its final referenced key is removed, by design | Use status/rotation and remove historical keys only after zero references |

## Channel List Scope and Filter Pass - 2026-08-04

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Normal channel list filters | Passed with focused regression coverage | `backend/app/services/channel_service.py` now escapes LIKE wildcards, searches channel names plus safe slugs, keeps `discover` public-only, and makes `my` include membership rows plus channels owned through `owner_user_id`; `0016_backfill_owner_memberships.py` repairs existing owner rows; `test_list_channels_scope_visibility_and_search_filters` covers `my`, `discover`, visibility, `#slug`, `%`, and `_`, and `test_list_channels_treats_owner_user_id_as_owner_when_membership_row_is_missing` covers the legacy owner fallback | Route-level behavior was verified through service tests rather than a full HTTP client test | Add a small API route test only if channel query validation changes again |
| Frontend channel listing | Improved | `frontend/src/hooks/use-channels.ts` now sends `limit=200`, follows `next_cursor` pages, includes visibility in the query key/params, and keeps scope/search filters stable across fetched pages | The sidebar still has no dedicated visibility filter UI; the hook supports it for future callers | Add UI controls only if the demo needs explicit public/private filtering |

## Channel List Preview Authorization Pass - 2026-08-04

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Channel list/detail preview authorization | Passed with focused runtime proof | `backend/app/services/channel_service.py` now enriches last-message previews, seen markers, and unread counts only for approved readable memberships; public discovery keeps channel metadata and last-activity time without decrypted message bodies | Existing developer Postgres volumes may have credentials that differ from `.env.example`, so host-side default DB runs can still skip | Keep using a clean Docker-backed test database or the canonical backend test command before final submission |
| Regression coverage | Passed | Added `test_list_channels_scopes_pagination_and_preview_permissions` in `backend/tests/test_p0_requirements.py`; focused run against disposable Postgres on `localhost:55432` passed; `python -m compileall -q backend\app backend\tests` passed; default local P0 run reported `33 passed, 15 skipped` | Full backend suite was not rerun against the disposable database in this pass | Run the full Docker-backed backend suite before final submission |

## Superadmin Console Hardening Pass - 2026-06-19

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Authorization/cache boundary | Passed | Every console endpoint still uses `SuperadminDep`; denied access is audited; global list/overview responses set `no-store`/`no-cache` | Frontend role cookie remains a navigation hint only; privileged auth has no MFA | Keep explaining that the backend dependency—not the UI guard—is authoritative |
| Audit privacy | Passed | `AdminService._safe_event_details` allowlists display fields per event family; `/admin/events` returns `details` instead of raw `payload`; new `message.published` events omit content/ciphertext/attachment structures; regression tests cover both | Historical database rows still contain their original payloads for hash-chain integrity, though the console API no longer exposes them | Define a separately reviewed retention/redaction migration only if historical payload removal becomes required |
| Operator relevance | Passed | Exact/prefix/contains search ranking; escaped wildcard search; event category, user status, channel status/visibility filters; debounced UI queries | No date-range event filter | Add date range only if real event volume makes it useful |
| Safer controls and pagination | Passed | Confirmation dialogs for user/session/channel mutations; independent selectable 10/25/50/100-row pagination on all three tables | No browser automation for confirmation and page-size flows | Rehearse one action and each filter during the final manual demo |
| Verification | Passed | Disposable PostgreSQL 16 run: full backend `68 passed`; frontend typecheck and production build passed; locale JSON validation and `git diff --check` passed | No browser e2e click-through for filters, confirmations, or page-size changes; one dependency deprecation warning remains | Manually rehearse the console once before submission |

## Superadmin Administration Pass - 2026-06-19

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Identity/bootstrap | Passed | Migration `0015_superadmin_controls`, `SuperadminBootstrapService`, Docker startup bootstrap, and refusal to auto-promote existing normal users | Bootstrap secret still comes from environment variables; no MFA | Use a unique bootstrap password, create the account once, then remove the password from local `.env` |
| Global audit visibility | Passed | `GET /v1/admin/events`, enriched actor/channel context (including channel recovery for upload/message/outbox references), unique channel slug display, channel-to-view and actor-to-profile links, safe typed details, relevant backend search/category filters, selectable pagination, and cross-channel/system integration test | Uploads reused across multiple channels remain explicitly unscoped because one channel cannot be attributed safely; channel navigation still honors normal private-content authorization; no browser automation for link navigation | Add date range only if event volume makes it useful |
| User/channel controls | Passed | Account deactivate/reactivate, session revocation, local WebSocket termination, channel suspend/restore, confirmation dialogs, self/protected-superadmin guards, and administrative audit events; Phase 2 later added Redis cross-instance socket control | No MFA or external approval workflow; remote immediate close is best-effort when Redis is unavailable | Keep controls intentionally small for the university MVP |
| Privacy boundary | Passed | Superadmin administration does not bypass private message/upload reads; global audit API returns allowlisted display details instead of raw payloads | Original historical payloads remain inside PostgreSQL and database operators remain technically privileged | Explain the application-level API boundary honestly during defense |
| Verification | Passed | Dedicated Docker-network test database: `7 passed` focused; full backend: `66 passed`; frontend typecheck/build passed; fresh Alembic migration and bootstrap passed | No browser e2e click-through for the console | Manually rehearse one user deactivation and disposable-channel restore |

## Profile Wallpaper Upload Pass - 2026-06-17

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Backend persistence | Passed | `users.wallpaper_url` model/schema support and Alembic migration `0014_user_wallpaper_url`; `/me` returns and updates the field | Existing running databases need `alembic upgrade head` before the field is available | Use the canonical Docker startup or run Alembic before manual backend testing |
| Upload validation and access | Passed | `MessageService.validate_profile_image_upload_reference` requires owned, stored, non-SVG image uploads for wallpaper updates; `test_profile_wallpaper_upload_is_saved_to_current_user` verifies persistence and owner-only media access | External `http(s)` wallpaper URLs are still allowed by schema, but the UI uses backend uploads for the demo | Prefer uploaded wallpapers during supervisor demos |
| Frontend wallpaper picker | Passed | `frontend/src/components/features/chat/pages/channel-view.tsx` uploads custom wallpapers through `/v1/uploads`, saves `wallpaper_url` through `/me`, clears it when a built-in wallpaper is selected, and renders protected images through temporary object URLs | No browser e2e test clicks the upload control or checks rendered background pixels | Manually upload and remove one small wallpaper image during UI rehearsal |
| Focused verification | Passed | `python -m pytest tests\test_p0_requirements.py -q` -> `33 passed, 14 skipped`; `npm run typecheck` passed; locale key alignment passed; `docker compose up -d --build` rebuilt and started the stack; backend logs show Alembic applied `0014_user_wallpaper_url`; `git diff --check` reported only line-ending warnings | Local backend tests can skip when PostgreSQL is unavailable; no Docker-backed full verifier was rerun for this narrow UI preference change | Run Docker-backed tests and the main demo verifier before final submission |

## Media Publishing Pass - 2026-06-16

| Area | Status | Evidence | Remaining Risk | Next Action |
| ---- | ------ | -------- | -------------- | ----------- |
| Attachment-only media publish | Passed | `backend/app/schemas/messages.py` allows attachments as message content; `backend/app/services/message_service.py` stores attachment-only messages as text-type messages with no text body; covered by `test_media_attachments_can_be_published_without_text_and_synced` | Existing `content_type` enum still has `text/json`; media type is carried by attachment metadata, not by the message content type | Keep this explanation in demo/report notes if asked why the message row says `text` |
| Stored-upload requirement | Passed | `MessageService._normalize_attachments` rejects attachment references whose upload bytes have not been stored; covered by `test_publishing_attachment_requires_stored_upload_content` | Upload metadata can still exist without content if the user abandons an upload before publishing | Add cleanup for abandoned upload records only if needed |
| Attachment contract | Passed | `PublishMessageRequest` now accepts only `file_id` attachment references, rejects duplicate IDs, and rejects extra client-supplied metadata; covered by `test_publish_request_rejects_duplicate_attachment_references` and `test_publish_request_rejects_extra_attachment_metadata` | Existing messages keep their stored attachment metadata as JSON | Continue deriving attachment metadata from upload records only |
| Upload error handling and audit events | Passed | Upload creation/content storage/access are logged; size/checksum store failures log `upload.store_failed` and keep `public_url` unset; covered by focused P0 upload tests | Abandoned upload metadata can still remain pending until manual cleanup | Add cleanup only if abandoned uploads become a demo problem |
| Frontend media composer/playback | Passed | `frontend/src/components/features/chat/pages/channel-view.tsx` supports paperclip selection for `image/*`, `video/*`, and `audio/*`, uploads through `/v1/uploads`, re-reads the latest access token before raw file PUTs, validates protected audio/video response MIME types, and renders a fallback if protected playback cannot load; `npm run typecheck` passed | No browser e2e test verifies actual media playback pixels/audio | Manually publish a small photo, video, and audio clip during final UI rehearsal |
| Focused verification | Passed | `python -m pytest backend\tests\test_p0_requirements.py -q` -> `33 passed, 13 skipped`; `cd frontend && npm run typecheck` passed | Local backend test skips depend on database availability; no browser e2e test has clicked through media playback | Run the manual UI media step in the already-started stack before supervisor review |

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
| Security honesty | Superseded by Phase 8 | This historical pass documented the former JS-managed credential design; Phase 8 now uses memory-only access tokens and rotating `HttpOnly` refresh cookies with Origin/CSRF controls | Browser automation and MFA remain absent | Follow the Phase 8 security and deployment documentation |

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

The Docker path, backend tests, frontend typecheck/build, upgraded full-stack verifier, and Docker-network event-integrity dry-run passed in this historical environment. Phase 8 later added and live-validated a production-oriented single-host boundary; neither pass is a certification of high-availability Internet-scale readiness.

## Remaining Risks

- Direct host execution of `python scripts/backfill_event_integrity.py --dry-run` failed on this machine with PostgreSQL password authentication; the Docker-network fallback passed and should be used for the final demo if the host has a conflicting PostgreSQL setup.
- Backend tests and the live demo verifier should not be run concurrently against the same Docker database because the tests reset state.
- There is still no full CI broker-outage/DLQ integration scenario.
- Frontend token storage remains demo-grade.
- There is no automated browser e2e test for approval-based membership refresh.

## Recommended Next Step

Package the final submission materials: final report, screenshots, and a short supervisor script that follows the Golden Demo Path exactly.
