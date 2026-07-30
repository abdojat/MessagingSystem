from redis.asyncio import Redis


# Groups the rate limit business operations; API route handlers call it to enforce application business rules.
class RateLimitService:
    # Records; API route handlers call it to enforce application business rules.
    @staticmethod
    async def hit(redis: Redis, key: str, limit: int, window_seconds: int) -> int | None:
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            count = await redis.incr(key)
            # Run this conditional step only when `count == 1` is true.
            if count == 1:
                await redis.expire(key, window_seconds)
            # Run this conditional step only when `count > limit` is true.
            if count > limit:
                ttl = await redis.ttl(key)
                return int(ttl if ttl and ttl > 0 else 1)
        # Handle `Exception` here so this workflow can recover or report the failure consistently.
        except Exception:
            return None
        return None
