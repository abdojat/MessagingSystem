# Requirements Mapping

| Official requirement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Create channels/topics | Complete | `POST /v1/channels`, slug auto-generation/collision handling, safe identifier validation, and database constraints | User A creates a channel in UI/API |
| Allow subscribers to publish and receive automatically | Complete | Membership join + text/media message publish + realtime pipeline (RabbitMQ/Redis/WebSocket + REST retrieval). Backend tests verify attachment-only photo/video/audio messages are syncable by a subscriber and that media attachment references are validated before publish. `scripts/verify_demo_flow.py` opens User B's WebSocket before join, explicitly subscribes/resyncs after join, checks live WebSocket delivery, and checks REST backfill fallback. Approval-after-connect is covered by `scripts/verify_approval_flow.py` | User B joins or is approved, User A publishes text and protected media, User B receives |
| Interfaces for managing channels and subscribers | Complete | Frontend channel list/details, create dialog, membership actions, channel settings, approval route, approval verifier, and a permission-aware reusable generic invite-link action on the details page for every visibility/join-policy combination. Targeted invites remain one-use; generic links remain valid until revoked/expired/deleted. Phase 6 binds existing email targets to immutable account IDs; Phase 10 provides authenticated mailbox proof, profile verification controls, and `/verify-email` for unresolved pre-registration targets. | Open channel details as its owner, create/copy a reusable invite link, accept it as two users, revoke it, and show a later acceptance denied. For an unresolved email invite, show denial while Unverified, request/open the captured or SMTP link, then accept after the profile reports Verified. |
| Security: encryption, authentication, permissions | Complete for university MVP; production-oriented single-host boundary validated | Session-bound access JWTs remain memory-only in the browser; refresh tokens use rotating `HttpOnly`, `Secure`, `SameSite` cookies with exact-Origin and double-submit CSRF validation. Phase 9 provides versioned message/upload encryption and rotation. Phase 10 adds hash-only exact-email verification challenges, authenticated confirmation, TLS-SMTP production validation, and email-change invalidation. Backend authorization occurs before decryption; presence remains non-authoritative metadata. Phase 1-10 regressions and schema upgrades provide evidence. | Show an Unverified profile becoming Verified through the fragment link, deny the same token twice/under another account, then demonstrate encrypted message/upload storage and outsider denial. Public certificate lifecycle, external KMS/HSM, MFA, multi-host HA, and browser automation remain limitations. |
| Event log for tracking activity | Complete | Channel events API/UI plus global superadmin audit API `GET /v1/admin/events` and bilingual `/app/admin` console; raw payloads are replaced by typed allowlisted display details; denied superadmin access and all administrative mutations are audited | Open channel Event Log, then superadmin console -> All audit events; filter by category/actor and show human-readable details |

## Phase 12 Final Validation Map

The official requirements above were exercised together on a fresh disposable
production-profile stack on 2026-08-11. The deterministic scenario in
`scripts/verify_release_candidate.py` created identities and a private channel,
completed a real locally captured SMTP verification and pre-registration invite,
published through PostgreSQL outbox -> RabbitMQ -> worker -> Redis -> WebSocket,
recovered an offline message through `/sync`, verified protected encrypted upload
storage and outsider denial, proved two-backend aggregate presence, exercised
refresh replay/logout, and verified event integrity/removal denial. The complete
backend suite passed 352 tests and the requested focused security matrix passed
213 tests.

| Supervisor feature | Final status | Concrete implementation and verification |
|---|---|---|
| Topics/channels | Complete | `backend/app/api/routes/channels.py`, `backend/app/services/channel_service.py`, frontend channel UI, final E2E |
| Publish/subscribe delivery | Complete for the defined MVP | `backend/app/services/message_service.py`, transactional outbox, `worker/worker_app`, RabbitMQ/Redis/WebSocket, REST sync, final live/offline E2E |
| Subscriber management | Complete | `backend/app/api/routes/memberships.py`, invite/approval/add/remove/role flows, real verified-email invite E2E |
| Security | Complete for the defined university MVP | Session-bound auth, RBAC, browser refresh/CSRF, broker-safe IDs, encrypted message/upload storage, production boundary, focused/full regressions; deployment limitations remain documented |
| Event/activity log | Complete | Channel/global APIs and UI, per-scope SHA-256 chains, final event/integrity E2E |
| Mandatory Merkle Tree | Implemented and validated | `backend/app/services/merkle_service.py`, `backend/app/services/merkle_audit_service.py`, `backend/app/db/merkle_tool.py`, `backend/alembic/versions/0024_phase11_merkle_audit.py`, `backend/tests/security/test_phase11_merkle_integrity.py`, admin UI/API, and `scripts/demo_merkle_integrity.py`; signed checkpoint, inclusion proof, linked chain, tampered-copy rejection, offline proof/anchor, and database-history anchor verification passed |

## Platform Administration Enhancement

| Enhancement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Global superadmin oversight and controls | Mostly complete | `users.is_superadmin/is_active`; migration `0015_superadmin_controls`; safe environment bootstrap; `AdminService`; guarded/no-store `/v1/admin/overview`, `/events`, `/users`, and `/channels`; global delivery-monitor scope; bilingual frontend console with ranked search, filters, typed event display, confirmation gates, and selectable pagination; focused regression tests | Login as configured superadmin, search/filter global events, change page size, revoke a test user's sessions after confirmation, and suspend/restore a disposable channel |

The enhancement is intentionally bounded: superadmins administer accounts, channels, audit evidence, and delivery state but do not receive implicit access to private message bodies. MFA and automated third-party anchor custody remain future work; Phase 11 provides manual signed-anchor export and verification.

## Advanced Reliability Enhancement

| Enhancement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Delivery Reliability Upgrade v1: outbox retry/dead-letter monitoring | Mostly complete | Outbox status fields and migration `0012_delivery_reliability`; worker retry/dead-letter logic; versioned `broker_binding_states` plus generation snapshots from migration `0019`; stale opposite-command rejection; obsolete-key removal; reconnect/global reconciliation; bounded per-user queues; paced Redis fanout retries; RabbitMQ DLQ topology; admin Delivery Monitor; Phase 3/4 tests; supervisor verifier `scripts/verify_delivery_reliability.py` | Open Delivery Monitor as a channel owner/admin; inspect counters; run delivery verifier for normal publish plus controlled dead-letter/manual retry; explain PostgreSQL desired state and REST sync recovery |

This enhancement strengthens the distributed-system reliability story, but it is not one of the official minimum requirements. PostgreSQL outbox state remains authoritative; the RabbitMQ DLQ is an operational mirror when the worker can publish to it.

## Advanced Security/Integrity Enhancement

| Enhancement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Event Integrity Upgrade v1: tamper-evident audit hash chain | Mostly complete | Event columns and migration `0013_event_integrity`; canonical hash-chain service in `backend/app/services/event_integrity_service.py`; event logging integration in `backend/app/services/event_service.py`; worker delivery-event hashing in `worker/worker_app/outbox_runner.py`; verification endpoint `GET /v1/channels/{id}/events/integrity`; backfill script `scripts/backfill_event_integrity.py`; frontend Event Log integrity badge/check; tests in `backend/tests/test_event_integrity.py` | Open channel details -> Event Log -> Verify integrity; use the Docker backfill dry-run command before any real legacy backfill |
| Phase 11 global Merkle audit checkpoints | Mostly complete operationally | Migration `0024`; domain-separated SHA-256 tree/proofs in `backend/app/services/merkle_service.py`; atomic signed checkpoint/anchor service; Ed25519 public-key ring and isolated signing profile; `merkle_tool` status/checkpoint/verify/proof/offline/anchor commands; superadmin no-store APIs and bilingual UI; deterministic demo and focused PostgreSQL/concurrency/tamper tests | Run checkpoint/status/verify; verify one proof in the admin UI and offline; tamper only a proof copy and show failure; export the latest anchor to separate storage |

These are advanced integrity enhancements. Per-scope chains retain chronology;
the real Merkle tree supplies compact membership proofs; signed checkpoint roots
resist database-only rewriting without the Ed25519 private key. The export
command is not automatic external notarization: rollback/tail-deletion evidence
exists only after the latest anchor is copied to and protected in independent
storage. The design is tamper-evident, not immutable and not a blockchain.

## Data Protection Enhancement

| Enhancement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Phase 9 versioned at-rest encryption and rotation | Mostly complete operationally | `backend/app/core/encryption.py`, `upload_encryption.py`, `crypto_tool.py`, migration `0022_phase9_upload_encryption`, production key-ring configuration, and `test_phase9_data_protection.py` (35 focused tests) cover active/historical keys, legacy conversion, authenticated streaming uploads/downloads, crash recovery, status, rotation, and old-key removal | Run status; publish a unique text marker and upload; inspect DB/file storage for absence; download exactly; rotate disposable data to a new active ID; remove the old test key and re-read |

This is server-side encryption at rest, not E2EE. The backend and maintenance
process possess keys and can decrypt authorized data. External KMS/HSM-backed
key custody, automated rotation scheduling, physical secure erasure, and backup
encryption/lifecycle remain operator/future work.

## Identity and Presence Enhancement

| Enhancement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Phase 10 email verification and distributed presence | Mostly complete operationally | Migration `0023`; `EmailVerificationService`; capture/console/SMTP transports; authenticated API and fragment frontend; Redis Lua leases/global expiration index; WebSocket heartbeat/reaper; 25 focused tests using PostgreSQL and real Redis | Request a verification email, open the link while signed in, show Verified and invite acceptance; open two tabs/sessions, close one and show aggregate online state remains until the final socket closes |

Provider SMTP availability and browser automation remain operational/testing
limitations. Presence is ephemeral UI/realtime metadata and is deliberately not
used for authentication, membership, message access, or invitation decisions.
