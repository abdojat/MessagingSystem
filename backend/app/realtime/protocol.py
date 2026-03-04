from typing import Any


def build_ws_message(channel_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "message",
        "channel_id": channel_id,
        "message": payload,
    }


WS_PROTOCOL_DOC = {
    "server_to_client": {
        "hello": {"type": "hello", "user_id": "uuid", "server_time": "iso-datetime"},
        "history": {"type": "history", "channel_id": "uuid", "items": ["Message"], "is_truncated": False},
        "message": {"type": "message", "channel_id": "uuid", "message": "Message"},
        "membership_update": {
            "type": "membership_update",
            "channel_id": "uuid",
            "user_id": "uuid",
            "new_role": "owner|admin|member|pending|none",
            "reason": "approved|removed|promoted|demoted|left|join|added|invite_accepted",
        },
    },
    "client_to_server": {
        "sync": {"type": "sync", "states": [{"channel_id": "uuid", "last_seen_seq_id": 0, "last_seen_at": "iso-datetime"}]},
        "seen": {"type": "seen", "channel_id": "uuid", "last_seen_seq_id": 0, "last_seen_at": "iso-datetime"},
    },
}
