from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import AMQPDep, DBDep, RedisDep, SuperadminDep
from app.core.config import get_settings
from app.core.errors import AppError, to_http_exception
from app.realtime.auth_control import AuthControlEvent, dispatch_auth_control
from app.schemas.admin import (
    AdminActionResponse,
    AdminChannelListResponse,
    AdminEventListResponse,
    AdminOverviewResponse,
    AdminUserListResponse,
    AdminUserStatusUpdate,
)
from app.schemas.merkle import MerkleBatchListResponse, MerkleProofResponse, MerkleStatusResponse
from app.services.admin_service import AdminService
from app.services.channel_service import ChannelService
from app.services.merkle_audit_service import MerkleAuditService, MerkleIntegrityError
from app.services.rate_limit_service import enforce_rate_limit

router = APIRouter(prefix="/admin", tags=["superadmin"])


def _prevent_sensitive_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


@router.get("/overview", response_model=AdminOverviewResponse)
async def overview(db: DBDep, _: SuperadminDep, response: Response) -> AdminOverviewResponse:
    _prevent_sensitive_caching(response)
    return await AdminService.overview(db)


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


@router.get("/audit/merkle/status", response_model=MerkleStatusResponse)
async def merkle_status(
    db: DBDep,
    superadmin: SuperadminDep,
    response: Response,
    redis: RedisDep,
) -> MerkleStatusResponse:
    await enforce_rate_limit(
        redis,
        f"rl:admin:{superadmin.id}",
        limit=get_settings().rate_limit_admin_per_minute,
        window_seconds=60,
    )
    _prevent_sensitive_caching(response)
    result = await MerkleAuditService.status(db, get_settings().audit_merkle_public_keys)
    return MerkleStatusResponse(**result)


@router.get("/audit/merkle/batches", response_model=MerkleBatchListResponse)
async def merkle_batches(
    db: DBDep,
    superadmin: SuperadminDep,
    response: Response,
    redis: RedisDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> MerkleBatchListResponse:
    await enforce_rate_limit(
        redis,
        f"rl:admin:{superadmin.id}",
        limit=get_settings().rate_limit_admin_per_minute,
        window_seconds=60,
    )
    _prevent_sensitive_caching(response)
    items, total = await MerkleAuditService.list_batches(db, offset=offset, limit=limit)
    return MerkleBatchListResponse(items=items, total=total)


@router.get("/audit/merkle/events/{event_id}/proof", response_model=MerkleProofResponse)
async def merkle_event_proof(
    event_id: UUID,
    db: DBDep,
    superadmin: SuperadminDep,
    response: Response,
    redis: RedisDep,
) -> MerkleProofResponse:
    await enforce_rate_limit(
        redis,
        f"rl:admin:{superadmin.id}",
        limit=get_settings().rate_limit_admin_per_minute,
        window_seconds=60,
    )
    _prevent_sensitive_caching(response)
    try:
        proof = await MerkleAuditService.proof_for_event(
            db,
            event_id,
            public_keys=get_settings().audit_merkle_public_keys,
        )
    except MerkleIntegrityError as exc:
        status_code = 404 if exc.code == "EVENT_NOT_FOUND" else 409
        raise to_http_exception(AppError(str(exc), status_code, code=exc.code)) from exc
    return MerkleProofResponse(**proof)


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


@router.patch("/users/{user_id}/status", response_model=AdminActionResponse)
async def update_user_status(
    user_id: UUID,
    req: AdminUserStatusUpdate,
    db: DBDep,
    superadmin: SuperadminDep,
    request: Request,
    redis: RedisDep,
) -> AdminActionResponse:
    await enforce_rate_limit(
        redis,
        f"rl:admin:{superadmin.id}",
        limit=get_settings().rate_limit_admin_per_minute,
        window_seconds=60,
    )
    try:
        count = await AdminService.set_user_active(db, superadmin, user_id, req.is_active)
        if not req.is_active:
            await dispatch_auth_control(
                request.app.state.redis,
                request.app.state.ws_manager,
                AuthControlEvent(user_id=user_id, reason="account deactivated"),
            )
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse(affected_sessions=count)


@router.post("/users/{user_id}/revoke-sessions", response_model=AdminActionResponse)
async def revoke_user_sessions(
    user_id: UUID,
    db: DBDep,
    superadmin: SuperadminDep,
    request: Request,
    redis: RedisDep,
) -> AdminActionResponse:
    await enforce_rate_limit(
        redis,
        f"rl:admin:{superadmin.id}",
        limit=get_settings().rate_limit_admin_per_minute,
        window_seconds=60,
    )
    try:
        count = await AdminService.revoke_user_sessions(db, superadmin, user_id)
        await dispatch_auth_control(
            request.app.state.redis,
            request.app.state.ws_manager,
            AuthControlEvent(user_id=user_id, reason="sessions revoked by administrator"),
        )
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse(affected_sessions=count)


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


@router.delete("/channels/{channel_id}", response_model=AdminActionResponse)
async def deactivate_channel(
    channel_id: UUID,
    db: DBDep,
    superadmin: SuperadminDep,
    amqp: AMQPDep,
    redis: RedisDep,
) -> AdminActionResponse:
    await enforce_rate_limit(
        redis,
        f"rl:admin:{superadmin.id}",
        limit=get_settings().rate_limit_admin_per_minute,
        window_seconds=60,
    )
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
    redis: RedisDep,
) -> AdminActionResponse:
    await enforce_rate_limit(
        redis,
        f"rl:admin:{superadmin.id}",
        limit=get_settings().rate_limit_admin_per_minute,
        window_seconds=60,
    )
    try:
        await AdminService.restore_channel(db, amqp, superadmin, channel_id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return AdminActionResponse()
