from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.deps import AMQPDep, CurrentUserDep, DBDep
from app.core.errors import AppError
from app.schemas.channels import ChannelCreateRequest, ChannelResponse
from app.services.channel_service import ChannelService

router = APIRouter(prefix="/channels", tags=["channels"])


@router.post("", response_model=ChannelResponse, status_code=201)
async def create_channel(req: ChannelCreateRequest, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> ChannelResponse:
    try:
        channel = await ChannelService.create_channel(db, user.id, req, amqp)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return ChannelResponse.model_validate(channel, from_attributes=True)


@router.get("", response_model=list[ChannelResponse])
async def list_channels(db: DBDep, user: CurrentUserDep) -> list[ChannelResponse]:
    channels = await ChannelService.list_channels(db, user.id)
    return [ChannelResponse.model_validate(ch, from_attributes=True) for ch in channels]


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: UUID, db: DBDep, user: CurrentUserDep) -> ChannelResponse:
    try:
        channel = await ChannelService.get_channel_or_404(db, channel_id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return ChannelResponse.model_validate(channel, from_attributes=True)
