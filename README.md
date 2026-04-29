# Distributed Messaging System Based on Publish/Subscribe Model

University final-year project implementing a secure distributed channel messaging platform with FastAPI, PostgreSQL, RabbitMQ, Redis/WebSocket, worker processing, and Next.js frontend.

## Architecture Summary
- Backend API: FastAPI (`backend/`)
- Worker: outbox + broker fanout (`worker/`)
- Persistence: PostgreSQL
- Broker: RabbitMQ
- Realtime: Redis + WebSocket
- Frontend: Next.js (`frontend/`)

## Services
- `postgres` (5432)
- `rabbitmq` (5672, 15672)
- `redis` (6379)
- `backend` (8000)
- `worker`
- `frontend` (3000)

## Quick Start
```bash
cp .env.example .env
# set MESSAGE_ENCRYPTION_KEY in .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

docker compose up -d --build
docker compose ps -a
```

## Environment Variables
See `.env.example`.
Important:
- `DATABASE_URL`
- `RABBITMQ_URL`
- `REDIS_URL`
- `JWT_SECRET` (replace development default)
- `MESSAGE_ENCRYPTION_ENABLED=true`
- `MESSAGE_ENCRYPTION_KEY` (Fernet key)
- `NEXT_PUBLIC_API_BASE_URL`

Development note:
- In `dev/test/local`, empty `MESSAGE_ENCRYPTION_KEY` uses a fallback key.
- For demo/prod-like runs, set a real key explicitly.

## Migrations
```bash
docker compose run --rm backend sh -lc "alembic upgrade head"
```

## Tests
Docker backend tests (verified):
```bash
docker compose run --rm backend sh -lc "cd /app && PYTHONPATH=/app pytest -q"
```

Local backend tests:
```bash
cd backend
python -m pytest -q
```
If local PostgreSQL is unreachable for `DATABASE_URL`, tests may be skipped.

## Frontend Checks
Supported scripts:
```bash
cd frontend
npm install
npm run typecheck
npm run build
```
Notes:
- `npm run lint` is not defined in this repo.
- Local Windows build may hit a Node dependency issue (`caniuse-lite/...`).
- Docker frontend build is verified and recommended for demo readiness.

## Demo Verification Script
```bash
python scripts/verify_demo_flow.py --base-url http://localhost:8000/v1
```
The script verifies register/login, channel creation, join, publish, read, and event log entries.

## Manual Demo Flow
1. User A register/login.
2. User B register/login.
3. User A creates channel.
4. User B joins/subscribes.
5. User A publishes.
6. User B receives/reads.
7. Show event log panel in channel details.
8. Show unauthorized access denial on private channel.
9. Show ciphertext at rest:
```bash
docker compose exec postgres psql -U postgres -d channels -c "select id, content_text, content_json from messages order by created_at desc limit 5;"
```

## Security Notes
- Password hashing enabled.
- JWT auth on protected routes.
- Membership/permission authorization checks.
- Message encryption at rest (Fernet).
- Unauthorized read/publish events logged.
- Do not commit real secrets.

## Documentation
- [Project Overview](docs/PROJECT_OVERVIEW.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Demo Guide](docs/DEMO_GUIDE.md)
- [Requirements Mapping](docs/REQUIREMENTS_MAPPING.md)
- [Testing](docs/TESTING.md)
