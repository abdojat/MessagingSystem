# Security Hardening Phase 11 — Merkle Audit Integrity Report

## 1. Scope

Phase 11 adds a bounded, operational Merkle integrity layer to the existing
audit-event system. It preserves the distributed messaging architecture and the
existing per-scope event hash chains. The implementation includes PostgreSQL
checkpoint persistence, deterministic inclusion proofs, Ed25519 signatures,
offline verification, optional external anchors, superadmin APIs/UI, operator
tooling, migrations, tests, and documentation.

This was an implementation task, not a general security reassessment.

## 2. Supervisor requirement

Merkle-tree audit integrity was a mandatory project requirement.

The completed architecture is deliberately layered:

```text
existing per-scope SHA-256 event chains
        +
bounded global Merkle checkpoints
        +
compact inclusion proofs
        +
Ed25519-signed checkpoint chain
        +
optional independently retained anchor
```

## 3. Previous audit-integrity architecture

Every audit event already receives a canonical SHA-256 `event_hash` that covers
its stable identifiers, actor/channel context, type, timestamp, payload,
`previous_hash`, integrity version, and integrity scope. PostgreSQL advisory
locks serialize writers per `system` or `channel:<uuid>` scope. These chains
detect content/metadata changes and broken ordering within a scope.

Phase 11 does not remove or replace that behavior. Per-scope chains remain the
authoritative chronology. Legacy events with missing integrity metadata must be
initialized explicitly before checkpointing.

## 4. Phase 11 architecture

One global checkpoint sequence combines initialized system and channel event
hashes. A bounded operator transaction selects committed, uncheckpointed rows,
recomputes their event hashes, snapshots them as Merkle leaves, builds a root,
links the previous checkpoint hash, signs the canonical checkpoint, and commits
the batch and leaf rows atomically.

The layers provide distinct evidence:

- event hash: commits to the current event record;
- per-scope chain: ordered continuity inside a channel/system scope;
- Merkle tree: compact batch commitment and membership proof;
- checkpoint chain: continuity between batches;
- Ed25519 signature: protects checkpoint metadata from a database-only rewriter
  without the signing private key;
- externally retained anchor: detects rollback before or deletion of an
  independently remembered latest checkpoint.

Merkle batch order is checkpoint-processing order, not authoritative event
chronology. A later-committing transaction with an earlier timestamp can
correctly enter the next batch.

## 5. Merkle algorithm

The pure implementation is in `backend/app/services/merkle_service.py`.

- Event hashes and all tree nodes are strict lowercase 64-character SHA-256 hex.
- A leaf is `SHA256(0x00 || raw_32_byte_event_hash)`.
- A parent is `SHA256(0x01 || raw_left_32_bytes || raw_right_32_bytes)`.
- Concatenation operates on bytes, never hexadecimal text.
- If a level has an unpaired final node, that node is promoted unchanged.
- The root is represented as lowercase SHA-256 hex.
- Each proof node is `{"side":"left|right","hash":"<sha256>"}`.
- Proofs bind `leaf_index` and `leaf_count`, reject malformed structure/hashes,
  and allow at most 64 sibling nodes.
- Batch size is configurable from 1 through 4,096; the default is 256.

For `A B C`, the root is `H(H(A,B),C)` because `C` is promoted unchanged on
the first level.

## 6. Database migration 0024

`0024_phase11_merkle_audit` adds:

- `audit_merkle_batches`: UUID identity, unique positive sequence, algorithm and
  version, bounded leaf count, first/last event IDs and hashes, root, previous
  checkpoint hash, unique checkpoint hash, strict signing-key ID, signature,
  and UTC creation time;
- `audit_merkle_leaves`: batch/event identities, contiguous zero-based index,
  checkpoint-time event-hash snapshot, and derived leaf-hash snapshot.

The schema enforces unique `(batch_id, leaf_index)` and unique `event_id`, so an
event cannot be checkpointed twice. Event and batch foreign keys use
`ON DELETE RESTRICT`; evidence is not silently cascade-deleted. Hash/key/size
checks and query indexes are defined in the migration and ORM models.

Fresh PostgreSQL upgraded to revision `0024_phase11_merkle_audit`. A
representative `0023 -> 0024` upgrade preserved an encrypted message, encrypted
upload metadata, email-verification challenge, channel, audit event, and the
existing event hash; it began with zero Merkle batches/leaves as intended.

## 7. Checkpoint lifecycle

`python -m app.db.merkle_tool checkpoint`:

1. validates the bounded batch size and matching signing configuration;
2. acquires the dedicated checkpoint advisory transaction lock;
3. refuses to claim complete coverage while any event lacks integrity metadata;
4. selects committed uncheckpointed events by `created_at ASC, id ASC`;
5. recomputes every selected current event hash;
6. snapshots event/leaf hashes and creates the Merkle root;
7. creates canonical checkpoint metadata and links the prior checkpoint hash;
8. signs the raw 32-byte checkpoint hash;
9. inserts the batch and all leaf rows in the same transaction;
10. commits, or rolls back the entire checkpoint on failure.

`--all` repeats bounded transactions until no pending event remains. Repeating
checkpoint creation without new events is idempotent and creates no duplicate
batch or leaf.

## 8. Signing architecture

Checkpoint hashes use deterministic UTF-8 JSON with sorted keys, fixed
separators, and microsecond UTC timestamps. Ed25519 signs the raw 32-byte
SHA-256 checkpoint hash. This identity is separate from JWT and data-encryption
keys.

`AUDIT_MERKLE_PUBLIC_KEYS` is a bounded key-ID-to-public-key ring. Verification
selects exactly the stored `signing_key_id`; it never tries every key. Unknown
IDs fail. Rotation keeps historical public keys trusted while new checkpoints
use the new active ID. Old checkpoints are not rewritten.

Before signing, the tool derives the public key from the private seed and
requires an exact match with the active trusted public key. Production-like
configuration requires a trusted public key when verification is enabled.

Rendered production Compose confirms that only the opt-in
`merkle-checkpoint` service receives `AUDIT_MERKLE_SIGNING_PRIVATE_KEY`. Backend
and migration verification receive public keys; worker, frontend, and proxy
receive no Merkle signing keys. No real or deterministic production signing key
is committed.

## 9. Inclusion proof

A proof bundle contains the event ID/hash and leaf hash, batch ID/sequence,
leaf index/count, explicit-side siblings, Merkle root, canonical checkpoint
metadata/hash, signing key ID, and signature. It contains no event payload or
private key.

Example conceptual path:

```text
selected event hash -> domain-separated leaf
leaf + sibling 0 (right) -> parent
sibling 1 (left) + parent -> parent
...
computed root == signed checkpoint root
```

Database proof creation also recomputes the current event hash and requires it
to equal the checkpoint snapshot. Offline verification checks leaf derivation,
proof path/root, checkpoint hash, exact trusted key, and Ed25519 signature
without PostgreSQL.

## 10. External anchoring

`export-anchor` emits only the latest signed checkpoint commitment: version,
sequence, checkpoint hash/root, previous hash, timestamp, signing key ID, and
signature. `verify-anchor --offline` verifies its form/signature. Database-backed
verification additionally requires the exact checkpoint to exist and validates
the chain through its sequence.

Signed checkpoints prevent a database-only attacker without the signing key
from silently creating replacement roots. They do not stop the attacker from
deleting the newest valid rows and presenting an older signed state. Rollback
evidence exists only if an operator actually copies the latest anchor to
independent protected storage. The repository does not claim automatic
notarization or external storage.

## 11. Admin/API/UI

Superadmin-only, rate-limited, `Cache-Control: no-store` endpoints provide:

- `GET /v1/admin/audit/merkle/status`;
- `GET /v1/admin/audit/merkle/batches`;
- `GET /v1/admin/audit/merkle/events/{event_id}/proof`.

Ordinary users are denied. Responses expose integrity metadata rather than raw
event payloads or secrets. Integrity inconsistencies fail closed.

The bilingual superadmin page includes an Audit Integrity card showing counts,
latest batch/root, signature state, and checkpoint-chain state. Each listed
event can open a compact proof dialog with its selected leaf, explicit proof
path, root, and verification results. It does not render a large tree or add a
visualization dependency.

## 12. CLI/tooling

`python -m app.db.merkle_tool` provides:

- `status`: safe event/checkpoint counts and current validation state;
- `checkpoint [--max-leaves N] [--all]`: explicit bounded signing operation;
- `verify [--verify-event-chains]`: full database verification with non-zero
  exit on failure;
- `proof --event-id UUID [--output FILE] [--force]`: safe proof JSON;
- `verify-proof --proof FILE`: PostgreSQL-free inclusion/signature verification;
- `export-anchor --output FILE [--force]`: latest signed commitment;
- `verify-anchor --file FILE [--offline]`: signature-only or database-backed
  rollback verification;
- `generate-keypair`: explicit operator generation with a clear private-key
  warning. Tests generate ephemeral keys internally and do not print them.

Proof/anchor export refuses to overwrite existing files without `--force`.
Status and verification never print event payloads or signing/JWT/data keys.

## 13. Concurrency

Checkpoint jobs use `pg_advisory_xact_lock` in a dedicated two-integer namespace
identified by `audit_merkle_checkpoint_v1`. This namespace is separate from the
one-integer per-scope event-integrity locks. Checkpoint code takes no per-scope
lock and no whole-table lock, avoiding a new lock-order cycle.

Real independent PostgreSQL session tests launched two checkpoint jobs and
confirmed serialized, non-overlapping batches with every event checkpointed
once. Another controlled interleaving committed an event while checkpointing
and confirmed that it was either included from committed selected state or left
pending for the next batch—never lost or duplicated.

## 14. Tamper tests

Focused tests alter disposable data/copies and detect:

- current `event.payload` and `event_hash` changes;
- leaf snapshot event/leaf hash changes;
- Merkle root and checkpoint-signature changes;
- sibling hash, side, index, count, and root proof changes;
- checkpoint leaf-count and previous-hash changes;
- unknown/wrong public keys and private/public mismatches;
- leaf index/order inconsistency;
- anchored newest-checkpoint deletion/rollback.

A live ten-event PostgreSQL exercise first returned valid. Direct payload
corruption returned `EVENT_HASH_MISMATCH`; after restoring the disposable row,
verification returned valid again. Changing only the Merkle root returned
`CHECKPOINT_HASH_MISMATCH`.

## 15. Complexity demonstration

Merkle inclusion proof work/storage grows as `O(log n)` for balanced paths,
instead of transferring or hashing all `n` event records for one membership
claim. A balanced 256-leaf batch is approximately eight sibling hashes; a
1,024-leaf batch is approximately ten. Odd-node promotion can produce a shorter
path for a promoted final node, so these are explanatory examples rather than
hardcoded assumptions.

The 16-event supervisor demo produced four siblings.

## 16. Performance experiment

The live disposable PostgreSQL experiment created 1,024 hash-chained events and
one 1,024-leaf checkpoint, selected event 512, generated its proof, and verified
the exported bundle offline. Results on this development host:

| Measurement | Result |
|---|---:|
| Audit-event creation/commit | 6.516 s |
| Checkpoint creation/commit | 229.651 ms |
| Database-backed proof creation | 153.123 ms |
| Offline proof verification | 0.485 ms |
| Proof siblings | 10 |

These are approximate observations, not service-level requirements or load
certification. Batch memory is bounded, and proof verification is substantially
smaller than full-event verification.

## 17. Regression validation

- Phase 11 focused: `40 passed`.
- Phase 8-10 focused regression: `73 passed, 1 warning` using disposable
  PostgreSQL and real Redis.
- Complete backend: `352 passed, 1 warning`.
- Existing warning: passlib reads deprecated Argon2 package version metadata.
- Frontend: `npm run typecheck` and `npm run build` passed.
- Locales: 845 English/Arabic keys parsed and aligned.
- Compose: development, hardened, and production renders passed.
- Production key placement: private seed only on `merkle-checkpoint`; worker has
  no Merkle keys.
- Migrations: fresh `->0024` and representative `0023->0024` passed.
- `git diff --check` is recorded in the final repository validation.

The canonical backend Docker image rebuild stalled twice at this host's
five-minute builder limit without a build error. For the live regression, a
disposable image was assembled from the previously built dependency layer plus
the current source and migrations. This is reported as an environment caveat,
not as a successful canonical backend image build.

## 18. Full demo

The existing full messaging verifier passed in an isolated hardened stack:
register/login, channel creation, join-after-connect, publish, PostgreSQL/outbox,
RabbitMQ, worker, Redis, live WebSocket receipt, REST backfill, channel event
integrity, and outsider upload denial. The complete regression suite separately
retained Phase 8 browser/session, Phase 9 message/upload encryption and rotation,
and Phase 10 email verification/distributed-presence coverage.

The Phase 11 deterministic live demonstration used 16 actual PostgreSQL audit
rows. It created a signed checkpoint, selected leaf 6, generated four siblings,
and reported YES for event hash, proof, signature, and checkpoint chain. It then
changed a proof copy in memory and reported `FAILED (expected)`. CLI live checks
also verified proof export offline, anchor export against PostgreSQL, and a
second linked checkpoint.

## 19. Files changed

- Configuration/deployment: `.env.example`, `.env.production.example`,
  `.gitignore`, `docker-compose.production.yml`, `backend/pyproject.toml`.
- Database/core: `backend/app/db/models.py`,
  `backend/alembic/versions/0024_phase11_merkle_audit.py`,
  `backend/app/core/config.py`.
- Merkle implementation/tooling:
  `backend/app/services/merkle_service.py`,
  `backend/app/services/merkle_audit_service.py`,
  `backend/app/db/merkle_tool.py`, `scripts/demo_merkle_integrity.py`.
- API/schema: `backend/app/api/routes/admin.py`,
  `backend/app/schemas/merkle.py`.
- Tests: `backend/tests/conftest.py`,
  `backend/tests/security/test_phase11_merkle_integrity.py`.
- Frontend: `frontend/src/types/api.ts`,
  `frontend/src/hooks/use-superadmin.ts`,
  `frontend/src/components/features/chat/pages/superadmin.tsx`, English/Arabic
  locale catalogs.
- Documentation/status: README, architecture, security, testing, demo,
  requirements/status/assessment documents, lock ordering, and this report.

## 20. Remaining limitations

- The backend can still create valid audit events; this is evidence integrity,
  not proof that every server action or claim is honest.
- A Merkle tree is not end-to-end encryption and does not hide integrity
  metadata. The application retains separate server-side encryption at rest.
- Compromise of the active signing private key defeats the trustworthiness of
  future signatures until rotation and incident handling occur.
- An external anchor detects rollback only if it is actually stored and
  protected separately from the database/server.
- There is no blockchain, distributed witness/gossip system, or transparency-log
  service.
- There is no external KMS/HSM, automated signing-key rotation scheduler, or
  independent anchor-storage integration.
- Multi-host checkpoint HA, operator separation of duties, monitoring, and
  production load certification remain deployment concerns.
- The production CSP retains its existing framework-required inline exception;
  Phase 11 did not weaken it or add a visualization dependency.
- Physical secure erasure, backup encryption/retention, and disaster-recovery
  controls remain operational responsibilities.
- The canonical backend image should be rebuilt on the presentation host because
  the local Docker builder timed out during this validation.

## 21. Final maturity assessment

Phase 11 is implemented as a real, bounded Merkle-tree audit layer rather than a
decorative root calculation. It preserves scope chronology, snapshots each
checkpointed event commitment, provides compact offline-verifiable inclusion
proofs, signs a linked checkpoint sequence with an isolated Ed25519 identity,
and offers an honest manual external-anchor boundary.

For a university MVP, the result is mature, demonstrable, and cryptographically
meaningful. It is accurately described as tamper-evident and cryptographically
verifiable—not immutable, tamper-proof, blockchain-secured, or a substitute for
deployment key custody, independent anchors, backups, monitoring, and operator
controls.
