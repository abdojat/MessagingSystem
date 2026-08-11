# Development

## Prerequisites

The canonical workflow requires:

- Git;
- Docker Engine/Desktop;
- Docker Compose v2 (`docker compose`, not legacy `docker-compose`).

For direct process execution, use the versions represented by the repository:

- Python 3.11 or newer (`pyproject.toml` declares `>=3.11`; Docker pins Python 3.11);
- Node.js 22 with npm (the frontend Dockerfile uses Node 22).

Docker is still required for the recommended PostgreSQL 16, RabbitMQ 3.13, and Redis 7 dependencies.

## Docker development quick start

From the repository root:

```bash
cp .env.example .env
docker compose config --quiet
docker compose up --build
```

PowerShell copy equivalent:

```powershell
Copy-Item .env.example .env
```

Development Compose publishes:

| Component | Address |
|---|---|
| Next.js UI | `http://localhost:3000` |
| FastAPI API | `http://localhost:8000/v1` |
| OpenAPI UI | `http://localhost:8000/docs` |
| RabbitMQ management | `http://localhost:15672` (`guest` / `guest`) |
| PostgreSQL | `localhost:5432` |
| RabbitMQ AMQP | `localhost:5672` |
| Redis | `localhost:6379` |

On every development backend start, Compose waits for PostgreSQL, RabbitMQ, and Redis health, runs:

```text
alembic upgrade head
python -m app.db.bootstrap_schema
python -m app.db.bootstrap_superadmin
uvicorn app.main:app ...
```

The bootstrap command is idempotent and does nothing unless valid `SUPERADMIN_*` values are present.

Useful commands:

```bash
docker compose ps -a
docker compose logs -f backend worker frontend
docker compose up --build --watch
docker compose down
```

`docker compose down` preserves named volumes. To reset the development database, RabbitMQ data, Redis container state, and uploads:

```bash
# Destructive for this Compose project's development volumes.
docker compose down -v
```

The equivalent Make targets are `make up`, `make up-watch`, `make down`, and destructive `make reset`.

## Development secrets and optional superadmin

The template values are intentionally local/demo oriented. The stack can start with them, but retained demo data should use unique values.

Generate a JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Generate a 32-byte data-encryption master key:

```bash
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Choose a broker-safe key ID such as `demo-key`, then set:

```dotenv
DATA_ENCRYPTION_ACTIVE_KEY_ID=demo-key
DATA_ENCRYPTION_KEYS={"demo-key":"<generated-base64-key>"}
```

For the first development superadmin, set an unused safe username, optional email, and unique 12+ character password before startup:

```dotenv
SUPERADMIN_USERNAME=demo_admin
SUPERADMIN_EMAIL=admin@example.test
SUPERADMIN_PASSWORD=<unique-password>
```

The bootstrap refuses to promote an existing normal user and does not reset an existing administrator password. Remove the password from `.env` after the account exists.

Do not place a real Merkle private signing seed in the development `.env`; that file is loaded by the normal backend. Use the isolated production-oriented integrity profile or an explicitly scoped one-shot environment described in [Deployment](DEPLOYMENT.md#merkle-checkpoint-operations).

## Run only infrastructure in Docker

This is useful when running the backend and worker directly:

```bash
docker compose up -d postgres rabbitmq redis
```

Host processes must use `localhost`, not Compose service DNS names:

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/channels
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
REDIS_URL=redis://localhost:6379/0
```

## Run the backend directly

From `backend/`, create an isolated environment and install the validated lock:

```bash
cd backend
python -m venv .venv
```

Activate it on Linux/macOS:

```bash
source .venv/bin/activate
```

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Windows cmd:

```cmd
.venv\Scripts\activate
```

Then:

```bash
python -m pip install -r requirements.lock
cp ../.env.example .env
# Edit DATABASE_URL/RABBITMQ_URL/REDIS_URL to use localhost.
# Set UPLOADS_BASE_DIR=./data/uploads for a host-local upload directory.
python -m alembic upgrade head
python -m app.db.bootstrap_schema
python -m app.db.bootstrap_superadmin
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-max-size 16384
```

The backend requires reachable PostgreSQL, RabbitMQ, and Redis. Its startup lifespan verifies broker topology and establishes Redis/AMQP clients; direct execution is not an in-memory mode.

## Run the worker directly

Use a separate terminal and environment:

```bash
cd worker
python -m venv .venv
# Activate using the same OS-specific command as above.
python -m pip install -r requirements.lock
python -m worker_app.main
```

Set `DATABASE_URL`, `RABBITMQ_URL`, and `REDIS_URL` in that terminal (or an untracked `worker/.env`) with localhost addresses. The worker needs all three services and expects the backend migration/bootstrap steps to have completed. It intentionally does not need JWT, message/upload encryption, or Merkle signing keys.

## Run the frontend directly

```bash
cd frontend
npm ci
```

Set the public API base at build/dev-server start. Linux/macOS:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/v1 npm run dev
```

PowerShell:

```powershell
$env:NEXT_PUBLIC_API_BASE_URL='http://localhost:8000/v1'
npm run dev
```

Alternatively place the value in an untracked `frontend/.env.local`. Open `http://localhost:3000`.

## Migrations and initialization

Development Compose applies migrations automatically. Manual commands are still useful for inspection:

```bash
docker compose exec backend python -m alembic heads
docker compose exec backend python -m alembic current
docker compose exec backend python -m alembic upgrade head
```

Expected single head: `0024_phase11_merkle_audit`.

Schema migration does not create historical Merkle checkpoints. Legacy event-chain backfill and Merkle checkpointing remain explicit operator actions; see [Deployment](DEPLOYMENT.md).

## Repository scripts

| Script | Classification | Purpose |
|---|---|---|
| `scripts/verify_demo_flow.py` | Demo/test | Main publish, live delivery, sync, audit, and outsider-access verifier. |
| `scripts/verify_approval_flow.py` | Demo/test | Approval-required join-after-WebSocket-connect scenario. |
| `scripts/verify_delivery_reliability.py` | Demo/test | Normal publish plus controlled dead-letter/manual retry evidence. |
| `scripts/verify_release.py` | Release/test | Safe disposable backend suite plus frontend, Compose, Alembic-head, locale, and Nginx checks. |
| `scripts/verify_release_candidate.py` | Release/integration | Data-creating full application scenario against an intended disposable stack. |
| `scripts/demo_merkle_integrity.py` | Demo/operator | Creates disposable audit events, checkpoints them, proves inclusion/signature/chain, and rejects a tampered proof copy. |
| `scripts/backfill_event_integrity.py` | Operator/migration | Dry-run or explicit initialization/rebuild of legacy event-chain metadata. |
| `scripts/ws_client.py` | Development | Minimal manual WebSocket client. |

None of these scripts replaces Alembic or normal service startup.
