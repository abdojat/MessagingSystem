# Final Demo Checklist

Target: 10–15 minutes. Rehearse with disposable demo data and keep the normal
feature demo separate from safe release verification.

## Before the Supervisor Arrives

- Copy `.env.example` to the untracked `.env`, replace development secrets, and
  start the demo stack with `docker compose up -d --build`.
- Confirm `docker compose ps -a` shows PostgreSQL, RabbitMQ, Redis, backend,
  worker, and frontend ready/running.
- Run `python scripts/verify_release.py` in advance. It uses uniquely named
  disposable test containers and does not modify application volumes.
- Prepare three browser profiles: User A (owner/publisher), User B
  (subscriber), and User C (outsider).
- If showing the production profile, prepare deployment-owned secrets and TLS
  files outside the repository; do not display their contents.

## 10–15 Minute Demonstration

1. **Architecture (1 minute).** Explain that this is a distributed
   publish/subscribe system: PostgreSQL is authoritative; the worker relays the
   transactional outbox through RabbitMQ; Redis bridges realtime delivery to
   WebSockets; REST sync/backfill covers missed events.
2. **Identity and topic management (2 minutes).** Register/login A and B. A
   creates a private channel/topic. Show its safe slug and channel details.
3. **Subscriber workflow (2 minutes).** A creates an invite for B. For the full
   identity proof, show an unresolved email invite denied before mailbox
   verification and accepted after the captured/SMTP fragment is confirmed.
4. **Live publish/subscribe (2 minutes).** Keep B's channel open. A publishes a
   distinctive message. Show B receives it without refreshing, then refresh and
   show persisted history. Mention the exact path: DB/outbox -> RabbitMQ ->
   worker -> Redis -> WebSocket.
5. **Protected attachment and offline recovery (2 minutes).** A publishes a
   small attachment. B downloads the exact bytes; C is denied. Publish another
   message while B is disconnected, reconnect, and show REST sync/backfill.
6. **Security and audit (2 minutes).** Show the Event Log and its SHA-256 chain
   integrity result. Remove B and show protected history is denied. Explain that
   message/upload encryption is server-side encryption at rest, not E2EE.
7. **Mandatory Merkle proof (2–3 minutes).** Create a signed checkpoint, run the
   demonstration below, and point out the root, selected event/leaf, sibling
   path, Ed25519 signature, linked checkpoint chain, valid proof, and expected
   tampered-copy failure.

## Merkle Demonstration Commands

The production profile isolates the signing private key to the explicit
maintenance service:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml \
  --profile integrity run --rm merkle-checkpoint

docker compose --env-file .env.production -f docker-compose.production.yml \
  --profile integrity run --rm --entrypoint python merkle-checkpoint \
  -B scripts/demo_merkle_integrity.py
```

Expected visible results: event hash PASS, Merkle inclusion PASS, checkpoint
hash PASS, Ed25519 signature PASS, checkpoint chain PASS, and `Tampered proof:
FAILED (expected)`. Never display the signing private key. Explain that an
exported latest anchor detects rollback only after it is retained independently;
this is tamper evidence, not blockchain or immutable storage.

## Useful Evidence Commands

```bash
docker compose ps -a
docker compose logs --tail=100 backend worker
docker compose exec postgres psql -U postgres -d channels \
  -c "select status, count(*) from outbox group by status order by status;"
docker compose exec backend python -B -m app.db.crypto_tool status
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```

For a disposable production stack, the comprehensive data-creating verifier is:

```bash
python scripts/verify_release_candidate.py --base-url http://localhost:8000/v1
```

Use its `--mailpit-url`, `--secondary-base-url`, and `--uploads-base-dir`
options only when those disposable fixtures are configured.

## Five-Minute Fallback Demo

1. Show `docker compose ps -a` and the architecture diagram.
2. A creates a channel; B joins; A publishes; B receives the message live.
3. Refresh B to prove persistence and show C denied from the private channel or
   attachment.
4. Open Event Log and show hash-chain integrity.
5. Run `scripts/demo_merkle_integrity.py` through the integrity profile and show
   the valid signed inclusion proof plus expected tampered-copy failure.

## Statements to Keep Precise

- PostgreSQL—not RabbitMQ or Redis—is the source of truth.
- Ordering is per channel; there is no global message-order guarantee.
- RabbitMQ/Redis/WebSocket provide asynchronous realtime delivery; REST sync is
  durable recovery.
- Browser access tokens are memory-only; rotating refresh credentials are
  `HttpOnly`, `Secure`, `SameSite` cookies protected by Origin/CSRF checks.
- Messages and uploads are encrypted at rest but remain server-decryptable.
- Signed Merkle checkpoints make audit modification detectable under the stated
  key/anchor assumptions; they do not make the database immutable.
- The production profile is a validated single-host university-MVP boundary,
  not HA, external-KMS, load-tested, or production-certified infrastructure.
