# Security Hardening Phase 5 Report

## 1. Scope

Phase 5 addressed only the four remaining Medium application-security findings from `SECURITY_VERIFICATION_AFTER_PHASE3.md`: established WebSocket work abuse (AV-04), attachment access after channel soft deletion (AV-05), invite lifecycle semantics and accept/revoke concurrency (AV-06), and Redis/fallback rate-limit failure behavior (AV-07).

The existing FastAPI, PostgreSQL, RabbitMQ, Redis, worker, WebSocket, outbox, and frontend architecture was preserved. AV-09 through AV-11, cookie/CSRF migration, attachment encryption, encryption-key rotation, production Compose/TLS/non-root work, and audit anchoring were not implemented.

## 2. Verification findings addressed

| Finding | Confirmation | Result |
| --- | --- | --- |
| AV-04 | **CONFIRMED** | Fixed with a repository-controlled inbound frame ceiling, weighted per-socket command budget, history-row budget, total per-command history cap, duplicate-subscribe suppression, explicit serial dispatch, and disconnect cleanup. |
| AV-05 | **CONFIRMED** | Fixed by requiring an active channel for channel-derived message-attachment authorization while preserving explicit upload-owner access. |
| AV-06 | **CONFIRMED** | Fixed by defining targeted invites as one-use, generic links as reusable, and serializing accept/revoke/delete through channel-then-invite row locks. |
| AV-07 | **CONFIRMED** | Fixed with one atomic Redis Lua operation and a bounded, non-evicting local fallback whose sensitive-key saturation denies rather than resets security state. |

## 3. AV-04 WebSocket abuse-control architecture

### Frame limits

- `WS_MAX_INBOUND_MESSAGE_BYTES` defaults to 16,384 bytes and is configurable.
- Docker starts Uvicorn with `--ws-max-size ${WS_MAX_INBOUND_MESSAGE_BYTES:-16384}`, so the ASGI server rejects larger raw WebSocket messages before handing an arbitrarily large frame to application code.
- The inbound loop independently checks character count and then UTF-8 bytes before `json.loads`. The character pre-check avoids allocating a same-sized encoded buffer for an already-obviously-oversized string.
- An application-visible violation returns `MESSAGE_TOO_LARGE` and closes only that socket with WebSocket code 1009. An alternate non-Docker ASGI launch retains the application check but should configure the same server-side limit.

### Command groups and weights

Each admitted socket owns a fixed-cardinality token bucket; attacker-provided channel IDs or command names do not create limiter keys.

| Command group | Commands | Cost |
| --- | --- | ---: |
| Cheap | `ping`, `auth`, `sync`, malformed/unsupported bounded frames | 1 |
| Medium | `seen`, `unsubscribe` | 3 |
| Expensive | `subscribe`, `resume` | 10 |

The default command bucket capacity is 60 units with a one-unit/second refill. Settings are environment-configurable through `WS_COMMAND_BUDGET_CAPACITY` and `WS_COMMAND_BUDGET_REFILL_PER_SECOND`.

### History and total work bounds

- `subscribe` and `resume` reserve their maximum possible returned row count before membership/message queries.
- The default history bucket capacity is 300 rows with a five-row/second refill.
- One command returns/materializes at most `min(WS_HISTORY_BATCH_LIMIT, WS_HISTORY_BUDGET_CAPACITY)`, which is 100 total rows by default across all requested channels, not 100 rows per channel.
- Resume's client-requested limit is clamped to the same per-command bound.
- Repeating an already-granted identical subscribe set with the same `from_seq_id` returns an empty sync acknowledgement without another membership query, history query, decryption, or serialization pass. A changed subscription/cursor or membership removal invalidates that optimization.

### Backpressure, cleanup, and scope

The inbound loop already awaited every command. Phase 5 makes the invariant explicit with one per-socket dispatch lock; no command handler is spawned as unbounded background work. Budget, lock, and duplicate-subscribe state are removed on disconnect and on a failed connection setup.

Budgets are deliberately per socket and per backend process. One abusive socket does not deplete another socket. The existing five-socket per-user/per-process quota and WebSocket ticket/connection rate limits bound parallel multiplication and reconnect resets, but no distributed global established-socket budget is claimed.

## 4. AV-05 attachment lifecycle policy

| Identity/state | Protected message attachment access |
| --- | --- |
| Upload owner | Allowed to retrieve their own existing upload, including after linked message/channel deletion. |
| Channel owner | Allowed only through current approved membership while the channel is active and message is not deleted, unless also the upload owner. |
| Channel admin | Same active-channel/non-deleted-message/current-approved-membership rule. |
| Ordinary member | Same active-channel/non-deleted-message/current-approved-membership rule. |
| Pending member | Denied. |
| Removed/former member | Denied, including after channel restoration. |
| Outsider | Denied. |
| Superadmin | No implicit private-upload bypass; allowed only through ordinary upload ownership or approved channel membership. |
| Soft-deleted channel | Ordinary channel-derived access is denied. |
| Restored channel | Current approved memberships regain channel-derived access. |
| Deleted message | Channel-derived access remains denied even if the channel is active; upload-owner access remains independent. |

The indexed authorization query now joins `Channel` and requires `Channel.deleted_at IS NULL`. This does not address AV-09's separate relational channel/message consistency finding.

## 5. AV-06 invite lifecycle/atomicity

### Final semantics

- A targeted invite has an invited user or email, is one-use, and records consumption in `accepted_at`.
- A generic invite has neither target field and is reusable until revoked, expired, or its channel is soft-deleted.
- A successful generic membership transition produces its own `invite.accepted` or membership audit event. Generic lifecycle never treats the first user's `accepted_at` as global consumption.
- Re-presenting a generic link by an already-approved member is idempotent and does not create another effective acceptance/audit mutation.

Historical generic rows that acquired `accepted_at` under the pre-Phase-5 behavior remain compatible: generic lifecycle, quota, preview, and status filters ignore that value, and the API represents generic `accepted_at` as null. No data rewrite was required.

### Linearization and races

State-changing join/accept/revoke/delete paths lock the channel row before the invite row with PostgreSQL `SELECT ... FOR UPDATE`.

- **Targeted accept vs accept:** one transaction sets membership plus `accepted_at`; the waiter observes consumed state and returns `INVITE_ALREADY_ACCEPTED`. At most one lifecycle claim succeeds.
- **Accept vs revoke:** the channel/invite lock order defines the winner. Revoke-first commits `revoked_at`, and the waiter creates no membership. Targeted accept-first commits membership plus `accepted_at`, and later revoke returns `INVITE_ALREADY_ACCEPTED` rather than producing both accepted/revoked active-state timestamps.
- **Generic accept vs accept:** requests serialize conservatively on the channel/invite locks; distinct eligible users can both succeed because generic `accepted_at` is not consumption.
- **Accept vs expiration:** expiry is checked after the locks are obtained; `expires_at <= now` cannot accept.
- **Accept vs channel deletion:** deletion locks the same channel row. Delete-first makes acceptance observe `CHANNEL_NOT_FOUND`; accept-first commits a membership before deletion subsequently suspends the whole channel.
- **Generic revoke:** revocation remains valid after earlier generic uses and prevents every later acceptance.

## 6. AV-07 rate-limit failure architecture

### Healthy Redis

One Lua evaluation performs:

1. `INCR`;
2. `TTL` inspection;
3. first-hit `EXPIRE`, or repair of a legacy no-TTL key;
4. return of count and TTL.

Redis executes the script atomically. Later hits do not reset/extend the window. The application no longer performs separate `INCR`, `EXPIRE`, and `TTL` round trips.

### Redis-outage fallback

- A dictionary stores at most `RATE_LIMIT_LOCAL_MAX_KEYS` active windows per backend process (default 10,000).
- A min-heap reclaims expired windows. It creates one expiry entry per admitted active window, so memory remains bounded with the dictionary.
- Existing active/blocked keys are never evicted to admit new identities.
- At saturation, previously unseen sensitive keys fail closed with a retry interval based on the next expiry.
- Low-risk operations that explicitly use `failure_policy=allow` bypass the fallback and remain available; their traffic cannot fill or be blocked by the sensitive structure.

### Failure semantics

- If Redis fails before executing the script, the sensitive request uses the local per-process fallback.
- If execution is uncertain because the response is lost, a completed script has already installed/repaired its TTL; the application may also conservatively consume local state for that request.
- During an extended outage, protection is per process, not distributed across replicas. Saturation denies new sensitive identities without resetting established keys.
- On the next successful Redis command, the application immediately resumes the distributed Redis result. Local outage state is ignored while Redis is healthy and expires independently.

## 7. Database migrations

No migration was added. AV-06 required semantic and transactional changes but no new column/table: targeted `accepted_at` remains the one-use consumption marker, while generic acceptances use existing audit/membership events.

A fresh disposable PostgreSQL database upgraded successfully through the existing head `0019_phase4_p0_hardening`.

## 8. Tests added

`backend/tests/security/test_phase5_medium_hardening.py` contains these 18 tests:

- `test_websocket_normal_command_rate_works_and_flood_is_throttled`
- `test_repeated_expensive_resume_is_bounded_by_history_budget`
- `test_one_websocket_history_command_has_one_total_row_cap`
- `test_identical_subscribe_does_not_repeat_history_work`
- `test_oversized_websocket_frame_fails_safely_before_json_parse`
- `test_abusive_socket_budget_does_not_consume_another_socket_budget`
- `test_five_abusive_sockets_each_have_a_finite_expensive_command_budget`
- `test_websocket_limiter_state_is_cleaned_after_disconnect`
- `test_attachment_access_follows_active_channel_lifecycle_and_explicit_owner_policy`
- `test_targeted_invite_accepts_once_and_expired_or_deleted_channel_invites_fail`
- `test_generic_invite_is_reusable_and_each_effective_acceptance_is_audited`
- `test_targeted_revoke_winning_race_prevents_membership`
- `test_two_concurrent_targeted_accepts_create_at_most_one_membership`
- `test_targeted_accept_winning_race_has_consistent_state`
- `test_concurrent_generic_accepts_both_succeed_then_revoke_blocks_later_use`
- `test_redis_fixed_window_is_one_atomic_eval_and_ttl_is_not_extended`
- `test_fallback_key_churn_cannot_reset_blocked_identity_and_memory_is_bounded`
- `test_redis_outage_fallback_and_recovery_resume_distributed_limiting`

The Phase 3 in-memory Redis harness was minimally updated to implement the new atomic `eval` contract without weakening its threshold assertion.

## 9. Adversarial scenarios

- **Attack A — WebSocket flood:** deterministic manager/budget tests admitted exactly five socket budget states; each allowed one capacity-sized expensive command and rejected the next. Normal cheap commands passed until their configured capacity. A 160-row two-channel history request returned 100 total rows; a second capacity-sized resume was rejected; an identical subscribe performed history work once; and a 1,025-byte frame under a test 1,024-byte cap closed only that socket with code 1009. No live five-socket network/load run was performed.
- **Attack B — deleted-channel media:** an approved member could read while active, received `403` through the route after soft deletion, regained access after restoration while still approved, and lost channel-derived access after message deletion. Pending/removed/outsider/superadmin identities remained denied; the upload owner retained explicit ownership access.
- **Attack C — invite revoke race:** two independent PostgreSQL sessions and explicit lock-attempt barriers proved both orders. Revoke-first produced no membership; accept-first produced membership plus accepted state and a later revoke conflict. Concurrent targeted accepts created one membership/claim; concurrent generic accepts for distinct users both succeeded before later revocation blocked a third user.
- **Attack D — emergency limiter churn:** with Redis forced unavailable and local capacity set to 100, the original identity remained blocked after 150 churn keys, both dictionary and heap stayed at 100 entries, unseen sensitive identities were denied at saturation, and a low-risk allow-policy request remained available.

## 10. Validation results

All database-backed final validation used disposable PostgreSQL 16 container `messaging-phase5-security-postgres` on `127.0.0.1:55441`; it did not use or modify the developer's existing PostgreSQL container/database.

```text
python -B -m pytest -q tests/security/test_phase5_medium_hardening.py
18 passed, 1 warning in 11.35s

python -B -m pytest -q tests/security/test_phase1_hardening.py tests/security/test_phase2_auth_hardening.py tests/security/test_phase3_abuse_hardening.py tests/security/test_phase4_p0_hardening.py
80 passed, 1 warning in 42.82s

python -B -m pytest -q
176 passed, 1 warning in 104.29s

python -B -m alembic upgrade head
passed on a fresh disposable database; current revision 0019_phase4_p0_hardening

npm run typecheck
passed

English/Arabic locale JSON parse
passed

docker compose config --quiet
passed
```

The warning is the existing `passlib` access to deprecated `argon2.__version__` metadata. The first host-default focused discovery run reported `9 passed, 7 skipped` because the Docker-only `postgres` hostname was unavailable; final database-backed evidence is the isolated run above. Redis Lua/outage and WebSocket flood/backpressure tests were simulated deterministically at the application/component boundary. No live Redis outage, ASGI network flood, or multi-backend load test is claimed.

Final `git diff --check` passed (Git printed only line-ending conversion notices). `.env` remains untracked, no `.pyc`/local database artifacts were present, and the changed-file review found only intentional Phase 5 files. The disposable test container was removed after validation. Staging status is reported in the final handoff.

## 11. Remaining limitations

- WebSocket command/history budgets, concurrent socket quota, protected-download concurrency, and Redis-outage fallback are per backend process; only healthy Redis route limiting is distributed.
- Reconnecting receives a fresh per-socket work budget. Existing ticket/connection rate limits and five concurrent sockets bound this reset but do not create a global session budget.
- The Docker Uvicorn frame cap is explicit; alternate deployment commands must configure their own equivalent ASGI/proxy raw-frame ceiling in addition to the application check.
- Live Redis script/outage recovery, real five-socket flooding, and multi-backend behavior were not load/integration-tested.
- Generic acceptance auditing reuses events/membership transitions rather than a separate invite-redemption table.
- Channel-wide row locking makes invite lifecycle ordering simple and safe for the MVP, but serializes concurrent invite acceptances within one channel.
- Upload-owner access after channel/message deletion is intentional. Attachment bytes remain unencrypted by the message Fernet layer.
- Existing browser-readable tokens, encryption-key rotation gaps, external audit anchoring, and production deployment limitations remain.

## 12. Remaining findings

- **AV-09 (Low):** `message_attachments.channel_id` is not relationally constrained to equal the referenced message's channel. Not changed in Phase 5.
- **AV-10 (Low):** unknown environment labels can still select development secret behavior. Not changed in Phase 5.
- **AV-11 (Low):** the local Docker/frontend deployment posture is not a hardened production profile. Not changed in Phase 5.

No unrelated finding was silently reclassified.

## 13. Recommended Phase 6

1. Enforce AV-09 attachment/message/channel relational consistency after an integrity audit and safe migration plan.
2. Make explicit development environment names an allowlist so AV-10 unknown labels fail safe.
3. Treat AV-11 as a separate production-profile task: private infrastructure networking, unique managed secrets, TLS/proxy limits, security headers, least-privilege containers, and a documented browser-session migration plan.
4. Add a repeatable live multi-backend WebSocket/Redis outage-load scenario without replacing the deterministic regression suite.

## 14. Files changed

### Configuration/runtime

- `.env.example`
- `backend/Dockerfile`
- `backend/app/core/config.py`
- `backend/app/realtime/protocol.py`
- `backend/app/realtime/ws_abuse_control.py`
- `backend/app/realtime/ws_manager.py`
- `backend/app/services/rate_limit_service.py`

### Attachment and invite policy

- `backend/app/api/routes/memberships.py`
- `backend/app/schemas/channels.py`
- `backend/app/services/channel_service.py`
- `backend/app/services/message_service.py`

### Tests

- `backend/tests/security/test_phase3_abuse_hardening.py`
- `backend/tests/security/test_phase5_medium_hardening.py`

### Frontend wording

- `frontend/src/locales/en.json`
- `frontend/src/locales/ar.json`

### Documentation/status

- `README.md`
- `REPOSITORY_ASSESSMENT.md`
- `docs/ARCHITECTURE.md`
- `docs/DEMO_GUIDE.md`
- `docs/FINAL_MVP_STATUS.md`
- `docs/REQUIREMENTS_MAPPING.md`
- `docs/SECURITY.md`
- `docs/STABILIZATION_STATUS.md`
- `docs/TESTING.md`
- `SECURITY_HARDENING_PHASE5_REPORT.md`
