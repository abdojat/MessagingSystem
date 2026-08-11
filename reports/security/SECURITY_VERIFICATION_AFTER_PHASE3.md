# Security Verification After Phase 3

## 1. Executive verdict

**SIGNIFICANT ISSUES REMAIN**

The three hardening phases materially improved the system. The reviewed implementation has credible session-bound access tokens, row-locked refresh rotation, one-time Redis WebSocket tickets, server-side authorization for the principal REST operations, immutable streamed upload writes, encrypted message storage, bounded message payloads, transactional message/outbox persistence, and useful abuse quotas.

The current system should not yet be described as production-secure. This adversarial review found three High-severity issues:

1. stale RabbitMQ binding commands can be replayed after a newer unbind, and a missed membership-control event can leave an already-connected socket accepting the resulting channel messages until its access token expires;
2. `/sync` limits the returned list but not the database rows loaded and sorted, allowing an authenticated user to force work proportional to all missed history in as many as 100 channels; and
3. authorized upload downloads read an entire file into process memory, allowing the media-rate-limit burst to allocate roughly 1.5 GiB per account/backend at the default 25 MiB file limit.

No Critical authentication bypass, direct outsider IDOR into private messages, plaintext password storage, refresh-token rotation bypass, WebSocket-ticket reuse, path traversal, or practical stored-XSS path was found.

Finding count: **0 Critical, 3 High, 5 Medium, 3 Low**.

## 2. Repository/version reviewed

| Item | Reviewed value |
|---|---|
| Repository | `abdojat/MessagingSystem` working tree supplied at `C:\Users\abdal\Desktop\FYP\MessagingSystem` |
| Branch | `master` |
| Commit | `73b173839c21ac89b216b078257f29ae51560a4c` |
| HEAD subject | `feat: enhance delivery reliability and rate limiting` |
| Phase 1 commit | `d171975 Implement Phase 1 security hardening with comprehensive tests` |
| Phase 2 commit | `0949428 Enhance authentication and WebSocket security` |
| Phase 3 commit | `73b1738 feat: enhance delivery reliability and rate limiting` |
| Initial working tree | Clean; `git status --short` returned no entries |
| Unstaged Phase 1–3 work | None present |
| Existing staged work | None present |

The review began by reading all of:

- `SECURITY_HARDENING_PHASE1_REPORT.md`
- `SECURITY_HARDENING_PHASE2_REPORT.md`
- `SECURITY_HARDENING_PHASE3_REPORT.md`

The reports were treated as claims to test, not as proof. Current source, migrations, tests, frontend, Docker configuration, and relevant history were independently inspected.

## 3. Validation of Phase 1

| Phase 1 control | Status | Adversarial result |
|---|---|---|
| `/sync` membership isolation | **VERIFIED** | Requested cursor IDs are intersected with the caller's current approved memberships before message reads. Empty cursors select only the caller's approved memberships. Pending/removed/outsider roles do not enter the membership map. Membership events are constrained to the current actor, target actor, or current channels and then post-filtered. No cross-channel membership disclosure was found. AV-02 is a resource-exhaustion defect in this endpoint, not an isolation bypass. |
| Targeted removal updates | **PARTIALLY VERIFIED** | The targeted user can receive their own removal update, and the local subscription is discarded before later ordinary events. This depends on Redis/outbox delivery. A missed control/update leaves the local subscription stale; combined with AV-01, confidentiality can fail until socket expiry. |
| Upload immutability and simultaneous first PUT | **VERIFIED** | `SELECT ... FOR UPDATE`, create-only temporary files, same-directory hard-link finalization, and the persisted marker serialize competing writers. A live two-session PostgreSQL experiment produced one success and one `409 UPLOAD_IMMUTABLE`. Size/checksum mismatch and interrupted-stream cleanup are covered by the existing suite. |
| Upload crash-state recovery | **PARTIALLY VERIFIED** | The implementation removes a finalized file on handled rollback paths, but a process crash between hard-link creation and DB commit can leave `final file exists + public_url is NULL`. Later PUTs reject that state as immutable; there is no automatic repair/GC. This is primarily availability/operations, not a content overwrite bypass. |
| Path/symlink containment | **VERIFIED** | Storage names are generated, `_resolve_upload_path` resolves and checks containment, the final file is created with `os.link`, and overwrite is refused. No user-controlled filesystem path was found. A privileged/local attacker controlling the upload directory is outside the application threat boundary. |
| Streaming request body and in-stream limits | **PARTIALLY VERIFIED** | The route passes `request.stream()` and never calls `request.body()`; the service subdivides writes into 64 KiB pieces and enforces configured and declared sizes while streaming. Application middleware does not buffer the body. No reverse proxy was present to test, and killed processes/abandoned pending uploads lack automatic temporary-file and reservation reclamation. |
| Production secret validation | **PARTIALLY VERIFIED** | Case/whitespace normalization works for `production`, `prod`, and `staging`; placeholders, short/low-diversity JWT secrets, missing keys, and malformed Fernet keys are rejected at settings construction. Unexpected aliases such as `live` fail open to development behavior (AV-10). |
| WebSocket channel filtering | **BYPASS FOUND** | Empty subscriptions are not wildcards, subscribe/resume requests are intersected with DB membership, and ordinary events with a `channel_id` require a local subscription. The filter trusts its cached subscription thereafter. A missed removal event plus stale Rabbit binding can deliver post-removal messages for the remainder of the socket lifetime (AV-01). Events without `channel_id` pass the channel filter, but no attacker-controlled cross-user route for such an event was found. |

## 4. Validation of Phase 2

| Phase 2 control | Status | Adversarial result |
|---|---|---|
| Session-bound access token `sid` | **VERIFIED** | The authentication query joins `User` to `UserSession` and constrains `User.id == token.sub` and `UserSession.id == token.sid` in the same query. Missing/malformed `sid`, another user's session, deleted/revoked/idle-expired/absolute-expired sessions, deactivated users, and subject/session mismatch are rejected. |
| Logout/revocation semantics | **VERIFIED** | New requests using a revoked session fail. A request that authenticated immediately before logout may finish; this is normal request-level race semantics and does not create durable privilege after revocation. |
| Refresh-token rotation and replay | **VERIFIED** | PostgreSQL `SELECT ... FOR UPDATE` serializes refreshes on one session row. The presented `sid`, subject, token type, expiry, JTI-derived hash, user state, idle expiry, and absolute expiry are checked. Stale-token detection revokes and commits the family before best-effort audit handling, so audit failure does not roll back replay revocation. Existing focused tests exercise concurrent/stale rotation paths. |
| Absolute session lifetime | **VERIFIED** | UTC-aware timestamps and `<=` boundary checks are used. Refresh cannot extend beyond `absolute_expires_at`. Migration `0017` deliberately preserves longer legacy expiry via `GREATEST`; that compatibility extension is documented behavior rather than a hidden runtime bypass. |
| One-time WebSocket tickets | **VERIFIED** | Tickets use cryptographically random values, store only a hash in Redis, cap input length, cap ticket expiry to authentication expiry, and consume with Redis `GETDEL`. Redis 7 is declared in Compose, where `GETDEL` is atomic. Session/user state is revalidated from PostgreSQL after ticket consumption. |
| Cross-instance WebSocket revocation | **PARTIALLY VERIFIED** | Local socket indexes close matching sessions/users promptly, and Redis broadcasts propagate logout, logout-all, replay revocation, and deactivation when delivered. Redis pub/sub is ephemeral: a missed control message is not replayed, and active sockets do not poll session state. The maximum default residual window is the remaining access-token lifetime, up to **30 minutes** (`JWT_ACCESS_TTL_MIN=30`). Access expiry itself is enforced by a timer. |
| Stolen credential outcomes | **PARTIALLY VERIFIED** | An old refresh token triggers family revocation while still parseable; a current refresh token can rotate the family; a stolen access token works only while its bound session remains active; a stolen WS ticket is single-use and short-lived. Browser-readable access/refresh storage remains an admitted production weakness, discussed in section 12. |

## 5. Validation of Phase 3

| Phase 3 control | Status | Adversarial result |
|---|---|---|
| Redis-backed grouped rate limits | **PARTIALLY VERIFIED** | Normal Redis counters and route grouping are present. Sensitive groups fall back locally on Redis failure, but fallback is per process and deliberately evictable at 10,000 keys; an attacker can reset a blocked key through churn (AV-07). Redis `INCR` and first-hit `EXPIRE` are separate operations, so a failure between them can leave a no-TTL counter. |
| Rate-limit IP trust | **VERIFIED** | The routes derive IP from `request.client.host`; arbitrary `X-Forwarded-For` is not directly used. No configured trusted-proxy middleware that accepts arbitrary forwarding headers was found. Multiple real IPs/accounts and multiple backend instances still distribute limits as expected for this design. |
| Message byte/depth validation | **VERIFIED** | Text uses UTF-8 byte length, JSON uses serialized byte length and iterative depth checks, and both default to 64 KiB. JSON escaping, multibyte text, wide shallow structures, edits, and HTTP publish routes use the same validation path. Encryption expansion occurs only after the bounded logical payload. No realistic <=64 KiB complexity attack was identified. |
| Protocol array/limit validation | **PARTIALLY VERIFIED** | REST/WS schemas bound cursor/channel arrays and response counts. The bounds do not guarantee bounded work: REST `/sync` loads all qualifying rows before slicing (AV-02), and repeated WebSocket commands are unmetered (AV-04). |
| Seen idempotency/concurrency | **VERIFIED** | Membership and state rows are locked, advancement is monotonic, and duplicate/non-advancing requests do not produce duplicate advancement. The full suite passed relevant focused tests. |
| Reaction idempotency/cardinality | **VERIFIED** | Message-row locking serializes distinct-variety checks, the unique constraint prevents duplicate user/message/emoji rows, and removes are idempotent. Unicode-equivalent spellings can fragment labels but do not bypass the locked distinct-reaction cap. |
| Reaction query batching | **VERIFIED** | History, sync, and pinned serialization use batched reaction summaries. No new reaction N+1 path was found in the inspected REST response builders. WebSocket payloads currently return an empty reaction summary rather than performing per-message reaction queries. |
| Normalized attachment authorization | **BYPASS FOUND** | Deleted messages and removed/pending/nonmembers are excluded. Soft-deleted channels are not checked, so retained approved members can still fetch old attachment bytes after the channel becomes inaccessible (AV-05). |
| Attachment relation integrity | **PARTIALLY VERIFIED** | Normal application publishing creates consistent rows and the migration backfills from each message's channel. Independent FKs do not enforce `message_attachments.channel_id == messages.channel_id`, leaving a latent authorization hazard if any import/repair/bug creates an inconsistent row (AV-09). |
| Account quotas | **PARTIALLY VERIFIED** | Channel, invite, upload-count, pending-upload, and reserved-byte checks lock the relevant user row, serializing normal application creation paths. WebSocket quotas are locked only inside one backend process, and upload reservations have no deletion/GC. The latter can permanently exhaust the attacker's own account and grow operational data but is not a cross-user authorization bypass. |
| Durable membership binding changes | **BYPASS FOUND** | The audited create/join/accept/add/approve/promote/demote/permission/remove/leave/delete paths enqueue membership/binding work within their DB transaction. Commands describe historical actions rather than versioned desired state, so stale retry ordering is unsafe (AV-01). Slug update and superadmin restore still perform direct Rabbit operations after commit (AV-08). |
| Queue declaration bounds | **PARTIALLY VERIFIED** | Backend and worker use the same expiry, message-TTL, max-length, and drop-head arguments. Legacy queues with different immutable arguments fail loudly with a Rabbit precondition error. No live legacy-queue upgrade was executed. |
| Redis fanout pacing | **PARTIALLY VERIFIED** | Retry attempts and per-user backoff are bounded and do not synchronously block every user's task. Rabbit QoS/prefetch is not explicitly configured, so extended Redis failure can accumulate unacked deliveries and synchronized requeues. Live outage behavior was not exercised. |

## 6. New findings

| ID | Severity | Component | Finding | Attack prerequisite | Impact | Confidence |
|---|---|---|---|---|---|---|
| AV-01 | **HIGH** | Outbox/RabbitMQ/WebSocket | Historical bind/unbind actions have no generation or desired-state check; a delayed bind can run after a newer unbind. With a missed membership update, a stale connected socket can receive post-removal messages. | Former member online; delayed/retried binding; Redis/control delivery loss or delay | Cross-user channel-message confidentiality loss for up to the remaining access-token lifetime | High (code/data-flow proof; multi-service sequence not live-reproduced) |
| AV-02 | **HIGH** | REST sync/PostgreSQL | `/sync` fetches every qualifying message per selected channel and only globally slices after materializing and sorting. | Authenticated member with access to high-history channels | Strong DB, memory, and CPU exhaustion per request | High |
| AV-03 | **HIGH** | Upload download/backend memory | Protected file GET uses synchronous `path.read_bytes()` and materializes the complete response. | Any account authorized for one or more maximum-size files | Burst process-memory exhaustion; default 60 x 25 MiB is about 1.5 GiB per account/backend before overhead | High |
| AV-04 | **MEDIUM** | WebSocket inbound protocol | Established sockets have no per-command rate/work limit; repeated subscribe/seen/resume commands bypass REST abuse groups. | Authenticated user with a valid socket | Sustained DB, decryption, serialization, and outbound-bandwidth amplification | High |
| AV-05 | **MEDIUM** | Attachment authorization | `can_access_upload` omits channel deletion state, so retained members can fetch attachments from a soft-deleted channel. | Former approved member who knows an attachment UUID | Violates channel deletion/suspension access lifecycle; continued private-media disclosure | High; reproduced against PostgreSQL |
| AV-06 | **MEDIUM** | Invite lifecycle | Invite accept/revoke state is read and updated without row locking or an atomic conditional transition. Generic-invite semantics are also internally inconsistent. | Valid invite token plus a concurrent revoke/accept race | A token checked before revocation can still create membership after revocation was requested | Medium-high (race window proven structurally; revoke/accept interleaving not live-reproduced) |
| AV-07 | **MEDIUM** | Redis-outage rate-limit fallback | Global 10,000-key LRU eviction lets attackers churn identities/keys and evict their own blocked key. | Redis unavailable plus ability to generate enough distinct rate keys across accounts/IPs/operations | Sensitive-route throttling can be reset during the failure mode it is meant to cover | High; deterministic local reproduction |
| AV-08 | **MEDIUM** | Channel slug/restore broker state | Channel slug changes and superadmin restores commit PostgreSQL before direct Rabbit bind/unbind calls, with no durable repair command. | RabbitMQ/transient backend failure at update or restore | Persistently missing or stale delivery bindings until manual/reconnect repair; partial distributed state | High |
| AV-09 | **LOW** | Database attachment relation | Independent FKs do not enforce that relation `channel_id` matches the referenced message's `channel_id`. | Malformed migration/import, direct DB write, or a future application bug | Inconsistent row could authorize an unrelated channel member to an upload | High structural confidence; no normal-user write path found |
| AV-10 | **LOW** | Production configuration | Secret enforcement is an environment-name denylist/allowlist for only `prod`, `production`, and `staging`; aliases such as `live` accept placeholders. | Operator deploys with an unexpected production label | Insecure JWT/encryption defaults can start due to deployment misclassification | High; reproduced |
| AV-11 | **LOW** | Frontend/Compose production posture | The documented demo profile uses JS-readable credentials, no frontend security headers/TLS, published unauthenticated infrastructure ports, development credentials, and root containers. | Deploying the local Compose profile unchanged on a reachable host | Credential theft impact after any XSS and direct infrastructure exposure | High; development concern becomes a production blocker |

## 7. Detailed findings

### AV-01 — stale binding retry can restore obsolete delivery

**Affected code**

- `backend/app/services/outbox_service.py:99`, `enqueue_broker_binding_outbox`
- `worker/worker_app/outbox_runner.py:125`, `process_outbox_batch`
- `worker/worker_app/outbox_runner.py:178`, `_apply_broker_binding`
- `backend/app/realtime/ws_manager.py:218`, `_ensure_user_bindings`
- `backend/app/realtime/ws_manager.py:565`, `_forward_event`

**Root cause.** A broker-binding outbox row captures an immutable historical `bind` or `unbind`, username, and channel slug. It has no membership generation, monotonically increasing aggregate sequence, or desired-state predicate. `SKIP LOCKED` allows multiple workers to work around locked older rows, and a retry-scheduled older row can become eligible after a newer command. `_apply_broker_binding` blindly executes the stored action without consulting current PostgreSQL membership/channel state. Reconnect reconciliation binds current memberships but never removes bindings that are no longer desired.

**Realistic attack/failure sequence.** A member's original bind fails and is scheduled for retry. The owner removes the member; the newer unbind succeeds. The original bind later retries and binds the former member's durable queue again. If the affected backend socket did not receive its Redis/outbox membership-removal event, its cached subscription still contains the channel. New channel messages routed to that user's queue are forwarded and decrypted to the stale socket.

**Expected vs actual.** Expected: current PostgreSQL desired membership always dominates old delivery commands. Actual: last Rabbit operation to execute wins, even when it represents older state.

**Impact.** A removed member can receive confidential post-removal channel messages under the explicitly scoped partial-infrastructure-failure threat model. The socket's hard upper bound is its authentication expiry—up to 30 minutes by default—but queued delivery and recovery ordering make the exact exposure dependent on timing.

**Existing tests.** `test_duplicate_broker_binding_processing_is_safe` proves bind-twice and unbind-twice idempotency. It does not exercise old-bind/new-unbind/retried-old-bind ordering or re-check DB desired state.

**Recommended direction.** Represent versioned desired binding state, serialize per user/channel aggregate, and make the worker compare the command generation and current PostgreSQL membership/channel before acting. Reconciliation must remove stale bindings as well as add missing ones. At the final plaintext WebSocket boundary, periodically/currently revalidate channel authorization or make membership invalidation durable rather than relying only on ephemeral pub/sub.

### AV-02 — `/sync` response cap does not cap work

**Affected code:** `backend/app/services/message_service.py:898`, `MessageService.sync`.

**Root cause.** For each selected channel, the service executes an ordered message query with no SQL `LIMIT`, materializes all rows, extends one Python list, sorts it, and only then applies `[:req.limit]`. The request allows as many as 100 channel cursors; the response limit is at most 500 but has no relationship to rows scanned/materialized.

**Attack sequence.** A normal user joins or creates channels with substantial persisted history, then repeatedly submits cursors at sequence zero. Each accepted request causes the backend to load and sort all missed rows across those channels even though only 500 can be returned. Sixty sync calls per minute remain enough for a strong amplification attack because a single call is not bounded.

**Expected vs actual.** Expected: database and memory work are proportional to the response/page limit. Actual: work is proportional to total missed history.

**Impact.** Authenticated DB pool starvation, backend memory pressure, CPU sorting load, latency for unrelated users, and possible process termination.

**Existing tests.** Tests assert authorization and returned item counts; they do not assert generated SQL limits, rows materialized, or behavior with large histories.

**Recommended direction.** Query a globally bounded page using a suitable keyset/union strategy, or decrement remaining capacity per channel and put `LIMIT remaining` on every query. Define stable cross-channel ordering/cursor semantics and add a large-history regression that measures bounded rows/queries.

### AV-03 — attachment downloads are fully buffered in backend memory

**Affected code:** `backend/app/api/routes/messages.py:446-479`, `get_upload_content`.

**Root cause.** After correct authorization and containment checks, the route returns `Response(content=path.read_bytes())`. `read_bytes()` synchronously allocates the entire file, and the response retains those bytes while the server/client transmits them.

**Attack sequence.** An authenticated user uploads or gains access to one or more 25 MiB files and opens many concurrent GETs. The shared media limit permits 60 requests per minute with no separate concurrent-download or bandwidth cap. Sixty maximum-size response bodies are approximately 1.5 GiB before Python/ASGI/socket overhead. Public registration and multiple accounts increase the ceiling.

**Expected vs actual.** Expected: authorized bytes are streamed in bounded chunks with backpressure. Actual: every accepted response is completely materialized.

**Impact.** Strong authenticated memory/worker exhaustion and event-loop blocking from synchronous disk reads.

**Existing tests.** Authorization and returned bytes are tested with small files. No maximum-size concurrent GET or slow-client test exists.

**Recommended direction.** Use a bounded streaming/file response with correct content headers, keep authorization before opening the file, add per-user/IP concurrency and bandwidth controls at the proxy/application layer, and test slow/aborted clients.

### AV-04 — established WebSockets bypass command-level abuse controls

**Affected code**

- `backend/app/realtime/ws_manager.py:228`, `_send_history`
- `backend/app/realtime/ws_manager.py:316`, `_inbound_loop`
- `backend/app/realtime/ws_manager.py:421`, `_handle_subscribe`
- `backend/app/main.py:127-159`, WebSocket handshake path

**Root cause.** Ticket issuance/connection is limited, but the inbound loop has no token bucket, command frequency limit, outstanding-work limit, or per-socket message-size configuration at the application layer. Repeated `subscribe` requests re-run membership queries and can fetch/decrypt up to 100 messages for each of up to 100 channels (10,000 messages) every time. Repeated `seen` requests enter DB transactions; `resume` is capped at 500 messages but is also repeatable without rate accounting.

**Attack sequence.** A normal user opens up to five sockets on one backend and continuously sends valid subscribe/seen/resume envelopes. The custom client does not follow frontend pacing.

**Expected vs actual.** Expected: Phase 3 protects expensive behavior independent of transport. Actual: equivalent REST work is limited, while post-handshake WS commands are not.

**Impact.** Sustained authenticated DB, CPU/decryption, serialization, and outbound bandwidth exhaustion. Per-process socket-count limits reduce but do not eliminate this abuse.

**Existing tests.** Schema array bounds and connection quotas are tested; command rate/work amplification is not.

**Recommended direction.** Add per-user/session/socket command budgets, total history-work bounds, inbound frame caps, and an outstanding-work/backpressure limit. Avoid sending history again when a subscription set is unchanged unless an explicit bounded cursor is supplied.

### AV-05 — soft-deleted channel attachments remain readable

**Affected code:** `backend/app/services/message_service.py:1198`, `MessageService.can_access_upload`.

**Root cause.** The normalized attachment check joins an approved `ChannelMembership` and non-deleted `Message` but does not join `Channel` or require `Channel.deleted_at IS NULL`. Soft deletion retains memberships and messages.

**Attack sequence.** An approved non-owner member records an attachment UUID. The owner/superadmin soft-deletes the private channel. Channel/history APIs now return channel-not-found, but the member directly requests `/v1/uploads/{id}/content`; `can_access_upload` still returns true.

**Expected vs actual.** Expected: channel deletion/suspension removes ordinary member access to all channel content, including protected media. Actual: message text becomes unavailable but attachment bytes remain available to retained memberships. Upload owners remain authorized by the separate owner rule; this finding concerns other members.

**Impact.** Continued disclosure of private media after the channel has been made inaccessible.

**Existing tests.** Deleted message, outsider, and membership authorization are covered; deleted-channel attachment lifecycle is not.

**Recommended direction.** Make the lifecycle policy explicit, include active-channel state in attachment authorization when deletion is meant to suspend access, and add deletion/restore tests for owner and non-owner readers.

### AV-06 — invite acceptance and revocation are not atomic lifecycle transitions

**Affected code**

- `backend/app/services/channel_service.py:834`, `revoke_invite`
- `backend/app/services/channel_service.py:885`, `accept_invite`
- `backend/app/services/channel_service.py:1330-1360`, `_validate_invite`

**Root cause.** All paths read invite state without `FOR UPDATE`; membership creation, `accepted_at`, and `revoked_at` are committed later. There is no conditional update such as `... WHERE revoked_at IS NULL AND accepted_at IS NULL AND expires_at >= now()` that claims the lifecycle transition. The schema calls generic invites reusable, while preview/accept/join set and reject `accepted_at`, making sequential and concurrent behavior inconsistent.

**Attack sequence.** An administrator revokes a leaked token while a holder concurrently accepts it. The accept transaction can pass its revocation check before the revoke commits and still insert/upgrade membership afterward. A controlled two-acceptance experiment confirmed that two transactions can pass the same unchecked lifecycle state; two distinct users joined from one generic token concurrently. Because generic invites are described as reusable, that exact two-user result is evidence of missing serialization/semantic inconsistency, not on its own the privilege impact; revoke-versus-accept is the security consequence.

**Expected vs actual.** Expected: revocation and one-use acceptance (if intended) have a defined linearization point. Actual: request timing determines whether a token accepted around revocation grants membership, and generic reuse semantics differ between schema comments and service behavior.

**Impact.** A leaked token may grant membership despite a concurrent revocation request; audit state may show both accepted and revoked timestamps.

**Existing tests.** Sequential invite creation/acceptance/revocation is tested. No two-session acceptance or accept/revoke race is covered.

**Recommended direction.** First define whether generic invites are reusable. For one-use/targeted transitions, lock the invite row or use an atomic conditional update and treat zero updated rows as stale/revoked. If generic links are reusable, do not use a single `accepted_at` as their global consumed state; record acceptances separately while retaining an atomically checked revocation boundary.

### AV-07 — local fallback limit can be reset through LRU churn

**Affected code:** `backend/app/services/rate_limit_service.py:27-68`, especially `_max_local_keys` and `_hit_local`.

**Root cause.** All local rate keys share one 10,000-entry `OrderedDict`. Every new distinct key evicts the least recently used entry. A blocked attacker key is therefore reset to a fresh window after enough other keys are inserted. The fallback is also per backend process. Redis uses separate `INCR` and first-hit `EXPIRE`; an exception after successful `INCR` falls back locally but may leave the Redis key without TTL.

**Attack sequence.** During Redis failure, the attacker exceeds a sensitive limit and is blocked. They create 10,000 other route/identity keys using accounts, operations, and/or source addresses, evict the blocked key, then retry it. The deterministic experiment returned allowed → blocked → churn → allowed.

**Expected vs actual.** Expected: bounding limiter memory may reduce precision but must not let an attacker deliberately reset their own sensitive limit. Actual: eviction is a predictable bypass.

**Impact.** Login/register/message/media/channel controls can lose effectiveness exactly during Redis outage or error conditions. Required effort is meaningful, so this is Medium rather than High.

**Existing tests.** Tests prove bounded memory and basic fallback limiting. They do not verify enforcement after adversarial eviction.

**Recommended direction.** Use a design whose saturation fails closed for sensitive groups, separate trusted fixed-cardinality buckets from attacker identity keys, or use a bounded approximate limiter that cannot selectively reset a blocked key. Make the Redis increment/expiry update atomic with Lua or an equivalent primitive and add multi-process/outage tests.

### AV-08 — slug updates and channel restore bypass the durable binding outbox

**Affected code**

- `backend/app/services/channel_service.py:538-624`, `update_channel`
- `backend/app/services/admin_service.py:560-600`, `restore_channel`

**Root cause.** These methods commit channel state and then call RabbitMQ directly. A broker error cannot roll the database back and no pending desired-state row remains for the worker to repair. The update comment assumes reconnect repairs binding, but reconnect only binds current slugs and does not unbind stale old slugs. Restore similarly has no durable retry.

**Attack/failure sequence.** RabbitMQ is temporarily unavailable as an authorized admin changes a slug or a superadmin restores a channel. PostgreSQL reports the operation complete. The direct Rabbit call fails. Members then miss realtime delivery; an old-slug binding may persist after a rename.

**Expected vs actual.** Expected: all DB changes affecting broker topology have transactional durable follow-up. Actual: these two lifecycle paths retain the pre-Phase-3 consistency gap.

**Impact.** Prolonged distributed delivery failure and stale broker state. WebSocket channel-ID filtering limits the stale-slug confidentiality consequence, so the direct issue is Medium availability/integrity rather than a separate High leak.

**Existing tests.** Membership mutation outbox paths are covered. No Rabbit failure at slug update/restore is tested.

**Recommended direction.** Store desired unbind-old/bind-new or a versioned reconcile command in the same DB transaction. Make restore enqueue binding reconciliation for each active member and verify retry behavior.

### AV-09 — attachment/channel consistency is not enforced relationally

**Affected code**

- `backend/app/db/models.py:215`, `MessageAttachment`
- `backend/alembic/versions/0018_phase3_abuse_hardening.py:16-29`
- `backend/app/services/message_service.py:1198`, `can_access_upload`

**Root cause.** `message_id`, `upload_id`, and `channel_id` each have independent foreign keys. No composite FK/constraint ties `(message_id, channel_id)` to the referenced message. Authorization joins the message on `message_id` and membership on the relation's `channel_id` without asserting equality.

**Attack sequence.** No normal attacker-controlled route that can insert an inconsistent relation was found. If a future route, repair script, import, compromised migration, or application defect inserts a relation whose channel differs from the message, a member of the false channel can satisfy the media authorization join.

**Expected vs actual.** Expected: DB integrity makes impossible states unrepresentable. Actual: correctness relies on the current publish path and migration.

**Impact.** Latent authorization hazard with no current direct normal-user exploit path; therefore Low.

**Existing tests.** Backfill and normal publishing consistency are tested. Direct inconsistent-row rejection is not possible because no such constraint exists.

**Recommended direction.** Add an appropriate composite uniqueness/reference design or remove redundant authorization state and derive channel from the message. Include a migration integrity check before adding the constraint.

### AV-10 — unexpected production labels skip secret enforcement

**Affected code:** `backend/app/core/config.py:10,110-137`, `PRODUCTION_ENVIRONMENTS` and `_validate_production_secrets`.

**Root cause.** Secret enforcement activates only when normalized `ENVIRONMENT` is one of three known strings. All other strings are assumed development, including names often used for production such as `live` or `release`.

**Attack/deployment sequence.** An operator sets `ENVIRONMENT=live`, expects production checks, and leaves `JWT_SECRET=change-me` or an empty encryption key. Configuration accepts the placeholder and can use development behavior.

**Expected vs actual.** Expected: unknown deployment environments fail safe or explicit development modes are allowlisted. Actual: unknown modes fail open.

**Impact.** Operator-dependent weak-secret deployment, not a remote bypass of a correctly labeled environment.

**Existing tests.** Case variants of recognized names and weak-secret shapes are covered; unknown production aliases are not.

**Recommended direction.** Allowlist explicit non-production values (`dev`, `test`, perhaps `local`) and apply strict validation to every other value, or use a separate explicit `ALLOW_INSECURE_DEVELOPMENT_DEFAULTS` flag.

### AV-11 — local demo posture is a production blocker if deployed unchanged

**Affected code/configuration**

- `docker-compose.yml`
- `backend/Dockerfile`, `worker/Dockerfile`, `frontend/Dockerfile`
- `frontend/src/services/auth/session-cookie.ts:3-13`
- `frontend/src/hooks/use-auth.ts` and `frontend/src/store/authStore.ts`
- Next.js configuration (no security-header policy found)

**Root cause.** Compose publishes PostgreSQL 5432, RabbitMQ 5672/15672, Redis 6379, backend HTTP 8000, and frontend HTTP 3000 on all host interfaces by default. PostgreSQL uses `postgres/postgres`; Rabbit uses the demo guest credentials; Redis has no authentication/TLS. Images do not switch to non-root runtime users. Access JWT state is in a JavaScript-managed cookie and refresh state in `localStorage`; the cookie is SameSite=Lax but cannot be HttpOnly and is not marked Secure. No CSP/HSTS/frame-ancestor/nosniff header set was found.

**Attack sequence.** This is not classified as a current Internet vulnerability because repository documentation frames Compose and browser storage as university-demo/local behavior. If the profile is placed on a reachable server, network clients can reach stateful services and HTTP traffic lacks transport security. Any future same-origin XSS would be able to read refresh/access material. An external avatar/wallpaper URL can also make a user's browser contact a third-party host and disclose ordinary network/referrer metadata; no authorization header is attached to those external URLs.

**Expected vs actual.** Expected for production: only a TLS reverse proxy is exposed; stateful services remain private/authenticated; containers are least-privilege; browser session credentials are HttpOnly/CSRF-aware; response headers reduce injection impact. Actual: local-demo defaults.

**Impact.** High consequence if misdeployed, but Low as a repository finding because the limitation is disclosed and requires an unsafe deployment decision. It is still a production launch blocker.

**Existing tests.** Compose rendering and frontend typecheck pass. No production deployment policy or browser header test exists.

**Recommended direction.** Keep the demo profile, add a separate hardened production profile/runbook, bind development ports to loopback, use unique service credentials and private networks, terminate TLS, drop root/capabilities, configure security headers, and migrate sessions to Secure HttpOnly cookies with CSRF protection.

## 8. Race-condition findings

| Race | Result | Severity/meaning |
|---|---|---|
| Two concurrent first upload PUTs | **Protected.** PostgreSQL row locking serializes them; live result was one stored and one `409 UPLOAD_IMMUTABLE`. | Verified Phase 1 control |
| Crash after file link but before DB commit | Handled exceptions unlink the final file; hard process death can leave an immutable orphan and pending DB marker. | Operational availability gap |
| Two refreshes with the same refresh token | **Protected.** Session-row `FOR UPDATE` makes the second observe rotated hash/replay state. | Verified Phase 2 control |
| Refresh replay plus audit failure | **Protected.** Family revocation is committed before best-effort replay audit. | Verified Phase 2 control |
| Seen 100 vs 110 | **Protected.** Membership/state locks and monotonic update prevent regression. | Verified Phase 3 control |
| Concurrent identical reaction adds / variety cap | **Protected.** Message lock plus unique constraint serializes the check. | Verified Phase 3 control |
| Channel/invite/upload count quotas | **Protected on normal application paths.** The user row is locked before the count/insert. | Soft abuse boundary; direct DB writes excluded |
| WebSocket connection quota | Atomic within one `WSManager`, but per process. | Distributed quota weakness, not a single-process race |
| Invite accept vs revoke | **Race remains.** Neither transaction locks or atomically claims lifecycle state. | AV-06, Medium |
| Old bind retry vs newer unbind | **Race/order defect remains.** Execution order, not DB membership generation, determines broker state. | AV-01, High |
| Slug/restore DB commit vs broker update | **Consistency gap remains.** Broker failure occurs after committed state. | AV-08, Medium |

Normal in-flight request behavior was not mislabeled: if a sensitive HTTP request fully authenticates before logout, that request may complete. Subsequent requests fail session validation; no durable post-revocation REST privilege was found.

## 9. Distributed-systems findings

PostgreSQL remains the authoritative state and message history. Message publication correctly commits message, encrypted content, audit event, and message-delivery outbox together. Most membership mutations also commit their membership update and broker-binding command together.

The remaining broker problem is semantic, not merely durability: the outbox stores commands, while security requires desired state. Rabbit bind/unbind is individually idempotent, but opposite operations are not commutative. `FOR UPDATE SKIP LOCKED` and retry scheduling make old-bind-after-new-unbind feasible. A versioned reconcile record or current-state check is required.

Two topology paths still bypass the durable mechanism: channel slug update and superadmin restore. Reconnection adds current bindings but does not enumerate/remove stale ones, so it is not full reconciliation.

Rabbit queue arguments match between backend and worker. Queue expiration, per-message TTL, maximum length, and drop-head limit disk/backlog growth. An existing queue declared with legacy arguments will cause a visible precondition failure rather than silently accepting mixed policies. This requires an operator migration/reset.

Redis fanout retry is scoped per user's consumer task and uses three paced attempts with bounded exponential delay. It therefore does not synchronously block every user. However, there is no explicit AMQP QoS/prefetch configuration in the consumer path; a Redis outage can leave many unacked deliveries and repeated per-user requeues. No live outage/load test quantified the buildup.

Redis presence tracking has an additional reliability defect: every socket disconnect calls `mark_user_offline` even if the same user has another socket on that backend. That can stop the worker's online consumer while a second socket remains connected until another connection refreshes presence. This affects realtime availability, not authorization, and is recorded as an informational distributed-systems issue rather than included in severity counts.

Redis auth-control and membership delivery are pub/sub-style ephemeral signals. Duplication is safe; loss is not repaired for active sockets. Session expiry provides a 30-minute default upper bound for missed session-revocation control. Membership loss is more sensitive because it combines with broker stale binding state at the plaintext delivery boundary.

## 10. Authorization matrix review

Legend: `Yes` is allowed; `Conditional` depends on granular permission, authorship, or public metadata policy; `No` is rejected by current server-side logic.

| Operation | Owner | Admin | Member | Pending | Outsider |
|---|---:|---:|---:|---:|---:|
| Read channel messages/history | Yes | Yes | Yes | No | No |
| View public channel metadata/discovery | Yes | Yes | Yes | Limited | Yes, public metadata only |
| View private channel metadata | Yes | Yes | Yes | No | No |
| Publish top-level message | Yes | Conditional: `can_publish` | No | No | No |
| Publish reply | Yes | Conditional: `can_publish` | Yes, only with valid reply target | No | No |
| Edit/delete own message | Yes | Yes | Yes | No | No |
| Edit/delete another user's message | Yes | Yes | No | No | No |
| React/mark seen | Yes | Yes | Yes | No | No |
| Pin/unpin | Yes | Yes | No | No | No |
| Edit channel | Yes | Conditional: `can_edit_channel` | No | No | No |
| Delete channel | Yes | No | No | No | No |
| Create/revoke/list invites | Yes | Conditional: `can_invite` | No | No | No |
| Approve pending | Yes | Conditional: `can_approve` | No | No | No |
| Add/manage/remove members | Yes | Conditional: `can_manage_members`; cannot remove owner/admin | No | No | No |
| Promote/demote admins | Yes | No | No | No | No |
| Leave | Owner must transfer first | Yes | Yes | Yes | N/A |
| REST sync | Current approved channels | Current approved channels | Current approved channels | No channel data | No channel data |
| WebSocket subscribe/resume | Current approved channels | Current approved channels | Current approved channels | Denied by intersection | Denied by intersection |
| Attachment GET | Yes if owner/eligible channel/avatar | Eligible | Eligible | No | No, except public-avatar policy |

Overall RBAC is credible and no direct IDOR/BOLA was found for ordinary current-state requests. Important qualifications:

- channel admins can edit/delete other users' messages and pin regardless of the sparse admin permission object; this is the current role model, not a bypass of a documented `can_moderate_messages` flag because no such flag exists;
- soft-deleted channel attachment access violates the otherwise consistent channel lifecycle (AV-05);
- invite revocation is not a linearizable boundary (AV-06);
- cached WebSocket subscriptions make removed-member confidentiality depend on delivery of a membership update (AV-01);
- the upload owner can always retrieve their own upload, even if its linked channel/message is later deleted. That is explicit ownership policy and should be documented if retained.

## 11. Abuse/DoS review

Controls that appear effective:

- authentication endpoints combine IP and normalized identity keys;
- rate-limit identity does not trust arbitrary forwarding headers;
- message text and JSON bytes are bounded before encryption/outbox work;
- JSON depth is checked iteratively and 64 KiB bounds realistic node width;
- channel cursor arrays and response counts are schema-bounded;
- reaction variety and duplicate additions are serialized;
- seen advancement is monotonic;
- channel/invite/upload quotas lock the user row;
- upload writes stream in bounded chunks and enforce declared/configured sizes;
- user Rabbit queues have expiry, TTL, and length caps;
- Redis retry uses bounded attempts/backoff.

Controls that remain bypassable or incomplete:

- `/sync` response length does not bound DB/memory work (AV-02);
- media request count does not prevent concurrent full-file memory amplification (AV-03);
- established WebSocket commands have no rate/work budget (AV-04);
- the Redis-outage LRU fallback can be deliberately reset (AV-07);
- all fallback and WebSocket-connection limits are per backend instance;
- abandoned upload reservations and files have no automatic GC; an attacker can permanently exhaust their own 1 GiB reservation/account limits and generate cleanup work;
- no reverse-proxy/server-wide request-body, connection, bandwidth, or slow-client policy is present in the repository;
- health status exposes dependency availability booleans without authentication. This is limited operational leakage, not a material exploit by itself.

## 12. Frontend/session exposure

The frontend stores the refresh token in `localStorage` and mirrors access state into a JavaScript-managed cookie. SameSite=Lax is set, but the cookie is neither Secure nor HttpOnly. This is accurately documented as demo-grade. A stolen current refresh token can rotate a session; reuse of an old token triggers family revocation. Access JWTs remain bounded by their session and expiry.

WebSocket handling is improved: the frontend obtains a short-lived opaque ticket and places that ticket—not the access JWT—in the WS URL. Atomic server-side consumption and DB revalidation limit ticket theft/reuse.

No realistic application-controlled XSS path was found in the inspected UI:

- message text, filenames, event fields, and profile/channel strings are rendered through React escaping;
- the only `dangerouslySetInnerHTML` occurrence is a generic chart CSS-variable helper, and no user-data call site for it was found;
- no unsafe `javascript:` URL acceptance was found in validated avatar/wallpaper schemas;
- protected same-origin uploads are fetched with authorization and converted to object URLs;
- external `http(s)` avatar/wallpaper URLs are loaded without the API Authorization header, so they do not directly exfiltrate tokens, though they expose the viewer's network/referrer metadata to the external host;
- the middleware's local `next` parameter was not consumed as an arbitrary redirect target by the login flow; no open redirect was demonstrated.

Forgeable client cookies can influence UI routing/role presentation but are not backend authorization boundaries. Missing CSP, frame restrictions, HSTS, and `nosniff` increase the impact of a future frontend injection or unsafe deployment and belong in production hardening.

## 13. Deployment blockers

### Development-only conveniences when confined to a local supervisor demo

- published ports for PostgreSQL, RabbitMQ management/broker, Redis, backend, and frontend;
- `postgres/postgres`, Rabbit guest credentials, unauthenticated Redis;
- plain HTTP URLs;
- root runtime users and build tools retained in Python runtime images;
- verbose dependency health status;
- JavaScript-readable session credentials;
- development secret placeholders in `.env.example` (the real `.env` is untracked and `.gitignore` protection is present).

These are acceptable only on a trusted, firewalled/loopback demo host. Compose currently binds published ports to all interfaces, not explicitly to `127.0.0.1`.

### Production security blockers

Before any Internet/reachable-host deployment:

1. expose only a hardened TLS reverse proxy; keep DB/Redis/Rabbit on private networks or loopback;
2. replace all default service credentials, enable appropriate Redis/Rabbit authentication, and manage secrets outside Compose/source;
3. make unknown environment modes fail safe and validate all production secrets;
4. migrate browser sessions to Secure HttpOnly cookies with a CSRF-aware design;
5. add CSP, frame-ancestor/frame-options, HSTS, `nosniff`, and a deliberate referrer policy;
6. run containers as non-root with reduced capabilities/read-only filesystems where practical;
7. add reverse-proxy request/body/concurrency/timeouts and media bandwidth limits;
8. fix AV-01 through AV-08 and monitor outbox, retry, DLQ, queue depth, Redis failures, and process memory;
9. define backup, key rotation, upload GC, and legacy Rabbit queue migration procedures.

## 14. Tests/experiments run

All PostgreSQL experiments used the disposable container `messaging-phase4-audit-postgres` (`postgres:16`) on loopback port `55439`, database `channels_audit`. It did not use or alter developer data and was removed after testing.

### Repository and configuration checks

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git log --oneline --decorate -n 8
git diff --check
git ls-files --error-unmatch .env
```

Actual result: initial status was empty; branch/commit matched section 2; `git diff --check` passed; `.env` is not tracked.

```powershell
docker compose config --quiet
```

Actual result: exit code 0.

```powershell
docker compose ps
```

Actual result: no project application services were running, so live HTTP/Rabbit/Redis tests were not performed against the developer stack.

### Disposable database and migration

```powershell
docker run --name messaging-phase4-audit-postgres -e POSTGRES_DB=channels_audit -e POSTGRES_USER=audit_user -e POSTGRES_PASSWORD=audit_password -p 127.0.0.1:55439:5432 -d postgres:16
```

Actual result: disposable PostgreSQL started and became ready. An initial attempt on port `55435` found that host port occupied; that failed container was removed before retrying on `55439`.

```powershell
$env:DATABASE_URL='postgresql+asyncpg://audit_user:audit_password@127.0.0.1:55439/channels_audit'
$env:ENVIRONMENT='test'
$env:JWT_SECRET='test-secret'
$env:MESSAGE_ENCRYPTION_ENABLED='true'
$env:MESSAGE_ENCRYPTION_KEY='MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY='
python -B -m alembic upgrade head
```

Actual result: migrations `0001` through `0018_phase3_abuse_hardening` applied successfully to a fresh database.

### Backend and frontend regression suites

```powershell
$env:DATABASE_URL='postgresql+asyncpg://audit_user:audit_password@127.0.0.1:55439/channels_audit'
$env:ENVIRONMENT='test'
$env:JWT_SECRET='test-secret'
$env:MESSAGE_ENCRYPTION_ENABLED='true'
$env:MESSAGE_ENCRYPTION_KEY='MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY='
python -B -m pytest -q
```

Run from `backend`. Actual result: **143 passed, 1 warning in 73.75s**. The warning is the existing passlib access to deprecated `argon2.__version__`.

```powershell
npm run typecheck
```

Run from `frontend`. Actual result: exit code 0, no TypeScript errors.

### Adversarial diagnostics

The diagnostics were supplied to `python -B -` through PowerShell here-strings and created no repository files.

1. **Fallback limiter eviction.** An always-failing Redis stub hit `target` with limit 1, confirmed the second hit was blocked, inserted 10,000 distinct local keys, and hit `target` again.

   Invocation wrapper (the ephemeral inline body was not persisted, so it is described above rather than reconstructed as an allegedly exact script):

   ```powershell
   @'<inline async Python using RateLimitService.hit(...)>'@ | python -B -
   ```

   Actual output:

   ```text
   {'first': None, 'blocked': 59, 'keys': 10000, 'after_churn': None}
   ```

2. **Deleted-channel attachment authorization and concurrent invite state.** An isolated async SQLAlchemy harness created users/channel/memberships/message/upload/relation, soft-deleted the channel, invoked `MessageService.can_access_upload`, and synchronized two `accept_invite` transactions before commit. Audit/outbox side effects were monkeypatched only inside the disposable process to isolate the state transition; no repository code was edited.

   Invocation wrapper (the ephemeral inline body was not persisted; the state setup and calls are described above):

   ```powershell
   @'<inline async SQLAlchemy attack harness>'@ | python -B -
   ```

   Actual security-relevant output (nondeterministic UUIDs omitted):

   ```text
   {'deleted_channel_attachment_access': True,
    'concurrent_invite_results': ['<membership A>', '<membership B>'],
    'non_owner_members_joined': 2}
   ```

3. **Concurrent first upload PUT.** Two independent async DB sessions were released together against one pending upload, each streaming the same four bytes. A temporary upload directory was created outside the repository and automatically removed.

   Invocation wrapper (the complete ephemeral harness behavior and inputs are described above):

   ```powershell
   @'<inline async two-session upload harness>'@ | python -B -
   ```

   Actual output:

   ```text
   {'concurrent_upload_results': [['a', 'stored'], ['b', 409, 'UPLOAD_IMMUTABLE']]}
   ```

   A first experimental design placed a barrier inside the stream after the row lock and therefore deadlocked by construction; it was terminated and discarded as invalid evidence. A subsequent harness setup initially inserted an upload before its directly-added user was flushed and correctly failed its FK; splitting those setup commits fixed the harness. Neither failed setup is treated as a product finding.

4. **Environment aliases.** Direct `Settings` construction tested the same placeholder under four environment names:

   ```powershell
   @'
   from pydantic import ValidationError
   from app.core.config import Settings
   results = {}
   for environment in ("production", "prod", "staging", "live"):
       try:
           Settings(environment=environment, jwt_secret="change-me", message_encryption_enabled=False)
           results[environment] = "accepted"
       except ValidationError:
           results[environment] = "rejected"
   print(results)
   '@ | python -B -
   ```

   Actual output:

   ```text
   {'production': 'rejected', 'prod': 'rejected', 'staging': 'rejected', 'live': 'accepted'}
   ```

### Cleanup

```powershell
docker inspect --format '{{.Name}} {{.Config.Image}} {{.State.Status}}' messaging-phase4-audit-postgres
docker rm -f messaging-phase4-audit-postgres
```

Actual result: the exact audit container was verified as `/messaging-phase4-audit-postgres postgres:16 running`, then removed. No developer container/data was removed.

## 15. Things that could not be verified

- A real two-backend deployment was not available, so cross-instance WebSocket quotas, ticket consumption, revocation delivery, and local-fallback divergence were reasoned from code/tests rather than live load.
- RabbitMQ/Redis/backend/worker were not running as a full project stack. No real broker outage, Redis outage, legacy-queue declaration conflict, delayed-binding replay, unacked-delivery buildup, or pub/sub message-loss experiment was run.
- AV-01's component behaviors are directly visible, but the complete multi-failure confidentiality sequence was not reproduced end to end.
- Invite accept-versus-revoke was not live-interleaved; the lack of a lock/atomic claim and concurrent dual acceptance were verified.
- No live maximum-size, 60-way, slow-client attachment download was run because intentionally forcing process OOM would be destructive. AV-03 follows directly from full-file allocation and configured limits.
- No high-volume historical `/sync` benchmark was run. AV-02 follows directly from the unbounded SQL queries and materialization before slicing.
- Uvicorn/proxy frame/body buffering and limits outside repository configuration were not assumed. No reverse proxy is defined in the repository.
- Crash-at-instruction-boundary upload behavior was not simulated with process termination; handled failures and concurrency were verified.
- No browser E2E/CSP scanner was run. The frontend review was source inspection plus TypeScript typecheck, not proof against every browser-specific injection behavior.
- External host firewalling, cloud security groups, secret rotation, TLS termination, backups, and production environment variables are outside the reviewed repository state.
- Dependency vulnerability/SBOM scanning was not part of this focused audit; versions were not declared vulnerability-free.

## 16. Recommended Phase 4

### P0 — resolve the High findings before any production claim

1. Replace broker action replay with versioned desired-state reconciliation. Make the worker validate current membership/channel state and generation, serialize user/channel ordering, remove stale bindings, and add an old-bind/new-unbind/retry integration test. Add a durable or DB-revalidated WebSocket membership boundary so a missed pub/sub event cannot expose plaintext.
2. Redesign `/sync` so SQL rows, Python objects, decryption, and sorting are strictly bounded by the requested page. Add large-history/100-channel query-budget tests.
3. Stream upload downloads with backpressure and add per-user/IP concurrent-download/bandwidth protections. Test maximum-size concurrent and aborted downloads without buffering.

### P1 — close meaningful Medium gaps

1. Rate-limit and backpressure established WebSocket commands; cap total subscribe-history work and inbound frame size.
2. Enforce active-channel state for attachment reads and define owner/media behavior across delete/restore.
3. Define generic versus one-use invite semantics and make accept/revoke an atomic state transition.
4. Make slug changes and channel restore enqueue durable desired broker state in the same DB transaction.
5. Redesign Redis-outage limiting so saturation cannot reset sensitive keys; make Redis counter+TTL atomic; add multi-instance/outage tests.
6. Add explicit Rabbit QoS/prefetch and load-test Redis failure, requeue pacing, and unacked buildup.

### P2 — defense-in-depth and production readiness

1. Enforce relational attachment/message/channel consistency at the database layer after an integrity audit.
2. Fail safe for unknown environment labels.
3. Add upload reservation/temp/final orphan reclamation and administrative quota recovery.
4. Correct multi-socket online presence tracking with reference counting/leases.
5. Create a separate hardened production deployment profile: TLS/private networks, secrets, non-root containers, security headers, proxy limits, monitoring, backup, and key rotation.
6. Move browser sessions to Secure HttpOnly cookies with CSRF-aware flows and add browser security/E2E tests.
7. Add dependency/SBOM scanning and a small repeatable two-backend Rabbit/Redis/PostgreSQL security integration environment.

## 17. Final conclusion

Phases 1–3 produced a substantially stronger and defensible university MVP. Core REST authorization, session-bound authentication, refresh replay handling, one-time WebSocket tickets, immutable upload writes, payload validation, principal quotas, and transactional message persistence are real controls rather than documentation-only claims.

Security maturity remains below production readiness because resource limits do not bound `/sync` and download work, established WebSockets bypass command throttles, and broker membership is modeled as reorderable historical commands. The stale-binding issue is the most important: under partial infrastructure failure it can turn a delivery-reliability defect into removed-member message disclosure. Phase 4 should address the three P0 items before additional features or security claims.
