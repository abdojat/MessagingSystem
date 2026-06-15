# Demo Guide

## Golden Demo Path

Run these commands from the repository root unless a step says otherwise.

Optional clean reset, destructive:
```bash
# WARNING: this deletes local Docker database, broker, and upload volumes.
docker compose down -v
```

Prepare environment:
```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Paste the generated value into `MESSAGE_ENCRYPTION_KEY` in `.env`. Replace `JWT_SECRET` with a non-default demo secret.

Start and inspect the stack:
```bash
docker compose config
docker compose up -d --build
docker compose ps -a
```

Run backend and frontend checks:
```bash
docker compose run --rm backend sh -lc "cd /app && PYTHONPATH=/app pytest -q"
cd frontend
npm run typecheck
npm run build
node -e "JSON.parse(require('fs').readFileSync('src/locales/en.json','utf8')); JSON.parse(require('fs').readFileSync('src/locales/ar.json','utf8')); console.log('locale json ok')"
cd ..
```

Run supervisor-safe verifiers:
```bash
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
python scripts/verify_approval_flow.py --base-url http://localhost:8000/v1
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/verify_delivery_reliability.py --base-url http://localhost:8000/v1"
```

Canonical event-integrity commands:
```bash
# Dry-run; safe for final demo.
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"

# Real backfill; use only when you intentionally want to initialize legacy event rows.
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py"
```

What to show the supervisor:
- User A creates a channel/topic.
- User B joins or is approved after a pending request.
- User A publishes and User B receives the message live.
- REST sync/backfill returns the same persisted message.
- Event Log shows channel, membership, approval, and message events.
- Audit integrity verifies initialized event rows.
- Delivery Monitor shows outbox status and manual retry behavior.
- The language switcher can show the same demo surfaces in English and Arabic, with Arabic using RTL layout.
- User C is blocked from private channel/upload access.
- PostgreSQL stores message ciphertext, not plaintext.

## 1) Start Services
```bash
cp .env.example .env
# set MESSAGE_ENCRYPTION_KEY in .env (recommended even for demo)
docker compose up -d --build
docker compose ps -a
```
Wait until backend status is healthy.

## 2) Run Migrations
```bash
docker compose run --rm backend sh -lc "alembic upgrade head"
```

## 3) Run Backend Tests
```bash
docker compose run --rm backend sh -lc "cd /app && PYTHONPATH=/app pytest -q"
```
Expected: backend regression tests pass; the current P0 slice includes upload authorization, routing-key-safe identifier validation, encryption, authorization, and smoke-flow checks.

## 4) Run Demo Verifier Script
```bash
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```
The script waits for API health before running flow checks and verifies the live publish/WebSocket/sync demo path, plus the unauthorized upload access check.
The current verifier intentionally opens User B's WebSocket before User B joins, then sends an explicit subscribe/resync after the join. This covers the join-after-connect edge case that can otherwise make demos look flaky.

## 5) Manual UI Demo (Instructor)
1. Open `http://localhost:3000`.
2. Use the language switcher to toggle between English and Arabic; confirm Arabic pages switch to RTL before continuing.
3. Register/login User A.
4. Register/login User B (incognito or second browser profile).
5. Register/login User C in a third window or separate profile.
6. User A creates a channel.
7. User B joins/subscribes.
8. User A publishes a text message.
9. User A uses the paperclip composer button to attach and publish a small photo, video, or audio file; caption text is optional.
10. User B receives/reads the text and media messages.
11. Open channel details -> Event Log.
12. Click Verify integrity and show `Audit integrity: Verified`.
    - If the database contains pre-upgrade legacy events, run the canonical Docker backfill command first or explain the Not initialized state honestly.
    - Dry-run first:
      ```bash
      docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"
      ```
    - Real backfill when intentional:
      ```bash
      docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py"
      ```
13. Open the Delivery Monitor from User A's Profile page.
    - Normal demo state should show published/pending counters and empty failed/dead-lettered tables.
    - If a delivery has failed in the environment, use the per-row Retry button or Retry all button to move it back to pending.
    - Worker logs show retry scheduling and dead-letter transitions when RabbitMQ publish failures occur.
14. Show unauthorized behavior:
   - Use a private upload download blocked for User C.
   - Optionally show a private channel where non-member read/publish is denied.
15. Show ciphertext at rest:
```bash
docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"
```
Expected: `content_text` is Fernet ciphertext (e.g., starts with `gAAAA`), not plaintext.
16. Optional: open the RabbitMQ management UI or worker logs if available to show the broker path and the `q.dead.messages` queue.

Developer-only tamper test:
```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"
```
Host command, optional when local PostgreSQL credentials match the Docker database:
```bash
python scripts/backfill_event_integrity.py --dry-run
```
For a real tamper demonstration, modify a non-production event payload directly in PostgreSQL, then click Verify integrity again. The UI should report Broken. Do not include manual database tampering in the normal supervisor demo unless asked.

Useful delivery reliability checks:
```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/verify_delivery_reliability.py --base-url http://localhost:8000/v1"
docker compose logs -f worker
docker compose exec postgres psql -U postgres -d channels -c "select status, count(*) from outbox group by status order by status;"
docker compose exec postgres psql -U postgres -d channels -c "select id, status, attempts, max_attempts, next_retry_at, dead_lettered_at from outbox order by created_at desc limit 10;"
```

## Final Acceptance Checklist
- [ ] Docker stack starts
- [ ] Migrations run
- [ ] Backend tests pass
- [ ] Frontend container builds
- [ ] Demo script passes
- [ ] User A can create channel
- [ ] User B can subscribe
- [ ] User A can publish
- [ ] User B can receive
- [ ] Event log shows activity
- [ ] Event integrity check shows Verified or an honestly explained Not initialized state
- [ ] Delivery Monitor loads for a channel owner/admin
- [ ] English/Arabic language switch works and Arabic renders RTL
- [ ] Unauthorized access denied
- [ ] Unauthorized upload access denied
- [ ] DB stores ciphertext, not plaintext
- [ ] README explains full run flow
