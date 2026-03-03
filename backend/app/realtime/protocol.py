from typing import Any


def build_ws_message(channel_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "message",
        "channel_id": channel_id,
        "message": payload,
    }
