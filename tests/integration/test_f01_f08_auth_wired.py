"""
F-01 / F-08 end-to-end: authentication wired into the real application.

The guards themselves are unit-tested in tests/unit/test_f01_f08_auth.py on a
standalone app; these tests prove create_app() actually applies them.
"""

from __future__ import annotations

import pytest
from conftest import TEST_API_KEY, TEST_AUTH_HEADERS
from httpx import AsyncClient
from main import create_app
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.integration.test_api_vitals import FULL_VITALS
from tests.integration.test_live_websocket import FULL_ORU

pytestmark = pytest.mark.integration


class TestHttpRoutesRequireKey:
    @pytest.mark.parametrize("path", ["/api/v1/ingest", "/api/v1/vitals"])
    async def test_no_credentials_is_401(
        self, unauthenticated_client: AsyncClient, path: str
    ) -> None:
        r = await unauthenticated_client.post(path, content=FULL_ORU)
        assert r.status_code == 401
        assert r.headers["WWW-Authenticate"] == "Bearer"

    async def test_wrong_key_is_401(self, unauthenticated_client: AsyncClient) -> None:
        r = await unauthenticated_client.post(
            "/api/v1/vitals",
            json=FULL_VITALS,
            headers={"Authorization": "Bearer " + "w" * 40},
        )
        assert r.status_code == 401

    async def test_non_bearer_scheme_is_401(self, unauthenticated_client: AsyncClient) -> None:
        r = await unauthenticated_client.post(
            "/api/v1/vitals", json=FULL_VITALS, headers={"Authorization": f"Basic {TEST_API_KEY}"}
        )
        assert r.status_code == 401

    async def test_401_body_does_not_echo_payload(
        self, unauthenticated_client: AsyncClient
    ) -> None:
        r = await unauthenticated_client.post("/api/v1/ingest", content=FULL_ORU)
        assert "PID" not in r.text and "OBX" not in r.text

    async def test_valid_key_ingest_is_200(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers={"Content-Type": "text/plain"}
        )
        assert r.status_code == 200

    async def test_valid_key_vitals_is_200(self, client: AsyncClient) -> None:
        r = await client.post("/api/v1/vitals", json=FULL_VITALS)
        assert r.status_code == 200

    async def test_health_stays_open(self, unauthenticated_client: AsyncClient) -> None:
        r = await unauthenticated_client.get("/health")
        assert r.status_code == 200


class TestStartupFailsClosed:
    def test_app_refuses_to_start_without_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GATEWAY_API_KEYS", raising=False)
        with pytest.raises(RuntimeError, match="GATEWAY_API_KEYS"), TestClient(create_app()):
            pass

    def test_app_refuses_to_start_with_short_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GATEWAY_API_KEYS", "too-short")
        with pytest.raises(RuntimeError, match="shorter"), TestClient(create_app()):
            pass


class TestLiveWebSocketRequiresKey:
    def test_no_credentials_is_refused(self) -> None:
        with (
            TestClient(create_app(), headers={}) as c,
            pytest.raises(WebSocketDisconnect) as exc,
            c.websocket_connect("/api/v1/live/vitals") as ws,
        ):
            ws.receive_text()
        assert exc.value.code == 1008

    def test_query_token_connects(self) -> None:
        with (
            TestClient(create_app(), headers={}) as c,
            c.websocket_connect(f"/api/v1/live/vitals?access_token={TEST_API_KEY}") as ws,
        ):
            r = c.post("/api/v1/ingest", content=FULL_ORU, headers=TEST_AUTH_HEADERS)
            assert r.status_code == 200
            assert ws.receive_json()["patient_id"]

    def test_disallowed_origin_is_refused_even_with_key(self) -> None:
        with (
            TestClient(create_app()) as c,
            pytest.raises(WebSocketDisconnect),
            c.websocket_connect(
                "/api/v1/live/vitals", headers={"Origin": "https://evil.example"}
            ) as ws,
        ):
            ws.receive_text()


class TestSubscriptionSecretNonAscii:
    """F-06: a non-ASCII bearer value is a 401, never a 500."""

    def test_non_ascii_secret_is_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHIR_SUBSCRIPTION_REGISTRATION_SECRET", "s" * 40)
        with TestClient(create_app(), headers={}) as c:
            r = c.get(
                "/api/v1/fhir/Subscription",
                headers={"Authorization": "Bearer sécret".encode()},  # type: ignore[dict-item]
            )
        assert r.status_code == 401
