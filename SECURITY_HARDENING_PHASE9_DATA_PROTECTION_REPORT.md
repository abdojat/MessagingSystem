# Security Hardening Phase 9 — Data Protection Report

Date: 2026-08-11

## 1. Scope

Phase 9 implements versioned server-side data-at-rest encryption and explicit
operator migration/rotation for message bodies and upload bytes. It preserves
the Phase 8 JWT/session, HttpOnly refresh, CSRF, WebSocket ticket, membership
generation, RabbitMQ desired-state, `/sync`, authorization, TLS/proxy, and
PostgreSQL runtime-role architecture.

This is application-level encryption at rest. It is not end-to-end encryption.

## 2. Findings addressed

| Finding | Confirmation | Result |
| --- | --- | --- |
| P9-01 — one non-versioned Fernet key/no rotation | **CONFIRMED** | New message writes use v2 envelopes with an explicit active key ID and bounded historical key ring. Bounded status and rotation commands are implemented. |
| P9-02 — unconditional plaintext message fallback | **CONFIRMED** | Plaintext is accepted only under an explicit development/migration flag; production-like configuration rejects that flag. Unknown/tampered formats fail closed. |
| P9-03 — plaintext uploaded file bytes | **CONFIRMED** | New PUT storage writes only authenticated chunked AES-256-GCM ciphertext. Historical files have an explicit bounded migration command. |
| P9-04 — no status/migration/rotation tooling | **CONFIRMED** | `app.db.crypto_tool` supplies counts-only status, message/upload migration, and message/upload rotation with bounded batches and crash recovery. |

## 3. Threat model and guarantees

Phase 9 protects primarily against database-dump disclosure, upload-volume or
backup inspection, accidental plaintext storage inspection, silent ciphertext
tampering, and unsafe historical-key replacement.

It guarantees:

- authenticated server-side encryption for new message bodies and upload bytes;
- explicit key selection rather than trial-decrypting every key;
- historical readability while the referenced key remains configured;
- fail-closed unknown-key, authentication, and production plaintext behavior;
- bounded storage migration/rotation without message republication;
- upload plaintext memory bounded by one 64 KiB framing buffer plus request/runtime overhead.

It does not protect data from a fully compromised running backend/maintenance
process that can read deployment keys. The server can decrypt authorized data.
There is no E2EE, external KMS/HSM, or client-held message key.

## 4. Key-ring architecture

Configuration:

```text
DATA_ENCRYPTION_ACTIVE_KEY_ID=key-2026-08
DATA_ENCRYPTION_KEYS={"key-2026-08":"<base64-32-byte-master-key>","key-2026-01":"<historical-key>"}
```

Key IDs match `^[A-Za-z0-9_-]{1,64}$`. The parser rejects empty/unsafe IDs,
duplicate JSON keys, malformed/non-object JSON, non-string values, malformed
base64, decoded lengths other than 32 bytes, an unknown active ID, and more than
32 keys. Pydantic input values are hidden in validation errors.

Production-like environments require a nonempty key ring and active member.
They reject both legacy plaintext compatibility flags. Explicit development or
test environments may use a deterministic development-only key when both new
settings are empty; runtime logs a warning without key bytes/values.

HKDF-SHA256 separates uses:

```text
message v2: salt=None, info="MessagingSystem/message/v2", length=32
upload v1:  salt=upload UUID bytes, info="MessagingSystem/upload/v1", length=32
```

`MESSAGE_ENCRYPTION_KEY` remains optional/deprecated for legacy-v1 message
decryption and migration only. New writes never use it.

## 5. Message encryption v2

Text storage:

```text
enc:v2:<key-id>:<fernet-token>
```

JSON storage is exactly:

```json
{"_enc_v2":{"kid":"<key-id>","token":"<fernet-token>"}}
```

Extra fields or malformed envelope fields fail. The key ID selects exactly one
HKDF-derived Fernet key. Unknown IDs and invalid/tampered tokens return the
controlled `DECRYPTION_FAILED` boundary.

Legacy bare Fernet text and `{"_enc_v1":"..."}` use only the deprecated legacy
key. A failed legacy Fernet authentication never falls through to plaintext.
Unrecognized persisted text/JSON requires
`ALLOW_LEGACY_PLAINTEXT_MESSAGES=true`, which production refuses.

The message service stores v2 ciphertext in PostgreSQL and copies that same
ciphertext into the outbox. The worker/RabbitMQ/Redis path remains opaque. The
backend decrypts only at an already-authorized REST/WebSocket boundary.

## 6. Upload encrypted-storage format

All integers are unsigned big-endian.

Canonical authenticated header (before its tag):

| Offset | Size | Field |
| --- | ---: | --- |
| 0 | 8 | magic `MSGUPENC` |
| 8 | 1 | version `1` |
| 9 | 16 | upload UUID bytes |
| 25 | 1 | key-ID byte length `1..64` |
| 26 | N | ASCII key ID |
| 26+N | 8 | logical plaintext size |
| 34+N | 4 | chunk size, currently exactly 65,536 |
| 38+N | 8 | random per-file nonce prefix |
| 46+N | 16 | AES-GCM header authentication tag |

Total header length is `62+N` bytes. The header tag is produced by encrypting
empty plaintext with nonce `nonce_prefix || 0xffffffff` and the canonical
header bytes as AAD.

Every frame is:

```text
chunk_index:uint32
plaintext_length:uint32
ciphertext_and_tag:plaintext_length+16
```

Frame nonce:

```text
nonce_prefix (8 bytes) || chunk_index (4 bytes)
```

Chunk indices start at zero, must be strictly monotonic, and may not reach the
reserved header counter. Every non-final chunk is exactly 65,536 plaintext
bytes; the final chunk is the exact remainder.

Frame AAD is:

```text
"MessagingSystem/upload/v1/chunk\0"
|| SHA-256(canonical_header)
|| chunk_index:uint32
|| plaintext_length:uint32
```

The parser bounds key-ID length, format plaintext size (1 TiB format ceiling),
chunk size (strict v1 64 KiB and absolute 1 MiB parser ceiling), frame length,
counter, ordering, total logical length, truncation, and trailing bytes. Header
and frame authentication prevents cross-upload/frame transplantation.

## 7. Upload streaming architecture

Upload:

```text
authorized request stream
  -> bounded plaintext aggregation
  -> logical SHA-256/size checks
  -> AES-GCM frames
  -> encrypted same-directory sibling
  -> flush/fsync
  -> atomic create-only final path
  -> version/key database metadata + audit commit
```

No complete plaintext sibling is written. `size_bytes`, `checksum`, and quotas
continue to describe logical plaintext, not physical encrypted bytes.

Download:

```text
authentication -> upload lookup -> authorization -> path containment
  -> range policy -> authenticated header -> download lease
  -> DB/audit completion and session close
  -> bounded authenticated decrypt stream -> client
```

`LeasedEncryptedFileResponse` retains the existing user/IP/process-global lease
until ASGI transmission ends and releases it on normal completion,
cancellation, send failure, filesystem failure, or integrity failure. Header
validation uses a worker thread; file reads use AnyIO's async file wrapper; each
AES-GCM operation is bounded to 64 KiB. Encrypted Range requests return 416.

## 8. Database migration 0022

`0022_phase9_upload_encryption` follows 0021 and does not alter older revisions.
It adds:

```text
storage_encryption_version SMALLINT NOT NULL DEFAULT 0
storage_key_id VARCHAR(64) NULL
```

The check constraint permits only:

```text
version 0 + null key ID
version 1 + non-null key ID
```

An index covers `(storage_encryption_version, storage_key_id)`. Historical and
pending rows begin at version 0. Alembic never decrypts or rewrites data.

## 9. Existing-data migration

Commands:

```text
python -m app.db.crypto_tool migrate-messages
python -m app.db.crypto_tool migrate-uploads
```

Message batches lock/order by UUID, preserve every domain field, and modify
only the persisted content fields. No message outbox or audit row is created.
Already-v2 rows are unchanged, making restart/retry idempotent.

Production application startup refuses plaintext compatibility. Historical
plaintext conversion therefore runs only in an isolated, non-listening CLI
process with the real database/upload volume and key ring, explicit
`ENVIRONMENT=local`, and only the required compatibility flag. The process must
never start Uvicorn/worker and is destroyed before normal production resumes
with both flags false.

Upload batches lock rows, resolve paths inside the configured base, and encrypt
plaintext into a fsynced same-directory temporary file before `os.replace`.
The database metadata commits afterward. If a process crashes after replacement
but before commit, the authenticated self-identifying header is detected on the
next run and the version/key metadata is repaired without double encryption.

After successful replacement, active application storage no longer retains the
plaintext file. This is not a claim of physical SSD/filesystem/backup erasure.

## 10. Key rotation

Operator sequence:

1. Add the new 32-byte master key to `DATA_ENCRYPTION_KEYS`.
2. Set `DATA_ENCRYPTION_ACTIVE_KEY_ID` to its ID and restart backend/migration processes; new writes switch immediately.
3. Keep every historical key configured.
4. Run `crypto_tool status` and resolve unreadable/invalid state.
5. Run `rotate-messages --to-key-id <active-id>`.
6. Run `rotate-uploads --to-key-id <active-id>`.
7. Run status again; require zero references to the old ID and zero errors.
8. Remove the old ID, restart, and re-read representative data.

Upload rotation authenticates/decrypts old chunks and writes a new fsynced
ciphertext sibling before atomic replacement. A restart can repair the same
file/DB commit window as migration.

## 11. Crypto status command

The counts-only command prints message v2 counts by key, legacy-v1, plaintext,
unknown/unreadable, and upload encrypted-v1 counts by key, plaintext,
pending/no-file, missing file, invalid format, and metadata mismatch. It prints
no content, names, tokens, ciphertext, paths, or key values.

Disposable empty-database result:

```text
Messages:
  legacy-v1: 0
  plaintext: 0
  unknown format: 0
  unreadable/unknown: 0
Uploads:
  plaintext: 0
  pending/no file: 0
  missing file: 0
  invalid format: 0
  metadata mismatch: 0
```

## 12. Tests added

`backend/tests/security/test_phase9_data_protection.py` has 35 tests covering
configuration, v2 text/JSON, active/historical keys, unknown/tampered data,
legacy/plaintext policy, multi-megabyte real-file storage, exact authorized
route/stream downloads, Range rejection, lease cleanup, migration idempotency,
outbox/audit non-duplication, crash recovery, rotation, status, and key removal.

Earlier Phase 1 tests were updated only where Phase 9 intentionally changes the
storage contract: raw upload paths now contain ciphertext, and optional preview
key-loss testing removes the referenced v2 key rather than changing the legacy
key.

## 13. Corruption/tampering tests

Tests mutate magic, version, key ID, plaintext size, chunk size, nonce, header
tag, frame index, frame length, ciphertext, GCM tag, truncation, trailing bytes,
and key-ID length. Every case fails without plaintext downgrade. Unknown upload
keys fail header preflight. Response failures release the download lease.

## 14. Validation results

Completed against disposable PostgreSQL 16:

```text
Phase 9 focused: 35 passed
Prior Phase 1/4/6/7/8 targeted subset: 95 passed, 1 warning
Complete backend: 287 passed, 1 warning
Frontend typecheck: passed
Frontend production build: passed
Development/hardened/production Compose rendering: passed
Production worker sensitive-key inspection: none
Fresh Alembic -> 0022: passed
Representative 0021 -> 0022 with historical upload: passed (version 0, null key)
Crypto status on disposable empty head schema: passed, zero errors
Disposable production-profile live demo: passed
```

The only warning is the existing passlib/argon2 version-metadata deprecation.
The frontend build retained its existing Next.js middleware-filename deprecation
notice; it did not fail the build.

## 15. Full demo regression

A fresh disposable production-profile stack passed the complete repository
verifier. It registered three users, joined User B after its WebSocket was
already connected, published through PostgreSQL/outbox -> RabbitMQ -> worker ->
Redis -> WebSocket, verified REST backfill and event integrity, and denied User
C access to the private attachment. Direct storage inspection then proved:

```text
UPLOAD_STORAGE_MAGIC=MSGUPENC
UPLOAD_PLAINTEXT_MARKER_PRESENT=no
AUTHORIZED_DOWNLOAD_EXACT=yes
MESSAGE_PLAINTEXT_MARKER_PRESENT=no
ENCRYPTED_RANGE_STATUS=416
WORKER_SENSITIVE_KEYS=none
HTTPS_API_HEALTH_STATUS=200
HTTP_REDIRECT_STATUS=308
```

Running both migration commands again reported only unchanged rows (two
messages and one upload), proving live idempotency. The first disposable launch
was intentionally rejected because the test runtime-database password was below
the repository's 32-character policy; it succeeded unchanged with a compliant
fixture. The generated one-day self-signed key also needed test-host read
permission for the deliberately unprivileged Nginx UID. Real deployments should
use narrowly group-readable operator-managed key permissions rather than the
disposable fixture's broad read bit. All disposable containers, volumes, images,
database state, and certificate files were removed after validation.

## 16. Key-removal proof

The focused proof created message/upload data under `key-a`, configured
`key-a + key-b` with `key-b` active, rotated to `key-b`, then rebuilt runtime
configuration containing only `key-b`. Rotated upload plaintext and message
content remained readable; status reported no invalid/mismatch state.

## 17. Files changed

Core implementation includes:

- `backend/app/core/config.py`, `encryption.py`, `upload_encryption.py`
- `backend/app/services/message_service.py`, `download_service.py`
- `backend/app/api/routes/messages.py`
- `backend/app/db/models.py`, `crypto_tool.py`
- `backend/alembic/versions/0022_phase9_upload_encryption.py`
- all three Compose profiles (worker key isolation included), `.env.example`, `.env.production.example`
- `backend/tests/security/test_phase9_data_protection.py` plus intentional legacy test expectation updates
- synchronized README/security/architecture/testing/status/requirements/assessment documentation

## 18. Remaining limitations

- No E2EE; the backend can decrypt authorized data.
- No external KMS, HSM, Vault, or automatic rotation scheduler.
- Replacing historical plaintext does not guarantee physical secure erasure.
- Backups require encryption, retention, and lifecycle controls.
- Provider-backed email verification remains absent.
- The documented multi-socket presence edge case remains.
- CSP retains its framework-required inline exception.
- External HTTPS images retain viewer-IP privacy implications.
- PostgreSQL/RabbitMQ/Redis HA, multi-host distributed quotas, load certification, and broader operator controls remain future work.

## 19. Final maturity assessment

Phase 9 closes the practical P9-01 through P9-04 storage gaps for the
single-host university MVP with bounded, reviewable primitives and explicit
operator control. The result is materially stronger data-at-rest protection,
not enterprise key management and not end-to-end encryption.
