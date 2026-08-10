import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _timestamp(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


def create_access_token(user_id: UUID, session_id: UUID, auth_expires_at: datetime | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.jwt_access_ttl_min)
    if auth_expires_at is not None:
        expires_at = min(expires_at, auth_expires_at)
    # The stable session id makes logout and server-side revocation effective
    # for already-issued access tokens, not only for refresh tokens.
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "type": "access",
        "iat": _timestamp(now),
        "exp": _timestamp(expires_at),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(user_id: UUID, session_id: UUID, expires_at: datetime | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    token_expires_at = expires_at or (now + timedelta(days=settings.jwt_refresh_ttl_days))
    # The session id links this refresh token to a revocable database session.
    # A random jti guarantees that rotations within the same second still
    # produce distinct token hashes for reliable replay detection.
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "jti": secrets.token_urlsafe(18),
        "type": "refresh",
        "iat": _timestamp(now),
        "exp": _timestamp(token_expires_at),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        # The service layer maps token decode failures to API-specific auth errors.
        raise ValueError("invalid token") from exc
