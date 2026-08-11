# Security Hardening Phase 8 — Production Boundary Report

Last updated: 2026-08-11

## 1. Scope

Phase 8 implements the remaining AV-11 browser-session and production-deployment boundary without redesigning the established token families, WebSocket tickets, broker generations, membership authorization, sync, invite, upload, attachment-integrity, encryption, or delivery architecture.

The repository now has three deliberately separate paths:

- `docker-compose.yml`: development only.
- `docker-compose.hardened.yml`: hardened local/demo validation.
- `docker-compose.production.yml`: production-oriented single-host deployment.

## 2. Browser authentication architecture

The legacy JSON token endpoints remain available for scripts and non-browser clients. The browser uses `POST /v1/auth/browser/login`, `GET /v1/auth/browser/csrf`, `POST /v1/auth/browser/refresh`, and `POST /v1/auth/browser/logout`.

Browser login delegates authentication/session creation to the existing `AuthService`, returns only the access JWT, and writes the refresh JWT to an `HttpOnly` cookie. The frontend stores the access JWT only in its in-memory Zustand state. It does not persist authentication credentials in localStorage, sessionStorage, IndexedDB, persistent Zustand state, or JavaScript-readable authentication cookies.

Production refresh and CSRF cookies use the `__Host-` prefix, `Secure`, `Path=/`, no `Domain`, and `SameSite=Strict`. Local development uses unprefixed non-Secure cookies while preserving `HttpOnly` on the refresh credential.

Cookie-authorized refresh/logout requests require all of:

- an exact allowed `Origin`;
- the random readable CSRF cookie;
- the same value in `X-CSRF-Token`, compared in constant time;
- the `HttpOnly` refresh cookie.

Successful refresh uses the existing row-locked refresh rotation, idle/absolute lifetime, replay-family revocation, and cross-instance session behavior, then rotates both cookies and returns a new memory access JWT. Page bootstrap obtains a CSRF value, refreshes with `credentials: include`, stores the new access token in memory, and loads `/me`. Browser logout validates CSRF, revokes the current server session, sends the existing socket-revocation event, clears both cookies, and clears frontend memory. Server-side logout-all or administrative revocation causes the next cookie refresh to fail.

WebSocket authentication remains unchanged: the memory access JWT requests a short-lived one-use opaque ticket; JWTs are never placed in WebSocket URLs.

## 3. Credential architecture

Production Compose requires credentials using `${VARIABLE:?required}` interpolation. PostgreSQL receives separate administrative/migration and application usernames/passwords. The application role is forced to `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, and `NOREPLICATION`, and receives the schema/table/sequence privileges required by backend and worker. PostgreSQL public-schema creation is revoked.

RabbitMQ requires a non-default username/password and exposes no management port. Redis starts with `--requirepass`; clients and health checks authenticate. Backend and worker URLs use the required credentials only through injected environment variables.

JWT, Fernet, infrastructure, and optional bootstrap-superadmin secrets are deployment inputs. `.env.production.example` contains placeholders and generation commands only. `.env`, `.env.production`, `secrets/`, private keys, PEM files, real certificates, and generated credentials are not committed. The application does not dump these URLs, cookies, tokens, or keys during startup.

## 4. Migration/bootstrap architecture

The backend image now defaults to Uvicorn only. In production, the one-shot `migrate` service authenticates with the administrative database credential, runs `alembic upgrade head`, the existing schema bootstrap, and the runtime-role grant step. Backend and worker start afterward with the restricted application credential and do not run migrations.

Initial superadmin provisioning is an explicit `bootstrap` profile operation:

```bash
docker compose -f docker-compose.production.yml --profile bootstrap run --rm bootstrap-superadmin
```

Normal backend startup neither creates nor promotes a superadmin and never prints the bootstrap password.

## 5. Container hardening

| Service | Observed/configured runtime user | Root filesystem | Capabilities / NNP | Writable scope |
|---|---|---|---|---|
| `migrate` | `messaging`, UID 10001, non-root | Read-only | Drop `ALL`; `no-new-privileges` | `/tmp` tmpfs only |
| `backend` | `messaging`, UID 10001, non-root | Read-only | Drop `ALL`; `no-new-privileges` | `/data/uploads` named volume; `/tmp` tmpfs |
| `worker` | `messaging`, UID 10001, non-root | Read-only | Drop `ALL`; `no-new-privileges` | `/tmp` tmpfs only |
| `frontend` | `messaging`, UID 10001, non-root | Read-only | Drop `ALL`; `no-new-privileges` | `/tmp` and `.next/cache` tmpfs |
| `proxy` | UID 101, non-root | Read-only | Drop `ALL`; `no-new-privileges` | `/tmp` and generated `conf.d` tmpfs; configuration/certificate mounts read-only |
| `bootstrap-superadmin` | `messaging`, UID 10001, non-root | Read-only | Drop `ALL`; `no-new-privileges` | `/tmp` tmpfs only |
| `postgres` | Official image default; observed UID 0 at container command boundary | Writable as required | Official image defaults | PostgreSQL named data volume; init script read-only |
| `rabbitmq` | Official image default; observed UID 0 at container command boundary | Writable as required | Official image defaults | RabbitMQ named data volume |
| `redis` | Official image default; observed UID 0 at container command boundary | Writable as required | Official image defaults | Redis named data volume |

The application images set `PYTHONDONTWRITEBYTECODE=1`. Upload write access is granted through image ownership/volume design, not `chmod 777`. Compose applies PID, memory, and CPU limits to every production service. The stateful official images were not given incompatible read-only/capability restrictions; stronger image-specific reduction remains an operator hardening option.

## 6. Network exposure

| Profile | Host-published ports |
|---|---|
| Development | PostgreSQL `5432`, RabbitMQ `5672/15672`, Redis `6379`, backend `8000`, frontend `3000` |
| Hardened local/demo | Proxy `8080` only |
| Production | Proxy `80` and `443` only |

Production uses `edge` and Docker-internal `internal` networks. The proxy joins both; all other services join only `internal`. Actual container inspection showed empty `PortBindings` for PostgreSQL, RabbitMQ, Redis, backend, worker, and frontend. `docker ps` showed host mappings only for proxy ports 80/443.

The validation host separately had an unrelated pre-existing PostgreSQL process listening on host port 5432. It was not the production Compose PostgreSQL container and was not modified. Therefore the verified claim is that the production stack publishes no stateful-service ports, not that the test machine had no unrelated listeners.

## 7. TLS and proxy security

Nginx listens unprivileged on container ports 8080/8443, mapped to host 80/443. The known HTTP host returns a permanent `308` HTTPS redirect. Unknown HTTP/HTTPS hosts use a default server that rejects the request. TLS accepts versions 1.2 and 1.3.

Certificate and key paths are required production inputs and mounted read-only at `/etc/nginx/tls/tls.crt` and `/etc/nginx/tls/tls.key`; they are never included in images or source. Validation used a disposable self-signed certificate outside the repository. This proves TLS termination/configuration, not public CA trust.

The proxy config includes bounded request/header/body timeouts, a 25 MiB request-body limit, per-client and total connection limits, upstream connect/send/read timeouts, response buffering controls, and a 35-minute WebSocket read timeout with upgrade forwarding.

## 8. Security headers / CSP

Actual HTTPS responses contained:

```text
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self' data:; connect-src 'self' wss:; worker-src 'self' blob:; upgrade-insecure-requests
```

HSTS is sent only by the production HTTPS server. The CSP forbids objects, framing, foreign bases, and `unsafe-eval`. Next.js currently requires inline bootstrap scripts and application styling, so `unsafe-inline` remains for `script-src` and `style-src`; this is the exact known CSP weakness. A future nonce-based Next response pipeline could remove the script exception.

## 9. Liveness/readiness

`GET /health` is a public minimal liveness endpoint returning exactly `{"status":"ok"}`. It contains no database, Redis, RabbitMQ, host, credential, or error details.

`GET /ready` performs internal PostgreSQL/Redis/RabbitMQ checks and returns 503 when unavailable. Docker health checks call it inside the internal network. Production Nginx returns 404 for `/ready` and `/v1/ready`, so dependency detail is not exposed publicly.

## 10. Production CORS/host policy

Production requires an explicit exact HTTPS CORS origin and rejects wildcard or plain-HTTP origins when credentialed CORS is enabled. Development localhost origins remain supported.

`TrustedHostMiddleware` uses explicit configured hosts. Production rejects empty/wildcard trusted-host configuration. Nginx also has exact `${PUBLIC_HOST}` servers plus unknown-host rejection. API docs, ReDoc, and OpenAPI are disabled by secure production default and explicitly blocked at the proxy; development retains docs. Production plain-HTTP external avatar/wallpaper URLs are rejected, while protected local upload paths and HTTPS URLs remain allowed.

## 11. Tests added

`backend/tests/security/test_phase8_production_hardening.py` adds these focused invariants:

- `test_browser_login_hides_refresh_json_and_sets_httponly_cookie`: B1.
- `test_production_cookie_is_secure_httponly_host_only_and_strict`: B2 and `__Host-` rules.
- `test_browser_refresh_rejects_missing_and_mismatched_csrf`: B3/B4.
- `test_cross_origin_browser_refresh_is_denied`: B5.
- `test_browser_refresh_rotates_and_old_cookie_replay_revokes_family`: B6/B7.
- `test_browser_logout_revokes_session_and_clears_both_cookies`: B8.
- `test_server_side_revocation_makes_browser_refresh_fail`: B9.
- `test_development_cookie_mode_remains_http_only_without_secure`: development compatibility.
- `test_production_configuration_rejects_wildcard_cors_and_insecure_cookie`: fail-safe production configuration.
- `test_development_docs_stay_enabled_and_public_health_is_minimal`: development docs and liveness.
- `test_public_liveness_does_not_expose_dependency_names`: public health privacy.
- `test_production_external_profile_media_requires_https`: mixed-content prevention.
- `test_frontend_auth_uses_memory_only_tokens_and_browser_refresh_bootstrap`: B10/B11 and static persistence inspection.

## 12. Container/network experiments

The disposable production stack completed migration `0001` through `0021`; `migrate` exited 0. Backend, worker, frontend, PostgreSQL, RabbitMQ, Redis, and proxy then remained healthy/running.

Observed runtime UIDs were backend `10001`, worker `10001`, frontend `10001`, and proxy `101`. Docker inspection confirmed read-only roots, dropped `ALL` capabilities, and `no-new-privileges:true` on all application/proxy containers.

Actual production port inspection showed only `0.0.0.0:80->8080` and `0.0.0.0:443->8443` (plus IPv6 equivalents) on the proxy. Infrastructure and application `PortBindings` were `{}`.

Credential probes rejected PostgreSQL `postgres/postgres`, RabbitMQ `guest/guest`, and unauthenticated Redis. The runtime PostgreSQL role reported false for superuser, createdb, and createrole, and actual `CREATE DATABASE` and `CREATE ROLE` attempts were denied.

HTTP returned `308` to the expected HTTPS host. HTTPS returned 200 for a representative frontend page using the disposable self-signed certificate, with all headers in section 8. Unknown HTTPS Host was rejected. `/health` returned only `{"status":"ok"}`; public readiness, docs, and OpenAPI requests returned 404.

The full demo verifier passed inside the production network, including registration/login, channel creation/join, persistent publish, RabbitMQ worker dispatch, Redis/WebSocket live delivery, REST sync/backfill, audit integrity, and unauthorized/private-upload denial.

No generated secret value appears in this report.

## 13. Validation results

Commands used below received disposable environment values without writing or printing them:

```text
python -B -m pytest -q backend/tests/security/test_phase8_production_hardening.py
13 passed, 1 warning in 6.43s

python -B -m pytest -q <Phase 2, Phase 4, Phase 5, Phase 6, Phase 7, post-Phase-7, and Phase 8 files>
128 passed, 1 warning in 72.26s

python -B -m pytest -q
252 passed, 1 warning in 122.58s

npm run typecheck
passed

npm run build
passed; Next.js emitted only its middleware filename deprecation warning

docker compose config --quiet
passed

docker compose -f docker-compose.hardened.yml config --quiet
passed

docker compose -f docker-compose.production.yml config --quiet
passed with disposable required values

docker compose -f docker-compose.production.yml build backend worker frontend
passed

python scripts/verify_demo_flow.py --base-url http://backend:8000/v1
passed from a container attached to the production internal network
```

The single Python warning is the existing passlib/argon2 deprecation/version warning. No backend regression failed. The production image build also ran and passed the Next.js production compilation.

## 14. Remaining production limitations

- No external KMS/centralized secret store, automated secret rotation, or encryption-key rotation redesign.
- Attachments remain server-readable and are not encrypted at rest by the message-body Fernet layer.
- No public certificate issuance/renewal automation; the validation certificate was disposable and self-signed.
- Rate-limit/download/socket fallback counters remain partly per process; no distributed multi-replica quota coordinator or multi-host load certification exists.
- Provider-backed email verification delivery is not implemented.
- The known multi-socket presence reliability edge case remains outside Phase 8.
- No HA PostgreSQL, RabbitMQ, Redis, multi-region deployment, Kubernetes, service mesh, or distributed tracing platform.
- Operators still need backup/restore drills, monitoring/alerting, patching, log retention, incident response, DNS, firewall, certificate, and secret-rotation procedures.
- No automated browser E2E suite, controlled broker-outage CI job, or slow-client/load test.
- External HTTPS profile media may reveal the viewer's IP address to its remote host.
- Backend and worker share one restricted runtime database role; separate roles can be introduced later if operationally justified.
- Event hashes are not externally anchored; a fully privileged database operator can recompute them.

## 15. Files changed

Application/configuration:

- `.env.example`, `.env.production.example`, `.gitignore`
- `backend/Dockerfile`, `worker/Dockerfile`, `frontend/Dockerfile`
- `backend/app/core/config.py`, `backend/app/core/browser_security.py`, `backend/app/core/identifiers.py`
- `backend/app/api/routes/auth.py`, `backend/app/api/routes/health.py`
- `backend/app/schemas/auth.py`, `backend/app/main.py`
- `backend/app/db/grant_runtime_role.py`
- `frontend/src/services/auth/browser-session.ts`; removed `frontend/src/services/auth/session-cookie.ts`
- `frontend/src/services/api/client.ts`, `frontend/src/store/authStore.ts`, `frontend/src/hooks/use-auth.ts`, `frontend/src/middleware.ts`, `frontend/src/types/api.ts`, `frontend/next.config.ts`
- `docker-compose.yml`, `docker-compose.hardened.yml`, `docker-compose.production.yml`
- `deploy/postgres/init-app-role.sh`, `deploy/nginx/templates/default.conf.template`
- `backend/tests/security/test_phase8_production_hardening.py`

Documentation/status:

- `README.md`
- `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/TESTING.md`, `docs/DEMO_GUIDE.md`
- `docs/REQUIREMENTS_MAPPING.md`, `docs/STABILIZATION_STATUS.md`, `docs/FINAL_MVP_STATUS.md`
- `REPOSITORY_ASSESSMENT.md`
- `SECURITY_HARDENING_PHASE8_PRODUCTION_REPORT.md`

## 16. Final maturity assessment

Production-oriented deployment profile implemented and validated for the single-host university MVP threat model.

Phase 8 closes the identified JavaScript-persisted refresh credential, CSRF, default production credential, runtime migration privilege, root application process, TLS/header, readiness exposure, CORS, and trusted-host gaps. The result is materially stronger and demonstrably runnable, but it is not described as fully secure, enterprise-ready, foolproof, or unhackable. Section 14 remains the boundary for any real public deployment claim.
