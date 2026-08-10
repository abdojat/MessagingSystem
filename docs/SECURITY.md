# Security

## Authentication
- API routes that expose user, channel, message, event, and upload data require JWT-based authentication.
- Passwords are hashed with a strong password hashing algorithm in the backend.
- Access JWTs contain a stable `sid` and every protected request resolves the user and that `UserSession` together. Missing, malformed, nonexistent, revoked, idle-expired, or absolute-expired sessions are rejected.
- Refresh tokens are stored server-side as hashes, not plain text. Rotation adds a unique `jti`; reuse of a signed stale token revokes that session/family and logs `security.refresh_replay_detected`.
- Sessions have both a sliding idle deadline (`JWT_REFRESH_TTL_DAYS`, default 14 days) and a non-sliding absolute deadline (`SESSION_ABSOLUTE_TTL_DAYS`, default 30 days).
- The frontend keeps the access token in a JavaScript-managed cookie and the refresh token in `localStorage`, which is acceptable for this university demo but not production-grade session security.
- Authenticated clients obtain a cryptographically random ticket from `POST /auth/ws-ticket`. Redis stores only its hash plus user/session/expiry metadata; atomic `GETDEL` consumption makes the ticket single-use. The default TTL is 30 seconds.
- WebSocket URLs carry only that short-lived opaque ticket. Raw access JWT query parameters, authorization headers, and first-frame JWT authentication are not accepted.
- An authenticated socket closes when the access/session authentication lifetime captured by its ticket expires. Logout, session revocation, logout-all, replay detection, and account deactivation publish minimal Redis control events so every listening backend instance can close matching sockets without per-socket database polling.
- Realtime outbox events carry a channel membership generation. The WebSocket layer checks this generation before decryption and refreshes current PostgreSQL membership immediately when a newer generation arrives or a legacy event has no generation. Matching/older generations use a deliberately short cache (`WS_MEMBERSHIP_AUTH_CACHE_TTL_SECONDS`, default one second), so a missed ephemeral Redis removal notification cannot expose a newly published post-removal message.
- Targeted `membership_update` events are forwarded to the authenticated user even when the affected channel is not yet in that socket's subscription set. This supports approval-required joins without exposing message payloads to unauthorized users.
- An empty WebSocket subscription set receives no ordinary channel events. A membership change bypasses that filter only when its `user_id` targets the authenticated user; removal/leave updates also clear the affected channel from the socket's local subscription set.

## Authorization
- Channel reads and writes check membership/role permissions.
- Channel list/detail payloads withhold decrypted last-message previews, seen markers, and unread counts unless the caller has an approved readable membership (`owner`, `admin`, or `member`). Public discovery can still expose basic channel metadata and last-activity time.
- Channel list search treats `%`, `_`, and `\` as literal text instead of SQL wildcards, and `#channel-slug` search is resolved against the safe stored slug.
- Private upload downloads require authentication and an authorization check before any file bytes are returned.
- Authorized upload bytes are served with chunked `FileResponse` streaming after database authorization/audit work is complete. `MAX_CONCURRENT_DOWNLOADS_PER_USER` (default 3) bounds active protected downloads per user in each backend process, and the lease is released on completion, cancellation, or send failure.
- The upload route allows content only to the owner, and the download route only allows the owner or a user who is a member of a channel that references the upload. Message attachment authorization uses the indexed `message_attachments(upload_id, channel_id, message_id)` relation rather than scanning message-history JSON; migration `0018_phase3_abuse_hardening` backfills historical attachment references.
- Upload request bodies are streamed in bounded chunks to a same-directory temporary file while size and SHA-256 are checked incrementally. Failed, interrupted, oversized, short, or checksum-mismatched uploads are cleaned up and remain pending.
- Successful upload storage is immutable. The existing protected `public_url` is the persisted pending/stored lifecycle marker, the upload row is locked during finalization, and a second PUT returns `409 Conflict` without replacing historical bytes.
- Message media attachments use the same protected upload route. A message can reference uploaded photo, video, or audio content only after the uploader has stored the bytes; subscribers fetch/play that media through authenticated requests.
- Publish requests accept only attachment `file_id` references from clients. Filename, content type, size, and protected URL are derived from trusted upload records by the backend before the message is stored.
- Upload content types are normalized before storage. SVG image uploads are rejected because they are not needed for the multimedia demo and are riskier to render than ordinary photo/video/audio files.
- Profile avatar, profile wallpaper, and channel avatar uploads stay behind the same authenticated upload route. Stored image URLs are validated to allow only `http`, `https`, or protected upload-content paths; internal uploads must be owned by the updater, already stored, and be non-SVG images.
- Avatar and wallpaper upload downloads have explicit access rules: profile avatars are visible to authenticated users, profile wallpapers are visible to the owning user, public channel avatars are visible to authenticated users, and private channel avatars are visible only to approved channel members or the upload owner.
- Unauthorized publish/read attempts are logged as security events.
- `/sync` membership backfill is limited to approved channels the caller can currently read, plus membership events whose `user_id`/`target_user_id` is the caller. This preserves a removed user's own removal notification without exposing unrelated channel membership activity.
- Pending membership rows do not grant private history, seen/unread state, sync/WS resume, or private-channel statistics; approved readers remain `owner`, `admin`, and `member`.
- Unauthorized upload download attempts are logged as `security.unauthorized_upload_access`.
- Upload creation, successful content storage, successful content access, and size/checksum store failures are logged as `upload.created`, `upload.content_stored`, `upload.accessed`, and `upload.store_failed`.
- Delivery monitoring endpoints under `/v1/admin/delivery/*` require authentication and are scoped to channels where the caller is an owner or an admin with management permissions.
- Manual delivery retry is authorized through the same scoped channel-manager rule.

### Global superadmin
- `users.is_superadmin` is a separate platform privilege; it is not a channel membership role and cannot be requested through registration or profile APIs.
- `/v1/admin/*` requires the dedicated `SuperadminDep` authorization dependency. Denied attempts are logged as `security.superadmin_access_denied`.
- The frontend's `chat_user_role` cookie only redirects navigation for convenience and is not trusted for authorization; every admin API re-loads the user from the signed access token and database.
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
- Message content is encrypted at rest on the server side with Fernet.
- The backend decrypts content only for authorized readers.
- The encryption key must come from environment variables for demo and deployment runs.
- Channel navigation remains available if an old last-message preview cannot be decrypted after a key change: the API logs a warning and omits that optional preview instead of returning ciphertext or failing the complete channel list. Direct message reads still fail until the original key is restored or a deliberate key-rotation migration is performed.

## Secret Handling
- Do not commit real `.env` files, database passwords, JWT secrets, or encryption keys.
- The repository keeps `.env.example` as documentation for required settings.
- A local `.env` file may be used for development, but it should remain untracked.
- In the current repository state, `git ls-files` does not show any tracked `.env` file.
- In `production`, `prod`, and `staging`, configuration validation refuses startup when `JWT_SECRET` is absent, is a known development placeholder, is shorter than 32 characters, or is obviously low-diversity. When message encryption is enabled, a valid explicit Fernet `MESSAGE_ENCRYPTION_KEY` is also mandatory, so the deterministic development fallback cannot be used.
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
- Redis is the normal distributed rate-limit store. If Redis fails, sensitive operations use a capped in-process fixed-window fallback instead of becoming unlimited. The fallback is bounded to 10,000 keys per API process. Ordinary paginated reads are not rate-limited and remain available during a Redis outage.
- The emergency fallback is deliberately per-process: it prevents unlimited traffic to one instance but is weaker than healthy Redis across several backend replicas.
- Message text defaults to 65,536 UTF-8 bytes. Structured JSON defaults to 65,536 serialized UTF-8 bytes and nesting depth 20. Validation happens at the request-schema boundary before Fernet encryption, PostgreSQL writes, outbox creation, RabbitMQ, Redis, or WebSocket amplification.
- REST `/sync` channel cursors and WebSocket subscribe, unsubscribe, resume, and sync-state arrays accept at most 100 entries. Oversized WebSocket commands return a protocol validation error without querying membership state or crashing the connection manager.
- REST `/sync` applies one global message budget. Each selected channel query uses the remaining budget as its SQL `LIMIT`; at most 100 message queries and at most the requested number of message rows (maximum 500) are materialized in deterministic channel/sequence order.
- Seen state is monotonic and idempotent. Equal or lower sequence markers do not update timestamps/unread counts or emit another outbox event; only initial state and forward progress are persisted/broadcast.
- Reaction values must be short supported Unicode emoji, and each message defaults to at most 20 distinct emoji values. Duplicate add and nonexistent remove operations return the current summary without another outbox event. Message-list reaction counts and caller reactions are loaded in two batch queries rather than per message.
- Default account quotas limit active owned channels (50), active invites (100), daily upload records (100), pending uploads (10), reserved upload bytes (1 GiB), and concurrent WebSockets per backend instance (5). Boundaries return `RESOURCE_QUOTA_EXCEEDED` or `WEBSOCKET_QUOTA_EXCEEDED`.

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

This protects against accidental or unauthorized event modification, insertion, reordering, or deletion that breaks links between remaining events being silently missed by the application verifier. Tail truncation requires an external remembered last hash to prove. It does not replace database access control, backups, monitoring, or secret management. It is not a blockchain, not external notarization, and not a full Merkle-tree proof. A database administrator with full write access could recompute a forged chain unless event hashes are anchored outside the database.

## Known Limitations
- This project is a university MVP, not a production-hardened identity or secret-management platform.
- Browser token storage remains demo-oriented: JavaScript can read the access/refresh credentials, so the project does not claim an httpOnly-cookie/CSRF-hardened production session architecture. WebSocket transport itself uses short-lived one-time tickets rather than access JWT URLs.
- The project does not claim end-to-end encryption; it uses server-side encryption at rest.
- There is no automatic encryption-key rotation or historical-key ring. Replacing `MESSAGE_ENCRYPTION_KEY` makes existing encrypted message bodies unreadable; retain the original key or migrate ciphertext deliberately before rotating it.
- Event integrity is tamper-evident inside PostgreSQL, but it does not prove that the database itself was never rewritten by a fully privileged operator.
- The verifier does not prove tail deletion unless the previous last hash was stored or witnessed outside the database.
- Successful upload access logging is best-effort so a temporary audit-log failure does not break protected media playback; unauthorized access logging still blocks the request with `403 Forbidden`.
- Protected upload-backed avatars, wallpapers, and message media are fetched by the frontend with the bearer token and rendered through temporary object URLs. This is suitable for the local demo, but it is not a production CDN/media pipeline.
- Upload attachments are protected and immutable after storage, but their file bytes are not encrypted by the message-body Fernet layer; attachment encryption remains future work.
- Superadmin activity is application-audited but does not replace external administrator monitoring, MFA, a hardware-backed secret store, or separation-of-duties controls.
- Cross-instance socket termination is best-effort realtime control. If Redis is unavailable during revocation, the database revocation still commits and blocks subsequent HTTP authentication, refresh, ticket validation, and reconnects, but a socket on another instance may remain until its captured authentication expiry.
- Emergency rate limiting and concurrent WebSocket quotas are per backend process when Redis/distributed coordination is unavailable; they are high-value MVP controls, not a billing-grade global quota service.
- Protected-download concurrency is also per backend process. Reverse-proxy connection, bandwidth, timeout, and IP policies remain required for production.
- A matching/older queued realtime event can use a cached authorization decision for at most one second by default. Newly committed post-membership-change events carry the newer generation and force immediate PostgreSQL revalidation before decryption.
- Broker ordering and Redis-loss scenarios are covered deterministically with fake Rabbit/Redis components, not a live multi-worker outage run.
- Existing RabbitMQ user queues created before Phase 3 have immutable declaration arguments. An upgraded environment must recreate those legacy queues (or reset the demo RabbitMQ volume) once so the new expiry/TTL/length arguments can be declared; PostgreSQL/REST sync protects message recovery, but operators should plan this transition rather than discovering a queue precondition error during the demo.
