from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from app.core.utils import utcnow


class WSEnvelope(BaseModel):
    type: str
    request_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime


class WSSubscribePayload(BaseModel):
    channel_ids: list[UUID]
    from_seq_id: int | None = None


class WSUnsubscribePayload(BaseModel):
    channel_ids: list[UUID]


class WSResumeCursor(BaseModel):
    channel_id: UUID
    last_seen_seq_id: int | None = None


class WSResumePayload(BaseModel):
    channels: list[WSResumeCursor] = Field(default_factory=list)
    since: datetime | None = None


def build_envelope(msg_type: str, payload: dict[str, Any], request_id: UUID | None = None) -> dict[str, Any]:
    return {
        "type": msg_type,
        "request_id": str(request_id) if request_id else None,
        "payload": payload,
        "ts": utcnow().isoformat(),
    }


def build_error(message: str, code: str = "BAD_REQUEST", request_id: UUID | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_envelope(
        "error",
        {
            "code": code,
            "message": message,
            "details": details,
        },
        request_id=request_id,
    )


def parse_client_envelope(data: dict[str, Any]) -> WSEnvelope:
    try:
        return WSEnvelope.model_validate(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
