"""
WS /api/v1/live/vitals — Live Dashboard Delta Channel.

Phase 5 Section A. A dashboard client opens one WebSocket connection here
and receives a JSON "delta" message (see
infrastructure/streaming/live_dashboard_channel.py:build_delta) every time
any ingestion path (MLLP, POST /api/v1/ingest, POST /api/v1/vitals) produces
a new FHIR R4 Bundle — no polling required.

IEC 62304 §5.3: Single responsibility — this route only manages the
WebSocket connection lifecycle and delegates all fan-out logic to
LiveDashboardChannel, which lives on app.state (one shared instance for the
whole application, created unconditionally at ASGI lifespan startup).
FDA CDS: Every delta's `bundle` field carries the same
X-CDS-Advisory-Only-equivalent note as the REST responses (Bundle.note) —
this channel is a display convenience, not a new clinical output.
"""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from infrastructure.streaming.live_dashboard_channel import LiveDashboardChannel

_log: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["Live Dashboard"])


@router.websocket("/live/vitals")
async def live_vitals_ws(websocket: WebSocket) -> None:
    """
    Live vitals/NEWS2 delta stream for dashboard clients.

    Runs two concurrent tasks per connection:
      - a sender that drains this client's delivery queue and pushes deltas
      - a receiver that exists solely to detect a client-initiated
        disconnect promptly (a pure sender loop would otherwise block
        forever awaiting the next delta on an idle connection)
    Whichever finishes first (normal disconnect, error, or — for the
    receiver — any inbound message, which dashboard clients aren't expected
    to send but which does not itself break the connection) ends the other.
    """
    channel: LiveDashboardChannel = websocket.app.state.live_dashboard_channel
    queue = await channel.connect(websocket)

    async def _sender() -> None:
        while True:
            delta = await queue.get()
            await websocket.send_json(delta)

    async def _receiver() -> None:
        while True:
            await websocket.receive_text()

    sender_task: asyncio.Task[None] = asyncio.ensure_future(_sender())
    receiver_task: asyncio.Task[None] = asyncio.ensure_future(_receiver())
    try:
        done, pending = await asyncio.wait(
            {sender_task, receiver_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        pass
    finally:
        await channel.disconnect(websocket)
