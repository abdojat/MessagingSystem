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

## Routing-Key and Path Safety
- RabbitMQ routing keys and Redis channels are normalized before use.
- Safe usernames and channel slugs are restricted to `^[A-Za-z0-9_-]{3,50}$`.
- Upload storage paths are derived from sanitized filename components and validated to stay inside the uploads directory.

## Known Limitations
- This project is a university MVP, not a production-hardended identity or secret-management platform.
- Browser-side token handling is acceptable for the demo flow, but it is not presented as production-grade session security.
