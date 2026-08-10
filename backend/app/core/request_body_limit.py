import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID


ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGISend = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], ASGIReceive, ASGISend], Awaitable[None]]


class _RequestBodyTooLarge(Exception):
    pass


def _is_streaming_upload_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 3 or parts[-3] != "uploads" or parts[-1] != "content":
        return False
    try:
        UUID(parts[-2])
    except (TypeError, ValueError):
        return False
    return True


class RequestBodyLimitMiddleware:
    """Stream-count ordinary request bodies without pre-buffering them.

    Upload-content PUTs retain their dedicated streamed size/checksum policy.
    All other body-bearing API requests get the repository-controlled small
    boundary, including requests without Content-Length.
    """

    _BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max(1, int(max_body_bytes))

    async def __call__(self, scope, receive, send) -> None:
        method = str(scope.get("method", "GET")).upper()
        if (
            scope.get("type") != "http"
            or method not in self._BODY_METHODS
            or (method == "PUT" and _is_streaming_upload_path(str(scope.get("path", ""))))
        ):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError):
                declared_length = self.max_body_bytes + 1
            if declared_length < 0 or declared_length > self.max_body_bytes:
                await self._send_too_large(send)
                return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> dict[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._send_too_large(send)

    @staticmethod
    async def _send_too_large(send) -> None:
        payload = json.dumps(
            {
                "code": "PAYLOAD_TOO_LARGE",
                "message": "request body too large",
                "details": None,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload, "more_body": False})
