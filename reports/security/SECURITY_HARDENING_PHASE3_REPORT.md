# Security Hardening Phase 3 Report

## 1. Scope

Phase 3 audited and hardened authenticated abuse resistance, logical payload amplification, protocol-array bounds, idempotent state changes, reaction query scaling, upload authorization scaling, RabbitMQ user-queue lifecycle, basic account quotas, membership/broker consistency, and RabbitMQ-to-Redis outage behavior.

The existing FastAPI, PostgreSQL, transactional outbox, RabbitMQ, Redis, WebSocket, worker, and Next.js architecture was preserved. No frontend files changed. No httpOnly-cookie/CSRF migration, key rotation, attachment encryption, Docker credential redesign, or broad infrastructure rewrite was attempted.

The audit was performed against the current working tree after reading the Phase 1 and Phase 2 reports. Prior report claims were checked against implementation before changes were made.

## 2. Confirmed vulnerabilities

| Requested issue | Status | Audit result |
| --- | --- | --- |
| 1. Rate limiter fails open when Redis is unavailable | **CONFIRMED** | `RateLimitService.hit` caught every Redis exception and returned the same value as an allowed request. Login/register/refresh and message publish therefore became unlimited when Redis failed. |
| 2. Missing limits on expensive/unbounded endpoints | **CONFIRMED** | Auth and publish had hardcoded limits, but search, channel/member/invite mutations, sync, uploads, edits/deletes/reactions/seen/pins, WebSocket tickets/connections, and admin mutations had no consistent grouped policy. |
| 3. Unbounded message content and structured payload | **CONFIRMED** | Publish/edit schemas had no text byte limit, serialized JSON byte limit, or nesting-depth limit before encryption and outbox work. |
| 4. Unbounded `/sync` and WebSocket channel arrays | **CONFIRMED** | REST sync channels and WS subscribe/unsubscribe/resume/sync-state lists had no `max_length`. |
| 5. Seen/read-state amplification | **CONFIRMED** | Equal and lower seen markers still updated timestamps/unread state, committed, and created another `seen` outbox row. |
| 6. Reaction-delete event amplification | **CONFIRMED** | Reaction add was already idempotent, but delete always summarized, enqueued, and committed even when the delete affected zero rows. Reaction strings allowed arbitrary 64-character values. |
| 7. Reaction N+1 behavior | **CONFIRMED** | Each returned message executed two reaction queries. A 200-message page could execute 400 reaction queries, plus sender lookups. |
| 8. Expensive upload authorization lookup | **CONFIRMED** | Non-owner attachment access loaded approved channel IDs, selected every non-deleted message with attachment JSON, and scanned those structures in Python. |
| 9. Durable RabbitMQ queue resource exhaustion | **CONFIRMED** | Per-user queues were durable/non-auto-delete without `x-expires`, `x-message-ttl`, `x-max-length`, or overflow policy. |
| 10. Missing basic resource quotas | **CONFIRMED** | Accounts had no limit on owned channels, active invites, daily/pending uploads, reserved upload bytes, or concurrent WebSockets. |
| 11. Membership/broker consistency gap | **CONFIRMED** | Join/accept/approve/add/remove/leave committed PostgreSQL state and then performed a one-shot RabbitMQ bind/unbind. A broker failure left divergent state without durable retry. |
| 12. Redis failure can hot-requeue RabbitMQ | **CONFIRMED** | The consumer used `message.process(requeue=True)` around a single Redis publish. Redis failure immediately NACKed/requeued the same delivery without retry delay or circuit pacing. |

No requested issue was classified as already fixed or not present. No requested issue was deferred in full. Live multi-service outage integration and a general reconciliation command remain deferred as Phase 4 validation/operations work.

## 3. Abuse/security policies introduced

### Rate-limit failure policy

- Healthy Redis remains the distributed fixed-window store.
- Sensitive/high-abuse operations use a bounded per-process emergency fixed-window limiter if Redis raises.
- The emergency limiter holds at most 10,000 keys and evicts oldest keys beyond that bound, so attacker-controlled identities cannot create unbounded local memory use.
- Ordinary paginated reads are not made dependent on Redis. They remain available and retain existing pagination bounds.
- The emergency fallback is weaker than healthy Redis across multiple API replicas because it is per process; this is documented rather than presented as a global guarantee.

### Endpoint rate-limit groups

Configurable defaults were added for:

- `auth`: registration, login, refresh by IP and identity;
- `search`: authenticated user search;
- `message-write`: publish, edit, delete, reactions, seen, and pins using one shared per-user burst/sustained budget;
- `media`: upload create, PUT, and GET using one shared per-user budget;
- `channel-management`: create/update/delete/join/leave/invite/accept/revoke/member/permission mutations using one shared per-user budget;
- `websocket`: ticket creation and connection attempts;
- `sync`: REST `/sync`;
- `admin`: superadmin mutations.

### Message and protocol limits

- Text: 65,536 UTF-8 bytes by default.
- Structured JSON: 65,536 serialized UTF-8 bytes and depth 20 by default.
- REST sync channel cursors: maximum 100.
- WebSocket subscribe/unsubscribe/resume/sync-state entries: maximum 100.
- Reaction: maximum 16 code points/64 UTF-8 bytes, supported Unicode emoji composition only, and default maximum 20 distinct emoji values per message.

### Quotas

- 50 active owned channels per user.
- 100 active invites created per user.
- 100 upload records per user per day.
- 10 concurrent pending uploads per user.
- 1 GiB reserved/stored upload bytes per user.
- 5 concurrent WebSockets per user per backend process.

All values are environment-configurable. The implementation is intentionally a cheap MVP quota layer, not a billing or distributed accounting system.

### RabbitMQ queue lifecycle

User queues retain `durable=True`, `auto_delete=False`, and add:

- unused queue expiry: seven days;
- message TTL: 24 hours;
- maximum queue length: 10,000;
- overflow: `drop-head`.

PostgreSQL message history and REST sync are authoritative. RabbitMQ holds a bounded recent realtime copy, not the only durable copy.

### Redis outage behavior

RabbitMQ-to-Redis fanout makes three publish attempts by default with exponential delay. If all attempts fail, the consumer sleeps using a capped failure-streak backoff before the context NACKs/requeues. The event is not acknowledged/dropped merely to hide the outage, and retries are paced rather than tight.

## 4. Changes made

### Rate limiting and endpoint coverage

- **Root cause:** Redis exceptions were indistinguishable from allowed requests, and policies were scattered/hardcoded.
- **Files:** `backend/app/services/rate_limit_service.py`, grouped settings in `backend/app/core/config.py`, auth/user/channel/membership/message/admin routes, and `backend/app/main.py` for WS attempts.
- **Before:** Redis outage failed open; most sensitive routes had no rate limit.
- **After:** sensitive groups fall back locally, thresholds are configurable, and ordinary reads remain independent of Redis.

### Payload and protocol validation

- **Root cause:** logical messages and channel arrays had no application boundary.
- **Files:** `backend/app/core/payload_limits.py`, message schemas, realtime protocol schemas.
- **Before:** multi-megabyte strings/JSON and thousands of channel IDs could reach encryption/database/query loops.
- **After:** byte/depth/item limits reject requests with the standard validation response before expensive work.

### Seen and reaction idempotency

- **Root cause:** seen used `>=` and always rewrote/broadcast; reaction delete ignored affected-row count.
- **Files:** `backend/app/services/message_service.py`.
- **Before:** equal/lower seen requests and nonexistent reaction deletes amplified outbox traffic.
- **After:** only initial/forward seen progress and real reaction row changes emit events. Seen rows are locked during update. Reaction values/cardinality are bounded.

### Batched reaction rendering

- **Root cause:** response shaping called two summary queries for every message.
- **Files:** message service and message routes.
- **Before:** reaction query count grew by two per returned message.
- **After:** one aggregate query and one caller-reaction query serve the whole page; sender profiles use one batch query.

### Indexed upload authorization

- **Root cause:** attachment ownership was embedded only in message JSON.
- **Files:** model, migration 0018, message publish/access service, tests.
- **Before:** non-owner access scanned all attachment-bearing message rows in Python.
- **After:** publish stores a normalized `message_attachments` row; authorization joins indexed upload/channel/message/membership relations. Historical JSON references are backfilled by migration.

### Resource quotas and WebSocket concurrency

- **Root cause:** authenticated accounts could create resources without application caps.
- **Files:** settings, channel service, message/upload service, WS manager, migration quota indexes.
- **Before:** no account-level bounds.
- **After:** cheap indexed counts/sums enforce configured limits. The WS manager uses a lock and reserves a slot before the first await so simultaneous local handshakes cannot race past the limit.

### Queue lifecycle

- **Root cause:** per-user queues were durable forever with unlimited retained messages.
- **Files:** backend publisher, worker config/topology/consumer, `.env.example`.
- **Before:** no queue expiry/TTL/length/overflow arguments.
- **After:** backend and worker declare identical bounded arguments. REST sync remains the recovery contract.

### Durable membership broker state

- **Root cause:** one-shot broker mutation after database commit.
- **Files:** outbox service, channel service, worker outbox runner.
- **Before:** broker failure could escape the request after DB commit and leave no retryable desired state.
- **After:** channel owner/member state changes persist an idempotent `broker_binding.bind`/`unbind` row in the same transaction. The worker applies it through existing retry/dead-letter handling. Initial WebSocket connect remains an idempotent reconciliation path.

### Redis fanout pacing

- **Root cause:** single Redis publish inside immediate requeue context.
- **Files:** worker consumer/config.
- **Before:** Redis outage could repeatedly consume/NACK the same event as fast as RabbitMQ delivered it.
- **After:** bounded internal retries plus capped pre-requeue delay pace failure while preserving eventual retry.

## 5. Database migrations

`backend/alembic/versions/0018_phase3_abuse_hardening.py`:

- creates `message_attachments(message_id, upload_id, channel_id, created_at)`;
- primary key: `(message_id, upload_id)`;
- index: `(upload_id, channel_id)` for authorization;
- index: `(channel_id, message_id)` for channel/message maintenance;
- backfills valid historical JSON `file_id` references that still match an upload row;
- adds partial active-invite quota index `(created_by_user_id, expires_at)` where accepted/revoked are null;
- adds upload quota index `(owner_user_id, created_at)`.

Fresh upgrade through revision 0018 passed. A separate database upgraded to 0017, received a historical attachment JSON row, then upgraded to head; the expected normalized `message_id|upload_id|channel_id` row was produced.

## 6. Tests added

All new focused tests are in `backend/tests/security/test_phase3_abuse_hardening.py`:

- `test_redis_backed_rate_limit_enforces_threshold`: healthy Redis path and threshold.
- `test_redis_failure_uses_bounded_local_fallback_for_sensitive_policy`: Redis failure is not unlimited.
- `test_low_risk_failure_policy_can_remain_available`: documented ordinary-read availability policy.
- `test_message_text_and_edit_limits_validate_utf8_bytes`: publish/edit boundary and oversize rejection.
- `test_structured_json_size_and_depth_are_bounded`: JSON size/depth and ordinary compatibility.
- `test_rest_and_websocket_channel_arrays_accept_boundary_and_reject_oversize`: REST/WS 100/101 boundary.
- `test_websocket_oversized_subscribe_is_rejected_before_database_work`: safe WS protocol error.
- `test_seen_advances_once_and_identical_or_lower_markers_do_not_amplify`: monotonic state and exact outbox counts.
- `test_reaction_add_remove_are_idempotent_and_validate_values`: add/remove amplification and value policy.
- `test_message_response_reaction_queries_are_constant`: fixed SQL query count for 25 messages.
- `test_attachment_access_uses_normalized_relation_for_member_and_blocks_outsider`: owner/member/outsider authorization.
- `test_attachment_lookup_does_not_scan_message_attachment_json`: SQL uses normalized relation, not history JSON scan.
- `test_channel_invite_and_upload_quota_boundaries`: at-boundary/over-boundary quota behavior.
- `test_websocket_concurrency_quota_rejects_one_over_boundary`: concurrent connection cap.
- `test_user_queue_declaration_is_bounded_and_worker_matches_backend`: queue arguments and parity.
- `test_membership_changes_generate_durable_bind_and_unbind_commands`: join/removal desired state.
- `test_failed_broker_unbind_is_retryable_without_undoing_membership`: authoritative DB removal and retry status.
- `test_duplicate_broker_binding_processing_is_safe`: duplicate bind/unbind idempotency.
- `test_redis_fanout_failure_has_bounded_attempts_and_backoff`: attempts, delays, and cap.

Existing direct route and delivery reliability tests were minimally adapted to supply a fake rate-limit Redis dependency and to isolate message-outbox assertions from the new channel-owner binding command.

## 7. Performance/query improvements

### Reaction batching

The performance regression renders 25 messages and records SQL statements. Result:

- 1 batched sender query;
- 1 grouped reaction-count query;
- 1 caller-reaction query;
- total response-enrichment queries: 3;
- `message_reactions` queries: exactly 2, independent of returned message count.

### Upload authorization

Attachment authorization now uses the indexed `message_attachments` relation joined to approved membership and non-deleted message state. The regression records SQL and asserts that `message_attachments` is queried and the former `messages.attachments IS NOT NULL` history scan is absent.

### Eliminated state amplification

Tests assert exact outbox counts:

- repeated/lower seen markers do not add rows;
- duplicate reaction add does not add rows;
- repeated nonexistent reaction delete does not add rows.

## 8. Messaging reliability

### Queue TTL and limits

Backend and worker declarations use the same expiry, message TTL, maximum length, and overflow values. PostgreSQL/REST sync is explicitly documented as the durable recovery source.

RabbitMQ queue arguments are immutable for an existing queue name. A pre-Phase-3 environment must recreate legacy user queues or reset its demo RabbitMQ volume once before using the new declarations. This operational transition is documented and was not silently automated.

### Bind/unbind retry strategy

Membership transactions persist desired broker state using the existing outbox. Worker processing validates safe username/slug identifiers, declares the bounded user queue, and applies bind/unbind idempotently. Failures use the established retry scheduling and dead-letter status. A future reconciliation command would improve recovery after operator-managed dead letters, but the original lost-command gap is closed.

### Redis outage behavior

The online-user consumer retries Redis with exponential delay and holds the RabbitMQ delivery unacknowledged. On exhaustion it sleeps again before NACK/requeue. This avoids a hot loop without acknowledging or dropping the broker event. Because PostgreSQL remains authoritative, clients can REST-sync missed events even if bounded RabbitMQ copies later expire or are evicted.

## 9. Validation results

Validation used isolated PostgreSQL 16 container `messaging-phase3-security-postgres` on host port 55434. It did not use or truncate the normal development database.

```text
python -B -m alembic upgrade head
passed on a fresh database through 0018_phase3_abuse_hardening

upgrade to 0017; insert historical attachment JSON; upgrade head; select message_attachments
passed; expected message_id|upload_id|channel_id row returned

python -B -m pytest -q tests/security/test_phase3_abuse_hardening.py
19 passed, 1 warning in 8.70s

python -B -m pytest -q
143 passed, 1 warning in 61.26s

python -B -m compileall -q backend/app worker/worker_app
passed; generated tracked bytecode changes were restored

python -B -c "from app.main import app; schema=app.openapi(); ..."
passed; 57 OpenAPI paths

docker compose config --quiet
passed

git diff --check
passed; Git emitted line-ending conversion notices only
```

The warning is the existing `passlib` access to deprecated `argon2.__version__` metadata.

The tests use fake broker/Redis failures for deterministic state, argument, and backoff assertions. No live RabbitMQ or Redis outage/recovery integration was performed, so this report does not claim one.

Frontend checks were not run because no frontend files changed.

## 10. Remaining risks

- Emergency rate limiting is per backend process during Redis failure; a multi-instance attacker receives an allowance per process.
- Concurrent WebSocket quota is per backend process, not a global distributed connection counter.
- Rate limits and quotas have no metrics/dashboard or operator alerting.
- Existing RabbitMQ queues require a one-time recreate/reset because queue declaration arguments cannot be changed in place.
- Broker binding commands can become dead-lettered after maximum attempts; operator retry exists through outbox tooling, but there is no dedicated binding reconciliation command.
- Live two-backend, RabbitMQ-outage, and Redis-outage integration tests remain missing.
- RabbitMQ keeps only a bounded recent copy by design. Client correctness depends on using PostgreSQL-backed REST sync after gaps.
- Avatar/profile media-reference authorization remains separate string-reference logic; the expensive message-attachment history scan is fixed.
- Upload reservations count all upload records and there is no deletion/garbage-collection endpoint; quota reclamation is therefore conservative.
- Application validation does not replace reverse-proxy/ASGI raw HTTP body limits in a production deployment.
- Browser credentials remain JavaScript-readable; there is no httpOnly-cookie/CSRF architecture.
- Attachments are authorized and immutable but not encrypted by the message-body Fernet layer.
- Encryption key rotation/KMS, Docker production credential/network hardening, external audit anchoring, and full dependency lint/type CI remain future work.

## 11. Recommended Phase 4

1. Add a live Docker integration scenario that stops Redis during delivery, verifies paced RabbitMQ retry, restores Redis, and confirms delivery or REST recovery.
2. Add a live RabbitMQ outage scenario for membership removal, then verify the durable unbind command succeeds after broker recovery.
3. Add a small broker-binding reconciliation command that compares approved PostgreSQL memberships with desired queue bindings and safely re-enqueues discrepancies/dead letters.
4. Add rate-limit/quota/outbox retry metrics and alerts before considering higher deployment scale.
5. Define a documented one-time legacy queue recreation procedure and run the supervisor demo on the recreated bounded queues.
6. Add reverse-proxy request-body/time limits for a production deployment profile.
7. Keep the already-deferred browser httpOnly/CSRF, encryption-key rotation, attachment encryption, and Docker credential work separate from the pub/sub MVP.

## 12. Files changed

### Configuration and documentation

- `.env.example`
- `README.md`
- `REPOSITORY_ASSESSMENT.md`
- `SECURITY_HARDENING_PHASE3_REPORT.md`
- `docs/ARCHITECTURE.md`
- `docs/FINAL_MVP_STATUS.md`
- `docs/REQUIREMENTS_MAPPING.md`
- `docs/SECURITY.md`
- `docs/STABILIZATION_STATUS.md`
- `docs/TESTING.md`

### Backend

- `backend/alembic/versions/0018_phase3_abuse_hardening.py`
- `backend/app/api/routes/admin.py`
- `backend/app/api/routes/auth.py`
- `backend/app/api/routes/channels.py`
- `backend/app/api/routes/memberships.py`
- `backend/app/api/routes/messages.py`
- `backend/app/api/routes/users.py`
- `backend/app/core/config.py`
- `backend/app/core/payload_limits.py`
- `backend/app/db/models.py`
- `backend/app/main.py`
- `backend/app/mq/publisher.py`
- `backend/app/realtime/protocol.py`
- `backend/app/realtime/ws_manager.py`
- `backend/app/schemas/messages.py`
- `backend/app/services/channel_service.py`
- `backend/app/services/message_service.py`
- `backend/app/services/outbox_service.py`
- `backend/app/services/rate_limit_service.py`

### Worker

- `worker/worker_app/amqp_consumer_runner.py`
- `worker/worker_app/core/config.py`
- `worker/worker_app/mq/topology.py`
- `worker/worker_app/outbox_runner.py`

### Tests

- `backend/tests/conftest.py`
- `backend/tests/security/test_phase1_hardening.py`
- `backend/tests/security/test_phase3_abuse_hardening.py`
- `backend/tests/test_delivery_reliability.py`
- `backend/tests/test_p0_requirements.py`
