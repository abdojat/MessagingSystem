import pytest

from app.realtime.protocol import build_envelope, parse_client_envelope


def test_ws_envelope_parse_and_build():
    env = build_envelope("ping", {}, None)
    parsed = parse_client_envelope(env)
    assert parsed.type == "ping"
    assert parsed.payload == {}
    assert parsed.request_id is None


def test_ws_envelope_validation_rejects_invalid():
    with pytest.raises(ValueError):
        parse_client_envelope({"type": "ping", "payload": {}})
