# Distributed Publish/Subscribe Messaging System

A university final-year project that demonstrates persistent topic-based messaging with a FastAPI API, PostgreSQL, RabbitMQ, an asynchronous worker, Redis/WebSockets, and a Next.js management interface. The UI looks chat-like, but the academic focus is the distributed publish/subscribe path, durable recovery, access control, and verifiable audit evidence.

The implementation and security-hardening phases are complete for the defined university MVP. This repository separates [current documentation](docs/README.md) from [historical implementation and verification reports](reports/security/README.md).

## Architecture

```text
                         Client
                            |
                       HTTPS / WSS
                            |
                            v
                          Nginx
                       /           \
                      v             v
                 Next.js         FastAPI
                                    |
                      +-------------+-------------+
                      |             |             |
                      v             v             v
                 PostgreSQL     RabbitMQ        Redis
                      ^             |             |
                      |             v             |
                      +---------- Worker ----------+
                         durable source of truth
```

- PostgreSQL stores users, sessions, channels, memberships, encrypted messages, uploads, outbox rows, events, and Merkle checkpoints.
- RabbitMQ provides durable asynchronous topic routing and bounded per-user realtime queues.
- The worker publishes committed outbox rows, consumes queues for online users, and bridges deliveries to Redis.
- Redis provides live fanout, WebSocket coordination, one-use tickets, distributed revocation, rate limits, and presence leases.
- WebSockets optimize live delivery; REST history and `/sync` recover missed messages from PostgreSQL.
- Nginx is the hardened/production edge. The direct development profile exposes services for local inspection.

See [Architecture](docs/ARCHITECTURE.md) for component responsibilities and end-to-end flows.

## Main features

- Public and private channels/topics with safe slugs, join policies, invitations, approvals, roles, and permissions.
- Persistent text and protected media messages with per-channel ordering.
- Transactional outbox, RabbitMQ topic exchange, retry/dead-letter tracking, Redis fanout, realtime WebSockets, and offline sync/backfill.
- Login, registration, session management, email verification, distributed presence, and a superadmin operations interface.
- Event/activity logs, delivery monitoring, English/Arabic localization, and RTL presentation.
- Server-side encryption at rest for messages and AES-GCM encrypted attachment storage with explicit key rotation tools.

## Security and integrity highlights

- Argon2 password hashing and session-bound access JWTs.
- Rotating refresh credentials with replay detection; browser refresh tokens use `HttpOnly` cookies plus Origin/CSRF checks.
- Single-use, short-lived WebSocket tickets and distributed session/socket revocation.
- Channel-level RBAC, protected uploads, bounded inputs/resources, rate limits, broker-safe identifiers, and trusted-proxy handling.
- Versioned data-encryption key rings, message encryption, authenticated chunked upload encryption, and rotation/migration commands.
- TLS Nginx production boundary with private state services and restricted non-root application containers.
- Per-scope SHA-256 audit hash chains, Merkle-tree checkpoints, Ed25519-signed roots, offline inclusion proofs, and exportable external anchors.

These are defense-in-depth controls for a university MVP, not a claim of end-to-end encryption, immutability, or production certification. See [Security](docs/SECURITY.md).

## Mandatory Merkle-tree feature

```text
Audit event
    -> canonical SHA-256 event hash
    -> ordered per-scope hash chain
    -> Merkle leaf
    -> Merkle tree
    -> Merkle root
    -> Ed25519-signed checkpoint
```

A Merkle tree combines many event hashes into one root. Proving that one event belongs to a batch needs only a logarithmic number of sibling hashes instead of every event. Changing the event, proof path, root, or signed checkpoint metadata makes verification fail.

The controls have distinct jobs:

- Hash chain: ordered continuity inside one channel or the system scope.
- Merkle tree: compact membership proof for an event in a checkpoint batch.
- Signed checkpoint: prevents a database-only attacker from silently replacing a root without the Ed25519 signing key.
- External anchor: detects rollback only after an operator stores the exported latest checkpoint independently.

Implementation, operator commands, and the supervisor demonstration are documented in [Architecture](docs/ARCHITECTURE.md#audit-and-merkle-flow), [Deployment](docs/DEPLOYMENT.md#merkle-checkpoint-operations), and [Demo Guide](docs/DEMO_GUIDE.md#mandatory-merkle-demonstration).

## Development quick start

Prerequisites: Git, Docker, and Docker Compose v2.

```bash
git clone https://github.com/abdojat/MessagingSystem.git
cd MessagingSystem
cp .env.example .env
docker compose up --build
```

PowerShell equivalent for the copy step:

```powershell
Copy-Item .env.example .env
```

The checked-in development template starts with local-only credentials and a warned deterministic encryption fallback. For retained demo data, replace `JWT_SECRET` and configure `DATA_ENCRYPTION_ACTIVE_KEY_ID` plus `DATA_ENCRYPTION_KEYS`; set the optional `SUPERADMIN_*` values before first startup if an administrator is needed. Exact generation commands are in [Development](docs/DEVELOPMENT.md#development-secrets-and-optional-superadmin).

The development backend automatically runs `alembic upgrade head`, schema reconciliation, and the optional idempotent superadmin bootstrap before Uvicorn starts.

| Service | Development URL/port |
|---|---|
| Frontend | `http://localhost:3000` |
| API | `http://localhost:8000/v1` |
| API docs | `http://localhost:8000/docs` |
| RabbitMQ management | `http://localhost:15672` (`guest` / `guest`, development only) |
| PostgreSQL | `localhost:5432` |
| RabbitMQ AMQP | `localhost:5672` |
| Redis | `localhost:6379` |

Stop without deleting data:

```bash
docker compose down
```

Reset all development volumes, including database, broker, and uploads:

```bash
# Destructive: deletes this Compose project's development volume data.
docker compose down -v
```

The complete Docker and direct-process workflows are in [Development](docs/DEVELOPMENT.md).

## Other run profiles

Hardened local/demo profile (HTTP, port `8080`, only Nginx published):

```bash
docker compose -f docker-compose.hardened.yml up --build
```

Production-oriented single-host reference profile:

```bash
cp .env.production.example .env.production
# Replace every placeholder and provide external TLS_CERT_PATH/TLS_KEY_PATH.
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yml ps -a
```

The production-oriented profile publishes only the configured HTTP/HTTPS edge, runs migrations in a one-shot service, does not silently bootstrap a superadmin in normal backend startup, and isolates the Merkle private signing seed to an explicit maintenance profile. It is a reference deployment for the university MVP, not an HA or production certification. Follow [Deployment](docs/DEPLOYMENT.md) before using it.

## Validation

Backend suite:

```bash
cd backend
python -B -m pytest -q
```

Frontend reproducible install and build:

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

Safe release verifier (uses uniquely named disposable backend test containers and does not touch application volumes):

```bash
python scripts/verify_release.py
```

The data-creating release-candidate scenario, focused suites, worker checks, Compose/Nginx checks, migration checks, and current measured results are in [Testing](docs/TESTING.md) and [Stabilization Status](docs/STABILIZATION_STATUS.md).

## Supervisor demo

Use the [Demo Guide](docs/DEMO_GUIDE.md) for setup and explanations, then the [Final Demo Checklist](docs/FINAL_DEMO_CHECKLIST.md) during the presentation. Both the 10-15 minute path and the five-minute fallback keep the mandatory signed Merkle checkpoint/proof/tamper demonstration visible.

## Documentation

- [Documentation index](docs/README.md)
- [Project overview](docs/PROJECT_OVERVIEW.md)
- [Architecture and component interaction](docs/ARCHITECTURE.md)
- [Development workflows](docs/DEVELOPMENT.md)
- [Deployment, migrations, crypto, and Merkle operations](docs/DEPLOYMENT.md)
- [Security model and limitations](docs/SECURITY.md)
- [Testing and release verification](docs/TESTING.md)
- [Requirements mapping](docs/REQUIREMENTS_MAPPING.md)
- [Final MVP status](docs/FINAL_MVP_STATUS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Final repository handoff](FINAL_REPOSITORY_HANDOFF.md)
- [Historical security reports](reports/security/README.md)

Direct Python dependencies are declared in `backend/pyproject.toml` and `worker/pyproject.toml`; the validated reproducible installations use their `requirements.lock` files. Frontend direct dependencies are declared in `frontend/package.json`, with `frontend/package-lock.json` as the reproducible npm lock.

## Known limitations

- Encryption is server-side at rest, not end-to-end encryption.
- External KMS/HSM custody, automatic independent anchor retention, managed backups, public-certificate automation, multi-host HA, and load certification are outside this MVP.
- Realtime queues are bounded; PostgreSQL-backed REST history/sync is the durable recovery path.
- Frontend browser automation, live multi-worker outage testing, and external SMTP-provider deliverability remain limited; the repository provides deterministic regressions and supervisor verifiers instead.
