# Testing

## Automated Tests
Backend P0 tests:
- `test_channel_creation_generates_slug_and_logs_event`
- `test_message_encryption_round_trip_and_authz_and_event`

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

## Demo Verification Script
```bash
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```
Verifies:
- User A/User B register+login
- Channel creation
- Join flow
- Publish flow
- Authorized plaintext retrieval
- Event log contains core events

## Manual Verification
- Frontend login/register/channel flows.
- Event log panel rendering.
- Ciphertext-at-rest SQL check.
- Unauthorized publish/read denial behavior.

## Current Limitations
- Local Windows `npm run build` may fail with a local Node dependency resolution issue (`caniuse-lite/dist/unpacker/agents`); Docker frontend build succeeds and is the verified path for demo readiness.
- No dedicated frontend lint script currently exists (`npm run lint` unsupported).
