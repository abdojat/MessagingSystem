import re

from app.core.errors import AppError

SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9_-]{3,50}$"
SAFE_IDENTIFIER_RE = re.compile(SAFE_IDENTIFIER_PATTERN)
SAFE_IDENTIFIER_MAX_LENGTH = 50


def _normalize_identifier(value: str, *, field: str, lowercase: bool = False) -> str:
    normalized = value.strip()
    if lowercase:
        normalized = normalized.lower()
    if not SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise AppError(
            f"{field} must match {SAFE_IDENTIFIER_PATTERN}",
            400,
            code="VALIDATION_ERROR",
            details={"field": field},
        )
    return normalized


def validate_username(value: str) -> str:
    normalized = value.strip()
    if not SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"username must match {SAFE_IDENTIFIER_PATTERN}")
    return normalized


def validate_channel_slug(value: str) -> str:
    normalized = value.strip().lower()
    if not SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"channel_slug must match {SAFE_IDENTIFIER_PATTERN}")
    return normalized


def normalize_username(value: str) -> str:
    return _normalize_identifier(value, field="username")


def normalize_channel_slug(value: str) -> str:
    return _normalize_identifier(value, field="channel_slug", lowercase=True)
