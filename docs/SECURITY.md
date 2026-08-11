# Security

## Phase 12 Final Validation

The final disposable production run confirmed TLS redirect and security
headers, trusted-host rejection, minimal health exposure, exact-origin CORS,
default PostgreSQL/RabbitMQ/Redis credential rejection, non-root/read-only
containers, dropped capabilities, and denial of runtime-role `CREATE ROLE` and
`CREATE DATABASE`. Only Nginx publishes host ports.

The application scenario additionally confirmed real local SMTP capture and
pre-registration invite verification, owner/admin/member/outsider RBAC,
single-use WebSocket tickets, refresh replay-family revocation, logout
invalidation, encrypted v2 message/outbox envelopes, chunked encrypted upload
bytes with immutable finalization, protected download, distributed aggregate
presence across two backends, audit hash-chain integrity, and removed-member
denial. The signed Merkle checkpoint, inclusion proof, checkpoint chain,
tampered-copy rejection, and external anchor all verified.

These are defense-in-depth university-MVP controls, not a production security
certification. The restrained deployment limitations remain: server-side rather
than end-to-end encryption; environment-managed rather than KMS/HSM-held keys;
manual independent anchor retention; CSP still permits required inline script
and style behavior; single-host dependencies without HA; operator-managed
certificate/SMTP/DNS/backups/monitoring/incident response; and no load or
automated browser certification.

## Authentication
- API routes that expose user, channel, message, event, and upload data require JWT-based authentication.
- Passwords are hashed with a strong password hashing algorithm in the backend.
- Emails are trimmed and lowercased consistently at registration, profile update,
  invite issuance/acceptance, login lookup, and superadmin bootstrap. No
  provider-specific rewriting such as Gmail dot removal is performed.
- `users.email_verified_at` is explicit proof state for the exact current email.
  Registration and profile mutation never set it. Changing to a different
  normalized email clears it; updating only case/whitespace around the same
  canonical address preserves the existing proof.
- Access JWTs contain a stable `sid` and every protected request resolves the user and that `UserSession` together. Missing, malformed, nonexistent, revoked, idle-expired, or absolute-expired sessions are rejected.
- Refresh tokens are stored server-side as hashes, not plain text. Rotation adds a unique `jti`; reuse of a signed stale token revokes that session/family and logs `security.refresh_replay_detected`.
- Login identity and password inputs are capped at 255 and 256 characters; refresh/logout tokens are capped at 2 KiB. Auth limiter keys use a SHA-256 digest of the normalized identity, while failed-login events retain only a 32-character prefix plus its digest and never store supplied passwords or tokens.
- Ordinary body-bearing HTTP requests have a streaming 128 KiB ASGI boundary before schema parsing, including clients without `Content-Length`. Only the protected upload-content `PUT` is exempt and continues through its separate bounded streaming size/checksum path.
- Sessions have both a sliding idle deadline (`JWT_REFRESH_TTL_DAYS`, default 14 days) and a non-sliding absolute deadline (`SESSION_ABSOLUTE_TTL_DAYS`, default 30 days).
- The browser-specific endpoints (`/v1/auth/browser/login`, `/refresh`, `/logout`, and `/csrf`) reuse the same server-side `UserSession`, rotation, replay-family, idle, and absolute-lifetime semantics as the legacy JSON token API. Browser responses never expose a refresh token in JSON.
- Browser refresh JWTs are stored only in an HttpOnly cookie. Production-like environments use `__Host-messaging_refresh` with `Secure`, `SameSite=Strict`, `Path=/`, and no `Domain`; explicit development/test HTTP uses the non-Secure `messaging_refresh` name. Production refuses `AUTH_COOKIE_SECURE=false`.
- Browser access JWTs exist only in the in-memory Zustand store. The frontend no longer places access or refresh credentials in `localStorage`, `sessionStorage`, IndexedDB, persistent Zustand state, or JavaScript-readable authentication cookies. Page reload obtains a new memory token through browser refresh.
- Browser refresh/logout require an allowed exact Origin and a random double-submit CSRF value: the non-HttpOnly CSRF cookie must match `X-CSRF-Token` using constant-time comparison. CSRF rotates with successful refresh. SameSite is an additional layer, not the only CSRF defense.
- The legacy `/auth/login`, `/refresh`, and `/logout` JSON-token endpoints remain for scripts, tests, and non-browser clients.
- Authenticated clients obtain a cryptographically random ticket from `POST /auth/ws-ticket`. Redis stores only its hash plus user/session/expiry metadata; atomic `GETDEL` consumption makes the ticket single-use. The default TTL is 30 seconds.
- WebSocket URLs carry only that short-lived opaque ticket. Raw access JWT query parameters, authorization headers, and first-frame JWT authentication are not accepted.
- An authenticated socket closes when the access/session authentication lifetime captured by its ticket expires. Logout, session revocation, logout-all, replay detection, and account deactivation publish minimal Redis control events so every listening backend instance can close matching sockets without per-socket database polling.
- Realtime outbox events carry a channel membership generation. The WebSocket layer checks this generation before decryption and refreshes current PostgreSQL membership immediately when a newer generation arrives or a legacy event has no generation. Matching/older generations use a deliberately short cache (`WS_MEMBERSHIP_AUTH_CACHE_TTL_SECONDS`, default one second), so a missed ephemeral Redis removal notification cannot expose a newly published post-removal message.
- Active presence is represented by one random Redis lease per admitted WebSocket connection, not one boolean per user. Atomic Lua connect/heartbeat/disconnect operations update a per-user sorted set, global expiration index, and the worker-facing online-user set. A second tab/session does not emit another effective online transition, and closing one socket cannot emit offline while another lease remains.
- Quiet sockets refresh their lease on a dedicated bounded task. A bounded, duplicate-safe reaper processes only due global-index entries, so process crashes and missing disconnect handlers eventually transition the final stale connection offline without an unbounded key scan. Redis failure leaves presence stale/unknown rather than inferring false offline; presence never participates in authentication, membership, message reads, invitations, or any other authorization decision.
- Targeted `membership_update` events are forwarded to the authenticated user even when the affected channel is not yet in that socket's subscription set. This supports approval-required joins without exposing message payloads to unauthorized users.
- An empty WebSocket subscription set receives no ordinary channel events. A membership change bypasses that filter only when its `user_id` targets the authenticated user; removal/leave updates also clear the affected channel from the socket's local subscription set.
- Docker starts Uvicorn with `--ws-max-size` from `WS_MAX_INBOUND_MESSAGE_BYTES` (default 16 KiB). The inbound loop applies the same UTF-8 byte limit before JSON parsing, returns `MESSAGE_TOO_LARGE`, and closes that socket with code 1009. Alternate ASGI launch paths still receive the application check, but should configure an equivalent server-side raw-frame bound.
- Each admitted socket has independent weighted command and history-row token buckets. Ping/auth/sync cost 1, seen/unsubscribe cost 3, and subscribe/resume cost 10. Subscribe and resume also reserve their maximum rows before database work. The default per-command total is 100 rows, the history bucket holds 300 rows and refills at 5 rows/second, and the command bucket holds 60 units and refills at 1 unit/second.
- The inbound loop awaits one command under an explicit per-socket lock, so a client cannot enqueue unbounded concurrent database/decryption/serialization work. Repeating the same authorized subscribe set with the same cursor returns an empty acknowledgement instead of refetching history. Budget state is removed on disconnect; another socket has independent state.

## Authorization
- Channel reads and writes check membership/role permissions.
- Channel list/detail payloads withhold decrypted last-message previews, seen markers, and unread counts unless the caller has an approved readable membership (`owner`, `admin`, or `member`). Public discovery can still expose basic channel metadata and last-activity time.
- Channel list search treats `%`, `_`, and `\` as literal text instead of SQL wildcards, and `#channel-slug` search is resolved against the safe stored slug.
- Private upload downloads require authentication and an authorization check before any file bytes are returned.
- Authorized encrypted upload bytes are served through bounded authenticated `LeasedEncryptedFileResponse` decryption after database authorization/audit work is complete; temporary migration-window plaintext uses the legacy `FileResponse`. One atomic lease checks and reserves `MAX_CONCURRENT_DOWNLOADS_PER_USER` (3), `MAX_CONCURRENT_DOWNLOADS_PER_IP` (12), and `MAX_CONCURRENT_DOWNLOADS_GLOBAL` (100) in each backend process. Failed admission changes no counter. Idempotent cleanup releases every dimension on completion, cancellation, file/stat/integrity failure, ASGI send failure, and response construction failure.
- The upload route allows content only to the owner. The download route always permits the upload owner; ordinary message-attachment access requires an active channel, a non-deleted message, and a current approved owner/admin/member membership. Soft-deleting a channel suspends channel-derived attachment access, and restoring it restores access only for current approved members. Pending, removed, outsider, and superadmin identities have no implicit channel-media bypass. Message attachment authorization uses the indexed `message_attachments(upload_id, channel_id, message_id)` relation rather than scanning message-history JSON; migration `0018_phase3_abuse_hardening` backfills historical attachment references, and migration `0021_phase7_attachment_integrity` normalizes historical channel IDs then enforces that every relation's `(message_id, channel_id)` matches the authoritative message row.
- Upload request bodies are streamed in bounded chunks to a same-directory temporary file while size and SHA-256 are checked incrementally. Failed, interrupted, oversized, short, or checksum-mismatched uploads are cleaned up and remain pending.
- Successful upload storage is immutable. The existing protected `public_url` is the persisted pending/stored lifecycle marker, the upload row is locked during finalization, and a second PUT returns `409 Conflict` without replacing historical bytes.
- Message media attachments use the same protected upload route. A message can reference uploaded photo, video, or audio content only after the uploader has stored the bytes; subscribers fetch/play that media through authenticated requests.
- Publish requests accept only attachment `file_id` references from clients. Filename, content type, size, and protected URL are derived from trusted upload records by the backend before the message is stored.
- Upload content types are normalized before storage. SVG image uploads are rejected because they are not needed for the multimedia demo and are riskier to render than ordinary photo/video/audio files.
- Profile avatar, profile wallpaper, and channel avatar uploads stay behind the same authenticated upload route. Development accepts external `http`/`https`, while production-like environments require HTTPS external media to prevent mixed content. Protected local upload paths remain valid; internal uploads must be owned by the updater, already stored, and be non-SVG images. Direct external HTTPS loads can still reveal the viewer's IP to that remote host.
- Avatar and wallpaper upload downloads have explicit access rules: profile avatars are visible to authenticated users, profile wallpapers are visible to the owning user, public channel avatars are visible to authenticated users, and private channel avatars are visible only to approved channel members or the upload owner.
- Unauthorized publish/read attempts are logged as security events.
- `/sync` membership backfill is limited to approved channels the caller can currently read, plus membership events whose `user_id`/`target_user_id` is the caller. This preserves a removed user's own removal notification without exposing unrelated channel membership activity.
- Pending membership rows do not grant private history, seen/unread state, sync/WS resume, or private-channel statistics; approved readers remain `owner`, `admin`, and `member`.
- Unauthorized upload download attempts are logged as `security.unauthorized_upload_access`.
- Upload creation, successful content storage, successful content access, and size/checksum store failures are logged as `upload.created`, `upload.content_stored`, `upload.accessed`, and `upload.store_failed`.
- Delivery monitoring endpoints under `/v1/admin/delivery/*` require authentication and are scoped to channels where the caller is an owner or an admin with management permissions.
- Manual delivery retry is authorized through the same scoped channel-manager rule.
- Targeted user/email invites are one-use. Generic links are reusable until revoked, expired, or their channel is deleted. Acceptance, revocation, and channel deletion lock the channel before the invite row; this supplies one PostgreSQL linearization order. If revocation wins, later membership creation is rejected; if targeted acceptance wins, the accepted state and membership commit together and later revocation reports that the invite was already accepted. Generic acceptances remain independently visible through `invite.accepted` or membership audit events rather than consuming one global `accepted_at` value.
- Email is not an immutable authorization identity. At invite issuance, an existing
  normalized email owner is resolved once into authoritative `invited_user_id`;
  the email remains only a display/audit snapshot. Later email reassignment
  cannot transfer that invite, and the originally targeted user may accept after
  changing email. If no account exists at issuance, acceptance requires both an
  exact normalized current email and non-null `email_verified_at`. Token possession
  plus an unverified profile value is denied with `EMAIL_VERIFICATION_REQUIRED`.
  Migration `0020_phase6_invite_identity` normalizes historical values and binds
  unambiguous existing-account invites without marking any historical email verified.
- The authenticated `/auth/email-verification/request` endpoint operates only on
  the current account's normalized email. It stores SHA-256 of a cryptographically
  random token in `email_verification_challenges`; the raw token is delivered only
  through the configured development capture/console or generic SMTP transport.
- Confirmation is authenticated and locks the user before the unique challenge.
  The challenge user, exact email snapshot, unconsumed/unrevoked state, and bounded
  expiry must all match before `email_verified_at` is set. Concurrent confirmation
  has one effective success. Profile email changes clear proof and revoke every
  outstanding challenge in the same transaction, so an old link cannot verify a
  replacement address.
- Verification links use an explicit public URL and a `#token=` fragment; the
  frontend removes the fragment from history, keeps the token only transiently,
  submits it to the authenticated API, and refreshes `/me`. Production verification
  requires an HTTPS public URL and generic SMTP with implicit TLS or STARTTLS.
  SMTP runs off the FastAPI event loop and uses Python's default certificate
  verification. Provider failures revoke the attempted challenge and expose only
  `EMAIL_DELIVERY_FAILED`, never provider credentials/details.
- Request and confirmation attempts use per-user/per-IP Redis rate limits with the
  existing bounded fail-safe local fallback. Audit events contain only user IDs and
  bounded reason codes, never raw tokens, token-bearing URLs, or SMTP secrets.

### Global superadmin
- `users.is_superadmin` is a separate platform privilege; it is not a channel membership role and cannot be requested through registration or profile APIs.
- `/v1/admin/*` requires the dedicated `SuperadminDep` authorization dependency. Denied attempts are logged as `security.superadmin_access_denied`.
- The frontend no longer persists an access token or role cookie for navigation. Client routing is convenience only; every admin API re-loads the user/session from the memory bearer token and database.
- Global console list/overview responses send `Cache-Control: no-store` and `Pragma: no-cache` so browsers and intermediary caches are instructed not to retain privileged data.
- Superadmin React Query entries use immediate garbage-collection after their final observer unmounts, limiting privileged data retention in the SPA's in-memory query cache.
- The initial account is created only when `SUPERADMIN_USERNAME` and `SUPERADMIN_PASSWORD` are explicitly configured. The password must contain at least 12 characters, and bootstrap refuses to promote an existing normal account with the same username/email.
- Superadmins can browse all audit events, view platform counts, deactivate/reactivate normal accounts, revoke their sessions, suspend/restore channels, and inspect/retry delivery failures across active channels.
- Account deactivation is enforced on login and access-token resolution; active sessions are revoked, local sockets close immediately, and a Redis control event notifies other backend instances.
- A superadmin cannot deactivate their own account through the API, and one superadmin cannot alter another superadmin through normal administration endpoints.
- Superadmin operations create `superadmin.*` or channel audit events.
- Destructive console actions require an explicit confirmation. This is a safety guard against accidental clicks; server-side `SuperadminDep` authorization remains the actual security boundary.
- `GET /v1/admin/events` returns only a per-event-family allowlisted, scalar `details` projection. It never returns the stored raw event payload, nested message/attachment structures, ciphertext, storage paths, or arbitrary unknown fields.
- New `message.published` audit rows store identifiers and operational metadata only. Message content remains in the encrypted message row and broker outbox, not duplicated into the audit payload.
- Console searches escape SQL wildcard characters and are filtered/paginated by the backend. Event search covers type, actor username, and channel name without searching raw event payloads.
- Superadmin status does **not** grant blanket read access to private message bodies or protected uploads. Platform administration and private channel content remain deliberately separate.

## Message Encryption
- New text/JSON content uses a strict v2 envelope with an explicit key ID. The active 32-byte master key is domain-separated with HKDF-SHA256 (`MessagingSystem/message/v2`) before Fernet is constructed.
- `DATA_ENCRYPTION_KEYS` contains at most 32 validated historical/current keys and `DATA_ENCRYPTION_ACTIVE_KEY_ID` selects new writes. Unknown IDs and tampered tokens fail closed; the runtime never silently tries every key.
- `MESSAGE_ENCRYPTION_KEY` is deprecated and used only to decrypt/migrate legacy-v1 bare Fernet rows. New writes never use it.
- Plaintext message compatibility is controlled by `ALLOW_LEGACY_PLAINTEXT_MESSAGES`. Production-like environments reject `true`; migration/test environments must opt in deliberately.
- The backend decrypts only after channel authorization. The worker/broker outbox carries encrypted payloads, and every supplied Compose worker receives only database/broker/fanout settings—not JWT, legacy-Fernet, or data-at-rest keys.
- Channel navigation remains available if an optional last-message preview cannot be decrypted: the API logs a bounded warning and omits the preview. Direct message reads fail closed.

## Upload Encryption
- New finalized upload paths contain authenticated ciphertext only. AES-256-GCM frames use 64 KiB logical chunks and a file key derived with HKDF-SHA256 from the selected master key plus upload UUID (`MessagingSystem/upload/v1`).
- The strict v1 header authenticates magic, version, upload UUID, key ID, logical plaintext size, chunk size, and random eight-byte nonce prefix. Each frame authenticates the header digest, upload context, monotonic index, and plaintext length.
- Upload PUT preserves streaming, logical SHA-256/size validation, immutable first write, encrypted sibling temporary storage, fsync, and atomic create-only finalization. It never writes a complete plaintext temporary file.
- Download authorization and path containment happen before header authentication/decryption. `LeasedEncryptedFileResponse` streams bounded authenticated plaintext chunks and releases its user/IP/global lease on completion, cancellation, send failure, or integrity failure. Encrypted Range requests return 416.
- `uploads.storage_encryption_version` and `storage_key_id` record storage metadata. Version 0 is a pending/historical plaintext row; version 1 requires a key ID. `ALLOW_LEGACY_PLAINTEXT_UPLOADS` is an explicit migration-window flag and is forbidden in production-like environments.
- A valid encrypted self-identifying header can be read when database metadata still says version 0, making file-replaced/DB-not-committed migration crashes recoverable. Unknown/corrupt encrypted files never downgrade to plaintext.
- Migration replacement means active application storage no longer retains that plaintext file. It is not a secure-erasure guarantee for SSD remanence, filesystem snapshots, or backups; encrypted volumes and backup lifecycle controls remain operational requirements.

## Key Rotation Operations
- Inspect without exposing content or key material: `python -m app.db.crypto_tool status`.
- Convert legacy storage in bounded idempotent batches: `migrate-messages`, then `migrate-uploads` while only the required compatibility flags are deliberately enabled.
- Production application processes reject those flags. If historical plaintext exists, use a one-shot, non-listening maintenance process with the production database/upload volume and real key ring but an explicit `ENVIRONMENT=local`; enable only the needed flag, run migration/status, destroy that process, and restore production with both flags false. Never serve HTTP or run the worker from this maintenance environment.
- Add the new key, set it active, restart backend, and run `rotate-messages --to-key-id <active-id>` plus `rotate-uploads --to-key-id <active-id>`.
- Run status again. Remove the historical key only when it has zero references and unreadable/unknown/missing/invalid/metadata-mismatch counts are zero.
- The key ring is deployment-injected. No external KMS/HSM integration or automated rotation scheduler is claimed.

## Secret Handling
- Do not commit real `.env` files, database passwords, JWT secrets, or encryption keys.
- The repository keeps `.env.example` as documentation for required settings.
- A local `.env` file may be used for development, but it should remain untracked.
- In the current repository state, `git ls-files` does not show any tracked `.env` file.
- `ENVIRONMENT` is required and normalized; missing or empty values fail configuration instead of selecting a default. Only `dev`, `development`, `local`, and `test` opt into the warned deterministic development data key. Every other normalized label is production-like, so values such as `live`, `release`, `prod-eu`, or a typo refuse startup when JWT or data-key-ring requirements are not satisfied.
- `.env.production.example` contains placeholders only. Production Compose requires explicit PostgreSQL admin/runtime, RabbitMQ, Redis, JWT, data-encryption key ring, public-host, and TLS-path values through `${VARIABLE:?required}` interpolation. The legacy Fernet key is optional after migration. `.env.production`, `secrets/`, `*.key`, and `*.pem` remain ignored.
- Production PostgreSQL uses a one-shot admin/migration credential and a separate application role shared by backend/worker. The role is forced `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION` and receives maintainable schema/table/sequence runtime grants. Stronger backend/worker role separation remains future work.
- Production RabbitMQ has an explicit non-default user and no published management/AMQP port. Redis requires a password and has no published port. Internal AMQP/Redis transport remains plaintext inside the host-local private Docker network; no claim of internal TLS is made.

## Production boundary

- `docker-compose.yml` is development-only. `docker-compose.hardened.yml` is an HTTP hardened local/demo path. `docker-compose.production.yml` is the TLS production-oriented single-host path.
- Production backend startup is Uvicorn-only. A one-shot `migrate` service runs Alembic/schema repair and grants runtime permissions before backend/worker start. Superadmin creation is an explicit `bootstrap` profile and is not attempted by normal production startup.
- Backend, worker, and frontend run as UID 10001. The unprivileged Nginx proxy runs as UID 101. These containers use read-only root filesystems, `no-new-privileges`, all capabilities dropped, and narrow uploads/cache/tmpfs write locations.
- Only Nginx publishes host ports 80/443. Stateful services and application ports stay on the internal Docker network. Nginx redirects HTTP to HTTPS, accepts externally mounted certificate/key files, supports WebSocket upgrades, applies connection/body/header/time limits, and rejects unknown hosts.
- HTTPS responses set HSTS, `nosniff`, strict referrer policy, a restrictive permissions policy, `X-Frame-Options: DENY`, and CSP with `frame-ancestors 'none'`, `object-src 'none'`, and `base-uri 'self'`. Next.js currently requires `'unsafe-inline'` for framework bootstrap scripts and inline styles in this deployment; `unsafe-eval` is not enabled. Nonce integration is future tightening.
- `/health` is public minimal liveness only. `/ready` contains dependency booleans for internal orchestration and is blocked by the production proxy. Production application docs default off and Nginx also blocks their public paths.
- Production credentialed CORS rejects `*` and non-HTTPS origins; an empty list remains a safe same-origin policy. `TrustedHostMiddleware` and Nginx `server_name` enforce configured hosts.

## Database lock ordering

- Security-sensitive transactions follow `User/UserSession -> Channel -> Membership/Invite/Message/UserChannelState/Upload -> existing Outbox -> BrokerBindingState -> event-integrity advisory lock`; details and exceptions are in [`backend/docs/LOCK_ORDERING.md`](LOCK_ORDERING.md).
- Channel and membership mutations acquire the channel before dependent row locks, use stable UUID order for multi-row topology work, and take the event-chain advisory lock last.
- Worker RabbitMQ failures commit authoritative projection/outbox status before a separate best-effort diagnostic event. Failure to store that diagnostic cannot undo retry/dead-letter state.
- Only idempotent post-commit worker diagnostics retry `40P01`/`40001`, at most three times. HTTP writes are not replayed automatically.
- Treat `SUPERADMIN_PASSWORD` as a bootstrap secret. Keep it only in the local/untracked environment and remove or rotate it after initial creation when practical.

## Routing-Key and Path Safety
- RabbitMQ routing keys and Redis channels are normalized before use.
- Safe usernames and channel slugs are restricted to `^[A-Za-z0-9_-]{3,50}$`.
- Upload storage paths are derived from sanitized filename components and validated to stay inside the uploads directory.
- Avatar and wallpaper URL fields reject unsafe schemes such as `javascript:`, `data:`, `file:`, and protocol-relative URLs before storage.
- Raw user input is not used directly in broker routing keys, Redis pub/sub channels, or filesystem paths.

## Delivery Error Handling
- Worker delivery errors are sanitized before being stored in `outbox.last_error` or exposed through the Delivery Monitor.
- Sanitization masks common token, password, secret, key, and AMQP credential patterns.
- Error text is still operational data, so it should not be used to intentionally log secrets or full connection strings.

## Abuse Resistance and Resource Bounds
- Rate limits are grouped into auth, search, message-write, media, channel-management, WebSocket, sync, and administration policies. Defaults are configurable with `RATE_LIMIT_*` environment variables.
- Login, registration, refresh, WebSocket ticket/connection attempts, search, message mutations, upload create/PUT/GET, channel/member/invite mutations, sync, and superadmin mutations are covered by the relevant group.
- HTTP and WebSocket abuse controls share one conservative client-IP resolver. Direct or untrusted peers use the immediate peer address and cannot spoof `X-Forwarded-For`; a peer inside `TRUSTED_PROXY_CIDRS` may supply exactly one valid, bounded forwarded IP. Missing, malformed, oversized, or comma-separated forwarding values fall back to the proxy peer. This keeps `rl:websocket:connect:<client-ip>` buckets isolated for clients behind the repository Nginx proxy.
- Redis is the normal distributed rate-limit store. One Lua evaluation atomically increments a fixed-window counter, installs the TTL on the first hit, repairs a legacy no-TTL key, and returns the count/TTL without extending the window on later hits.
- If Redis fails, sensitive operations use a capped in-process fixed-window fallback instead of becoming unlimited. Active state is never evicted to admit attacker-controlled churn. Expired windows are reclaimed through a bounded expiry heap; at `RATE_LIMIT_LOCAL_MAX_KEYS` saturation (default 10,000), unseen sensitive keys are denied until capacity expires. Ordinary `failure_policy=allow` reads remain available and do not consume this fallback.
- The emergency fallback is deliberately per-process: it prevents unlimited traffic to one instance but is weaker than healthy Redis across several backend replicas. A Redis response-loss/uncertain-execution error can conservatively consume both a Redis hit and a local allowance; recovery resumes the distributed Redis counters on the next successful request.
- Message text defaults to 65,536 UTF-8 bytes. Structured JSON defaults to 65,536 serialized UTF-8 bytes and nesting depth 20. Validation happens at the request-schema boundary before Fernet encryption, PostgreSQL writes, outbox creation, RabbitMQ, Redis, or WebSocket amplification.
- REST `/sync` channel cursors and WebSocket subscribe, unsubscribe, resume, and sync-state arrays accept at most 100 entries. Oversized WebSocket commands return a protocol validation error without querying membership state or crashing the connection manager.
- REST `/sync` applies one global message budget. Each selected channel query uses the remaining budget as its SQL `LIMIT`; at most 100 message queries and at most the requested number of message rows (maximum 500) are materialized in deterministic channel/sequence order.
- Seen state is monotonic and idempotent. Equal or lower sequence markers do not update timestamps/unread counts or emit another outbox event; only initial state and forward progress are persisted/broadcast.
- Reaction values must be short supported Unicode emoji, and each message defaults to at most 20 distinct emoji values. Duplicate add and nonexistent remove operations return the current summary without another outbox event. Message-list reaction counts and caller reactions are loaded in two batch queries rather than per message.
- Default account quotas limit active owned channels (50), active invites (100), daily upload records (100), pending uploads (10), reserved upload bytes (1 GiB), and concurrent WebSockets per backend instance (5). Boundaries return `RESOURCE_QUOTA_EXCEEDED` or `WEBSOCKET_QUOTA_EXCEEDED`.
- Protected-download request rate and active-resource admission are independent.
  Media rate limiting remains enabled, while active user/IP/global stream counts
  are reserved together under one process lock. Only active keys are retained,
  so limiter dictionary cardinality is bounded by the process-global stream cap.
- Client-IP resolution ignores arbitrary forwarding headers in direct mode. A
  forwarded address is accepted only when the immediate peer is inside an
  explicit `TRUSTED_PROXY_CIDRS` range and the header contains one valid address.
  The repository Nginx path overwrites that header and uses a fixed trusted `/32`.
- `docker-compose.hardened.yml` publishes only Nginx. Its configuration limits
  body/header sizes and active per-IP/server connections, buffers ordinary
  upstream responses, and applies header/body/upstream/write-inactivity timeouts.
  `send_timeout` is an inactivity bound, not a minimum-bandwidth guarantee.

## Broker and Redis Outage Semantics
- Membership/topology transactions update a monotonically versioned `broker_binding_states` row and enqueue a `broker_binding.reconcile` snapshot. The worker locks that row, rejects old generations, checks current membership and channel deletion state, removes obsolete routing keys, and applies the current projection idempotently. Duplicate execution and a crash after Rabbit success but before PostgreSQL acknowledgement are safe. Slug update and superadmin restore use the same path.
- Reconnect re-enqueues all known desired and undesired states for that user. Operators can run `python -m app.db.reconcile_broker_bindings` to enqueue the complete PostgreSQL-derived projection, including stale undesired bindings known from historical outbox rows.
- Per-user RabbitMQ queues remain durable while present but are bounded by default to seven-day unused-queue expiry, 24-hour message TTL, and 10,000 messages with `drop-head` overflow. PostgreSQL message history plus REST sync is the durable recovery path; RabbitMQ is not the only message copy.
- Redis fanout uses three bounded attempts with exponential delay by default. After exhaustion, the worker sleeps before RabbitMQ NACK/requeue, preventing a tight Redis-outage redelivery loop. It does not acknowledge/drop the event merely to hide the failure.

## Event Integrity / Tamper-Evident Audit Log
- Event Integrity Upgrade v1 stores a SHA-256 hash chain on event rows.
- Channel events are chained per `channel:<channel_id>` scope; non-channel events are chained under the `system` scope.
- New events receive `previous_hash`, `event_hash`, `hash_algorithm`, `integrity_version`, and `integrity_scope`.
- The hash protects stable audit fields: event id, channel id, actor id, event type, created timestamp, payload, previous hash, integrity version, and scope.
- Channel owners/admins with event-log access can call `GET /v1/channels/{id}/events/integrity` or use the Event Log UI to verify the chain.
- Legacy events created before the upgrade may show Not initialized until `scripts/backfill_event_integrity.py` is run. The canonical demo-safe dry-run is `docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"`.

This protects against accidental or unauthorized event modification, insertion,
reordering, or deletion that breaks links between remaining events being
silently missed by the application verifier. Phase 11 retains this layer and
adds a global sequence of bounded Merkle checkpoints:

- Leaves use `SHA256(0x00 || raw_32_byte_event_hash)`; internal nodes use
  `SHA256(0x01 || raw_left || raw_right)`. An odd final node is promoted
  unchanged.
- Checkpoint leaf rows snapshot both the source `event_hash` and derived leaf
  hash. Database verification recomputes the current event hash before comparing
  the snapshot, rebuilding the root, and checking the checkpoint chain.
- Canonical checkpoint metadata is SHA-256 hashed and the raw 32-byte hash is
  signed with Ed25519. Verification selects exactly the checkpoint's trusted
  `signing_key_id`; an unknown ID fails.
- The backend/API receives only the bounded public-key ring. The separate
  `merkle-checkpoint` maintenance process receives the active private seed. The
  worker, frontend, and proxy receive neither signing private material nor an
  unnecessary public ring.
- Proof and anchor APIs are superadmin-only and return integrity metadata, not
  event payloads. Responses use `Cache-Control: no-store`.
- Signing-key rotation retains old public keys so historical checkpoints remain
  verifiable; old checkpoints are never rewritten.

The signed root resists a database-only attacker rewriting events, snapshots,
and roots without the private signing key. It does not make PostgreSQL immutable.
Deleting a valid signed tail can still present an older state. Periodically
exporting the latest signed anchor and actually retaining it outside the
database/server gives a verifier a trusted latest-state reference; the project
does not claim automatic external anchoring.

## Known Limitations
- This project is a production-oriented single-host university MVP, not an enterprise identity, HA, backup, or secret-management platform.
- Browser refresh credentials are HttpOnly and access tokens are memory-only, but no automated Playwright/browser suite currently exercises the complete UI cookie lifecycle. Focused backend tests and static frontend inspection cover the boundary. WebSocket transport continues to use short-lived one-time tickets rather than access JWT URLs.
- The project does not claim end-to-end encryption; it uses server-side encryption at rest.
- Key rotation is explicit operator work rather than automatic scheduling, and keys are environment-injected rather than KMS/HSM-backed.
- Event integrity is tamper-evident and signed checkpoints resist database-only
  rewriting without the signing key. A compromised backend can still create
  legitimate-looking audit events, a compromised signing key defeats future
  signatures, and a fully privileged operator controlling both database and
  key can forge new state. No blockchain, gossip/witness network, or external
  transparency service is implemented.
- Merkle integrity is not end-to-end encryption and does not hide hashes,
  identifiers, roots, proof paths, public keys, or signatures. Message/upload
  confidentiality remains the separate server-side at-rest encryption layer.
- The signing private key is deployment-managed; external KMS/HSM custody,
  automated rotation scheduling, multi-host checkpoint high availability, and
  separation-of-duties/operator monitoring remain operational work.
- External anchors detect deletion/rollback only when an operator stores and
  protects the exported file independently and later supplies it for checking.
- The verifier does not prove tail deletion unless the previous last hash was stored or witnessed outside the database.
- Successful upload access logging is best-effort so a temporary audit-log failure does not break protected media playback; unauthorized access logging still blocks the request with `403 Forbidden`.
- Protected upload-backed avatars, wallpapers, and message media are fetched by the frontend with the bearer token and rendered through temporary object URLs. This is suitable for the local demo, but it is not a production CDN/media pipeline.
- Upload attachments are encrypted at rest with the Phase 9 chunked AES-GCM format but remain server-decryptable after authorization; this is not E2EE.
- Secrets are injected through required environment values rather than a managed secret store. External KMS integration and automatic credential/key rotation remain future work.
- PostgreSQL/RabbitMQ/Redis are single instances with named volumes. Production operators still need backup/restore procedures, monitoring, upgrades, capacity tuning, and HA appropriate to their environment.
- Superadmin activity is application-audited but does not replace external administrator monitoring, MFA, a hardware-backed secret store, or separation-of-duties controls.
- Cross-instance socket termination is best-effort realtime control. If Redis is unavailable during revocation, the database revocation still commits and blocks subsequent HTTP authentication, refresh, ticket validation, and reconnects, but a socket on another instance may remain until its captured authentication expiry.
- Emergency rate limiting and concurrent WebSocket quotas are per backend process when Redis/distributed coordination is unavailable; they are high-value MVP controls, not a billing-grade global quota service.
- Established-socket command/history budgets are also per socket and per backend process. The five-socket default and ticket/connection limits bound multiplication and reconnect resets, but the implementation does not claim one globally shared WebSocket budget across replicas.
- Protected-download user/IP/global counters are per backend process, not shared
  across replicas. The repository proxy bounds each proxy instance, but a
  multi-replica deployment still needs coordinated ingress limits and operator
  file-descriptor/socket limits.
- No live many-account slow-reader load test was run. The application-level
  admission and cleanup invariants are deterministic tests; Nginx syntax was
  validated, but slow-client behavior was configuration-reviewed rather than
  exercised under TCP load. Stock Nginx does not enforce a guaranteed minimum
  downstream throughput in this configuration.
- Email verification depends on operator-configured SMTP availability and mailbox
  delivery; there is no provider-specific bounce/complaint webhook or account
  recovery workflow. Tests use capture transport and a disposable local SMTP sink,
  never an external mailbox provider.
- A matching/older queued realtime event can use a cached authorization decision for at most one second by default. Newly committed post-membership-change events carry the newer generation and force immediate PostgreSQL revalidation before decryption.
- Broker ordering and Redis-loss scenarios are covered deterministically with fake Rabbit/Redis components, not a live multi-worker outage run.
- Existing RabbitMQ user queues created before Phase 3 have immutable declaration arguments. An upgraded environment must recreate those legacy queues (or reset the demo RabbitMQ volume) once so the new expiry/TTL/length arguments can be declared; PostgreSQL/REST sync protects message recovery, but operators should plan this transition rather than discovering a queue precondition error during the demo.
