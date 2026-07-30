import re

SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9_-]{3,50}$"
SAFE_IDENTIFIER_RE = re.compile(SAFE_IDENTIFIER_PATTERN)


# Normalizes username; the worker runtime uses it for asynchronous broker delivery.
def _normalize_username(username: str) -> str:
    normalized = username.strip()
    # Reject the operation when `not SAFE_IDENTIFIER_RE.fullmatch(normalized)` to keep invalid state from progressing.
    if not SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"username must match {SAFE_IDENTIFIER_PATTERN}")
    return normalized


# Builds the Redis key that tracks online users; the worker runtime uses it for asynchronous broker delivery.
def online_users_key() -> str:
    return "rt.online_users"


# Builds the Redis pub/sub channel for a user; the worker runtime uses it for asynchronous broker delivery.
def user_pubsub_channel(username: str) -> str:
    return f"rt.user.{_normalize_username(username)}"


# Builds the durable RabbitMQ queue name for a user; the worker runtime uses it for asynchronous broker delivery.
def user_queue_name(username: str) -> str:
    return f"user.{_normalize_username(username)}"
