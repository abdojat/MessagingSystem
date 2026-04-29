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
Expected: `2 passed`.

## 4) Run Demo Verifier Script
```bash
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```
The script now waits for API health before running flow checks.

## 5) Manual UI Demo (Instructor)
1. Open `http://localhost:3000`.
2. Register/login User A.
3. Register/login User B (incognito or second browser profile).
4. User A creates a channel.
5. User B joins/subscribes.
6. User A publishes a message.
7. User B receives/reads message.
8. Open channel details -> Event Log panel.
9. Show unauthorized behavior:
   - Use a private channel where non-member read/publish is denied.
10. Show ciphertext at rest:
```bash
docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"
```
Expected: `content_text` is Fernet ciphertext (e.g., starts with `gAAAA`), not plaintext.

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
- [ ] Unauthorized access denied
- [ ] DB stores ciphertext, not plaintext
- [ ] README explains full run flow
