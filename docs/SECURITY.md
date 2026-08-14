# Security

This document describes the current security model. Historical findings and repair chronology are preserved under [`reports/security/`](../reports/security/README.md).

## Authentication and sessions

- Passwords are hashed with Argon2 through the maintained authentication service; plaintext passwords are never stored.
- Access JWTs are short-lived and bound to a database session. Logout, explicit revocation, logout-all, refresh replay detection, absolute expiry, and account deactivation invalidate later authenticated requests.
- Refresh tokens rotate. The browser flow stores the access token only in memory and the refresh credential in an `HttpOnly` cookie; refresh/logout require an allowed Origin and double-submit CSRF validation.
- Secure production-like environments derive `Secure` `__Host-` cookie names. The legacy JSON token endpoints remain for scripts/non-browser clients.
- WebSockets do not accept a long-lived JWT in the URL. An authenticated client obtains a short-lived, single-use opaque ticket whose hash is consumed through Redis.
- Login, registration, refresh, verification, WebSocket admission, message writes, uploads, management operations, and other expensive/sensitive groups have bounded inputs and rate limits.

## Authorization

Authentication does not imply channel access. Services check channel lifecycle, membership, role, and explicit permissions before:

- listing or reading private channel data;
- publishing, editing, deleting, pinning, reacting, or syncing messages;
- joining, approving, inviting, removing, or changing member roles;
- reading event logs or delivery state;
- creating, linking, or downloading uploads;
- performing superadmin account/channel/session operations.

Authorization occurs before message or attachment decryption. Superadmin status grants platform administration and global audit visibility, but it does not implicitly grant access to private message bodies. Unauthorized access is returned as `403 Forbidden` (or `404` for absent resources) and security-relevant denials are audited where appropriate.

## Identifier and path safety

Usernames and channel slugs use the broker-safe rule:

```text
^[A-Za-z0-9_-]{3,50}$
```

RabbitMQ routing keys, queue names, Redis pub/sub channels, and filesystem storage paths are built from validated identifiers or UUID-backed metadata. Raw filenames and arbitrary user strings are not used as broker patterns or trusted paths. Upload resolution verifies that the final path remains under `UPLOADS_BASE_DIR`.

## Message encryption at rest

New message writes use a versioned envelope with an explicit key ID. `DATA_ENCRYPTION_ACTIVE_KEY_ID` selects the write key and `DATA_ENCRYPTION_KEYS` holds a bounded current/historical key ring. Domain-separated derived keys prevent reuse across message and upload purposes.

`MESSAGE_ENCRYPTION_KEY` is deprecated and exists only to decrypt/migrate legacy v1 Fernet rows. Production-like environments reject plaintext compatibility. Old keys must remain configured until `crypto_tool status` reports no remaining references or unreadable data.

This is server-side encryption at rest, not end-to-end encryption: the authorized backend and explicit maintenance process can decrypt data.

## Upload encryption and access

- Upload metadata creation and content storage require authentication.
- Upload bodies are streamed, size/checksum validated, and finalized once; interrupted or invalid temporary files are cleaned up.
- New upload files use chunked authenticated AES-256-GCM storage. The upload ID, key ID, framing, logical size, and checksum context are authenticated.
- Downloads complete database authorization/audit work before bounded streaming decryption. Authorized reads have a separate default budget of 600 requests/minute, while upload creation/body writes retain the stricter 60 requests/minute budget. Per-user, per-client-IP, and process-global leases bound concurrent protected streams at configurable defaults of 20, 100, and 1,000 respectively.
- Encrypted range requests are rejected, and APIs do not expose host filesystem paths.
- Profile avatars, wallpapers, and message media use the same protected-media authorization path.

## Email identity and presence

Verification challenges are stored as hashes, expire, are one-use, and bind to the authenticated user's exact normalized email snapshot. Production configuration permits SMTP only with implicit TLS or STARTTLS and an HTTPS public verification URL. Existing-user email invitations bind to immutable user IDs; only unresolved pre-registration invitations depend on later mailbox proof.

Presence uses per-WebSocket Redis leases and aggregate transitions. Redis failure may make presence stale/unknown; presence never influences authentication, membership, or content authorization.

## Browser, proxy, and resource boundary

The production-oriented profile provides TLS termination, Host/CORS enforcement, trusted fixed-proxy forwarding, security headers, request/body/header/time/connection limits, authenticated Redis/RabbitMQ/PostgreSQL, private service networks, and a non-superuser runtime database role. Application containers are non-root, read-only, capability-dropped, and `no-new-privileges`.

Only explicit development/test environment labels permit local placeholder secrets, non-secure cookies, plaintext migration windows, or the warned deterministic data-encryption fallback. Production-like configuration fails closed for weak/missing JWT secrets, invalid key rings, insecure cookies, plaintext compatibility, invalid SMTP transport, and missing Merkle verifier keys when verification is enabled.

## Audit hash chains and mandatory Merkle tree

```text
Audit event
    -> canonical SHA-256 event hash
    -> ordered per-scope hash chain
    -> Merkle leaf and bounded tree
    -> Merkle root
    -> linked checkpoint hash
    -> Ed25519 signature
```

A Merkle tree commits many audit-event hashes to one root. An inclusion proof needs only a logarithmic sibling path. Verification recomputes the event hash, leaf/path, root, canonical checkpoint hash, signature, and checkpoint chain; changing any covered value makes the check fail.

The hash chain and Merkle tree are intentionally both present:

- Hash chain: chronology and continuity inside a channel/system scope.
- Merkle tree: efficient membership proof across a checkpoint batch.
- Signed checkpoint: protects the committed root against a database-only rewrite without the private Ed25519 seed.
- External anchor: adds rollback/tail-deletion evidence only when copied to independent operator-controlled storage.

Normal event writes do not rebuild a tree. An explicit one-shot operator/scheduled job checkpoints accumulated, integrity-initialized events in bounded batches. The normal backend and worker do not receive the signing private seed; production Compose injects it only into `merkle-checkpoint`. Public keys remain available for verification and key rotation history.

The implementation is tamper-evident, not immutable, not a blockchain, and not automatic third-party notarization. Exact commands are in [Deployment](DEPLOYMENT.md#merkle-checkpoint-operations); the presentation path is in [Demo Guide](DEMO_GUIDE.md#mandatory-merkle-demonstration).

## Secret handling

Tracked files contain templates only. Do not commit `.env`, `.env.production`, JWT/data/Merkle private keys, service passwords, SMTP passwords, TLS private keys, proof/anchor exports, uploads, dumps, or logs. Generate secrets outside captured CI logs and remove optional bootstrap credentials after use.

The production worker deliberately receives database/broker/Redis settings but no JWT, data-encryption, legacy-Fernet, or Merkle signing keys. The checkpoint service receives the Merkle private seed but not JWT or application data-encryption keys.

## Event logging

Registration, login/logout, channel/membership/message/upload operations, administrative changes, important denials, broker retries/dead letters, email verification, and integrity operations produce typed events. Event payloads are allowlisted/sanitized; passwords, full tokens, encryption keys, SMTP credentials, and private filesystem paths must never be logged.

Delivery diagnostics are best effort after authoritative outbox status commits. Successful upload-access logging is also best effort so a temporary audit failure does not break authorized media delivery; authorization itself is not best effort.

## Known limitations

- Server-side encryption does not protect plaintext from a compromised authorized backend process.
- Keys are environment-injected; managed KMS/HSM custody and automated rotation authority are not included.
- Merkle rollback detection depends on manual independent anchor retention; signing-key compromise defeats future signatures.
- The production-oriented Compose profile is single-host and not HA, disaster-recovery, managed-backup, or production-load certified.
- CSP still allows inline script/style behavior required by the current Next.js build.
- Browser automation, public certificate lifecycle, external SMTP deliverability/bounces, centralized monitoring/alerting, backup restoration, and incident-response processes remain operator/future work.
- Cross-instance revocation during Redis loss is best effort until credential expiry; some emergency limits are intentionally per process.
- RabbitMQ/Redis outage behavior has deterministic regression coverage but no sustained multi-worker failure/load certification.
