from redis.asyncio import Redis

from app.core.identifiers import normalize_username


# Builds the Redis pub/sub channel for a user; the WebSocket layer uses it for realtime client delivery.
def user_pubsub_channel(username: str) -> str:
    return f"rt.user.{normalize_username(username)}"


# Builds the Redis key that tracks online users; the WebSocket layer uses it for realtime client delivery.
def online_users_key() -> str:
    return "rt.online_users"


# Marks user online; the WebSocket layer uses it for realtime client delivery.
async def mark_user_online(redis: Redis, username: str) -> None:
    await redis.sadd(online_users_key(), normalize_username(username))


# Marks user offline; the WebSocket layer uses it for realtime client delivery.
async def mark_user_offline(redis: Redis, username: str) -> None:
    await redis.srem(online_users_key(), normalize_username(username))
