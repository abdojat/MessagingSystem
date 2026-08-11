"""Versioned server-side message encryption and bounded data-key management."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import (
    DATA_ENCRYPTION_KEY_ID_RE,
    DEVELOPMENT_DATA_KEY_ID,
    get_settings,
)
from app.core.errors import AppError

logger = logging.getLogger(__name__)

MESSAGE_V2_PREFIX = "enc:v2:"
MESSAGE_V2_HKDF_INFO = b"MessagingSystem/message/v2"
UPLOAD_V1_HKDF_INFO = b"MessagingSystem/upload/v1"
LEGACY_JSON_FIELD = "_enc_v1"
V2_JSON_FIELD = "_enc_v2"
MAX_MESSAGE_TOKEN_LENGTH = 512 * 1024
_FERNET_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def _derive_dev_key() -> str:
    """Deprecated test hook retained while Phase 7 regression tests transition."""

    return base64.urlsafe_b64encode(b"\0" * 32).decode("ascii")


@dataclass(frozen=True)
class MessageStorageFormat:
    kind: str
    key_id: str | None = None


@dataclass(frozen=True)
class DataEncryptionKeyRing:
    active_key_id: str
    _keys: Mapping[str, bytes]

    @property
    def key_ids(self) -> tuple[str, ...]:
        return tuple(self._keys.keys())

    def master_key(self, key_id: str, *, for_encryption: bool = False) -> bytes:
        key = self._keys.get(key_id)
        if key is None:
            code = "ENCRYPTION_FAILED" if for_encryption else "DECRYPTION_FAILED"
            raise AppError("referenced data encryption key is unavailable", 500, code=code)
        return key

    def derive_message_key(self, key_id: str) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=MESSAGE_V2_HKDF_INFO,
        ).derive(self.master_key(key_id))

    def derive_upload_key(self, key_id: str, upload_id: UUID) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=upload_id.bytes,
            info=UPLOAD_V1_HKDF_INFO,
        ).derive(self.master_key(key_id))


def _decode_configured_master_key(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise AppError("invalid data encryption key configuration", 500, code="CONFIG_ERROR") from exc
    if len(decoded) != 32:
        raise AppError("invalid data encryption key configuration", 500, code="CONFIG_ERROR")
    return decoded


@lru_cache(maxsize=1)
def _build_key_ring() -> DataEncryptionKeyRing:
    settings = get_settings()
    raw_keys = settings.data_encryption_keys
    if not isinstance(raw_keys, dict) or not raw_keys:
        raise AppError("data encryption key ring is not configured", 500, code="CONFIG_ERROR")
    decoded = {str(key_id): _decode_configured_master_key(str(value)) for key_id, value in raw_keys.items()}
    active_key_id = settings.data_encryption_active_key_id
    if active_key_id not in decoded:
        raise AppError("active data encryption key is not configured", 500, code="CONFIG_ERROR")
    if active_key_id == DEVELOPMENT_DATA_KEY_ID:
        logger.warning("Using deterministic DEVELOPMENT data encryption key; never use it for deployment data.")
    return DataEncryptionKeyRing(active_key_id=active_key_id, _keys=MappingProxyType(decoded))


def get_data_encryption_key_ring() -> DataEncryptionKeyRing:
    return _build_key_ring()


@lru_cache(maxsize=64)
def _build_fernet(key_id: str | None = None) -> Fernet:
    """Build the domain-separated v2 Fernet primitive.

    The optional key ID keeps the old cache-clear test hook while allowing
    historical v2 keys to remain independently addressable.
    """

    ring = _build_key_ring()
    selected = key_id or ring.active_key_id
    derived = ring.derive_message_key(selected)
    return Fernet(base64.urlsafe_b64encode(derived))


@lru_cache(maxsize=1)
def _build_legacy_fernet() -> Fernet:
    key = get_settings().message_encryption_key.strip()
    if not key:
        raise AppError("legacy message decryption key is unavailable", 500, code="DECRYPTION_FAILED")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise AppError("legacy message decryption key is invalid", 500, code="DECRYPTION_FAILED") from exc


def _parse_v2_text_envelope(ciphertext: str) -> tuple[str, str] | None:
    if not ciphertext.startswith(MESSAGE_V2_PREFIX):
        return None
    parts = ciphertext.split(":", 3)
    if len(parts) != 4 or parts[0] != "enc" or parts[1] != "v2":
        raise AppError("invalid encrypted message envelope", 500, code="DECRYPTION_FAILED")
    key_id, token = parts[2], parts[3]
    if not DATA_ENCRYPTION_KEY_ID_RE.fullmatch(key_id) or not token or len(token) > MAX_MESSAGE_TOKEN_LENGTH:
        raise AppError("invalid encrypted message envelope", 500, code="DECRYPTION_FAILED")
    return key_id, token


def _looks_like_legacy_fernet_token(value: str) -> bool:
    if not value or len(value) > MAX_MESSAGE_TOKEN_LENGTH or not _FERNET_TOKEN_RE.fullmatch(value):
        return False
    try:
        decoded = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError):
        return False
    # Fernet's fixed version byte is 0x80. The remaining minimum is timestamp,
    # IV, one padded block, and HMAC; this recognizes only the legacy format.
    return len(decoded) >= 73 and decoded[0] == 0x80


def inspect_text_message_format(value: str | None) -> MessageStorageFormat:
    if value is None:
        return MessageStorageFormat("unknown")
    if value.startswith(MESSAGE_V2_PREFIX):
        try:
            key_id, _ = _parse_v2_text_envelope(value) or (None, None)
        except AppError:
            return MessageStorageFormat("unknown")
        return MessageStorageFormat("v2", key_id)
    if value.startswith("enc:"):
        return MessageStorageFormat("unknown")
    if _looks_like_legacy_fernet_token(value):
        return MessageStorageFormat("legacy-v1")
    return MessageStorageFormat("plaintext")


def _strict_v2_json_envelope(payload: dict[str, Any]) -> tuple[str, str] | None:
    if V2_JSON_FIELD not in payload:
        return None
    if set(payload) != {V2_JSON_FIELD}:
        raise AppError("invalid encrypted json envelope", 500, code="DECRYPTION_FAILED")
    envelope = payload[V2_JSON_FIELD]
    if not isinstance(envelope, dict) or set(envelope) != {"kid", "token"}:
        raise AppError("invalid encrypted json envelope", 500, code="DECRYPTION_FAILED")
    key_id = envelope.get("kid")
    token = envelope.get("token")
    if (
        not isinstance(key_id, str)
        or not DATA_ENCRYPTION_KEY_ID_RE.fullmatch(key_id)
        or not isinstance(token, str)
        or not token
        or len(token) > MAX_MESSAGE_TOKEN_LENGTH
    ):
        raise AppError("invalid encrypted json envelope", 500, code="DECRYPTION_FAILED")
    return key_id, token


def inspect_json_message_format(payload: dict[str, Any] | None) -> MessageStorageFormat:
    if not isinstance(payload, dict):
        return MessageStorageFormat("unknown")
    if V2_JSON_FIELD in payload:
        try:
            key_id, _ = _strict_v2_json_envelope(payload) or (None, None)
        except AppError:
            return MessageStorageFormat("unknown")
        return MessageStorageFormat("v2", key_id)
    if LEGACY_JSON_FIELD in payload:
        if set(payload) != {LEGACY_JSON_FIELD} or not isinstance(payload[LEGACY_JSON_FIELD], str):
            return MessageStorageFormat("unknown")
        if _looks_like_legacy_fernet_token(payload[LEGACY_JSON_FIELD]):
            return MessageStorageFormat("legacy-v1")
        return MessageStorageFormat("unknown")
    if any(str(key).startswith("_enc_") for key in payload):
        return MessageStorageFormat("unknown")
    return MessageStorageFormat("plaintext")


def encrypt_message_with_key(plaintext: str, key_id: str) -> str:
    if plaintext is None:
        raise AppError("cannot encrypt empty message", 400, code="VALIDATION_ERROR")
    ring = _build_key_ring()
    ring.master_key(key_id, for_encryption=True)
    try:
        token = _build_fernet(key_id).encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"{MESSAGE_V2_PREFIX}{key_id}:{token}"
    except AppError:
        raise
    except Exception as exc:
        raise AppError("failed to encrypt message", 500, code="ENCRYPTION_FAILED") from exc


def encrypt_message(plaintext: str) -> str:
    ring = _build_key_ring()
    return encrypt_message_with_key(plaintext, ring.active_key_id)


def _decrypt_v2_token(key_id: str, token: str) -> str:
    # Resolve exactly the declared key; trying historical keys in sequence would
    # make the key ID non-authoritative and obscure unknown-key failures.
    _build_key_ring().master_key(key_id)
    try:
        plaintext = _build_fernet(key_id).decrypt(token.encode("ascii"))
        return plaintext.decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise AppError("unable to decrypt message", 500, code="DECRYPTION_FAILED") from exc


def _decrypt_legacy_token(token: str) -> str:
    try:
        plaintext = _build_legacy_fernet().decrypt(token.encode("ascii"))
        return plaintext.decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise AppError("unable to decrypt legacy message", 500, code="DECRYPTION_FAILED") from exc


def decrypt_message(ciphertext: str) -> str:
    if ciphertext is None:
        raise AppError("ciphertext is missing", 500, code="DECRYPTION_FAILED")
    value = str(ciphertext)
    parsed = _parse_v2_text_envelope(value)
    if parsed is not None:
        return _decrypt_v2_token(*parsed)
    if value.startswith("enc:"):
        raise AppError("unknown encrypted message format", 500, code="DECRYPTION_FAILED")
    if _looks_like_legacy_fernet_token(value):
        return _decrypt_legacy_token(value)
    if get_settings().allow_legacy_plaintext_messages:
        return value
    raise AppError("plaintext message storage is not permitted", 500, code="DECRYPTION_FAILED")


def encrypt_json_payload_with_key(payload: dict[str, Any], key_id: str) -> dict[str, dict[str, str]]:
    serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    ring = _build_key_ring()
    ring.master_key(key_id, for_encryption=True)
    try:
        token = _build_fernet(key_id).encrypt(serialized.encode("utf-8")).decode("ascii")
    except AppError:
        raise
    except Exception as exc:
        raise AppError("failed to encrypt message", 500, code="ENCRYPTION_FAILED") from exc
    return {V2_JSON_FIELD: {"kid": key_id, "token": token}}


def encrypt_json_payload(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    ring = _build_key_ring()
    return encrypt_json_payload_with_key(payload, ring.active_key_id)


def decrypt_json_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise AppError("invalid encrypted json payload", 500, code="DECRYPTION_FAILED")

    parsed = _strict_v2_json_envelope(payload)
    if parsed is not None:
        raw = _decrypt_v2_token(*parsed)
    elif LEGACY_JSON_FIELD in payload:
        if set(payload) != {LEGACY_JSON_FIELD} or not isinstance(payload[LEGACY_JSON_FIELD], str):
            raise AppError("invalid legacy encrypted json envelope", 500, code="DECRYPTION_FAILED")
        token = payload[LEGACY_JSON_FIELD]
        if not _looks_like_legacy_fernet_token(token):
            raise AppError("invalid legacy encrypted json envelope", 500, code="DECRYPTION_FAILED")
        raw = _decrypt_legacy_token(token)
    else:
        if any(str(key).startswith("_enc_") for key in payload):
            raise AppError("unknown encrypted json format", 500, code="DECRYPTION_FAILED")
        if get_settings().allow_legacy_plaintext_messages:
            return payload
        raise AppError("plaintext json message storage is not permitted", 500, code="DECRYPTION_FAILED")

    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AppError("invalid decrypted json payload", 500, code="DECRYPTION_FAILED") from exc
    if not isinstance(loaded, dict):
        raise AppError("invalid decrypted json payload", 500, code="DECRYPTION_FAILED")
    return loaded
