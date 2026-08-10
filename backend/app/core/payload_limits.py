import json
import unicodedata
from typing import Any

from app.core.config import get_settings


PROTOCOL_CHANNEL_ARRAY_MAX = 100


def validate_message_text(value: str | None) -> str | None:
    if value is None:
        return None
    limit = get_settings().message_text_max_bytes
    if len(value.encode("utf-8")) > limit:
        raise ValueError(f"content_text exceeds {limit} UTF-8 bytes")
    return value


def _json_depth(value: Any) -> int:
    max_depth = 1
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        max_depth = max(max_depth, depth)
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
    return max_depth


def validate_message_json(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    settings = get_settings()
    if _json_depth(value) > settings.message_json_max_depth:
        raise ValueError(f"content_json exceeds maximum nesting depth {settings.message_json_max_depth}")
    try:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("content_json must contain finite JSON values") from exc
    if len(serialized) > settings.message_json_max_bytes:
        raise ValueError(f"content_json exceeds {settings.message_json_max_bytes} serialized bytes")
    return value


def normalize_reaction(value: str) -> str:
    emoji = value.strip()
    if not emoji:
        raise ValueError("emoji cannot be empty")
    if len(emoji) > 16 or len(emoji.encode("utf-8")) > 64:
        raise ValueError("emoji is too long")
    if any(char.isspace() or unicodedata.category(char).startswith("C") and char != "\u200d" for char in emoji):
        raise ValueError("emoji cannot contain whitespace or control characters")

    # Keep the policy deliberately small: accept common emoji blocks plus the
    # joiner/modifier code points needed for composed emoji. This rejects
    # arbitrary words while avoiding a heavyweight Unicode dependency.
    def is_emoji_base(codepoint: int) -> bool:
        return (
            0x1F000 <= codepoint <= 0x1FAFF
            or 0x2600 <= codepoint <= 0x27BF
            or 0x2300 <= codepoint <= 0x23FF
            or 0x1F1E6 <= codepoint <= 0x1F1FF
            or codepoint in {0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139}
        )

    allowed_composition = {0x200D, 0xFE0F, 0x20E3} | set(range(0x1F3FB, 0x1F400))
    if not any(is_emoji_base(ord(char)) for char in emoji):
        raise ValueError("emoji must contain a supported Unicode emoji")
    if any(not is_emoji_base(ord(char)) and ord(char) not in allowed_composition for char in emoji):
        raise ValueError("emoji contains unsupported characters")
    return emoji
