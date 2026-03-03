from collections.abc import AsyncGenerator
from typing import Annotated

import aio_pika
from fastapi import Depends, Header, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import AuthService


async def get_redis(request: Request) -> Redis:
    return request.app.state.redis


async def get_amqp(request: Request) -> aio_pika.RobustConnection:
    return request.app.state.amqp


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return await AuthService.get_user_from_access_token(db, token)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc


DBDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
RedisDep = Annotated[Redis, Depends(get_redis)]
AMQPDep = Annotated[aio_pika.RobustConnection, Depends(get_amqp)]
