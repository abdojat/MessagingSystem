# Requirements Mapping

| Official requirement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Create channels/topics | Complete | `POST /v1/channels`, slug auto-generation/collision handling, safe identifier validation, and database constraints | User A creates a channel in UI/API |
| Allow subscribers to publish and receive automatically | Complete | Membership join + message publish + realtime pipeline (RabbitMQ/Redis/WebSocket + REST retrieval). Verified by `scripts/verify_demo_flow.py`, which checks live WebSocket delivery when available and REST backfill fallback | User B joins, User A publishes, User B receives |
| Interfaces for managing channels and subscribers | Complete | Frontend channel list/details, create dialog, membership actions, channel settings | Show channel details and membership actions |
| Security: encryption, authentication, permissions | Complete | JWT auth, role/permission checks, Fernet encryption at rest, protected upload downloads, safe routing identifiers, unauthorized security events | Login required routes, denied unauthorized actions, DB ciphertext query |
| Event log for tracking activity | Complete | `events` API (`GET /v1/channels/{id}/events`) + frontend event log panel | Open channel details Event Log panel |

## Advanced Reliability Enhancement

| Enhancement | Status | Implementation evidence | Demo step |
|---|---|---|---|
| Delivery Reliability Upgrade v1: outbox retry/dead-letter monitoring | Mostly complete | Outbox status fields and migration `0012_delivery_reliability`; worker retry/dead-letter logic in `worker/worker_app/outbox_runner.py`; RabbitMQ DLQ topology in `backend/app/mq/topology.py` and `worker/worker_app/mq/topology.py`; admin APIs under `/v1/admin/delivery/*`; frontend Delivery Monitor at `/app/delivery`; tests in `backend/tests/test_delivery_reliability.py` | Open Delivery Monitor as a channel owner/admin; inspect counters and retry failed/dead-lettered rows if present |

This enhancement strengthens the distributed-system reliability story, but it is not one of the official minimum requirements. PostgreSQL outbox state remains authoritative; the RabbitMQ DLQ is an operational mirror when the worker can publish to it.
