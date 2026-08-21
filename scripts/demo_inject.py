#!/usr/bin/env python3
"""
scripts/demo_inject.py — Single real-pipeline HL7v2 injection helper for
scripts/demo_run.sh. Not a mock: every step below talks to the actually
running gateway container over the real wire protocols it serves.

1. Opens a real WebSocket connection to WS /api/v1/live/vitals
   (src/api/v1/live.py — the same live dashboard channel a real dashboard
   client would use).
2. Sends ONE MLLP-framed HL7 v2.x ORU^R01 message over a real TCP socket to
   the gateway's MLLP listener (infrastructure/streaming/mllp_listener.py,
   port 2575) — identical framing to
   deploy/local/hl7_monitor_simulator/simulate.py, which is already part of
   this project's docker-compose.yml stack.
3. Reads the real MLLP ACK the gateway sends back.
4. Waits for the live-dashboard delta that this one message triggers
   (infrastructure/streaming/live_dashboard_channel.py::build_delta) and
   prints it as JSON to stdout.

Deliberate artifact under test: the message carries TWO Heart Rate
(LOINC 8867-4) OBX observations for the same patient —

  OBX|1: 450 bpm at ts0   — outside PhysiologicalBoundsChecker's configured
                             HEART_RATE bound of [20, 250]
                             (domain/services/artifact_rejector.py) —
                             this is the injected artifact.
  OBX|2: 82 bpm  at ts0+1s — a physiologically valid corrected reading.

domain/services/news2_calculator.py::_extract_value() selects only the most
recent WITHIN-BOUNDS sample per vital-sign type, so the 450 bpm spike is
excluded from NEWS2 scoring by the real DSP pipeline — not filtered by this
script. Had the spike NOT been rejected, NEWS2._score_heart_rate() would
have scored it 3 (≥131 bpm, the most severe pulse-rate band) — a false
critical-risk signal. Rejecting it lets the score reflect the corrected
82 bpm reading (score 0) instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

try:
    import websockets
except ImportError:  # pragma: no cover - preflight message, not exercised in CI
    print(
        "[demo_inject] ERROR: the 'websockets' package is required.\n"
        "Install dev dependencies first: "
        "python -m pip install -r requirements-dev.txt",
        file=sys.stderr,
    )
    raise SystemExit(1) from None

_START_BLOCK = b"\x0b"
_END_BLOCK = b"\x1c"
_CARRIAGE_RETURN = b"\x0d"
_FRAME_TERMINATOR = _END_BLOCK + _CARRIAGE_RETURN


def _oru_message(patient_id: str, msg_id: str, ts0: str, ts1: str) -> str:
    """
    Minimal but complete ORU^R01 — same segment shape as
    deploy/local/hl7_monitor_simulator/simulate.py's fixture, with a
    deliberate duplicate Heart Rate OBX (artifact spike + correction).
    """
    return (
        f"MSH|^~\\&|DEMO_MONITOR|ICU_UNIT|EHR|HOSPITAL|{ts0}"
        f"||ORU^R01|{msg_id}|P|2.5.1\r"
        f"PID|1||{patient_id}^^^HOSP^MR||DEMO^PATIENT||19800101|M\r"
        f"OBR|1||ORDER-{msg_id}|||||{ts0}\r"
        f"OBX|1|NM|8867-4^Heart rate^LN||450|/min|60-100||||F|||{ts0}\r"
        f"OBX|2|NM|8867-4^Heart rate^LN||82|/min|60-100||||F|||{ts1}\r"
        f"OBX|3|NM|59408-5^SpO2^LN||97|%|95-100||||F|||{ts0}\r"
        f"OBX|4|NM|9279-1^Respiratory rate^LN||18|/min|12-20||||F|||{ts0}\r"
        f"OBX|5|NM|8480-6^Systolic BP^LN||124|mmHg|90-140||||F|||{ts0}\r"
        f"OBX|6|NM|8310-5^Temperature^LN||37.1|Cel|36.1-38.0||||F|||{ts0}\r"
        f"OBX|7|NM|57834-7^Supplemental O2^LN||0||||||F|||{ts0}\r"
    )


async def _send_mllp(host: str, port: int, message: str) -> str:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        frame = _START_BLOCK + message.encode("utf-8") + _END_BLOCK + _CARRIAGE_RETURN
        writer.write(frame)
        await writer.drain()
        ack_frame = await reader.readuntil(_FRAME_TERMINATOR)
        return ack_frame.strip(_START_BLOCK + _FRAME_TERMINATOR).decode(
            "utf-8", errors="replace"
        )
    finally:
        writer.close()
        await writer.wait_closed()


async def _wait_for_delta(ws_url: str, patient_id: str, timeout_s: float) -> dict:
    async with websockets.connect(ws_url, open_timeout=timeout_s) as ws:
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            delta = json.loads(raw)
            if delta.get("patient_id") == patient_id:
                return delta
            # Not our message (e.g. the compose stack's own HL7 simulator
            # sidecar cycling in the background) — keep waiting.
    raise TimeoutError(
        f"No live-dashboard delta for patient_id={patient_id!r} within {timeout_s}s"
    )


async def _run(args: argparse.Namespace) -> dict:
    patient_id = args.patient_id
    msg_id = f"DEMO{int(time.time())}"
    now = time.time()
    ts0 = time.strftime("%Y%m%d%H%M%S", time.gmtime(now))
    ts1 = time.strftime("%Y%m%d%H%M%S", time.gmtime(now + 1))
    message = _oru_message(patient_id, msg_id, ts0, ts1)

    ws_url = f"ws://{args.gateway_host}:{args.http_port}/api/v1/live/vitals"
    delta_task = asyncio.ensure_future(_wait_for_delta(ws_url, patient_id, args.timeout))
    # Give the WS handshake/registration a moment to complete before the
    # MLLP send races it — otherwise the delta could be broadcast before
    # this client's queue is registered in LiveDashboardChannel.
    await asyncio.sleep(0.5)

    print(
        f"[demo_inject] sending MLLP ORU^R01 for patient_id={patient_id} "
        f"(msg_id={msg_id}) to {args.gateway_host}:{args.mllp_port}",
        file=sys.stderr,
    )
    ack = await _send_mllp(args.gateway_host, args.mllp_port, message)
    print(f"[demo_inject] MLLP ACK received: {ack!r}", file=sys.stderr)

    delta = await delta_task
    return delta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--gateway-host", default="localhost")
    parser.add_argument("--mllp-port", type=int, default=2575)
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    try:
        delta = asyncio.run(_run(args))
    except (TimeoutError, OSError) as exc:
        print(f"[demo_inject] FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(delta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
