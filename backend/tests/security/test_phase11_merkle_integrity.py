import copy
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user, get_db, get_redis
from app.api.routes import admin
from app.core.config import get_settings
from app.core.config import Settings
from app.db.models import AuditMerkleBatch, AuditMerkleLeaf, Event, User
from app.services.event_service import log_event
from app.services.merkle_audit_service import (
    MerkleAuditService,
    MerkleIntegrityError,
    anchor_for_batch,
    checkpoint_payload,
    compute_checkpoint_hash,
    generate_ed25519_keypair,
    sign_checkpoint_hash,
    validate_signing_configuration,
    verify_anchor_against_database,
    verify_checkpoint_signature,
    verify_proof_bundle,
)
from app.services.merkle_service import (
    build_merkle_proof,
    build_merkle_root,
    leaf_hash,
    parent_hash,
    verify_merkle_proof,
)


def _event_hashes(count: int) -> list[str]:
    return [hashlib.sha256(f"event-{index}".encode()).hexdigest() for index in range(count)]


def _tree(count: int):
    events = _event_hashes(count)
    leaves = [leaf_hash(value) for value in events]
    return events, leaves, build_merkle_root(leaves)


@pytest.fixture
def merkle_keys(monkeypatch):
    private_key, public_key = generate_ed25519_keypair()
    key_id = "audit-test"
    public_keys = {key_id: public_key}
    monkeypatch.setenv("AUDIT_MERKLE_VERIFICATION_ENABLED", "true")
    monkeypatch.setenv("AUDIT_MERKLE_PUBLIC_KEYS", json.dumps(public_keys))
    get_settings.cache_clear()
    return key_id, private_key, public_keys


async def _events(db: AsyncSession, count: int, *, prefix: str = "phase11") -> list[Event]:
    result = []
    for index in range(count):
        result.append(await log_event(db, f"{prefix}.{index}", {"index": index}))
    await db.commit()
    return result


async def _checkpoint(db: AsyncSession, keys, *, max_leaves: int = 256):
    key_id, private_key, public_keys = keys
    batch = await MerkleAuditService.create_checkpoint(
        db,
        max_leaves=max_leaves,
        signing_key_id=key_id,
        private_key_base64=private_key,
        public_keys=public_keys,
    )
    await db.commit()
    return batch


# Pure Merkle algorithm


def test_one_leaf_root_and_empty_proof():
    _, leaves, root = _tree(1)
    proof = build_merkle_proof(leaves, 0)
    assert root == leaves[0]
    assert proof.siblings == ()
    assert verify_merkle_proof(leaves[0], leaf_index=0, leaf_count=1, siblings=[], merkle_root=root)


def test_two_leaf_root_and_both_proofs():
    _, leaves, root = _tree(2)
    assert root == parent_hash(leaves[0], leaves[1])
    for index in range(2):
        proof = build_merkle_proof(leaves, index)
        assert verify_merkle_proof(
            leaves[index], leaf_index=index, leaf_count=2, siblings=proof.siblings, merkle_root=root
        )


def test_three_leaf_tree_promotes_unpaired_node_unchanged():
    _, leaves, root = _tree(3)
    assert root == parent_hash(parent_hash(leaves[0], leaves[1]), leaves[2])
    assert len(build_merkle_proof(leaves, 2).siblings) == 1
    for index in range(3):
        proof = build_merkle_proof(leaves, index)
        assert verify_merkle_proof(
            leaves[index], leaf_index=index, leaf_count=3, siblings=proof.siblings, merkle_root=root
        )


@pytest.mark.parametrize("count", [4, 5, 7, 9, 1025])
def test_balanced_odd_and_large_tree_proofs(count):
    _, leaves, root = _tree(count)
    for index in {0, count // 2, count - 1}:
        proof = build_merkle_proof(leaves, index)
        assert len(proof.siblings) <= 64
        assert verify_merkle_proof(
            leaves[index], leaf_index=index, leaf_count=count, siblings=proof.siblings, merkle_root=root
        )


@pytest.mark.parametrize("mutation", ["leaf", "sibling", "side", "root", "index", "count"])
def test_proof_tampering_and_wrong_position_fail(mutation):
    _, leaves, root = _tree(7)
    index = 3
    proof = build_merkle_proof(leaves, index)
    leaf_value = leaves[index]
    siblings = [dict(item) for item in proof.siblings]
    leaf_index = index
    leaf_count = 7
    expected_root = root
    replacement = hashlib.sha256(b"tampered").hexdigest()
    if mutation == "leaf":
        leaf_value = replacement
    elif mutation == "sibling":
        siblings[0]["hash"] = replacement
    elif mutation == "side":
        siblings[0]["side"] = "right" if siblings[0]["side"] == "left" else "left"
    elif mutation == "root":
        expected_root = replacement
    elif mutation == "index":
        leaf_index = 2
    else:
        # A count with a different promoted-node shape must reject this path.
        # The signed checkpoint separately binds the exact real leaf count.
        leaf_count = 4
    assert not verify_merkle_proof(
        leaf_value,
        leaf_index=leaf_index,
        leaf_count=leaf_count,
        siblings=siblings,
        merkle_root=expected_root,
    )


@pytest.mark.parametrize("malformed", ["", "0" * 63, "g" * 64, "A" * 64])
def test_malformed_hashes_are_rejected(malformed):
    with pytest.raises(ValueError):
        leaf_hash(malformed)
    with pytest.raises(ValueError):
        build_merkle_root([malformed])


# Checkpoint canonicalization and signatures


def _checkpoint_metadata(key_id: str) -> dict:
    values = _event_hashes(2)
    leaves = [leaf_hash(value) for value in values]
    return {
        "checkpoint_version": 1,
        "sequence_no": 1,
        "merkle_version": 1,
        "hash_algorithm": "sha256",
        "leaf_count": 2,
        "first_event_id": str(uuid4()),
        "last_event_id": str(uuid4()),
        "first_event_hash": values[0],
        "last_event_hash": values[1],
        "merkle_root": build_merkle_root(leaves),
        "previous_checkpoint_hash": None,
        "signing_key_id": key_id,
        "created_at": datetime(2026, 8, 11, 12, 30, tzinfo=timezone.utc),
    }


def test_valid_signature_and_canonical_checkpoint_are_stable(merkle_keys):
    key_id, private_key, public_keys = merkle_keys
    metadata = _checkpoint_metadata(key_id)
    checkpoint_hash = compute_checkpoint_hash(metadata)
    reordered = dict(reversed(list(metadata.items())))
    signature = sign_checkpoint_hash(checkpoint_hash, private_key)
    assert compute_checkpoint_hash(reordered) == checkpoint_hash
    assert verify_checkpoint_signature(checkpoint_hash, key_id, signature, public_keys) == (True, None)


@pytest.mark.parametrize("field", ["merkle_root", "leaf_count", "previous_checkpoint_hash"])
def test_signed_checkpoint_metadata_tampering_fails(field, merkle_keys):
    key_id, private_key, public_keys = merkle_keys
    metadata = _checkpoint_metadata(key_id)
    original_hash = compute_checkpoint_hash(metadata)
    signature = sign_checkpoint_hash(original_hash, private_key)
    changed = dict(metadata)
    if field == "merkle_root":
        changed[field] = hashlib.sha256(b"different-root").hexdigest()
    elif field == "leaf_count":
        changed[field] = 1
    else:
        changed[field] = hashlib.sha256(b"previous").hexdigest()
    changed_hash = compute_checkpoint_hash(changed)
    assert changed_hash != original_hash
    assert verify_checkpoint_signature(changed_hash, key_id, signature, public_keys)[0] is False


def test_unknown_wrong_and_mismatched_signing_keys_fail(merkle_keys):
    key_id, private_key, public_keys = merkle_keys
    metadata = _checkpoint_metadata(key_id)
    checkpoint_hash = compute_checkpoint_hash(metadata)
    signature = sign_checkpoint_hash(checkpoint_hash, private_key)
    assert verify_checkpoint_signature(checkpoint_hash, "unknown", signature, public_keys)[1] == "UNKNOWN_SIGNING_KEY"
    _, wrong_public = generate_ed25519_keypair()
    assert verify_checkpoint_signature(checkpoint_hash, key_id, signature, {key_id: wrong_public})[1] == "SIGNATURE_INVALID"
    wrong_private, _ = generate_ed25519_keypair()
    with pytest.raises(MerkleIntegrityError, match="does not match"):
        validate_signing_configuration(key_id, wrong_private, public_keys)


def test_historical_signature_remains_valid_after_key_rotation(merkle_keys):
    old_id, old_private, old_ring = merkle_keys
    new_private, new_public = generate_ed25519_keypair()
    metadata = _checkpoint_metadata(old_id)
    checkpoint_hash = compute_checkpoint_hash(metadata)
    signature = sign_checkpoint_hash(checkpoint_hash, old_private)
    rotated_ring = {**old_ring, "audit-next": new_public}
    validate_signing_configuration("audit-next", new_private, rotated_ring)
    assert verify_checkpoint_signature(checkpoint_hash, old_id, signature, rotated_ring)[0] is True


def test_production_verification_requires_a_trusted_public_key():
    with pytest.raises(ValueError, match="AUDIT_MERKLE_PUBLIC_KEYS"):
        Settings(
            environment="production",
            jwt_secret="phase11-production-secret-with-enough-entropy-123456",
            trusted_hosts=["audit.example.com"],
            data_encryption_active_key_id="data-key",
            data_encryption_keys={
                "data-key": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
            },
            audit_merkle_verification_enabled=True,
            audit_merkle_public_keys={},
        )


def test_production_compose_isolates_private_signing_key_from_runtime_services():
    compose_path = __import__("pathlib").Path(__file__).resolve().parents[3] / "docker-compose.production.yml"
    compose = compose_path.read_text(encoding="utf-8")
    before_checkpoint, checkpoint_service = compose.split("  merkle-checkpoint:", 1)
    worker_section = before_checkpoint.split("  worker:", 1)[1].split("  frontend:", 1)[0]
    backend_section = before_checkpoint.split("  backend:", 1)[1].split("  worker:", 1)[0]
    assert "AUDIT_MERKLE_SIGNING_PRIVATE_KEY" not in before_checkpoint
    assert "AUDIT_MERKLE_SIGNING_PRIVATE_KEY" in checkpoint_service
    assert "AUDIT_MERKLE" not in worker_section
    assert "AUDIT_MERKLE_SIGNING_PRIVATE_KEY" not in backend_section


# Checkpoint persistence, proofs, tampering, anchors, and concurrency


@pytest.mark.asyncio
async def test_checkpoint_persists_unique_ordered_leaf_snapshots_and_is_idempotent(db_session, merkle_keys):
    events = await _events(db_session, 5)
    batch = await _checkpoint(db_session, merkle_keys)
    assert batch.sequence_no == 1
    assert batch.leaf_count == 5
    leaves = list(
        (
            await db_session.execute(
                select(AuditMerkleLeaf).order_by(AuditMerkleLeaf.leaf_index.asc())
            )
        ).scalars().all()
    )
    assert [item.event_id for item in leaves] == [item.id for item in events]
    assert [item.leaf_index for item in leaves] == list(range(5))
    assert len({item.event_id for item in leaves}) == 5
    assert await _checkpoint(db_session, merkle_keys) is None
    assert len((await db_session.execute(select(AuditMerkleBatch))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_new_batch_links_previous_checkpoint_and_database_verifies(db_session, merkle_keys):
    await _events(db_session, 2, prefix="first")
    first = await _checkpoint(db_session, merkle_keys)
    await _events(db_session, 2, prefix="second")
    second = await _checkpoint(db_session, merkle_keys)
    result = await MerkleAuditService.verify_database(db_session, public_keys=merkle_keys[2], verify_event_chains=True)
    assert second.sequence_no == 2
    assert second.previous_checkpoint_hash == first.checkpoint_hash
    assert result["valid"] is True
    assert result["checked_events"] == 4


@pytest.mark.asyncio
async def test_proof_export_verifies_offline_and_tampered_copies_fail(db_session, merkle_keys):
    events = await _events(db_session, 9)
    await _checkpoint(db_session, merkle_keys)
    proof = await MerkleAuditService.proof_for_event(db_session, events[6].id, public_keys=merkle_keys[2])
    assert verify_proof_bundle(proof, merkle_keys[2])["valid"] is True
    assert len(proof["siblings"]) == 4
    for mutate in ("event_hash", "sibling", "root", "signature"):
        changed = copy.deepcopy(proof)
        if mutate == "event_hash":
            changed["event_hash"] = hashlib.sha256(b"event change").hexdigest()
        elif mutate == "sibling":
            changed["siblings"][0]["hash"] = hashlib.sha256(b"sibling change").hexdigest()
        elif mutate == "root":
            changed["merkle_root"] = hashlib.sha256(b"root change").hexdigest()
        else:
            changed["signature"] = changed["signature"][:-2] + "AA"
        assert verify_proof_bundle(changed, merkle_keys[2])["valid"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["payload", "event_hash", "leaf_hash", "root", "signature"])
async def test_database_tampering_is_detected(db_session, merkle_keys, target):
    events = await _events(db_session, 3)
    batch = await _checkpoint(db_session, merkle_keys)
    middle_leaf = (
        await db_session.execute(
            select(AuditMerkleLeaf).where(AuditMerkleLeaf.batch_id == batch.id, AuditMerkleLeaf.leaf_index == 1)
        )
    ).scalar_one()
    replacement = hashlib.sha256(f"changed-{target}".encode()).hexdigest()
    if target == "payload":
        events[1].payload = {"index": 999}
    elif target == "event_hash":
        events[1].event_hash = replacement
    elif target == "leaf_hash":
        middle_leaf.leaf_hash = replacement
    elif target == "root":
        batch.merkle_root = replacement
    else:
        batch.signature = batch.signature[:-2] + "AA"
    await db_session.commit()
    result = await MerkleAuditService.verify_database(db_session, public_keys=merkle_keys[2])
    assert result["valid"] is False


@pytest.mark.asyncio
async def test_checkpoint_refuses_missing_integrity_and_signing_mismatch(db_session, merkle_keys):
    db_session.add(Event(event_type="legacy.event", payload={}))
    await db_session.commit()
    with pytest.raises(MerkleIntegrityError) as missing:
        await _checkpoint(db_session, merkle_keys)
    assert missing.value.code == "MISSING_INTEGRITY_METADATA"
    await db_session.rollback()
    wrong_private, _ = generate_ed25519_keypair()
    with pytest.raises(MerkleIntegrityError) as mismatch:
        await MerkleAuditService.create_checkpoint(
            db_session,
            max_leaves=256,
            signing_key_id=merkle_keys[0],
            private_key_base64=wrong_private,
            public_keys=merkle_keys[2],
        )
    assert mismatch.value.code == "SIGNING_KEY_MISMATCH"


@pytest.mark.asyncio
async def test_external_anchor_detects_checkpoint_deletion(db_session, merkle_keys):
    await _events(db_session, 3)
    batches = []
    for _ in range(3):
        batches.append(await _checkpoint(db_session, merkle_keys, max_leaves=1))
    anchor = anchor_for_batch(batches[-1])
    assert (await verify_anchor_against_database(db_session, anchor, merkle_keys[2]))["valid"] is True
    await db_session.execute(delete(AuditMerkleLeaf).where(AuditMerkleLeaf.batch_id == batches[-1].id))
    await db_session.execute(delete(AuditMerkleBatch).where(AuditMerkleBatch.id == batches[-1].id))
    await db_session.commit()
    rolled_back = await verify_anchor_against_database(db_session, anchor, merkle_keys[2])
    assert rolled_back["valid"] is False
    assert rolled_back["reason_code"] == "ANCHORED_CHECKPOINT_MISSING"


@pytest.mark.asyncio
async def test_two_checkpoint_jobs_serialize_without_overlap(db_session, merkle_keys):
    await _events(db_session, 8)
    database_url = db_session.get_bind().url.render_as_string(hide_password=False)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def run_one():
        async with sessions() as session:
            batch = await MerkleAuditService.create_checkpoint(
                session,
                max_leaves=256,
                signing_key_id=merkle_keys[0],
                private_key_base64=merkle_keys[1],
                public_keys=merkle_keys[2],
            )
            await session.commit()
            return None if batch is None else batch.id

    first, second = await __import__("asyncio").gather(run_one(), run_one())
    await engine.dispose()
    assert sorted(value is None for value in (first, second)) == [False, True]
    leaf_ids = list((await db_session.execute(select(AuditMerkleLeaf.event_id))).scalars().all())
    assert len(leaf_ids) == len(set(leaf_ids)) == 8


@pytest.mark.asyncio
async def test_event_commit_during_checkpoint_is_included_or_remains_pending_without_loss(
    db_session, merkle_keys, monkeypatch
):
    await _events(db_session, 4)
    database_url = db_session.get_bind().url.render_as_string(hide_password=False)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    locked = __import__("asyncio").Event()
    continue_checkpoint = __import__("asyncio").Event()
    original_lock = MerkleAuditService.lock_checkpoint

    async def paused_lock(db):
        await original_lock(db)
        locked.set()
        await continue_checkpoint.wait()

    monkeypatch.setattr(MerkleAuditService, "lock_checkpoint", paused_lock)

    async def run_checkpoint():
        async with sessions() as session:
            batch = await MerkleAuditService.create_checkpoint(
                session,
                max_leaves=256,
                signing_key_id=merkle_keys[0],
                private_key_base64=merkle_keys[1],
                public_keys=merkle_keys[2],
            )
            await session.commit()
            return batch

    task = __import__("asyncio").create_task(run_checkpoint())
    await locked.wait()
    async with sessions() as writer:
        late_event = await log_event(writer, "phase11.concurrent", {"late": True})
        await writer.commit()
    continue_checkpoint.set()
    await task
    monkeypatch.setattr(MerkleAuditService, "lock_checkpoint", original_lock)
    async with sessions() as check:
        checkpointed = (
            await check.execute(select(AuditMerkleLeaf.event_id).where(AuditMerkleLeaf.event_id == late_event.id))
        ).scalar_one_or_none()
        pending = (await MerkleAuditService.status(check, merkle_keys[2]))["pending_events"]
    await engine.dispose()
    assert checkpointed == late_event.id or pending == 1


# API authorization and safe read projection


@pytest.mark.asyncio
async def test_merkle_admin_status_requires_superadmin(db_session, merkle_keys, monkeypatch):
    normal_user = User(username="merkle_normal", password_hash="unused", is_superadmin=False)
    db_session.add(normal_user)
    await db_session.commit()
    app = FastAPI()
    app.include_router(admin.router, prefix="/v1")

    async def override_db():
        yield db_session

    async def override_user():
        return normal_user

    async def override_redis():
        return object()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_redis] = override_redis
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/admin/audit/merkle/status")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SUPERADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_merkle_admin_status_and_proof_expose_no_event_payload(db_session, merkle_keys, monkeypatch):
    admin_user = User(username="merkle_admin", password_hash="unused", is_superadmin=True)
    db_session.add(admin_user)
    await db_session.commit()
    events = await _events(db_session, 2)
    await _checkpoint(db_session, merkle_keys)

    async def no_rate_limit(*args, **kwargs):
        return None

    monkeypatch.setattr(admin, "enforce_rate_limit", no_rate_limit)
    status = await admin.merkle_status(db_session, admin_user, __import__("fastapi").Response(), object())
    proof = await admin.merkle_event_proof(
        events[0].id, db_session, admin_user, __import__("fastapi").Response(), object()
    )
    assert status.checkpoint_chain_valid is True
    serialized = proof.model_dump_json()
    assert "payload" not in serialized
    assert proof.verification.valid is True
