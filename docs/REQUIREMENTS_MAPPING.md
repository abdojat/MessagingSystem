# Requirements Mapping

| Official requirement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Create channels/topics | Complete | `POST /v1/channels`, slug auto-generation/collision handling in backend service/tests | User A creates a channel in UI/API |
| Allow subscribers to publish and receive automatically | Complete | Membership join + message publish + realtime pipeline (RabbitMQ/Redis/WebSocket + REST retrieval) | User B joins, User A publishes, User B receives |
| Interfaces for managing channels and subscribers | Complete | Frontend channel list/details, create dialog, membership actions, channel settings | Show channel details and membership actions |
| Security: encryption, authentication, permissions | Complete | JWT auth, role/permission checks, Fernet encryption at rest, unauthorized security events | Login required routes, denied unauthorized actions, DB ciphertext query |
| Event log for tracking activity | Complete | `events` API (`GET /v1/channels/{id}/events`) + frontend event log panel | Open channel details Event Log panel |
