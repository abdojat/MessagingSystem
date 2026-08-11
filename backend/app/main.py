import asyncio
import logging
from contextlib import asynccontextmanager

import aio_pika
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import admin, auth, channels, delivery, events, health, memberships, messages, users
from app.core.client_ip import get_client_ip
from app.core.config import get_settings
from app.core.errors import AppError, default_error_code
from app.core.logging import configure_logging
from app.core.request_body_limit import RequestBodyLimitMiddleware
from app.db.session import SessionLocal
from app.mq.topology import ensure_topology
from app.realtime.protocol import build_error
from app.realtime.ws_manager import WSManager
from app.schemas.common import ErrorResponse
from app.services.auth_service import AuthService
from app.services.email_delivery_service import build_verification_mailer
from app.services.ws_ticket_service import WebSocketTicketService
from app.services.rate_limit_service import RateLimitService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)

    # Compose can start the API before RabbitMQ accepts connections, so startup
    # waits briefly instead of failing the whole demo on service ordering.
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
    app.state.verification_mailer = build_verification_mailer(settings)
    app.state.ws_manager = WSManager(SessionLocal, redis, amqp)
    await app.state.ws_manager.start()

    try:
        yield
    finally:
        await app.state.ws_manager.stop()
        await redis.close()
        await amqp.close()


settings = get_settings()
app = FastAPI(
    title="Channels Backend",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)
app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=settings.api_request_body_max_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

# Keep both prefixed and legacy unprefixed routes available; newer docs use
# /v1, while older demo scripts and supervisor bookmarks may still hit /auth.
for route_module in (auth, users, channels, memberships, messages, events, delivery, admin, health):
    app.include_router(route_module.router, prefix=settings.api_v1_prefix)
for route_module in (auth, users, channels, memberships, messages, events, delivery, admin, health):
    app.include_router(route_module.router, include_in_schema=False)


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
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    payload = ErrorResponse(
        code="VALIDATION_ERROR",
        message="validation error",
        details={"errors": exc.errors()},
    ).model_dump()
    return JSONResponse(status_code=400, content=payload)


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception", exc_info=exc)
    payload = ErrorResponse(code="INTERNAL_ERROR", message="internal server error", details=None).model_dump()
    return JSONResponse(status_code=500, content=payload)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await _run_websocket(websocket)


@app.websocket("/v1/ws")
async def websocket_endpoint_v1(websocket: WebSocket):
    await _run_websocket(websocket)


async def _run_websocket(websocket: WebSocket) -> None:
    # Browsers present only a short-lived, single-use opaque ticket. Raw access
    # JWT query parameters, headers, and first-frame credentials are rejected.
    client_ip = get_client_ip(websocket)
    websocket_rate_key = f"rl:websocket:connect:{client_ip}"
    app_redis = getattr(app.state, "redis", None)
    if app_redis is None:
        # This path is primarily useful for startup/unit contexts; a live app
        # always sets Redis during lifespan. It retains the same local bound.
        rate_result = await RateLimitService._hit_local(
            websocket_rate_key,
            get_settings().rate_limit_websocket_per_minute,
            60,
        )
    else:
        rate_result = await RateLimitService.hit(
            app_redis,
            websocket_rate_key,
            limit=get_settings().rate_limit_websocket_per_minute,
            window_seconds=60,
        )
    if rate_result.retry_after_seconds is not None:
        await websocket.accept()
        await websocket.send_json(
            build_error(
                "WebSocket connection rate limit exceeded",
                code="RATE_LIMITED",
                details={"retry_after_seconds": rate_result.retry_after_seconds},
            )
        )
        await websocket.close(code=1013, reason="WebSocket rate limit exceeded")
        return

    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.accept()
        await websocket.send_json(build_error("missing WebSocket ticket", code="WS_TICKET_INVALID"))
        await websocket.close(code=1008, reason="missing WebSocket ticket")
        return
    try:
        ticket_claims = await WebSocketTicketService.consume(app.state.redis, ticket)
    except AppError as exc:
        await websocket.accept()
        await websocket.send_json(build_error(exc.message, code=exc.code))
        close_code = 1013 if exc.status_code == 503 else 1008
        await websocket.close(code=close_code, reason="invalid WebSocket ticket")
        return

    async with SessionLocal() as db:
        try:
            auth = await AuthService.get_session_access_context(
                db,
                ticket_claims.user_id,
                ticket_claims.session_id,
                ticket_claims.authentication_expires_at,
            )
        except (AppError, ValueError) as exc:
            await websocket.accept()
            code = exc.code if isinstance(exc, AppError) else "AUTH_INVALID"
            await websocket.send_json(build_error("invalid authentication session", code=code))
            await websocket.close(code=1008, reason="invalid authentication session")
            return

    manager: WSManager = app.state.ws_manager
    try:
        await manager.connect(websocket, auth.user.id, auth.user.username, auth.session_id)
    except AppError as exc:
        await websocket.accept()
        await websocket.send_json(build_error(exc.message, code=exc.code))
        await websocket.close(code=1013, reason="WebSocket quota exceeded")
        return
    try:
        await manager.run_socket(
            websocket,
            auth.user.id,
            auth.user.username,
            auth.session_id,
            auth.authentication_expires_at,
        )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, auth.user.username)
