"""
Unit Tests — LiveDashboardChannel (Phase 5 Section A dashboard fan-out).

Uses a minimal fake in place of fastapi.WebSocket -- these tests target the
channel's own connect/disconnect/broadcast/overflow logic (HAZARD-STREAM-005),
not Starlette's WebSocket protocol implementation. End-to-end WebSocket
wire-protocol behavior is covered separately in
tests/integration/test_live_websocket.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from infrastructure.streaming.live_dashboard_channel import (
    LiveDashboardChannel,
    build_delta,
)


class _FakeWebSocket:
    """Minimal stand-in for fastapi.WebSocket's accept()/client surface."""

    def __init__(self, name: str = "fake") -> None:
        self.accepted = False
        self.client = name

    async def accept(self) -> None:
        self.accepted = True


def _bundle(patient_id: str = "PT-001") -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "subject": {"reference": f"Patient/{patient_id}"},
                }
            }
        ],
    }


class TestBuildDelta:
    def test_envelope_shape(self) -> None:
        delta = build_delta(_bundle("PT-007"), source="http-ingest")
        assert delta["type"] == "vitals.delta"
        assert delta["source"] == "http-ingest"
        assert delta["patient_id"] == "PT-007"
        assert delta["news2"] is None  # no NEWS2 Observation in this minimal fixture
        assert delta["bundle"]["resourceType"] == "Bundle"
        assert "received_at" in delta


class TestConnectDisconnect:
    async def test_connect_accepts_and_registers_client(self) -> None:
        channel = LiveDashboardChannel()
        ws = _FakeWebSocket()
        queue = await channel.connect(ws)  # type: ignore[arg-type]
        assert ws.accepted is True
        assert channel.client_count == 1
        assert isinstance(queue, asyncio.Queue)

    async def test_disconnect_removes_client(self) -> None:
        channel = LiveDashboardChannel()
        ws = _FakeWebSocket()
        await channel.connect(ws)  # type: ignore[arg-type]
        await channel.disconnect(ws)  # type: ignore[arg-type]
        assert channel.client_count == 0

    async def test_disconnect_of_unknown_client_is_a_no_op(self) -> None:
        channel = LiveDashboardChannel()
        ws = _FakeWebSocket()
        await channel.disconnect(ws)  # type: ignore[arg-type]  # never connected
        assert channel.client_count == 0


class TestBroadcast:
    async def test_broadcast_with_no_clients_returns_zero(self) -> None:
        channel = LiveDashboardChannel()
        count = await channel.broadcast(_bundle(), source="mllp")
        assert count == 0

    async def test_broadcast_enqueues_delta_for_every_connected_client(self) -> None:
        channel = LiveDashboardChannel()
        ws_a, ws_b = _FakeWebSocket("a"), _FakeWebSocket("b")
        queue_a = await channel.connect(ws_a)  # type: ignore[arg-type]
        queue_b = await channel.connect(ws_b)  # type: ignore[arg-type]

        count = await channel.broadcast(_bundle("PT-042"), source="http-vitals")

        assert count == 2
        delta_a = queue_a.get_nowait()
        delta_b = queue_b.get_nowait()
        assert delta_a["patient_id"] == "PT-042"
        assert delta_b["patient_id"] == "PT-042"

    async def test_disconnected_client_no_longer_receives_broadcasts(self) -> None:
        channel = LiveDashboardChannel()
        ws = _FakeWebSocket()
        await channel.connect(ws)  # type: ignore[arg-type]
        await channel.disconnect(ws)  # type: ignore[arg-type]

        count = await channel.broadcast(_bundle(), source="mllp")
        assert count == 0


class TestQueueOverflowPolicy:
    async def test_overflow_drops_oldest_delta_keeps_newest(self) -> None:
        channel = LiveDashboardChannel(max_queue_per_client=2)
        ws = _FakeWebSocket()
        queue = await channel.connect(ws)  # type: ignore[arg-type]

        await channel.broadcast(_bundle("PT-1"), source="mllp")
        await channel.broadcast(_bundle("PT-2"), source="mllp")
        await channel.broadcast(_bundle("PT-3"), source="mllp")  # overflow: drop PT-1

        assert queue.qsize() == 2
        remaining = [queue.get_nowait()["patient_id"] for _ in range(2)]
        assert remaining == ["PT-2", "PT-3"]


class TestScheduleBroadcast:
    async def test_schedule_broadcast_delivers_without_being_awaited(self) -> None:
        channel = LiveDashboardChannel()
        ws = _FakeWebSocket()
        queue = await channel.connect(ws)  # type: ignore[arg-type]

        channel.schedule_broadcast(_bundle("PT-999"), source="mllp")
        # schedule_broadcast() is fire-and-forget; give the scheduled task a
        # turn to run before asserting delivery.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        delta = queue.get_nowait()
        assert delta["patient_id"] == "PT-999"
        assert delta["source"] == "mllp"
