from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import CurrentUserDep, DBDep, RedisDep
from app.core.config import get_settings
from app.core.errors import AppError, to_http_exception
from app.schemas.auth import (
    LoginRequest,
    LogoutAllResponse,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    SessionListResponse,
    SessionResponse,
    TokenPair,
)
from app.services.auth_service import AuthService
from app.services.event_service import log_event
from app.services.rate_limit_service import RateLimitService

router = APIRouter(prefix="/auth", tags=["auth"])


# Implements the enforce auth rate limits operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
async def _enforce_auth_rate_limits(redis: RedisDep, scope: str, ip: str, identity: str) -> None:
    ip_retry = await RateLimitService.hit(redis, f"rl:auth:{scope}:ip:{ip}", limit=30, window_seconds=60)
    # Reject the operation when `ip_retry is not None` to keep invalid state from progressing.
    if ip_retry is not None:
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": "rate limit exceeded", "details": {"retry_after_seconds": ip_retry}},
            headers={"Retry-After": str(ip_retry)},
        )
    user_retry = await RateLimitService.hit(redis, f"rl:auth:{scope}:identity:{identity.lower()}", limit=20, window_seconds=60)
    # Reject the operation when `user_retry is not None` to keep invalid state from progressing.
    if user_retry is not None:
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": "rate limit exceeded", "details": {"retry_after_seconds": user_retry}},
            headers={"Retry-After": str(user_retry)},
        )


# Registers a new user account; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("/register", status_code=201)
async def register(req: RegisterRequest, db: DBDep, request: Request, redis: RedisDep) -> dict:
    ip = request.client.host if request.client else "unknown"
    await _enforce_auth_rate_limits(redis, "register", ip, req.username)
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        user = await AuthService.register(db, req)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return {"id": str(user.id), "username": user.username, "email": user.email}


# Authenticates credentials and creates a user session; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("/login", response_model=TokenPair)
async def login(req: LoginRequest, db: DBDep, request: Request, redis: RedisDep) -> TokenPair:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    await _enforce_auth_rate_limits(redis, "login", ip, req.username_or_email)
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return await AuthService.login(
            db,
            req,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
            refresh_ttl_days=settings.jwt_refresh_ttl_days,
        )
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        # Run this conditional step only when `exc.code == 'AUTH_INVALID'` is true.
        if exc.code == "AUTH_INVALID":
            await log_event(
                db,
                "security.login_failed",
                {
                    "identity": req.username_or_email.strip().lower(),
                    "ip": ip,
                },
                channel_id=None,
                actor_user_id=None,
            )
            await db.commit()
        raise to_http_exception(exc) from exc


# Rotates the refresh credential and issues a new token pair; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("/refresh", response_model=TokenPair)
async def refresh(req: RefreshRequest, db: DBDep, request: Request, redis: RedisDep) -> TokenPair:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    await _enforce_auth_rate_limits(redis, "refresh", ip, ip)
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return await AuthService.refresh(
            db,
            req.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
            refresh_ttl_days=settings.jwt_refresh_ttl_days,
        )
    # Handle `(AppError, ValueError)` here so this workflow can recover or report the failure consistently.
    except (AppError, ValueError) as exc:
        # Reject the operation when `isinstance(exc, AppError)` to keep invalid state from progressing.
        if isinstance(exc, AppError):
            raise to_http_exception(exc) from exc
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_EXPIRED", "message": str(exc), "details": None},
        ) from exc


# Revokes the current user session; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("/logout")
async def logout(req: LogoutRequest, db: DBDep) -> dict:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        await AuthService.logout(db, req.refresh_token)
    # Handle `(AppError, ValueError)` here so this workflow can recover or report the failure consistently.
    except (AppError, ValueError) as exc:
        # Reject the operation when `isinstance(exc, AppError)` to keep invalid state from progressing.
        if isinstance(exc, AppError):
            raise to_http_exception(exc) from exc
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_EXPIRED", "message": str(exc), "details": None},
        ) from exc
    return {"status": "ok"}


# Lists sessions; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(db: DBDep, user: CurrentUserDep) -> SessionListResponse:
    sessions = await AuthService.list_sessions(db, user.id)
    return SessionListResponse(
        items=[
            SessionResponse(
                id=s.id,
                created_at=s.created_at,
                expires_at=s.expires_at,
                revoked_at=s.revoked_at,
                user_agent=s.user_agent,
                ip=s.ip,
            )
            for s in sessions
        ]
    )


# Revokes all active sessions for a user; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.post("/logout_all", response_model=LogoutAllResponse)
async def logout_all(db: DBDep, user: CurrentUserDep) -> LogoutAllResponse:
    revoked_count = await AuthService.logout_all(db, user.id)
    return LogoutAllResponse(revoked_count=revoked_count)


# Revokes session; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, db: DBDep, user: CurrentUserDep) -> dict:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        await AuthService.revoke_session(db, user.id, UUID(session_id))
    # Handle `(AppError, ValueError)` here so this workflow can recover or report the failure consistently.
    except (AppError, ValueError) as exc:
        # Reject the operation when `isinstance(exc, AppError)` to keep invalid state from progressing.
        if isinstance(exc, AppError):
            raise to_http_exception(exc) from exc
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "invalid session id", "details": None},
        ) from exc
    return {"status": "ok"}
