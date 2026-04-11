from redis.asyncio import Redis


def user_pubsub_channel(username: str) -> str:
    return f"rt.user.{username}"


def online_users_key() -> str:
    return "rt.online_users"


async def mark_user_online(redis: Redis, username: str) -> None:
    await redis.sadd(online_users_key(), username)


async def mark_user_offline(redis: Redis, username: str) -> None:
    await redis.srem(online_users_key(), username)
