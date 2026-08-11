# Final Demo Checklist

## Before the supervisor arrives

- [ ] Use disposable demo data and three browser profiles (owner, subscriber, outsider).
- [ ] Confirm `.env` has unique demo JWT/data-encryption values; keep private keys off screen.
- [ ] Run `docker compose up -d --build` and confirm `docker compose ps -a` is healthy/running.
- [ ] Run `python scripts/verify_release.py` in advance.
- [ ] Run `python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1` against the demo stack.
- [ ] Prepare the session-local Merkle demo key variables or the isolated production integrity profile.

## 10-15 minute path

- [ ] Architecture: PostgreSQL -> outbox -> RabbitMQ -> worker -> Redis -> WebSocket; REST sync recovers missed data.
- [ ] A logs in and creates a private channel/topic.
- [ ] B joins/is approved; show member management.
- [ ] A publishes; B receives live without refresh.
- [ ] Refresh/reconnect B; show persistence/offline sync.
- [ ] Publish a protected attachment; B succeeds and C receives `403`.
- [ ] Show `crypto_tool status` and ciphertext envelope evidence; call it server-side encryption at rest.
- [ ] Show Event Log and per-scope hash-chain verification.
- [ ] If time permits, show email verification and multi-socket aggregate presence.
- [ ] Run the mandatory Merkle demo: event hash, inclusion, checkpoint hash, signature, and chain pass; tampered copy fails as expected.
- [ ] Explain independent anchor retention and current limitations.

## Five-minute fallback

- [ ] Architecture and healthy stack.
- [ ] Live A -> channel -> B publish/subscribe.
- [ ] Refresh persistence and outsider denial.
- [ ] Encrypted storage evidence.
- [ ] Signed Merkle proof plus tampered-copy failure.

## Close with accurate claims

- [ ] PostgreSQL is authoritative; realtime infrastructure is the delivery optimization.
- [ ] Ordering is per channel.
- [ ] Encryption is not E2EE.
- [ ] Merkle evidence is not blockchain/immutability.
- [ ] Production Compose is a single-host reference, not production certification.
