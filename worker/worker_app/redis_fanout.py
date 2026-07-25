import re

SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9_-]{3,50}$"
SAFE_IDENTIFIER_RE = re.compile(SAFE_IDENTIFIER_PATTERN)


def _normalize_username(username: str) -> str:
    normalized = username.strip()
    if not SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"username must match {SAFE_IDENTIFIER_PATTERN}")
    return normalized


def online_users_key() -> str:
    return "rt.online_users"


def user_pubsub_channel(username: str) -> str:
    return f"rt.user.{_normalize_username(username)}"


def user_queue_name(username: str) -> str:
    return f"user.{_normalize_username(username)}"
