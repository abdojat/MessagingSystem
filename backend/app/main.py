import asyncio
import logging
from contextlib import asynccontextmanager

import aio_pika
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.api.routes import admin, auth, channels, delivery, events, health, memberships, messages, users
from app.core.config import get_settings
from app.core.errors import AppError, default_error_code
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.mq.topology import ensure_topology
from app.realtime.protocol import build_error
from app.realtime.ws_manager import WSManager
from app.schemas.common import ErrorResponse
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)


# Starts and stops shared application dependencies; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)

    amqp = None
    # Process each `_` from `range(30)` to apply this step to the full collection.
    for _ in range(30):
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            amqp = await aio_pika.connect_robust(settings.rabbitmq_url)
            await ensure_topology(amqp)
            break
        # Handle `Exception` here so this workflow can recover or report the failure consistently.
        except Exception:
            await asyncio.sleep(1)
    # Reject the operation when `amqp is None` to keep invalid state from progressing.
    if amqp is None:
        raise RuntimeError("cannot connect to rabbitmq")

    app.state.redis = redis
    app.state.amqp = amqp
    app.state.ws_manager = WSManager(SessionLocal, redis, amqp)

    # Protect this operation so its cleanup step runs even if processing fails.
    try:
        yield
    # Always run this cleanup path after the guarded operation finishes.
    finally:
        await redis.close()
        await amqp.close()


app = FastAPI(title="Channels Backend", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Process each `route_module` from `(auth, users, channels, memberships, messages, events, delivery, admi...` to apply this step to the full collection.
for route_module in (auth, users, channels, memberships, messages, events, delivery, admin, health):
    app.include_router(route_module.router, prefix=settings.api_v1_prefix)
# Process each `route_module` from `(auth, users, channels, memberships, messages, events, delivery, admi...` to apply this step to the full collection.
for route_module in (auth, users, channels, memberships, messages, events, delivery, admin, health):
    app.include_router(route_module.router, include_in_schema=False)


# Handles app error; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    payload = ErrorResponse(code=exc.code, message=exc.message, details=exc.details).model_dump()
    return JSONResponse(status_code=exc.status_code, content=payload)


# Handles http error; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@app.exception_handler(HTTPException)
async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    # Choose the appropriate path based on whether `isinstance(detail, dict)` is true.
    if isinstance(detail, dict):
        code = str(detail.get("code") or default_error_code(exc.status_code))
        message = str(detail.get("message") or "request failed")
        details = detail.get("details")
    # Handle the alternate path after the preceding branch or loop does not produce a result.
    else:
        code = default_error_code(exc.status_code)
        message = str(detail or "request failed")
        details = None
    payload = ErrorResponse(code=code, message=message, details=details).model_dump()
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)


# Handles validation error; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    payload = ErrorResponse(
        code="VALIDATION_ERROR",
        message="validation error",
        details={"errors": exc.errors()},
    ).model_dump()
    return JSONResponse(status_code=400, content=payload)


# Handles unexpected error; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception", exc_info=exc)
    payload = ErrorResponse(code="INTERNAL_ERROR", message="internal server error", details=None).model_dump()
    return JSONResponse(status_code=500, content=payload)


# Accepts WebSocket clients on the compatibility endpoint; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await _run_websocket(websocket)


# Accepts WebSocket clients on the versioned endpoint; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@app.websocket("/v1/ws")
async def websocket_endpoint_v1(websocket: WebSocket):
    await _run_websocket(websocket)


# Runs websocket; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
async def _run_websocket(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    # Run this conditional step only when `not token` is true.
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        # Run this conditional step only when `auth_header.lower().startswith('bearer ')` is true.
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
    # Run this conditional step only when `not token` is true.
    if not token:
        await websocket.accept()
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        # Handle `Exception` here so this workflow can recover or report the failure consistently.
        except Exception:
            await websocket.send_json(build_error("missing auth", code="AUTH_INVALID"))
            await websocket.close(code=1008, reason="missing token")
            return
        # Run this conditional step only when `auth_msg.get('type') != 'auth'` is true.
        if auth_msg.get("type") != "auth":
            await websocket.send_json(build_error("missing auth", code="AUTH_INVALID"))
            await websocket.close(code=1008, reason="missing token")
            return
        payload = auth_msg.get("payload") or {}
        token = payload.get("token")
        # Run this conditional step only when `not token` is true.
        if not token:
            await websocket.send_json(build_error("missing auth token", code="AUTH_INVALID"))
            await websocket.close(code=1008, reason="missing token")
            return
        await _run_websocket_with_token(websocket, token, pre_accepted=True)
        return
    await _run_websocket_with_token(websocket, token, pre_accepted=False)


# Runs websocket with token; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
async def _run_websocket_with_token(websocket: WebSocket, token: str, pre_accepted: bool = False) -> None:
    # Keep `SessionLocal()` active while this scoped operation is performed.
    async with SessionLocal() as db:
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            user = await AuthService.get_user_from_access_token(db, token)
        # Handle `(AppError, ValueError)` here so this workflow can recover or report the failure consistently.
        except (AppError, ValueError):
            # Run this conditional step only when `not pre_accepted` is true.
            if not pre_accepted:
                await websocket.accept()
            await websocket.send_json(build_error("invalid token", code="AUTH_INVALID"))
            await websocket.close(code=1008, reason="invalid token")
            return

    manager: WSManager = app.state.ws_manager
    await manager.connect(websocket, user.id, user.username, pre_accepted=pre_accepted)
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        await manager.run_socket(websocket, user.id, user.username)
    # Handle `WebSocketDisconnect` here so this workflow can recover or report the failure consistently.
    except WebSocketDisconnect:
        pass
    # Always run this cleanup path after the guarded operation finishes.
    finally:
        await manager.disconnect(websocket, user.username)
