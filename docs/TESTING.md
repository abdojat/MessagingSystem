# Testing

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
- immediate closure of WebSockets connected to the current backend instance
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
The earlier 2026-06-19 isolated PostgreSQL run passed all seven original focused tests. After console hardening, the complete suite passed `68` tests against a disposable PostgreSQL 16 container; frontend typecheck and production build also passed. Use a dedicated test database because the shared fixture truncates its configured database between cases.

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
