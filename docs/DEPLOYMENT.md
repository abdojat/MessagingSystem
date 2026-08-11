# Deployment and Operator Guide

## Profiles at a glance

| Profile | Purpose | Host exposure | Initialization |
|---|---|---|---|
| `docker-compose.yml` | Convenient development | PostgreSQL `5432`, RabbitMQ `5672/15672`, Redis `6379`, API `8000`, UI `3000` | Backend automatically migrates, reconciles schema, and optionally bootstraps superadmin. |
| `docker-compose.hardened.yml` | Proxy-bounded local/supervisor demo | Nginx HTTP `8080` only | Backend automatically migrates/reconciles and optionally bootstraps. |
| `docker-compose.production.yml` | Single-host production-oriented reference | Configured HTTP/HTTPS Nginx edge only | One-shot `migrate` service; explicit bootstrap and Merkle integrity profiles. |

The production-oriented profile is not production certification, multi-host HA, or a replacement for operator-managed DNS, trusted certificates, secret storage, backups, monitoring, and recovery procedures.

## Hardened local/demo profile

This profile uses the development `.env` and credentials but puts PostgreSQL, RabbitMQ, Redis, backend, worker, and frontend on a private network. Nginx publishes HTTP port `8080` and applies bounded request/header/body/connection/time behavior.

```bash
cp .env.example .env
docker compose -f docker-compose.hardened.yml config --quiet
docker compose -f docker-compose.hardened.yml up -d --build
docker compose -f docker-compose.hardened.yml ps -a
```

Open `http://localhost:8080`. RabbitMQ management and direct API/frontend ports are not published in this profile.

Stop while preserving volumes:

```bash
docker compose -f docker-compose.hardened.yml down
```

Reset its named volumes only when destruction is intended:

```bash
docker compose -f docker-compose.hardened.yml down -v
```

## Production-oriented profile

### 1. Prepare the environment

```bash
cp .env.production.example .env.production
```

PowerShell:

```powershell
Copy-Item .env.production.example .env.production
```

Replace every `replace_with_*` value, set the real public hostname, configure the public verification URL, and provide absolute operator-owned TLS certificate/key paths. Keep `.env.production`, certificates, and private keys outside version control.

### 2. Generate secrets

Generate independent URL-safe values for the PostgreSQL roles, RabbitMQ, Redis, and JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Generate each 32-byte data-encryption master key:

```bash
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Generate the Ed25519 Merkle signing pair from an installed backend environment:

```bash
cd backend
python -m app.db.merkle_tool generate-keypair --key-id audit-2026-01
```

Or use a built backend image without mounting the repository:

```bash
docker build -t messaging-backend-ops -f backend/Dockerfile .
docker run --rm messaging-backend-ops python -m app.db.merkle_tool generate-keypair --key-id audit-2026-01
```

The command intentionally prints the private seed. Run it only in a private operator terminal, never captured CI logs. Put the public key in `AUDIT_MERKLE_PUBLIC_KEYS`; inject the private seed only into the explicit checkpoint process.

### 3. Validate and start

```bash
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yml ps -a
```

The `migrate` service waits for PostgreSQL, applies Alembic/schema reconciliation, grants the restricted runtime role, and must exit `0`. Backend and worker wait for it. Normal backend startup runs Uvicorn only; it does not silently migrate or bootstrap an administrator.

Only the configured `${HTTP_PORT:-80}` and `${HTTPS_PORT:-443}` are published. HTTP redirects to HTTPS. State services and applications remain private.

### 4. Bootstrap the first superadmin explicitly

Temporarily set `SUPERADMIN_USERNAME`, optional `SUPERADMIN_EMAIL`, and a unique 12+ character `SUPERADMIN_PASSWORD` in the untracked production environment, then run:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml \
  --profile bootstrap run --rm bootstrap-superadmin
```

The operation is idempotent, refuses to promote an existing normal user, and does not reset a password. Remove `SUPERADMIN_PASSWORD` after provisioning.

### 5. Stop

```bash
docker compose --env-file .env.production -f docker-compose.production.yml down
```

Do not add `-v` unless destruction of the production-profile database, broker, Redis, and upload volumes is explicitly intended.

## Production environment groups

The authoritative variable template is [`.env.production.example`](../.env.production.example). These groups explain responsibility without duplicating every default.

| Area | Variables | Purpose |
|---|---|---|
| PostgreSQL | `POSTGRES_DB`, `POSTGRES_ADMIN_*`, `POSTGRES_APP_*` | Separate schema/migration administrator from restricted runtime login. |
| RabbitMQ | `RABBITMQ_USER`, `RABBITMQ_PASSWORD` | Authenticated broker account used by API/worker. |
| Redis | `REDIS_PASSWORD` | Authenticated fanout/presence/rate-limit service. |
| Authentication | `JWT_SECRET` | Access/refresh JWT signing; must be independent from other secrets. |
| Email | `EMAIL_VERIFICATION_*`, `EMAIL_DELIVERY_MODE`, `SMTP_*` | HTTPS verification URL and TLS/STARTTLS SMTP transport. |
| Data encryption | `DATA_ENCRYPTION_ACTIVE_KEY_ID`, `DATA_ENCRYPTION_KEYS`, optional legacy `MESSAGE_ENCRYPTION_KEY` | Current/historical server-side at-rest key ring and legacy migration compatibility. |
| Merkle integrity | `AUDIT_MERKLE_*` | Bounded checkpoint size, trusted public-key ring, and one-shot signing identity. |
| Public edge | `PUBLIC_HOST`, `HTTP_PORT`, `HTTPS_PORT`, `TLS_CERT_PATH`, `TLS_KEY_PATH` | Nginx hostname, port, and external certificate mounts. |
| Bootstrap | `SUPERADMIN_*` | Explicit one-shot first administrator only. |

Production Compose forces plaintext message/upload compatibility off and secure browser cookies on.

## Database migrations

From an installed backend environment:

```bash
cd backend
python -m alembic heads
python -m alembic current
python -m alembic upgrade head
```

Expected single head:

```text
0024_phase11_merkle_audit
```

Development Compose applies the upgrade automatically. The production one-shot path is:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml run --rm migrate
```

`0024_phase11_merkle_audit` creates checkpoint/leaf schema only. Schema migration does not synthesize historical Merkle checkpoints. If pre-integrity events need chain metadata, inspect first and run the explicit backfill only after review:

```bash
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"
docker compose exec backend sh -lc "cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py"
```

The second command changes event-integrity metadata and is not part of ordinary startup.

## Data crypto status, migration, and rotation

Run these from `backend/` (or replace the prefix with `docker compose exec backend python -B -m`):

```bash
python -m app.db.crypto_tool status
python -m app.db.crypto_tool migrate-messages
python -m app.db.crypto_tool migrate-uploads
python -m app.db.crypto_tool rotate-messages --to-key-id key-2026-08
python -m app.db.crypto_tool rotate-uploads --to-key-id key-2026-08
python -m app.db.crypto_tool status
```

All commands are bounded and restartable; `--batch-size` is supported. Rotation requires `--to-key-id` to match `DATA_ENCRYPTION_ACTIVE_KEY_ID`. Change the active ID first so new writes immediately use the target, rotate messages and uploads, confirm status, and remove an old key only after no data references it.

Plaintext migration is deliberately incompatible with a listening production server. If historical plaintext exists, run only the CLI in an isolated, non-listening maintenance process that mounts the same database/upload volume, supplies the real key ring, uses `ENVIRONMENT=local`, and enables only the required plaintext compatibility flag. Restore production configuration and both flags to `false` immediately afterward. Do not start Uvicorn or the worker with that maintenance environment.

## Merkle checkpoint operations

Normal audit writes update the event hash chain only. Events accumulate until a one-shot checkpoint command selects bounded batches:

```text
events accumulate -> operator/scheduled job -> bounded batch -> signed checkpoint
```

The production-isolated checkpoint command is:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml \
  --profile integrity run --rm merkle-checkpoint
```

Schedule that same one-shot command with cron, a systemd timer, or a deployment scheduler if periodic checkpoints are required. The application does not include an internal scheduler.

All supported CLI commands, run from an operator backend environment with the necessary database/public-key configuration, are:

```bash
python -m app.db.merkle_tool status
python -m app.db.merkle_tool checkpoint --all
python -m app.db.merkle_tool verify --verify-event-chains
python -m app.db.merkle_tool proof --event-id <uuid> --output event-proof.json
python -m app.db.merkle_tool verify-proof --proof event-proof.json
python -m app.db.merkle_tool export-anchor --output latest-audit-anchor.json
python -m app.db.merkle_tool verify-anchor --file latest-audit-anchor.json
python -m app.db.merkle_tool verify-anchor --file latest-audit-anchor.json --offline
python -m app.db.merkle_tool generate-keypair --key-id audit-2026-01
```

Checkpoint creation needs `AUDIT_MERKLE_SIGNING_KEY_ID`, `AUDIT_MERKLE_SIGNING_PRIVATE_KEY`, and a matching entry in `AUDIT_MERKLE_PUBLIC_KEYS`. Status/verify/proof operations need the public-key ring but not the private seed. Output files are not overwritten unless `--force` is supplied.

After exporting an anchor:

> Copy the anchor to storage independent from the application and database host.

Suitable examples include operator-controlled storage, a separate backup repository, or protected archival storage. Exporting the file without independent retention does not provide rollback evidence.

## Merkle supervisor demo

The isolated production integrity service can run the data-creating deterministic demo:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml \
  --profile integrity run --rm --entrypoint python merkle-checkpoint \
  -B scripts/demo_merkle_integrity.py
```

Expected labels: event hash PASS, Merkle inclusion PASS, checkpoint hash PASS, Ed25519 signature PASS, checkpoint chain PASS, and tampered proof FAILED (expected). The script modifies no existing evidence; it creates dedicated demo events and tampers only with an in-memory proof copy.
