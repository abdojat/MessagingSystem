import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from app.core.errors import AppError

SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9_-]{3,50}$"
SAFE_IDENTIFIER_RE = re.compile(SAFE_IDENTIFIER_PATTERN)
SAFE_IDENTIFIER_MAX_LENGTH = 50
SAFE_UPLOAD_FILENAME_MAX_LENGTH = 100
UPLOAD_CONTENT_PATH_RE = re.compile(
    r"^/(?:v1/)?uploads/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/content$"
)


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


def normalize_upload_filename(value: str) -> str:
    """
    Convert a user-supplied filename into a safe storage-path component.

    The original filename is still preserved in the database for display, but the
    storage path must never contain path separators or traversal segments.
    """

    basename = Path(value).name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
    cleaned = cleaned.strip("._")
    if not cleaned:
        cleaned = "upload"
    return cleaned[:SAFE_UPLOAD_FILENAME_MAX_LENGTH]


def extract_upload_id_from_url(value: str | None) -> UUID | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    match = UPLOAD_CONTENT_PATH_RE.fullmatch(parsed.path)
    if not match:
        return None
    try:
        return UUID(match.group(1))
    except ValueError:
        return None


def normalize_avatar_url(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    if any(ch.isspace() or ord(ch) < 32 for ch in normalized):
        raise ValueError("avatar_url cannot contain whitespace or control characters")

    parsed = urlsplit(normalized)
    if parsed.scheme:
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError("avatar_url must use http, https, or a protected upload path")
        if not parsed.netloc:
            raise ValueError("avatar_url must include a host")
        return normalized

    if parsed.netloc or normalized.startswith("//"):
        raise ValueError("avatar_url must not be protocol-relative")

    if parsed.query or parsed.fragment:
        raise ValueError("protected upload avatar URLs cannot include query strings or fragments")

    if extract_upload_id_from_url(normalized) is None:
        raise ValueError("avatar_url must be an http(s) URL or /v1/uploads/{file_id}/content")

    return normalized
