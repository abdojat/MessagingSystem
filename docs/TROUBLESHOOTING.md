# Troubleshooting

Use `docker compose ps -a` and service logs first. Do not paste secrets, full connection URLs, access/refresh tokens, verification fragments, or private signing keys into issue reports.

## Docker or Compose unavailable

Symptoms: `docker` is not recognized, the daemon is unavailable, or `docker compose` fails before rendering.

```bash
docker version
docker compose version
```

Start Docker Desktop/Engine and use Compose v2. The repository does not target the legacy `docker-compose` binary.

## Port already in use

Development publishes `3000`, `8000`, `5432`, `5672`, `6379`, and `15672`; hardened demo publishes `8080`. Stop the conflicting process/profile or change an intentional host mapping. Do not run direct and hardened profiles simultaneously against the same ports.

```bash
docker compose ps -a
docker compose down
docker compose -f docker-compose.hardened.yml down
```

## PostgreSQL is unhealthy or migrations fail

```bash
docker compose ps -a
docker compose logs --tail=200 postgres backend
docker compose exec backend python -m alembic heads
docker compose exec backend python -m alembic current
```

There must be one head: `0024_phase11_merkle_audit`. Development backend startup runs migrations automatically. In production, inspect the one-shot service:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml logs migrate
```

If a disposable development schema is irreparably stale, `docker compose down -v` recreates it, but deletes all development database/broker/upload volume data.

## RabbitMQ is unhealthy or delivery remains pending

```bash
docker compose logs --tail=200 rabbitmq worker backend
docker compose exec postgres psql -U postgres -d channels \
  -c "select status, count(*) from outbox group by status order by status;"
```

The worker retries with backoff and records terminal dead-letter state. PostgreSQL outbox rows remain authoritative; REST sync still recovers persisted messages. Development RabbitMQ management is at `http://localhost:15672`; it is intentionally not published in hardened/production profiles.

Retained queues from releases before bounded user-queue arguments may initially produce one RabbitMQ `PRECONDITION_FAILED` per current user. Worker startup recognizes only a managed `user.*` queue whose expected `x-expires`, `x-message-ttl`, `x-max-length`, or `x-overflow` argument is absent, refuses deletion while another consumer is active, recreates that realtime queue with current bounds, and logs the repair. Do not delete the RabbitMQ volume merely for this upgrade: PostgreSQL/REST sync is the durable recovery path, and failed binding rows can be replayed through the authenticated Delivery Monitor after the queue repair. Other inequivalent queue arguments are not deleted automatically.

## Redis authentication/fanout/presence failure

```bash
docker compose logs --tail=200 redis worker backend
```

Verify `REDIS_URL` matches the selected profile. Production Redis requires `REDIS_PASSWORD`; an unauthenticated URL will fail. During Redis loss, live fanout, distributed tickets/revocation/rate limits, and presence are degraded according to their fail-safe behavior; PostgreSQL message history remains available.

## Frontend cannot reach the API

- Direct development build: `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/v1`.
- Hardened/production proxy build: `NEXT_PUBLIC_API_BASE_URL=/v1` is set by Compose.

The value is compiled into the client bundle, so rebuild after changing it:

```bash
docker compose build frontend
docker compose up -d frontend
```

For direct npm development, set it before `npm run dev` or use untracked `frontend/.env.local`.

## WebSocket fails behind Nginx

Inspect both proxy and backend logs:

```bash
docker compose -f docker-compose.hardened.yml logs --tail=200 proxy backend
```

Use the same origin/host that the profile expects. The repository Nginx configurations explicitly forward Upgrade plus trusted `Host`, `X-Forwarded-For`, and `X-Forwarded-Proto` headers. Custom proxies must overwrite forwarding identity and their exact network must be included in `TRUSTED_PROXY_CIDRS`; do not trust arbitrary Internet CIDRs.

## Missing or invalid data-encryption configuration

Production-like startup rejects an empty/invalid key ring, unknown active ID, weak/default JWT secret, or enabled plaintext compatibility. Confirm:

- `DATA_ENCRYPTION_ACTIVE_KEY_ID` is a safe ID present in `DATA_ENCRYPTION_KEYS`;
- every master key decodes to 32 bytes;
- `ALLOW_LEGACY_PLAINTEXT_MESSAGES=false` and `ALLOW_LEGACY_PLAINTEXT_UPLOADS=false`;
- historical keys remain until status reports no references.

Inspect counts without printing plaintext or keys:

```bash
docker compose exec backend python -B -m app.db.crypto_tool status
```

## SMTP/email verification unavailable

Development may use `EMAIL_DELIVERY_MODE=console`; the verification fragment URL appears in backend output. Production verification requires an HTTPS `EMAIL_VERIFICATION_PUBLIC_URL`, `EMAIL_DELIVERY_MODE=smtp`, SMTP host/from address, and exactly one encrypted transport mode (implicit TLS or STARTTLS). Check:

```bash
docker compose logs --tail=200 backend
```

Do not log or share verification fragments. If production verification is disabled/unavailable, unresolved pre-registration email invitations are intentionally unavailable; generic, user-ID, and already resolved existing-account invitations remain separate flows.

## Merkle signing or proof verification fails

`SIGNING_KEY_CONFIG_INVALID` means the one-shot checkpoint/demo process lacks a valid key ID/private seed or its public-key ring does not contain the matching key. The normal backend should not hold the private seed.

```bash
docker compose exec backend python -B -m app.db.merkle_tool status
docker compose exec backend python -B -m app.db.merkle_tool verify --verify-event-chains
```

An `unknown signing key` result means the required historical public key is absent from `AUDIT_MERKLE_PUBLIC_KEYS`. Retain public keys for every checkpoint that must remain verifiable. A missing proof may also mean the event has not yet been checkpointed; run the explicit integrity profile after reviewing pending status.

## Production TLS mount or host failure

Compose rendering reports `${TLS_CERT_PATH required}`, `${TLS_KEY_PATH required}`, or another `... required` message when a mandatory production value is missing. Supply absolute readable certificate/key paths outside the repository and confirm `PUBLIC_HOST` matches the requested hostname.

```bash
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml logs proxy
```

Unknown Host values are deliberately rejected. A self-signed certificate is suitable only for isolated validation, not a public deployment.

## `npm ci` rejects the lock or the frontend build fails

Run from `frontend/` with Node 22/npm and do not substitute pnpm/yarn:

```bash
npm ci
npm run typecheck
npm run build
```

`npm ci` requires `package.json` and `package-lock.json` to match. Do not “fix” this by deleting the lock; dependency changes must update and review both files.
