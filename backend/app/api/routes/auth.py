from fastapi import APIRouter, HTTPException, Request

from app.api.deps import DBDep
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest, TokenPair
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(req: RegisterRequest, db: DBDep) -> dict:
    try:
        user = await AuthService.register(db, req)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"id": str(user.id), "username": user.username, "email": user.email}


@router.post("/login", response_model=TokenPair)
async def login(req: LoginRequest, db: DBDep, request: Request) -> TokenPair:
    settings = get_settings()
    try:
        return await AuthService.login(
            db,
            req,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
            refresh_ttl_days=settings.jwt_refresh_ttl_days,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/refresh", response_model=TokenPair)
async def refresh(req: RefreshRequest, db: DBDep, request: Request) -> TokenPair:
    settings = get_settings()
    try:
        return await AuthService.refresh(
            db,
            req.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
            refresh_ttl_days=settings.jwt_refresh_ttl_days,
        )
    except (AppError, ValueError) as exc:
        code = exc.status_code if isinstance(exc, AppError) else 401
        msg = exc.message if isinstance(exc, AppError) else str(exc)
        raise HTTPException(status_code=code, detail=msg) from exc


@router.post("/logout")
async def logout(req: LogoutRequest, db: DBDep) -> dict:
    try:
        await AuthService.logout(db, req.refresh_token)
    except (AppError, ValueError) as exc:
        code = exc.status_code if isinstance(exc, AppError) else 401
        msg = exc.message if isinstance(exc, AppError) else str(exc)
        raise HTTPException(status_code=code, detail=msg) from exc
    return {"status": "ok"}
