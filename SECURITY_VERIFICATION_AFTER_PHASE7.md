# Security Verification After Phase 7

## 1. Executive Verdict

**Verdict: PASS WITH FINDINGS**

This was an independent source-code security review of the current GitHub repository after Phase 7 hardening.

Reviewed repository:

```text
https://github.com/abdojat/MessagingSystem
```

Reviewed commit:

```text
c2c58fac0fb7bce08a095791a715de509974ad5c
```

The review focused primarily on the Phase 6 and Phase 7 security changes, with a shorter regression review of earlier critical controls.

### Findings

| Severity | Count |
|---|---:|
| Critical | 0 |
| High | 0 |
| Medium | 2 |
| Low | 0 new repair-priority findings |
| Informational / known limitations | Several |

The two Medium findings are:

1. **R7-01 — WebSocket connection rate limiting collapses proxied clients onto the Nginx peer IP.**
2. **R7-02 — Missing `ENVIRONMENT` still silently selects development mode.**

Both should be repaired before declaring core application-security hardening complete.

---

## 2. Audit Method and Scope

This review inspected the current GitHub source directly rather than relying only on the Phase 7 hardening report.

Primary areas reviewed:

- Phase 7 request-body middleware;
- authentication input limits;
- environment classification;
- message-attachment relational integrity;
- PostgreSQL/advisory lock ordering;
- worker outbox failure handling;
- Phase 6 invite identity;
- aggregate protected-download limits;
- trusted proxy/client-IP handling;
- hardened Nginx/Compose deployment path;
- selected regressions from earlier authentication, broker, upload, and WebSocket security work.

### Important limitation

This was primarily a **source-code audit**.

The reviewer could inspect the current GitHub code and repository history, but could not independently clone and execute the repository in the local sandbox because outbound GitHub network access was unavailable there.

Therefore:

- runtime/concurrency conclusions below are based on source inspection unless explicitly stated otherwise;
- the previously reported `218 passed` backend test result comes from the Phase 7 project report, not an independently rerun suite in this audit;
- GitHub exposed no CI status checks for the reviewed commit.

This limitation does not invalidate source-visible findings, but runtime validation should be performed by Codex/local development after repairs.

---

# 3. New Finding R7-01

## R7-01 — Proxied WebSocket connection rate limiting uses the reverse-proxy IP

**Severity: Medium**

**Component:**
- `backend/app/main.py`
- `backend/app/core/client_ip.py`
- `deploy/nginx/nginx.conf`
- `docker-compose.hardened.yml`

### Root cause

HTTP code already has a trusted client-address resolver:

```text
backend/app/core/client_ip.py
```

Its policy is sound for the intended deployment:

- use the direct peer IP in direct-development mode;
- ignore attacker-controlled `X-Forwarded-For` from untrusted peers;
- trust one forwarded address only when the immediate peer belongs to `TRUSTED_PROXY_CIDRS`.

Protected download and HTTP abuse controls use this logic.

However, the WebSocket entrypoint in:

```text
backend/app/main.py
```

constructs its connection limiter key directly from:

```python
websocket.client.host
```

instead of the trusted client-IP resolver.

The hardened deployment configures Nginx at the fixed Docker-network address:

```text
172.31.240.10
```

and configures:

```text
TRUSTED_PROXY_CIDRS=["172.31.240.10/32"]
```

Nginx overwrites:

```text
X-Forwarded-For
```

with the real client address before forwarding traffic.

Because the WebSocket connection limiter ignores this trusted forwarded address, all proxied WebSocket clients are effectively keyed as:

```text
rl:websocket:connect:172.31.240.10
```

### Attack sequence

```text
attacker
    ↓
many unauthenticated WebSocket connection attempts
    ↓
Nginx
    ↓
FastAPI sees immediate peer = 172.31.240.10
    ↓
shared WebSocket connection rate-limit bucket is consumed
    ↓
unrelated legitimate users behind the same proxy are rate-limited
```

The current default is approximately:

```text
RATE_LIMIT_WEBSOCKET_PER_MINUTE=30
```

The outer connection limiter executes before successful WebSocket ticket authentication, so an unauthenticated attacker can consume this shared bucket.

### Impact

A single hostile client can temporarily deny WebSocket connection establishment to unrelated users using the hardened proxy.

HTTP remains available, but realtime functionality can be disrupted.

This is an application-level availability issue rather than a confidentiality/authentication bypass, so **Medium** is appropriate.

### Required repair

HTTP and WebSocket abuse controls should use the same trusted client-IP semantics.

A clean design is to generalize:

```text
get_client_ip(...)
```

to accept a Starlette `HTTPConnection` or another shared request/WebSocket abstraction.

Expected behavior:

```text
direct client
    -> peer IP

trusted Nginx
    -> validated single X-Forwarded-For IP

untrusted direct client with X-Forwarded-For
    -> ignore header
    -> peer IP
```

The WebSocket connection limiter should then use:

```text
rl:websocket:connect:<resolved-client-ip>
```

### Required regression cases

1. direct connection resolves to peer IP;
2. spoofed `X-Forwarded-For` from untrusted peer is ignored;
3. trusted Nginx resolves to real forwarded client IP;
4. two clients behind one Nginx receive distinct rate-limit keys;
5. exhausting Client A's allowance does not consume Client B's allowance;
6. malformed/comma-separated/oversized forwarded values fail conservatively.

---

# 4. New Finding R7-02

## R7-02 — Missing `ENVIRONMENT` silently enables development behavior

**Severity: Medium**

**Component:**
- `backend/app/core/config.py`
- `backend/app/core/encryption.py`
- `.env.example`
- `docker-compose.hardened.yml`

### Root cause

Phase 7 correctly changed environment classification so only explicit development labels are considered development-like:

```text
dev
development
local
test
```

Unknown nonempty values such as:

```text
live
release
prod-eu
foo
```

are now handled as production-like and receive strict secret validation.

However, the current settings model still defines:

```python
environment: str = "dev"
```

Therefore:

```text
ENVIRONMENT absent
```

does not fail.

It silently becomes:

```text
dev
```

This contradicts the intended security principle:

> Development behavior should be explicitly opted into.

### Security consequence

The explicit development path permits development conveniences, including weak/default secret behavior that is intentionally forbidden in production-like environments.

The message encryption layer also permits a deterministic development Fernet fallback when:

```text
MESSAGE_ENCRYPTION_KEY
```

is missing and the environment is development-like.

Therefore an operator who forgets to configure `ENVIRONMENT` can unintentionally start the application under development assumptions.

### Attack / failure scenario

This is primarily a deployment-misconfiguration security failure:

```text
operator deploys application
ENVIRONMENT accidentally omitted
JWT_SECRET remains development placeholder
MESSAGE_ENCRYPTION_KEY absent
    ↓
Settings silently select dev
    ↓
strict production-like validation is skipped
```

An external attacker cannot normally unset a server environment variable, so this is not a remote configuration injection issue.

However, it defeats the Phase 7 fail-safe configuration boundary and can result in real weak-secret deployment.

### Impact

Potential deployment with:

- weak/default JWT secret;
- deterministic development encryption fallback;
- other development assumptions.

Because exploitation requires an operator/deployment mistake rather than a direct remote request, **Medium** is appropriate.

### Required repair

`environment` should be explicitly required.

Conceptually:

```python
environment: str
```

with no `"dev"` model default.

Expected behavior:

```text
ENVIRONMENT=dev
    -> explicit development behavior

ENVIRONMENT=test
    -> explicit test behavior

ENVIRONMENT=production
    -> strict validation

ENVIRONMENT=live
    -> strict production-like validation

ENVIRONMENT absent
    -> configuration/startup failure

ENVIRONMENT=""
    -> configuration/startup failure
```

Local development remains straightforward because `.env.example` already explicitly contains:

```text
ENVIRONMENT=dev
```

Tests should explicitly select `ENVIRONMENT=test` where appropriate rather than depending on an implicit development default.

### Required regression cases

1. missing `ENVIRONMENT` fails validation;
2. empty `ENVIRONMENT` fails;
3. explicit `dev`, `development`, `local`, and `test` continue to work;
4. unknown nonempty environments remain production-like;
5. secure production-like configuration succeeds;
6. absent environment cannot reach deterministic development encryption fallback.

---

# 5. Phase 7 Controls Reviewed Without a New Repair Finding

## 5.1 Request-body limiting

Reviewed:

```text
backend/app/core/request_body_limit.py
backend/app/main.py
backend/app/schemas/auth.py
backend/app/api/routes/auth.py
```

The Phase 7 design is materially sound:

- ordinary request bodies are counted while being received;
- the middleware does not globally call `request.body()`;
- declared oversized `Content-Length` can be rejected before downstream work;
- requests without a trustworthy declared length are still byte-counted while receiving;
- authentication fields have explicit maximum lengths;
- rate-limit identity keys hash attacker-controlled identity text;
- failed-login audit payloads use a short prefix plus SHA-256 rather than arbitrary full input.

### Upload exemption

The upload exemption recognizes the expected upload-content path shape.

It is somewhat syntactic rather than route-object-aware, but no separate application endpoint was identified that makes the exemption exploitable.

The real upload route continues to use its own streamed upload-size enforcement.

No new Medium-or-higher issue was identified here.

---

## 5.2 Attachment/message relational integrity

Reviewed:

```text
backend/alembic/versions/0021_phase7_attachment_integrity.py
backend/app/db/models.py
```

Migration `0021`:

1. normalizes historical `message_attachments.channel_id` from the authoritative `messages.channel_id`;
2. adds:

```text
UNIQUE(messages.id, messages.channel_id)
```

3. replaces the single message FK with a composite FK:

```text
(message_attachments.message_id, message_attachments.channel_id)
    ->
(messages.id, messages.channel_id)
```

The ORM model contains the matching `ForeignKeyConstraint`.

This converts the previous latent integrity assumption into a PostgreSQL-enforced invariant.

No source-visible bypass was identified.

---

## 5.3 Lock-order/deadlock repair

Reviewed:

```text
backend/docs/LOCK_ORDERING.md
backend/app/services/outbox_service.py
worker/worker_app/outbox_runner.py
backend/app/services/channel_service.py
```

Phase 7 documents a global lock-order policy with event-integrity advisory locking last.

The important previous worker inversion was materially changed.

The worker now performs:

```text
outbox / BrokerBindingState processing
    ↓
retry / dead-letter / projection state update
    ↓
COMMIT authoritative transaction
    ↓
only then persist diagnostic audit event
```

This means the worker no longer intentionally holds the projection lock while trying to acquire the event-chain advisory lock.

Application membership/topology paths inspected generally acquire the channel/projection state before event logging.

No new deterministic source-visible lock-order cycle was identified during this review.

### Runtime limitation

The reviewer did not independently run real PostgreSQL two-session deadlock experiments, so this should be considered **source-verified but not independently concurrency-reproduced**.

---

# 6. Phase 6 Regression Review

## 6.1 Email-targeted invite identity

Reviewed:

```text
backend/app/core/email_identity.py
backend/app/api/routes/users.py
backend/app/services/channel_service.py
backend/app/db/models.py
```

Existing-user email invitations are resolved to:

```text
invited_user_id
```

at invite issuance.

Acceptance treats that immutable user ID as authoritative.

Unresolved/pre-registration email invitations require:

```text
normalized current email == invited email
AND
email_verified_at IS NOT NULL
```

Changing a user's email clears `email_verified_at`.

The database also has normalized email uniqueness.

No source-visible recurrence of the previous invite-transfer vulnerability was identified.

### Product limitation

There is still no complete provider-backed email verification delivery/completion flow.

This currently fails closed for unresolved invites, so it is a product/deployment incompleteness rather than an active authorization vulnerability.

---

## 6.2 Protected download concurrency

Reviewed:

```text
backend/app/services/download_service.py
backend/app/api/routes/messages.py
backend/app/core/client_ip.py
deploy/nginx/nginx.conf
docker-compose.hardened.yml
```

Application admission is atomic across:

```text
per user
per resolved client IP
process-global
```

under one asyncio lock.

Failed admission changes no counters.

Lease release is idempotent.

`LeasedFileResponse` releases capacity in `finally`.

The protected-download route releases DB work before the potentially slow file transfer.

The hardened Nginx profile also adds connection/time/body/header controls.

No additional repair-priority bypass was identified in this layer.

---

# 7. Earlier Security Controls — Short Regression Review

The following earlier mechanisms were spot-checked for nearby regressions:

### Authentication/session binding

Access authorization remains tied to both:

```text
user_id
session_id
```

and checks active user/session state and token/session expiry.

Refresh rotation still locks the session row and treats a signed stale token for the same family as replay.

### Broker desired state

Broker binding state remains PostgreSQL-owned and generation based.

The worker re-checks the current durable desired state before applying topology work.

### Membership generation

Outbox events continue to carry `membership_generation`, allowing WebSocket delivery authorization to detect changed membership state.

### Upload streaming

Protected uploads still use `request.stream()` and a separate upload-size boundary.

### Download streaming

Protected downloads still use a leased `FileResponse` rather than `read_bytes()`.

No new Critical/High finding was identified from this regression pass.

---

# 8. Known Remaining Limitations Not Classified as New Core Findings

These remain relevant for later production work.

## 8.1 Browser credential posture

Browser access/refresh token storage and CSRF/HttpOnly migration remain production-hardening work.

## 8.2 Production TLS/security headers

TLS termination, HSTS/CSP and related browser headers remain outside the completed core application-hardening phases.

## 8.3 Infrastructure credentials and container privilege

Development/default PostgreSQL/RabbitMQ/Redis credentials, service-account separation, non-root/restricted containers and secret distribution remain AV-11 production-hardening concerns.

## 8.4 Encryption key management

Message encryption still uses a single application Fernet key.

Key rotation/KMS and attachment encryption are not solved by Phase 7.

## 8.5 Multi-process/distributed limits

Some emergency and connection/resource controls are process-local and require infrastructure/proxy layers for stronger distributed enforcement.

## 8.6 Presence reliability

The previously identified multi-socket presence issue should still be treated separately:

```text
socket A closes
socket B remains connected
user may be marked offline
```

This is a reliability/presence correctness issue unless shown to affect authorization.

---

# 9. Recommended Immediate Repair

Before starting the final production-hardening phase, repair only:

```text
R7-01
R7-02
```

Do not reopen the broader messaging/security architecture unless the repair work exposes a new dependency.

Recommended output report for the repair task:

```text
SECURITY_REPAIR_AFTER_PHASE7_REPORT.md
```

After those repairs:

1. run the focused regression tests;
2. run the full backend test suite;
3. run frontend typecheck;
4. validate normal and hardened Compose;
5. validate Nginx configuration if changed.

If those pass and no new Medium/High/Critical application finding is discovered during the repair, core application-security hardening can reasonably be considered complete for this university/portfolio MVP.

The next major work should then be a distinct **production-hardening phase**, not another broad application-security rewrite.

---

# 10. Final Conclusion

The project has progressed substantially from its initial security posture.

The current source shows meaningful defense-in-depth across:

- session-bound authentication;
- refresh replay protection;
- short-lived single-use WebSocket tickets;
- PostgreSQL-backed broker desired state;
- membership-generation-aware realtime delivery;
- bounded sync work;
- streamed immutable uploads;
- streamed protected downloads;
- message/reaction/seen abuse controls;
- invite lifecycle serialization;
- immutable existing-user invite identity;
- normalized attachment authorization;
- database-enforced attachment/channel integrity;
- explicit lock-order policy;
- raw request-body boundaries;
- fail-safe handling for unknown nonempty environment labels.

However, two Medium source-visible gaps remain:

```text
R7-01 — proxied WebSocket connection rate-limit identity
R7-02 — missing environment silently defaults to development
```

These should be repaired before the repository moves to the final production/deployment-hardening phase.

**Assessment:** hardened and defensible university/portfolio messaging MVP, with two targeted application-security repairs still recommended before closing core security work.
