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
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```
Choose a safe ID such as `demo-key`, paste the value into a one-entry
`DATA_ENCRYPTION_KEYS` JSON object, and set `DATA_ENCRYPTION_ACTIVE_KEY_ID` to
that ID in `.env`. Replace `JWT_SECRET` with a non-default demo secret.

Start and inspect the stack:
```bash
docker compose config
docker compose up -d --build
docker compose ps -a
```

Optional recommended proxy-bounded path (use this instead of the commands above,
not at the same time with the same project volumes):

```bash
docker compose -f docker-compose.hardened.yml config
docker compose -f docker-compose.hardened.yml up -d --build
```

Open `http://localhost:8080`; only Nginx is published in this topology. The
direct Compose path remains easier for showing RabbitMQ management locally.

Optional production-boundary demonstration (separate project/volumes):

```bash
cp .env.production.example .env.production
# Replace every placeholder and provide external TLS_CERT_PATH/TLS_KEY_PATH.
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yml ps -a
```

Use a trusted certificate for a real deployment. A disposable self-signed
certificate is acceptable only for local validation and must remain outside the
repository. Show that HTTP redirects to HTTPS, `/health` is minimal,
`/v1/ready` and `/openapi.json` return 404 through Nginx, browser security
headers appear on HTTPS, and only ports 80/443 have host mappings. Do not confuse
Docker's internal `5432/tcp`/`6379/tcp` display with host publication; a host
binding contains `->` and can also be verified with `docker inspect`.

Production backend startup does not migrate or bootstrap a superadmin. The
one-shot `migrate` dependency must exit 0. If an initial admin is required, set
the bootstrap values temporarily and run:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml \
  --profile bootstrap run --rm bootstrap-superadmin
```

Then remove the bootstrap password from the untracked environment. The normal
supervisor feature demo remains easier through development Compose; the
production profile demonstrates the deployment boundary rather than exposing
RabbitMQ management UI.

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
- Finalized upload storage contains authenticated ciphertext, while authorized download reproduces the original file.

## 1) Start Services
```bash
cp .env.example .env
# set DATA_ENCRYPTION_ACTIVE_KEY_ID and DATA_ENCRYPTION_KEYS in .env
# optional initial admin: set SUPERADMIN_USERNAME and a unique 12+ character SUPERADMIN_PASSWORD
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
7. User A opens Channel Details and clicks **Create and copy invite link**. The generic link is reusable until revoked or expired and is available to the owner for public/private channels with any join policy; targeted invites remain one-use. Existing-account email targets bind to that account ID. For a pre-registration email target, show the future account as **Unverified**, request verification from Profile, open the configured development-capture/SMTP fragment link while signed in, then show **Verified** before accepting the invite.
8. User B opens the copied link and accepts the invitation (or joins/subscribes through the configured join flow).
9. User A publishes a text message.
10. User A uses the paperclip composer button to attach and publish a small photo, video, or audio file; caption text is optional.
11. User B receives/reads the text and media messages.
12. Open channel details -> Event Log.
13. Click Verify integrity and show `Audit integrity: Verified`.
    - If the database contains pre-upgrade legacy events, run the canonical Docker backfill command first or explain the Not initialized state honestly.
    - Dry-run first:
      ```bash
      docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"
      ```
    - Real backfill when intentional:
      ```bash
      docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py"
      ```
14. Open the Delivery Monitor from User A's Profile page.
    - Normal demo state should show published/pending counters and empty failed/dead-lettered tables.
    - If a delivery has failed in the environment, use the per-row Retry button or Retry all button to move it back to pending.
    - Worker logs show retry scheduling and dead-letter transitions when RabbitMQ publish failures occur.
15. Show unauthorized behavior:
   - Use a private upload download blocked for User C.
   - Optionally show a private channel where non-member read/publish is denied.
16. Show ciphertext at rest:
```bash
docker compose exec postgres psql -U postgres -d channels -c "select id, left(content_text, 40), content_json from messages order by created_at desc limit 5;"
docker compose exec backend sh -lc "cd /app && python -m app.db.crypto_tool status"
```
Expected: new text starts with `enc:v2:<key-id>:` and status reports no
plaintext/legacy/unreadable message or upload storage. Do not print keys or
message plaintext. For a disposable upload marker proof, inspect only that the
unique marker is absent from the finalized storage file, then show the
authorized browser download matches it.
17. Optional: open the RabbitMQ management UI or worker logs if available to show the broker path and the `q.dead.messages` queue.
18. Optional superadmin proof:
   - Log in with the explicitly bootstrapped superadmin account and open the shield link (`/app/admin`).
   - Show that the global event table includes system and cross-channel events.
   - Revoke a disposable user's sessions, then demonstrate that their next protected request/login is blocked if the account is deactivated.
   - Suspend and restore a disposable channel, and show the corresponding audit events.
   - Explain that the superadmin does not automatically read private message bodies.

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
- [ ] Normal user cannot open `/app/admin`; superadmin can see global audit events and perform audited controls
- [ ] Unauthorized access denied
- [ ] Unauthorized upload access denied
- [ ] DB stores ciphertext, not plaintext
- [ ] README explains full run flow
