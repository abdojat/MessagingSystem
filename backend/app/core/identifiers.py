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


# Normalizes identifier; the application layers use it as shared infrastructure.
def _normalize_identifier(value: str, *, field: str, lowercase: bool = False) -> str:
    normalized = value.strip()
    # Run this conditional step only when `lowercase` is true.
    if lowercase:
        normalized = normalized.lower()
    # Reject the operation when `not SAFE_IDENTIFIER_RE.fullmatch(normalized)` to keep invalid state from progressing.
    if not SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise AppError(
            f"{field} must match {SAFE_IDENTIFIER_PATTERN}",
            400,
            code="VALIDATION_ERROR",
            details={"field": field},
        )
    return normalized


# Validates username; the application layers use it as shared infrastructure.
def validate_username(value: str) -> str:
    normalized = value.strip()
    # Reject the operation when `not SAFE_IDENTIFIER_RE.fullmatch(normalized)` to keep invalid state from progressing.
    if not SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"username must match {SAFE_IDENTIFIER_PATTERN}")
    return normalized


# Validates channel slug; the application layers use it as shared infrastructure.
def validate_channel_slug(value: str) -> str:
    normalized = value.strip().lower()
    # Reject the operation when `not SAFE_IDENTIFIER_RE.fullmatch(normalized)` to keep invalid state from progressing.
    if not SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"channel_slug must match {SAFE_IDENTIFIER_PATTERN}")
    return normalized


# Normalizes username; the application layers use it as shared infrastructure.
def normalize_username(value: str) -> str:
    return _normalize_identifier(value, field="username")


# Normalizes channel slug; the application layers use it as shared infrastructure.
def normalize_channel_slug(value: str) -> str:
    return _normalize_identifier(value, field="channel_slug", lowercase=True)


# Normalizes upload filename; the application layers use it as shared infrastructure.
def normalize_upload_filename(value: str) -> str:
    """
    Convert a user-supplied filename into a safe storage-path component.

    The original filename is still preserved in the database for display, but the
    storage path must never contain path separators or traversal segments.
    """

    basename = Path(value).name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
    cleaned = cleaned.strip("._")
    # Run this conditional step only when `not cleaned` is true.
    if not cleaned:
        cleaned = "upload"
    return cleaned[:SAFE_UPLOAD_FILENAME_MAX_LENGTH]


# Extracts upload id from url; the application layers use it as shared infrastructure.
def extract_upload_id_from_url(value: str | None) -> UUID | None:
    # Return early when `not value` because the remaining work is not applicable.
    if not value:
        return None
    parsed = urlsplit(value.strip())
    match = UPLOAD_CONTENT_PATH_RE.fullmatch(parsed.path)
    # Return early when `not match` because the remaining work is not applicable.
    if not match:
        return None
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return UUID(match.group(1))
    # Handle `ValueError` here so this workflow can recover or report the failure consistently.
    except ValueError:
        return None


# Normalizes profile image url; the application layers use it as shared infrastructure.
def normalize_profile_image_url(value: str | None, *, field_name: str = "image_url") -> str | None:
    # Return early when `value is None` because the remaining work is not applicable.
    if value is None:
        return None

    normalized = value.strip()
    # Return early when `not normalized` because the remaining work is not applicable.
    if not normalized:
        return None

    # Reject the operation when `any((ch.isspace() or ord(ch) < 32 for ch in normalized))` to keep invalid state from progressing.
    if any(ch.isspace() or ord(ch) < 32 for ch in normalized):
        raise ValueError(f"{field_name} cannot contain whitespace or control characters")

    parsed = urlsplit(normalized)
    # Run this conditional step only when `parsed.scheme` is true.
    if parsed.scheme:
        # Reject the operation when `parsed.scheme.lower() not in {'http', 'https'}` to keep invalid state from progressing.
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError(f"{field_name} must use http, https, or a protected upload path")
        # Reject the operation when `not parsed.netloc` to keep invalid state from progressing.
        if not parsed.netloc:
            raise ValueError(f"{field_name} must include a host")
        return normalized

    # Reject the operation when `parsed.netloc or normalized.startswith('//')` to keep invalid state from progressing.
    if parsed.netloc or normalized.startswith("//"):
        raise ValueError(f"{field_name} must not be protocol-relative")

    # Reject the operation when `parsed.query or parsed.fragment` to keep invalid state from progressing.
    if parsed.query or parsed.fragment:
        raise ValueError(f"protected upload {field_name} URLs cannot include query strings or fragments")

    # Reject the operation when `extract_upload_id_from_url(normalized) is None` to keep invalid state from progressing.
    if extract_upload_id_from_url(normalized) is None:
        raise ValueError(f"{field_name} must be an http(s) URL or /v1/uploads/{{file_id}}/content")

    return normalized


# Normalizes avatar url; the application layers use it as shared infrastructure.
def normalize_avatar_url(value: str | None) -> str | None:
    return normalize_profile_image_url(value, field_name="avatar_url")


# Normalizes wallpaper url; the application layers use it as shared infrastructure.
def normalize_wallpaper_url(value: str | None) -> str | None:
    return normalize_profile_image_url(value, field_name="wallpaper_url")
