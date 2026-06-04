# Security

## Authentication
- API routes that expose user, channel, message, event, and upload data require JWT-based authentication.
- Passwords are hashed with a strong password hashing algorithm in the backend.
- Refresh tokens are stored server-side as hashes, not plain text.

## Authorization
- Channel reads and writes check membership/role permissions.
- Private upload downloads require authentication and an authorization check before any file bytes are returned.
- Unauthorized publish/read attempts are logged as security events.

## Message Encryption
- Message content is encrypted at rest on the server side with Fernet.
- The backend decrypts content only for authorized readers.
- The encryption key must come from environment variables for demo and deployment runs.

## Secret Handling
- Do not commit real `.env` files, database passwords, JWT secrets, or encryption keys.
- The repository keeps `.env.example` as documentation for required settings.
- A local `.env` file may be used for development, but it should remain untracked.
- In the current repository state, `.env` is present locally but is not tracked by git.

## Routing-Key and Path Safety
- RabbitMQ routing keys and Redis channels are normalized before use.
- Safe usernames and channel slugs are restricted to `^[A-Za-z0-9_-]{3,50}$`.
- Upload storage paths are derived from sanitized filename components and validated to stay inside the uploads directory.
- Raw user input is not used directly in broker routing keys, Redis pub/sub channels, or filesystem paths.

## Known Limitations
- This project is a university MVP, not a production-hardened identity or secret-management platform.
- The frontend stores the access token in a JavaScript-managed cookie and the refresh token in `localStorage`; that is acceptable for the demo flow, but it is not production-grade session security.
- The frontend also places the access token on WebSocket connection URLs for the demo verifier and client flow, so the system should not be presented as if it were using httpOnly Secure SameSite cookies.
