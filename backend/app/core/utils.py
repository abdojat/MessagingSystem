import hashlib
import secrets
from datetime import datetime, timezone


# Returns the current UTC timestamp; the application layers use it as shared infrastructure.
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Computes the SHA-256 hash of hex; the application layers use it as shared infrastructure.
def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# Creates invite token; the application layers use it as shared infrastructure.
def make_invite_token() -> str:
    return secrets.token_urlsafe(32)
