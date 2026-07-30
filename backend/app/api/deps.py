from collections.abc import AsyncGenerator
from typing import Annotated

import aio_pika
from fastapi import Depends, Header, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, to_http_exception
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import AuthService


# Retrieves redis; the surrounding module uses it in the project workflow.
async def get_redis(request: Request) -> Redis:
    return request.app.state.redis


# Retrieves amqp; the surrounding module uses it in the project workflow.
async def get_amqp(request: Request) -> aio_pika.RobustConnection:
    return request.app.state.amqp


# Retrieves current user; the surrounding module uses it in the project workflow.
async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    # Reject the operation when `not authorization or not authorization.lower().startswith('bearer ')` to keep invalid state from progressing.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_INVALID", "message": "missing bearer token", "details": None},
        )
    token = authorization.split(" ", 1)[1].strip()
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return await AuthService.get_user_from_access_token(db, token)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    # Handle `ValueError` here so this workflow can recover or report the failure consistently.
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_EXPIRED", "message": str(exc) or "invalid token", "details": None},
        ) from exc


DBDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
RedisDep = Annotated[Redis, Depends(get_redis)]
AMQPDep = Annotated[aio_pika.RobustConnection, Depends(get_amqp)]


# Retrieves current superadmin; the surrounding module uses it in the project workflow.
async def get_current_superadmin(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    # Return early when `user.is_superadmin` because the remaining work is not applicable.
    if user.is_superadmin:
        return user

    from app.services.event_service import log_event

    await log_event(
        db,
        "security.superadmin_access_denied",
        {"actor_user_id": str(user.id)},
        actor_user_id=user.id,
    )
    await db.commit()
    raise HTTPException(
        status_code=403,
        detail={"code": "SUPERADMIN_REQUIRED", "message": "superadmin access required", "details": None},
    )


SuperadminDep = Annotated[User, Depends(get_current_superadmin)]
