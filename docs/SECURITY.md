# Security

## Authentication
- API routes that expose user, channel, message, event, and upload data require JWT-based authentication.
- Passwords are hashed with a strong password hashing algorithm in the backend.
- Refresh tokens are stored server-side as hashes, not plain text.
- The frontend keeps the access token in a JavaScript-managed cookie and the refresh token in `localStorage`, which is acceptable for this university demo but not production-grade session security.
- WebSocket connections use a short-lived access token in the connection URL for the demo flow and verifier.

## Authorization
- Channel reads and writes check membership/role permissions.
- Private upload downloads require authentication and an authorization check before any file bytes are returned.
- The upload route allows content only to the owner, and the download route only allows the owner or a user who is a member of a channel that references the upload.
- Unauthorized publish/read attempts are logged as security events.
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
- Raw user input is not used directly in broker routing keys, Redis pub/sub channels, or filesystem paths.

## Delivery Error Handling
- Worker delivery errors are sanitized before being stored in `outbox.last_error` or exposed through the Delivery Monitor.
- Sanitization masks common token, password, secret, key, and AMQP credential patterns.
- Error text is still operational data, so it should not be used to intentionally log secrets or full connection strings.

## Known Limitations
- This project is a university MVP, not a production-hardened identity or secret-management platform.
- The frontend token storage and WebSocket token transport are demo-oriented and should not be presented as production-grade session security.
- The project does not claim end-to-end encryption; it uses server-side encryption at rest.
