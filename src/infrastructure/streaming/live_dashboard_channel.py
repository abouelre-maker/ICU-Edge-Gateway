"""
LiveDashboardChannel — Low-Latency Live Dashboard Delta Push (WebSocket).

Phase 5 Section A. Fan-out broadcaster: every time any ingestion path
(POST /api/v1/ingest, POST /api/v1/vitals, or the MLLP listener) produces a
FHIR R4 Bundle, a compact "delta" envelope is pushed to every connected
dashboard WebSocket client in near-real-time — without the dashboard having
to poll. This module changes no DSP, NEWS2, or FHIR assembly behavior; it
only observes already-assembled Bundles and republishes a summary of them.

Design: paho-mqtt style per-consumer bounded queues, not a single shared
queue — each connected WebSocket gets its own asyncio.Queue fed by
broadcast(); a per-connection task in the route handler drains its queue
and writes to the socket. This means one slow dashboard client can never
block delivery to any other client, and never blocks the producer
(MLLPListener / HTTP request handlers) that called broadcast().

ISO 14971 HAZARD-STREAM-005 (PROPOSED — pending human risk-management
sign-off; new hazard for new code, not a resolution of an existing one):
  A dashboard client that stops reading (slow network, backgrounded
  browser tab, crashed JS) would, with an unbounded per-client queue, grow
  memory without limit; with a naive blocking send, would stall the
  broadcaster and delay/drop delivery to every other client.
  Mitigation implemented here:
    - Each client's queue is bounded (default: 200 deltas). On overflow,
      the OLDEST buffered delta for that client is dropped to make room for
      the newest — a live dashboard cares about "what is the vitals state
      now", not a complete historical replay, so recency is preferred over
      completeness once a client falls behind. Every such drop is logged.
    - broadcast() only enqueues (non-blocking `put_nowait` with its own
      overflow handling) and never awaits a per-client send, so one slow
      or dead client cannot delay delivery to others or block the caller
      that produced the Bundle (MLLPListener, an HTTP request handler).
  NOT mitigated here: this channel is display/monitoring-only — no
  acknowledgement, no delivery guarantee, no store-and-forward. A dashboard
  that is disconnected during an event permanently misses that delta (it
  should instead re-fetch current state via the REST endpoints on
  reconnect). This is a deliberate scope boundary, not an oversight: unlike
  the MQTT/MLLP telemetry paths (HAZARD-STREAM-002/003, which exist because
  that data must not be lost), a dashboard is a live view, not a system of
  record.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from fastapi import WebSocket

from infrastructure.streaming.fhir_bundle_utils import (
    extract_news2_summary,
    extract_patient_id,
)

_log: structlog.BoundLogger = structlog.get_logger(__name__)

_DEFAULT_MAX_QUEUE_PER_CLIENT = 200

DeltaSource = Literal["mllp", "http-ingest", "http-vitals"]


def build_delta(bundle: dict[str, Any], source: DeltaSource) -> dict[str, Any]:
    """
    Build a compact dashboard delta envelope from a FHIR Bundle.

    The full Bundle is included (dashboards that want raw FHIR can use it),
    alongside a pre-extracted patient_id/news2 summary so simple dashboard
    clients don't need their own FHIR-walking logic.
    """
    return {
        "type": "vitals.delta",
        "source": source,
        "received_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "patient_id": extract_patient_id(bundle),
        "news2": extract_news2_summary(bundle),
        "bundle": bundle,
    }


class LiveDashboardChannel:
    """
    WebSocket fan-out broadcaster for live vitals/NEWS2 dashboard deltas.

    Stateful (holds live client connections) — one instance is shared across
    the whole application via app.state.live_dashboard_channel, unlike the
    stateless domain services. Safe for concurrent use: all client-set
    mutation is guarded by an asyncio.Lock.
    """

    def __init__(
        self, max_queue_per_client: int = _DEFAULT_MAX_QUEUE_PER_CLIENT
    ) -> None:
        self._max_queue_per_client = max_queue_per_client
        self._clients: dict[WebSocket, asyncio.Queue[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> asyncio.Queue[dict[str, Any]]:
        """Accept a WebSocket connection and register a bounded delivery queue for it."""
        await websocket.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._max_queue_per_client
        )
        async with self._lock:
            self._clients[websocket] = queue
        _log.info(
            "live_dashboard_channel.client_connected", client_count=self.client_count
        )
        return queue

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(websocket, None)
        _log.info(
            "live_dashboard_channel.client_disconnected", client_count=self.client_count
        )

    async def broadcast(self, bundle: dict[str, Any], source: DeltaSource) -> int:
        """
        Enqueue a delta built from `bundle` for every connected client.

        Non-blocking with respect to any individual client's socket I/O —
        only queues are touched here, never `websocket.send_json()`.

        Returns the number of clients the delta was enqueued for.
        """
        async with self._lock:
            targets = list(self._clients.items())
        if not targets:
            return 0

        delta = build_delta(bundle, source)
        for websocket, queue in targets:
            self._enqueue_with_overflow_policy(websocket, queue, delta)
        return len(targets)

    def schedule_broadcast(self, bundle: dict[str, Any], source: DeltaSource) -> None:
        """
        Fire-and-forget variant of broadcast() for callers that are not
        coroutines themselves (e.g. MLLPListener._process_frame(), which is
        a synchronous method invoked from within a running asyncio event
        loop). Schedules broadcast() as a background task; does not await
        it, so it never adds latency to the MLLP ACK/NAK response path.
        """
        asyncio.ensure_future(self.broadcast(bundle, source))

    @staticmethod
    def _enqueue_with_overflow_policy(
        websocket: WebSocket,
        queue: asyncio.Queue[dict[str, Any]],
        delta: dict[str, Any],
    ) -> None:
        try:
            queue.put_nowait(delta)
        except asyncio.QueueFull:
            # HAZARD-STREAM-005: drop the OLDEST buffered delta for this
            # slow client to make room for the newest, rather than blocking
            # the broadcaster or growing memory without bound. Logged so a
            # persistently lagging client is visible in the audit trail.
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(delta)
            _log.warning(
                "live_dashboard_channel.client_queue_overflow",
                client=str(websocket.client),
            )
