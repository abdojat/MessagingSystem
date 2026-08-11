"""Strict, chunked AES-256-GCM storage format for protected uploads.

The file header is authenticated separately and every plaintext chunk is an
independent AEAD frame. Callers can therefore upload, migrate, rotate, and
download with memory bounded by ``UPLOAD_ENCRYPTION_CHUNK_SIZE``.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Iterator
from uuid import UUID

import anyio
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import DATA_ENCRYPTION_KEY_ID_RE
from app.core.encryption import DataEncryptionKeyRing, get_data_encryption_key_ring
from app.core.errors import AppError

UPLOAD_ENCRYPTION_MAGIC = b"MSGUPENC"
UPLOAD_ENCRYPTION_VERSION = 1
UPLOAD_ENCRYPTION_CHUNK_SIZE = 64 * 1024
UPLOAD_ENCRYPTION_MAX_CHUNK_SIZE = 1024 * 1024
UPLOAD_ENCRYPTION_MAX_PLAINTEXT_SIZE = 1024 * 1024 * 1024 * 1024
UPLOAD_ENCRYPTION_TAG_SIZE = 16
UPLOAD_ENCRYPTION_NONCE_PREFIX_SIZE = 8
UPLOAD_ENCRYPTION_MAX_KEY_ID_SIZE = 64
UPLOAD_ENCRYPTION_HEADER_NONCE_COUNTER = 0xFFFFFFFF
UPLOAD_ENCRYPTION_MAX_CHUNK_COUNTER = 0xFFFFFFFE
_HEADER_PREFIX_SIZE = len(UPLOAD_ENCRYPTION_MAGIC) + 1 + 16 + 1
_HEADER_SUFFIX_WITHOUT_TAG_SIZE = 8 + 4 + UPLOAD_ENCRYPTION_NONCE_PREFIX_SIZE
_FRAME_HEADER_SIZE = 8
_CHUNK_AAD_DOMAIN = b"MessagingSystem/upload/v1/chunk\x00"


class UploadEncryptionError(Exception):
    """Base class for controlled encrypted-storage failures."""


class UploadFormatError(UploadEncryptionError):
    pass


class UploadIntegrityError(UploadEncryptionError):
    pass


class UploadKeyError(UploadEncryptionError):
    pass


@dataclass(frozen=True)
class UploadEncryptionHeader:
    upload_id: UUID
    key_id: str
    plaintext_size: int
    chunk_size: int
    nonce_prefix: bytes
    canonical_bytes: bytes
    header_tag: bytes

    @property
    def encoded(self) -> bytes:
        return self.canonical_bytes + self.header_tag

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(self.canonical_bytes).digest()


def _aesgcm_for_upload(ring: DataEncryptionKeyRing, key_id: str, upload_id: UUID) -> AESGCM:
    try:
        return AESGCM(ring.derive_upload_key(key_id, upload_id))
    except AppError as exc:
        raise UploadKeyError("referenced upload encryption key is unavailable") from exc


def _nonce(prefix: bytes, counter: int) -> bytes:
    if len(prefix) != UPLOAD_ENCRYPTION_NONCE_PREFIX_SIZE or not 0 <= counter <= 0xFFFFFFFF:
        raise UploadFormatError("invalid encrypted upload nonce")
    return prefix + struct.pack(">I", counter)


def _chunk_aad(header: UploadEncryptionHeader, index: int, plaintext_length: int) -> bytes:
    return _CHUNK_AAD_DOMAIN + header.digest + struct.pack(">II", index, plaintext_length)


def build_upload_encryption_header(
    upload_id: UUID,
    key_id: str,
    plaintext_size: int,
    *,
    chunk_size: int = UPLOAD_ENCRYPTION_CHUNK_SIZE,
    nonce_prefix: bytes | None = None,
    ring: DataEncryptionKeyRing | None = None,
) -> UploadEncryptionHeader:
    if not DATA_ENCRYPTION_KEY_ID_RE.fullmatch(key_id):
        raise UploadFormatError("invalid upload encryption key ID")
    if not 0 <= int(plaintext_size) <= UPLOAD_ENCRYPTION_MAX_PLAINTEXT_SIZE:
        raise UploadFormatError("invalid encrypted upload plaintext size")
    if chunk_size != UPLOAD_ENCRYPTION_CHUNK_SIZE or chunk_size > UPLOAD_ENCRYPTION_MAX_CHUNK_SIZE:
        raise UploadFormatError("unsupported encrypted upload chunk size")
    key_bytes = key_id.encode("ascii")
    if not 1 <= len(key_bytes) <= UPLOAD_ENCRYPTION_MAX_KEY_ID_SIZE:
        raise UploadFormatError("invalid upload encryption key ID")
    selected_nonce_prefix = nonce_prefix if nonce_prefix is not None else os.urandom(UPLOAD_ENCRYPTION_NONCE_PREFIX_SIZE)
    if len(selected_nonce_prefix) != UPLOAD_ENCRYPTION_NONCE_PREFIX_SIZE:
        raise UploadFormatError("invalid encrypted upload nonce prefix")

    canonical = b"".join(
        (
            UPLOAD_ENCRYPTION_MAGIC,
            struct.pack(">B", UPLOAD_ENCRYPTION_VERSION),
            upload_id.bytes,
            struct.pack(">B", len(key_bytes)),
            key_bytes,
            struct.pack(">QI", int(plaintext_size), chunk_size),
            selected_nonce_prefix,
        )
    )
    selected_ring = ring or get_data_encryption_key_ring()
    aesgcm = _aesgcm_for_upload(selected_ring, key_id, upload_id)
    tag = aesgcm.encrypt(
        _nonce(selected_nonce_prefix, UPLOAD_ENCRYPTION_HEADER_NONCE_COUNTER),
        b"",
        canonical,
    )
    if len(tag) != UPLOAD_ENCRYPTION_TAG_SIZE:
        raise UploadIntegrityError("invalid encrypted upload header authentication tag")
    return UploadEncryptionHeader(
        upload_id=upload_id,
        key_id=key_id,
        plaintext_size=int(plaintext_size),
        chunk_size=chunk_size,
        nonce_prefix=selected_nonce_prefix,
        canonical_bytes=canonical,
        header_tag=tag,
    )


def _parse_upload_encryption_header_bytes(
    encoded: bytes,
    *,
    expected_upload_id: UUID | None = None,
    expected_key_id: str | None = None,
    ring: DataEncryptionKeyRing | None = None,
) -> UploadEncryptionHeader:
    minimum = _HEADER_PREFIX_SIZE + 1 + _HEADER_SUFFIX_WITHOUT_TAG_SIZE + UPLOAD_ENCRYPTION_TAG_SIZE
    if not minimum <= len(encoded) <= minimum + UPLOAD_ENCRYPTION_MAX_KEY_ID_SIZE - 1:
        raise UploadFormatError("invalid encrypted upload header length")
    if encoded[: len(UPLOAD_ENCRYPTION_MAGIC)] != UPLOAD_ENCRYPTION_MAGIC:
        raise UploadFormatError("invalid encrypted upload magic")
    offset = len(UPLOAD_ENCRYPTION_MAGIC)
    version = encoded[offset]
    offset += 1
    if version != UPLOAD_ENCRYPTION_VERSION:
        raise UploadFormatError("unsupported encrypted upload version")
    upload_id = UUID(bytes=encoded[offset : offset + 16])
    offset += 16
    key_id_length = encoded[offset]
    offset += 1
    if not 1 <= key_id_length <= UPLOAD_ENCRYPTION_MAX_KEY_ID_SIZE:
        raise UploadFormatError("invalid encrypted upload key ID length")
    expected_total = _HEADER_PREFIX_SIZE + key_id_length + _HEADER_SUFFIX_WITHOUT_TAG_SIZE + UPLOAD_ENCRYPTION_TAG_SIZE
    if len(encoded) != expected_total:
        raise UploadFormatError("invalid encrypted upload header length")
    try:
        key_id = encoded[offset : offset + key_id_length].decode("ascii")
    except UnicodeDecodeError as exc:
        raise UploadFormatError("invalid encrypted upload key ID") from exc
    offset += key_id_length
    if not DATA_ENCRYPTION_KEY_ID_RE.fullmatch(key_id):
        raise UploadFormatError("invalid encrypted upload key ID")
    plaintext_size, chunk_size = struct.unpack(">QI", encoded[offset : offset + 12])
    offset += 12
    if plaintext_size > UPLOAD_ENCRYPTION_MAX_PLAINTEXT_SIZE:
        raise UploadFormatError("encrypted upload plaintext size exceeds format bound")
    if chunk_size != UPLOAD_ENCRYPTION_CHUNK_SIZE or chunk_size > UPLOAD_ENCRYPTION_MAX_CHUNK_SIZE:
        raise UploadFormatError("unsupported encrypted upload chunk size")
    nonce_prefix = encoded[offset : offset + UPLOAD_ENCRYPTION_NONCE_PREFIX_SIZE]
    offset += UPLOAD_ENCRYPTION_NONCE_PREFIX_SIZE
    canonical = encoded[:offset]
    tag = encoded[offset : offset + UPLOAD_ENCRYPTION_TAG_SIZE]

    if expected_upload_id is not None and upload_id != expected_upload_id:
        raise UploadIntegrityError("encrypted upload UUID does not match its database record")
    if expected_key_id is not None and key_id != expected_key_id:
        raise UploadIntegrityError("encrypted upload key ID does not match its database record")
    selected_ring = ring or get_data_encryption_key_ring()
    aesgcm = _aesgcm_for_upload(selected_ring, key_id, upload_id)
    try:
        plaintext = aesgcm.decrypt(
            _nonce(nonce_prefix, UPLOAD_ENCRYPTION_HEADER_NONCE_COUNTER),
            tag,
            canonical,
        )
    except InvalidTag as exc:
        raise UploadIntegrityError("encrypted upload header authentication failed") from exc
    if plaintext != b"":
        raise UploadIntegrityError("invalid encrypted upload header authentication result")
    return UploadEncryptionHeader(
        upload_id=upload_id,
        key_id=key_id,
        plaintext_size=plaintext_size,
        chunk_size=chunk_size,
        nonce_prefix=nonce_prefix,
        canonical_bytes=canonical,
        header_tag=tag,
    )


def _read_exact(source: BinaryIO, length: int) -> bytes:
    data = source.read(length)
    if len(data) != length:
        raise UploadFormatError("truncated encrypted upload")
    return data


def read_upload_encryption_header(
    source: BinaryIO,
    *,
    expected_upload_id: UUID | None = None,
    expected_key_id: str | None = None,
    ring: DataEncryptionKeyRing | None = None,
) -> UploadEncryptionHeader:
    prefix = _read_exact(source, _HEADER_PREFIX_SIZE)
    key_id_length = prefix[-1]
    if not 1 <= key_id_length <= UPLOAD_ENCRYPTION_MAX_KEY_ID_SIZE:
        raise UploadFormatError("invalid encrypted upload key ID length")
    remainder = _read_exact(
        source,
        key_id_length + _HEADER_SUFFIX_WITHOUT_TAG_SIZE + UPLOAD_ENCRYPTION_TAG_SIZE,
    )
    return _parse_upload_encryption_header_bytes(
        prefix + remainder,
        expected_upload_id=expected_upload_id,
        expected_key_id=expected_key_id,
        ring=ring,
    )


def read_upload_encryption_header_from_path(
    path: Path,
    *,
    expected_upload_id: UUID | None = None,
    expected_key_id: str | None = None,
    ring: DataEncryptionKeyRing | None = None,
) -> UploadEncryptionHeader:
    try:
        with path.open("rb") as source:
            return read_upload_encryption_header(
                source,
                expected_upload_id=expected_upload_id,
                expected_key_id=expected_key_id,
                ring=ring,
            )
    except FileNotFoundError:
        raise
    except UploadEncryptionError:
        raise
    except OSError as exc:
        raise UploadFormatError("unable to read encrypted upload header") from exc


def file_has_encrypted_upload_magic(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            return source.read(len(UPLOAD_ENCRYPTION_MAGIC)) == UPLOAD_ENCRYPTION_MAGIC
    except OSError:
        return False


class UploadChunkEncryptor:
    def __init__(
        self,
        upload_id: UUID,
        key_id: str,
        plaintext_size: int,
        *,
        ring: DataEncryptionKeyRing | None = None,
    ) -> None:
        self._ring = ring or get_data_encryption_key_ring()
        self.header = build_upload_encryption_header(
            upload_id,
            key_id,
            plaintext_size,
            ring=self._ring,
        )
        self._aesgcm = _aesgcm_for_upload(self._ring, key_id, upload_id)
        self._next_index = 0
        self._total_plaintext = 0

    def encrypt_chunk(self, plaintext: bytes | bytearray | memoryview) -> bytes:
        chunk = bytes(plaintext)
        if not chunk or len(chunk) > self.header.chunk_size:
            raise UploadFormatError("invalid plaintext upload chunk length")
        if self._next_index > UPLOAD_ENCRYPTION_MAX_CHUNK_COUNTER:
            raise UploadFormatError("encrypted upload chunk counter overflow")
        if self._total_plaintext + len(chunk) > self.header.plaintext_size:
            raise UploadFormatError("plaintext upload exceeds declared size")
        index = self._next_index
        ciphertext = self._aesgcm.encrypt(
            _nonce(self.header.nonce_prefix, index),
            chunk,
            _chunk_aad(self.header, index, len(chunk)),
        )
        self._next_index += 1
        self._total_plaintext += len(chunk)
        return struct.pack(">II", index, len(chunk)) + ciphertext

    def finalize(self) -> None:
        if self._total_plaintext != self.header.plaintext_size:
            raise UploadFormatError("plaintext upload does not match declared size")


def _iter_decrypted_frames(source: BinaryIO, header: UploadEncryptionHeader, ring: DataEncryptionKeyRing) -> Iterator[bytes]:
    aesgcm = _aesgcm_for_upload(ring, header.key_id, header.upload_id)
    remaining = header.plaintext_size
    expected_index = 0
    while remaining:
        if expected_index > UPLOAD_ENCRYPTION_MAX_CHUNK_COUNTER:
            raise UploadFormatError("encrypted upload chunk counter overflow")
        frame_header = _read_exact(source, _FRAME_HEADER_SIZE)
        index, plaintext_length = struct.unpack(">II", frame_header)
        expected_length = min(header.chunk_size, remaining)
        if index != expected_index or plaintext_length != expected_length:
            raise UploadFormatError("invalid encrypted upload frame ordering or length")
        ciphertext = _read_exact(source, plaintext_length + UPLOAD_ENCRYPTION_TAG_SIZE)
        try:
            plaintext = aesgcm.decrypt(
                _nonce(header.nonce_prefix, index),
                ciphertext,
                _chunk_aad(header, index, plaintext_length),
            )
        except InvalidTag as exc:
            raise UploadIntegrityError("encrypted upload chunk authentication failed") from exc
        if len(plaintext) != plaintext_length:
            raise UploadIntegrityError("invalid encrypted upload plaintext length")
        yield plaintext
        remaining -= plaintext_length
        expected_index += 1
    if source.read(1):
        raise UploadFormatError("encrypted upload contains trailing data")


def iter_decrypted_upload_file(
    path: Path,
    *,
    expected_upload_id: UUID,
    expected_key_id: str | None = None,
    expected_plaintext_size: int | None = None,
    ring: DataEncryptionKeyRing | None = None,
) -> Iterator[bytes]:
    selected_ring = ring or get_data_encryption_key_ring()
    with path.open("rb") as source:
        header = read_upload_encryption_header(
            source,
            expected_upload_id=expected_upload_id,
            expected_key_id=expected_key_id,
            ring=selected_ring,
        )
        if expected_plaintext_size is not None and header.plaintext_size != expected_plaintext_size:
            raise UploadIntegrityError("encrypted upload size does not match its database record")
        yield from _iter_decrypted_frames(source, header, selected_ring)


def validate_encrypted_upload_file(
    path: Path,
    *,
    expected_upload_id: UUID,
    expected_key_id: str | None = None,
    expected_plaintext_size: int | None = None,
    expected_checksum: str | None = None,
    ring: DataEncryptionKeyRing | None = None,
) -> tuple[UploadEncryptionHeader, str]:
    selected_ring = ring or get_data_encryption_key_ring()
    with path.open("rb") as source:
        header = read_upload_encryption_header(
            source,
            expected_upload_id=expected_upload_id,
            expected_key_id=expected_key_id,
            ring=selected_ring,
        )
        if expected_plaintext_size is not None and header.plaintext_size != expected_plaintext_size:
            raise UploadIntegrityError("encrypted upload size does not match its database record")
        digest = hashlib.sha256()
        total = 0
        for chunk in _iter_decrypted_frames(source, header, selected_ring):
            digest.update(chunk)
            total += len(chunk)
        if total != header.plaintext_size:
            raise UploadIntegrityError("encrypted upload plaintext length mismatch")
        checksum = digest.hexdigest()
        if expected_checksum and checksum.lower() != expected_checksum.strip().lower():
            raise UploadIntegrityError("encrypted upload checksum does not match its database record")
        return header, checksum


def encrypt_plaintext_file(
    source_path: Path,
    destination_path: Path,
    *,
    upload_id: UUID,
    key_id: str,
    plaintext_size: int,
    expected_checksum: str | None = None,
    ring: DataEncryptionKeyRing | None = None,
) -> str:
    selected_ring = ring or get_data_encryption_key_ring()
    encryptor = UploadChunkEncryptor(upload_id, key_id, plaintext_size, ring=selected_ring)
    digest = hashlib.sha256()
    total = 0
    with source_path.open("rb") as source, destination_path.open("xb") as destination:
        destination.write(encryptor.header.encoded)
        while True:
            chunk = source.read(encryptor.header.chunk_size)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
            destination.write(encryptor.encrypt_chunk(chunk))
        encryptor.finalize()
        destination.flush()
        os.fsync(destination.fileno())
    if total != plaintext_size:
        raise UploadIntegrityError("plaintext upload size does not match its database record")
    checksum = digest.hexdigest()
    if expected_checksum and checksum.lower() != expected_checksum.strip().lower():
        raise UploadIntegrityError("plaintext upload checksum does not match its database record")
    return checksum


def reencrypt_upload_file(
    source_path: Path,
    destination_path: Path,
    *,
    upload_id: UUID,
    source_key_id: str | None,
    target_key_id: str,
    plaintext_size: int,
    expected_checksum: str | None = None,
    ring: DataEncryptionKeyRing | None = None,
) -> str:
    selected_ring = ring or get_data_encryption_key_ring()
    encryptor = UploadChunkEncryptor(upload_id, target_key_id, plaintext_size, ring=selected_ring)
    digest = hashlib.sha256()
    total = 0
    with destination_path.open("xb") as destination:
        destination.write(encryptor.header.encoded)
        for chunk in iter_decrypted_upload_file(
            source_path,
            expected_upload_id=upload_id,
            expected_key_id=source_key_id,
            expected_plaintext_size=plaintext_size,
            ring=selected_ring,
        ):
            total += len(chunk)
            digest.update(chunk)
            destination.write(encryptor.encrypt_chunk(chunk))
        encryptor.finalize()
        destination.flush()
        os.fsync(destination.fileno())
    if total != plaintext_size:
        raise UploadIntegrityError("rotated upload plaintext length mismatch")
    checksum = digest.hexdigest()
    if expected_checksum and checksum.lower() != expected_checksum.strip().lower():
        raise UploadIntegrityError("rotated upload checksum mismatch")
    return checksum


async def _read_exact_async(source: anyio.AsyncFile, length: int) -> bytes:
    data = await source.read(length)
    if len(data) != length:
        raise UploadFormatError("truncated encrypted upload")
    return data


async def _read_upload_encryption_header_async(
    source: anyio.AsyncFile,
    *,
    expected_upload_id: UUID,
    expected_key_id: str | None,
    ring: DataEncryptionKeyRing,
) -> UploadEncryptionHeader:
    prefix = await _read_exact_async(source, _HEADER_PREFIX_SIZE)
    key_id_length = prefix[-1]
    if not 1 <= key_id_length <= UPLOAD_ENCRYPTION_MAX_KEY_ID_SIZE:
        raise UploadFormatError("invalid encrypted upload key ID length")
    remainder = await _read_exact_async(
        source,
        key_id_length + _HEADER_SUFFIX_WITHOUT_TAG_SIZE + UPLOAD_ENCRYPTION_TAG_SIZE,
    )
    return _parse_upload_encryption_header_bytes(
        prefix + remainder,
        expected_upload_id=expected_upload_id,
        expected_key_id=expected_key_id,
        ring=ring,
    )


async def iter_decrypted_upload_async(
    path: Path,
    *,
    expected_upload_id: UUID,
    expected_key_id: str | None,
    expected_plaintext_size: int,
) -> AsyncIterator[bytes]:
    ring = get_data_encryption_key_ring()
    async with await anyio.open_file(path, "rb") as source:
        header = await _read_upload_encryption_header_async(
            source,
            expected_upload_id=expected_upload_id,
            expected_key_id=expected_key_id,
            ring=ring,
        )
        if header.plaintext_size != expected_plaintext_size:
            raise UploadIntegrityError("encrypted upload size does not match its database record")
        aesgcm = _aesgcm_for_upload(ring, header.key_id, header.upload_id)
        remaining = header.plaintext_size
        expected_index = 0
        while remaining:
            frame_header = await _read_exact_async(source, _FRAME_HEADER_SIZE)
            index, plaintext_length = struct.unpack(">II", frame_header)
            expected_length = min(header.chunk_size, remaining)
            if index != expected_index or plaintext_length != expected_length:
                raise UploadFormatError("invalid encrypted upload frame ordering or length")
            ciphertext = await _read_exact_async(source, plaintext_length + UPLOAD_ENCRYPTION_TAG_SIZE)
            try:
                plaintext = aesgcm.decrypt(
                    _nonce(header.nonce_prefix, index),
                    ciphertext,
                    _chunk_aad(header, index, plaintext_length),
                )
            except InvalidTag as exc:
                raise UploadIntegrityError("encrypted upload chunk authentication failed") from exc
            yield plaintext
            remaining -= plaintext_length
            expected_index += 1
        if await source.read(1):
            raise UploadFormatError("encrypted upload contains trailing data")
