import aio_pika
from fastapi import APIRouter, Request
from redis.asyncio import Redis
from sqlalchemy import text

from app.db.session import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
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

    return {"status": "ok", "db": db_ok, "redis": redis_ok, "rabbitmq": amqp_ok}
