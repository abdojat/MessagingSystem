"""Supervisor-facing live demonstration of signed Merkle audit integrity.

Run inside the backend image or with the backend package on ``PYTHONPATH``.
The signing seed must be supplied only to this explicit process.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT if (BACKEND_ROOT / "app").is_dir() else PROJECT_ROOT))

from app.core.config import parse_audit_merkle_public_keys
from app.services.event_service import log_event
from app.services.merkle_audit_service import MerkleAuditService, MerkleIntegrityError, verify_proof_bundle


async def run() -> None:
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/channels"
    )
    key_id = os.environ.get("AUDIT_MERKLE_SIGNING_KEY_ID", "").strip()
    private_key = os.environ.get("AUDIT_MERKLE_SIGNING_PRIVATE_KEY", "").strip()
    public_keys = parse_audit_merkle_public_keys(os.environ.get("AUDIT_MERKLE_PUBLIC_KEYS", ""))
    if not key_id or not private_key:
        raise MerkleIntegrityError(
            "SIGNING_KEY_CONFIG_INVALID",
            "the demo requires the explicit Merkle checkpoint signing environment",
        )

    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as db:
            run_id = str(uuid4())
            events = []
            for index in range(16):
                events.append(
                    await log_event(
                        db,
                        "audit.merkle_demo",
                        {"demo_run_id": run_id, "position": index},
                    )
                )
            await db.commit()
            selected_event_id = events[6].id

            created_count = 0
            while True:
                batch = await MerkleAuditService.create_checkpoint(
                    db,
                    max_leaves=256,
                    signing_key_id=key_id,
                    private_key_base64=private_key,
                    public_keys=public_keys,
                )
                if batch is None:
                    await db.rollback()
                    break
                created_count += batch.leaf_count
                await db.commit()

            proof = await MerkleAuditService.proof_for_event(db, selected_event_id, public_keys=public_keys)
            verification = verify_proof_bundle(proof, public_keys)
            tampered = copy.deepcopy(proof)
            if tampered["siblings"]:
                tampered["siblings"][0]["hash"] = hashlib.sha256(b"tampered-proof-copy").hexdigest()
            else:
                tampered["event_hash"] = hashlib.sha256(b"tampered-event-copy").hexdigest()
            tampered_verification = verify_proof_bundle(tampered, public_keys)

            print(f"Audit events checkpointed this run: {created_count}")
            print(f"Checkpoint sequence: {proof['batch_sequence']}")
            print(f"Batch leaf count: {proof['leaf_count']}")
            print(f"Merkle root: {proof['merkle_root']}")
            print(f"Signing key ID: {proof['checkpoint']['signing_key_id']}")
            print(f"Selected event: {proof['event_id']}")
            print(f"Leaf index: {proof['leaf_index']}")
            print(f"Proof sibling count: {len(proof['siblings'])}")
            print(f"Event hash:              {'PASS' if proof['verification']['event_hash_valid'] else 'FAIL'}")
            print(f"Merkle inclusion:        {'PASS' if verification['inclusion_proof_valid'] else 'FAIL'}")
            print(f"Checkpoint hash:         {'PASS' if verification['checkpoint_hash_valid'] else 'FAIL'}")
            print(f"Ed25519 signature:       {'PASS' if verification['signature_valid'] else 'FAIL'}")
            print(f"Checkpoint chain:        {'PASS' if proof['verification']['checkpoint_chain_valid'] else 'FAIL'}")
            print(
                "Tampered proof:           "
                + ("FAILED (expected)" if not tampered_verification["valid"] else "UNEXPECTED SUCCESS")
            )
            if not verification["valid"] or tampered_verification["valid"]:
                raise MerkleIntegrityError("DEMO_VERIFICATION_FAILED", "Merkle demonstration did not meet expectations")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (MerkleIntegrityError, OSError, ValueError, json.JSONDecodeError) as exc:
        code = exc.code if isinstance(exc, MerkleIntegrityError) else "DEMO_FAILED"
        raise SystemExit(f"Merkle demo failed [{code}]: {exc}") from None
