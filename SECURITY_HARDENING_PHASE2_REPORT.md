# Security Hardening Phase 2 Report

## 1. Scope

Phase 2 was limited to authentication/session lifecycle security across HTTP access tokens, `UserSession`, refresh rotation, logout/revocation, WebSocket authentication, socket expiry, and multi-instance revocation control. The existing FastAPI/PostgreSQL/Redis/RabbitMQ/Next.js architecture was preserved.

## 2. Confirmed vulnerabilities

| Requested issue | Status | Evidence before the change |
| --- | --- | --- |
| Access tokens survive logout/session revocation | **CONFIRMED** | Access JWTs had `sub`, type, `iat`, and `exp`, but no `sid`; protected authentication loaded only the user. Revoking `UserSession` affected refresh only. |
| WebSocket remains authenticated after JWT/session expiry | **CONFIRMED** | Authentication occurred once at handshake. No expiry task or session-targeted connection index existed. |
| JWT access token is placed in WebSocket URL | **CONFIRMED** | The frontend and verifier scripts built `?token=<access JWT>`. The backend also accepted query, authorization-header, and first-frame access JWTs. |
| Distributed session/WebSocket revocation | **CONFIRMED** | Account deactivation closed sockets only through the current process's `WSManager`; other revocation endpoints did not close sockets or notify other instances. |
| Refresh-token replay detection | **CONFIRMED** | Rotation replaced one stored hash, but a stale token produced only `AUTH_INVALID`. Refresh JWTs also lacked a unique claim, so rotations inside one second could be identical. |
| Absolute session lifetime | **CONFIRMED** | Each refresh set `expires_at = now + idle TTL`; there was no immutable maximum lifetime. |

## 3. Architecture decisions

### Access-token/session binding

Access JWTs now contain `sub` and stable `sid`. Authentication parses both and uses one indexed PostgreSQL join to load the user and session. It rejects an inactive user and a missing, malformed, nonexistent, revoked, idle-expired, or absolute-expired session.

```text
access JWT (sub + sid)
        |
        v
one User + UserSession query
        |
        +-- user active
        +-- session active
        +-- idle deadline valid
        +-- absolute deadline valid
```

The database is checked once per protected request. No cache was added because correctness and invalidation safety are more important for this MVP; the query and new active-lifetime index leave a clear optimization path if measured load later requires caching.

### WebSocket ticket mechanism

`POST /auth/ws-ticket` uses normal bearer authentication and returns a cryptographically random opaque ticket. Redis stores a SHA-256-derived key, never the plaintext ticket, with only user/session/expiry metadata. Redis `GETDEL` consumes it atomically. Default TTL is 30 seconds and is capped by the authenticated access/session lifetime.

```text
Authorization: Bearer access JWT
        |
POST /auth/ws-ticket
        |
Redis SET NX hash(ticket), TTL 30s
        |
ws...?ticket=<opaque value>
        |
Redis GETDEL + PostgreSQL session validation
```

Raw access JWT query, header, and first-frame WebSocket authentication were removed. Each accepted socket retains the authenticated session id and effective authentication expiry; a local timer closes it with code `4001` at expiry.

### Distributed revocation

After durable database revocation, the handling backend closes matching local sockets and publishes a minimal Redis control event containing `user_id`, optional `session_id`, and reason. Every backend manager subscribes to the shared control channel. Duplicate events are ignored safely through per-socket closing state.

If Redis publish is unavailable, the user operation still succeeds: PostgreSQL remains authoritative and blocks later HTTP requests, refresh, ticket validation, and reconnect. A remote socket that missed the event can remain only until its captured authentication expiry.

### Refresh replay detection

One `UserSession` is the small refresh-token family. Refresh JWTs now have a random `jti`; only the current token hash is stored. Rotation locks the session row, preventing concurrent uses from both succeeding. A valid signed token for that session whose hash is no longer current is treated as replay: the family is committed revoked, `replay_detected_at` is recorded, and `security.refresh_replay_detected` is attempted in a separate best-effort audit transaction. No plaintext refresh token is stored.

Current pre-Phase-2 refresh tokens without `jti` remain usable once when their stored hash matches; rotation upgrades them to the hardened format. Access tokens without `sid` are rejected and can recover through the existing refresh flow.

### Absolute session expiration

Login creates both `expires_at` (sliding idle deadline) and immutable `absolute_expires_at`. Legitimate refresh sets:

```text
expires_at = min(now + JWT_REFRESH_TTL_DAYS, absolute_expires_at)
```

The default `SESSION_ABSOLUTE_TTL_DAYS` is 30 days. Access authentication, refresh, session listing, and active-session administration all enforce both deadlines.

## 4. Changes made

### Issue 1 — session-bound access tokens

- **Root cause:** access authentication had no link to `UserSession`.
- **Files:** `backend/app/core/security.py`, `backend/app/services/auth_service.py`, `backend/app/api/deps.py`, auth/admin routes and tests.
- **Before:** a revoked session's access token worked until JWT expiry.
- **After:** access JWTs require `sid`; all protected requests validate the corresponding active session in PostgreSQL. Single-session revocation remains isolated from other sessions.

### Issue 2 — WebSocket lifetime and revocation

- **Root cause:** handshake-only user authentication and connections indexed only by user.
- **Files:** `backend/app/main.py`, `backend/app/realtime/ws_manager.py`.
- **Before:** an accepted socket had no authentication deadline or session identity.
- **After:** sockets are indexed by user and session, expose the session in `hello`, close at effective authentication expiry, reject revoked-session reconnects, and can be closed by session or user control events.

### Issue 3 — one-time WebSocket tickets

- **Root cause:** browser and helper clients placed the access JWT directly in the URL; backend kept multiple JWT handshake paths.
- **Files:** `backend/app/services/ws_ticket_service.py`, `backend/app/api/routes/auth.py`, `backend/app/main.py`, frontend runtime/hook/types, and three verifier/client scripts.
- **Before:** `?token=<JWT>` was accepted.
- **After:** only `?ticket=<short-lived opaque value>` is accepted; issue is authenticated over HTTP, storage is hashed, and consumption is atomic/single-use.

### Issue 4 — distributed revocation

- **Root cause:** only a current-process user-wide close existed, and most revocation routes did not call it.
- **Files:** `backend/app/realtime/auth_control.py`, `backend/app/realtime/ws_manager.py`, auth/admin routes, `backend/app/main.py`.
- **Before:** Backend A could not close a matching socket on Backend B.
- **After:** every manager listens for minimal Redis control events. Logout, explicit revoke, logout-all, replay, administrator session revoke, and deactivation dispatch after database commit.

### Issue 5 — refresh replay detection

- **Root cause:** stale/current distinction existed only as a hash mismatch and was not treated as compromise; tokens could repeat within one second.
- **Files:** `backend/app/core/security.py`, `backend/app/services/auth_service.py`, model/migration/tests.
- **Before:** stale token reuse returned an invalid-token response and the rotated token remained usable.
- **After:** random `jti`, row-locked rotation, replay timestamp/event, and committed family revocation make both stale and newly rotated tokens unusable while unrelated sessions remain active.

### Issue 6 — absolute lifetime

- **Root cause:** refresh always reset the only session deadline.
- **Files:** config, model, migration, auth service/schema, `.env.example`, frontend session type, docs/tests.
- **Before:** continuous refresh could keep a session alive indefinitely.
- **After:** idle refresh cannot pass the stored absolute deadline; access and refresh both reject an absolute-expired session.

## 5. Database migrations

`backend/alembic/versions/0017_auth_session_hardening.py` adds:

- `user_sessions.absolute_expires_at timestamptz NOT NULL`;
- `user_sessions.replay_detected_at timestamptz NULL`;
- `ix_user_sessions_active_lifetime` over user/revocation/idle/absolute fields.

Existing sessions are not deleted. Migration backfill sets their absolute deadline to the later of their current idle deadline or a one-time 30-day compatibility window. A downgrade/upgrade test with an existing row verified non-null, non-shortening backfill behavior. New sessions use configured policy.

## 6. Tests added

`backend/tests/security/test_phase2_auth_hardening.py` contains 19 tests:

- `test_active_session_access_token_works`
- `test_logout_invalidates_existing_access_token`
- `test_revoking_session_a_does_not_revoke_session_b`
- `test_logout_all_invalidates_access_tokens_from_all_sessions`
- `test_nonexistent_and_legacy_access_session_claims_are_rejected`
- `test_refresh_rotation_replay_revokes_only_compromised_family`
- `test_current_legacy_refresh_without_jti_rotates_into_hardened_format`
- `test_refresh_replay_revocation_survives_audit_failure`
- `test_refresh_extends_idle_lifetime_but_not_absolute_lifetime`
- `test_absolute_expired_session_cannot_refresh_or_authenticate_access`
- `test_authenticated_ticket_is_opaque_bound_and_single_use`
- `test_websocket_ticket_expires_before_use`
- `test_anonymous_and_expired_access_cannot_create_websocket_ticket`
- `test_ticket_cannot_be_rebound_to_another_session`
- `test_valid_ticket_connects_correct_user_and_revoked_session_cannot_reconnect`
- `test_raw_access_jwt_query_parameter_is_rejected`
- `test_socket_closes_when_authentication_lifetime_expires`
- `test_local_and_redis_revocation_close_open_session_idempotently_without_tokens`
- `test_redis_outage_does_not_undo_durable_logout`

The existing superadmin test was updated to construct a valid session-bound access token. The test fixture applies the new columns when exercising an already-created development test schema.

## 7. Validation results

Validation used isolated PostgreSQL 16 container `messaging-phase2-security-postgres` on host port `55433`; it did not use the repository's normal development database.

```text
python -B -m alembic upgrade head
passed on a fresh database through 0017_auth_session_hardening

alembic downgrade 0016_backfill_owner_memberships; insert existing session; alembic upgrade head
migration backfill verification: true|true|true

python -B -m pytest -q tests/security/test_phase2_auth_hardening.py
19 passed, 1 warning in 10.31s

python -B -m pytest -q tests/security/test_phase1_hardening.py tests/test_superadmin.py
36 passed, 1 warning in 11.94s

python -B -m pytest -q
124 passed, 1 warning in 54.22s

npm run typecheck
passed

docker compose config --quiet
passed

python -B -c "from app.main import app; ... app.openapi() ..."
passed; 57 OpenAPI paths, including /v1/auth/ws-ticket
```

The warning is the existing `passlib` access to deprecated `argon2.__version__` metadata. `git diff --check` passed; Ruff, mypy, and pyright are not installed in this environment. The first local focused attempt reported `5 passed, 11 skipped` because the configured PostgreSQL host was unavailable; Docker Desktop was started and all final database-backed validation used the isolated container. No live two-backend or browser end-to-end run was performed.

## 8. Remaining risks

- Access and refresh credentials remain JavaScript-readable in a cookie/localStorage; this is still demo-grade against XSS and is not an httpOnly-cookie/CSRF design.
- Redis is required for ticket issuance/consumption. During Redis failure, durable database revocation remains correct, but a remote socket that misses the control event can remain until its access-authentication deadline.
- Redis control pub/sub is ephemeral; there is no durable control-event replay. Database checks protect every later HTTP request and reconnect.
- Each protected HTTP request performs one indexed user/session database query. No cache was added without a safe invalidation design.
- A stale refresh token presented after its JWT expiry is classified as expired, not replay.
- Tests cover the control protocol and local handler, but not two actual backend processes or a real Redis outage/recovery sequence.
- Browser and verifier ticket flows were type-/unit-tested but not rerun against the complete RabbitMQ/Redis/worker stack in this phase.
- Existing Phase 1 limitations remain: browser session storage, attachment encryption, encryption-key rotation/KMS, deployment credential hardening, and broad broker integration coverage.

## 9. Recommended Phase 3

1. Migrate browser authentication to `httpOnly`, `Secure`, `SameSite` cookies with an explicit CSRF design and logout semantics.
2. Add a two-backend integration test proving Redis-delivered session and user revocation, plus an outage/recovery test and operational alerting.
3. Add a live WebSocket ticket/reconnect scenario to the Docker demo verifier and CI broker path.
4. Address attachment encryption and encryption-key rotation/key-ring/KMS deployment without redesigning the pub/sub core.
5. Harden Docker credentials/network exposure and add production session/secret runbooks.

## 10. Files changed

- `.env.example`
- `README.md`
- `REPOSITORY_ASSESSMENT.md`
- `SECURITY_HARDENING_PHASE2_REPORT.md`
- `backend/alembic/versions/0017_auth_session_hardening.py`
- `backend/app/api/deps.py`
- `backend/app/api/routes/admin.py`
- `backend/app/api/routes/auth.py`
- `backend/app/core/config.py`
- `backend/app/core/security.py`
- `backend/app/db/models.py`
- `backend/app/main.py`
- `backend/app/realtime/auth_control.py`
- `backend/app/realtime/ws_manager.py`
- `backend/app/schemas/auth.py`
- `backend/app/services/admin_service.py`
- `backend/app/services/auth_service.py`
- `backend/app/services/ws_ticket_service.py`
- `backend/tests/conftest.py`
- `backend/tests/security/test_phase2_auth_hardening.py`
- `backend/tests/test_superadmin.py`
- `docs/FINAL_MVP_STATUS.md`
- `docs/REQUIREMENTS_MAPPING.md`
- `docs/SECURITY.md`
- `docs/STABILIZATION_STATUS.md`
- `docs/TESTING.md`
- `frontend/src/hooks/use-websocket.tsx`
- `frontend/src/services/api/runtime.ts`
- `frontend/src/types/api.ts`
- `scripts/verify_approval_flow.py`
- `scripts/verify_demo_flow.py`
- `scripts/ws_client.py`
