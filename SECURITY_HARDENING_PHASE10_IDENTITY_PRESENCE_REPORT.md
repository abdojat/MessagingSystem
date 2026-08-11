# Security Hardening Phase 10 — Identity and Presence Report

## 1. Scope

Phase 10 implemented the two requested application fixes only: authenticated
mailbox verification and correct aggregate WebSocket presence across multiple
connections and backend processes. It preserved the established session, CSRF,
WebSocket-ticket, encryption, broker-generation, membership, sync, invitation,
and deployment architectures.

## 2. Findings addressed

| Finding | Finding status | Remediation | Result |
| --- | --- | --- | --- |
| P10-01 — provider-backed email verification is missing | CONFIRMED | Fixed in Phase 10 | A complete authenticated challenge lifecycle, generic SMTP transport, frontend flow, and unresolved-invite integration now exist. |
| P10-02 — presence can become incorrect when one of multiple WebSocket connections disconnects | CONFIRMED | Fixed in Phase 10 | Distributed per-connection Redis leases now determine aggregate online/offline transitions atomically. |

## 3. Email verification architecture

Migration `0023_phase10_email_verification` adds
`email_verification_challenges` with a UUID identity, cascading user reference,
normalized email snapshot, unique SHA-256 token hash, timestamps, and indexed
active/expiry lookup paths. A raw `secrets.token_urlsafe(32)` token exists only
during delivery; PostgreSQL, API responses, and audit metadata never contain it.

An authenticated request locks the user, returns `already_verified` when
appropriate, revokes older active challenges, performs bounded historical
cleanup, and creates one 30-minute challenge by default. Confirmation locks the
user and challenge and requires the same authenticated user, exact current
normalized email, unused/unrevoked status, and unexpired lifetime. It consumes
the challenge and sets `email_verified_at` in one transaction. Concurrent use
therefore has one effective success. Changing the normalized profile email
clears verification and revokes all outstanding challenges in that transaction.

## 4. Email delivery

Business logic depends on a small `VerificationMailer` abstraction. Tests use
an in-memory capture transport; explicit development mode may use a console
transport. Production verification rejects capture/console modes and requires
generic SMTP, an explicit HTTPS public verification URL, and either implicit
TLS or STARTTLS. Implicit TLS and STARTTLS use Python's default certificate
verification; incompatible modes and incomplete credentials fail settings
validation. Blocking `smtplib` work runs through `asyncio.to_thread`.

SMTP credentials are secret settings, use placeholders in the production
example, and are passed only to the backend container. The URL is derived only
from configured public origin data and carries the token in the fragment. If
delivery fails after commit, the new challenge is revoked, the user receives a
controlled `EMAIL_DELIVERY_FAILED` response, and a bounded safe audit reason is
recorded without provider details or secrets. A later request can replace it.

## 5. Invite integration

Existing-account email invitations continue to resolve to an immutable
`invited_user_id` and do not gain a new verification requirement. Generic
invitations are also unchanged. An unresolved/pre-registration email invitation
still requires both an exact current normalized-email match and non-null
`email_verified_at`. It is denied before proof and succeeds after the genuine
request/capture/confirm lifecycle. When production verification is unavailable,
creation of a new unresolved email invitation fails with the controlled
`EMAIL_VERIFICATION_UNAVAILABLE` error instead of creating an unusable path.

## 6. Frontend verification flow

Profile now displays Verified, Unverified, or missing-email state and provides
request/resend actions with a local cooldown and controlled error feedback. The
localized `/verify-email` page reads the token from `location.hash`, copies it
only into transient component state, immediately removes the fragment with
`history.replaceState`, and submits it through the authenticated API. It never
uses localStorage, sessionStorage, IndexedDB, or persisted Zustand state. On
success it refreshes `/me` so the verified profile state updates immediately.

## 7. Presence architecture

Each admitted socket receives a random URL-safe `connection_id`. Redis stores
that connection in a per-user sorted set with lease-expiry score, plus a bounded
global expiration sorted set and the existing worker-facing online-user set.
The username mapping supports expiry-driven transition payloads without adding
a public enumeration endpoint.

Lua scripts atomically register, refresh, disconnect, prune expired entries,
update expiry/TTL metadata, and calculate aggregate transitions. A quiet socket
gets a dedicated refresh task; the default refresh is 20 seconds for a 60-second
lease, validated so refresh is shorter than the lease. A bounded periodic reaper
reads only due global-index entries and does not use `KEYS` or store heartbeat
history in PostgreSQL.

## 8. Multi-socket semantics

The implemented aggregate contract is:

```text
0 -> 1  emit online
1 -> N  remain online; no duplicate effective transition
N -> 1  remain online; do not emit offline
1 -> 0  emit offline
```

Disconnect removes only that socket's connection identity. This applies to
multiple tabs, multiple sessions, and WebSocket managers in separate backend
instances. Session-specific revocation leaves the user online when another
valid socket remains; closing the final connection produces one effective
offline transition.

## 9. Distributed/backend-crash behavior

All aggregate state is Redis-backed, not an in-process counter. A crashed
backend cannot run disconnect cleanup, but its lease expires. The global due
index lets any backend reaper atomically remove the stale connection and emit
offline only if no refreshed connection remains. Concurrent reapers are
idempotent, and heartbeat refresh wins safely against processing of an older
global-index deadline. Per-user presence keys expire after their leases become
irrelevant, so historical connection keys do not accumulate permanently.

## 10. Redis failure degradation

Presence is ephemeral UI/realtime metadata and is never used for authentication,
membership, message reads, invitation acceptance, WebSocket admission, or
session validation. Presence bookkeeping failures are contained and logged at
a bounded rate. A local disconnect does not manufacture a confident global
offline transition when Redis state is unavailable; state may remain stale or
unknown until Redis recovers. Existing realtime dependencies otherwise retain
their prior behavior.

## 11. Migration 0023

A fresh PostgreSQL 16 database upgraded through `0023`. A representative
`0022 -> 0023` upgrade preserved one verified user, one unverified user, an
unresolved email invitation, and an immutable existing-user invitation, and
created zero challenge rows. Existing valid `email_verified_at` values and Phase
6 invitation identity semantics were unchanged. The bounded maintenance entry
point is `python -m app.db.cleanup_email_verification`.

## 12. Tests added

`backend/tests/security/test_phase10_identity_presence.py` adds 25 focused tests
covering E1–E18 and P1–P16, with related invariants combined where appropriate.
Email tests cover hash-only storage, exact binding, one use, expiry/revocation,
cross-user denial, email change, supersession, real PostgreSQL concurrency,
delivery failure, production configuration, rate limits, safe audit/log output,
and denial-before/success-after unresolved invitation acceptance.

Presence tests execute the Lua contract against real disposable Redis 7. They
cover first/second sockets, local and cross-manager final disconnect, heartbeat,
crash expiry, stale/live mixtures, duplicate reapers, rapid reconnect, session
revocation/logout-all semantics, background-task cleanup, and Redis degradation.
The existing Phase 9 tamper regression was made deterministic by mutating a
meaningful middle token byte instead of a potentially equivalent trailing
base64 character.

## 13. Live/disposable experiments

- Disposable PostgreSQL 16 and Redis 7 backed focused and regression tests.
- Disposable Mailpit received one real application-generated SMTP message. It
  captured locally and did not contact an external mailbox provider. External
  provider authentication, public DNS, and TLS delivery were not live-tested.
- Fresh and representative upgrade paths passed as described above.
- An isolated hardened Compose project built and became healthy. Its complete
  demo verifier passed REST backfill, RabbitMQ/worker/Redis/WebSocket delivery,
  event logging/integrity, persistence, and outsider upload denial.
- A supplemental live scenario passed authorized exact upload download,
  database message-ciphertext and framed upload-ciphertext inspection, and
  logout-all invalidation of the old access token.
- The first live WebSocket attempt exposed Nginx `proxy_set_header` inheritance:
  the WebSocket location lost the server-level Host/forwarding headers when it
  added Upgrade headers. Development and production templates now repeat the
  trusted identity headers; containerized `nginx -t` and the rerun passed.

## 14. Full regression results

| Validation | Result |
| --- | --- |
| Phase 10 focused suite | `25 passed, 1 warning` |
| Requested Phase 2/5/6/8/9/post-Phase-7 group plus Phase 10 | `150 passed, 1 warning` |
| Complete backend suite | `312 passed, 1 warning` |
| Frontend typecheck | Passed |
| Frontend production build | Passed; existing middleware-filename deprecation notice only |
| English/Arabic catalogs | Valid JSON; 825 aligned keys |
| Development/hardened/production Compose render | Passed |
| Production SMTP secret placement | Backend only |
| Nginx syntax after WebSocket header fix | Passed |
| Hardened full demo verifier | Passed |
| `git diff --check` | Passed; line-ending conversion notices only |

The backend warning is the existing passlib/argon2 version-metadata
deprecation. No failing regression was hidden.

## 15. Files changed

- Backend identity/configuration: `backend/app/core/config.py`,
  `backend/app/db/models.py`, `backend/app/db/cleanup_email_verification.py`,
  `backend/app/schemas/auth.py`, `backend/app/services/email_delivery_service.py`,
  `backend/app/services/email_verification_service.py`,
  `backend/app/api/routes/auth.py`, `backend/app/api/routes/users.py`,
  `backend/app/services/channel_service.py`, and `backend/app/main.py`.
- Migration/tests: `backend/alembic/versions/0023_phase10_email_verification.py`,
  `backend/tests/conftest.py`,
  `backend/tests/security/test_phase10_identity_presence.py`, and the
  deterministic Phase 9 tamper fixture.
- Presence: `backend/app/realtime/presence.py` and
  `backend/app/realtime/ws_manager.py`.
- Frontend: profile/verification pages, route, API types, and aligned English
  and Arabic locale catalogs under `frontend/src`.
- Deployment: `.env.example`, `.env.production.example`,
  `docker-compose.production.yml`, and both Nginx development/production
  configurations.
- Documentation/status: `README.md`, the relevant `docs/` architecture,
  security, testing, demo, stabilization, final-status, and requirements files,
  `REPOSITORY_ASSESSMENT.md`, and this report.

## 16. Remaining limitations

- Server-side encryption is not end-to-end encryption; there is no external
  KMS/HSM custody.
- Production mailbox delivery depends on an operator-configured HTTPS public URL
  and available TLS SMTP provider. There is no bounce/complaint webhook, MFA, or
  account-recovery workflow.
- Presence may be temporarily stale/unknown during Redis failure and is not a
  durable last-seen history.
- The documented CSP inline-style exception and external HTTPS image
  viewer-IP/privacy boundary remain.
- PostgreSQL, Redis, and RabbitMQ are single-host services in supplied Compose;
  no HA or multi-region infrastructure is claimed.
- Encrypted deletion does not guarantee physical secure erasure from storage
  media or backups. Backup lifecycle, restore drills, monitoring, and alerting
  remain operator responsibilities.
- There is no full browser-automation, external SMTP-provider, broker-outage,
  slow-reader, or production load certification.

## 17. Final maturity assessment

P10-01 and P10-02 are implemented and confirmed by focused integration tests,
real PostgreSQL/Redis execution, schema-upgrade checks, frontend compilation,
local SMTP transport, Compose rendering, and a live hardened broker/WebSocket
demo. The result is a credible, defendable university MVP with materially
stronger identity proof and distributed presence correctness. Production use
still requires operator SMTP/TLS configuration, secret custody, monitoring,
backup practice, and infrastructure resilience appropriate to its deployment.
