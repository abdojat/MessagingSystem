# Security Verification After Phase 5

## 1. Executive verdict

**PASS WITH FINDINGS**

The Phase 4 desired-state broker projection, stale-generation rejection, WebSocket final-delivery check, global sync row cap, and streamed-response lease are materially stronger than the pre-Phase-4 design. The Phase 5 WebSocket budgets, active-reference media checks, invite row locking, and bounded rate-limit fallback are also present and generally operate as described.

The audit nevertheless found two Medium and two new Low issues. Most importantly, an email-targeted invite is bound only to the current mutable, unverified `User.email` value. A live PostgreSQL experiment showed that after the invited address was moved from the intended user to a different account through the normal profile-update path, the different account successfully accepted the private-channel invite. The download limiter also remains susceptible to account-multiplied slow-client resource exhaustion in the canonical direct-backend deployment.

Open finding count, including retained AV-09/AV-10/AV-11: **0 Critical, 0 High, 2 Medium, 5 Low**. Informational reliability and deployment limitations are listed separately and are not included in that count.

This verdict does not mean that the application is secure or production-ready. It means the principal Phase 4 broker ordering invariant resisted source review and a live RabbitMQ scenario, while several meaningful boundary conditions remain.

## 2. Repository/version reviewed

- Repository: `https://github.com/abdojat/MessagingSystem`
- Branch: `master`
- HEAD: `a6c4ba34736237eee8f788ff59058b05a2dc33f3`
- Starting `git status --short`: empty (clean)
- The six Phase 1-5 hardening/verification reports were read before the independent implementation review.
- Disposable PostgreSQL 16, Redis 7, and RabbitMQ 3.13 containers were used. They did not use or modify developer data.
- No implementation, test, migration, or existing documentation file was changed. This report is the only repository artifact created by the audit.

## 3. Phase 4 verification

| Control | Result | Evidence and qualification |
|---|---|---|
| Broker generations/state creation | **VERIFIED** | `Channel.membership_generation`, `BrokerBindingState`, migration `0019`, `OutboxService`, and all normal join/accept/approve/add/remove/leave/role/delete/restore paths were traced. Membership-affecting paths update state in the same DB transaction. No normal restoration/ownership-transfer path was found outside these services. |
| Stale worker ordering | **VERIFIED** | `_apply_broker_binding` locks the durable pair state, accepts only exact current generation, and re-derives eligibility from current channel and membership rows. A live RabbitMQ run returned `stale_generation` for delayed bind and unbind commands while current g3/g4/g5 projections won. Rabbit-before-DB crash replay is idempotent. |
| Slug A -> B -> C | **VERIFIED** | Historical keys remain until successful projection. A live RabbitMQ run with A/B/C in `routing_keys` ignored stale generation B, removed A and B, and delivered only through C. DB pruning occurs after Rabbit operations in the worker transaction. |
| Delete/restore ordering | **PARTIALLY VERIFIED** | Source and regression tests show generation changes plus a full desired-state projection. An older delete/restore reconciliation cannot override a newer state generation. The exact delete/restore sequence was not repeated live against RabbitMQ. A previously dead-lettered unbind for a no-longer-approved pair is not automatically re-enqueued by every later channel transition; WS/REST authorization still prevents plaintext disclosure, but stale broker resource cleanup can require reconnect/reconciliation or operator retry. |
| WebSocket final authorization | **PARTIALLY VERIFIED** | Sensitive message events carry membership generation, and missing/newer/malformed values force a DB authorization check before decryption. A matching/older event may use the documented short cache. A pre-removal g5 event can therefore be delivered shortly after g6 removal; post-removal events carrying g6 force revalidation and were not found to leak. Redis loss can still delay cross-instance logout/deactivation enforcement until access-token expiry. |
| `/sync` work bound | **PARTIALLY VERIFIED** | Every message query receives the decreasing global remaining limit (maximum 500), and sender/reaction/decryption enrichment is bounded by returned rows. Up to 100 channel views are separately bounded. Deterministic UUID ordering can starve a later selected channel while an earlier channel continually fills the entire page; selecting/syncing the later channel separately avoids permanent loss, but there is no fair/global cursor. |
| Streamed download/lease | **PARTIALLY VERIFIED** | `LeasedFileResponse.__call__` releases its idempotent lease in `finally`, covering stat/open/stream/send/cancellation failures after response construction; route exceptions before return also release. Starlette 1.0.0 was inspected locally and streams rather than fully buffering. The per-user, per-process lease does not bound aggregate slow clients across many registered accounts (P5V-02). |

## 4. Phase 5 verification

| Prior issue/control | Result | Evidence and qualification |
|---|---|---|
| AV-04 WebSocket work budgets | **PARTIALLY VERIFIED** | Frame size, weighted command tokens, serialized per-socket dispatch, and history-row tokens are enforced. Equivalent subscribe lists are canonicalized, and WS `sync` performs no DB sync. Defaults allow 300 history rows per fresh socket. With 30 tickets and 30 connection attempts per minute, sequential reconnects can request about 9,000 rows/decryptions per minute per account and source IP; five concurrent sockets allow 1,500 initial rows. Multiple sessions do not multiply the per-user keys, but multiple backend processes multiply active-socket and per-socket budgets. This is bounded defense-in-depth rather than a demonstrated strong service-wide DoS. |
| AV-05 deleted-channel attachment access | **VERIFIED** | Non-owner access requires at least one active authorized message/channel or permitted avatar/profile relationship. The query uses ANY valid active reference, so an upload reused in a deleted and active channel remains available only through the valid active relationship. Owners intentionally retain access. Attachment bytes remain unencrypted, as documented. |
| AV-06 invite atomicity | **BYPASS FOUND** | Channel-then-invite locking prevents the tested accept/revoke/delete ordering races and generic links remain reusable. However, email-target identity is mutable and unverified; P5V-01 allowed the wrong account to consume a targeted invite. |
| AV-07 rate-limit fallback | **VERIFIED** | The Redis Lua fixed window atomically increments and establishes/repairs TTL. The local fallback has one heap entry per admitted window, monotonic time, bounded keys, and fail-closed unseen-key saturation. Live Redis confirmed limit and TTL behavior; live outage simulation confirmed independent local allowance and fail-closed saturation. Store transitions can provide up to one Redis allowance plus one local allowance, and local state multiplies per backend process. |

## 5. New findings

| ID | Severity | Component | Finding | Prerequisite | Impact | Confidence |
|---|---|---|---|---|---|---|
| P5V-01 | Medium | Invites/account identity | Email-targeted invites follow a mutable, unverified email string and can be accepted by a later account holding that string | Valid invite token plus ability to claim/reclaim the target email; public accounts/profile email changes | Wrong account joins a private channel | Confirmed live |
| P5V-02 | Medium | Protected downloads | Per-user/per-process leases do not bound aggregate slow streams; public accounts multiply held sockets/file descriptors | Authenticated accounts, one accessible file, direct/weakly proxied backend, slow clients | Sustained service resource exhaustion | High source confidence; not load-tested |
| P5V-03 | Low | DB locking/event audit | Advisory event-chain locks and row locks are acquired in inconsistent orders, producing real deadlock cycles | Concurrent topology/admin work, especially while worker reconciliation fails | Transaction aborts; attacker can amplify availability failures | Confirmed with live PostgreSQL lock cycle |
| P5V-04 | Low | Authentication input limits | Login/refresh/logout strings and raw HTTP request bodies lack application/deployment size bounds; failed-login identity is persisted | Unauthenticated direct backend access | Bandwidth-proportional memory/DB-log pressure and oversized limiter keys | High source confidence; not stress-tested |

Retained findings AV-09, AV-10, and AV-11 remain Low and are counted in the executive total but are not relabeled as new findings.

## 6. Detailed findings

### P5V-01 - Email-targeted invite can transfer to the wrong account (Medium)

- **Files/functions:** `backend/app/schemas/channels.py::InviteRequest`; `backend/app/services/channel_service.py::create_invite`, `_validate_invite`, and `accept_invite`; `backend/app/api/routes/users.py::update_me`; `backend/app/schemas/users.py::UpdateMeRequest`.
- **Root cause:** An email invite stores only `invited_email`. Acceptance compares it with the accepting account's current `User.email`. Profile update permits changing that unique email without mailbox verification or binding an existing target to `invited_user_id` when the invite is created.
- **Attack sequence:** An owner creates a private-channel invite for an intended user's email. The intended account changes away from that address (or the address was initially unclaimed). A different account claims the old address through `PATCH /me`, obtains/retains the invite token, and accepts it. Preview also discloses the targeted address to a token holder.
- **Expected:** A targeted invite should remain bound to the intended immutable identity, or acceptance should require verified ownership of the intended mailbox under explicit transfer semantics.
- **Actual:** In disposable PostgreSQL, the normal update function moved the target email to an attacker account; `accept_invite` returned a `member` membership for the attacker and consumed the invite.
- **Impact:** Unauthorized membership and subsequent private channel/message/attachment access.
- **Existing tests:** Phase 5 tests cover accept/revoke atomicity, user-ID matching, generic reuse, and exact email matching, but not email reassignment between issuance and acceptance.
- **Recommended direction:** Resolve existing target addresses to immutable user IDs at issuance; normalize consistently; introduce verified-email state and verification for changes; define behavior for pre-registration invitations. Preserve generic-link semantics separately.

### P5V-02 - Slow protected downloads can exhaust aggregate service resources (Medium)

- **Files/functions:** `backend/app/services/download_service.py::DownloadConcurrencyLimiter`, `DownloadLease`, `LeasedFileResponse`; `backend/app/api/routes/messages.py::download_upload`; canonical backend exposure in `docker-compose.yml` and `backend/Dockerfile`.
- **Root cause:** The limit is three leases per user per backend process. A stream holds the lease, file descriptor, and socket until ASGI completion, with no application-wide/IP limit or response-duration/minimum-throughput bound. Public registration lets one actor multiply the per-user allowance.
- **Attack sequence:** Register many accounts, make one file accessible through an allowed avatar/public relationship (or create per-account uploads), open three protected downloads per account, and read extremely slowly. Repeat across backend processes.
- **Expected:** Aggregate server resources should remain bounded even when authorized clients do not consume response bodies.
- **Actual:** Each identity is bounded, but aggregate identities, instances, and stream duration are not. The canonical Compose backend is published directly on port 8000, so the reverse-proxy assumption is not inherent to that run path.
- **Impact:** Sustained socket/file-descriptor/worker pressure and eventual availability loss under realistic authenticated abuse.
- **Existing tests:** Unit/regression tests cover admission boundaries and exact-once release on normal/error/cancellation paths; no many-account slow-reader load test exists.
- **Recommended direction:** Put a configured reverse proxy in the canonical deployment with header/body/idle/minimum-rate/time limits; add per-IP and process/global download admission, total duration/throughput policy, and operational FD/socket limits. Retain exact-once lease release.

### P5V-03 - Inconsistent lock ordering permits deadlocks (Low)

- **Files/functions:** `backend/app/services/event_service.py::log_event`; `EventIntegrityService.lock_scope`; membership/channel service paths; `OutboxService.enqueue_broker_binding_outbox`; `worker/worker_app/outbox_runner.py::_apply_broker_binding` and failure logging.
- **Root cause:** Application paths can hold the channel event advisory lock before waiting for `Channel`/`BrokerBindingState`, while the worker holds `BrokerBindingState` and, on Rabbit failure, waits for the same advisory lock. Other paths use Channel -> advisory while membership operations can reach membership/advisory -> Channel.
- **Attack sequence:** Concurrent topology mutation holds the channel advisory lock and waits for its binding-state row. A worker reconciliation holds that row, hits Rabbit failure, and attempts `broker.publish_failed` event logging, which waits for the advisory lock. PostgreSQL detects and aborts a transaction. Concurrent delete and member changes have another Channel/advisory inversion.
- **Expected:** A global order should prevent user-amplifiable cyclic waits.
- **Actual:** A disposable PostgreSQL two-session experiment using the exact advisory scope and binding-state row produced `DeadlockDetectedError` for one transaction.
- **Impact:** Rollback/retry generally preserves authorization and desired state, but repeated concurrent requests or broker failure can increase errors, audit gaps for the aborted attempt, and recovery latency.
- **Existing tests:** Deterministic invite locks are covered; global advisory/row ordering and multi-worker deadlocks are not.
- **Recommended direction:** Define one lock order for User/Channel/Membership/Invite/BindingState/event scope; avoid taking the event advisory lock while holding worker projection rows during external failure handling; add retry for serialization/deadlock errors and multi-session regression tests.

### P5V-04 - Oversized unauthenticated auth inputs are not bounded (Low)

- **Files/functions:** `backend/app/schemas/auth.py::LoginRequest`, `RefreshRequest`, `LogoutRequest`; `backend/app/api/routes/auth.py::login`; `backend/app/services/rate_limit_service.py`; `backend/Dockerfile`.
- **Root cause:** Unlike registration fields, login identity/password and refresh-token strings have no `max_length`. The raw JSON body is parsed before route rate limiting. Failed login stores the normalized identity in the event JSON. No request-body limit is configured in the canonical direct Uvicorn command.
- **Attack sequence:** Send concurrent very large JSON strings to `/login`; parsing/allocation occurs before IP/identity limiting, and admitted invalid attempts can also create very large rate-limit keys and persistent audit payloads. Refresh/logout accept similarly unbounded tokens.
- **Expected:** Authentication inputs and request bodies should be rejected at small explicit limits before expensive parsing/persistence where possible.
- **Actual:** Only request frequency is bounded after parsing; size is not.
- **Impact:** Bandwidth-proportional memory pressure and bounded-frequency but potentially large DB/audit growth. No amplification to Critical/High impact was demonstrated.
- **Existing tests:** Normal validation and rate-limit tests exist; oversized body/field tests do not.
- **Recommended direction:** Add schema maxima consistent with username/email/JWT formats, truncate/hash security-log identities, and enforce proxy/server body limits in the canonical deployment.

## 7. Broker/distributed-systems review

The desired-state pair `(channel_id, user_id)` is the PostgreSQL authority. Each worker locks that row, compares exact generation, validates broker-safe identifiers, and independently recomputes `actual_desired_bound` from current channel deletion state and membership role. Thus a tampered desired flag alone cannot grant a binding.

Normal current-state transitions inspected were channel creation, direct/open join, invite join/accept, pending approval, admin add/remove, leave, role/permission changes, delete, restore, and slug update. Eligibility changes call the membership update helper, which increments channel membership generation and enqueues pair state in the same transaction. Slug change does not increment membership generation because access does not change, but it increments each binding-state generation. No owner-transfer or membership-restoration endpoint exists.

The live RabbitMQ sequence demonstrated:

- delayed bind g1 against current g3: `stale_generation`;
- current g3: bound and delivered;
- delayed g3 after current unbound g4: stale, while g4 removed delivery;
- delayed unbind g4 after rejoin g5: stale, while g5 restored delivery;
- A/B/C known keys with stale g6/current g7: A false, B false, C true.

Rabbit operations precede `reconciled_generation`/routing-key pruning. A worker crash after Rabbit success rolls back the DB transaction and causes an idempotent full projection on retry. Publisher/consumer semantics remain at-least-once; message IDs and client handling must tolerate duplicates. A worker transaction holds DB locks while awaiting Rabbit, which preserves ordering but lengthens contention and participates in P5V-03.

## 8. WebSocket security review

Final delivery, not subscription bookkeeping, is treated as the confidentiality boundary. New/edit/delete/pin/reaction/reply paths use outbox helpers that overwrite event generation from the locked channel. Legacy or malformed missing generation does not get cache permission; it forces DB authorization. For cached generation 10, events 9 and 10 can use a fresh cache, event 11 queries DB and is rejected if DB is below 11, and missing values query DB. Integer conversion accepts integer-like strings, but no attacker-controlled event publisher was found.

The one-second default cache permits a queued pre-removal message to arrive after removal. This is a documented historical/in-flight delivery choice. A message created after removal carries the bumped generation and cannot use the older cache. Channel deletion/removal/reconnect/backend restart force or rebuild state. Redis membership notification loss is compensated by event generation for channel delivery; Redis auth-control loss is different and can leave a revoked/deactivated socket on another backend usable until its short access token expires.

WS work is serial per socket. Inbound application validation rejects more than 16 KiB before JSON work, and Docker passes the same `--ws-max-size`; installed Uvicorn 0.46.0 with `websockets` 16.0 supports the option. Dependency specifications are minimum ranges, so future builds can drift and should remain tested.

`subscribe` canonicalizes a set of UUIDs, so order, duplicates, and accepted textual variants do not defeat identical-request optimization. Subscribe/resume share history tokens; alternating commands/cursors cannot exceed the socket's row budget. WS `sync` only returns a REST-use error and does not query/decrypt. Reconnect gives fresh tokens; global ticket/IP attempt limits bound one account/IP to about 30 fresh sockets and 9,000 initial history rows per minute. Five active sockets are per user per backend, not per login session; N backend instances permit roughly `5N` active sockets and independent work buckets.

## 9. Sync/performance review

`MessageService.sync` accepts at most 100 channel cursors and 500 total messages. Each channel SQL query is called with the decreasing remaining limit; sender enrichment is one bounded query, reaction summaries use two bounded queries, and decryption/serialization touches at most the returned messages. Membership updates use the request limit. Channel views create up to 100 additional bounded queries, so query count is not constant but input-bounded.

Per-channel cursor semantics handle equal sequence numbers in different channels independently. Missing cursor starts from zero; ahead-of-head returns none; duplicate channel cursor IDs collapse by dictionary assignment (last value wins). A delete/removal racing an in-progress request has request-level authorization timing semantics; a deleted channel retained in the initially selected membership set can make the whole sync fail rather than leak data.

UUID-sorted sequential allocation is not fair. If channel A continually supplies the entire limit, B receives no rows in that response. Advancing A's cursor reaches B only when A contributes fewer than the remaining capacity; a client can explicitly select B to recover. This is an informational correctness/availability limitation, not a confidentiality bypass.

## 10. Media authorization/download review

Metadata and byte routes authenticate and call the same active relationship policy. Owner access is an explicit policy, not a role confused with channel ownership. For non-owners, an upload reused in multiple messages/channels is permitted if ANY relationship is current, active, nondeleted, and authorized. A stale deleted relation does not override a valid relation and does not grant access by itself. Removed members and deleted messages/channels lose relationship-derived access; restoration re-enables access only under current membership. There is no message restore or channel ownership-transfer path to bypass these checks.

Avatar/profile relations are distinct intentional sharing policies. A user avatar is viewable by authenticated users and a channel avatar follows channel visibility/membership. Reusing an attachment upload as a public/profile image can intentionally broaden access, so ownership validation of profile references remains important. Upload paths are contained and do not disclose filesystem paths.

The exact-once lease implementation is sound for inspected Starlette behavior, but P5V-02 leaves aggregate slow-reader pressure unbounded. A stream authorized before removal continues as an in-flight response; it is not reauthorized per chunk. Attachment bytes are not encrypted at rest.

## 11. Invite/concurrency review

Accept, token-join, revoke, and channel delete use channel-then-invite ordering where both rows are locked. Preview/list do not lock or mutate. Generic invites deliberately ignore historical `accepted_at` for reuse but still enforce revoked, expired, and channel-deleted states. The same already-approved user returns without duplicate audit/outbox work. Historical generic rows with `accepted_at` remain reusable only if otherwise active. Restoring a channel also restores still-unexpired/unrevoked generic link utility; this should remain an explicit product policy.

The atomic accept/revoke/delete race fix resisted code review and existing real-PostgreSQL tests. The targeted identity model did not: P5V-01 is a confirmed authorization bypass. User-ID targets remain immutable and safe. Malformed historical rows containing both user ID and email require both comparisons, which fails closed. Create-invite does not lock the channel, so a concurrent delete can leave an unusable invite that may become valid after restore; this is a low-impact lifecycle consistency note rather than immediate access while deleted.

## 12. Rate-limit review

The Lua script performs `INCR`, reads `TTL`, and calls `EXPIRE` for a new key or any key with missing expiry. `TTL=-1` is repaired; `-2` is not reachable after successful `INCR` except unusual concurrent deletion, in which case `ttl < 0` still attempts expiry. Result values are converted to integers and retry-after is at least one second. A transport exception after Redis execution may also consume local allowance, which tightens rather than bypasses the aggregate transition.

Live Redis results for a limit of two were allow, allow, block with retry 30; a deliberately TTL-less key was repaired to TTL 17. Healthy-to-outage transition produced one Redis allowance followed by two local allowances and then a local block for a local limit of two. A three-key local capacity admitted a/b/c and denied unseen d with retry 60. Thus a transition may approximately double a window's allowance, and Redis restart/empty recovery may grant another allowance. Repeated flapping does not continually reset either still-existing store.

The local heap uses monotonic time, adds one expiry entry only when a new key/window is admitted, does not refresh active keys, and purges the matching entry and dictionary record together; memory is O(configured max keys), excluding the bytes of each key. At saturation, a distributed attacker can deny new identities during Redis outage. IP-first auth limiting and the 10,000-key default make one-IP saturation impractical, but many IPs/backend replicas can amplify it. Fail-closed is a defensible security tradeoff and must be operationally monitored.

## 13. Authorization matrix

| Action | Owner | Admin | Member | Pending/removed/outsider | Superadmin |
|---|---|---|---|---|---|
| Read active private channel/history/sync/WS | Yes | Yes | Yes | No | No implicit bypass |
| Publish top-level | Yes | Permission-dependent | `can_publish`/role policy | No | No implicit bypass |
| Reply | Yes | Yes | Approved member under reply policy | No | No implicit bypass |
| Edit/delete message | Own; manage others | Own/manage under policy | Own only | No | No implicit bypass |
| Pin | Yes | Permission-dependent | No | No | No implicit bypass |
| Invite/approve/manage members | Yes | Explicit admin permissions | No | No | Only explicit administrative routes |
| Read protected upload/attachment | Owner or valid relationship | Same | Same | No channel-derived access | No implicit media bypass |
| Deleted channel ordinary access | Blocked except upload-owner policy | Blocked | Blocked | Blocked | Delete/restore administration only |
| Restored channel | Retained approved role | Retained approved role | Retained approved role | Still blocked | No implicit read |

No REST BOLA regression was found in the inspected channel/message/sync/media paths. Pending memberships are not treated as approved. Admin promotion/demotion constraints preserve owner-only control over peer-admin privilege changes. New locks can cause availability failures described in P5V-03, but rollback does not silently weaken authorization.

## 14. Database-lock/deadlock review

Relevant orders include:

1. Membership/topology path: membership or channel work -> channel event advisory lock -> channel/binding state through membership-generation/outbox helpers.
2. Worker failure path: outbox batch -> `BrokerBindingState FOR UPDATE` -> Rabbit operation -> channel event advisory lock for failure logging.
3. Delete path: Channel -> channel event advisory lock -> binding states.
4. Some membership management paths: Membership -> advisory lock -> Channel -> binding state.

Cycle 1 is application advisory -> binding row versus worker binding row -> advisory. It was reproduced against disposable PostgreSQL; one session received `DeadlockDetectedError`. Cycle 2 is delete Channel -> advisory versus membership advisory -> Channel. Multiple workers also hold a batch of state/outbox locks across external Rabbit waits; overlapping batches/reconciliation can add contention, although SKIP LOCKED and pair-row serialization protect current state.

These are Low security severity because PostgreSQL aborts a transaction and desired state rolls back, but a channel admin/member can deliberately add concurrency during broker degradation. No cross-user data exposure or state grant was observed.

## 15. Frontend/session review

The frontend obtains a short-lived opaque one-time WS ticket instead of placing the access JWT in the WebSocket URL. React rendering escapes message/user/channel text. The only `dangerouslySetInnerHTML` occurrence is a static chart-style helper; no user-controlled flow to it was found. URL validation restricts protected media and HTTP(S) URLs, and bearer attachment fetching is limited to the configured API origin/path, so no actual token-exfiltration or script-injection path was demonstrated.

Refresh tokens remain in `localStorage`; access tokens are held in memory plus a JavaScript-managed, non-HttpOnly, non-Secure SameSite cookie for the demo. No production CSP/HSTS/frame/referrer security headers are configured in `next.config`. External HTTP(S) images can disclose client network/referrer information to their hosts but do not receive the API bearer token. These are demo deployment limitations, not an asserted XSS exploit.

## 16. Presence/reliability observations

The previous multi-socket presence bug remains. `WebSocketManager.disconnect` calls `mark_user_offline` when any one socket closes even if another local socket for the same user remains connected. This can produce false offline presence but does not grant unauthorized access. Multi-backend presence is also best-effort/ephemeral.

Redis pub/sub auth-control delivery remains non-durable. If a logout, session revocation, or deactivation notification is missed on another backend, that existing socket can remain until access-token expiry (default approximately 30 minutes). Channel membership generation protects membership loss, but not account/session revocation. This is a known residual confidentiality window under infrastructure failure and should be explicit in operations documentation.

## 17. AV-09 / AV-10 / AV-11 status

- **AV-09 - Low, remains open.** `message_attachments` independently stores `message_id`, `channel_id`, and `upload_id`; the database does not enforce that the relation channel equals `messages.channel_id`. The authorization query trusts both fields. Normal publish and migration paths populate them consistently, and no new route/admin/import/repair path allowing an attacker to create an inconsistent row was found. Phase 5's ANY-active-reference policy does not create such rows. Retain Low latent-integrity severity.
- **AV-10 - Low, remains open.** Environment validation applies strict secret/config checks only to recognized `prod`, `production`, and `staging` labels. Unknown deployment-like labels such as `live` fail open as nonproduction. Phase 4/5 WS, download, and rate-limit settings do not introduce a new label-dependent authorization branch, but the central classification weakness remains.
- **AV-11 - Low, remains open.** The canonical deployment is a university/demo posture: direct service ports, demo defaults, no integrated TLS/reverse proxy/security headers, JavaScript-readable browser tokens, and containers without production hardening. No new actual frontend injection was found. It must not be represented as production-grade.

## 18. Tests and experiments

All commands were run at reviewed HEAD with test-only environment overrides. Secrets below were disposable and the containers were removed after the audit.

| Command/experiment | Actual result |
|---|---|
| `git status --short` at start | Empty |
| `python -B -m alembic upgrade head` then `python -B -m alembic current` against fresh PostgreSQL 16 | Passed; `0019 (head)` |
| `python -B -m pytest -q` from `backend` against disposable PostgreSQL | **176 passed, 1 warning in 103.72s**; warning was Passlib/Argon2 version deprecation |
| `npm run typecheck` from `frontend` | Passed, exit 0 |
| Live Redis 7 fixed-window/TTL script | 2 allows then block at retry 30; TTL-less key repaired to 17 seconds |
| Redis outage/local transition script | One prior Redis allowance plus two local allows, then local block; 3-key local capacity denied unseen fourth key |
| Live RabbitMQ 3.13 desired-state script | Stale bind/unbind returned `stale_generation`; current bind/unbind/rebind behaved correctly; A/B/C delivery was `False/False/True` |
| Live PostgreSQL invite identity script | Target email reassigned through `update_me`; attacker accepted targeted token and received `member` |
| Live PostgreSQL two-session lock-cycle script | One participant raised `DeadlockDetectedError`, confirming advisory/binding-row inversion |

Existing tests were not modified. The live Rabbit test exercised actual exchanges, durable user queues, bindings, publishes, and the real worker `_apply_broker_binding` function; it was not a fake transport test.

## 19. Things not verified

- No full browser-driven end-to-end supervisor flow was run.
- No multi-backend or multi-worker deployment was load-tested; those conclusions are source/limit analysis.
- No large-scale slow-reader/FD exhaustion test was performed, to avoid destabilizing the host.
- The exact channel delete -> delayed reconcile -> restore sequence was not repeated live in RabbitMQ; equivalent stale bind/unbind and slug projections were live-tested.
- No process-kill test was performed at the exact point between Rabbit success and DB acknowledgement.
- PostgreSQL deadlock reproduction used the exact advisory and binding-row locks in independent sessions, not a full HTTP+worker harness.
- Redis network ambiguity after server execution but before client response was not fault-injected.
- Dependency behavior was inspected for locally installed versions; alternate/future dependency resolution was not tested.
- Production TLS, proxy, WAF, container orchestration, backup, monitoring, and secret rotation were outside this repository-only audit.

## 20. Recommended next phase

### P0

- Bind targeted invites to immutable user IDs where possible and require verified, consistently normalized email ownership for pre-registration email invitations. Add issuance-to-email-reassignment regression tests.
- Put explicit aggregate and per-IP limits plus idle/minimum-rate/total-duration response controls in the canonical download deployment; document and test the proxy path.

### P1

- Establish and enforce a global database/advisory lock order. Move or isolate worker failure audit logging so it cannot invert the binding-state order; add deadlock retries and independent-session tests.
- Add strict auth field/body limits and bound/truncate failed-login audit metadata.
- Make WebSocket account/session revocation durable or revalidate session/user activity periodically at final delivery; fix multi-socket presence reference counting.
- Add fairness to `/sync` (round-robin allocation or a resumable global/fair cursor) and make deleted-channel races fail per-channel rather than fail the whole response where appropriate.

### P2

- Add the AV-09 composite relation invariant or eliminate redundant `channel_id` authority.
- Fail closed for unknown deployment environment labels and formalize deployment profiles.
- Add CSP and standard security headers, HttpOnly/Secure cookie sessions for a production profile, TLS/reverse proxy, non-root/restricted containers, and internal-only infrastructure ports.
- Add live multi-worker Rabbit crash/retry, multi-backend WS budget/revocation, and controlled slow-download tests to CI or a dedicated integration environment.

## 21. Final conclusion

The repository is a credible, defendable university publish/subscribe MVP with substantially improved broker ordering, realtime authorization, bounded sync, streaming, and failure-mode controls. The live broker experiment supports the central claim that newest PostgreSQL desired state wins over stale Rabbit reconciliation. The full backend suite, frontend typecheck, and fresh migration also pass.

It is not ready to be described as production-secure. Email-targeted invitation identity is presently exploitable under a realistic token-plus-email-reassignment condition, and direct slow downloads can multiply across public accounts. Lock-order deadlocks and retained AV-09/10/11 hardening gaps further justify another targeted security phase. The next work should fix the two Medium issues first without weakening the verified generation and final-delivery invariants.
