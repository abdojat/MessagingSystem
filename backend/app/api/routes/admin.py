from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.deps import AMQPDep, DBDep, SuperadminDep
from app.core.errors import AppError, to_http_exception
from app.schemas.admin import (
    AdminActionResponse,
    AdminChannelListResponse,
    AdminEventListResponse,
    AdminOverviewResponse,
    AdminUserListResponse,
    AdminUserStatusUpdate,
)
from app.services.admin_service import AdminService
from app.services.channel_service import ChannelService

router = APIRouter(prefix="/admin", tags=["superadmin"])


@router.get("/overview", response_model=AdminOverviewResponse)
async def overview(db: DBDep, _: SuperadminDep) -> AdminOverviewResponse:
    return await AdminService.overview(db)


@router.get("/events", response_model=AdminEventListResponse)
async def list_events(
    db: DBDep,
    _: SuperadminDep,
    event_type: str | None = Query(default=None, max_length=128),
    channel_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> AdminEventListResponse:
    items, total = await AdminService.list_events(
        db,
        event_type=event_type,
        channel_id=channel_id,
        actor_user_id=actor_user_id,
        offset=offset,
        limit=limit,
    )
    return AdminEventListResponse(items=items, total=total)


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    db: DBDep,
    _: SuperadminDep,
    q: str | None = Query(default=None, max_length=255),
    is_active: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> AdminUserListResponse:
    items, total = await AdminService.list_users(db, q=q, is_active=is_active, offset=offset, limit=limit)
    return AdminUserListResponse(items=items, total=total)


@router.patch("/users/{user_id}/status", response_model=AdminActionResponse)
async def update_user_status(
    user_id: UUID,
    req: AdminUserStatusUpdate,
    db: DBDep,
    superadmin: SuperadminDep,
    request: Request,
) -> AdminActionResponse:
    try:
        count = await AdminService.set_user_active(db, superadmin, user_id, req.is_active)
        if not req.is_active:
            await request.app.state.ws_manager.disconnect_user(user_id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse(affected_sessions=count)


@router.post("/users/{user_id}/revoke-sessions", response_model=AdminActionResponse)
async def revoke_user_sessions(user_id: UUID, db: DBDep, superadmin: SuperadminDep) -> AdminActionResponse:
    try:
        count = await AdminService.revoke_user_sessions(db, superadmin, user_id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse(affected_sessions=count)


@router.get("/channels", response_model=AdminChannelListResponse)
async def list_channels(
    db: DBDep,
    _: SuperadminDep,
    q: str | None = Query(default=None, max_length=255),
    include_deleted: bool = True,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> AdminChannelListResponse:
    items, total = await AdminService.list_channels(
        db, q=q, include_deleted=include_deleted, offset=offset, limit=limit
    )
    return AdminChannelListResponse(items=items, total=total)


@router.delete("/channels/{channel_id}", response_model=AdminActionResponse)
async def deactivate_channel(
    channel_id: UUID,
    db: DBDep,
    superadmin: SuperadminDep,
    amqp: AMQPDep,
) -> AdminActionResponse:
    try:
        await ChannelService.delete_channel(db, channel_id, superadmin.id, amqp)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse()


@router.post("/channels/{channel_id}/restore", response_model=AdminActionResponse)
async def restore_channel(
    channel_id: UUID,
    db: DBDep,
    superadmin: SuperadminDep,
    amqp: AMQPDep,
) -> AdminActionResponse:
    try:
        await AdminService.restore_channel(db, amqp, superadmin, channel_id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse()
