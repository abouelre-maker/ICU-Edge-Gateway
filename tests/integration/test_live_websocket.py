"""
Integration Tests — WS /api/v1/live/vitals end-to-end (Phase 5 Section A).

Uses starlette.testclient.TestClient rather than the `client` fixture:
TestClient actually drives the ASGI lifespan protocol (confirmed against
test_main_mllp_lifespan.py's finding that httpx.ASGITransport does not) and
is the only client in this dependency set that supports WebSocket
connections at all. Sync, not async, test functions -- TestClient's API is
synchronous by design; pytest-asyncio's `asyncio_mode = "auto"` only wraps
`async def` tests, so these run as ordinary sync tests.

FULL_ORU is the same fixture used by test_api_ingest.py and
test_mllp_listener.py.
"""

from __future__ import annotations

import socket

import pytest
from main import create_app
from starlette.testclient import TestClient

FULL_ORU = (
    "MSH|^~\\&|GENERIC_MONITOR|ICU_UNIT|EHR|HOSPITAL|20240115100000"
    "||ORU^R01|MSG001|P|2.5.1\r"
    "PID|1||PT-WS-001^^^HOSP^MR||DOE^JOHN||19800101|M\r"
    "OBR|1||ORDER-001|||||20240115100000\r"
    "OBX|1|NM|8867-4^Heart rate^LN||72|/min|60-100||||F|||20240115100000\r"
    "OBX|2|NM|59408-5^SpO2^LN||98|%|95-100||||F|||20240115100000\r"
    "OBX|3|NM|9279-1^Respiratory rate^LN||16|/min|12-20||||F|||20240115100000\r"
    "OBX|4|NM|8480-6^Systolic BP^LN||120|mmHg|90-140||||F|||20240115100000\r"
    "OBX|5|NM|8310-5^Temperature^LN||37.0|Cel|36.1-38.0||||F|||20240115100000\r"
    "OBX|6|NM|57834-7^Supplemental O2^LN||0||||||F|||20240115100000\r"
)

_VITALS_PAYLOAD = {
    "patient_id": "PT-WS-002",
    "spo2_scale": "SCALE_1",
    "samples": [
        {
            "vital_sign_type": "HEART_RATE",
            "value": 80,
            "unit": "bpm",
            "timestamp": "2024-01-15T10:00:00Z",
        }
    ],
}


@pytest.mark.integration
class TestLiveWebsocketHttpIngestDelta:
    def test_post_ingest_delivers_delta_to_connected_dashboard(self) -> None:
        app = create_app()
        with (
            TestClient(app) as client,
            client.websocket_connect("/api/v1/live/vitals") as ws,
        ):
            response = client.post(
                "/api/v1/ingest",
                content=FULL_ORU,
                headers={"Content-Type": "text/plain"},
            )
            assert response.status_code == 200

            delta = ws.receive_json()
            assert delta["type"] == "vitals.delta"
            assert delta["source"] == "http-ingest"
            assert delta["patient_id"] == "PT-WS-001"
            assert delta["bundle"]["resourceType"] == "Bundle"

    def test_post_vitals_delivers_delta_to_connected_dashboard(self) -> None:
        app = create_app()
        with (
            TestClient(app) as client,
            client.websocket_connect("/api/v1/live/vitals") as ws,
        ):
            response = client.post("/api/v1/vitals", json=_VITALS_PAYLOAD)
            assert response.status_code == 200

            delta = ws.receive_json()
            assert delta["source"] == "http-vitals"
            assert delta["patient_id"] == "PT-WS-002"


@pytest.mark.integration
class TestLiveWebsocketMultipleClients:
    def test_all_connected_clients_receive_the_same_delta(self) -> None:
        app = create_app()
        with (
            TestClient(app) as client,
            client.websocket_connect("/api/v1/live/vitals") as ws_a,
            client.websocket_connect("/api/v1/live/vitals") as ws_b,
        ):
            client.post(
                "/api/v1/ingest",
                content=FULL_ORU,
                headers={"Content-Type": "text/plain"},
            )
            delta_a = ws_a.receive_json()
            delta_b = ws_b.receive_json()
            assert delta_a["patient_id"] == delta_b["patient_id"] == "PT-WS-001"


@pytest.mark.integration
class TestLiveWebsocketDisconnectHandling:
    def test_disconnect_does_not_break_subsequent_requests(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/api/v1/live/vitals"):
                pass  # connect then immediately close

            # Server must still be healthy and able to process a normal
            # request after a dashboard client disconnects.
            response = client.post(
                "/api/v1/ingest",
                content=FULL_ORU,
                headers={"Content-Type": "text/plain"},
            )
            assert response.status_code == 200

    def test_no_connected_clients_does_not_error(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            # No websocket connected at all -- broadcast() must be a safe no-op.
            response = client.post(
                "/api/v1/ingest",
                content=FULL_ORU,
                headers={"Content-Type": "text/plain"},
            )
            assert response.status_code == 200


@pytest.mark.integration
class TestLiveWebsocketMllpSourceDelta:
    """
    MLLPListener wires the same LiveDashboardChannel (see main.py's lifespan
    and mllp_listener.py's _process_frame). MLLPListener binds a real OS TCP
    socket, so a plain synchronous `socket` connection -- rather than
    asyncio -- is used here to talk to it from outside TestClient's own
    background event loop.
    """

    def test_mllp_ingestion_delivers_delta_with_mllp_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MLLP_ENABLED", "true")
        monkeypatch.setenv("MLLP_HOST", "127.0.0.1")
        monkeypatch.setenv("MLLP_PORT", "0")
        app = create_app()

        with TestClient(app) as client:
            mllp_port = client.app.state.mllp_listener.port
            frame = b"\x0b" + FULL_ORU.encode("utf-8") + b"\x1c\x0d"

            with (
                client.websocket_connect("/api/v1/live/vitals") as ws,
                socket.create_connection(("127.0.0.1", mllp_port), timeout=5) as sock,
            ):
                sock.sendall(frame)
                ack = sock.recv(4096)
                assert b"MSA|AA|" in ack

                delta = ws.receive_json()
                assert delta["source"] == "mllp"
                assert delta["patient_id"] == "PT-WS-001"
