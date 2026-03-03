import hashlib
import secrets
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_invite_token() -> str:
    return secrets.token_urlsafe(32)
