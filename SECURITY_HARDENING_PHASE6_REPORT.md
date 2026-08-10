# Security Hardening Phase 6 Report

## 1. Scope

Phase 6 addressed only the two Medium findings from
`SECURITY_VERIFICATION_AFTER_PHASE5.md`:

- P5V-01: email-targeted invitations followed a mutable account email;
- P5V-02: per-user download leases did not bound many-account slow streams.

The FastAPI/PostgreSQL/RabbitMQ/Redis/WebSocket/worker/Next.js architecture was
preserved. P5V-03, P5V-04, AV-09, AV-10, and full AV-11 production hardening
were not substantially changed. The new proxy path is intentionally limited to
the HTTP/download resource boundary required by P5V-02.

## 2. Findings addressed

| Finding | Current-source confirmation | Result |
| --- | --- | --- |
| P5V-01 | **CONFIRMED** | Existing-account email targets now resolve once to immutable user ID. Unresolved targets require verified ownership of the exact normalized current email. Email changes clear verification. |
| P5V-02 | **CONFIRMED** | Protected download admission now atomically bounds user, trusted client IP, and backend-process total. A separate Nginx-fronted Compose path adds connection/body/header/buffering/inactivity controls and does not publish backend/state-service ports. |

## 3. Invite identity architecture

### Existing-account resolution

Email normalization is centralized in `app.core.email_identity.normalize_email`
and applies trimming plus lowercase conversion. It is used by registration,
profile update, invite issuance/acceptance, email lookup/login, and superadmin
bootstrap. No provider-specific transformation is performed.

When an email invitation is created, the service looks up the current normalized
email owner. If one exists, it stores:

```text
invited_user_id = current immutable User.id
invited_email   = normalized issuance-time snapshot
```

Acceptance treats `invited_user_id` as authoritative. It does not also require
the snapshot to match, so the intended user can change email without losing the
invite and a later owner of the old address cannot acquire it.

### Pre-registration semantics and verification state

`users.email_verified_at TIMESTAMPTZ NULL` represents proof for the exact current
email. Registration does not mark email verified. `PATCH /me` clears verification
when the canonical address changes and preserves it only when case/whitespace
normalizes to the same address.

An invitation whose email had no existing account retains
`invited_user_id = NULL`. Acceptance requires both:

```text
normalize(current_user.email) == normalize(invited_email)
current_user.email_verified_at IS NOT NULL
```

Token possession plus changing an unverified profile value is insufficient.

The repository has no email provider or verification-token delivery/completion
endpoint. It therefore does not invent proof or expose a development shortcut
that marks arbitrary addresses verified. Phase 6 tests simulate the trusted
external completion boundary by persisting `email_verified_at`; a real deployment
must supply mailbox verification before unresolved pre-registration invitations
can be accepted.

### Generic and explicit user-ID compatibility

- Explicit `invited_user_id` remains one-use and authoritative.
- Generic invitations still have neither target field and remain reusable until
  revocation, expiry, or channel deletion.
- Existing Phase 5 channel-then-invite lock ordering and acceptance semantics
  remain unchanged.

## 4. Download resource architecture

### Atomic application admission

`DownloadConcurrencyLimiter` uses one `asyncio.Lock` to check and increment all
three dimensions in one critical section:

```text
MAX_CONCURRENT_DOWNLOADS_PER_USER   default 3
MAX_CONCURRENT_DOWNLOADS_PER_IP     default 12
MAX_CONCURRENT_DOWNLOADS_GLOBAL     default 100 per backend process
```

If any dimension is full, no counter changes. Only positive active user/IP keys
are stored; zero-count keys are removed. Consequently both maps are bounded by
the process-global active-stream cap.

One idempotent `DownloadLease` owns all three reservations. It releases them on:

- normal completion;
- client cancellation;
- ASGI send failure;
- file open/stat failure;
- audit/database/route failure after admission;
- response-construction failure.

Authorization and audit work completes and the SQLAlchemy session closes before
the potentially slow response body begins, preserving the Phase 4 database
lifetime invariant.

### Trusted client address

Direct mode has an empty `TRUSTED_PROXY_CIDRS` list and ignores arbitrary
`X-Forwarded-For`. A forwarded address is accepted only when the immediate peer
matches an explicit trusted CIDR and the header contains exactly one valid IP.

The hardened Compose network assigns Nginx `172.31.240.10` and configures only
`172.31.240.10/32` as trusted. Nginx overwrites, rather than appends, the client
address header. Authentication/invite-preview rate limiting and protected
downloads use the same resolver.

### Proxy-bounded path

`docker-compose.yml` remains the direct development workflow.
`docker-compose.hardened.yml` is the recommended bounded HTTP path:

```text
client -> Nginx :8080 -> frontend/backend
                         PostgreSQL/RabbitMQ/Redis remain internal
```

Nginx configures:

- 26 MiB request body cap;
- 2 KiB base and four 8 KiB large header buffers;
- header/body/keepalive/upstream/write-inactivity timeouts;
- 20 active requests per client IP and 200 per proxy server;
- ordinary upstream response buffering with a 32 MiB temporary-file cap;
- separate WebSocket upgrade handling without response buffering.

The buffering layer lets FastAPI commonly finish a protected file response and
release its application lease even when the downstream client is slower. Nginx
`send_timeout` bounds inactivity between writes; it does not guarantee a minimum
throughput or a total response duration. OS file-descriptor/socket limits and
multi-proxy coordination remain operator responsibilities.

## 5. Database migration

`backend/alembic/versions/0020_phase6_invite_identity.py`:

- adds nullable `users.email_verified_at`;
- refuses to choose an owner if historical case/whitespace-normalized user emails
  collide;
- normalizes historical user and invite emails;
- creates a partial unique index on `lower(btrim(users.email))`;
- resolves historical email-only invites to the current unambiguous user ID;
- leaves no-account email invites unresolved and every historical email unverified;
- preserves existing user-ID-targeted and generic invitations.

The downgrade removes the new column/index but deliberately retains normalized
email snapshots and immutable invite bindings because erasing them would be
lossy and could restore the authorization flaw.

Migration evidence:

- fresh database upgraded through revision `0020_phase6_invite_identity`;
- a database upgraded first to 0019 was populated with users plus existing-email,
  future-email, explicit-user-ID, and generic invites;
- upgrading to head bound only the existing-email invite, normalized both email
  snapshots, preserved user-ID/generic rows, and left all users unverified.

## 6. Tests added

`backend/tests/security/test_phase6_medium_hardening.py` contains 19 test cases:

1. existing account email resolves to immutable ID;
2. email reassignment cannot transfer the token, while the original ID can accept;
3. a real email change clears verification;
4. pre-registration invite denies unverified and accepts after simulated proof;
5. token plus unverified profile email is denied;
6. explicit user-ID targeting remains correct;
7. generic links remain reusable;
8. concurrent email claim has one normalized owner and cannot transfer the invite;
9. user download boundary;
10. IP boundary across many users;
11. global boundary across users/IPs;
12. concurrent atomic admission cannot oversubscribe;
13. failed admission consumes no partial capacity;
14-15. cancellation and ASGI send failure release all capacity exactly once;
16. missing-file/stat failure releases all capacity;
17. database session closes before streaming;
18. response construction failure releases all route capacity;
19. untrusted forwarding is ignored and explicit proxy trust is honored.

Phase 4/5/P0 direct route tests were updated only to provide a request/client
address to the now layered download admission API. Their assertions were not
weakened.

## 7. Adversarial scenarios

- **Attack A - email reassignment:** denied. The invitation remains bound to the
  intended user ID after their email changes. The new owner of the old address
  receives `403 FORBIDDEN`; the original user can accept.
- **Attack B - pre-registration theft:** denied. A token holder who changes an
  unverified profile email receives `EMAIL_VERIFICATION_REQUIRED`. Acceptance
  succeeds only after the trusted verification state is established.
- **Attack C - many accounts from one IP:** bounded. The per-IP active limit
  stops account multiplication before the process-global limit when configured
  lower.
- **Attack D - many source IPs:** bounded in one backend by the process-global
  limit. Separate backend replicas retain independent counters.

## 8. Validation results

All database-backed final tests used disposable PostgreSQL 16 container
`messaging-phase6-security-postgres` on `127.0.0.1:55442`.

```text
python -B -m pytest -q tests/security/test_phase6_medium_hardening.py
19 passed, 1 warning in 10.84s

python -B -m pytest -q tests/security/test_phase1_hardening.py ... test_phase5_medium_hardening.py
98 passed, 1 warning in 59.34s

python -B -m pytest -q
195 passed, 1 warning in 106.43s

python -B -m alembic upgrade head (fresh PostgreSQL)
passed; 0020_phase6_invite_identity (head)

0019 fixture with existing-email/future-email/user-ID/generic invites -> upgrade head
passed; expected normalization/binding/unverified state verified with SQL

npm run typecheck
passed

docker compose config --quiet
passed

docker compose -f docker-compose.hardened.yml config --quiet
passed

docker run ... nginx:1.27-alpine nginx -t (with temporary backend/frontend host mappings)
passed; syntax is ok and configuration test is successful

git diff --check
passed
```

The first focused run reported `18 passed, 1 failed`: the new explicit-user-ID
test referenced an ORM object after deliberately rolling back its session. The
test was corrected to retain the UUID before rollback; no implementation change
was needed, and the final focused/full runs passed.

The first standalone `nginx -t` attempt had no Compose DNS and failed with
`host not found in upstream "backend:8000"`. Repeating the syntax check with
temporary `--add-host` mappings passed; the hardened Compose rendering also
passed. No live slow-reader, proxy throughput, or many-account TCP load test was
performed. The one warning in pytest is the existing Passlib access to deprecated
`argon2.__version__` metadata.

## 9. Remaining limitations

- Email verification delivery/issuance/completion is not implemented. Tests
  simulate only the trusted persisted completion state.
- Historical emails remain unverified after migration by design.
- A legacy database with normalized duplicate email owners must be manually
  corrected before migration; the migration fails rather than selecting one.
- User/IP/global application limits are per backend process, not distributed.
- Nginx connection zones are per proxy instance and this scoped path has no TLS.
- `send_timeout` is an inactivity limit, not a minimum-throughput guarantee.
- Proxy behavior was configuration-reviewed and syntax-validated, not load-tested
  against real slow downstream TCP clients.
- Direct `docker-compose.yml` still publishes development ports and remains a
  local/demo path; AV-11 is not closed.

## 10. Remaining findings

The following findings were not substantially fixed or reclassified:

- **P5V-03 (Low):** advisory/row lock ordering deadlock risk;
- **P5V-04 (Low):** unbounded authentication fields/raw request bodies;
- **AV-09 (Low):** message-attachment relational channel consistency;
- **AV-10 (Low):** unknown environment labels fail open;
- **AV-11 (Low):** full production deployment/browser-session posture.

## 11. Recommended Phase 7

1. Establish one database/advisory lock order and isolate/retry worker failure
   auditing to address P5V-03.
2. Add strict authentication schema/body limits and bounded failed-login audit
   metadata for P5V-04.
3. Then address AV-09 and AV-10 with targeted migrations/config validation.
4. Keep AV-11 as a separate production-readiness effort: TLS, managed unique
   secrets, security headers, non-root/restricted containers, HttpOnly/CSRF-aware
   sessions, and controlled slow-client/multi-replica load testing.
5. Add provider-backed email verification only if pre-registration email invite
   delivery is a required product/demo flow.

## 12. Files changed

### Invite identity and migration

- `backend/app/core/email_identity.py`
- `backend/app/db/models.py`
- `backend/app/schemas/auth.py`
- `backend/app/schemas/users.py`
- `backend/app/schemas/channels.py`
- `backend/app/services/auth_service.py`
- `backend/app/services/superadmin_bootstrap_service.py`
- `backend/app/services/channel_service.py`
- `backend/app/api/routes/users.py`
- `backend/alembic/versions/0020_phase6_invite_identity.py`
- `frontend/src/types/api.ts`

### Download admission and proxy

- `backend/app/core/client_ip.py`
- `backend/app/core/config.py`
- `backend/app/services/download_service.py`
- `backend/app/api/routes/messages.py`
- `backend/app/api/routes/auth.py`
- `backend/app/api/routes/memberships.py`
- `.env.example`
- `deploy/nginx/nginx.conf`
- `docker-compose.hardened.yml`

### Tests and compatibility fixtures

- `backend/tests/conftest.py`
- `backend/tests/security/test_phase6_medium_hardening.py`
- `backend/tests/security/test_phase4_p0_hardening.py`
- `backend/tests/security/test_phase5_medium_hardening.py`
- `backend/tests/test_p0_requirements.py`

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
- `SECURITY_HARDENING_PHASE6_REPORT.md`
