def online_users_key() -> str:
    return "rt.online_users"


def user_pubsub_channel(user_id: str) -> str:
    return f"rt.user.{user_id}"


def user_queue_name(user_id: str) -> str:
    return f"user.{user_id}"
