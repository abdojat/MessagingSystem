"""Operator tooling for Phase 11 signed Merkle audit checkpoints.

Run from ``backend`` or the backend image, for example:

    python -m app.db.merkle_tool status
    python -m app.db.merkle_tool checkpoint --all
    python -m app.db.merkle_tool verify
    python -m app.db.merkle_tool proof --event-id <uuid> --output event-proof.json
    python -m app.db.merkle_tool verify-proof --proof event-proof.json
    python -m app.db.merkle_tool export-anchor --output latest-audit-anchor.json
    python -m app.db.merkle_tool verify-anchor --file latest-audit-anchor.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import parse_audit_merkle_public_keys
from app.db.models import AuditMerkleBatch
from app.services.merkle_audit_service import (
    MAX_BATCH_SIZE,
    SIGNING_KEY_ID_RE,
    MerkleAuditService,
    MerkleIntegrityError,
    anchor_for_batch,
    generate_ed25519_keypair,
    verify_anchor_against_database,
    verify_anchor_signature,
    verify_proof_bundle,
)


DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@postgres:5432/channels"


@asynccontextmanager
async def _maintenance_session():
    engine = create_async_engine(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


def _public_keys() -> dict[str, str]:
    return parse_audit_merkle_public_keys(os.environ.get("AUDIT_MERKLE_PUBLIC_KEYS", ""))


def _signing_values() -> tuple[str, str, dict[str, str]]:
    key_id = os.environ.get("AUDIT_MERKLE_SIGNING_KEY_ID", "").strip()
    private_key = os.environ.get("AUDIT_MERKLE_SIGNING_PRIVATE_KEY", "").strip()
    if not private_key:
        raise MerkleIntegrityError(
            "SIGNING_KEY_CONFIG_INVALID", "AUDIT_MERKLE_SIGNING_PRIVATE_KEY is required for checkpoint creation"
        )
    return key_id, private_key, _public_keys()


def _load_json(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MerkleIntegrityError("JSON_INPUT_INVALID", f"cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise MerkleIntegrityError("JSON_INPUT_INVALID", "input JSON must be an object")
    return value


def _write_json(path_value: str, value: dict[str, Any], *, force: bool) -> None:
    path = Path(path_value)
    mode = "w" if force else "x"
    try:
        with path.open(mode, encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise MerkleIntegrityError(
            "OUTPUT_EXISTS", f"refusing to overwrite {path}; pass --force to replace it"
        ) from exc
    except OSError as exc:
        raise MerkleIntegrityError("OUTPUT_WRITE_FAILED", f"cannot write {path}") from exc


def _print_status(status: dict[str, Any]) -> None:
    print("Audit events:")
    print(f"  total: {status['total_events']}")
    print(f"  integrity-hashed: {status['integrity_hashed_events']}")
    print(f"  checkpointed: {status['checkpointed_events']}")
    print(f"  pending checkpoint: {status['pending_events']}")
    print(f"  missing integrity metadata: {status['missing_integrity_events']}")
    print("Merkle checkpoints:")
    print(f"  batches: {status['batch_count']}")
    print(f"  latest sequence: {status['latest_sequence'] or '-'}")
    print(f"  latest root: {status['latest_root'] or '-'}")
    latest_signature = status["latest_signature_valid"]
    print(f"  latest checkpoint signature: {'not available' if latest_signature is None else 'valid' if latest_signature else 'INVALID'}")
    print(f"  checkpoint chain: {'valid' if status['checkpoint_chain_valid'] else 'INVALID'}")
    if status.get("reason_code"):
        print(f"  failure reason: {status['reason_code']}")


async def _status() -> None:
    async with _maintenance_session() as db:
        _print_status(await MerkleAuditService.status(db, _public_keys()))


async def _checkpoint(args: argparse.Namespace) -> None:
    key_id, private_key, public_keys = _signing_values()
    created: list[AuditMerkleBatch] = []
    async with _maintenance_session() as db:
        while True:
            batch = await MerkleAuditService.create_checkpoint(
                db,
                max_leaves=args.max_leaves,
                signing_key_id=key_id,
                private_key_base64=private_key,
                public_keys=public_keys,
            )
            if batch is None:
                await db.rollback()
                break
            await db.commit()
            created.append(batch)
            print(
                f"created checkpoint #{batch.sequence_no}: leaves={batch.leaf_count} "
                f"root={batch.merkle_root}"
            )
            if not args.all:
                break
    if not created:
        print("no checkpoint created: no eligible uncheckpointed audit events")


async def _verify(args: argparse.Namespace) -> None:
    async with _maintenance_session() as db:
        result = await MerkleAuditService.verify_database(
            db,
            public_keys=_public_keys(),
            verify_event_chains=args.verify_event_chains,
        )
    print(json.dumps(result, sort_keys=True, indent=2))
    if not result["valid"]:
        raise MerkleIntegrityError(str(result["reason_code"]), "Merkle checkpoint verification failed")


async def _proof(args: argparse.Namespace) -> None:
    try:
        event_id = UUID(args.event_id)
    except ValueError as exc:
        raise MerkleIntegrityError("EVENT_ID_INVALID", "event ID must be a UUID") from exc
    async with _maintenance_session() as db:
        proof = await MerkleAuditService.proof_for_event(db, event_id, public_keys=_public_keys())
    if args.output:
        _write_json(args.output, proof, force=args.force)
        print(f"proof written: {args.output}")
    else:
        print(json.dumps(proof, sort_keys=True, indent=2))


def _verify_proof(args: argparse.Namespace) -> None:
    result = verify_proof_bundle(_load_json(args.proof), _public_keys())
    print(json.dumps(result, sort_keys=True, indent=2))
    if not result["valid"]:
        raise MerkleIntegrityError(str(result["reason_code"]), "offline Merkle proof verification failed")


async def _export_anchor(args: argparse.Namespace) -> None:
    async with _maintenance_session() as db:
        batch = (
            await db.execute(select(AuditMerkleBatch).order_by(AuditMerkleBatch.sequence_no.desc()).limit(1))
        ).scalar_one_or_none()
        if batch is None:
            raise MerkleIntegrityError("CHECKPOINT_NOT_FOUND", "no Merkle checkpoint exists to anchor")
        verification = await MerkleAuditService.verify_database(
            db, public_keys=_public_keys(), through_sequence=batch.sequence_no
        )
        if not verification["valid"]:
            raise MerkleIntegrityError(str(verification["reason_code"]), "refusing to export an invalid checkpoint")
        anchor = anchor_for_batch(batch)
    _write_json(args.output, anchor, force=args.force)
    print(f"anchor written: {args.output}")


async def _verify_anchor(args: argparse.Namespace) -> None:
    anchor = _load_json(args.file)
    public_keys = _public_keys()
    if args.offline:
        result = verify_anchor_signature(anchor, public_keys)
        result["database_history_checked"] = False
    else:
        async with _maintenance_session() as db:
            result = await verify_anchor_against_database(db, anchor, public_keys)
        result["database_history_checked"] = True
    print(json.dumps(result, sort_keys=True, indent=2))
    if not result["valid"]:
        raise MerkleIntegrityError(str(result["reason_code"]), "anchor verification failed")


def _generate_keypair(args: argparse.Namespace) -> None:
    if SIGNING_KEY_ID_RE.fullmatch(args.key_id or "") is None:
        raise MerkleIntegrityError("SIGNING_KEY_CONFIG_INVALID", "--key-id must match ^[A-Za-z0-9_-]{1,64}$")
    private_key, public_key = generate_ed25519_keypair()
    print("SECRET - store securely; supply only to the Merkle checkpoint process:")
    print(f"AUDIT_MERKLE_SIGNING_PRIVATE_KEY={private_key}")
    print("Public verifier key:")
    print(f'AUDIT_MERKLE_PUBLIC_KEYS={{"{args.key_id}":"{public_key}"}}')
    print(f"AUDIT_MERKLE_SIGNING_KEY_ID={args.key_id}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and verify signed Merkle audit checkpoints")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status")

    checkpoint = commands.add_parser("checkpoint")
    checkpoint.add_argument("--max-leaves", type=int, default=int(os.environ.get("AUDIT_MERKLE_BATCH_SIZE", "256")))
    checkpoint.add_argument("--all", action="store_true", help="checkpoint all eligible events in bounded batches")

    verify = commands.add_parser("verify")
    verify.add_argument("--verify-event-chains", action="store_true")

    proof = commands.add_parser("proof")
    proof.add_argument("--event-id", required=True)
    proof.add_argument("--output")
    proof.add_argument("--force", action="store_true")

    verify_proof = commands.add_parser("verify-proof")
    verify_proof.add_argument("--proof", required=True)

    export_anchor = commands.add_parser("export-anchor")
    export_anchor.add_argument("--output", required=True)
    export_anchor.add_argument("--force", action="store_true")

    verify_anchor = commands.add_parser("verify-anchor")
    verify_anchor.add_argument("--file", required=True)
    verify_anchor.add_argument("--offline", action="store_true", help="check only signature/trusted key, not database history")

    generate = commands.add_parser("generate-keypair")
    generate.add_argument("--key-id", default="audit-demo")
    return parser


async def _run(args: argparse.Namespace) -> None:
    if args.command == "status":
        await _status()
    elif args.command == "checkpoint":
        if not 1 <= int(args.max_leaves) <= MAX_BATCH_SIZE:
            raise MerkleIntegrityError("BATCH_SIZE_INVALID", "--max-leaves must be between 1 and 4096")
        await _checkpoint(args)
    elif args.command == "verify":
        await _verify(args)
    elif args.command == "proof":
        await _proof(args)
    elif args.command == "verify-proof":
        _verify_proof(args)
    elif args.command == "export-anchor":
        await _export_anchor(args)
    elif args.command == "verify-anchor":
        await _verify_anchor(args)
    elif args.command == "generate-keypair":
        _generate_keypair(args)


def main() -> None:
    args = _parser().parse_args()
    try:
        asyncio.run(_run(args))
    except (MerkleIntegrityError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, MerkleIntegrityError) else "OPERATION_FAILED"
        raise SystemExit(f"Merkle operation failed [{code}]: {exc}") from None


if __name__ == "__main__":
    main()
