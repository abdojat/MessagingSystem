from redis.asyncio import Redis

from app.core.identifiers import normalize_username


def user_pubsub_channel(username: str) -> str:
    return f"rt.user.{normalize_username(username)}"


def online_users_key() -> str:
    return "rt.online_users"


async def mark_user_online(redis: Redis, username: str) -> None:
    await redis.sadd(online_users_key(), normalize_username(username))


async def mark_user_offline(redis: Redis, username: str) -> None:
    await redis.srem(online_users_key(), normalize_username(username))
