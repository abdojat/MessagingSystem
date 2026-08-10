# Requirements Mapping

| Official requirement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Create channels/topics | Complete | `POST /v1/channels`, slug auto-generation/collision handling, safe identifier validation, and database constraints | User A creates a channel in UI/API |
| Allow subscribers to publish and receive automatically | Complete | Membership join + text/media message publish + realtime pipeline (RabbitMQ/Redis/WebSocket + REST retrieval). Backend tests verify attachment-only photo/video/audio messages are syncable by a subscriber and that media attachment references are validated before publish. `scripts/verify_demo_flow.py` opens User B's WebSocket before join, explicitly subscribes/resyncs after join, checks live WebSocket delivery, and checks REST backfill fallback. Approval-after-connect is covered by `scripts/verify_approval_flow.py` | User B joins or is approved, User A publishes text and protected media, User B receives |
| Interfaces for managing channels and subscribers | Complete | Frontend channel list/details, create dialog, membership actions, channel settings, approval route, approval verifier, and a permission-aware generic invite-link action on the details page for every visibility/join-policy combination. `test_owner_can_create_generic_invite_for_every_channel_kind` covers the backend matrix. | Open channel details as its owner, create/copy an invite link, and accept it as another user; show other membership actions and run the approval verifier |
| Security: encryption, authentication, permissions | Complete | Session-bound access JWTs; idle plus absolute session expiry; refresh-family replay detection; one-time Redis WebSocket tickets; distributed socket revocation; role/permission checks; Fernet encryption at rest; protected immutable streamed uploads; indexed attachment authorization; safe identifiers; grouped rate-limit fallback, message/protocol limits, and resource quotas; migrations `0015_superadmin_controls`, `0017_auth_session_hardening`, and `0018_phase3_abuse_hardening`; focused Phase 1/2/3 security tests | Login required routes, revoke one session and show its old access token/socket rejected while another session remains active, then demonstrate denied unauthorized/pending actions, protected upload behavior, and an oversized message rejection |
| Event log for tracking activity | Complete | Channel events API/UI plus global superadmin audit API `GET /v1/admin/events` and bilingual `/app/admin` console; raw payloads are replaced by typed allowlisted display details; denied superadmin access and all administrative mutations are audited | Open channel Event Log, then superadmin console -> All audit events; filter by category/actor and show human-readable details |

## Platform Administration Enhancement

| Enhancement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Global superadmin oversight and controls | Mostly complete | `users.is_superadmin/is_active`; migration `0015_superadmin_controls`; safe environment bootstrap; `AdminService`; guarded/no-store `/v1/admin/overview`, `/events`, `/users`, and `/channels`; global delivery-monitor scope; bilingual frontend console with ranked search, filters, typed event display, confirmation gates, and selectable pagination; focused regression tests | Login as configured superadmin, search/filter global events, change page size, revoke a test user's sessions after confirmation, and suspend/restore a disposable channel |

The enhancement is intentionally bounded: superadmins administer accounts, channels, audit evidence, and delivery state but do not receive implicit access to private message bodies. Production additions such as MFA and external audit anchoring remain future work.

## Advanced Reliability Enhancement

| Enhancement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Delivery Reliability Upgrade v1: outbox retry/dead-letter monitoring | Mostly complete | Outbox status fields and migration `0012_delivery_reliability`; worker retry/dead-letter logic in `worker/worker_app/outbox_runner.py`; durable membership bind/unbind commands in the same outbox; bounded per-user queues; paced Redis fanout retries; RabbitMQ DLQ topology; admin Delivery Monitor; delivery and Phase 3 tests; supervisor verifier `scripts/verify_delivery_reliability.py` | Open Delivery Monitor as a channel owner/admin; inspect counters; run delivery verifier for normal publish plus controlled dead-letter/manual retry; explain that REST sync recovers queue expiry/eviction |

This enhancement strengthens the distributed-system reliability story, but it is not one of the official minimum requirements. PostgreSQL outbox state remains authoritative; the RabbitMQ DLQ is an operational mirror when the worker can publish to it.

## Advanced Security/Integrity Enhancement

| Enhancement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Event Integrity Upgrade v1: tamper-evident audit hash chain | Mostly complete | Event columns and migration `0013_event_integrity`; canonical hash-chain service in `backend/app/services/event_integrity_service.py`; event logging integration in `backend/app/services/event_service.py`; worker delivery-event hashing in `worker/worker_app/outbox_runner.py`; verification endpoint `GET /v1/channels/{id}/events/integrity`; backfill script `scripts/backfill_event_integrity.py`; frontend Event Log integrity badge/check; tests in `backend/tests/test_event_integrity.py` | Open channel details -> Event Log -> Verify integrity; use the Docker backfill dry-run command before any real legacy backfill |

This is an advanced integrity enhancement, not an official minimum requirement. It is tamper-evident against later event modification, insertion, reordering, and deletion that breaks links between remaining events. Tail truncation requires an external remembered last hash to prove. It is not a blockchain, not a full Merkle tree, and not external notarization; a database administrator with full write access could recompute a forged chain unless hashes are anchored outside the database.
