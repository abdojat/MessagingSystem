import asyncio
import uuid

import pytest

from app import main as main_module
from app.realtime.ws_manager import WSManager


class _FakeWebSocket:
    def __init__(self, query_token=None, auth_header=None, first_message=None):
        self.query_params = {"token": query_token} if query_token else {}
        self.headers = {"authorization": auth_header} if auth_header else {}
        self._first_message = first_message
        self.accepted = False
        self.closed = None
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def receive_json(self):
        if self._first_message is None:
            raise RuntimeError("no message")
        return self._first_message

    async def close(self, code, reason=None):
        self.closed = (code, reason)

    async def send_json(self, payload):
        self.sent.append(payload)


class _DummyRedis:
    pass


class _DummyAMQP:
    pass


@pytest.mark.asyncio
async def test_ws_auth_supports_query_header_and_first_message(monkeypatch):
    seen_tokens = []

    async def _fake_run_with_token(websocket, token, pre_accepted=False):
        seen_tokens.append((token, pre_accepted))

    monkeypatch.setattr(main_module, "_run_websocket_with_token", _fake_run_with_token)

    ws_query = _FakeWebSocket(query_token="token-q")
    await main_module._run_websocket(ws_query)
    ws_header = _FakeWebSocket(auth_header="Bearer token-h")
    await main_module._run_websocket(ws_header)
    ws_msg = _FakeWebSocket(first_message={"type": "auth", "payload": {"token": "token-m"}})
    await main_module._run_websocket(ws_msg)

    assert seen_tokens == [("token-q", False), ("token-h", False), ("token-m", True)]
    assert ws_msg.accepted is True


@pytest.mark.asyncio
async def test_ws_unauthenticated_socket_is_closed():
    ws = _FakeWebSocket(first_message={"type": "ping", "payload": {}})
    await main_module._run_websocket(ws)
    assert ws.accepted is True
    assert ws.closed is not None
    assert ws.closed[0] == 1008


@pytest.mark.asyncio
async def test_ws_manager_sends_hello_on_run_socket(monkeypatch):
    manager = WSManager(session_factory=None, redis=_DummyRedis(), amqp=_DummyAMQP())

    async def _fast_return(*args, **kwargs):
        return None

    async def _slow_loop(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(manager, "_redis_forward_loop", _fast_return)
    monkeypatch.setattr(manager, "_inbound_loop", _slow_loop)

    ws = _FakeWebSocket()
    await manager.run_socket(ws, uuid.uuid4())
    assert ws.sent
    assert ws.sent[0]["type"] == "hello"
