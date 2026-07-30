from redis.asyncio import Redis


class RateLimitService:
    @staticmethod
    async def hit(redis: Redis, key: str, limit: int, window_seconds: int) -> int | None:
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window_seconds)
            if count > limit:
                ttl = await redis.ttl(key)
                return int(ttl if ttl and ttl > 0 else 1)
        except Exception:
            return None
        return None
