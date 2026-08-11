import hmac
import secrets
from dataclasses import dataclass

from fastapi import Request, Response

from app.core.config import Settings, get_settings
from app.core.errors import AppError


CSRF_HEADER_NAME = "X-CSRF-Token"


@dataclass(frozen=True)
class BrowserCookiePair:
    refresh_token: str
    csrf_token: str


def new_csrf_token() -> str:
    # This random value carries no authentication authority. It only proves
    # that JavaScript can read the same-site, non-HttpOnly CSRF cookie.
    return secrets.token_urlsafe(32)


def validate_browser_origin(request: Request, settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    origin = request.headers.get("origin", "").strip().rstrip("/")
    allowed = {value.strip().rstrip("/") for value in active_settings.cors_origins}
    if not origin or origin not in allowed:
        raise AppError("browser request origin is not allowed", 403, code="CSRF_ORIGIN_DENIED")


def validate_browser_csrf(request: Request, settings: Settings | None = None) -> BrowserCookiePair:
    active_settings = settings or get_settings()
    validate_browser_origin(request, active_settings)

    refresh_token = request.cookies.get(active_settings.browser_refresh_cookie_name, "")
    csrf_cookie = request.cookies.get(active_settings.browser_csrf_cookie_name, "")
    csrf_header = request.headers.get(CSRF_HEADER_NAME, "")
    if not refresh_token:
        raise AppError("browser refresh credential is missing", 401, code="AUTH_EXPIRED")
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise AppError("invalid CSRF token", 403, code="CSRF_INVALID")
    return BrowserCookiePair(refresh_token=refresh_token, csrf_token=csrf_cookie)


def set_browser_auth_cookies(
    response: Response,
    refresh_token: str,
    *,
    settings: Settings | None = None,
) -> str:
    active_settings = settings or get_settings()
    csrf_token = new_csrf_token()
    max_age = active_settings.jwt_refresh_ttl_days * 24 * 60 * 60
    shared = {
        "secure": active_settings.browser_cookie_secure,
        "samesite": active_settings.auth_cookie_samesite,
        "path": "/",
        "max_age": max_age,
    }
    response.set_cookie(
        active_settings.browser_refresh_cookie_name,
        refresh_token,
        httponly=True,
        **shared,
    )
    response.set_cookie(
        active_settings.browser_csrf_cookie_name,
        csrf_token,
        httponly=False,
        **shared,
    )
    return csrf_token


def set_csrf_cookie(response: Response, *, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    csrf_token = new_csrf_token()
    response.set_cookie(
        active_settings.browser_csrf_cookie_name,
        csrf_token,
        httponly=False,
        secure=active_settings.browser_cookie_secure,
        samesite=active_settings.auth_cookie_samesite,
        path="/",
        max_age=active_settings.jwt_refresh_ttl_days * 24 * 60 * 60,
    )
    return csrf_token


def clear_browser_auth_cookies(response: Response, *, settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    shared = {
        "secure": active_settings.browser_cookie_secure,
        "samesite": active_settings.auth_cookie_samesite,
        "path": "/",
    }
    response.delete_cookie(active_settings.browser_refresh_cookie_name, httponly=True, **shared)
    response.delete_cookie(active_settings.browser_csrf_cookie_name, httponly=False, **shared)
