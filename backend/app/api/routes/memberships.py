from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import AMQPDep, CurrentUserDep, DBDep
from app.core.errors import AppError
from app.db.models import MembershipRole
from app.schemas.channels import (
    ChannelMembershipItem,
    ChannelMembershipListResponse,
    InviteListItem,
    InviteListResponse,
    InvitePreviewResponse,
    InviteRequest,
    InviteResponse,
    JoinOutcomeResponse,
    JoinRequest,
    MembershipActionResponse,
)
from app.services.channel_service import ChannelService

router = APIRouter(tags=["memberships"])


@router.post("/channels/{channel_id}/join", response_model=JoinOutcomeResponse)
async def join_channel(channel_id: UUID, req: JoinRequest, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> JoinOutcomeResponse:
    try:
        status, membership, message = await ChannelService.join_channel(db, amqp, channel_id, user.id, req)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return JoinOutcomeResponse(status=status, role=membership.role if membership else None, message=message)


@router.post("/channels/{channel_id}/leave")
async def leave_channel(channel_id: UUID, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> dict:
    try:
        await ChannelService.leave_channel(db, amqp, channel_id, user.id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"status": "ok"}


@router.get("/channels/{channel_id}/members", response_model=ChannelMembershipListResponse)
async def list_members(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    role: MembershipRole | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=255),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> ChannelMembershipListResponse:
    try:
        rows, next_cursor, has_more = await ChannelService.list_members(
            db,
            channel_id,
            user.id,
            role,
            q,
            cursor,
            limit,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return ChannelMembershipListResponse(
        items=[
            ChannelMembershipItem(
                user_id=u.id,
                username=u.username,
                email=u.email,
                role=m.role,
                created_at=m.created_at,
                approved_at=m.approved_at,
            )
            for m, u in rows
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/channels/{channel_id}/requests", response_model=ChannelMembershipListResponse)
async def list_pending_requests(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> ChannelMembershipListResponse:
    try:
        rows, next_cursor, has_more = await ChannelService.list_pending_requests(db, channel_id, user.id, cursor, limit)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return ChannelMembershipListResponse(
        items=[
            ChannelMembershipItem(
                user_id=u.id,
                username=u.username,
                email=u.email,
                role=m.role,
                created_at=m.created_at,
                approved_at=m.approved_at,
            )
            for m, u in rows
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post("/channels/{channel_id}/invite", response_model=InviteResponse)
async def create_invite(channel_id: UUID, req: InviteRequest, db: DBDep, user: CurrentUserDep) -> InviteResponse:
    try:
        invite = await ChannelService.create_invite(db, channel_id, user.id, req)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return InviteResponse(id=invite.id, token=invite.token, channel_id=invite.channel_id, expires_at=invite.expires_at)


@router.get("/channels/{channel_id}/invites", response_model=InviteListResponse)
async def list_invites(channel_id: UUID, db: DBDep, user: CurrentUserDep) -> InviteListResponse:
    try:
        invites = await ChannelService.list_invites(db, channel_id, user.id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return InviteListResponse(
        items=[
            InviteListItem(
                id=i.id,
                channel_id=i.channel_id,
                invited_user_id=i.invited_user_id,
                invited_email=i.invited_email,
                token_masked=ChannelService.mask_token(i.token),
                created_by_user_id=i.created_by_user_id,
                created_at=i.created_at,
                expires_at=i.expires_at,
                accepted_at=i.accepted_at,
                revoked_at=i.revoked_at,
            )
            for i in invites
        ]
    )


@router.post("/channels/{channel_id}/invites/{invite_id}/revoke")
async def revoke_invite(channel_id: UUID, invite_id: UUID, db: DBDep, user: CurrentUserDep) -> dict:
    try:
        await ChannelService.revoke_invite(db, channel_id, invite_id, user.id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"status": "ok"}


@router.get("/invites/{token}", response_model=InvitePreviewResponse)
async def preview_invite(token: str, db: DBDep) -> InvitePreviewResponse:
    payload = await ChannelService.get_invite_preview(db, token)
    return InvitePreviewResponse.model_validate(payload)


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
