"""
MLLPListener — Edge-Side MLLP TCP Listener wrapping HL7v2Adapter.

Phase 5 Section A. Implements the Minimal Lower Layer Protocol (MLLP) framing
used by ICU bedside monitors and hospital interface engines to carry HL7 v2.x
messages over a persistent TCP connection (the standard alternative to the
existing HTTP `POST /api/v1/ingest` route, for devices/engines that only
speak MLLP). Each inbound frame is decoded and run through exactly the same
domain pipeline as the HTTP route — HL7v2Adapter -> VitalsOrchestrator ->
BundleAssembler — and ACKed/NAKed per HL7 MSA acknowledgement conventions.

This module changes no DSP, NEWS2, or FHIR assembly behavior. It is a new
transport in front of the existing, already-tested pipeline (HARD CONSTRAINT
#1: signal_processor.py, news2_calculator.py, and news2_score.py are
untouched by this change).

ISO 14971 HAZARD-ARCH-001 (existing, unchanged): this listener calls
VitalsOrchestrator.analyse() — the same integration seam used by
`api/v1/ingest.py` — so "DSP artifact rejection before NEWS2 scoring" is
inherited structurally from the existing orchestrator, not reimplemented
here. See tests/regulatory/test_hazard_arch_001_pipeline_order.py.

ISO 14971 HAZARD-STREAM-001 (PROPOSED — pending human risk-management
sign-off; new hazard for new code, not a resolution of an existing one):
  MLLP frames arrive as raw TCP bytes with no integrity check beyond the
  start-block/end-block/carriage-return framing characters. A malformed,
  truncated, or concatenated frame passed to HL7v2Adapter risks the parser
  treating corrupted or partial data as a complete, valid message.
  Mitigation implemented here:
    - Framing is validated strictly (VT ... FS CR) via asyncio stream
      `readuntil()` boundaries before any bytes reach HL7v2Adapter.parse().
    - A frame that is incomplete when the connection closes, or whose
      decoded bytes fail UTF-8 decoding, is rejected outright (NAK,
      discarded) and is NEVER passed to the parser in partial/"best effort"
      form.
    - An oversized frame (default cap: 1 MiB) is rejected rather than
      buffered without bound, to prevent a single misbehaving sender from
      exhausting edge-appliance memory.
    - Stray bytes received before a start block (e.g. TCP keepalive noise
      some interface engines emit) are discarded and logged, never treated
      as message content.
  NOT mitigated here: byte-level corruption *inside* an otherwise
  well-framed message (e.g. a bit-flip). HL7 v2.x has no per-message
  checksum; this is a residual risk inherent to the wire protocol, not
  specific to this listener. Accepting this residual risk for a given
  edge-network deployment requires human risk-management sign-off.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from domain.entities.device_context import DeviceContext, MonitorVendor
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.services.vitals_orchestrator import VitalsOrchestrator

from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter
from infrastructure.fhir.bundle_assembler import BundleAssembler
from infrastructure.streaming.live_dashboard_channel import LiveDashboardChannel
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer

_log: structlog.BoundLogger = structlog.get_logger(__name__)

# ── MLLP Framing Constants (HL7 standard: MLLP v1) ──────────────────────────
_START_BLOCK: bytes = b"\x0b"  # VT
_END_BLOCK: bytes = b"\x1c"  # FS
_CARRIAGE_RETURN: bytes = b"\x0d"  # CR
_FRAME_TERMINATOR: bytes = _END_BLOCK + _CARRIAGE_RETURN

_DEFAULT_MAX_FRAME_BYTES: int = 1_048_576  # 1 MiB — HAZARD-STREAM-001 mitigation
_DEFAULT_FORWARD_BUFFER_CAPACITY: int = 10_000


@dataclass(frozen=True)
class MLLPIngestOutcome:
    """Result of processing a single MLLP-framed HL7 message."""

    accepted: bool
    patient_id: str | None
    reason: str | None
    bundle: dict[str, Any] | None


class MLLPFramingError(ValueError):
    """Raised for a structurally invalid MLLP frame (HAZARD-STREAM-001)."""


class MLLPListener:
    """
    Asyncio TCP server implementing MLLP framing over the existing HL7 pipeline.

    Pipeline components (HL7v2Adapter, VitalsOrchestrator, BundleAssembler)
    are stateless and shared across connections — the same pattern used by
    the module-level singletons in api/v1/ingest.py.

    Successfully processed bundles are pushed onto a StoreAndForwardRingBuffer
    (`forward_buffer`) rather than published directly, so this listener has
    no dependency on cloud/network availability. A downstream forwarder
    (Phase 5 Section A follow-up: MQTT publisher) drains this buffer.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 2575,
        forward_buffer: StoreAndForwardRingBuffer[dict[str, Any]] | None = None,
        adapter: HL7v2Adapter | None = None,
        orchestrator: VitalsOrchestrator | None = None,
        assembler: BundleAssembler | None = None,
        default_spo2_scale: SpO2Scale = SpO2Scale.SCALE_1,
        max_frame_bytes: int = _DEFAULT_MAX_FRAME_BYTES,
        live_channel: LiveDashboardChannel | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._forward_buffer: StoreAndForwardRingBuffer[dict[str, Any]] = (
            forward_buffer
            or StoreAndForwardRingBuffer(capacity=_DEFAULT_FORWARD_BUFFER_CAPACITY)
        )
        self._adapter = adapter or HL7v2Adapter()
        self._orchestrator = orchestrator or VitalsOrchestrator()
        self._assembler = assembler or BundleAssembler()
        self._default_spo2_scale = default_spo2_scale
        self._max_frame_bytes = max_frame_bytes
        # Optional: Phase 5 Section A live dashboard fan-out. None is a
        # fully supported configuration (MLLP ingestion has no dependency
        # on a dashboard being present) -- see _process_frame().
        self._live_channel = live_channel
        self._server: asyncio.Server | None = None

    @property
    def forward_buffer(self) -> StoreAndForwardRingBuffer[dict[str, Any]]:
        return self._forward_buffer

    @property
    def port(self) -> int:
        """Bound port. If constructed with port=0, valid only after start()."""
        if self._server is not None and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self._port

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._port
        )
        _log.info("mllp_listener.start", host=self._host, port=self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            _log.info("mllp_listener.stop")
            self._server = None

    async def __aenter__(self) -> MLLPListener:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    # ── Connection Handling ──────────────────────────────────────────────────

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        log = _log.bind(peer=str(peer))
        log.info("mllp_listener.connection.open")
        try:
            while True:
                frame = await self._read_frame(reader, log)
                if frame is None:
                    break  # clean EOF between messages
                outcome = self._process_frame(frame, log)
                ack = self._build_ack(outcome)
                writer.write(_START_BLOCK + ack.encode("utf-8") + _FRAME_TERMINATOR)
                await writer.drain()
        except MLLPFramingError as exc:
            log.warning("mllp_listener.connection.framing_error", error=str(exc))
        except asyncio.IncompleteReadError:
            log.warning("mllp_listener.connection.truncated")
        except (ConnectionResetError, ConnectionAbortedError):
            log.info("mllp_listener.connection.reset_by_peer")
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            log.info("mllp_listener.connection.close")

    async def _read_frame(self, reader: asyncio.StreamReader, log: Any) -> bytes | None:
        """
        Read one complete MLLP frame (between VT and FS+CR), or None on clean EOF.

        Raises MLLPFramingError for oversized or otherwise malformed frames.
        Raises asyncio.IncompleteReadError if the connection closes mid-frame.
        """
        try:
            leading = await reader.readuntil(_START_BLOCK)
        except asyncio.IncompleteReadError as exc:
            if not exc.partial:
                return None  # clean EOF, no partial data — normal disconnect
            raise

        discarded = leading[:-1]
        if discarded:
            # HAZARD-STREAM-001 mitigation: stray pre-frame bytes are logged,
            # never treated as message content.
            log.warning("mllp_listener.frame.leading_bytes_discarded", n=len(discarded))

        body_and_terminator = await reader.readuntil(_FRAME_TERMINATOR)

        if len(body_and_terminator) > self._max_frame_bytes:
            raise MLLPFramingError(
                f"MLLP frame of {len(body_and_terminator)} bytes exceeds the "
                f"{self._max_frame_bytes}-byte maximum (HAZARD-STREAM-001)."
            )

        return body_and_terminator[: -len(_FRAME_TERMINATOR)]

    # ── Pipeline Invocation ───────────────────────────────────────────────────

    def _process_frame(self, frame: bytes, log: Any) -> MLLPIngestOutcome:
        try:
            raw_hl7 = frame.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            log.warning("mllp_listener.frame.decode_error", error=str(exc))
            return MLLPIngestOutcome(
                accepted=False,
                patient_id=None,
                reason=f"Undecodable frame: {exc}",
                bundle=None,
            )

        try:
            parse_result = self._adapter.parse(raw_hl7)
        except ValueError as exc:
            log.warning("mllp_listener.frame.parse_error", error=str(exc))
            return MLLPIngestOutcome(
                accepted=False, patient_id=None, reason=str(exc), bundle=None
            )

        patient_context = PatientContext(
            patient_id=parse_result.patient_id,
            spo2_scale=self._default_spo2_scale,
        )
        device_context: DeviceContext | None = None
        if parse_result.detected_vendor is not MonitorVendor.GENERIC:
            device_context = DeviceContext(
                device_id=f"DEVICE-{parse_result.detected_vendor.value}",
                vendor=parse_result.detected_vendor,
                model="ICU Monitor",
            )

        # ── Domain Pipeline (DSP + NEWS2) — HAZARD-ARCH-001 order inherited ────
        analysis_result = self._orchestrator.analyse(
            samples=list(parse_result.samples),
            context=patient_context,
        )
        bundle = self._assembler.assemble(
            result=analysis_result,
            patient_context=patient_context,
            device_context=device_context,
            encounter_id=None,
        )

        dropped = self._forward_buffer.push(bundle)
        if dropped:
            log.warning("mllp_listener.forward_buffer.overflow_drop")

        if self._live_channel is not None:
            # Fire-and-forget: never adds latency to the ACK/NAK response.
            self._live_channel.schedule_broadcast(bundle, source="mllp")

        log.info(
            "mllp_listener.frame.processed",
            patient_id=parse_result.patient_id,
            sample_count=len(parse_result.samples),
            skipped_obx=parse_result.skipped_obx_count,
            news2_total=(
                analysis_result.news2_score.total
                if analysis_result.news2_score
                else None
            ),
        )
        return MLLPIngestOutcome(
            accepted=True,
            patient_id=parse_result.patient_id,
            reason=None,
            bundle=bundle,
        )

    @staticmethod
    def _build_ack(outcome: MLLPIngestOutcome) -> str:
        """
        Build an HL7 v2.x ACK/NAK message per MSA acknowledgement conventions.

        AA = Application Accept, AE = Application Error. This listener never
        raises AR (Application Reject) — every structurally-parseable frame
        is either fully accepted or explicitly rejected with a reason.
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        ack_code = "AA" if outcome.accepted else "AE"
        control_id = f"ACK{ts}"
        detail = (outcome.reason or "").replace("|", "-").replace("\r", " ")
        segments = [
            f"MSH|^~\\&|ICU-EDGE-GATEWAY|EDGE|||{ts}||ACK|{control_id}|P|2.5.1",
            f"MSA|{ack_code}|{control_id}|{detail}",
        ]
        return "\r".join(segments) + "\r"
