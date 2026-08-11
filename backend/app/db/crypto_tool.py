"""Bounded, restartable Phase 9 data-encryption maintenance commands.

Examples (run from ``backend`` or the backend container):

    python -m app.db.crypto_tool status
    python -m app.db.crypto_tool migrate-messages
    python -m app.db.crypto_tool migrate-uploads
    python -m app.db.crypto_tool rotate-messages --to-key-id key-2026-08
    python -m app.db.crypto_tool rotate-uploads --to-key-id key-2026-08

The command prints counts only. It never emits plaintext, ciphertext, names,
tokens, or key material.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.encryption import (
    decrypt_json_payload,
    decrypt_message,
    encrypt_json_payload_with_key,
    encrypt_message_with_key,
    get_data_encryption_key_ring,
    inspect_json_message_format,
    inspect_text_message_format,
)
from app.core.errors import AppError
from app.core.upload_encryption import (
    UploadEncryptionError,
    encrypt_plaintext_file,
    file_has_encrypted_upload_magic,
    read_upload_encryption_header_from_path,
    reencrypt_upload_file,
    validate_encrypted_upload_file,
)
from app.db.models import ContentType, Message, Upload


@dataclass
class CryptoStatus:
    message_formats: Counter[str] = field(default_factory=Counter)
    message_unreadable: int = 0
    upload_formats: Counter[str] = field(default_factory=Counter)
    upload_missing_files: int = 0
    upload_invalid: int = 0
    upload_metadata_mismatch: int = 0


@asynccontextmanager
async def _maintenance_session():
    """Own and dispose an engine inside the command's current event loop."""

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


def _resolve_upload_path(base_dir_value: str, storage_path: str) -> Path:
    base_dir = Path(base_dir_value).resolve()
    full_path = (base_dir / storage_path).resolve()
    try:
        full_path.relative_to(base_dir)
    except ValueError as exc:
        raise RuntimeError("upload storage path escapes the configured base directory") from exc
    return full_path


def _message_format(message: Message):
    if message.content_type == ContentType.text:
        return inspect_text_message_format(message.content_text)
    if message.content_type == ContentType.json:
        return inspect_json_message_format(message.content_json)
    return None


def _decrypt_message_storage(message: Message) -> tuple[str | None, dict | None]:
    if message.content_type == ContentType.text:
        if message.content_text is None:
            raise AppError("missing persisted text message", 500, code="DECRYPTION_FAILED")
        return decrypt_message(message.content_text), None
    if message.content_type == ContentType.json:
        if message.content_json is None:
            raise AppError("missing persisted json message", 500, code="DECRYPTION_FAILED")
        return None, decrypt_json_payload(message.content_json)
    raise AppError("unsupported persisted message type", 500, code="DECRYPTION_FAILED")


async def collect_status(batch_size: int = 250) -> CryptoStatus:
    status = CryptoStatus()
    settings = get_settings()
    async with _maintenance_session() as db:
        cursor: UUID | None = None
        while True:
            stmt = select(Message).order_by(Message.id).limit(batch_size)
            if cursor is not None:
                stmt = stmt.where(Message.id > cursor)
            rows = list((await db.execute(stmt)).scalars().all())
            if not rows:
                break
            for message in rows:
                storage_format = _message_format(message)
                if storage_format is None:
                    status.message_formats["unknown"] += 1
                    status.message_unreadable += 1
                    continue
                label = f"v2 {storage_format.key_id}" if storage_format.kind == "v2" else storage_format.kind
                status.message_formats[label] += 1
                try:
                    _decrypt_message_storage(message)
                except AppError:
                    status.message_unreadable += 1
            cursor = rows[-1].id

        cursor = None
        while True:
            stmt = select(Upload).order_by(Upload.id).limit(batch_size)
            if cursor is not None:
                stmt = stmt.where(Upload.id > cursor)
            rows = list((await db.execute(stmt)).scalars().all())
            if not rows:
                break
            for upload in rows:
                path = _resolve_upload_path(settings.uploads_base_dir, upload.storage_path)
                if not path.exists():
                    if upload.public_url:
                        status.upload_missing_files += 1
                    else:
                        status.upload_formats["pending/no file"] += 1
                    continue
                encrypted = int(upload.storage_encryption_version or 0) == 1 or file_has_encrypted_upload_magic(path)
                if not encrypted:
                    status.upload_formats["plaintext"] += 1
                    continue
                try:
                    header, _ = validate_encrypted_upload_file(
                        path,
                        expected_upload_id=upload.id,
                        expected_plaintext_size=int(upload.size_bytes),
                        expected_checksum=upload.checksum,
                    )
                    status.upload_formats[f"encrypted-v1 {header.key_id}"] += 1
                    if int(upload.storage_encryption_version or 0) != 1 or upload.storage_key_id != header.key_id:
                        status.upload_metadata_mismatch += 1
                except (UploadEncryptionError, OSError):
                    status.upload_invalid += 1
            cursor = rows[-1].id
    return status


def _print_status(status: CryptoStatus) -> None:
    print("Messages:")
    for label in sorted(label for label in status.message_formats if label.startswith("v2 ")):
        print(f"  {label}: {status.message_formats[label]}")
    print(f"  legacy-v1: {status.message_formats['legacy-v1']}")
    print(f"  plaintext: {status.message_formats['plaintext']}")
    print(f"  unknown format: {status.message_formats['unknown']}")
    print(f"  unreadable/unknown: {status.message_unreadable}")
    print("Uploads:")
    for label in sorted(label for label in status.upload_formats if label.startswith("encrypted-v1 ")):
        print(f"  {label}: {status.upload_formats[label]}")
    print(f"  plaintext: {status.upload_formats['plaintext']}")
    print(f"  pending/no file: {status.upload_formats['pending/no file']}")
    print(f"  missing file: {status.upload_missing_files}")
    print(f"  invalid format: {status.upload_invalid}")
    print(f"  metadata mismatch: {status.upload_metadata_mismatch}")


def _require_target_key(target_key_id: str | None) -> str:
    ring = get_data_encryption_key_ring()
    target = target_key_id or ring.active_key_id
    ring.master_key(target, for_encryption=True)
    if target != ring.active_key_id:
        raise RuntimeError("rotation target must match DATA_ENCRYPTION_ACTIVE_KEY_ID")
    return target


async def migrate_messages(*, batch_size: int = 100, target_key_id: str | None = None, rotate_v2: bool = False) -> Counter[str]:
    target = _require_target_key(target_key_id)
    counts: Counter[str] = Counter()
    async with _maintenance_session() as db:
        cursor: UUID | None = None
        while True:
            # Do not combine a forward-only UUID cursor with SKIP LOCKED: a
            # concurrently locked lower-ID row could otherwise be skipped for
            # the remainder of this invocation. Maintenance waits for the row
            # lock, then advances only after the complete batch commits.
            stmt = select(Message).order_by(Message.id).limit(batch_size).with_for_update()
            if cursor is not None:
                stmt = stmt.where(Message.id > cursor)
            rows = list((await db.execute(stmt)).scalars().all())
            if not rows:
                break
            for message in rows:
                storage_format = _message_format(message)
                if storage_format is None or storage_format.kind == "unknown":
                    raise RuntimeError("an unreadable message storage format prevents migration")
                if storage_format.kind == "v2" and (not rotate_v2 or storage_format.key_id == target):
                    counts["unchanged"] += 1
                    continue
                plaintext, json_payload = _decrypt_message_storage(message)
                if message.content_type == ContentType.text:
                    message.content_text = encrypt_message_with_key(plaintext or "", target)
                else:
                    if json_payload is None:
                        raise RuntimeError("decrypted JSON message is missing")
                    message.content_json = encrypt_json_payload_with_key(json_payload, target)
                counts["reencrypted"] += 1
            await db.commit()
            cursor = rows[-1].id
    return counts


def _temporary_sibling(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid4()}.phase9")


async def migrate_uploads(*, batch_size: int = 25, target_key_id: str | None = None, rotate_v1: bool = False) -> Counter[str]:
    target = _require_target_key(target_key_id)
    settings = get_settings()
    counts: Counter[str] = Counter()
    async with _maintenance_session() as db:
        cursor: UUID | None = None
        while True:
            stmt = select(Upload).order_by(Upload.id).limit(batch_size).with_for_update()
            if cursor is not None:
                stmt = stmt.where(Upload.id > cursor)
            rows = list((await db.execute(stmt)).scalars().all())
            if not rows:
                break
            for upload in rows:
                path = _resolve_upload_path(settings.uploads_base_dir, upload.storage_path)
                if not path.exists():
                    if upload.public_url:
                        raise RuntimeError("a finalized upload file is missing")
                    counts["pending_missing"] += 1
                    continue

                encrypted = file_has_encrypted_upload_magic(path)
                if int(upload.storage_encryption_version or 0) == 1 and not encrypted:
                    raise RuntimeError("encrypted upload metadata references a non-encrypted file")

                if encrypted:
                    header, _ = validate_encrypted_upload_file(
                        path,
                        expected_upload_id=upload.id,
                        expected_plaintext_size=int(upload.size_bytes),
                        expected_checksum=upload.checksum,
                    )
                    if rotate_v1 and header.key_id != target:
                        temp_path = _temporary_sibling(path)
                        try:
                            reencrypt_upload_file(
                                path,
                                temp_path,
                                upload_id=upload.id,
                                source_key_id=header.key_id,
                                target_key_id=target,
                                plaintext_size=int(upload.size_bytes),
                                expected_checksum=upload.checksum,
                            )
                            os.replace(temp_path, path)
                        finally:
                            temp_path.unlink(missing_ok=True)
                        upload.storage_key_id = target
                        counts["reencrypted"] += 1
                    else:
                        # Repairs both migration and rotation crash windows where
                        # the authenticated file changed before DB commit.
                        upload.storage_key_id = header.key_id
                        counts["metadata_repaired" if int(upload.storage_encryption_version or 0) != 1 else "unchanged"] += 1
                    upload.storage_encryption_version = 1
                    continue

                if not settings.allow_legacy_plaintext_uploads:
                    raise RuntimeError("plaintext upload migration compatibility is disabled")
                temp_path = _temporary_sibling(path)
                try:
                    encrypt_plaintext_file(
                        path,
                        temp_path,
                        upload_id=upload.id,
                        key_id=target,
                        plaintext_size=int(upload.size_bytes),
                        expected_checksum=upload.checksum,
                    )
                    # The encrypted temp is fsynced before atomic replacement.
                    # Physical remanence/backups are outside this operation.
                    os.replace(temp_path, path)
                finally:
                    temp_path.unlink(missing_ok=True)
                upload.storage_encryption_version = 1
                upload.storage_key_id = target
                counts["encrypted"] += 1
            await db.commit()
            cursor = rows[-1].id
    return counts


def _print_operation(label: str, counts: Counter[str]) -> None:
    print(f"{label}:")
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect, migrate, and rotate encrypted application storage")
    subcommands = parser.add_subparsers(dest="command", required=True)

    status = subcommands.add_parser("status")
    status.add_argument("--batch-size", type=int, default=250)

    migrate_messages_parser = subcommands.add_parser("migrate-messages")
    migrate_messages_parser.add_argument("--batch-size", type=int, default=100)

    migrate_uploads_parser = subcommands.add_parser("migrate-uploads")
    migrate_uploads_parser.add_argument("--batch-size", type=int, default=25)

    rotate_messages_parser = subcommands.add_parser("rotate-messages")
    rotate_messages_parser.add_argument("--to-key-id", required=True)
    rotate_messages_parser.add_argument("--batch-size", type=int, default=100)

    rotate_uploads_parser = subcommands.add_parser("rotate-uploads")
    rotate_uploads_parser.add_argument("--to-key-id", required=True)
    rotate_uploads_parser.add_argument("--batch-size", type=int, default=25)
    return parser


async def _run(args: argparse.Namespace) -> None:
    if not 1 <= int(args.batch_size) <= 1000:
        raise RuntimeError("batch size must be between 1 and 1000")
    if args.command == "status":
        _print_status(await collect_status(args.batch_size))
    elif args.command == "migrate-messages":
        _print_operation("Messages", await migrate_messages(batch_size=args.batch_size))
    elif args.command == "migrate-uploads":
        _print_operation("Uploads", await migrate_uploads(batch_size=args.batch_size))
    elif args.command == "rotate-messages":
        _print_operation(
            "Messages",
            await migrate_messages(batch_size=args.batch_size, target_key_id=args.to_key_id, rotate_v2=True),
        )
    elif args.command == "rotate-uploads":
        _print_operation(
            "Uploads",
            await migrate_uploads(batch_size=args.batch_size, target_key_id=args.to_key_id, rotate_v1=True),
        )


def main() -> None:
    args = _parser().parse_args()
    try:
        asyncio.run(_run(args))
    except (AppError, UploadEncryptionError, RuntimeError, OSError) as exc:
        # Deliberately bounded: none of these messages contain key values,
        # plaintext, ciphertext, filenames, or storage paths.
        raise SystemExit(f"crypto operation failed: {exc}") from None


if __name__ == "__main__":
    main()
