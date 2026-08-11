# Testing

## Phase 1 Security Regression Tests

`backend/tests/security/test_phase1_hardening.py` contains 27 focused regressions covering:

- `/sync` isolation between channels, outsider denial, and self-targeted removal backfill;
- streamed upload handling without `request.body()`, configured/declared size bounds, checksum validation, interruption cleanup, immutable second PUT behavior, original-byte preservation, and continued attachment use;
- production-like JWT/encryption-secret validation while development/test convenience remains available;
- WebSocket delivery for subscribed channels, denial for unsubscribed/empty sets (including other users' membership updates), final-channel unsubscribe, and self-targeted removal delivery;
- pending-member denial for private seen state, history, statistics, sync, and WebSocket subscription membership.

Focused command:

```bash
cd backend
python -m pytest -q tests/security/test_phase1_hardening.py
```

Verified on 2026-08-10 against a dedicated PostgreSQL 16 test container: `27 passed, 1 warning`. The warning is the existing `passlib` access to deprecated `argon2.__version__` metadata.

## Phase 2 Authentication Security Regression Tests

`backend/tests/security/test_phase2_auth_hardening.py` contains 19 focused regressions covering:

- active, revoked, logout-all, isolated-session, forged-`sid`, legacy-token, idle-expiry, and absolute-expiry access behavior;
- refresh rotation uniqueness, one-time compatibility rotation for a current pre-Phase-2 refresh token, stale-token replay detection, family revocation even if audit logging fails, compromise of the newly rotated token, audit logging, and unrelated-session continuity;
- authenticated WebSocket ticket issue, opaque hashed storage, short expiry, atomic single use, user/session binding, anonymous/expired denial, and rejection of raw access JWT URL parameters;
- valid ticket connection, revoked-session reconnect denial, authentication-expiry socket closure, idempotent local plus Redis revocation dispatch without credential payloads, and durable logout behavior during a Redis publish outage.

Focused command:

```bash
cd backend
python -m pytest -q tests/security/test_phase2_auth_hardening.py
```

Verified on 2026-08-10 against isolated PostgreSQL 16: `19 passed, 1 warning`. The complete backend suite then passed with `124 passed, 1 warning`.

## Security Hardening Phase 3

`backend/tests/security/test_phase3_abuse_hardening.py` contains 19 focused regressions covering:

- normal Redis limiting, threshold enforcement, sensitive local fallback during Redis failure, and the documented low-risk allow policy;
- text/edit UTF-8 byte limits, structured JSON serialized-size/depth limits, and ordinary-message compatibility;
- 100-entry REST sync and WebSocket subscribe/unsubscribe/resume/sync-state boundaries, including safe oversized WebSocket rejection before database work;
- monotonic/idempotent seen state with explicit outbox-row counts;
- reaction value constraints, duplicate add/nonexistent delete idempotency, and outbox-row counts;
- fixed-query reaction rendering: 25 messages use exactly two `message_reactions` queries plus one batched sender query;
- normalized `message_attachments` authorization for owner/member/outsider and SQL evidence that lookup no longer scans message attachment JSON;
- channel, active-invite, upload, and concurrent-WebSocket quota boundaries;
- RabbitMQ queue expiry/TTL/max-length declaration parity between backend and worker;
- durable bind/unbind outbox generation, broker failure retry state without membership rollback, and duplicate command safety;
- bounded Redis fanout attempts, exponential retry delays, and capped pre-requeue delay.

Run:

```bash
cd backend
python -B -m pytest -q tests/security/test_phase3_abuse_hardening.py
```

Verified on 2026-08-10 against isolated PostgreSQL 16: `19 passed, 1 warning`. Fresh Alembic migration through `0018_phase3_abuse_hardening` passed. A separate upgrade from revision 0017 with a historical JSON attachment produced the expected normalized `message_id|upload_id|channel_id` backfill row. The complete backend suite passed with `143 passed, 1 warning`.

The broker-binding and Redis-outage tests are deterministic fake-broker/fake-Redis checks of retry state, arguments, and backoff. They are not claimed as a live RabbitMQ/Redis outage integration test.

## Security Hardening Phase 4

`backend/tests/security/test_phase4_p0_hardening.py` contains 15 focused regressions:

- `test_old_bind_generation_cannot_beat_newer_unbind`: delayed old bind is rejected after a newer unbind generation.
- `test_old_unbind_generation_cannot_beat_newer_rejoin`: delayed old unbind cannot remove a legitimate newer rejoin.
- `test_duplicate_current_generation_is_idempotent`: duplicate current projection is harmless.
- `test_worker_crash_after_rabbit_action_retries_full_projection_safely`: rollback after Rabbit success repeats safely.
- `test_missed_membership_event_cannot_deliver_or_decrypt_post_removal_message`: lost Redis removal does not expose plaintext.
- `test_active_member_refreshes_generation_and_receives_realtime_message`: generation refresh preserves legitimate delivery.
- `test_slug_delete_and_restore_use_same_versioned_reconciliation`: all related topology paths use desired state.
- `test_sync_large_single_channel_materializes_only_global_limit`: 10,000 missed rows with `limit=100` materialize 100.
- `test_sync_many_channels_uses_one_decreasing_global_row_budget`: 100 channels share one 500-row budget and deterministic order.
- `test_sync_next_cursor_has_no_skip_or_duplicate`: successive sequence cursors neither skip nor duplicate.
- `test_sync_arbitrary_pending_removed_and_outsider_cursors_return_no_history`: cursor IDs do not bypass authorization.
- `test_protected_download_uses_chunked_file_response_without_read_bytes`: multiple bounded ASGI chunks are sent without `Path.read_bytes`.
- `test_protected_download_authorization_blocks_pending_removed_and_outsider_before_stream`: denial happens before streaming/admission.
- `test_download_concurrency_limit_allows_boundary_and_rejects_one_above`: the per-user lease boundary is race-safe.
- `test_aborted_stream_releases_download_slot`: cancellation releases the lease for reuse.

Run:

```bash
cd backend
python -B -m pytest -q tests/security/test_phase4_p0_hardening.py
```

Verified on 2026-08-10 against isolated PostgreSQL 16: `15 passed, 1 warning`; the complete backend suite passed with `158 passed, 1 warning`. Fresh migration through `0019_phase4_p0_hardening` passed. A separate upgrade from revision 0018 with one active member and one already-removed historical binding produced desired `BOUND`/`UNBOUND` states, retained both old/current routing keys, and enqueued two current reconcile rows.

The broker-ordering and missed-Redis-notification tests are deterministic simulations. No live multi-worker RabbitMQ ordering or live Redis-loss test is claimed. Download concurrency is per backend process; proxy bandwidth limits are outside the application test boundary.

## Security Hardening Phase 5

`backend/tests/security/test_phase5_medium_hardening.py` contains 18 focused regressions covering:

- normal weighted WebSocket commands, flood rejection, repeated resume/history depletion, one total 100-row history cap across channels, unchanged subscribe/cursor suppression, oversized frame closure, per-socket isolation, and disconnect cleanup;
- active/deleted/restored channel attachment access for upload owner, channel owner, admin, member, pending, removed, outsider, and superadmin identities, plus deleted-message behavior;
- targeted one-use acceptance, second-use rejection, expiry/deletion denial, reusable generic-link semantics, per-accept audit events, deterministic accept-versus-revoke winners, concurrent generic accepts, and later revoke denial;
- one-call Redis counter/TTL behavior, non-extending windows, Redis outage fallback, adversarial key churn, bounded memory, fail-safe saturation, low-risk availability, and clean Redis recovery.

Run:

```bash
cd backend
python -B -m pytest -q tests/security/test_phase5_medium_hardening.py
```

Verified on 2026-08-10 against disposable PostgreSQL 16: `18 passed, 1 warning`. Phase 1–4 security suites passed `80 passed, 1 warning`, and the complete backend suite passed `176 passed, 1 warning`. Invite concurrency tests use two independent PostgreSQL sessions with explicit row-lock barriers. Redis Lua and WebSocket flood/work behavior are deterministic application-level harnesses, not a live Redis outage or multi-backend socket load test. No database migration was added.

## Security Hardening Phase 6

`backend/tests/security/test_phase6_medium_hardening.py` contains 19 focused cases covering:

- normalized existing-account email invite resolution to immutable user ID;
- the issuance-to-email-change-to-attacker-reclaim attack, including the original target accepting after changing email;
- verification clearing on a real email change and preservation for the same canonical address;
- unresolved pre-registration denial before verification and acceptance after a simulated trusted verification completion;
- token plus unverified profile-email denial, explicit user-ID compatibility, and reusable generic-link compatibility;
- independent-session concurrent email claims under the normalized unique index, with no invite transfer;
- per-user, same-IP/many-user, and many-IP/global protected-download boundaries;
- concurrent atomic admission without oversubscription, no partial-capacity leak on rejection, and bounded active-state maps;
- exact-once release after cancellation, ASGI send failure, missing file/stat failure, and response-construction failure;
- database-session closure before streaming starts; and
- direct-mode forwarding-header rejection plus explicit trusted-proxy client-IP resolution.

Run:

```bash
cd backend
python -B -m pytest -q tests/security/test_phase6_medium_hardening.py
```

Verified on 2026-08-10 against disposable PostgreSQL 16: `19 passed, 1 warning`. Phase 1–5 security suites passed `98 passed, 1 warning`; the complete backend suite passed `195 passed, 1 warning`. Fresh migration and a representative 0019→0020 upgrade passed. The upgrade fixture contained an existing-user email invite, unresolved email invite, user-ID invite, and generic invite. Frontend typecheck, both Compose render checks, and containerized Nginx syntax validation passed.

These Phase 6 tests predate the real mailbox-verification lifecycle and retain a
few direct timestamp fixtures for their narrow invite-identity cases. Phase 10
adds the end-to-end challenge/capture/confirmation path and proves the same
pre-registration invitation remains denied before genuine confirmation and is
accepted afterward. Download concurrency tests exercise the application/ASGI
boundary, not a live many-account TCP slow-reader load. Nginx slow-client
controls were syntax/configuration-validated rather than load-tested.

Proxy validation:

```bash
docker run --rm --add-host backend:127.0.0.1 --add-host frontend:127.0.0.1 \
  -v "${PWD}/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  nginx:1.27-alpine nginx -t
docker compose -f docker-compose.hardened.yml config --quiet
```

## Security Hardening Phase 7

`backend/tests/security/test_phase7_final_app_hardening.py` contains 23 focused
cases covering:

- real PostgreSQL independent-session reproduction of the historical
  event-advisory/broker-binding cycle and channel-delete/member serialization;
- mocked RabbitMQ failure with durable retry state, post-commit diagnostics,
  audit failure isolation, and transactional rollback safety;
- bounded login/password/refresh/logout fields, fixed-size auth limiter keys,
  bounded failed-login audit data, declared/chunked raw JSON rejection, and an
  unbuffered upload-stream exemption;
- development-environment allowlisting and fail-safe unknown labels; and
- valid/invalid attachment relationships, active-member/outsider authorization,
  and deleted-channel lifecycle behavior under the composite foreign key.

Run:

```bash
cd backend
python -B -m pytest -q tests/security/test_phase7_final_app_hardening.py
```

Verified on 2026-08-10 against disposable PostgreSQL 16: Phase 7 passed
`23 passed, 1 warning`; Phase 1–6 security suites passed `117 passed, 1 warning`;
the complete backend suite passed `218 passed, 1 warning`. Migration
`0021_phase7_attachment_integrity` passed on a fresh database and on a 0020
fixture containing two attachments (one deliberately mismatched), two users,
and one invite. The mismatch was normalized without deleting relations and a
new inconsistent write was rejected by PostgreSQL. Frontend typecheck and both
Compose render checks passed. RabbitMQ failure was mocked; no live RabbitMQ
outage test is claimed.

## Post-Phase-7 Targeted Security Repairs

`backend/tests/security/test_post_phase7_repairs.py` contains 21 focused cases
for the two findings in `SECURITY_VERIFICATION_AFTER_PHASE7.md`:

- direct, spoofed, trusted-proxy, and conservative malformed-forwarding client-IP behavior for WebSockets;
- distinct connection limiter keys and independent fixed-window allowances for two clients behind one trusted Nginx peer;
- missing/empty `ENVIRONMENT` failure, explicit development labels, strict unknown labels, secure production-like configuration, and proof that a missing environment cannot reach the development Fernet fallback.

```bash
cd backend
python -B -m pytest -q tests/security/test_post_phase7_repairs.py
```

Verified on 2026-08-11: the pre-fix reproduction produced `3 failed, 18 passed`.
After the targeted repair, the focused file passed `21 passed`; the Phase 6 and
Phase 7 files passed `42 passed, 1 warning`; and the complete suite passed
`239 passed, 1 warning` against a disposable PostgreSQL 16 container. The
warning remains the existing `passlib` access to deprecated
`argon2.__version__` metadata. Frontend typecheck and direct/hardened Compose
render checks also passed. Nginx configuration was unchanged, so no new
`nginx -t` result is claimed for this repair.

## Security Hardening Phase 8

`backend/tests/security/test_phase8_production_hardening.py` contains 13 focused
tests covering:

- browser login hides refresh JSON and sets an HttpOnly cookie;
- production `Secure`, `SameSite=Strict`, `Path=/`, host-only cookie behavior;
- missing/mismatched CSRF and untrusted Origin denial;
- browser refresh rotation and stale-cookie replay-family revocation;
- browser logout revocation plus refresh/CSRF cookie clearing;
- server-side session revocation blocking later browser refresh;
- development HTTP cookie compatibility and production insecure-cookie refusal;
- production wildcard-CORS refusal, secure default cookies, production docs off,
  development docs on, and minimal public liveness;
- production rejection of plain-HTTP external profile media;
- static proof that authentication code has no `localStorage`, `sessionStorage`,
  IndexedDB, persistent Zustand, or old authentication-cookie token storage, and
  page bootstrap calls the browser refresh flow. The one remaining frontend
  `persist()`/`localStorage` match is inspected and belongs only to
  `chatPreferencesStore.ts` UI preferences.

Verified on 2026-08-11 against disposable PostgreSQL 16:

```text
Phase 8 focused: 13 passed, 1 warning
Phase 2/4/5/6/7/post-7/8 regression: 128 passed, 1 warning
Complete backend: 252 passed, 1 warning
Frontend typecheck: passed
Frontend production build: passed (Next middleware filename deprecation notice)
Production Compose config: passed
Backend/worker/frontend image build: passed
```

The running production experiment also verified migration exit 0, backend and
worker operation through the runtime database role, the complete demo verifier,
UID 10001 application processes, UID 101 proxy, read-only/capability controls,
default-credential rejection, actual denial of `CREATE DATABASE`/`CREATE ROLE`,
only Nginx host bindings, HTTP-to-HTTPS redirect, disposable self-signed TLS,
actual HTTPS security headers/CSP, hidden readiness/docs, and unknown-Host
rejection. The machine already had an unrelated local PostgreSQL process on host
port 5432; Docker inspection confirmed the production PostgreSQL container had
an empty `PortBindings` map. No publicly trusted certificate is claimed.

Run the focused suite:

```bash
cd backend
python -B -m pytest -q tests/security/test_phase8_production_hardening.py
```

## Security Hardening Phase 9

`backend/tests/security/test_phase9_data_protection.py` contains 35 focused
tests covering:

- production key-ring requirements, active-key membership, safe IDs, strict
  base64/32-byte length, duplicate JSON keys, the 32-key bound, development-only
  fallback, plaintext-policy rejection, and secret-free validation errors;
- v2 text/JSON envelopes, active-key switching, historical-key reads, unknown
  key/tamper failure, legacy-v1 migration compatibility, and plaintext failure;
- real multi-megabyte filesystem ciphertext inspection, byte-exact bounded
  decrypt streaming, logical SHA-256/size preservation, malformed header/frame
  bounds, AES-GCM tamper rejection, response send/integrity lease cleanup, and
  encrypted Range rejection;
- message migration/rotation idempotency with unchanged IDs/sequence/type/time
  and no new outbox/audit rows;
- plaintext upload migration, file-replaced/DB-version-0 crash recovery without
  double encryption, upload rotation, crypto status, and old-key removal proof.

Run:

```bash
cd backend
python -B -m pytest -q tests/security/test_phase9_data_protection.py
python -B -m pytest -q
```

Verified on 2026-08-11 against disposable PostgreSQL 16: Phase 9 focused
`35 passed`. A fresh database upgraded through
`0022_phase9_upload_encryption`; a representative 0021 database retained its
historical upload with `storage_encryption_version=0` and null key ID after the
schema upgrade. Cryptographic conversion remained a separate operator action.
The complete backend suite passed `287 passed, 1 warning`; the warning remains
the existing passlib/argon2 metadata deprecation. Frontend typecheck and
production build passed, as did development, hardened-demo, and production
Compose rendering. A disposable production-profile stack passed the full demo
verifier over the real PostgreSQL/outbox -> RabbitMQ -> worker -> Redis ->
WebSocket path. Direct storage inspection found no upload/message plaintext
marker, authorized download was byte-exact, encrypted Range returned 416, both
migration commands were idempotent, and the running worker had no JWT or
data-encryption environment keys.

Operator preflight/postflight:

```bash
python -m app.db.crypto_tool status
python -m app.db.crypto_tool migrate-messages
python -m app.db.crypto_tool migrate-uploads
python -m app.db.crypto_tool rotate-messages --to-key-id <active-id>
python -m app.db.crypto_tool rotate-uploads --to-key-id <active-id>
python -m app.db.crypto_tool status
```

Do not run database-resetting tests, crypto maintenance, or the live demo
verifier concurrently against the same database/storage volume.

## Security Hardening Phase 10

`backend/tests/security/test_phase10_identity_presence.py` contains 25 focused
tests grouped around email verification and distributed presence. They cover:

- unverified registration, raw-token capture with hash-only PostgreSQL storage,
  exact current-email confirmation, single consumption, expiry, revocation,
  cross-user denial, email-change invalidation, challenge supersession, and
  two-session confirmation concurrency;
- controlled SMTP failure, production console/capture rejection, production
  plaintext SMTP rejection, resend rate limiting, and absence of raw tokens in
  audit payloads/log records;
- the complete unresolved email invite sequence: denial before verification,
  real challenge confirmation, then successful acceptance;
- first/second socket semantics, local and two-backend final disconnect,
  heartbeat extension, crash/lease expiry, stale/live mixed leases, duplicate
  reapers, rapid reconnect, multiple sessions, Redis failure degradation, and
  heartbeat-task cleanup.

Run with disposable PostgreSQL and Redis:

```bash
cd backend
set DATABASE_URL=postgresql+asyncpg://postgres:...@127.0.0.1:.../channels
set PHASE10_TEST_REDIS_URL=redis://127.0.0.1:.../0
python -B -m pytest -q tests/security/test_phase10_identity_presence.py
```

Verified on 2026-08-11: the focused suite passed `25 passed, 1 warning` against
disposable PostgreSQL 16 and real Redis 7 Lua execution. The requested Phase
2/5/6/8/9, post-Phase-7, and Phase 10 regression group passed `150 passed, 1
warning`. A fresh database upgraded through `0023`; a representative
`0022 -> 0023` database preserved verified/unverified users, unresolved and
existing-user invitations, and began with zero challenge rows. The warning is
the existing passlib/argon2 version-metadata deprecation.

The complete backend suite then passed `312 passed, 1 warning`. Frontend
`npm run typecheck` and `npm run build` passed; the build emitted only the
existing Next.js middleware-filename deprecation notice. English and Arabic
catalog parsing/key alignment passed with 825 aligned keys. Development,
hardened-demo, and production Compose renders passed, and production rendering
confirmed that SMTP settings are injected only into the backend.

A disposable Mailpit SMTP sink received a verification message from the generic
SMTP transport without external delivery. This proves the application-to-SMTP
boundary, not a real provider, public DNS, or TLS mailbox-delivery path. A fresh
isolated hardened stack also passed `scripts/verify_demo_flow.py` through the
PostgreSQL/outbox/RabbitMQ/worker/Redis/WebSocket route. A supplemental live
check passed authorized encrypted-upload download, message/upload ciphertext
inspection, and logout-all access-token revocation. The run also caught and
fixed missing inherited proxy identity headers in the WebSocket locations;
containerized `nginx -t` passed after the fix.

## Automated Tests
Backend P0 tests:
- `test_channel_creation_generates_slug_and_logs_event`
- `test_owner_can_create_generic_invite_for_every_channel_kind` (six public/private and join-policy combinations)
- `test_list_channels_scopes_pagination_and_preview_permissions`
- `test_list_channels_keeps_channels_visible_when_last_preview_key_is_unavailable`
- `test_list_channels_scope_visibility_and_search_filters`
- `test_list_channels_treats_owner_user_id_as_owner_when_membership_row_is_missing`
- `test_message_encryption_round_trip_and_authz_and_event`
- `test_upload_download_requires_channel_membership`
- `test_media_attachments_can_be_published_without_text_and_synced`
- `test_publishing_attachment_requires_stored_upload_content`
- `test_publish_request_rejects_duplicate_attachment_references`
- `test_publish_request_rejects_extra_attachment_metadata`
- `test_upload_store_errors_are_logged_and_do_not_mark_content_stored`
- `test_upload_checksum_mismatch_is_logged_and_keeps_upload_pending`
- `test_svg_uploads_are_rejected_for_protected_media`
- `test_upload_storage_path_sanitizes_filename_and_stays_within_base_dir`
- `test_avatar_url_validation_rejects_unsafe_values`
- `test_avatar_url_validation_accepts_safe_values`
- `test_profile_avatar_upload_is_accessible_to_authenticated_users`
- `test_profile_wallpaper_upload_is_saved_to_current_user`
- `test_avatar_update_rejects_unowned_or_non_image_uploads`
- `test_private_channel_avatar_upload_requires_channel_membership`
- `test_username_validation_rejects_unsafe_identifiers`
- `test_channel_slug_validation_rejects_unsafe_identifiers`
- `test_smoke_flow_channel_join_publish_sync_and_events`

Delivery reliability tests:
- `test_outbox_publish_success_marks_published`
- `test_outbox_failure_schedules_retry_with_sanitized_error`
- `test_outbox_failure_after_max_attempts_dead_letters`
- `test_admin_delivery_stats_are_scoped_to_channel_managers`
- `test_manual_retry_resets_dead_lettered_outbox_and_logs_event`

Event integrity tests:
- `test_new_events_receive_hash_chain_metadata`
- `test_integrity_verification_returns_valid_for_unchanged_chain`
- `test_integrity_verification_detects_payload_tampering`
- `test_integrity_verification_detects_event_type_tampering`
- `test_integrity_verification_detects_previous_hash_tampering`
- `test_integrity_verification_reports_legacy_missing_hash`
- `test_unauthorized_user_cannot_verify_channel_event_integrity`

Superadmin tests (`backend/tests/test_superadmin.py`):
- explicit, idempotent bootstrap and refusal to auto-promote an existing user
- immediate account deactivation, session revocation, login denial, and access-token denial
- immediate socket closure plus the Phase 2 Redis cross-instance control path
- denied superadmin dependency access with audit logging
- global system/cross-channel event visibility with matching channel name/slug and actor identity, including upload-event channel recovery through message attachments
- relevant event search by actor plus category filtering
- safe event-detail projection that excludes content, nested attachments, storage paths, and arbitrary raw fields
- superadmin channel suspension and restoration without channel membership

The P0 message test also asserts that new `message.published` audit payloads contain only operational summary fields and do not duplicate `content_text`, `content_json`, or attachment structures.

Run in Docker (recommended):
```bash
docker compose run --rm backend sh -lc "cd /app && PYTHONPATH=/app pytest -q"
```

Local run:
```bash
cd backend
python -m pytest -q
```
Note: local tests may skip if `DATABASE_URL` PostgreSQL is not reachable.

Focused delivery reliability run:
```bash
python -m pytest backend/tests/test_delivery_reliability.py -q
```
These tests use a fake AMQP exchange to verify worker status transitions without requiring a live RabbitMQ broker. They still require PostgreSQL because the project uses PostgreSQL-specific schema behavior.

Focused event integrity run:
```bash
cd backend
python -m pytest tests/test_event_integrity.py -q
```
These tests verify hash creation, sequential chain linking, clean verification, tamper detection, missing legacy hashes, and authorization for the integrity endpoint.

Focused superadmin run:
```bash
docker compose run --rm backend sh -lc "cd /app && PYTHONPATH=/app pytest tests/test_superadmin.py -q"
```
The earlier 2026-06-19 isolated PostgreSQL run passed all seven original focused tests. After console hardening, the complete suite passed `68` tests against a disposable PostgreSQL 16 container; frontend typecheck and production build also passed. After Phase 1 security hardening on 2026-08-10, the broad backend suite passed `105` tests with one existing dependency deprecation warning against an isolated PostgreSQL 16 container. Use a dedicated test database because the shared fixture truncates its configured database between cases.

Legacy event backfill check:
```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"
```
The script groups events by `channel:<channel_id>` or `system`, computes hashes in chronological order, and reports what would be updated without committing. The Docker command is the canonical demo-safe path because it uses the backend container's database environment.

Real backfill, only when intentionally initializing legacy rows:
```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py"
```
Host execution (`python scripts/backfill_event_integrity.py --dry-run`) may work, but it depends on local PostgreSQL credentials matching the Docker database. On failure, the script prints the canonical Docker fallback.

Frontend typecheck:
```bash
cd frontend
npm run typecheck
```

Frontend production build:
```bash
cd frontend
npm run build
```

Frontend locale file validation:
```bash
cd frontend
node -e "JSON.parse(require('fs').readFileSync('src/locales/en.json','utf8')); JSON.parse(require('fs').readFileSync('src/locales/ar.json','utf8')); console.log('locale json ok')"
```
This verifies that both English and Arabic message catalogs are valid JSON. The current frontend i18n pass is also covered by `npm run typecheck`, but there is not yet an automated visual RTL regression test.

Frontend locale key-set alignment:
```bash
cd frontend
node -e "const fs=require('fs'); const flat=(obj,p='')=>Object.entries(obj).flatMap(([k,v])=>v&&typeof v==='object'&&!Array.isArray(v)?flat(v,p?p+'.'+k:k):[p?p+'.'+k:k]); const en=flat(JSON.parse(fs.readFileSync('src/locales/en.json','utf8'))); const ar=flat(JSON.parse(fs.readFileSync('src/locales/ar.json','utf8'))); const missingAr=en.filter(k=>!ar.includes(k)); const missingEn=ar.filter(k=>!en.includes(k)); if(missingAr.length||missingEn.length){console.log({missingAr,missingEn}); process.exit(1)} console.log('locale keys aligned:', en.length);"
```

Docker Compose config check:
```bash
docker compose config
```

## Demo Verification Script
```bash
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```
Verifies:
- User A/User B/User C register+login
- Channel creation
- Join-after-WebSocket-connect flow with explicit subscribe/resync
- Publish flow
- Live WebSocket delivery to the subscriber when available
- REST `/sync` backfill when live delivery is unavailable
- Event log contains core events
- Event integrity is checked from `GET /v1/channels/{id}/events/integrity` for the fresh demo channel
- Private upload access is denied to an unauthorized user
- Backend regression coverage verifies attachment-only photo/video/audio messages are syncable by a subscriber, that messages cannot reference upload records before file bytes are stored, that client-supplied attachment metadata is rejected, and that duplicate attachment references are rejected
- Upload create/store/access audit events are covered, and size/checksum upload store failures are logged without marking the upload content as stored
- SVG image uploads are rejected for protected media/avatar safety
- Unsafe avatar URLs are rejected before storage
- Uploaded profile avatars are visible to authenticated users through the protected media path
- Uploaded profile wallpapers are saved on the current user's backend profile and remain readable only by the owning user through the protected media path
- Private channel avatar uploads remain restricted to approved channel members
- Avatar and wallpaper updates reject unowned uploads and non-image uploads
- Final PASS/FAIL summary with visible step names and timeouts
The verifier does not currently force a RabbitMQ failure or DLQ transition; use the backend delivery reliability tests and worker logs for that path.
Note: the verifier is the best single proof of the pub/sub chain in this repo, but it is still a scripted demo flow rather than a CI-level full-stack integration suite.
Do not run the Docker backend test suite and `scripts/verify_demo_flow.py` concurrently against the same Docker database; the tests reset database state and can invalidate live verifier users mid-flow.

Latest focused media verification:
```bash
python -m pytest backend\tests\test_p0_requirements.py -q
cd frontend
npm run typecheck
```
Result on 2026-06-16 multimedia audit: backend P0 tests passed (`33 passed, 13 skipped`) and frontend typecheck passed.

## Approval-Required Membership Verifier
```bash
python scripts/verify_approval_flow.py --base-url http://localhost:8000/v1
```
Verifies:
- owner, pending subscriber, and outsider registration
- private `approval_required` channel creation
- pending join request before approval
- subscriber WebSocket opened while pending
- existing subscriber channel keeps the socket subscription set non-empty
- owner approval
- membership update over WebSocket, or explicit REST membership resync when realtime is unavailable
- explicit WebSocket subscribe/resync after approval
- live message delivery after approval when the worker/RabbitMQ/Redis path is healthy
- REST `/sync` backfill for the approved subscriber
- event log contains `membership.approved` and `message.published`
- outsider is denied private channel messages

If live delivery fails but REST backfill succeeds, the script prints that degraded result instead of hiding it.

## Delivery Reliability Verifier
```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/verify_delivery_reliability.py --base-url http://localhost:8000/v1"
```
Verifies:
- owner can create a channel and publish a message
- worker moves at least one outbox row to `published`
- a controlled `dead_lettered` outbox row appears in `/v1/admin/delivery/dead-lettered`
- manual retry resets that controlled row to `pending`
- outsider cannot access delivery monitor stats

This is an automated supervisor proof for the normal worker path and controlled manual retry path. It is not a full RabbitMQ outage simulation. The PostgreSQL outbox remains the source of truth; the RabbitMQ DLQ is operational mirror/evidence when the worker can publish to it.

## Manual Verification
- Frontend login/register/channel flows.
- English/Arabic language switcher and Arabic RTL rendering on login/register, channel, details, event log, delivery monitor, profile, and sessions pages.
- Event log subpage rendering.
- Ciphertext-at-rest SQL check.
- Unauthorized publish/read denial behavior.
- Private upload download denial for a non-member.
- Profile/channel avatar upload and chat wallpaper upload/display behavior, including fallback initials/icons and protected-image loading.
- Superadmin console global event filtering, user deactivation/reactivation, session revocation, channel suspension/restoration, and normal-user denial.

## Current Limitations
- Local Windows `npm run build` passed during the 2026-06-14 frontend i18n pass. Docker Compose remains the canonical evaluator path if local Node dependency behavior differs on another machine.
- No dedicated frontend lint script currently exists (`npm run lint` unsupported).
- No automated browser screenshot/regression suite currently verifies Arabic RTL layout; check it manually during the UI demo.
- `scripts/ws_client.py` is still useful for a standalone socket check, but the main demo verifier now covers the end-to-end proof path with join-after-connect resubscribe, live WebSocket delivery, event-integrity verification, and REST backfill fallback.
- There is no dedicated CI broker/WebSocket integration test yet.
- Delivery reliability tests cover database outbox transitions and admin APIs, but they mock AMQP publish success/failure rather than exercising a real RabbitMQ outage.
- `scripts/verify_delivery_reliability.py` strengthens the supervisor proof with the live worker publish path and a controlled dead-letter/manual retry check, but full broker-outage CI remains future work.
