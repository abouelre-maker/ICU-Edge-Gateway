"""
Request body size limit (F-02) — pure ASGI middleware.

Rejects with HTTP 413 before the body is buffered: first on a declared
Content-Length, then while streaming for chunked bodies. The limit is an
engineering DoS control, not a clinical value (config.get_max_request_body_bytes).
"""

from __future__ import annotations

from typing import Any

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[bytes, bytes] = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await _send_413(send, self.max_bytes)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(status_code=413, detail="Request body too large.")
            return message

        await self.app(scope, limited_receive, send)


async def _send_413(send: Send, max_bytes: int) -> None:
    body = (
        b'{"error":"payload_too_large","detail":"Request body exceeds '
        + str(max_bytes).encode()
        + b' bytes."}'
    )
    start: dict[str, Any] = {
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    }
    await send(start)
    await send({"type": "http.response.body", "body": body})
