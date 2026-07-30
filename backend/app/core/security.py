from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


# Hashes password; the application layers use it as shared infrastructure.
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


# Verifies password; the application layers use it as shared infrastructure.
def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


# Creates access token; the application layers use it as shared infrastructure.
def create_access_token(user_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_access_ttl_min)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


# Creates refresh token; the application layers use it as shared infrastructure.
def create_refresh_token(user_id: UUID, session_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.jwt_refresh_ttl_days)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


# Decodes token; the application layers use it as shared infrastructure.
def decode_token(token: str) -> dict:
    settings = get_settings()
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    # Handle `JWTError` here so this workflow can recover or report the failure consistently.
    except JWTError as exc:
        raise ValueError("invalid token") from exc
