from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, DBDep
from app.core.errors import AppError, to_http_exception
from app.schemas.delivery import DeliveryListResponse, DeliveryRetryResponse, DeliveryStatsResponse
from app.services.delivery_service import DeliveryService

router = APIRouter(prefix="/admin/delivery", tags=["admin-delivery"])


# Implements the delivery stats operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/stats", response_model=DeliveryStatsResponse)
async def delivery_stats(db: DBDep, user: CurrentUserDep) -> DeliveryStatsResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return await DeliveryService.get_stats(db, user.id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc


# Implements the failed deliveries operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/failed", response_model=DeliveryListResponse)
async def failed_deliveries(
    db: DBDep,
    user: CurrentUserDep,
    limit: int = Query(default=100, ge=1, le=200),
) -> DeliveryListResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        items = await DeliveryService.list_failed(db, user.id, limit=limit)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return DeliveryListResponse(items=items)


# Implements the dead lettered deliveries operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/dead-lettered", response_model=DeliveryListResponse)
async def dead_lettered_deliveries(
    db: DBDep,
    user: CurrentUserDep,
    limit: int = Query(default=100, ge=1, le=200),
) -> DeliveryListResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        items = await DeliveryService.list_dead_lettered(db, user.id, limit=limit)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return DeliveryListResponse(items=items)


# Retries delivery; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("/{outbox_id}/retry", response_model=DeliveryRetryResponse)
async def retry_delivery(outbox_id: UUID, db: DBDep, user: CurrentUserDep) -> DeliveryRetryResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return await DeliveryService.retry_one(db, user.id, outbox_id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc


# Retries all deliveries; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("/retry-all", response_model=DeliveryRetryResponse)
async def retry_all_deliveries(db: DBDep, user: CurrentUserDep) -> DeliveryRetryResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return await DeliveryService.retry_all(db, user.id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
