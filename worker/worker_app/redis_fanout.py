def online_users_key() -> str:
    return "rt.online_users"


def user_pubsub_channel(username: str) -> str:
    return f"rt.user.{username}"


def user_queue_name(username: str) -> str:
    return f"user.{username}"
