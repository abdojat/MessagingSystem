from uuid import UUID

from fastapi import APIRouter

from app.api.deps import AMQPDep, CurrentUserDep, DBDep
from app.core.errors import AppError, to_http_exception
from app.db.models import MembershipRole
from app.schemas.channels import ChannelCreateRequest, ChannelPatchRequest, ChannelResponse, MyMembershipResponse
from app.services.channel_service import ChannelService

router = APIRouter(prefix="/channels", tags=["channels"])


@router.post("", response_model=ChannelResponse, status_code=201)
async def create_channel(req: ChannelCreateRequest, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> ChannelResponse:
    try:
        channel = await ChannelService.create_channel(db, user.id, req, amqp)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ChannelResponse.model_validate(ChannelService.build_channel_payload(channel, MembershipRole.owner))


@router.get("", response_model=list[ChannelResponse])
async def list_channels(db: DBDep, user: CurrentUserDep) -> list[ChannelResponse]:
    channels = await ChannelService.list_channels(db, user.id)
    return [ChannelResponse.model_validate(ch) for ch in channels]


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: UUID, db: DBDep, user: CurrentUserDep) -> ChannelResponse:
    try:
        channel = await ChannelService.get_channel_view(db, channel_id, user.id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ChannelResponse.model_validate(channel)


@router.patch("/{channel_id}", response_model=ChannelResponse)
async def patch_channel(channel_id: UUID, req: ChannelPatchRequest, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> ChannelResponse:
    try:
        channel = await ChannelService.update_channel(db, channel_id, user.id, req, amqp)
        membership = await ChannelService.get_membership(db, channel_id, user.id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ChannelResponse.model_validate(ChannelService.build_channel_payload(channel, membership.role if membership else None))


@router.delete("/{channel_id}")
async def delete_channel(channel_id: UUID, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> dict:
    try:
        await ChannelService.delete_channel(db, channel_id, user.id, amqp)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return {"status": "ok"}


@router.get("/{channel_id}/my-membership", response_model=MyMembershipResponse)
async def my_membership(channel_id: UUID, db: DBDep, user: CurrentUserDep) -> MyMembershipResponse:
    try:
        await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, user.id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    if not membership:
        return MyMembershipResponse(channel_id=channel_id, user_id=user.id, role="none")
    return MyMembershipResponse(
        channel_id=channel_id,
        user_id=user.id,
        role=membership.role,
        created_at=membership.created_at,
        approved_at=membership.approved_at,
    )
