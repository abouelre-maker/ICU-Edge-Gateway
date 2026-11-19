"""
F-01 / F-08 — authentication mechanism (API key; WebSocket token + Origin)
and the MLLP client allow-list.

The HTTP/WS dependencies are tested on a standalone app here. Wiring them into
create_app() is BLOCKED-TEST-CONFLICT F01-1 / F08-1 (HD-E6): ~70 existing API
tests call the endpoints without credentials. The MLLP allow-list IS wired.
"""

from __future__ import annotations

import asyncio

import pytest
from api.auth import authorize_websocket, require_api_key
from config import validate_gateway_auth_config
from fastapi import Depends, FastAPI, WebSocket
from infrastructure.streaming.mllp_listener import (
    _CARRIAGE_RETURN,
    _END_BLOCK,
    _START_BLOCK,
    MLLPListener,
)
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

_KEY = "k" * 40


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("GATEWAY_API_KEYS", f"{_KEY},{'z' * 48}")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://dash.example")
    a = FastAPI()

    @a.post("/protected", dependencies=[Depends(require_api_key)])
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    @a.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        if not await authorize_websocket(websocket):
            return
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    return a


class TestApiKey:
    def test_missing_credentials_is_401(self, app: FastAPI) -> None:
        assert TestClient(app).post("/protected").status_code == 401

    def test_wrong_key_is_401(self, app: FastAPI) -> None:
        r = TestClient(app).post("/protected", headers={"Authorization": "Bearer " + "x" * 40})
        assert r.status_code == 401

    def test_non_ascii_key_is_401_not_500(self, app: FastAPI) -> None:
        r = TestClient(app).post(
            "/protected", headers={"Authorization": "Bearer sécret".encode()}
        )
        assert r.status_code == 401

    def test_valid_key_is_accepted(self, app: FastAPI) -> None:
        r = TestClient(app).post("/protected", headers={"Authorization": f"Bearer {_KEY}"})
        assert r.status_code == 200


class TestFailClosedConfig:
    def test_unset_keys_refuse_to_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GATEWAY_API_KEYS", raising=False)
        with pytest.raises(RuntimeError, match="GATEWAY_API_KEYS"):
            validate_gateway_auth_config()

    def test_short_key_refuses_to_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GATEWAY_API_KEYS", "short")
        with pytest.raises(RuntimeError, match="32"):
            validate_gateway_auth_config()


class TestWebSocketGuard:
    def test_no_token_is_refused(self, app: FastAPI) -> None:
        with pytest.raises(WebSocketDisconnect), TestClient(app).websocket_connect(
            "/ws", headers={"Origin": "https://dash.example"}
        ) as ws:
            ws.receive_text()

    def test_bad_origin_is_refused_even_with_token(self, app: FastAPI) -> None:
        with pytest.raises(WebSocketDisconnect), TestClient(app).websocket_connect(
            f"/ws?access_token={_KEY}", headers={"Origin": "https://evil.example"}
        ) as ws:
            ws.receive_text()

    def test_token_and_allowed_origin_connects(self, app: FastAPI) -> None:
        with TestClient(app).websocket_connect(
            f"/ws?access_token={_KEY}", headers={"Origin": "https://dash.example"}
        ) as ws:
            assert ws.receive_text() == "hello"


_OK = (
    "MSH|^~\\&|MON|ICU|EHR|HOSP|20260929110000||ORU^R01|F01|P|2.5.1\r"
    "PID|1||PT-F01^^^H^MR\rOBX|1|NM|8867-4^HR^LN||72|/min|||||F|||20260929110000\r"
)


async def _send(lst: MLLPListener) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", lst.port)
    writer.write(_START_BLOCK + _OK.encode() + _END_BLOCK + _CARRIAGE_RETURN)
    await writer.drain()
    try:
        data = await asyncio.wait_for(reader.read(65536), timeout=5)
    except ConnectionResetError:  # Windows reports a refused/closed peer this way
        data = b""
    writer.close()
    return data


class TestMllpAllowList:
    async def test_default_allows_loopback(self) -> None:
        lst = MLLPListener(host="127.0.0.1", port=0, forward_buffer=StoreAndForwardRingBuffer(capacity=5))
        await lst.start()
        try:
            assert b"MSA|AA|" in await _send(lst)
        finally:
            await lst.stop()

    async def test_client_outside_allow_list_is_refused(self) -> None:
        lst = MLLPListener(
            host="127.0.0.1",
            port=0,
            forward_buffer=StoreAndForwardRingBuffer(capacity=5),
            allowed_networks=("10.0.0.0/8",),
        )
        await lst.start()
        try:
            assert await _send(lst) == b""
            assert lst.forward_buffer.size() == 0
        finally:
            await lst.stop()
