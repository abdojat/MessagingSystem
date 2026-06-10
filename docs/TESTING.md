# Testing

## Automated Tests
Backend P0 tests:
- `test_channel_creation_generates_slug_and_logs_event`
- `test_message_encryption_round_trip_and_authz_and_event`
- `test_upload_download_requires_channel_membership`
- `test_upload_storage_path_sanitizes_filename_and_stays_within_base_dir`
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

Legacy event backfill check:
```bash
python scripts/backfill_event_integrity.py --dry-run
```
The script groups events by `channel:<channel_id>` or `system`, computes hashes in chronological order, and reports what would be updated without committing.

Frontend typecheck:
```bash
cd frontend
npm run typecheck
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
- Join flow
- Publish flow
- Live WebSocket delivery to the subscriber when available
- REST `/sync` backfill when live delivery is unavailable
- Event log contains core events
- Event integrity can be checked from `GET /v1/channels/{id}/events/integrity` or the Event Log panel
- Private upload access is denied to an unauthorized user
- Final PASS/FAIL summary with visible step names and timeouts
The verifier does not currently force a RabbitMQ failure or DLQ transition; use the backend delivery reliability tests and worker logs for that path.
Note: the verifier is the best single proof of the pub/sub chain in this repo, but it is still a scripted demo flow rather than a CI-level full-stack integration suite.

## Manual Verification
- Frontend login/register/channel flows.
- Event log panel rendering.
- Ciphertext-at-rest SQL check.
- Unauthorized publish/read denial behavior.
- Private upload download denial for a non-member.

## Current Limitations
- Local Windows `npm run build` may fail with a local Node dependency resolution issue (`caniuse-lite/dist/unpacker/agents`); Docker frontend build succeeds and is the verified path for demo readiness.
- No dedicated frontend lint script currently exists (`npm run lint` unsupported).
- `scripts/ws_client.py` is still useful for a standalone socket check, but the main demo verifier now covers the end-to-end proof path with live WebSocket delivery plus REST backfill fallback.
- There is no dedicated CI broker/WebSocket integration test yet.
- Delivery reliability tests cover database outbox transitions and admin APIs, but they mock AMQP publish success/failure rather than exercising a real RabbitMQ outage.
