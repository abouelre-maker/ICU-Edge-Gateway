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
import collections
import contextlib
import hashlib
import ipaddress
import re
import uuid
from collections.abc import Callable
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
from infrastructure.streaming.subscription_dispatcher import SubscriptionDispatcher

_log: structlog.BoundLogger = structlog.get_logger(__name__)

# ── MLLP Framing Constants (HL7 standard: MLLP v1) ──────────────────────────
_START_BLOCK: bytes = b"\x0b"  # VT
_END_BLOCK: bytes = b"\x1c"  # FS
_CARRIAGE_RETURN: bytes = b"\x0d"  # CR
_FRAME_TERMINATOR: bytes = _END_BLOCK + _CARRIAGE_RETURN

_DEFAULT_MAX_FRAME_BYTES: int = 1_048_576  # 1 MiB — HAZARD-STREAM-001 mitigation
# F-03: engineering DoS controls (not clinical values).
_DEFAULT_FRAME_TIMEOUT_SECONDS: float = 30.0  # start block → end block
_DEFAULT_IDLE_TIMEOUT_SECONDS: float = 600.0  # between frames on a persistent link
_DEFAULT_MAX_CONNECTIONS: int = 64
_DEFAULT_FORWARD_BUFFER_CAPACITY: int = 10_000


@dataclass(frozen=True)
class MLLPIngestOutcome:
    """Result of processing a single MLLP-framed HL7 message."""

    accepted: bool
    patient_id: str | None
    reason: str | None
    bundle: dict[str, Any] | None
    # A8: explicit acknowledgement code (AA/AE/AR) and the sender's MSH-10.
    ack_code: str = ""
    control_id: str = ""


# A8: MSH-10 of an inbound frame, for echoing in MSA-2 even when the message
# cannot be parsed. MSH|<enc>|3|4|5|6|7|8|9|10 → seven fields after MSH-2.
_MSH10 = re.compile(r"^MSH\|[^|\r]*\|(?:[^|\r]*\|){7}([^|\r]*)")


def _raw_control_id(raw: str) -> str:
    m = _MSH10.match(raw.lstrip())
    return m.group(1).strip() if m else ""


# A8-1: (MSH-3 sending application, MSH-4 sending facility, MSH-10 control ID).
_MSH_SENDER_AND_ID = re.compile(r"^MSH\|[^|\r]*\|([^|\r]*)\|([^|\r]*)\|(?:[^|\r]*\|){5}([^|\r]*)")
_DEFAULT_DEDUP_CAPACITY = 10_000
_DISCARD_SECONDS = 2.0


def _dedup_key(frame: bytes) -> tuple[str, str, str] | None:
    """Idempotency key of a frame, or None when it has no MSH-10 to key on."""
    m = _MSH_SENDER_AND_ID.match(frame.decode("utf-8", errors="replace").lstrip())
    if not m or not m.group(3).strip():
        return None
    return (m.group(1).strip(), m.group(2).strip(), m.group(3).strip())


class MLLPFramingError(ValueError):
    """Raised for a structurally invalid MLLP frame (HAZARD-STREAM-001)."""


class MLLPOversizeError(MLLPFramingError):
    """F-03 / F03-1: a frame over the byte cap. Answered with AR, then closed."""


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
        # F01-2: loopback by default; main.py passes config.get_mllp_host().
        host: str = "127.0.0.1",
        port: int = 2575,
        forward_buffer: StoreAndForwardRingBuffer[dict[str, Any]] | None = None,
        adapter: HL7v2Adapter | None = None,
        orchestrator: VitalsOrchestrator | None = None,
        assembler: BundleAssembler | None = None,
        default_spo2_scale: SpO2Scale = SpO2Scale.SCALE_1,
        max_frame_bytes: int = _DEFAULT_MAX_FRAME_BYTES,
        live_channel: LiveDashboardChannel | None = None,
        subscription_dispatcher: SubscriptionDispatcher | None = None,
        spo2_scale_resolver: Callable[[str], SpO2Scale | None] | None = None,
        frame_timeout_seconds: float = _DEFAULT_FRAME_TIMEOUT_SECONDS,
        idle_timeout_seconds: float = _DEFAULT_IDLE_TIMEOUT_SECONDS,
        max_connections: int = _DEFAULT_MAX_CONNECTIONS,
        allowed_networks: tuple[str, ...] = ("127.0.0.0/8", "::1/128"),
        dedup_capacity: int = _DEFAULT_DEDUP_CAPACITY,
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
        # A8: per-patient SpO2 scale (e.g. from a clinician-maintained registry).
        # None / unknown patient ⇒ default_spo2_scale (same as HTTP /ingest).
        self._spo2_scale_resolver = spo2_scale_resolver
        self._max_frame_bytes = max_frame_bytes
        # Optional: Phase 5 Section A live dashboard fan-out / FHIR
        # Subscription dispatch. None is a fully supported configuration
        # (MLLP ingestion has no dependency on either being present) --
        # see _process_frame().
        self._live_channel = live_channel
        self._subscription_dispatcher = subscription_dispatcher
        self._server: asyncio.Server | None = None
        self._frame_timeout = frame_timeout_seconds
        self._idle_timeout = idle_timeout_seconds
        self._max_connections = max_connections
        self._active_connections = 0
        self._handler_tasks: set[asyncio.Task[None]] = set()
        # A8-1: keys of recently ACCEPTED messages. A retransmission (same
        # sender + MSH-10, e.g. after a lost ACK) is acknowledged AA again but
        # not re-processed, so one observation never becomes several records.
        # ponytail: in-memory LRU, lost on restart; a durable store comes with
        # the durable forward queue (A8 known gap).
        self._accepted_keys: collections.OrderedDict[tuple[str, str, str], bytes] = (
            collections.OrderedDict()
        )
        self._dedup_capacity = dedup_capacity
        # F-01: IP allow-list. Default loopback only; config.get_mllp_allowed_networks().
        self._allowed_networks = tuple(
            ipaddress.ip_network(n, strict=False) for n in allowed_networks
        )

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
        # F-03: the stream limit must cover the configured frame cap; asyncio's
        # 64 KiB default made the 1 MiB cap dead code (LimitOverrunError).
        self._server = await asyncio.start_server(
            self._handle_connection,
            self._host,
            self._port,
            limit=self._max_frame_bytes + len(_FRAME_TERMINATOR) + 1,
        )
        _log.info("mllp_listener.start", host=self._host, port=self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            # server.close() does not close live client connections; cancel
            # their handlers so none is left pending (F-03 connection hygiene).
            for task in list(self._handler_tasks):
                task.cancel()
            if self._handler_tasks:
                await asyncio.gather(*self._handler_tasks, return_exceptions=True)
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
        if not self._peer_allowed(peer):
            log.warning("mllp_listener.connection.refused_not_allowed")
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return
        if self._active_connections >= self._max_connections:
            # F-03: refuse beyond the connection cap rather than queue unbounded.
            log.warning("mllp_listener.connection.refused_over_cap", cap=self._max_connections)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return
        self._active_connections += 1
        task = asyncio.current_task()
        if task is not None:
            self._handler_tasks.add(task)
        log.info("mllp_listener.connection.open")
        try:
            while True:
                frame = await self._read_frame(reader, log)
                if frame is None:
                    break  # clean EOF between messages
                key = _dedup_key(frame)
                digest = hashlib.sha256(frame).digest()
                seen = self._accepted_keys.get(key) if key is not None else None
                if seen is not None and seen != digest:
                    # Same sender + MSH-10 but DIFFERENT content (e.g. a
                    # monitor counter reset after reboot): never swallow new
                    # clinical data -- process it normally and say so.
                    log.warning("mllp_listener.frame.control_id_reused_with_new_content")
                if key is not None and seen == digest:
                    # A8-1: byte-identical retransmission of an accepted message.
                    self._accepted_keys.move_to_end(key)
                    log.info("mllp_listener.frame.duplicate_not_reprocessed")
                    outcome = MLLPIngestOutcome(
                        accepted=True,
                        patient_id=None,
                        reason="Duplicate of an accepted message; not re-processed.",
                        bundle=None,
                        ack_code="AA",
                        control_id=key[2],
                    )
                else:
                    # F-02: parsing / DSP / NEWS2 / FHIR assembly run in a worker
                    # thread; only the cheap publish step touches the event loop.
                    outcome = await asyncio.get_running_loop().run_in_executor(
                        None, self._process_frame, frame, log
                    )
                    if outcome.accepted and outcome.bundle is not None:
                        self._publish(outcome.bundle, log)
                        if key is not None:
                            self._remember_accepted(key, digest)
                ack = self._build_ack(outcome)
                writer.write(_START_BLOCK + ack.encode("utf-8") + _FRAME_TERMINATOR)
                await writer.drain()
        except MLLPOversizeError as exc:
            # F03-1 (HD-E6 option 1, approved 2026-11-19): tell the sender the
            # message was refused (AR) instead of a silent close it would
            # simply retransmit into. The stream position is unknown after an
            # overrun, so the connection is closed after the AR.
            log.warning("mllp_listener.connection.oversize_frame", error=str(exc))
            ack = self._build_ack(
                MLLPIngestOutcome(
                    accepted=False,
                    patient_id=None,
                    reason="Frame exceeds the maximum size; message refused.",
                    bundle=None,
                    ack_code="AR",
                )
            )
            with contextlib.suppress(Exception):
                writer.write(_START_BLOCK + ack.encode("utf-8") + _FRAME_TERMINATOR)
                await writer.drain()
                if writer.can_write_eof():
                    writer.write_eof()
                # Closing with unread inbound bytes makes the OS send RST, which
                # can destroy the AR before the sender reads it. Discard what is
                # left of the oversized frame first, bounded in time and bytes.
                await self._discard_input(reader)
        except MLLPFramingError as exc:
            log.warning("mllp_listener.connection.framing_error", error=str(exc))
        except asyncio.IncompleteReadError:
            log.warning("mllp_listener.connection.truncated")
        except (ConnectionResetError, ConnectionAbortedError):
            log.info("mllp_listener.connection.reset_by_peer")
        except TimeoutError:
            log.warning("mllp_listener.connection.read_timeout")
        finally:
            self._active_connections -= 1
            if task is not None:
                self._handler_tasks.discard(task)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            log.info("mllp_listener.connection.close")

    async def _discard_input(self, reader: asyncio.StreamReader) -> None:
        """Drain at most max(4x the frame cap, 1 MiB) or 2 s of input, whichever first."""
        budget = max(4 * self._max_frame_bytes, 1 << 20)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _DISCARD_SECONDS
        while budget > 0:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                chunk = await asyncio.wait_for(reader.read(65536), timeout=remaining)
            except (TimeoutError, ConnectionError):
                return
            if not chunk:
                return
            budget -= len(chunk)

    def _remember_accepted(self, key: tuple[str, str, str], digest: bytes) -> None:
        self._accepted_keys[key] = digest
        self._accepted_keys.move_to_end(key)
        while len(self._accepted_keys) > self._dedup_capacity:
            self._accepted_keys.popitem(last=False)

    def _peer_allowed(self, peer: Any) -> bool:
        try:
            addr = ipaddress.ip_address(peer[0])
        except (TypeError, ValueError, IndexError):
            return False
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        return any(addr in net for net in self._allowed_networks)

    async def _read_frame(self, reader: asyncio.StreamReader, log: Any) -> bytes | None:
        """
        Read one complete MLLP frame (between VT and FS+CR), or None on clean EOF.

        Raises MLLPFramingError for oversized or otherwise malformed frames.
        Raises asyncio.IncompleteReadError if the connection closes mid-frame.
        """
        try:
            leading = await asyncio.wait_for(
                reader.readuntil(_START_BLOCK), timeout=self._idle_timeout
            )
        except asyncio.IncompleteReadError as exc:
            if not exc.partial:
                return None  # clean EOF, no partial data — normal disconnect
            raise
        except asyncio.LimitOverrunError as exc:
            raise MLLPFramingError(
                "More than the frame limit of bytes before any MLLP start block."
            ) from exc

        discarded = leading[:-1]
        if discarded:
            # HAZARD-STREAM-001 mitigation: stray pre-frame bytes are logged,
            # never treated as message content.
            log.warning("mllp_listener.frame.leading_bytes_discarded", n=len(discarded))

        try:
            body_and_terminator = await asyncio.wait_for(
                reader.readuntil(_FRAME_TERMINATOR), timeout=self._frame_timeout
            )
        except asyncio.LimitOverrunError as exc:
            # F-03: handled explicitly (was an unhandled exception + reset);
            # F03-1: answered with AR before the connection is closed.
            raise MLLPOversizeError(
                f"MLLP frame exceeds the {self._max_frame_bytes}-byte maximum "
                "(HAZARD-STREAM-001)."
            ) from exc

        if len(body_and_terminator) > self._max_frame_bytes:
            raise MLLPOversizeError(
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
                ack_code="AR",
            )

        control_id = _raw_control_id(raw_hl7)
        if raw_hl7.lstrip().startswith(("FHS", "BHS")):
            # A8: batch envelopes are not supported — rejected explicitly.
            return MLLPIngestOutcome(
                accepted=False,
                patient_id=None,
                reason="HL7 batch (FHS/BHS) not supported; send single messages.",
                bundle=None,
                ack_code="AR",
            )

        try:
            parse_result = self._adapter.parse(raw_hl7)
        except ValueError as exc:
            log.warning("mllp_listener.frame.parse_error", error=str(exc))
            return MLLPIngestOutcome(
                accepted=False,
                patient_id=None,
                reason=str(exc),
                bundle=None,
                ack_code="AE",
                control_id=control_id,
            )
        control_id = parse_result.message_control_id or control_id

        if parse_result.message_type != "ORU^R01":
            return MLLPIngestOutcome(
                accepted=False,
                patient_id=None,
                reason=(
                    f"Message type '{parse_result.message_type or 'absent'}' "
                    "not supported; only ORU^R01."
                ),
                bundle=None,
                ack_code="AR",
                control_id=control_id,
            )
        if not parse_result.samples:
            return MLLPIngestOutcome(
                accepted=False,
                patient_id=None,
                reason="No usable observation in message.",
                bundle=None,
                ack_code="AE",
                control_id=control_id,
            )

        scale = (
            self._spo2_scale_resolver(parse_result.patient_id)
            if self._spo2_scale_resolver is not None
            else None
        )
        patient_context = PatientContext(
            patient_id=parse_result.patient_id,
            spo2_scale=scale or self._default_spo2_scale,
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
            upstream_findings=parse_result.findings,
        )
        bundle = self._assembler.assemble(
            result=analysis_result,
            patient_context=patient_context,
            device_context=device_context,
            encounter_id=None,
        )

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
            ack_code="AA",
            control_id=control_id,
        )

    def _publish(self, bundle: dict[str, Any], log: Any) -> None:
        """Buffer + fan-out; runs on the event loop (schedules asyncio tasks)."""
        dropped = self._forward_buffer.push(bundle)
        if dropped:
            log.warning("mllp_listener.forward_buffer.overflow_drop")

        if self._live_channel is not None:
            # Fire-and-forget: never adds latency to the ACK/NAK response.
            self._live_channel.schedule_broadcast(bundle, source="mllp")

        if self._subscription_dispatcher is not None:
            self._subscription_dispatcher.schedule_dispatch(bundle)

    @staticmethod
    def _build_ack(outcome: MLLPIngestOutcome) -> str:
        """
        Build an HL7 v2.x ACK/NAK message per MSA acknowledgement conventions.

        A8: AA = accepted (into the volatile store-and-forward buffer — see
        known gap: not a durable store), AE = application error (unparseable,
        or no usable observation), AR = application reject (undecodable frame,
        unsupported message type, batch envelope). MSA-2 echoes the sender's
        MSH-10. The ACK's own MSH-10 is unique (not second-resolution).
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        ack_code = outcome.ack_code or ("AA" if outcome.accepted else "AE")
        own_id = f"ACK{uuid.uuid4().hex[:17].upper()}"
        echo = outcome.control_id.replace("|", "-").replace("\r", " ")
        detail = (outcome.reason or "").replace("|", "-").replace("\r", " ")
        segments = [
            f"MSH|^~\\&|ICU-EDGE-GATEWAY|EDGE|||{ts}||ACK|{own_id}|P|2.5.1",
            f"MSA|{ack_code}|{echo}|{detail}",
        ]
        return "\r".join(segments) + "\r"
