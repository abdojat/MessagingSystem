from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import AMQPDep, CurrentUserDep, DBDep
from app.core.errors import AppError, to_http_exception
from app.db.models import ChannelVisibility
from app.schemas.channels import (
    ChannelCreateRequest,
    ChannelListItem,
    ChannelListResponse,
    ChannelPatchRequest,
    ChannelResponse,
    ChannelStatsResponse,
    MyMembershipResponse,
)
from app.services.channel_service import ChannelService

router = APIRouter(prefix="/channels", tags=["channels"])


# Creates channel; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("", response_model=ChannelResponse, status_code=201)
async def create_channel(req: ChannelCreateRequest, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> ChannelResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        created = await ChannelService.create_channel(db, user.id, req, amqp)
        channel = await ChannelService.get_channel_view(db, created.id, user.id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ChannelResponse.model_validate(channel)


# Lists channels; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("", response_model=ChannelListResponse)
async def list_channels(
    db: DBDep,
    user: CurrentUserDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None, min_length=1, max_length=255),
    visibility: str | None = Query(default=None, pattern="^(public|private)$"),
    scope: str = Query(default="my", pattern="^(my|discover)$"),
) -> ChannelListResponse:
    # Run this conditional step only when `not isinstance(q, str)` is true.
    if not isinstance(q, str):
        q = None
    # Run this conditional step only when `not isinstance(visibility, str)` is true.
    if not isinstance(visibility, str):
        visibility = None
    # Run this conditional step only when `not isinstance(scope, str)` is true.
    if not isinstance(scope, str):
        scope = "my"
    # Run this conditional step only when `q is not None` is true.
    if q is not None:
        q = q.strip() or None
    visibility_enum = ChannelVisibility(visibility) if visibility is not None else None
    channels, next_cursor, has_more = await ChannelService.list_channels(
        db,
        user.id,
        cursor,
        limit,
        q=q,
        visibility=visibility_enum,
        scope=scope,
    )
    return ChannelListResponse(
        items=[ChannelListItem.model_validate(ch) for ch in channels],
        next_cursor=next_cursor,
        has_more=has_more,
    )


# Retrieves channel; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: UUID, db: DBDep, user: CurrentUserDep) -> ChannelResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        channel = await ChannelService.get_channel_view(db, channel_id, user.id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ChannelResponse.model_validate(channel)


# Updates channel; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.patch("/{channel_id}", response_model=ChannelResponse)
async def patch_channel(channel_id: UUID, req: ChannelPatchRequest, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> ChannelResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        channel = await ChannelService.update_channel(db, channel_id, user.id, req, amqp)
        membership = await ChannelService.get_membership(db, channel_id, user.id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ChannelResponse.model_validate(
        ChannelService.build_channel_payload(
            channel,
            membership.role if membership else None,
            membership.admin_permissions if membership else None,
        )
    )


# Deletes channel; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.delete("/{channel_id}")
async def delete_channel(channel_id: UUID, db: DBDep, user: CurrentUserDep, amqp: AMQPDep) -> dict:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        await ChannelService.delete_channel(db, channel_id, user.id, amqp)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return {"status": "ok"}


# Implements the my membership operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/{channel_id}/my-membership", response_model=MyMembershipResponse)
async def my_membership(channel_id: UUID, db: DBDep, user: CurrentUserDep) -> MyMembershipResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        await ChannelService.get_channel_or_404(db, channel_id)
        membership = await ChannelService.get_membership(db, channel_id, user.id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    # Return early when `not membership` because the remaining work is not applicable.
    if not membership:
        return MyMembershipResponse(channel_id=channel_id, user_id=user.id, role="none")
    return MyMembershipResponse(
        channel_id=channel_id,
        user_id=user.id,
        role=membership.role,
        created_at=membership.created_at,
        approved_at=membership.approved_at,
    )


# Implements the channel stats operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/{channel_id}/stats", response_model=ChannelStatsResponse)
async def channel_stats(channel_id: UUID, db: DBDep, user: CurrentUserDep) -> ChannelStatsResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        payload = await ChannelService.get_channel_stats(db, channel_id, user.id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ChannelStatsResponse.model_validate(payload)
