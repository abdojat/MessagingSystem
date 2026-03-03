from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class EventResponse(BaseModel):
    id: UUID
    channel_id: UUID | None
    actor_user_id: UUID | None
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
