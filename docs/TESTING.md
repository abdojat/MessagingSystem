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
- Private upload access is denied to an unauthorized user
- Final PASS/FAIL summary with visible step names and timeouts
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
