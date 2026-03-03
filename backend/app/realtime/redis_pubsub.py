from redis.asyncio import Redis


def user_pubsub_channel(user_id: str) -> str:
    return f"rt.user.{user_id}"


def online_users_key() -> str:
    return "rt.online_users"


async def mark_user_online(redis: Redis, user_id: str) -> None:
    await redis.sadd(online_users_key(), user_id)


async def mark_user_offline(redis: Redis, user_id: str) -> None:
    await redis.srem(online_users_key(), user_id)
