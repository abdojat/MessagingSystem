# Final MVP Status

Last updated: 2026-08-11

## Final status

The system is functionally complete for the defined university MVP. It remains a distributed publish/subscribe messaging system, not merely a chat UI: PostgreSQL persists topics, memberships, messages, outbox state, and audit evidence; RabbitMQ routes committed publications; the worker bridges online delivery through Redis; WebSockets provide live updates; REST history/sync recovers missed messages.

## Complete for the defined scope

- Registration, login, Argon2 password storage, session-bound JWTs, refresh rotation/replay detection, browser cookie/CSRF flow, logout/revocation, and single-use WebSocket tickets.
- Public/private channel creation, safe slugs, join policies, invitations, approvals, roles, permissions, removal, update, and deletion/suspension controls.
- Persistent encrypted text/media messages, transactional outbox, RabbitMQ topic routing, worker retries/dead-letter visibility, Redis fanout, realtime WebSockets, and offline backfill.
- Protected upload metadata/content endpoints, streamed validation, authenticated AES-GCM storage, authorized bounded download/decryption, and profile/message media use.
- Event/activity logging, delivery monitoring, per-scope SHA-256 event hash chains, and superadmin audit/operations interface.
- Email verification tied to exact email identity and distributed multi-socket presence as non-authoritative metadata.
- Supervisor-mandated Merkle trees: bounded batches, compact inclusion proofs, Ed25519-signed linked checkpoints, offline verification, and manual external-anchor export/verification.
- Development, proxy-bounded hardened demo, and single-host production-oriented Compose profiles.
- Current architecture, development, deployment, security, testing, troubleshooting, demo, and requirement documentation.

## Operationally bounded or mostly complete

- RabbitMQ and Redis realtime buffers are intentionally bounded; PostgreSQL/REST is the durable recovery guarantee.
- Worker startup narrowly migrates retained managed user queues that predate bounded arguments; a queue with active consumers or an unrelated topology mismatch still requires operator coordination.
- Dead-letter mirroring to RabbitMQ is best effort after authoritative PostgreSQL state is committed.
- Merkle checkpoint creation and independent anchor retention are explicit operator/scheduled tasks, not automatic application work.
- The single-host production-oriented profile establishes a credible boundary but leaves certificate, secret, backup, monitoring, and recovery operations to the deployer.

## Known limitations

- Encryption is server-side at rest, not E2EE.
- No managed KMS/HSM, automatic key/anchor custody, immutable storage, blockchain, or third-party notarization.
- No multi-host HA, disaster-recovery certification, public-certificate automation, sustained load/slow-reader certification, or complete live outage matrix.
- No automated browser end-to-end or visual RTL suite; frontend validation is compile/build plus manual/integration verification.
- External SMTP provider deliverability, bounce handling, MFA, account recovery, centralized monitoring/logging, and managed backups remain operator/future work.

## Evidence

- [Requirements Mapping](REQUIREMENTS_MAPPING.md)
- [Stabilization Status](STABILIZATION_STATUS.md)
- [Testing](TESTING.md)
- [Final Repository Handoff](../FINAL_REPOSITORY_HANDOFF.md)
- [Historical Security Reports](../reports/security/README.md)

No further implementation/security phase is planned. Future work should be driven by an actual deployment or university requirement.
