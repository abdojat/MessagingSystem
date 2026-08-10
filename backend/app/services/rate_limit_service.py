import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException
from redis.asyncio import Redis


FailurePolicy = Literal["local", "allow"]


@dataclass(frozen=True)
class RateLimitResult:
    retry_after_seconds: int | None
    backend: Literal["redis", "local", "bypassed"]


class RateLimitService:
    """Redis limiter with a bounded per-process emergency fallback.

    The local fallback intentionally has a capped key set so an outage cannot
    turn attacker-controlled identities into an in-process memory exhaustion
    vector. It is not a replacement for distributed Redis enforcement, but it
    keeps sensitive endpoints bounded on every API instance during an outage.
    """

    _local_windows: OrderedDict[str, tuple[float, int]] = OrderedDict()
    _local_lock = asyncio.Lock()
    _max_local_keys = 10_000

    @classmethod
    async def hit(
        cls,
        redis: Redis,
        key: str,
        limit: int,
        window_seconds: int,
        *,
        failure_policy: FailurePolicy = "local",
    ) -> RateLimitResult:
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window_seconds)
            if count > limit:
                ttl = await redis.ttl(key)
                return RateLimitResult(int(ttl if ttl and ttl > 0 else 1), "redis")
            return RateLimitResult(None, "redis")
        except Exception:
            if failure_policy == "allow":
                return RateLimitResult(None, "bypassed")
            return await cls._hit_local(key, limit, window_seconds)

    @classmethod
    async def _hit_local(cls, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.monotonic()
        async with cls._local_lock:
            window_start, count = cls._local_windows.pop(key, (now, 0))
            if now - window_start >= window_seconds:
                window_start, count = now, 0
            count += 1
            cls._local_windows[key] = (window_start, count)
            while len(cls._local_windows) > cls._max_local_keys:
                cls._local_windows.popitem(last=False)
            retry_after = max(1, int(window_seconds - (now - window_start))) if count > limit else None
            return RateLimitResult(retry_after, "local")

    @classmethod
    def reset_local_for_tests(cls) -> None:
        cls._local_windows.clear()


async def enforce_rate_limit(
    redis: Redis,
    key: str,
    *,
    limit: int,
    window_seconds: int,
    failure_policy: FailurePolicy = "local",
) -> None:
    result = await RateLimitService.hit(
        redis,
        key,
        limit,
        window_seconds,
        failure_policy=failure_policy,
    )
    if result.retry_after_seconds is None:
        return
    retry_after = result.retry_after_seconds
    raise HTTPException(
        status_code=429,
        detail={
            "code": "RATE_LIMITED",
            "message": "rate limit exceeded",
            "details": {"retry_after_seconds": retry_after},
        },
        headers={"Retry-After": str(retry_after)},
    )
