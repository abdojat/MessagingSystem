# Security

## Authentication
- API routes that expose user, channel, message, event, and upload data require JWT-based authentication.
- Passwords are hashed with a strong password hashing algorithm in the backend.
- Refresh tokens are stored server-side as hashes, not plain text.
- The frontend keeps the access token in a JavaScript-managed cookie and the refresh token in `localStorage`, which is acceptable for this university demo but not production-grade session security.
- WebSocket connections use a short-lived access token in the connection URL for the demo flow and verifier.
- WebSocket membership refresh is demo-grade but explicit: after a user joins or receives a membership update, the frontend sends a subscribe/resync message so the open socket follows the latest authorized channel set.
- Targeted `membership_update` events are forwarded to the authenticated user even when the affected channel is not yet in that socket's subscription set. This supports approval-required joins without exposing message payloads to unauthorized users.

## Authorization
- Channel reads and writes check membership/role permissions.
- Private upload downloads require authentication and an authorization check before any file bytes are returned.
- The upload route allows content only to the owner, and the download route only allows the owner or a user who is a member of a channel that references the upload.
- Message media attachments use the same protected upload route. A message can reference uploaded photo, video, or audio content only after the uploader has stored the bytes; subscribers fetch/play that media through authenticated requests.
- Profile and channel avatar uploads stay behind the same authenticated upload route. Stored avatar URLs are validated to allow only `http`, `https`, or protected upload-content paths; internal avatar uploads must be owned by the updater, already stored, and be non-SVG images.
- Avatar upload downloads have explicit access rules: profile avatars are visible to authenticated users, public channel avatars are visible to authenticated users, and private channel avatars are visible only to approved channel members or the upload owner.
- Unauthorized publish/read attempts are logged as security events.
- Unauthorized upload download attempts are logged as `security.unauthorized_upload_access`.
- Delivery monitoring endpoints under `/v1/admin/delivery/*` require authentication and are scoped to channels where the caller is an owner or an admin with management permissions.
- Manual delivery retry is authorized through the same scoped channel-manager rule.

## Message Encryption
- Message content is encrypted at rest on the server side with Fernet.
- The backend decrypts content only for authorized readers.
- The encryption key must come from environment variables for demo and deployment runs.

## Secret Handling
- Do not commit real `.env` files, database passwords, JWT secrets, or encryption keys.
- The repository keeps `.env.example` as documentation for required settings.
- A local `.env` file may be used for development, but it should remain untracked.
- In the current repository state, `git ls-files` does not show any tracked `.env` file.

## Routing-Key and Path Safety
- RabbitMQ routing keys and Redis channels are normalized before use.
- Safe usernames and channel slugs are restricted to `^[A-Za-z0-9_-]{3,50}$`.
- Upload storage paths are derived from sanitized filename components and validated to stay inside the uploads directory.
- Avatar URL fields reject unsafe schemes such as `javascript:`, `data:`, `file:`, and protocol-relative URLs before storage.
- Raw user input is not used directly in broker routing keys, Redis pub/sub channels, or filesystem paths.

## Delivery Error Handling
- Worker delivery errors are sanitized before being stored in `outbox.last_error` or exposed through the Delivery Monitor.
- Sanitization masks common token, password, secret, key, and AMQP credential patterns.
- Error text is still operational data, so it should not be used to intentionally log secrets or full connection strings.

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
- The frontend token storage and WebSocket token transport are demo-oriented and should not be presented as production-grade session security.
- The project does not claim end-to-end encryption; it uses server-side encryption at rest.
- Event integrity is tamper-evident inside PostgreSQL, but it does not prove that the database itself was never rewritten by a fully privileged operator.
- The verifier does not prove tail deletion unless the previous last hash was stored or witnessed outside the database.
