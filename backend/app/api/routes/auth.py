from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import CurrentAuthDep, CurrentUserDep, DBDep, RedisDep
from app.core.client_ip import get_client_ip
from app.core.browser_security import (
    clear_browser_auth_cookies,
    set_browser_auth_cookies,
    set_csrf_cookie,
    validate_browser_csrf,
    validate_browser_origin,
)
from app.core.config import get_settings
from app.core.errors import AppError, to_http_exception
from app.core.utils import sha256_hex
from app.schemas.auth import (
    BrowserAccessTokenResponse,
    BrowserCsrfResponse,
    ChangePasswordRequest,
    EmailVerificationConfirmRequest,
    EmailVerificationConfirmResponse,
    EmailVerificationRequestResponse,
    LoginRequest,
    LogoutAllResponse,
    LogoutRequest,
    PasswordChangeResponse,
    RefreshRequest,
    RegisterRequest,
    SessionListResponse,
    SessionResponse,
    TokenPair,
    WebSocketTicketResponse,
)
from app.realtime.auth_control import AuthControlEvent, dispatch_auth_control
from app.services.auth_service import AuthService, RefreshTokenReplayError
from app.services.email_verification_service import EmailVerificationService
from app.services.event_service import log_event
from app.services.rate_limit_service import enforce_rate_limit
from app.services.ws_ticket_service import WebSocketTicketService

router = APIRouter(prefix="/auth", tags=["auth"])


async def _enforce_auth_rate_limits(redis: RedisDep, scope: str, ip: str, identity: str) -> None:
    settings = get_settings()
    # Keep attacker-controlled identity text out of Redis and local limiter
    # keys. Normalization retains stable case-insensitive login semantics while
    # SHA-256 gives every accepted input a fixed-size representation.
    identity_digest = sha256_hex(identity.strip().lower())
    await enforce_rate_limit(
        redis,
        f"rl:auth:{scope}:ip:{ip}",
        limit=settings.rate_limit_auth_ip_per_minute,
        window_seconds=60,
    )
    await enforce_rate_limit(
        redis,
        f"rl:auth:{scope}:identity:{identity_digest}",
        limit=settings.rate_limit_auth_identity_per_minute,
        window_seconds=60,
    )


async def _enforce_email_verification_request_limits(redis: RedisDep, user_id: UUID, ip: str) -> None:
    settings = get_settings()
    await enforce_rate_limit(
        redis,
        f"rl:email-verification:request:user:{user_id}",
        limit=settings.rate_limit_email_verification_user_per_15_minutes,
        window_seconds=15 * 60,
    )
    await enforce_rate_limit(
        redis,
        f"rl:email-verification:request:ip:{ip}",
        limit=settings.rate_limit_email_verification_ip_per_15_minutes,
        window_seconds=15 * 60,
    )


async def _enforce_email_verification_confirm_limits(redis: RedisDep, user_id: UUID, ip: str) -> None:
    limit = get_settings().rate_limit_email_verification_confirm_per_15_minutes
    await enforce_rate_limit(
        redis,
        f"rl:email-verification:confirm:user:{user_id}",
        limit=limit,
        window_seconds=15 * 60,
    )
    await enforce_rate_limit(
        redis,
        f"rl:email-verification:confirm:ip:{ip}",
        limit=limit,
        window_seconds=15 * 60,
    )


@router.post("/register", status_code=201)
async def register(req: RegisterRequest, db: DBDep, request: Request, redis: RedisDep) -> dict:
    ip = get_client_ip(request)
    await _enforce_auth_rate_limits(redis, "register", ip, req.username)
    try:
        user = await AuthService.register(db, req)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return {"id": str(user.id), "username": user.username, "email": user.email}


@router.post("/login", response_model=TokenPair)
async def login(req: LoginRequest, db: DBDep, request: Request, redis: RedisDep) -> TokenPair:
    settings = get_settings()
    ip = get_client_ip(request)
    await _enforce_auth_rate_limits(redis, "login", ip, req.username_or_email)
    try:
        return await AuthService.login(
            db,
            req,
            user_agent=request.headers.get("user-agent"),
            ip=ip,
            refresh_ttl_days=settings.jwt_refresh_ttl_days,
            absolute_ttl_days=settings.session_absolute_ttl_days,
        )
    except AppError as exc:
        if exc.code == "AUTH_INVALID":
            await log_event(
                db,
                "security.login_failed",
                {
                    "identity_prefix": req.username_or_email.strip().lower()[:32],
                    "identity_sha256": sha256_hex(req.username_or_email.strip().lower()),
                    "ip": ip,
                },
                channel_id=None,
                actor_user_id=None,
            )
            await db.commit()
        raise to_http_exception(exc) from exc


@router.post("/browser/login", response_model=BrowserAccessTokenResponse)
async def browser_login(
    req: LoginRequest,
    db: DBDep,
    request: Request,
    response: Response,
    redis: RedisDep,
) -> BrowserAccessTokenResponse:
    """Create the existing server-side session without exposing refresh JSON."""

    settings = get_settings()
    ip = get_client_ip(request)
    try:
        validate_browser_origin(request, settings)
        await _enforce_auth_rate_limits(redis, "browser-login", ip, req.username_or_email)
        pair = await AuthService.login(
            db,
            req,
            user_agent=request.headers.get("user-agent"),
            ip=ip,
            refresh_ttl_days=settings.jwt_refresh_ttl_days,
            absolute_ttl_days=settings.session_absolute_ttl_days,
        )
    except AppError as exc:
        if exc.code == "AUTH_INVALID":
            await log_event(
                db,
                "security.login_failed",
                {
                    "identity_prefix": req.username_or_email.strip().lower()[:32],
                    "identity_sha256": sha256_hex(req.username_or_email.strip().lower()),
                    "ip": ip,
                },
                channel_id=None,
                actor_user_id=None,
            )
            await db.commit()
        raise to_http_exception(exc) from exc

    set_browser_auth_cookies(response, pair.refresh_token, settings=settings)
    return BrowserAccessTokenResponse(access_token=pair.access_token)


@router.get("/browser/csrf", response_model=BrowserCsrfResponse)
async def browser_csrf(request: Request, response: Response) -> BrowserCsrfResponse:
    settings = get_settings()
    # Same-origin GET requests do not consistently carry Origin. If it is
    # present, however, never let an untrusted site plant browser state.
    if request.headers.get("origin"):
        try:
            validate_browser_origin(request, settings)
        except AppError as exc:
            raise to_http_exception(exc) from exc
    token = set_csrf_cookie(response, settings=settings)
    return BrowserCsrfResponse(csrf_token=token)


@router.post("/email-verification/request", response_model=EmailVerificationRequestResponse)
async def request_email_verification(
    db: DBDep,
    auth: CurrentAuthDep,
    request: Request,
    redis: RedisDep,
) -> EmailVerificationRequestResponse:
    ip = get_client_ip(request)
    await _enforce_email_verification_request_limits(redis, auth.user.id, ip)
    try:
        result = await EmailVerificationService.request_verification(
            db,
            auth.user.id,
            request.app.state.verification_mailer,
        )
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return EmailVerificationRequestResponse(status=result.status, expires_at=result.expires_at)


@router.post("/email-verification/confirm", response_model=EmailVerificationConfirmResponse)
async def confirm_email_verification(
    req: EmailVerificationConfirmRequest,
    db: DBDep,
    auth: CurrentAuthDep,
    request: Request,
    redis: RedisDep,
) -> EmailVerificationConfirmResponse:
    ip = get_client_ip(request)
    await _enforce_email_verification_confirm_limits(redis, auth.user.id, ip)
    try:
        result = await EmailVerificationService.confirm(db, auth.user.id, req.token)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return EmailVerificationConfirmResponse(verified_at=result.verified_at)


@router.post("/refresh", response_model=TokenPair)
async def refresh(req: RefreshRequest, db: DBDep, request: Request, redis: RedisDep) -> TokenPair:
    settings = get_settings()
    ip = get_client_ip(request)
    await _enforce_auth_rate_limits(redis, "refresh", ip, ip)
    try:
        return await AuthService.refresh(
            db,
            req.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip=ip,
            refresh_ttl_days=settings.jwt_refresh_ttl_days,
        )
    except RefreshTokenReplayError as exc:
        await dispatch_auth_control(
            redis,
            request.app.state.ws_manager,
            AuthControlEvent.for_session(exc.revocation),
        )
        raise to_http_exception(exc) from exc
    except (AppError, ValueError) as exc:
        if isinstance(exc, AppError):
            raise to_http_exception(exc) from exc
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_EXPIRED", "message": str(exc), "details": None},
        ) from exc


@router.post("/browser/refresh", response_model=BrowserAccessTokenResponse)
async def browser_refresh(
    db: DBDep,
    request: Request,
    response: Response,
    redis: RedisDep,
) -> BrowserAccessTokenResponse:
    settings = get_settings()
    ip = get_client_ip(request)
    try:
        cookie_pair = validate_browser_csrf(request, settings)
        await _enforce_auth_rate_limits(redis, "browser-refresh", ip, ip)
        pair = await AuthService.refresh(
            db,
            cookie_pair.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip=ip,
            refresh_ttl_days=settings.jwt_refresh_ttl_days,
        )
    except RefreshTokenReplayError as exc:
        await dispatch_auth_control(
            redis,
            request.app.state.ws_manager,
            AuthControlEvent.for_session(exc.revocation),
        )
        raise to_http_exception(exc) from exc
    except AppError as exc:
        raise to_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_EXPIRED", "message": str(exc), "details": None},
        ) from exc

    # Refresh and CSRF cookies rotate together. Only the short-lived access JWT
    # is returned to JavaScript and it remains memory-only in the web client.
    set_browser_auth_cookies(response, pair.refresh_token, settings=settings)
    return BrowserAccessTokenResponse(access_token=pair.access_token)


@router.post("/logout")
async def logout(req: LogoutRequest, db: DBDep, request: Request, redis: RedisDep) -> dict:
    try:
        revocation = await AuthService.logout(db, req.refresh_token)
        await dispatch_auth_control(redis, request.app.state.ws_manager, AuthControlEvent.for_session(revocation))
    except RefreshTokenReplayError as exc:
        await dispatch_auth_control(
            redis,
            request.app.state.ws_manager,
            AuthControlEvent.for_session(exc.revocation),
        )
        raise to_http_exception(exc) from exc
    except (AppError, ValueError) as exc:
        if isinstance(exc, AppError):
            raise to_http_exception(exc) from exc
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_EXPIRED", "message": str(exc), "details": None},
        ) from exc
    return {"status": "ok"}


@router.post("/browser/logout")
async def browser_logout(db: DBDep, request: Request, response: Response, redis: RedisDep) -> dict:
    settings = get_settings()
    try:
        cookie_pair = validate_browser_csrf(request, settings)
        revocation = await AuthService.logout(db, cookie_pair.refresh_token)
        await dispatch_auth_control(redis, request.app.state.ws_manager, AuthControlEvent.for_session(revocation))
    except RefreshTokenReplayError as exc:
        await dispatch_auth_control(
            redis,
            request.app.state.ws_manager,
            AuthControlEvent.for_session(exc.revocation),
        )
        raise to_http_exception(exc) from exc
    except AppError as exc:
        raise to_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_EXPIRED", "message": str(exc), "details": None},
        ) from exc

    clear_browser_auth_cookies(response, settings=settings)
    return {"status": "ok"}


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(db: DBDep, user: CurrentUserDep) -> SessionListResponse:
    sessions = await AuthService.list_sessions(db, user.id)
    return SessionListResponse(
        items=[
            SessionResponse(
                id=s.id,
                created_at=s.created_at,
                expires_at=s.expires_at,
                absolute_expires_at=s.absolute_expires_at,
                revoked_at=s.revoked_at,
                user_agent=s.user_agent,
                ip=s.ip,
            )
            for s in sessions
        ]
    )


@router.post("/logout_all", response_model=LogoutAllResponse)
async def logout_all(
    db: DBDep,
    user: CurrentUserDep,
    request: Request,
    response: Response,
    redis: RedisDep,
) -> LogoutAllResponse:
    revocation = await AuthService.logout_all(db, user.id)
    await dispatch_auth_control(redis, request.app.state.ws_manager, AuthControlEvent.for_user(revocation))
    # The access token authorizes this endpoint, so clearing the current
    # browser's stale cookies does not introduce cookie-derived authority.
    clear_browser_auth_cookies(response)
    return LogoutAllResponse(revoked_count=revocation.revoked_count)


@router.put("/password", response_model=PasswordChangeResponse)
async def change_password(
    req: ChangePasswordRequest,
    db: DBDep,
    auth: CurrentAuthDep,
    request: Request,
    response: Response,
    redis: RedisDep,
) -> PasswordChangeResponse:
    await _enforce_auth_rate_limits(redis, "password-change", get_client_ip(request), str(auth.user.id))
    try:
        revocation = await AuthService.change_password(db, auth.user.id, req)
    except AppError as exc:
        raise to_http_exception(exc) from exc

    await dispatch_auth_control(redis, request.app.state.ws_manager, AuthControlEvent.for_user(revocation))
    clear_browser_auth_cookies(response)
    return PasswordChangeResponse(revoked_sessions=revocation.revoked_count)


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    db: DBDep,
    user: CurrentUserDep,
    request: Request,
    redis: RedisDep,
) -> dict:
    try:
        revocation = await AuthService.revoke_session(db, user.id, UUID(session_id))
        await dispatch_auth_control(redis, request.app.state.ws_manager, AuthControlEvent.for_session(revocation))
    except (AppError, ValueError) as exc:
        if isinstance(exc, AppError):
            raise to_http_exception(exc) from exc
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "invalid session id", "details": None},
        ) from exc
    return {"status": "ok"}


@router.post("/ws-ticket", response_model=WebSocketTicketResponse)
async def create_websocket_ticket(auth: CurrentAuthDep, redis: RedisDep) -> WebSocketTicketResponse:
    await enforce_rate_limit(
        redis,
        f"rl:websocket:ticket:{auth.user.id}",
        limit=get_settings().rate_limit_websocket_per_minute,
        window_seconds=60,
    )
    ticket = await WebSocketTicketService.issue(redis, auth)
    return WebSocketTicketResponse(ticket=ticket.value, expires_at=ticket.expires_at)
