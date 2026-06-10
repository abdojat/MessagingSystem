# Demo Guide

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

## 5) Manual UI Demo (Instructor)
1. Open `http://localhost:3000`.
2. Register/login User A.
3. Register/login User B (incognito or second browser profile).
4. Register/login User C in a third window or separate profile.
5. User A creates a channel.
6. User B joins/subscribes.
7. User A publishes a message.
8. User B receives/reads message.
9. Open channel details -> Event Log panel.
10. Open the sidebar Delivery Monitor as User A.
    - Normal demo state should show published/pending counters and empty failed/dead-lettered tables.
    - If a delivery has failed in the environment, use the per-row Retry button or Retry all button to move it back to pending.
    - Worker logs show retry scheduling and dead-letter transitions when RabbitMQ publish failures occur.
11. Show unauthorized behavior:
   - Use a private upload download blocked for User C.
   - Optionally show a private channel where non-member read/publish is denied.
12. Show ciphertext at rest:
```bash
docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"
```
Expected: `content_text` is Fernet ciphertext (e.g., starts with `gAAAA`), not plaintext.
13. Optional: open the RabbitMQ management UI or worker logs if available to show the broker path and the `q.dead.messages` queue.

Useful delivery reliability checks:
```bash
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
- [ ] Delivery Monitor loads for a channel owner/admin
- [ ] Unauthorized access denied
- [ ] Unauthorized upload access denied
- [ ] DB stores ciphertext, not plaintext
- [ ] README explains full run flow
