from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.deps import AMQPDep, CurrentUserDep, DBDep
from app.core.errors import AppError
from app.schemas.channels import InviteRequest, InviteResponse, JoinRequest, MembershipActionResponse
from app.services.channel_service import ChannelService

router = APIRouter(tags=["memberships"])


@router.post("/channels/{channel_id}/join", response_model=MembershipActionResponse)
async def join_channel(channel_id: UUID, req: JoinRequest, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> MembershipActionResponse:
    try:
        membership = await ChannelService.join_channel(db, amqp, channel_id, user.id, req)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MembershipActionResponse(channel_id=membership.channel_id, user_id=membership.user_id, role=membership.role)


@router.post("/channels/{channel_id}/invite", response_model=InviteResponse)
async def create_invite(channel_id: UUID, req: InviteRequest, db: DBDep, user: CurrentUserDep) -> InviteResponse:
    try:
        invite = await ChannelService.create_invite(db, channel_id, user.id, req)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return InviteResponse(token=invite.token, channel_id=invite.channel_id, expires_at=invite.expires_at)


@router.post("/invites/{token}/accept", response_model=MembershipActionResponse)
async def accept_invite(token: str, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> MembershipActionResponse:
    try:
        membership = await ChannelService.accept_invite(db, amqp, token, user.id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MembershipActionResponse(channel_id=membership.channel_id, user_id=membership.user_id, role=membership.role)


@router.post("/channels/{channel_id}/members/{user_id}/approve", response_model=MembershipActionResponse)
async def approve_member(channel_id: UUID, user_id: UUID, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> MembershipActionResponse:
    try:
        membership = await ChannelService.approve_member(db, amqp, channel_id, user.id, user_id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MembershipActionResponse(channel_id=membership.channel_id, user_id=membership.user_id, role=membership.role)


@router.post("/channels/{channel_id}/members/{user_id}/add", response_model=MembershipActionResponse)
async def add_member(channel_id: UUID, user_id: UUID, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> MembershipActionResponse:
    try:
        membership = await ChannelService.add_member_direct(db, amqp, channel_id, user.id, user_id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MembershipActionResponse(channel_id=membership.channel_id, user_id=membership.user_id, role=membership.role)


@router.post("/channels/{channel_id}/members/{user_id}/promote", response_model=MembershipActionResponse)
async def promote_member(channel_id: UUID, user_id: UUID, db: DBDep, user: CurrentUserDep) -> MembershipActionResponse:
    try:
        membership = await ChannelService.promote_member(db, channel_id, user.id, user_id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MembershipActionResponse(channel_id=membership.channel_id, user_id=membership.user_id, role=membership.role)


@router.post("/channels/{channel_id}/members/{user_id}/demote", response_model=MembershipActionResponse)
async def demote_member(channel_id: UUID, user_id: UUID, db: DBDep, user: CurrentUserDep) -> MembershipActionResponse:
    try:
        membership = await ChannelService.demote_member(db, channel_id, user.id, user_id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MembershipActionResponse(channel_id=membership.channel_id, user_id=membership.user_id, role=membership.role)


@router.delete("/channels/{channel_id}/members/{user_id}")
async def remove_member(channel_id: UUID, user_id: UUID, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> dict:
    try:
        await ChannelService.remove_member(db, amqp, channel_id, user.id, user_id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"status": "ok"}
