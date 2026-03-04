import asyncio
import logging
from contextlib import asynccontextmanager

import aio_pika
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.api.routes import auth, channels, events, health, memberships, messages, users
from app.core.config import get_settings
from app.core.errors import AppError, default_error_code
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.mq.topology import ensure_topology
from app.realtime.ws_manager import WSManager
from app.schemas.common import ErrorResponse
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)

    amqp = None
    for _ in range(30):
        try:
            amqp = await aio_pika.connect_robust(settings.rabbitmq_url)
            await ensure_topology(amqp)
            break
        except Exception:
            await asyncio.sleep(1)
    if amqp is None:
        raise RuntimeError("cannot connect to rabbitmq")

    app.state.redis = redis
    app.state.amqp = amqp
    app.state.ws_manager = WSManager(SessionLocal, redis, amqp)

    try:
        yield
    finally:
        await redis.close()
        await amqp.close()


app = FastAPI(title="Channels Backend", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(channels.router)
app.include_router(memberships.router)
app.include_router(messages.router)
app.include_router(events.router)
app.include_router(health.router)


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    payload = ErrorResponse(code=exc.code, message=exc.message, details=exc.details).model_dump()
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(HTTPException)
async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or default_error_code(exc.status_code))
        message = str(detail.get("message") or "request failed")
        details = detail.get("details")
    else:
        code = default_error_code(exc.status_code)
        message = str(detail or "request failed")
        details = None
    payload = ErrorResponse(code=code, message=message, details=details).model_dump()
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    payload = ErrorResponse(
        code="VALIDATION_ERROR",
        message="validation error",
        details={"errors": exc.errors()},
    ).model_dump()
    return JSONResponse(status_code=422, content=payload)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
    if not token:
        await websocket.close(code=4401, reason="missing token")
        return

    async with SessionLocal() as db:
        try:
            user = await AuthService.get_user_from_access_token(db, token)
        except (AppError, ValueError):
            await websocket.close(code=4401, reason="invalid token")
            return

    manager: WSManager = app.state.ws_manager
    await manager.connect(websocket, user.id)
    try:
        await manager.run_socket(websocket, user.id)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, user.id)
