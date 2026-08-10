import pytest
from pydantic import ValidationError
from starlette.websockets import WebSocket

from app.core import encryption
from app.core.client_ip import get_client_ip
from app.core.config import Settings, get_settings
from app.main import _run_websocket, app
from app.services.rate_limit_service import RateLimitResult, RateLimitService


SECURE_JWT_SECRET = "phase7-repair-jwt-secret-with-sufficient-length-and-diversity-2026"
SECURE_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
TRUSTED_NGINX = "172.31.240.10"


def _websocket(peer: str, forwarded_for: str | None = None) -> WebSocket:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))

    connected = False

    async def receive() -> dict:
        nonlocal connected
        if not connected:
            connected = True
            return {"type": "websocket.connect"}
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(_: dict) -> None:
        return None

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": "/v1/ws",
        "raw_path": b"/v1/ws",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": (peer, 54321),
        "server": ("testserver", 80),
        "subprotocols": [],
        "state": {},
    }
    return WebSocket(scope, receive, send)


def _set_trusted_proxies(monkeypatch, cidrs: str) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", cidrs)
    get_settings.cache_clear()


def test_websocket_direct_connection_resolves_peer_ip(monkeypatch) -> None:
    _set_trusted_proxies(monkeypatch, "[]")
    assert get_client_ip(_websocket("198.51.100.10")) == "198.51.100.10"


def test_websocket_untrusted_peer_cannot_spoof_forwarded_ip(monkeypatch) -> None:
    _set_trusted_proxies(monkeypatch, "[]")
    websocket = _websocket("198.51.100.10", "203.0.113.99")
    assert get_client_ip(websocket) == "198.51.100.10"


def test_websocket_trusted_nginx_resolves_forwarded_client(monkeypatch) -> None:
    _set_trusted_proxies(monkeypatch, f'["{TRUSTED_NGINX}/32"]')
    websocket = _websocket(TRUSTED_NGINX, "198.51.100.20")
    assert get_client_ip(websocket) == "198.51.100.20"


@pytest.mark.asyncio
async def test_websocket_entrypoint_uses_distinct_trusted_proxy_rate_limit_keys(monkeypatch) -> None:
    _set_trusted_proxies(monkeypatch, f'["{TRUSTED_NGINX}/32"]')
    observed_keys: list[str] = []

    async def record_local_hit(key: str, _: int, __: int) -> RateLimitResult:
        observed_keys.append(key)
        return RateLimitResult(None, "local")

    monkeypatch.setattr(app.state, "redis", None, raising=False)
    monkeypatch.setattr(RateLimitService, "_hit_local", record_local_hit)

    await _run_websocket(_websocket(TRUSTED_NGINX, "198.51.100.20"))
    await _run_websocket(_websocket(TRUSTED_NGINX, "198.51.100.21"))

    assert observed_keys == [
        "rl:websocket:connect:198.51.100.20",
        "rl:websocket:connect:198.51.100.21",
    ]


@pytest.mark.asyncio
async def test_websocket_rate_limit_buckets_are_isolated_behind_proxy(monkeypatch) -> None:
    _set_trusted_proxies(monkeypatch, f'["{TRUSTED_NGINX}/32"]')
    client_a = get_client_ip(_websocket(TRUSTED_NGINX, "198.51.100.20"))
    client_b = get_client_ip(_websocket(TRUSTED_NGINX, "198.51.100.21"))
    key_a = f"rl:websocket:connect:{client_a}"
    key_b = f"rl:websocket:connect:{client_b}"

    assert (await RateLimitService._hit_local(key_a, 2, 60)).retry_after_seconds is None
    assert (await RateLimitService._hit_local(key_a, 2, 60)).retry_after_seconds is None
    assert (await RateLimitService._hit_local(key_a, 2, 60)).retry_after_seconds is not None
    assert (await RateLimitService._hit_local(key_b, 2, 60)).retry_after_seconds is None


@pytest.mark.parametrize(
    "forwarded_for",
    [
        None,
        "not-an-ip",
        "198.51.100.20, 203.0.113.99",
        "1" * 65,
    ],
    ids=["missing", "invalid-ip", "comma-separated-chain", "oversized"],
)
def test_websocket_malformed_forwarding_falls_back_to_trusted_peer(
    monkeypatch,
    forwarded_for: str | None,
) -> None:
    _set_trusted_proxies(monkeypatch, f'["{TRUSTED_NGINX}/32"]')
    assert get_client_ip(_websocket(TRUSTED_NGINX, forwarded_for)) == TRUSTED_NGINX


def test_missing_environment_fails_configuration(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    assert ("environment",) in {error["loc"] for error in exc_info.value.errors()}


def test_empty_environment_fails_configuration() -> None:
    with pytest.raises(ValidationError, match="ENVIRONMENT must not be empty"):
        Settings(_env_file=None, environment="  ")


@pytest.mark.parametrize("environment", ["dev", "development", "local", "test"])
def test_explicit_development_environments_retain_development_behavior(environment: str) -> None:
    settings = Settings(
        _env_file=None,
        environment=f"  {environment.upper()}  ",
        jwt_secret="change-me",
        message_encryption_enabled=True,
        message_encryption_key="",
    )
    assert settings.environment == environment


@pytest.mark.parametrize("environment", ["live", "release", "prod-eu", "foo"])
def test_unknown_environments_remain_production_like(environment: str) -> None:
    with pytest.raises(ValidationError, match="known development placeholder"):
        Settings(
            _env_file=None,
            environment=environment,
            jwt_secret="change-me",
            message_encryption_enabled=False,
        )


def test_secure_production_like_environment_succeeds() -> None:
    settings = Settings(
        _env_file=None,
        environment=" prod-eu ",
        jwt_secret=SECURE_JWT_SECRET,
        message_encryption_enabled=True,
        message_encryption_key=SECURE_FERNET_KEY,
    )
    assert settings.environment == "prod-eu"


def test_missing_environment_cannot_reach_development_encryption_fallback(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("MESSAGE_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    encryption._build_fernet.cache_clear()
    fallback_calls = 0

    def fail_if_fallback_runs() -> str:
        nonlocal fallback_calls
        fallback_calls += 1
        raise AssertionError("development fallback must not run without ENVIRONMENT")

    monkeypatch.setattr(encryption, "_derive_dev_key", fail_if_fallback_runs)
    with pytest.raises(ValidationError):
        encryption._build_fernet()
    assert fallback_calls == 0
