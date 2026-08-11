import aio_pika
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.db.session import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Public liveness without infrastructure names or topology details."""

    return {"status": "ok"}


@router.get("/ready", response_model=None)
async def readiness(request: Request) -> JSONResponse:
    """Internal dependency readiness used by container orchestration only."""

    db_ok = False
    redis_ok = False
    amqp_ok = False

    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False

    try:
        redis: Redis = request.app.state.redis
        await redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    try:
        amqp: aio_pika.RobustConnection = request.app.state.amqp
        ch = await amqp.channel()
        await ch.close()
        amqp_ok = True
    except Exception:
        amqp_ok = False

    ready = db_ok and redis_ok and amqp_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "unavailable",
            "db": db_ok,
            "redis": redis_ok,
            "rabbitmq": amqp_ok,
        },
    )
