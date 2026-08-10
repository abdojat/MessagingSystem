# Security Hardening Phase 1 Report

## 1. Scope

Phase 1 inspected the FastAPI message/upload routes, `MessageService`, channel RBAC/statistics, membership event creation, REST `/sync`, WebSocket subscription and Redis forwarding, the PostgreSQL outbox/RabbitMQ/Redis flow, encryption/JWT configuration, existing upload/avatar/wallpaper/attachment behavior, and the backend test/documentation baseline.

The implemented scope was limited to the six requested issues: sync membership-event privacy, upload immutability, streamed upload intake, production-like secret validation, WebSocket empty-subscription filtering, and pending-member read authorization. No frontend redesign, authentication-protocol migration, broker-binding redesign, attachment encryption, key rotation, or Docker credential redesign was attempted.

## 2. Confirmed vulnerabilities

| Original issue | Status | Evidence |
| --- | --- | --- |
| `/sync` cross-channel membership leakage | **CONFIRMED** | `MessageService.sync` queried all matching membership/member/invite audit events after `since` without channel/target authorization. It also fell back to `actor_user_id`, so a removal row described the administrator rather than reliably notifying the removed target. |
| Stored upload bytes could be replaced | **CONFIRMED** | `PUT /uploads/{file_id}/content` called `Path.write_bytes` on every authorized PUT and had no finalized-state rejection or row lock. |
| Upload request-body memory exhaustion | **CONFIRMED** | The PUT route called `await request.body()` before validation/storage. `.env.example` advertised 1 GiB although the backend default was 25 MiB. |
| Insecure production-like secret defaults | **PARTIALLY CONFIRMED** | JWT configuration accepted `change-me`, missing, or weak values in every environment. Fernet already refused its deterministic fallback outside dev/test/local when encryption was first used, but this was not startup validation and JWT had no equivalent protection. |
| Empty WebSocket subscription accepted channel events | **CONFIRMED** | The filter used `and subs`, so an empty set bypassed ordinary channel filtering. Every `membership_update` also bypassed filtering, even when it concerned another user. |
| Pending-member authorization inconsistencies | **PARTIALLY CONFIRMED** | `mark_seen` and private channel statistics treated a pending membership row as sufficient. Message history, REST sync, WebSocket membership/resume, channel-list previews, and unread enrichment already used approved-reader roles correctly. |

## 3. Changes made

### `/sync` membership privacy

- **Root cause:** membership audit events were selected globally and the response inferred affected identity from the event actor.
- **Files:** `backend/app/services/message_service.py`.
- **Before:** any authenticated caller using `since` could receive membership activity from unrelated channels; a removed user was not reliably represented as the affected user.
- **After:** the SQL query and a defense-in-depth post-filter allow events only for channels where the caller currently has an approved role, or events whose `user_id`/`target_user_id` equals the caller. Role inference now represents join/add/approve/promote/demote/remove/leave events consistently, including `new_role=none` for removal.

### Immutable, streamed upload storage

- **Root cause:** the route buffered the entire request and the service rewrote the final path without a lifecycle/race check.
- **Files:** `backend/app/api/routes/messages.py`, `backend/app/services/message_service.py`, `.env.example`, `README.md`.
- **Before:** PUT used `request.body()`, checksum calculation required the complete byte string, and later PUTs could replace already-referenced bytes.
- **After:** PUT passes `request.stream()` to the service. The service locks the upload row, treats the existing `public_url` as the persisted pending/stored marker, streams bounded 64 KiB writes into a same-directory temporary file, incrementally tracks bytes/SHA-256, aborts at configured or declared limits, removes partial files on every failure, and atomically exposes a complete file with a create-only hard link. A finalized upload or existing final path returns `409 UPLOAD_IMMUTABLE`; original bytes are not overwritten. `.env.example` now matches the existing 25 MiB application/frontend behavior.

### Production-like secret validation

- **Root cause:** settings had development defaults but no environment-aware startup validator.
- **Files:** `backend/app/core/config.py`, `.env.example`, `README.md`.
- **Before:** production-like deployments could start with a missing/default/weak JWT signing secret. Fernet fallback rejection occurred only when encryption was used.
- **After:** `production`, `prod`, and `staging` reject absent or known-placeholder JWT secrets, secrets shorter than 32 characters or with obvious low diversity, and missing/invalid Fernet keys while encryption is enabled. Dev/test/local behavior remains available. No real secret was added.

### WebSocket subscription filtering

- **Root cause:** ordinary filtering was conditional on the subscription set being non-empty, and membership updates had a blanket bypass.
- **Files:** `backend/app/realtime/ws_manager.py`.
- **Before:** an empty set behaved like a wildcard for channel events, and an unrelated membership update could bypass the filter.
- **After:** every ordinary channel event requires its channel in the socket subscription set. Only a membership update targeting the authenticated `user_id` bypasses this rule; a removal/leave also removes that channel from the local set.

### Pending-member read authorization

- **Root cause:** two paths checked membership-row existence or explicitly included `pending` instead of using the shared approved-reader rule.
- **Files:** `backend/app/services/message_service.py`, `backend/app/services/channel_service.py`.
- **Before:** pending users could write seen/unread state and view private channel statistics.
- **After:** seen state uses `_assert_can_read`, and private statistics use `can_read`. Approved readers remain owner/admin/member. Existing history, sync, and WebSocket checks were retained.

## 4. Tests added

All new tests are in `backend/tests/security/test_phase1_hardening.py`.

### Configuration

- `test_development_and_test_configuration_allow_explicit_test_convenience`: dev/test placeholders remain usable for local tests.
- `test_production_rejects_missing_jwt_secret`: absent JWT secret fails production configuration.
- `test_production_like_environments_reject_known_default_jwt_secrets`: production/prod/staging reject both known defaults (six parameter cases).
- `test_production_rejects_missing_encryption_key_when_enabled`: production cannot use the dev fallback.
- `test_production_accepts_securely_configured_secrets`: valid JWT and Fernet values pass.

### Uploads

- `test_upload_route_streams_request_without_calling_body`: the route consumes `stream()` and never calls `body()`.
- `test_streamed_upload_is_immutable_and_attachment_reference_still_works`: chunked first PUT succeeds, a same-size replacement gets 409, original bytes remain, and message attachment access still works.
- `test_streamed_upload_aborts_at_configured_max_and_cleans_partial_file`: configured overflow aborts at 413 and leaves no valid/temporary file.
- `test_streamed_upload_rejects_declared_size_mismatch_without_finalizing`: larger-than-declared and smaller-than-declared bodies fail without transition.
- `test_streamed_upload_rejects_checksum_mismatch_without_finalizing`: checksum mismatch remains pending and cleans files.
- `test_interrupted_stream_cleans_partial_upload_and_keeps_pending`: an interrupted stream cannot leave a stored or temporary artifact.
- `test_finalization_rolls_back_if_success_audit_event_cannot_be_stored`: a post-finalization audit failure rolls back the database marker and removes the final file.

### WebSocket filtering

- `test_subscribed_channel_event_is_delivered`: subscribed ordinary event is forwarded.
- `test_unsubscribed_channel_event_is_not_delivered`: a different channel is rejected.
- `test_empty_subscription_does_not_receive_other_users_membership_updates`: the original membership-update bypass is closed.
- `test_unsubscribing_final_channel_blocks_ordinary_channel_events`: an empty final set is not a wildcard.
- `test_targeted_membership_removal_reaches_affected_unsubscribed_user`: self-targeted removal still arrives.

### Sync and pending RBAC

- `test_sync_member_cannot_receive_membership_events_from_unrelated_channel`: Channel A membership cannot expose Channel B activity.
- `test_sync_outsider_cannot_receive_private_membership_activity`: an outsider receives no private membership/channel/message data.
- `test_sync_removed_user_receives_own_removal_event`: a removed user still receives the targeted `none` role update.
- `test_pending_member_cannot_access_private_read_derived_state`: pending users cannot mark seen, list private history, read private stats, sync messages, or join the WebSocket approved-channel set.

The file reports 27 test cases because the secret and size-mismatch tests are parametrized.

## 5. Validation results

Validation used a dedicated temporary PostgreSQL 16 container named `messaging-phase1-security-postgres` on host port 55432; it did not use or truncate the existing development database.

```text
python -m pytest -q tests/security/test_phase1_hardening.py
27 passed, 1 warning in 9.63s

python -m pytest -q tests/test_p0_requirements.py -k "upload or sync or seen or stats"
29 passed, 28 deselected, 1 warning in 21.83s

python -m pytest -q
105 passed, 1 warning in 46.75s

docker compose config --quiet
passed

git diff --check
passed (Git emitted line-ending conversion notices only)
```

The warning in each applicable pytest run is an existing `passlib` use of deprecated `argon2.__version__` package metadata. `python -m compileall -q app` also passed; generated tracked bytecode changes were restored before staging. Ruff, mypy, and pyright are not installed in the environment, so those checks could not be run.

Infrastructure notes:

- The initial local focused run had `5 passed, 24 skipped, 28 deselected` because its configured PostgreSQL host was unavailable.
- Docker Desktop was initially stopped and `docker compose ps` could not connect to the engine. Docker was started for isolated validation.
- The unrelated PostgreSQL already on localhost:5432 rejected the repository credentials with `InvalidPasswordError`; no database was created or modified there.

## 6. Remaining risks discovered

- Browser-managed access/refresh token storage remains demo-grade; this phase intentionally did not migrate authentication to httpOnly cookies/CSRF-aware sessions.
- WebSocket query-string token support remains and was intentionally not redesigned.
- Attachment bytes are access-controlled and now immutable but are not encrypted by the message-body Fernet layer.
- Encryption keys have no rotation/key-ring/KMS support.
- Real RabbitMQ -> worker -> Redis -> WebSocket security/reliability coverage remains script/manual rather than a dedicated CI integration test.
- Broker binding reconciliation and distributed socket/session revocation remain incomplete for a multi-backend deployment.
- Upload GET currently returns a bounded (25 MiB default) in-memory response and has no range/streaming, malware scanning, per-user quota, or external object-storage policy.
- The application audit hash chain is not externally anchored.
- One dependency deprecation warning remains for passlib/argon2 metadata access.

## 7. Recommended Phase 2

1. Move browser authentication to secure httpOnly/Secure/SameSite cookies with an explicit CSRF design.
2. Replace WebSocket query tokens with a short-lived one-time ticket or authenticated cookie handshake.
3. Add distributed session/socket revocation via Redis control messages.
4. Add one real RabbitMQ -> worker -> Redis -> WebSocket integration test, including membership removal and empty-subscription behavior.
5. Add broker binding reconciliation and recovery tests for join/leave/removal failures.
6. Design encryption-key rotation/key-ring support and a KMS/secret-store deployment path.
7. Evaluate attachment encryption, streamed/range downloads, malware/content inspection, and per-user quotas.
8. Harden Docker deployment credentials/network exposure and add a production deployment checklist.
9. Add CI lint/type checks and resolve the passlib/argon2 deprecation warning.
10. Consider external audit-hash anchoring if the final report needs stronger tamper evidence.

## 8. Files changed

- `.env.example`
- `README.md`
- `backend/app/api/routes/messages.py`
- `backend/app/core/config.py`
- `backend/app/realtime/ws_manager.py`
- `backend/app/services/channel_service.py`
- `backend/app/services/message_service.py`
- `backend/tests/security/test_phase1_hardening.py`
- `docs/FINAL_MVP_STATUS.md`
- `docs/REQUIREMENTS_MAPPING.md`
- `docs/SECURITY.md`
- `docs/STABILIZATION_STATUS.md`
- `docs/TESTING.md`
- `REPOSITORY_ASSESSMENT.md`
- `SECURITY_HARDENING_PHASE1_REPORT.md`
