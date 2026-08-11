from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from starlette.requests import Request

from app.api.routes import auth as auth_routes
from app.api.routes.health import health
from app.core.browser_security import set_browser_auth_cookies
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import decode_token
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.users import UpdateMeRequest
from app.services.auth_service import AuthService


SECURE_JWT_SECRET = "phase8-secure-jwt-secret-with-enough-diversity-0123456789"
SECURE_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
TEST_ORIGIN = "http://testserver"


@pytest.fixture(autouse=True)
def _phase8_browser_origin(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", f'["{TEST_ORIGIN}"]')
    get_settings.cache_clear()


class _RateRedis:
    async def eval(self, script: str, numkeys: int, key: str, window_seconds: int):
        return [1, window_seconds]


class _Manager:
    pass


def _request(
    path: str,
    *,
    origin: str | None = TEST_ORIGIN,
    cookies: dict[str, str] | None = None,
    csrf: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        headers.append((b"cookie", cookie_header.encode("ascii")))
    if csrf is not None:
        headers.append((b"x-csrf-token", csrf.encode("ascii")))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 4321),
            "server": ("testserver", 80),
            "app": SimpleNamespace(state=SimpleNamespace(ws_manager=_Manager())),
        }
    )


def _set_cookie_headers(response: Response) -> list[str]:
    return [value.decode("latin-1") for key, value in response.raw_headers if key.lower() == b"set-cookie"]


def _cookie_value(response: Response, name: str) -> str:
    jar = SimpleCookie()
    for header in _set_cookie_headers(response):
        jar.load(header)
    return jar[name].value


async def _browser_login(db, username: str = "phase8_browser"):
    await AuthService.register(
        db,
        RegisterRequest(username=username, email=f"{username}@example.com", password="Password123!"),
    )
    response = Response()
    result = await auth_routes.browser_login(
        LoginRequest(username_or_email=username, password="Password123!"),
        db,
        _request("/v1/auth/browser/login"),
        response,
        _RateRedis(),
    )
    settings = get_settings()
    cookies = {
        settings.browser_refresh_cookie_name: _cookie_value(response, settings.browser_refresh_cookie_name),
        settings.browser_csrf_cookie_name: _cookie_value(response, settings.browser_csrf_cookie_name),
    }
    return result, response, cookies


@pytest.mark.asyncio
async def test_browser_login_hides_refresh_json_and_sets_httponly_cookie(db_session) -> None:
    result, response, _ = await _browser_login(db_session)
    headers = _set_cookie_headers(response)

    assert result.access_token
    assert "refresh_token" not in result.model_dump()
    refresh_header = next(value for value in headers if "messaging_refresh=" in value)
    assert "HttpOnly" in refresh_header
    assert "SameSite=strict" in refresh_header


def test_production_cookie_is_secure_httponly_host_only_and_strict() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret=SECURE_JWT_SECRET,
        message_encryption_key=SECURE_FERNET_KEY,
        cors_origins=["https://chat.example.com"],
        trusted_hosts=["chat.example.com"],
    )
    response = Response()
    set_browser_auth_cookies(response, "signed-refresh-value", settings=settings)
    refresh_header = next(value for value in _set_cookie_headers(response) if "messaging_refresh=" in value)

    assert "__Host-messaging_refresh=" in refresh_header
    assert "Secure" in refresh_header
    assert "HttpOnly" in refresh_header
    assert "SameSite=strict" in refresh_header
    assert "Path=/" in refresh_header
    assert "Domain=" not in refresh_header


@pytest.mark.asyncio
async def test_browser_refresh_rejects_missing_and_mismatched_csrf(db_session) -> None:
    _, _, cookies = await _browser_login(db_session, "phase8_csrf")

    for csrf in (None, "different-csrf-value"):
        with pytest.raises(HTTPException) as error:
            await auth_routes.browser_refresh(
                db_session,
                _request("/v1/auth/browser/refresh", cookies=cookies, csrf=csrf),
                Response(),
                _RateRedis(),
            )
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_cross_origin_browser_refresh_is_denied(db_session) -> None:
    _, _, cookies = await _browser_login(db_session, "phase8_origin")
    csrf = cookies[get_settings().browser_csrf_cookie_name]

    with pytest.raises(HTTPException) as error:
        await auth_routes.browser_refresh(
            db_session,
            _request(
                "/v1/auth/browser/refresh",
                origin="https://attacker.example",
                cookies=cookies,
                csrf=csrf,
            ),
            Response(),
            _RateRedis(),
        )
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_browser_refresh_rotates_and_old_cookie_replay_revokes_family(db_session, monkeypatch) -> None:
    first_access, _, first_cookies = await _browser_login(db_session, "phase8_rotate")
    settings = get_settings()
    first_refresh = first_cookies[settings.browser_refresh_cookie_name]
    first_csrf = first_cookies[settings.browser_csrf_cookie_name]

    refresh_response = Response()
    second_access = await auth_routes.browser_refresh(
        db_session,
        _request("/v1/auth/browser/refresh", cookies=first_cookies, csrf=first_csrf),
        refresh_response,
        _RateRedis(),
    )
    second_refresh = _cookie_value(refresh_response, settings.browser_refresh_cookie_name)
    assert second_access.access_token
    assert second_refresh != first_refresh

    async def _dispatch(*args, **kwargs):
        return None

    monkeypatch.setattr(auth_routes, "dispatch_auth_control", _dispatch)
    with pytest.raises(HTTPException) as replay:
        await auth_routes.browser_refresh(
            db_session,
            _request("/v1/auth/browser/refresh", cookies=first_cookies, csrf=first_csrf),
            Response(),
            _RateRedis(),
        )
    assert replay.value.status_code == 401
    assert replay.value.detail["code"] == "AUTH_REPLAY_DETECTED"

    with pytest.raises(AppError):
        await AuthService.get_access_context(db_session, second_access.access_token)


@pytest.mark.asyncio
async def test_browser_logout_revokes_session_and_clears_both_cookies(db_session, monkeypatch) -> None:
    access, _, cookies = await _browser_login(db_session, "phase8_logout")
    settings = get_settings()

    async def _dispatch(*args, **kwargs):
        return None

    monkeypatch.setattr(auth_routes, "dispatch_auth_control", _dispatch)
    response = Response()
    result = await auth_routes.browser_logout(
        db_session,
        _request(
            "/v1/auth/browser/logout",
            cookies=cookies,
            csrf=cookies[settings.browser_csrf_cookie_name],
        ),
        response,
        _RateRedis(),
    )

    assert result == {"status": "ok"}
    headers = _set_cookie_headers(response)
    assert sum("Max-Age=0" in value for value in headers) == 2
    with pytest.raises(AppError):
        await AuthService.get_access_context(db_session, access.access_token)


@pytest.mark.asyncio
async def test_server_side_revocation_makes_browser_refresh_fail(db_session) -> None:
    access, _, cookies = await _browser_login(db_session, "phase8_revoked")
    settings = get_settings()
    claims = decode_token(access.access_token)
    await AuthService.revoke_session(db_session, UUID(claims["sub"]), UUID(claims["sid"]))

    with pytest.raises(HTTPException) as error:
        await auth_routes.browser_refresh(
            db_session,
            _request(
                "/v1/auth/browser/refresh",
                cookies=cookies,
                csrf=cookies[settings.browser_csrf_cookie_name],
            ),
            Response(),
            _RateRedis(),
        )
    assert error.value.status_code == 401


def test_development_cookie_mode_remains_http_only_without_secure() -> None:
    settings = Settings(_env_file=None, environment="test", auth_cookie_secure=False)
    response = Response()
    set_browser_auth_cookies(response, "development-refresh", settings=settings)
    refresh_header = next(value for value in _set_cookie_headers(response) if "messaging_refresh=" in value)

    assert "messaging_refresh=" in refresh_header
    assert "__Host-" not in refresh_header
    assert "HttpOnly" in refresh_header
    assert "Secure" not in refresh_header


def test_production_configuration_rejects_wildcard_cors_and_insecure_cookie() -> None:
    secure = {
        "_env_file": None,
        "environment": "production",
        "jwt_secret": SECURE_JWT_SECRET,
        "message_encryption_key": SECURE_FERNET_KEY,
        "trusted_hosts": ["chat.example.com"],
    }
    with pytest.raises(ValidationError):
        Settings(**secure, cors_origins=["*"])
    with pytest.raises(ValidationError):
        Settings(**secure, cors_origins=["https://chat.example.com"], auth_cookie_secure=False)

    settings = Settings(**secure, cors_origins=["https://chat.example.com"])
    assert settings.browser_cookie_secure is True
    assert settings.api_docs_enabled is False


def test_development_docs_stay_enabled_and_public_health_is_minimal() -> None:
    settings = Settings(_env_file=None, environment="test")
    assert settings.api_docs_enabled is True
    assert health.__name__ == "health"


@pytest.mark.asyncio
async def test_public_liveness_does_not_expose_dependency_names() -> None:
    assert await health() == {"status": "ok"}


def test_production_external_profile_media_requires_https(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", SECURE_JWT_SECRET)
    monkeypatch.setenv("MESSAGE_ENCRYPTION_KEY", SECURE_FERNET_KEY)
    monkeypatch.setenv("CORS_ORIGINS", '["https://chat.example.com"]')
    monkeypatch.setenv("TRUSTED_HOSTS", '["chat.example.com"]')
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        UpdateMeRequest(avatar_url="http://media.example/avatar.png")
    assert UpdateMeRequest(avatar_url="https://media.example/avatar.png").avatar_url.startswith("https://")


def test_frontend_auth_uses_memory_only_tokens_and_browser_refresh_bootstrap() -> None:
    frontend = Path(__file__).resolve().parents[3] / "frontend" / "src"
    auth_sources = [
        frontend / "store" / "authStore.ts",
        frontend / "hooks" / "use-auth.ts",
        frontend / "services" / "api" / "client.ts",
        frontend / "services" / "auth" / "browser-session.ts",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in auth_sources)
    lowered = combined.lower()

    assert "chat_refresh_token" not in combined
    assert "chat_access_token" not in combined
    assert "localstorage" not in lowered
    assert "sessionstorage" not in lowered
    assert "indexeddb" not in lowered
    assert "persist(" not in combined
    assert "/auth/browser/refresh" in combined
    assert "refreshAccessToken(baseUrl)" in combined

    all_matches = []
    for path in frontend.rglob("*.ts*"):
        source = path.read_text(encoding="utf-8")
        if any(term in source for term in ("localStorage", "sessionStorage", "IndexedDB", "persist(")):
            all_matches.append(path.relative_to(frontend).as_posix())
    assert all_matches == ["store/chatPreferencesStore.ts"]
