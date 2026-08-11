# Requirements Mapping

This table maps the final university MVP to concrete implementation, tests/verifiers, and presentation evidence. “Complete” means complete for the defined project scope, not enterprise production certification.

| Requirement | Status | Implementation evidence | Test/verification evidence | Supervisor demo |
|---|---|---|---|---|
| Create channels/topics | Complete | `backend/app/api/routes/channels.py`, `backend/app/services/channel_service.py`, `Channel`/membership models, frontend create/list/details pages | `backend/tests/test_p0_requirements.py`, channel/security suites, `scripts/verify_demo_flow.py` | A creates a private channel and shows safe slug/settings. |
| Publish to a channel | Complete | `backend/app/api/routes/messages.py`, `backend/app/services/message_service.py`; authorization, validation, encryption, message/outbox/event transaction | P0/security/message tests and demo verifier | A publishes text/media to the channel. |
| Automatic subscriber delivery | Complete for defined MVP | Transactional outbox, `worker/worker_app/outbox_runner.py`, RabbitMQ `ex.channels`, per-user queues, Redis fanout, `backend/app/realtime/`, frontend WebSocket hook | `backend/tests/test_delivery_reliability.py`, Phase 3/4/7 regressions, `verify_demo_flow.py`, `verify_approval_flow.py`, release-candidate scenario | B receives without refreshing; show worker/RabbitMQ evidence. |
| Offline sync/backfill | Complete | PostgreSQL message history and delivery/sync routes; WebSocket is not authoritative | `backend/tests/test_delivery_reliability.py`, Phase 4 sync regressions, `verify_demo_flow.py`, release-candidate scenario | Disconnect B, publish, reconnect/refresh, recover message. |
| Channel/subscriber management | Complete | `memberships.py`, `channel_service.py`, frontend channel details; join/leave/invite/approve/remove/role/permission flows | P0 plus Phase 5/6/7/10 tests; approval verifier | Invite/approve B, list members, change/remove membership. |
| RabbitMQ publish/subscribe architecture | Complete for defined MVP | Topic exchange/topology in backend and worker, durable bounded queues/bindings, versioned desired binding projection, confirms/acks | Delivery/reliability and routing regressions; live demo/release-candidate verifier | Explain DB/outbox -> RabbitMQ -> worker -> Redis path and optionally show management/logs. |
| Realtime WebSockets | Complete for defined MVP | One-use ticket route/service, `ws_manager.py`, Redis pub/sub/control, frontend `use-websocket.tsx` | Phase 4/8/10 tests, demo and approval verifiers | Keep B connected and show automatic delivery/presence. |
| Authentication/session security | Complete university baseline | Argon2, session-bound JWTs, rotating refresh/replay detection, browser cookie/Origin/CSRF flow, revocation, one-use WebSocket tickets | Phase 2/5/7/8/10 security suites | Login, session page/logout, optional replay/revocation explanation. |
| Channel-level RBAC and private access | Complete | Service-level owner/admin/member/pending/outsider checks before reads, writes, sync, events, and decrypt | P0 and Phase 1/4/5/6/7/8 tests; demo/release-candidate outsider checks | C is denied private history and upload; removed B loses access. |
| Protected attachments | Complete | `download_service.py`, upload routes in `messages.py`, `upload_encryption.py`, protected frontend media | P0 plus Phase 1/4/5/6/7/9 tests; release-candidate upload scenario | B downloads exact media; C receives `403`; show encrypted storage status. |
| Message/upload encryption at rest | Complete university baseline; operational key custody remains | `backend/app/core/encryption.py`, `upload_encryption.py`, `backend/app/db/crypto_tool.py`, migration `0022_phase9_upload_encryption.py` | `test_phase9_data_protection.py`, crypto status/rotation commands, release-candidate ciphertext checks | Show v2 envelope/status and exact authorized download; state not E2EE. |
| Email verification and invite identity | Complete university baseline | `email_verification_service.py`, delivery service, auth/profile routes/UI, migration `0023_phase10_email_verification.py` | `test_phase10_identity_presence.py`, captured-SMTP release-candidate scenario | Verify B's exact email before unresolved invite acceptance. |
| Distributed presence | Complete as non-authoritative metadata | Redis per-connection leases, heartbeat/reaper, aggregate transitions | `test_phase10_identity_presence.py`, cross-backend release-candidate scenario | Two sockets keep online until final socket closes. |
| Event/activity log | Complete | `event_service.py`, events/channel/admin APIs, frontend Event Log/admin table | `test_event_integrity.py`, security tests, demo/release-candidate checks | Show channel/member/message/security activity. |
| Event hash-chain integrity | Complete; legacy rows need explicit initialization | `event_integrity_service.py`, event integrity fields/migration `0013_event_integrity.py`, backfill tool | `test_event_integrity.py`, backfill dry-run, release-candidate scenario | Click Verify integrity and explain ordered per-scope continuity. |
| Mandatory Merkle Tree | Implemented and validated | `backend/app/services/merkle_service.py`, `backend/app/services/merkle_audit_service.py`, `backend/app/db/merkle_tool.py`, `backend/alembic/versions/0024_phase11_merkle_audit.py`, superadmin Merkle API/UI, isolated `merkle-checkpoint` profile | `backend/tests/security/test_phase11_merkle_integrity.py`, `scripts/demo_merkle_integrity.py`, release-candidate proof/anchor checks | Create signed checkpoint, verify one inclusion proof/signature/chain, then show tampered proof copy fails. |
| Delivery/event management interfaces | Complete for MVP operations | Frontend Delivery Monitor, channel Event Log, superadmin overview/events/users/channels, retry controls | `test_delivery_reliability.py`, `test_superadmin.py`, Phase 11 admin API tests | Inspect outbox status/events; optionally retry a disposable failed item. |
| Dockerized run/deployment | Complete for development/demo and single-host reference | Three Compose files, backend/worker/frontend Dockerfiles, Nginx, PostgreSQL runtime-role init | Compose renders, image builds, Nginx syntax, release verifier, fresh migration/stack validation | Show healthy services and explain direct vs hardened vs production profiles. |

## Merkle requirement explanation

```text
Audit event -> SHA-256 event hash -> per-scope hash chain
            -> Merkle leaf/tree/root -> Ed25519-signed linked checkpoint
            -> compact proof / optional independently retained anchor
```

- The hash chain preserves order within a scope.
- The Merkle tree proves one event belongs to a batch with logarithmic proof size.
- The signature prevents a database-only attacker from replacing the root without the signing key.
- The exported anchor detects rollback only after independent retention.

See [Security](SECURITY.md#audit-hash-chains-and-mandatory-merkle-tree), [Deployment](DEPLOYMENT.md#merkle-checkpoint-operations), and [Demo Guide](DEMO_GUIDE.md#mandatory-merkle-demonstration).

## Remaining non-MVP gaps

Automated browser tests, sustained outage/load tests, external SMTP deliverability, managed KMS/HSM, automatic independent anchor custody, managed backup/restore, and multi-host HA remain outside the final university scope.
