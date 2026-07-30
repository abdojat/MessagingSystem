import base64
import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

DEV_FALLBACK_SEED = "dev-only-message-encryption-key"


# Implements the derive dev key operation; the application layers use it as shared infrastructure.
def _derive_dev_key() -> str:
    digest = hashlib.sha256(DEV_FALLBACK_SEED.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8")


# Builds fernet; the application layers use it as shared infrastructure.
@lru_cache(maxsize=1)
def _build_fernet() -> Fernet:
    settings = get_settings()
    enabled = bool(settings.message_encryption_enabled)
    key = settings.message_encryption_key.strip() if settings.message_encryption_key else ""
    env = settings.environment.lower().strip()
    is_dev_like = env in {"dev", "development", "local", "test"}

    # Reject the operation when `not enabled` to keep invalid state from progressing.
    if not enabled:
        raise AppError("message encryption is disabled", 500, code="CONFIG_ERROR")

    # Run this conditional step only when `not key` is true.
    if not key:
        # Reject the operation when `not is_dev_like` to keep invalid state from progressing.
        if not is_dev_like:
            raise AppError("missing MESSAGE_ENCRYPTION_KEY", 500, code="CONFIG_ERROR")
        key = _derive_dev_key()
        logger.warning("Using development fallback message encryption key. Do not use this in production.")
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return Fernet(key.encode("utf-8"))
    # Handle `Exception` here so this workflow can recover or report the failure consistently.
    except Exception as exc:
        raise AppError("invalid MESSAGE_ENCRYPTION_KEY", 500, code="CONFIG_ERROR") from exc


# Encrypts message; the application layers use it as shared infrastructure.
def encrypt_message(plaintext: str) -> str:
    # Reject the operation when `plaintext is None` to keep invalid state from progressing.
    if plaintext is None:
        raise AppError("cannot encrypt empty message", 400, code="VALIDATION_ERROR")
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        token = _build_fernet().encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError:
        raise
    # Handle `Exception` here so this workflow can recover or report the failure consistently.
    except Exception as exc:
        raise AppError("failed to encrypt message", 500, code="ENCRYPTION_FAILED") from exc


# Decrypts message; the application layers use it as shared infrastructure.
def decrypt_message(ciphertext: str) -> str:
    # Reject the operation when `ciphertext is None` to keep invalid state from progressing.
    if ciphertext is None:
        raise AppError("ciphertext is missing", 500, code="DECRYPTION_FAILED")
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        plain = _build_fernet().decrypt(ciphertext.encode("utf-8"))
        return plain.decode("utf-8")
    # Handle `InvalidToken` here so this workflow can recover or report the failure consistently.
    except InvalidToken as exc:
        # Return early when `not str(ciphertext).startswith('gAAAA')` because the remaining work is not applicable.
        if not str(ciphertext).startswith("gAAAA"):
            # Backward compatibility for legacy plaintext rows created before encryption rollout.
            return str(ciphertext)
        raise AppError("unable to decrypt message", 500, code="DECRYPTION_FAILED") from exc
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError:
        raise
    # Handle `Exception` here so this workflow can recover or report the failure consistently.
    except Exception as exc:
        raise AppError("unable to decrypt message", 500, code="DECRYPTION_FAILED") from exc


# Encrypts json payload; the application layers use it as shared infrastructure.
def encrypt_json_payload(payload: dict[str, Any]) -> dict[str, str]:
    serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return {"_enc_v1": encrypt_message(serialized)}


# Decrypts json payload; the application layers use it as shared infrastructure.
def decrypt_json_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    # Return early when `payload is None` because the remaining work is not applicable.
    if payload is None:
        return None
    token = payload.get("_enc_v1") if isinstance(payload, dict) else None
    # Return early when `not token` because the remaining work is not applicable.
    if not token:
        return payload if isinstance(payload, dict) else None
    raw = decrypt_message(str(token))
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        loaded = json.loads(raw)
    # Handle `json.JSONDecodeError` here so this workflow can recover or report the failure consistently.
    except json.JSONDecodeError as exc:
        raise AppError("invalid decrypted json payload", 500, code="DECRYPTION_FAILED") from exc
    # Reject the operation when `not isinstance(loaded, dict)` to keep invalid state from progressing.
    if not isinstance(loaded, dict):
        raise AppError("invalid decrypted json payload", 500, code="DECRYPTION_FAILED")
    return loaded
