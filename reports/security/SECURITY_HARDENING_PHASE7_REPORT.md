# Security Hardening Phase 7 Report

Date: 2026-08-10

## 1. Scope

Phase 7 addresses only P5V-03, P5V-04, AV-09, and AV-10 in the current
repository. It preserves the Phase 1–6 controls and does not implement the
separate AV-11 production deployment/browser-security redesign.

The review covered application and worker lock acquisition, authentication
schemas and raw ASGI input handling, normalized attachment persistence, and
environment-dependent secret validation. Findings were confirmed from the
current source before changes were made.

## 2. Findings addressed

| Finding | Confirmation | Result |
| --- | --- | --- |
| P5V-03 — inconsistent database/advisory lock ordering | **CONFIRMED** | The worker could hold `BrokerBindingState FOR UPDATE` and then request an event-integrity advisory lock, while application transactions could take those classes in the opposite order. Channel, membership, invite, message, seen-state, delivery-retry, and restore paths also lacked one explicit global policy. Reviewed paths now follow the documented order, and worker diagnostics are isolated after the authoritative status commit. |
| P5V-04 — insufficient auth/raw request bounds | **CONFIRMED** | Login identity/password and refresh/logout token strings were unbounded; raw identity text entered rate-limit keys and failed-login events; direct ASGI traffic had no repository-controlled ordinary-body ceiling. Field, key, event, and streaming raw-body boundaries were added. |
| AV-09 — attachment channel/message relation not relationally enforced | **CONFIRMED** | Independent foreign keys allowed a relation to name message A while claiming channel B. Migration 0021 normalizes historical rows and adds a composite foreign key to the authoritative message/channel pair. |
| AV-10 — unknown environments fail open | **CONFIRMED** | Strict secret validation used a finite production-name list, so labels such as `live` or `release` received development behavior. Development behavior now requires an explicit allowlisted label; all other labels are production-like. |

## 3. Database lock-order architecture

The audit searched every current `FOR UPDATE`, `with_for_update()`,
`pg_advisory_xact_lock`, event-integrity lock, and `BrokerBindingState` site. It
reviewed user/session lifecycle rows, channels, memberships, invites, messages,
seen state, uploads, existing outbox claims, broker desired-state projections,
event advisory scopes, worker reconciliation/failure handling, delivery retry,
and superadmin channel restoration.

The chosen relative order is:

```text
User / UserSession
  -> Channel
  -> ChannelMembership / ChannelInvite / Message / UserChannelState / Upload
  -> existing Outbox claim
  -> BrokerBindingState
  -> event-integrity advisory lock
```

Not every transaction takes every class. Multi-membership and topology work is
ordered by UUID. Channel/member/invite/message mutations take the channel before
dependent rows and take the event advisory lock last. Newly inserted outbox rows
are not existing claim locks because other transactions cannot see them before
commit. The full policy is in `backend/docs/LOCK_ORDERING.md`.

The outbox worker now claims and commits one outbox/projection pair per
transaction instead of retaining a retry-ordered collection of binding locks.
On RabbitMQ failure, it first commits the authoritative retry/dead-letter and
desired-projection state. It then writes `broker.retry_scheduled` or
`broker.dead_lettered` in a separate best-effort event transaction, which takes
no retained binding lock. A failed diagnostic write cannot undo the committed
security/delivery state.

Only the idempotent post-commit diagnostic transaction retries SQLSTATE
`40P01`/`40001`, with at most three attempts and a short bounded delay. HTTP
writes are not blindly retried. Unrelated PostgreSQL workloads may still contend
or deadlock; this work removes the known opposite-order cycle rather than
claiming deadlocks are impossible.

## 4. Authentication/request-size policy

- `username_or_email`: 1–255 characters.
- Login `password`: 1–256 characters, matching registration's existing maximum.
- Refresh/logout token: 1–2048 characters. Current generated HS256 refresh JWTs
  remain well below this value, leaving substantial claim-growth headroom.
- Ordinary `POST`, `PUT`, `PATCH`, and `DELETE` bodies: 131,072 bytes by default,
  configurable through `API_REQUEST_BODY_MAX_BYTES` (1 KiB–10 MiB).
- The middleware rejects an oversized declared `Content-Length` before reading
  the body and counts streamed chunks when the header is absent or inaccurate.
  It does not call `request.body()` or otherwise pre-buffer globally.
- Only `PUT /.../uploads/{uuid}/content` bypasses the ordinary ceiling. The
  existing upload service continues to stream, count, hash, and enforce
  `UPLOAD_MAX_SIZE_BYTES`.
- Auth rate-limit identity keys contain `sha256(trim(lower(identity)))`, never the
  supplied text. Failed-login events store only a normalized 32-character prefix
  and the 64-character digest. Passwords and refresh tokens are not audited.

## 5. Attachment relational invariant

`message_attachments.channel_id` is retained for the indexed authorization
query, while `messages.channel_id` remains authoritative. `messages` now has
`UNIQUE(id, channel_id)`, and `message_attachments` has:

```text
FOREIGN KEY (message_id, channel_id)
REFERENCES messages(id, channel_id)
ON DELETE CASCADE
```

Normal publishing still derives attachment metadata and channel identity from
trusted database records. PostgreSQL now rejects a relation whose message and
claimed channel do not match. Active approved members remain authorized,
outsiders remain denied, and the existing deleted channel/message lifecycle is
preserved.

## 6. Environment classification

Environment labels are stripped and lowercased. Exactly `dev`, `development`,
`local`, and `test` permit development placeholder/fallback behavior. Every
other non-empty label—including `production`, `staging`, `live`, `release`,
`prod-eu`, and unknown strings—is production-like and receives strict JWT and
enabled-message-encryption key validation. An empty label is invalid.

`ENVIRONMENT=test` therefore remains compatible with disposable test secrets,
while `ENVIRONMENT=live` plus `JWT_SECRET=change-me` fails configuration.

## 7. Database migrations

Added `backend/alembic/versions/0021_phase7_attachment_integrity.py`, revising
`0020_phase6_invite_identity`.

Upgrade behavior:

1. Updates each mismatched `message_attachments.channel_id` to its referenced
   authoritative `messages.channel_id`.
2. Deletes no attachment relation.
3. Adds `uq_messages_id_channel`.
4. Replaces the single-column message foreign key with
   `fk_message_attachments_message_channel`.

The old message foreign key already guarantees that the referenced message
exists, so the correct channel is unambiguous. Downgrade restores the old
single-column foreign key and removes the composite unique constraint; it does
not reconstruct invalid historical channel values that the upgrade normalized.

Validation used two disposable PostgreSQL 16 databases. A fresh database
upgraded to head. A second database upgraded to 0020, received two attachment
relations (one valid and one deliberately inconsistent), two users, and one
invite, then upgraded to 0021. It retained 2 attachments, 2 users, and 1 invite,
reported 0 mismatches, and rejected a new cross-channel update with
`fk_message_attachments_message_channel`.

## 8. Tests added

Added `backend/tests/security/test_phase7_final_app_hardening.py`. Its 15 named
tests expand to 23 cases through environment parametrization:

- `test_normal_login_and_maximum_registered_password_remain_accepted` — normal
  login, 256-character registered password, and generated refresh compatibility.
- `test_authentication_fields_reject_oversized_values` — identity, password,
  refresh, and logout schema maxima.
- `test_current_refresh_jwt_has_documented_headroom` — current JWT length margin.
- `test_failed_login_audit_and_rate_limit_identity_are_bounded` — bounded event
  fields and no raw identity in limiter keys.
- `test_auth_rate_limit_key_is_fixed_size_at_schema_boundary` — 64-hex digest.
- `test_oversized_raw_json_is_rejected_by_declared_and_streamed_boundaries` —
  both `Content-Length` and chunk-counting 413 paths.
- `test_streaming_upload_path_is_exempt_and_not_prebuffered` — ordered upload
  chunks reach the downstream ASGI app unchanged.
- `test_explicit_development_environments_allow_placeholders` — four explicit
  development/test labels, including case/whitespace normalization.
- `test_production_and_unknown_environments_reject_placeholders` — production,
  staging, live, release, prod-eu, and foo fail safe.
- `test_secure_unknown_environment_is_treated_as_production_like` — a secure
  release-labelled configuration succeeds.
- `test_attachment_composite_fk_allows_valid_publish_and_rejects_false_channel`
  — valid publish, member/outsider checks, PostgreSQL mismatch rejection, and
  deleted-channel denial.
- `test_historical_advisory_binding_cycle_completes_without_deadlock` — two real
  PostgreSQL sessions plus mocked RabbitMQ failure reproduce the prior schedule.
- `test_channel_delete_and_member_mutation_serialize_without_deadlock` — two
  real PostgreSQL sessions block/serialize without a cycle.
- `test_worker_audit_failure_does_not_undo_retry_state` — diagnostic isolation.
- `test_membership_event_failure_rolls_back_projection_and_authorization` — no
  partial membership, generation, or outbox state.

Existing Phase 5 attachment tests continue to cover deleted-message behavior,
restore behavior, every membership role, upload-owner access, and route denial.

## 9. Adversarial scenarios

- **Attack A — intentional deadlock amplification:** the historical advisory →
  binding/application versus binding → advisory/worker schedule completed under
  an explicit timeout with no deadlock. Worker status committed before its
  diagnostic advisory transaction. PostgreSQL sessions were real; RabbitMQ
  failure was mocked.
- **Attack B — huge login body:** oversize auth fields fail Pydantic validation;
  oversize declared or streamed ordinary bodies receive 413; attacker identity
  cannot create large limiter keys or event payloads.
- **Attack C — inconsistent attachment relation:** PostgreSQL rejected message A
  plus channel B under the composite foreign key.
- **Attack D — deployment typo:** `ENVIRONMENT=live` with a placeholder JWT
  secret failed settings validation; arbitrary unknown labels behave the same.

## 10. Validation results

Commands were run on 2026-08-10:

| Validation | Result |
| --- | --- |
| `python -B -m pytest -q tests/security/test_phase7_final_app_hardening.py` | `23 passed, 1 warning` |
| Phase 1–6 security regression files | `117 passed, 1 warning` |
| `python -B -m pytest -q` | `218 passed, 1 warning` |
| Fresh PostgreSQL `python -B -m alembic upgrade head` | Passed; current revision `0021_phase7_attachment_integrity` |
| Representative PostgreSQL 0020→0021 upgrade | Passed; 2 attachments/2 users/1 invite retained, mismatch count 1→0, new mismatch rejected |
| `npm run typecheck` | Passed |
| `docker compose config --quiet` | Passed |
| `docker compose -f docker-compose.hardened.yml config --quiet` | Passed |
| `git diff --check` / `git diff --cached --check` | Passed; only Git line-ending conversion notices were emitted |

The one warning is the existing passlib access to deprecated
`argon2.__version__`. No live RabbitMQ failure, Redis outage, proxy load, or
multi-backend load test was run in this phase.

## 11. Remaining limitations

- Multi-socket presence remains a reliability issue: closing socket A while
  socket B remains may mark the user offline. Phase 7 did not redesign presence.
- Frontend tokens remain JavaScript-managed rather than httpOnly-cookie/CSRF
  protected; TLS and browser/session production posture remain AV-11 work.
- The repository has explicit email verification state but no provider-backed
  verification issuance/delivery/completion flow.
- WebSocket, download, and local rate-limit fallback caps remain per process;
  Nginx bounds one proxy instance and does not coordinate backend replicas.
- The lock policy removes known inversions but does not eliminate ordinary row
  contention or every possible PostgreSQL deadlock from unrelated workloads.
- RabbitMQ failure tests are mocked, not live broker-outage integrations.
- Uploads/attachments are authorized but are not encrypted at rest.
- Audit hashes have no external anchoring, KMS-backed key lifecycle, or full
  monitoring/alerting.

## 12. Remaining security findings

- **AV-11 remains open:** production TLS, httpOnly cookies/CSRF, deployment
  credentials, non-root/restricted containers, CSP/HSTS/security headers,
  private production service networking, KMS/key rotation, attachment
  encryption, external audit anchoring, and monitoring/alerting were not
  substantially implemented.
- A provider-backed email verification completion flow remains absent.
- Distributed/global enforcement for per-process limits remains absent.
- Live RabbitMQ/Redis failure and multi-instance load coverage remains absent.

No claim of production readiness is made.

## 13. Recommended final production phase

Address AV-11 as a separate deployment-focused change set: terminate and enforce
TLS, migrate browser auth to secure httpOnly cookie sessions with an explicit
CSRF design, supply secrets through a deployment secret manager with rotation,
run containers non-root with restricted filesystems/capabilities, add CSP/HSTS
and related response headers, isolate stateful services on private networks,
choose attachment-encryption and external-audit anchoring policies, add metrics
and alerts for broker/event/lock failures, and run controlled live broker,
multi-replica, and slow-client tests. Separately correct multi-socket presence
with connection counting or leases.

## 14. Files changed

- `.env.example`
- `backend/alembic/versions/0021_phase7_attachment_integrity.py`
- `backend/app/api/routes/auth.py`
- `backend/app/core/config.py`
- `backend/app/core/encryption.py`
- `backend/app/core/request_body_limit.py`
- `backend/app/db/models.py`
- `backend/app/main.py`
- `backend/app/schemas/auth.py`
- `backend/app/services/admin_service.py`
- `backend/app/services/channel_service.py`
- `backend/app/services/delivery_service.py`
- `backend/app/services/message_service.py`
- `backend/docs/LOCK_ORDERING.md`
- `backend/tests/security/test_phase7_final_app_hardening.py`
- `worker/worker_app/outbox_runner.py`
- `README.md`
- `REPOSITORY_ASSESSMENT.md`
- `docs/ARCHITECTURE.md`
- `docs/FINAL_MVP_STATUS.md`
- `docs/REQUIREMENTS_MAPPING.md`
- `docs/SECURITY.md`
- `docs/STABILIZATION_STATUS.md`
- `docs/TESTING.md`
- `SECURITY_HARDENING_PHASE7_REPORT.md`
