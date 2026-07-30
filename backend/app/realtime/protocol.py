from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from app.core.utils import utcnow


# Defines the wsenvelope project abstraction; the WebSocket layer uses it for realtime client delivery.
class WSEnvelope(BaseModel):
    type: str
    request_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime


# Defines the wssubscribe payload project abstraction; the WebSocket layer uses it for realtime client delivery.
class WSSubscribePayload(BaseModel):
    channel_ids: list[UUID]
    from_seq_id: int | None = None


# Defines the wsunsubscribe payload project abstraction; the WebSocket layer uses it for realtime client delivery.
class WSUnsubscribePayload(BaseModel):
    channel_ids: list[UUID]


# Defines the wsresume cursor project abstraction; the WebSocket layer uses it for realtime client delivery.
class WSResumeCursor(BaseModel):
    channel_id: UUID
    last_seen_seq_id: int | None = None


# Defines the wsresume payload project abstraction; the WebSocket layer uses it for realtime client delivery.
class WSResumePayload(BaseModel):
    channels: list[WSResumeCursor] = Field(default_factory=list)
    since: datetime | None = None
    limit: int = Field(default=200, ge=1, le=500)


# Defines the wssync state project abstraction; the WebSocket layer uses it for realtime client delivery.
class WSSyncState(BaseModel):
    channel_id: UUID
    last_seen_seq_id: int | None = None
    last_seen_at: datetime | None = None


# Defines the wssync payload project abstraction; the WebSocket layer uses it for realtime client delivery.
class WSSyncPayload(BaseModel):
    states: list[WSSyncState] = Field(default_factory=list)


# Defines the wsseen payload project abstraction; the WebSocket layer uses it for realtime client delivery.
class WSSeenPayload(BaseModel):
    channel_id: UUID
    last_seen_seq_id: int | None = None
    last_seen_at: datetime | None = None


# Builds envelope; the WebSocket layer uses it for realtime client delivery.
def build_envelope(msg_type: str, payload: dict[str, Any], request_id: UUID | None = None) -> dict[str, Any]:
    return {
        "type": msg_type,
        "request_id": str(request_id) if request_id else None,
        "payload": payload,
        "ts": utcnow().isoformat(),
    }


# Builds error; the WebSocket layer uses it for realtime client delivery.
def build_error(
    message: str,
    code: str = "VALIDATION_ERROR",
    request_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_envelope(
        "error",
        {
            "code": code,
            "message": message,
            "details": details,
        },
        request_id=request_id,
    )


# Parses client envelope; the WebSocket layer uses it for realtime client delivery.
def parse_client_envelope(data: dict[str, Any]) -> WSEnvelope:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return WSEnvelope.model_validate(data)
    # Handle `ValidationError` here so this workflow can recover or report the failure consistently.
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
