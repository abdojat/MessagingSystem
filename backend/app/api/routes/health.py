import aio_pika
from fastapi import APIRouter, Request
from redis.asyncio import Redis
from sqlalchemy import text

from app.db.session import SessionLocal

router = APIRouter(tags=["health"])


# Reports API and dependency health; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/health")
async def health(request: Request) -> dict:
    db_ok = False
    redis_ok = False
    amqp_ok = False

    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        # Keep `SessionLocal()` active while this scoped operation is performed.
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    # Handle `Exception` here so this workflow can recover or report the failure consistently.
    except Exception:
        db_ok = False

    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        redis: Redis = request.app.state.redis
        await redis.ping()
        redis_ok = True
    # Handle `Exception` here so this workflow can recover or report the failure consistently.
    except Exception:
        redis_ok = False

    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        amqp: aio_pika.RobustConnection = request.app.state.amqp
        ch = await amqp.channel()
        await ch.close()
        amqp_ok = True
    # Handle `Exception` here so this workflow can recover or report the failure consistently.
    except Exception:
        amqp_ok = False

    return {"status": "ok", "db": db_ok, "redis": redis_ok, "rabbitmq": amqp_ok}
