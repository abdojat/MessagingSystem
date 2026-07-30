from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

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


# Implements the prevent sensitive caching operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
def _prevent_sensitive_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


# Implements the overview operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/overview", response_model=AdminOverviewResponse)
async def overview(db: DBDep, _: SuperadminDep, response: Response) -> AdminOverviewResponse:
    _prevent_sensitive_caching(response)
    return await AdminService.overview(db)


# Lists events; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/events", response_model=AdminEventListResponse)
async def list_events(
    db: DBDep,
    _: SuperadminDep,
    response: Response,
    q: str | None = Query(default=None, max_length=128),
    event_type: str | None = Query(default=None, max_length=128),
    category: str | None = Query(default=None, pattern="^(security|channels|messages|memberships|uploads|delivery|administration|system)$"),
    channel_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> AdminEventListResponse:
    _prevent_sensitive_caching(response)
    items, total = await AdminService.list_events(
        db,
        q=q,
        event_type=event_type,
        category=category,
        channel_id=channel_id,
        actor_user_id=actor_user_id,
        offset=offset,
        limit=limit,
    )
    return AdminEventListResponse(items=items, total=total)


# Lists users; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    db: DBDep,
    _: SuperadminDep,
    response: Response,
    q: str | None = Query(default=None, max_length=255),
    is_active: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> AdminUserListResponse:
    _prevent_sensitive_caching(response)
    items, total = await AdminService.list_users(db, q=q, is_active=is_active, offset=offset, limit=limit)
    return AdminUserListResponse(items=items, total=total)


# Updates user status; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.patch("/users/{user_id}/status", response_model=AdminActionResponse)
async def update_user_status(
    user_id: UUID,
    req: AdminUserStatusUpdate,
    db: DBDep,
    superadmin: SuperadminDep,
    request: Request,
) -> AdminActionResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        count = await AdminService.set_user_active(db, superadmin, user_id, req.is_active)
        # Run this conditional step only when `not req.is_active` is true.
        if not req.is_active:
            await request.app.state.ws_manager.disconnect_user(user_id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse(affected_sessions=count)


# Revokes user sessions; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("/users/{user_id}/revoke-sessions", response_model=AdminActionResponse)
async def revoke_user_sessions(user_id: UUID, db: DBDep, superadmin: SuperadminDep) -> AdminActionResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        count = await AdminService.revoke_user_sessions(db, superadmin, user_id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse(affected_sessions=count)


# Lists channels; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/channels", response_model=AdminChannelListResponse)
async def list_channels(
    db: DBDep,
    _: SuperadminDep,
    response: Response,
    q: str | None = Query(default=None, max_length=255),
    include_deleted: bool = True,
    state: str | None = Query(default=None, pattern="^(active|suspended)$"),
    visibility: str | None = Query(default=None, pattern="^(public|private)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> AdminChannelListResponse:
    _prevent_sensitive_caching(response)
    items, total = await AdminService.list_channels(
        db,
        q=q,
        include_deleted=include_deleted,
        state=state,
        visibility=visibility,
        offset=offset,
        limit=limit,
    )
    return AdminChannelListResponse(items=items, total=total)


# Deactivates channel; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.delete("/channels/{channel_id}", response_model=AdminActionResponse)
async def deactivate_channel(
    channel_id: UUID,
    db: DBDep,
    superadmin: SuperadminDep,
    amqp: AMQPDep,
) -> AdminActionResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        await ChannelService.delete_channel(db, channel_id, superadmin.id, amqp)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse()


# Restores channel; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("/channels/{channel_id}/restore", response_model=AdminActionResponse)
async def restore_channel(
    channel_id: UUID,
    db: DBDep,
    superadmin: SuperadminDep,
    amqp: AMQPDep,
) -> AdminActionResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        await AdminService.restore_channel(db, amqp, superadmin, channel_id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse()
