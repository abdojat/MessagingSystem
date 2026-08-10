# Security Repair After Phase 7

## 1. Scope

This repair addressed only the two Medium findings in
`SECURITY_VERIFICATION_AFTER_PHASE7.md`:

- R7-01 — proxied WebSocket connection rate-limit identity;
- R7-02 — implicit development mode when `ENVIRONMENT` is missing.

The current implementation was inspected and each defect was reproduced before
production code changed. Access/refresh authentication, WebSocket tickets,
per-user socket quotas, established-socket work budgets, broker desired state,
membership-generation authorization, sync, uploads, and other Phase 1–7 controls
were not redesigned.

## 2. R7-01 — Proxied WebSocket Client-IP Isolation

**CONFIRMED**

### Root cause

HTTP controls used `backend/app/core/client_ip.py`, but `_run_websocket()` used
`websocket.client.host` directly. Behind the hardened Nginx service, unrelated
clients therefore shared the fixed proxy identity `172.31.240.10` and the key:

```text
rl:websocket:connect:172.31.240.10
```

The pre-fix regression reproduced two different forwarded clients producing
that same key.

### Repair

`get_client_ip()` now accepts Starlette's shared `HTTPConnection` abstraction,
which supports both `Request` and `WebSocket`. `_run_websocket()` calls that
resolver before constructing:

```text
rl:websocket:connect:<resolved-client-ip>
```

Behavior is now consistent across HTTP and WebSocket controls:

- a direct connection uses the immediate peer;
- an untrusted peer cannot override its identity with `X-Forwarded-For`;
- the configured trusted Nginx `/32` may provide one valid, bounded forwarded IP;
- missing, invalid, comma-separated, or oversized values fall back to the peer.

The connection-level limiter, ticket issuance limiter, single-use ticket flow,
per-user socket quota, and Phase 5 per-socket command/history budgets remain
enabled and unchanged.

## 3. R7-02 — Explicit Environment Requirement

**CONFIRMED**

### Root cause

`Settings.environment` had a model default of `"dev"`. An absent
`ENVIRONMENT` therefore bypassed the intended explicit-selection policy and
could reach placeholder-secret behavior and the deterministic development
Fernet fallback.

### Repair

`Settings.environment` is now required and retains its existing trim/lowercase
validator. The resulting behavior is:

- missing or empty: configuration validation failure;
- explicit `dev`, `development`, `local`, or `test`: development/test behavior;
- any other nonempty label: strict production-like secret validation;
- a strong JWT secret plus valid Fernet key: accepted in a production-like label.

Because settings validation fails first when the environment is absent, that
state cannot reach the deterministic development encryption fallback. Existing
tests explicitly set `ENVIRONMENT=test`, and `.env.example` explicitly sets
`ENVIRONMENT=dev`, so development/test convenience remains opt-in.

`docker-compose.hardened.yml` was reviewed. It loads `.env`, and the backend now
fails startup if that file/input does not provide `ENVIRONMENT`; no Compose or
Nginx configuration change was necessary.

## 4. Tests Added

`backend/tests/security/test_post_phase7_repairs.py` adds these exact tests:

- `test_websocket_direct_connection_resolves_peer_ip` — direct peer identity;
- `test_websocket_untrusted_peer_cannot_spoof_forwarded_ip` — spoof resistance;
- `test_websocket_trusted_nginx_resolves_forwarded_client` — trusted proxy resolution;
- `test_websocket_entrypoint_uses_distinct_trusted_proxy_rate_limit_keys` — the real entrypoint builds distinct client keys;
- `test_websocket_rate_limit_buckets_are_isolated_behind_proxy` — exhausting Client A does not consume Client B's allowance;
- `test_websocket_malformed_forwarding_falls_back_to_trusted_peer` — missing, invalid, comma-separated, and oversized values use conservative fallback;
- `test_missing_environment_fails_configuration` — absent environment is rejected;
- `test_empty_environment_fails_configuration` — empty/whitespace environment is rejected;
- `test_explicit_development_environments_retain_development_behavior` — all four explicit development labels remain supported;
- `test_unknown_environments_remain_production_like` — `live`, `release`, `prod-eu`, and `foo` remain strict;
- `test_secure_production_like_environment_succeeds` — strong JWT/Fernet configuration succeeds;
- `test_missing_environment_cannot_reach_development_encryption_fallback` — validation stops the missing-environment path before fallback derivation.

Parameterized cases produce 21 focused test cases in total.

## 5. Validation Results

The pre-fix focused reproduction reported:

```text
3 failed, 18 passed
```

Post-repair validation:

| Command | Actual result |
|---|---|
| `cd backend && python -B -m pytest -q tests/security/test_post_phase7_repairs.py` | `21 passed in 1.43s` |
| `cd backend && python -B -m pytest -q tests/security/test_post_phase7_repairs.py tests/security/test_phase2_auth_hardening.py::test_raw_access_jwt_query_parameter_is_rejected` | `22 passed in 1.04s` |
| `cd backend && python -B -m pytest -q tests/security/test_phase6_medium_hardening.py tests/security/test_phase7_final_app_hardening.py` | `42 passed, 1 warning in 17.85s` against disposable PostgreSQL 16 |
| `cd backend && python -B -m pytest -q` | `239 passed, 1 warning in 126.92s` against disposable PostgreSQL 16 |
| `cd frontend && npm run typecheck` | Passed, exit code 0 |
| `docker compose config --quiet` | Passed, exit code 0 |
| `docker compose -f docker-compose.hardened.yml config --quiet` | Passed, exit code 0 |
| `git diff --check` | Passed, exit code 0 |

The sole backend warning is the existing `passlib` access to deprecated
`argon2.__version__` metadata. Disposable PostgreSQL containers used anonymous
storage and were removed after each validation run; repository Docker volumes
were not mounted or modified.

Nginx configuration did not change, so `nginx -t` was not rerun and no new
Nginx syntax result is claimed.

## 6. Remaining Limitations

This targeted repair does not complete AV-11 or make the project production-ready.
Known deferred areas include production TLS/security headers, infrastructure
credential redesign, non-root/restricted containers, centralized secret
distribution, KMS/key rotation, attachment encryption, httpOnly/CSRF browser
authentication, coordinated multi-replica resource limits, live proxy flood/load
testing, and multi-socket presence reliability.

The local emergency limiter and socket/resource quotas retain their documented
per-process limits when Redis/distributed coordination is unavailable.

## 7. Files Changed

- `backend/app/core/client_ip.py`
- `backend/app/core/config.py`
- `backend/app/main.py`
- `backend/tests/security/test_post_phase7_repairs.py`
- `docs/SECURITY.md`
- `docs/TESTING.md`
- `docs/STABILIZATION_STATUS.md`
- `docs/FINAL_MVP_STATUS.md`
- `docs/REQUIREMENTS_MAPPING.md`
- `REPOSITORY_ASSESSMENT.md`
- `SECURITY_REPAIR_AFTER_PHASE7_REPORT.md`
