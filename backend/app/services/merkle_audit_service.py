"""Persistence, signing, proof, and verification for Phase 11 audit checkpoints."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.db.models import AuditMerkleBatch, AuditMerkleLeaf, Event
from app.services.event_integrity_service import (
    HASH_ALGORITHM,
    INTEGRITY_VERSION,
    EventIntegrityService,
    compute_event_hash,
)
from app.services.merkle_service import (
    HASH_HEX_RE,
    build_merkle_proof,
    build_merkle_root,
    leaf_hash,
    verify_event_merkle_proof,
)


CHECKPOINT_VERSION = 1
MERKLE_VERSION = 1
MAX_BATCH_SIZE = 4096
SIGNING_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CHECKPOINT_LOCK_NAME = "audit_merkle_checkpoint_v1"
CHECKPOINT_CANONICAL_FIELDS = (
    "checkpoint_version",
    "sequence_no",
    "merkle_version",
    "hash_algorithm",
    "leaf_count",
    "first_event_id",
    "last_event_id",
    "first_event_hash",
    "last_event_hash",
    "merkle_root",
    "previous_checkpoint_hash",
    "signing_key_id",
    "created_at",
)


class MerkleIntegrityError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime | str) -> str:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MerkleIntegrityError("CHECKPOINT_FORMAT_INVALID", "checkpoint timestamp is malformed") from exc
        value = parsed
    if not isinstance(value, datetime):
        raise MerkleIntegrityError("CHECKPOINT_FORMAT_INVALID", "checkpoint timestamp is malformed")
    return _as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decode_base64(value: str, *, size: int, field: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise MerkleIntegrityError("KEY_FORMAT_INVALID", f"{field} is missing or malformed")
    try:
        decoded = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise MerkleIntegrityError("KEY_FORMAT_INVALID", f"{field} is missing or malformed") from exc
    if len(decoded) != size:
        raise MerkleIntegrityError("KEY_FORMAT_INVALID", f"{field} has an invalid decoded length")
    return decoded


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def generate_ed25519_keypair() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    seed = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return _encode_base64(seed), _encode_base64(public)


def derive_public_key(private_key_base64: str) -> str:
    seed = _decode_base64(private_key_base64, size=32, field="signing private key")
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    return _encode_base64(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    )


def validate_signing_configuration(
    signing_key_id: str,
    private_key_base64: str,
    public_keys: Mapping[str, str],
) -> None:
    if SIGNING_KEY_ID_RE.fullmatch(signing_key_id or "") is None:
        raise MerkleIntegrityError("SIGNING_KEY_CONFIG_INVALID", "active Merkle signing key ID is invalid")
    trusted_value = public_keys.get(signing_key_id)
    if trusted_value is None:
        raise MerkleIntegrityError("UNKNOWN_SIGNING_KEY", "active Merkle signing key ID is not trusted")
    _decode_base64(trusted_value, size=32, field="trusted public key")
    if derive_public_key(private_key_base64) != trusted_value:
        raise MerkleIntegrityError(
            "SIGNING_KEY_MISMATCH",
            "active Merkle signing private key does not match its configured public key",
        )


def sign_checkpoint_hash(checkpoint_hash: str, private_key_base64: str) -> str:
    if HASH_HEX_RE.fullmatch(checkpoint_hash or "") is None:
        raise MerkleIntegrityError("CHECKPOINT_HASH_MISMATCH", "checkpoint hash is malformed")
    seed = _decode_base64(private_key_base64, size=32, field="signing private key")
    signature = Ed25519PrivateKey.from_private_bytes(seed).sign(bytes.fromhex(checkpoint_hash))
    return _encode_base64(signature)


def verify_checkpoint_signature(
    checkpoint_hash: str,
    signing_key_id: str,
    signature: str,
    public_keys: Mapping[str, str],
) -> tuple[bool, str | None]:
    if HASH_HEX_RE.fullmatch(checkpoint_hash or "") is None:
        return False, "CHECKPOINT_HASH_MISMATCH"
    public_value = public_keys.get(signing_key_id)
    if public_value is None:
        return False, "UNKNOWN_SIGNING_KEY"
    try:
        public_bytes = _decode_base64(public_value, size=32, field="trusted public key")
        signature_bytes = _decode_base64(signature, size=64, field="checkpoint signature")
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature_bytes, bytes.fromhex(checkpoint_hash))
    except (MerkleIntegrityError, InvalidSignature, ValueError):
        return False, "SIGNATURE_INVALID"
    return True, None


def checkpoint_payload(source: AuditMerkleBatch | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, AuditMerkleBatch):
        raw: Mapping[str, Any] = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "sequence_no": source.sequence_no,
            "merkle_version": source.merkle_version,
            "hash_algorithm": source.hash_algorithm,
            "leaf_count": source.leaf_count,
            "first_event_id": str(source.first_event_id),
            "last_event_id": str(source.last_event_id),
            "first_event_hash": source.first_event_hash,
            "last_event_hash": source.last_event_hash,
            "merkle_root": source.merkle_root,
            "previous_checkpoint_hash": source.previous_checkpoint_hash,
            "signing_key_id": source.signing_key_id,
            "created_at": source.created_at,
        }
    else:
        raw = source
    if any(field not in raw for field in CHECKPOINT_CANONICAL_FIELDS):
        raise MerkleIntegrityError("CHECKPOINT_FORMAT_INVALID", "checkpoint metadata is incomplete")
    try:
        checkpoint_version = int(raw["checkpoint_version"])
        sequence_no = int(raw["sequence_no"])
        merkle_version = int(raw["merkle_version"])
        leaf_count = int(raw["leaf_count"])
        first_event_id = str(UUID(str(raw["first_event_id"])))
        last_event_id = str(UUID(str(raw["last_event_id"])))
    except (TypeError, ValueError) as exc:
        raise MerkleIntegrityError("CHECKPOINT_FORMAT_INVALID", "checkpoint metadata is malformed") from exc
    if sequence_no < 1 or merkle_version != MERKLE_VERSION or not 1 <= leaf_count <= MAX_BATCH_SIZE:
        raise MerkleIntegrityError("CHECKPOINT_FORMAT_INVALID", "checkpoint numeric metadata is invalid")
    if checkpoint_version != CHECKPOINT_VERSION or raw["hash_algorithm"] != HASH_ALGORITHM:
        raise MerkleIntegrityError("CHECKPOINT_FORMAT_INVALID", "checkpoint version or algorithm is unsupported")
    for field in ("first_event_hash", "last_event_hash", "merkle_root"):
        if HASH_HEX_RE.fullmatch(str(raw[field])) is None:
            raise MerkleIntegrityError("CHECKPOINT_FORMAT_INVALID", f"{field} is malformed")
    previous = raw["previous_checkpoint_hash"]
    if previous is not None and HASH_HEX_RE.fullmatch(str(previous)) is None:
        raise MerkleIntegrityError("CHECKPOINT_FORMAT_INVALID", "previous checkpoint hash is malformed")
    signing_key_id = str(raw["signing_key_id"])
    if SIGNING_KEY_ID_RE.fullmatch(signing_key_id) is None:
        raise MerkleIntegrityError("CHECKPOINT_FORMAT_INVALID", "checkpoint signing key ID is invalid")
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "sequence_no": sequence_no,
        "merkle_version": merkle_version,
        "hash_algorithm": HASH_ALGORITHM,
        "leaf_count": leaf_count,
        "first_event_id": first_event_id,
        "last_event_id": last_event_id,
        "first_event_hash": str(raw["first_event_hash"]),
        "last_event_hash": str(raw["last_event_hash"]),
        "merkle_root": str(raw["merkle_root"]),
        "previous_checkpoint_hash": str(previous) if previous is not None else None,
        "signing_key_id": signing_key_id,
        "created_at": _timestamp(raw["created_at"]),
    }


def canonical_checkpoint_json(source: AuditMerkleBatch | Mapping[str, Any]) -> str:
    return json.dumps(checkpoint_payload(source), sort_keys=True, separators=(",", ":"))


def compute_checkpoint_hash(source: AuditMerkleBatch | Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_checkpoint_json(source).encode("utf-8")).hexdigest()


def _valid_event_metadata_filter():
    return and_(
        Event.event_hash.is_not(None),
        Event.hash_algorithm == HASH_ALGORITHM,
        Event.integrity_version == INTEGRITY_VERSION,
        Event.integrity_scope.is_not(None),
    )


class MerkleAuditService:
    @staticmethod
    async def lock_checkpoint(db: AsyncSession) -> None:
        bind = db.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        # The two-int advisory namespace is distinct from the existing one-int
        # per-scope event locks. Checkpointing never acquires those scope locks.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(1296387660, hashtext(:lock_name))"),
            {"lock_name": CHECKPOINT_LOCK_NAME},
        )

    @staticmethod
    async def create_checkpoint(
        db: AsyncSession,
        *,
        max_leaves: int,
        signing_key_id: str,
        private_key_base64: str,
        public_keys: Mapping[str, str],
    ) -> AuditMerkleBatch | None:
        if not 1 <= int(max_leaves) <= MAX_BATCH_SIZE:
            raise MerkleIntegrityError("BATCH_SIZE_INVALID", "Merkle batch size must be between 1 and 4096")
        validate_signing_configuration(signing_key_id, private_key_base64, public_keys)
        await MerkleAuditService.lock_checkpoint(db)

        missing_count = int(
            (
                await db.execute(
                    select(func.count(Event.id)).where(or_(
                        Event.event_hash.is_(None),
                        Event.hash_algorithm != HASH_ALGORITHM,
                        Event.hash_algorithm.is_(None),
                        Event.integrity_version != INTEGRITY_VERSION,
                        Event.integrity_version.is_(None),
                        Event.integrity_scope.is_(None),
                    ))
                )
            ).scalar_one()
            or 0
        )
        if missing_count:
            raise MerkleIntegrityError(
                "MISSING_INTEGRITY_METADATA",
                f"{missing_count} audit event(s) require integrity initialization before checkpointing",
            )

        events = list(
            (
                await db.execute(
                    select(Event)
                    .outerjoin(AuditMerkleLeaf, AuditMerkleLeaf.event_id == Event.id)
                    .where(AuditMerkleLeaf.event_id.is_(None), _valid_event_metadata_filter())
                    .order_by(Event.created_at.asc(), Event.id.asc())
                    .limit(int(max_leaves))
                )
            ).scalars().all()
        )
        if not events:
            return None
        for event in events:
            if compute_event_hash(event) != event.event_hash:
                raise MerkleIntegrityError(
                    "EVENT_HASH_MISMATCH", f"audit event {event.id} failed hash verification before checkpointing"
                )

        latest = (
            await db.execute(select(AuditMerkleBatch).order_by(AuditMerkleBatch.sequence_no.desc()).limit(1))
        ).scalar_one_or_none()
        event_hashes = [str(event.event_hash) for event in events]
        leaf_hashes = [leaf_hash(value) for value in event_hashes]
        created_at = utcnow()
        batch = AuditMerkleBatch(
            sequence_no=1 if latest is None else latest.sequence_no + 1,
            merkle_version=MERKLE_VERSION,
            hash_algorithm=HASH_ALGORITHM,
            leaf_count=len(events),
            first_event_id=events[0].id,
            last_event_id=events[-1].id,
            first_event_hash=event_hashes[0],
            last_event_hash=event_hashes[-1],
            merkle_root=build_merkle_root(leaf_hashes),
            previous_checkpoint_hash=latest.checkpoint_hash if latest is not None else None,
            checkpoint_hash="0" * 64,
            signing_key_id=signing_key_id,
            signature="",
            created_at=created_at,
        )
        batch.checkpoint_hash = compute_checkpoint_hash(batch)
        batch.signature = sign_checkpoint_hash(batch.checkpoint_hash, private_key_base64)
        db.add(batch)
        await db.flush()
        db.add_all(
            [
                AuditMerkleLeaf(
                    batch_id=batch.id,
                    event_id=event.id,
                    leaf_index=index,
                    event_hash=event_hashes[index],
                    leaf_hash=leaf_hashes[index],
                )
                for index, event in enumerate(events)
            ]
        )
        await db.flush()
        return batch

    @staticmethod
    async def status(db: AsyncSession, public_keys: Mapping[str, str]) -> dict[str, Any]:
        total_events = int((await db.execute(select(func.count(Event.id)))).scalar_one() or 0)
        integrity_hashed = int(
            (await db.execute(select(func.count(Event.id)).where(_valid_event_metadata_filter()))).scalar_one() or 0
        )
        checkpointed = int((await db.execute(select(func.count(AuditMerkleLeaf.event_id)))).scalar_one() or 0)
        pending = int(
            (
                await db.execute(
                    select(func.count(Event.id))
                    .outerjoin(AuditMerkleLeaf, AuditMerkleLeaf.event_id == Event.id)
                    .where(AuditMerkleLeaf.event_id.is_(None), _valid_event_metadata_filter())
                )
            ).scalar_one()
            or 0
        )
        batch_count = int((await db.execute(select(func.count(AuditMerkleBatch.id)))).scalar_one() or 0)
        latest = (
            await db.execute(select(AuditMerkleBatch).order_by(AuditMerkleBatch.sequence_no.desc()).limit(1))
        ).scalar_one_or_none()
        chain = await MerkleAuditService.verify_database(db, public_keys=public_keys)
        latest_signature_valid: bool | None = None
        if latest is not None:
            latest_signature_valid, _ = verify_checkpoint_signature(
                latest.checkpoint_hash, latest.signing_key_id, latest.signature, public_keys
            )
        return {
            "total_events": total_events,
            "integrity_hashed_events": integrity_hashed,
            "checkpointed_events": checkpointed,
            "pending_events": pending,
            "missing_integrity_events": total_events - integrity_hashed,
            "batch_count": batch_count,
            "latest_sequence": latest.sequence_no if latest else None,
            "latest_root": latest.merkle_root if latest else None,
            "latest_checkpoint_hash": latest.checkpoint_hash if latest else None,
            "latest_signing_key_id": latest.signing_key_id if latest else None,
            "latest_signature_valid": latest_signature_valid,
            "checkpoint_chain_valid": bool(chain["valid"]),
            "reason_code": chain.get("reason_code"),
        }

    @staticmethod
    async def list_batches(db: AsyncSession, *, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        total = int((await db.execute(select(func.count(AuditMerkleBatch.id)))).scalar_one() or 0)
        batches = list(
            (
                await db.execute(
                    select(AuditMerkleBatch)
                    .order_by(AuditMerkleBatch.sequence_no.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).scalars().all()
        )
        return [MerkleAuditService.batch_summary(batch) for batch in batches], total

    @staticmethod
    def batch_summary(batch: AuditMerkleBatch) -> dict[str, Any]:
        return {
            "id": batch.id,
            "sequence_no": batch.sequence_no,
            "leaf_count": batch.leaf_count,
            "merkle_root": batch.merkle_root,
            "checkpoint_hash": batch.checkpoint_hash,
            "previous_checkpoint_hash": batch.previous_checkpoint_hash,
            "signing_key_id": batch.signing_key_id,
            "created_at": batch.created_at,
        }

    @staticmethod
    async def _verify_batch(
        db: AsyncSession,
        batch: AuditMerkleBatch,
        public_keys: Mapping[str, str],
    ) -> str | None:
        try:
            expected_checkpoint_hash = compute_checkpoint_hash(batch)
        except MerkleIntegrityError:
            return "CHECKPOINT_FORMAT_INVALID"
        if batch.checkpoint_hash != expected_checkpoint_hash:
            return "CHECKPOINT_HASH_MISMATCH"
        signature_valid, signature_reason = verify_checkpoint_signature(
            batch.checkpoint_hash, batch.signing_key_id, batch.signature, public_keys
        )
        if not signature_valid:
            return signature_reason

        leaves = list(
            (
                await db.execute(
                    select(AuditMerkleLeaf)
                    .where(AuditMerkleLeaf.batch_id == batch.id)
                    .order_by(AuditMerkleLeaf.leaf_index.asc())
                )
            ).scalars().all()
        )
        if len(leaves) != batch.leaf_count:
            return "LEAF_COUNT_MISMATCH"
        if [item.leaf_index for item in leaves] != list(range(batch.leaf_count)):
            return "LEAF_INDEX_MISMATCH"
        if not leaves:
            return "LEAF_COUNT_MISMATCH"
        if (
            leaves[0].event_id != batch.first_event_id
            or leaves[-1].event_id != batch.last_event_id
            or leaves[0].event_hash != batch.first_event_hash
            or leaves[-1].event_hash != batch.last_event_hash
        ):
            return "CHECKPOINT_BOUNDARY_MISMATCH"

        for item in leaves:
            try:
                if leaf_hash(item.event_hash) != item.leaf_hash:
                    return "LEAF_HASH_MISMATCH"
            except ValueError:
                return "LEAF_HASH_MISMATCH"
        try:
            if build_merkle_root([item.leaf_hash for item in leaves]) != batch.merkle_root:
                return "MERKLE_ROOT_MISMATCH"
        except ValueError:
            return "MERKLE_ROOT_MISMATCH"

        events = list(
            (
                await db.execute(select(Event).where(Event.id.in_([item.event_id for item in leaves])))
            ).scalars().all()
        )
        events_by_id = {event.id: event for event in events}
        if len(events_by_id) != len(leaves):
            return "EVENT_MISSING"
        for item in leaves:
            event = events_by_id[item.event_id]
            if event.event_hash != item.event_hash:
                return "EVENT_HASH_SNAPSHOT_MISMATCH"
            try:
                if compute_event_hash(event) != item.event_hash:
                    return "EVENT_HASH_MISMATCH"
            except (TypeError, ValueError):
                return "EVENT_HASH_MISMATCH"
        return None

    @staticmethod
    async def verify_database(
        db: AsyncSession,
        *,
        public_keys: Mapping[str, str],
        through_sequence: int | None = None,
        verify_event_chains: bool = False,
    ) -> dict[str, Any]:
        stmt = select(AuditMerkleBatch).order_by(AuditMerkleBatch.sequence_no.asc())
        if through_sequence is not None:
            stmt = stmt.where(AuditMerkleBatch.sequence_no <= through_sequence)
        batches = list((await db.execute(stmt)).scalars().all())
        expected_sequence = 1
        expected_previous: str | None = None
        checked_events = 0
        scopes: set[str] = set()
        for batch in batches:
            if batch.sequence_no != expected_sequence:
                return MerkleAuditService._invalid_verification(
                    "CHECKPOINT_SEQUENCE_BROKEN", len(batches), expected_sequence - 1, checked_events, batch.sequence_no
                )
            if batch.previous_checkpoint_hash != expected_previous:
                return MerkleAuditService._invalid_verification(
                    "CHECKPOINT_CHAIN_BROKEN", len(batches), expected_sequence - 1, checked_events, batch.sequence_no
                )
            reason = await MerkleAuditService._verify_batch(db, batch, public_keys)
            if reason:
                return MerkleAuditService._invalid_verification(
                    reason, len(batches), expected_sequence - 1, checked_events, batch.sequence_no
                )
            if verify_event_chains:
                scope_rows = await db.execute(
                    select(Event.integrity_scope)
                    .join(AuditMerkleLeaf, AuditMerkleLeaf.event_id == Event.id)
                    .where(AuditMerkleLeaf.batch_id == batch.id)
                )
                scopes.update(str(scope) for scope in scope_rows.scalars().all() if scope is not None)
            checked_events += batch.leaf_count
            expected_previous = batch.checkpoint_hash
            expected_sequence += 1

        if through_sequence is not None and (not batches or batches[-1].sequence_no != through_sequence):
            return MerkleAuditService._invalid_verification(
                "ANCHORED_CHECKPOINT_MISSING", len(batches), len(batches), checked_events, through_sequence
            )
        if verify_event_chains:
            for scope in sorted(scopes):
                rows = list(
                    (
                        await db.execute(
                            select(Event)
                            .where(Event.integrity_scope == scope)
                            .order_by(Event.created_at.asc(), Event.id.asc())
                        )
                    ).scalars().all()
                )
                if not EventIntegrityService.verify_events(scope, rows)["valid"]:
                    return MerkleAuditService._invalid_verification(
                        "EVENT_CHAIN_BROKEN", len(batches), len(batches), checked_events, None
                    )
        return {
            "valid": True,
            "reason_code": None,
            "batch_count": len(batches),
            "checked_batches": len(batches),
            "checked_events": checked_events,
            "latest_sequence": batches[-1].sequence_no if batches else None,
            "latest_checkpoint_hash": batches[-1].checkpoint_hash if batches else None,
        }

    @staticmethod
    def _invalid_verification(
        reason: str,
        batch_count: int,
        checked_batches: int,
        checked_events: int,
        broken_sequence: int | None,
    ) -> dict[str, Any]:
        return {
            "valid": False,
            "reason_code": reason,
            "batch_count": batch_count,
            "checked_batches": checked_batches,
            "checked_events": checked_events,
            "broken_sequence": broken_sequence,
            "latest_sequence": None,
            "latest_checkpoint_hash": None,
        }

    @staticmethod
    async def proof_for_event(
        db: AsyncSession,
        event_id: UUID,
        *,
        public_keys: Mapping[str, str],
    ) -> dict[str, Any]:
        row = (
            await db.execute(
                select(Event, AuditMerkleLeaf, AuditMerkleBatch)
                .join(AuditMerkleLeaf, AuditMerkleLeaf.event_id == Event.id)
                .join(AuditMerkleBatch, AuditMerkleBatch.id == AuditMerkleLeaf.batch_id)
                .where(Event.id == event_id)
            )
        ).one_or_none()
        if row is None:
            event_exists = (await db.execute(select(Event.id).where(Event.id == event_id))).scalar_one_or_none()
            if event_exists is None:
                raise MerkleIntegrityError("EVENT_NOT_FOUND", "audit event was not found")
            raise MerkleIntegrityError("MERKLE_NOT_CHECKPOINTED", "audit event has not been checkpointed")
        event, selected_leaf, batch = row
        if event.event_hash is None or compute_event_hash(event) != event.event_hash:
            raise MerkleIntegrityError("EVENT_HASH_MISMATCH", "current audit event hash verification failed")
        if selected_leaf.event_hash != event.event_hash or leaf_hash(selected_leaf.event_hash) != selected_leaf.leaf_hash:
            raise MerkleIntegrityError("LEAF_HASH_MISMATCH", "Merkle leaf snapshot does not match the event")

        chain_result = await MerkleAuditService.verify_database(
            db, public_keys=public_keys, through_sequence=batch.sequence_no
        )
        if not chain_result["valid"]:
            raise MerkleIntegrityError(str(chain_result["reason_code"]), "Merkle checkpoint verification failed")
        leaves = list(
            (
                await db.execute(
                    select(AuditMerkleLeaf)
                    .where(AuditMerkleLeaf.batch_id == batch.id)
                    .order_by(AuditMerkleLeaf.leaf_index.asc())
                )
            ).scalars().all()
        )
        proof = build_merkle_proof([item.leaf_hash for item in leaves], selected_leaf.leaf_index)
        bundle = {
            "proof_version": 1,
            "event_id": str(event.id),
            "event_hash": selected_leaf.event_hash,
            "leaf_hash": selected_leaf.leaf_hash,
            "batch_id": str(batch.id),
            "batch_sequence": batch.sequence_no,
            "leaf_index": selected_leaf.leaf_index,
            "leaf_count": batch.leaf_count,
            "merkle_root": batch.merkle_root,
            "siblings": list(proof.siblings),
            "checkpoint": checkpoint_payload(batch),
            "checkpoint_hash": batch.checkpoint_hash,
            "signature": batch.signature,
        }
        bundle["verification"] = {
            "valid": True,
            "event_hash_valid": True,
            "inclusion_proof_valid": True,
            "checkpoint_hash_valid": True,
            "signature_valid": True,
            "checkpoint_chain_valid": True,
            "reason_code": None,
        }
        return bundle


def verify_proof_bundle(proof: Mapping[str, Any], public_keys: Mapping[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "valid": False,
        "event_hash_valid": False,
        "inclusion_proof_valid": False,
        "checkpoint_hash_valid": False,
        "signature_valid": False,
        "checkpoint_chain_valid": None,
        "reason_code": "PROOF_FORMAT_INVALID",
    }
    try:
        if not isinstance(proof, Mapping) or int(proof.get("proof_version", 0)) != 1:
            return result
        checkpoint_raw = proof.get("checkpoint")
        if not isinstance(checkpoint_raw, Mapping):
            return result
        canonical = checkpoint_payload(checkpoint_raw)
        computed_checkpoint_hash = compute_checkpoint_hash(canonical)
        supplied_checkpoint_hash = str(proof.get("checkpoint_hash", ""))
        if computed_checkpoint_hash != supplied_checkpoint_hash:
            result["reason_code"] = "CHECKPOINT_HASH_MISMATCH"
            return result
        result["checkpoint_hash_valid"] = True

        signature_valid, signature_reason = verify_checkpoint_signature(
            supplied_checkpoint_hash,
            canonical["signing_key_id"],
            str(proof.get("signature", "")),
            public_keys,
        )
        if not signature_valid:
            result["reason_code"] = signature_reason
            return result
        result["signature_valid"] = True

        event_id = str(UUID(str(proof.get("event_id", ""))))
        event_hash_value = str(proof.get("event_hash", ""))
        supplied_leaf_hash = str(proof.get("leaf_hash", ""))
        if leaf_hash(event_hash_value) != supplied_leaf_hash:
            result["reason_code"] = "LEAF_HASH_MISMATCH"
            return result
        result["event_hash_valid"] = True

        leaf_index = int(proof.get("leaf_index", -1))
        leaf_count = int(proof.get("leaf_count", 0))
        batch_sequence = int(proof.get("batch_sequence", 0))
        merkle_root = str(proof.get("merkle_root", ""))
        if (
            canonical["leaf_count"] != leaf_count
            or canonical["sequence_no"] != batch_sequence
            or canonical["merkle_root"] != merkle_root
            or event_id == ""
        ):
            result["reason_code"] = "PROOF_CHECKPOINT_MISMATCH"
            return result
        siblings = proof.get("siblings")
        if not isinstance(siblings, list) or not verify_event_merkle_proof(
            event_hash_value,
            leaf_index=leaf_index,
            leaf_count=leaf_count,
            siblings=siblings,
            merkle_root=merkle_root,
        ):
            result["reason_code"] = "MERKLE_PROOF_INVALID"
            return result
        result["inclusion_proof_valid"] = True
        result["valid"] = True
        result["reason_code"] = None
        return result
    except (KeyError, TypeError, ValueError, MerkleIntegrityError):
        return result


def anchor_for_batch(batch: AuditMerkleBatch) -> dict[str, Any]:
    return {
        "anchor_version": 1,
        "sequence_no": batch.sequence_no,
        "checkpoint_hash": batch.checkpoint_hash,
        "merkle_root": batch.merkle_root,
        "previous_checkpoint_hash": batch.previous_checkpoint_hash,
        "created_at": _timestamp(batch.created_at),
        "signing_key_id": batch.signing_key_id,
        "signature": batch.signature,
    }


def verify_anchor_signature(anchor: Mapping[str, Any], public_keys: Mapping[str, str]) -> dict[str, Any]:
    try:
        if int(anchor.get("anchor_version", 0)) != 1 or int(anchor.get("sequence_no", 0)) < 1:
            raise ValueError
        checkpoint_hash_value = str(anchor.get("checkpoint_hash", ""))
        root = str(anchor.get("merkle_root", ""))
        previous = anchor.get("previous_checkpoint_hash")
        _timestamp(anchor.get("created_at"))
        if HASH_HEX_RE.fullmatch(root) is None:
            raise ValueError
        if previous is not None and HASH_HEX_RE.fullmatch(str(previous)) is None:
            raise ValueError
        valid, reason = verify_checkpoint_signature(
            checkpoint_hash_value,
            str(anchor.get("signing_key_id", "")),
            str(anchor.get("signature", "")),
            public_keys,
        )
        return {"valid": valid, "signature_valid": valid, "reason_code": reason}
    except (TypeError, ValueError, MerkleIntegrityError):
        return {"valid": False, "signature_valid": False, "reason_code": "ANCHOR_FORMAT_INVALID"}


async def verify_anchor_against_database(
    db: AsyncSession,
    anchor: Mapping[str, Any],
    public_keys: Mapping[str, str],
) -> dict[str, Any]:
    signature = verify_anchor_signature(anchor, public_keys)
    if not signature["valid"]:
        return signature
    sequence_no = int(anchor["sequence_no"])
    batch = (
        await db.execute(select(AuditMerkleBatch).where(AuditMerkleBatch.sequence_no == sequence_no))
    ).scalar_one_or_none()
    if batch is None:
        return {"valid": False, "signature_valid": True, "reason_code": "ANCHORED_CHECKPOINT_MISSING"}
    expected_anchor = anchor_for_batch(batch)
    if any(anchor.get(key) != value for key, value in expected_anchor.items()):
        return {"valid": False, "signature_valid": True, "reason_code": "ANCHOR_CHECKPOINT_MISMATCH"}
    chain = await MerkleAuditService.verify_database(
        db, public_keys=public_keys, through_sequence=sequence_no
    )
    return {
        "valid": bool(chain["valid"]),
        "signature_valid": True,
        "checkpoint_chain_valid": bool(chain["valid"]),
        "reason_code": chain.get("reason_code"),
        "sequence_no": sequence_no,
    }
