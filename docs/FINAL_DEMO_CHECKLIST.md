# Final Demo Checklist

## What To Open
- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8000/health`
- RabbitMQ management UI, if exposed by Compose: `http://localhost:15672`

## Users To Create
- User A: channel owner and publisher.
- User B: subscriber who joins and receives the live message.
- User C: outsider who will be blocked from a private upload.

## Demo Flow
1. Start the stack with `docker compose up -d --build`.
2. Open the frontend in two browser sessions, or one normal window plus one incognito window.
3. Register and log in User A.
4. Register and log in User B.
5. Register and log in User C in the second window or a third window.
6. User A creates a channel.
7. User B joins that channel.
8. Open the channel page for User B and keep the WebSocket-connected view visible.
9. User A publishes a text message.
10. User A publishes a small photo, video, or audio file from the paperclip composer control.
11. Show that User B receives the text and media messages live through the WebSocket-backed UI. If the live socket is unavailable in the environment, show the REST sync/backfill result instead.
12. Open the event log and show `channel.created`, `membership.joined`, and `message.published`.
13. Click Verify integrity and show the Audit integrity badge/check.
14. Open Delivery Monitor from User A's Profile page and show delivery counters plus empty or retryable failure tables.
15. Create a private upload owned by User A, attach it to a message, and show that User C receives `403 Forbidden` when trying to download the file.
16. If RabbitMQ management is available, show the exchange/queue activity, worker logs, or the `q.dead.messages` queue as extra proof of the broker path.

## Proof To Show
- The channel exists and persists.
- The subscriber receives the message.
- The subscriber can view/play protected photo, video, or audio attachments.
- The event log records the activity.
- The event log integrity check reports Verified for initialized events.
- The Delivery Monitor shows outbox delivery status for managed channels.
- Unauthorized access is blocked.
- The message remains stored encrypted at rest in PostgreSQL.

## Helpful Commands During The Demo
```bash
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
python scripts/verify_approval_flow.py --base-url http://localhost:8000/v1
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/verify_delivery_reliability.py --base-url http://localhost:8000/v1"
docker compose logs -f backend worker
docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"
docker compose exec postgres psql -U postgres -d channels -c "select status, count(*) from outbox group by status order by status;"
```

## What To Say Clearly
- This is a distributed publish/subscribe system, not just a chat app.
- PostgreSQL is the source of truth.
- RabbitMQ, the worker, Redis, and WebSockets are part of the delivery path.
- Delivery failures are tracked in PostgreSQL, retried by the worker, and dead-lettered after max attempts; the RabbitMQ DLQ is operational evidence, not the source of truth.
- The audit log hash chain is tamper-evident, not a blockchain or external notarization system.
- Upload downloads are protected by backend authorization checks.
- Browser token storage is demo-grade, not production-grade.
