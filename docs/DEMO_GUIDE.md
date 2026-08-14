# Supervisor Demo Guide

This guide explains setup and presentation. Use [Final Demo Checklist](FINAL_DEMO_CHECKLIST.md) as the short checklist during the live session.

## Preparation

Use disposable demo accounts/data. From the repository root:

```bash
cp .env.example .env
# Replace JWT_SECRET and configure DATA_ENCRYPTION_ACTIVE_KEY_ID/DATA_ENCRYPTION_KEYS.
# Optionally configure a unique SUPERADMIN_* account before first startup.
docker compose up -d --build
docker compose ps -a
```

Wait for the backend to become healthy. Development URLs:

- UI: `http://localhost:3000`
- API/docs: `http://localhost:8000/v1`, `http://localhost:8000/docs`
- RabbitMQ management: `http://localhost:15672` (`guest` / `guest`, local only)

Prepare three browser profiles:

- User A: channel owner/publisher.
- User B: subscriber.
- User C: outsider used to prove denial.

Preflight the repository and application flow:

```bash
python scripts/verify_release.py
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```

The release verifier is safe/disposable. The demo verifier creates application data, so use the prepared demo stack.

## 10-15 minute demo

### 1. Architecture (1 minute)

Show the diagram in [Architecture](ARCHITECTURE.md). State:

> PostgreSQL is the durable source of truth. FastAPI commits the encrypted message, outbox row, and audit event. The worker publishes through RabbitMQ, consumes the online subscriber queue, and uses Redis to reach the backend WebSocket. REST history and sync recover missed messages.

### 2. Login and channel/topic management (1-2 minutes)

Register/login A, B, and C. As A, create a private channel and show its safe slug, join policy, and member-management page.

### 3. Subscriber workflow (1-2 minutes)

A creates an invite or approves B's join request. Show B becomes a member. Explain that existing-user targeted invitations bind to the user ID; an unresolved pre-registration email invite requires later verification of the exact target email.

If demonstrating mailbox proof, request verification from B's profile, read the development fragment URL from backend console/logs, open it while signed in as B, and show the profile becomes Verified before accepting the unresolved email invite.

### 4. Live publish/subscribe and persistence (2 minutes)

Keep B's channel open. A publishes a distinctive message. Show B receives it without refreshing. Refresh B and show the message is still present. Disconnect B, publish another message, reconnect, and show history/sync recovers it.

Optionally show worker logs or RabbitMQ management to make broker involvement visible:

```bash
docker compose logs --tail=100 worker
```

### 5. Protected attachment (1 minute)

A publishes a small photo/audio/video attachment. B downloads or opens the exact content. C attempts the private resource and receives `403 Forbidden`. Explain the path: streamed validation, AES-GCM encrypted storage, authorized bounded streaming decrypt.

### 6. Encryption evidence (1 minute)

Show storage status without printing secrets or plaintext:

```bash
docker compose exec backend python -B -m app.db.crypto_tool status
docker compose exec postgres psql -U postgres -d channels \
  -c "select id, left(content_text, 40), content_json from messages order by created_at desc limit 5;"
```

New text should use an `enc:v2:<key-id>:` envelope. State precisely that this is server-side encryption at rest, not end-to-end encryption.

### 7. Event log and authorization (1 minute)

Open Channel Details -> Event Log and run integrity verification. Show channel/member/message activity. Remove B or use C to show protected history remains denied. If legacy events are not initialized, explain that state honestly and use the documented dry-run before any real backfill.

### 8. Email verification and presence (optional 1 minute)

Show B's verified email state. With two tabs/sessions open, close one and show aggregate presence remains online until the final socket closes. Presence is metadata and never authorizes access.

### 9. Mandatory Merkle demonstration (2-3 minutes)

Run the prepared command in [Mandatory Merkle demonstration](#mandatory-merkle-demonstration). Point out the selected event, leaf index, sibling path length, Merkle root, signing key ID, valid event/root/checkpoint/signature/chain results, and the expected failure after changing a copy of one proof hash.

Explain:

- hash chain = ordered continuity inside one audit scope;
- Merkle tree = compact batch membership proof;
- signed checkpoint = database-only root replacement requires the external private signing key;
- independently retained anchor = rollback/tail-deletion evidence.

### 10. Close (30 seconds)

State the limitations: PostgreSQL is authoritative; ordering is per channel; encryption is server-side; the production profile is a single-host reference; independent anchor retention and deployment operations are operator responsibilities.

## Mandatory Merkle demonstration

With development/hardened automatic checkpointing enabled, first create or
trigger an audit event and open the Superadmin event table. A hashed row shows
**Pending checkpoint**. Watch `docker compose logs -f merkle-checkpointer`; the
startup/next cycle creates one or more bounded signed batches. Refresh the table
and show **Verify Merkle proof**, then open the proof. This demonstrates the
normal automatic path without giving FastAPI the private signing seed.

For a fast supervised run, `AUDIT_MERKLE_CHECKPOINT_INTERVAL_SECONDS=10` is the
minimum allowed test interval; restore the normal 300-second development value
afterward. The deterministic CLI demonstration below remains useful for showing
tamper rejection and anchor behavior.

Generate a dedicated demo key pair in a private terminal before the presentation:

```bash
docker compose run --rm backend python -B -m app.db.merkle_tool \
  generate-keypair --key-id audit-demo
```

Do not record or display the private seed. Put the three printed values into session-local environment variables, then pass only those variables to the one-shot container. Do not put the private seed in `.env`.

```bash
docker compose run --rm \
  -e AUDIT_MERKLE_SIGNING_KEY_ID \
  -e AUDIT_MERKLE_SIGNING_PRIVATE_KEY \
  -e AUDIT_MERKLE_PUBLIC_KEYS \
  backend python -B scripts/demo_merkle_integrity.py
```

Expected visible evidence:

```text
Event hash:              PASS
Merkle inclusion:        PASS
Checkpoint hash:         PASS
Ed25519 signature:       PASS
Checkpoint chain:        PASS
Tampered proof:           FAILED (expected)
```

The demo creates 16 dedicated audit events, checkpoints eligible events in bounded batches, and tampers only with an in-memory proof copy. It does not alter persisted evidence.

For the production-oriented profile, the isolated equivalent is:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml \
  --profile integrity run --rm --entrypoint python merkle-checkpoint \
  -B scripts/demo_merkle_integrity.py
```

## Five-minute emergency demo

1. Show the architecture and healthy Compose services.
2. A creates a channel; B joins; A publishes; B receives live.
3. Refresh B to prove persistence; show C denied from a private channel/upload.
4. Show encrypted message status/storage evidence.
5. Run the signed Merkle demo and show valid inclusion/signature/chain plus expected tampered-copy failure.

Merkle stays in the short path because it is supervisor-mandated.

## Recovery options during a live demo

- If WebSocket delivery is delayed, show the persisted message through refresh or `/sync`, then inspect `docker compose logs --tail=100 backend worker`.
- If RabbitMQ management is unavailable under the hardened profile, use worker logs; the management port is intentionally private there.
- If SMTP is unavailable, use development console delivery and state that production requires TLS/STARTTLS SMTP.
- If no event is eligible for a Merkle proof, run the deterministic demo; it creates its own audit events.
- If a signing key is not configured, do not invent a result. Use the prepared session-local demo key variables or the production integrity profile.

## Statements to keep precise

- PostgreSQL, not RabbitMQ or Redis, is the source of truth.
- RabbitMQ/Redis/WebSockets provide asynchronous realtime delivery; REST sync is durable recovery.
- Ordering is per channel, not global.
- Browser access tokens are memory-only; rotating refresh credentials use protected cookies.
- Messages/uploads are encrypted at rest but remain server-decryptable.
- Signed Merkle checkpoints are tamper evidence under key/anchor assumptions, not immutable storage or blockchain.
- The production-oriented profile is a validated single-host reference, not HA or production certification.
