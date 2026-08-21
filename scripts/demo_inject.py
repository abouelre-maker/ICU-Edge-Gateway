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

────────────────────────────────────────────────────────────────────────────
CONTINUOUS MODE (--continuous) — Phase 5 three-bed demonstration narrative
────────────────────────────────────────────────────────────────────────────
The single-shot behaviour above is unchanged and remains the default (it is
what scripts/demo_run.sh drives). Passing --continuous instead runs a
looping, seeded, three-bed narrative through the SAME real pipeline, for a
live dashboard demonstration:

  ICU-BED-01 / PT-DEMO-001 — Philips IntelliVue, stable post-op.
      MSH-3 "PHILIPS_INTELLIVUE"; the five continuous parameters use Philips
      PROPRIETARY OBX-3 codes (HR, SPO2, RESP, NIBP-S, TEMP). Gentle seeded
      drift inside normal ranges. Steady state NEWS2 0-1.

  ICU-BED-02 / PT-DEMO-002 — GE CARESCAPE, COPD on supplemental O2.
      MSH-3 "GE_CARESCAPE"; every OBX-3 is LOINC-coded. SpO2 is held in the
      88-92% COPD target band. This bed exists to demonstrate SpO2 Scale 1
      vs Scale 2 routing — see the SpO2 SCALE note below.

  ICU-BED-03 / PT-DEMO-003 — Draeger Infinity, progressive sepsis.
      MSH-3 "DRAEGER_INFINITY"; the five continuous parameters use Draeger
      proprietary OBX-3 codes (a DIFFERENT proprietary dialect from BED-01:
      RR, NBP-S, T1) so the demo shows three vendor vocabularies normalised
      by one adapter. Runs a deterministic ~90 s deterioration ramp that
      loops, so the demo can be re-run without restarting anything.

SpO2 SCALE — A DELIBERATE CONSTRAINT, NOT AN OVERSIGHT
  infrastructure/streaming/mllp_listener.py builds every PatientContext with
  ONE process-wide `default_spo2_scale` (SCALE_1 by default). HL7 v2.x has
  no field carrying the scale assignment, and this listener does not infer
  one. Scale assignment is a CLINICIAN decision (ISO 14971 HAZARD-SPO2-001),
  so a bed streaming over MLLP is always scored on the listener's configured
  scale regardless of the narrative below.
  BED-02's Scale 1 vs Scale 2 contrast is therefore demonstrated over the
  HTTP path, where `POST /api/v1/ingest?spo2_scale=SCALE_2` makes the
  assignment explicit per request (api/v1/ingest.py, HAZARD-API-001). Use
  --transport http --spo2-scale SCALE_2 to see it, or let the Streamlit
  dashboard's BED-02 toggle re-send the latest message that way.

NEWS2 TRAJECTORY (verified against the real NEWS2Calculator, not asserted):
  BED-03's ramp stages score 0 (NORMAL) -> 3 (LOW) -> 6 (MEDIUM) ->
  7 (HIGH) -> 17 (HIGH), monotonically non-decreasing.
  BED-02 at SpO2 90% on O2 scores 2 (LOW) on Scale 2 versus 5 (MEDIUM) on
  Scale 1 — a three-point swing that also crosses a risk band.
  See tests/unit/test_demo_streamer.py, which re-derives all of the above
  through the validated calculator rather than hardcoding expectations.

This module generates and TRANSMITS messages only. It performs no clinical
computation: every score shown comes back from the gateway.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import random
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

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
    delta_task = asyncio.ensure_future(
        _wait_for_delta(ws_url, patient_id, args.timeout)
    )
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


# ════════════════════════════════════════════════════════════════════════════
# CONTINUOUS THREE-BED NARRATIVE MODE (Phase 5)
# ════════════════════════════════════════════════════════════════════════════

BANNER: str = "SYNTHETIC DEMONSTRATION DATA - NOT REAL PATIENT DATA"


@dataclass(frozen=True)
class Vitals:
    """One instant of a synthetic bed's observable state."""

    resp_rate: float
    spo2: float
    systolic_bp: float
    heart_rate: float
    temperature_c: float
    on_supplemental_o2: bool
    avpu: str  # OBX-5 ST value; must be a key of the adapter's _AVPU_STRINGS


@dataclass(frozen=True)
class BedProfile:
    """
    Static identity of one demonstration bed.

    `obx3_codes` maps each parameter to the exact OBX-3 field this bed emits.
    Every code here is verified against the adapter's _LOINC_TO_TYPE /
    _VENDOR_TO_TYPE tables by tests/unit/test_demo_streamer.py, which asserts
    skipped_obx_count == 0 for every generated message — no code is emitted
    that the adapter cannot already map, and the adapter is never edited to
    accommodate this script.
    """

    bed_id: str
    patient_id: str
    sending_application: str  # MSH-3, drives adapter vendor detection
    vendor_label: str
    narrative: str
    obx3_codes: dict[str, str]
    clinical_spo2_scale: str  # narrative intent; see module docstring


# ── OBX-3 code vocabularies ─────────────────────────────────────────────────
# Philips IntelliVue proprietary identifiers. Coding system "PHILIPS" is
# deliberately NOT "LN"/"LOINC"/"" so the adapter routes these through
# _VENDOR_TO_TYPE rather than the LOINC table.
_PHILIPS_CODES: dict[str, str] = {
    "resp_rate": "RESP^Respiration Rate^PHILIPS",
    "spo2": "SPO2^Arterial Oxygen Saturation^PHILIPS",
    "systolic_bp": "NIBP-S^Non-Invasive Systolic^PHILIPS",
    "heart_rate": "HR^Heart Rate^PHILIPS",
    "temperature": "TEMP^Temperature^PHILIPS",
    # Supplemental O2 and AVPU have no widely-used Philips proprietary OBX-3
    # identifier in the adapter's table, so they use the standard LOINC codes
    # here. Mixed proprietary/standard coding within one message is ordinary
    # real-world interface-engine output, not a demo shortcut.
    "supplemental_o2": "57834-7^Oxygen therapy^LN",
    "avpu": "76270-8^AVPU score^LN",
}

# GE CARESCAPE — fully LOINC-coded, the contrast case against Philips.
_LOINC_CODES: dict[str, str] = {
    "resp_rate": "9279-1^Respiratory rate^LN",
    "spo2": "59408-5^Oxygen saturation in Arterial blood by Pulse oximetry^LN",
    "systolic_bp": "8480-6^Systolic blood pressure^LN",
    "heart_rate": "8867-4^Heart rate^LN",
    "temperature": "8310-5^Body temperature^LN",
    "supplemental_o2": "57834-7^Oxygen therapy^LN",
    "avpu": "76270-8^AVPU score^LN",
}

# Draeger Infinity — a DIFFERENT proprietary dialect from Philips above
# (RR not RESP, NBP-S not NIBP-S, T1 not TEMP), so the demo shows one adapter
# normalising three distinct vendor vocabularies rather than two.
_DRAEGER_CODES: dict[str, str] = {
    "resp_rate": "RR^Respiratory Rate^DRAEGER",
    "spo2": "SPO2^Pulse Oximetry^DRAEGER",
    "systolic_bp": "NBP-S^Non-Invasive BP Systolic^DRAEGER",
    "heart_rate": "HR^Heart Rate^DRAEGER",
    "temperature": "T1^Temperature Channel 1^DRAEGER",
    "supplemental_o2": "57834-7^Oxygen therapy^LN",
    "avpu": "76270-8^AVPU score^LN",
}


BED_PROFILES: tuple[BedProfile, ...] = (
    BedProfile(
        bed_id="ICU-BED-01",
        patient_id="PT-DEMO-001",
        sending_application="PHILIPS_INTELLIVUE",
        vendor_label="Philips IntelliVue MX800",
        narrative="Stable post-operative",
        obx3_codes=_PHILIPS_CODES,
        clinical_spo2_scale="SCALE_1",
    ),
    BedProfile(
        bed_id="ICU-BED-02",
        patient_id="PT-DEMO-002",
        sending_application="GE_CARESCAPE",
        vendor_label="GE CARESCAPE B650",
        narrative="COPD, hypercapnic respiratory failure, on supplemental O2",
        obx3_codes=_LOINC_CODES,
        clinical_spo2_scale="SCALE_2",
    ),
    BedProfile(
        bed_id="ICU-BED-03",
        patient_id="PT-DEMO-003",
        sending_application="DRAEGER_INFINITY",
        vendor_label="Draeger Infinity Delta",
        narrative="Progressive sepsis with deterioration",
        obx3_codes=_DRAEGER_CODES,
        clinical_spo2_scale="SCALE_1",
    ),
)


# ── BED-03 sepsis ramp ──────────────────────────────────────────────────────
# Deterministic and jitter-free BY DESIGN: this is a scripted clinical
# narrative, and the seeded drift applied to BED-01/BED-02 could otherwise
# push a parameter across a NEWS2 band boundary and make the trajectory
# non-monotonic. Stage values were chosen by evaluating them through the real
# NEWS2Calculator, not by hand-scoring.
#
# The waypoints requested for this demo (RR 22, SpO2 94, SBP 100, HR 110,
# T 38.8) evaluate to a total of 7 = HIGH -- they are already past MEDIUM.
# Stages "early" and "established" below are therefore inserted BEFORE that
# waypoint so the dashboard visibly dwells in LOW and MEDIUM on the way up,
# rather than stepping straight from NORMAL to HIGH.
_SEPSIS_STAGES: tuple[tuple[float, str, Vitals], ...] = (
    (0.00, "baseline", Vitals(16.0, 98.0, 120.0, 80.0, 37.0, False, "A")),
    (0.22, "early-deterioration", Vitals(20.0, 95.0, 115.0, 95.0, 38.2, False, "A")),
    (0.44, "established-sepsis", Vitals(22.0, 94.0, 105.0, 105.0, 38.5, False, "A")),
    (0.66, "septic-shock-onset", Vitals(22.0, 94.0, 100.0, 110.0, 38.8, False, "A")),
    (0.88, "critical-new-confusion", Vitals(28.0, 89.0, 85.0, 140.0, 39.5, False, "C")),
)

SEPSIS_LOOP_SECONDS: float = 90.0


def sepsis_stage_at(progress: float) -> tuple[str, Vitals]:
    """
    Return the (stage_name, Vitals) in effect at `progress` in [0, 1).

    Step-and-hold rather than interpolation: each stage is HELD until the
    next begins, so every NEWS2 band is on screen long enough to read and
    narrate. Interpolating would sweep through MEDIUM in a couple of frames.
    """
    progress = progress % 1.0
    name, vitals = _SEPSIS_STAGES[0][1], _SEPSIS_STAGES[0][2]
    for threshold, stage_name, stage_vitals in _SEPSIS_STAGES:
        if progress >= threshold:
            name, vitals = stage_name, stage_vitals
    return name, vitals


def _drift(rng: random.Random, centre: float, amplitude: float, phase: float) -> float:
    """
    Gentle bounded oscillation around `centre`.

    Combines a slow sinusoid (physiological-looking, reproducible) with a
    small seeded random component. Amplitude is kept well inside the
    surrounding NEWS2 band so ordinary drift never flips a component score --
    a stable bed must LOOK alive without its score flickering.
    """
    jitter = rng.uniform(-amplitude / 3.0, amplitude / 3.0)
    return centre + amplitude * math.sin(phase) + jitter


def vitals_for_bed(
    profile: BedProfile,
    tick: int,
    elapsed_s: float,
    rng: random.Random,
) -> tuple[str, Vitals]:
    """Produce the current Vitals for one bed. Returns (stage_label, vitals)."""
    phase = tick / 6.0

    if profile.bed_id == "ICU-BED-01":
        return "stable", Vitals(
            resp_rate=round(_drift(rng, 14.0, 1.5, phase), 1),
            spo2=round(_drift(rng, 97.5, 1.0, phase * 0.7), 1),
            systolic_bp=round(_drift(rng, 118.0, 5.0, phase * 0.5), 1),
            heart_rate=round(_drift(rng, 68.0, 4.0, phase), 1),
            temperature_c=round(_drift(rng, 36.8, 0.2, phase * 0.3), 1),
            on_supplemental_o2=False,
            avpu="A",
        )

    if profile.bed_id == "ICU-BED-02":
        # SpO2 held inside the 88-92% COPD target band on supplemental O2.
        # Clamped explicitly so seeded drift cannot wander outside the band
        # that makes this bed's Scale 1 vs Scale 2 contrast meaningful.
        spo2 = min(92.0, max(88.0, _drift(rng, 90.0, 1.2, phase * 0.6)))
        return "copd-target-band", Vitals(
            resp_rate=round(_drift(rng, 18.0, 1.5, phase), 1),
            spo2=round(spo2, 1),
            systolic_bp=round(_drift(rng, 125.0, 5.0, phase * 0.5), 1),
            heart_rate=round(_drift(rng, 78.0, 4.0, phase), 1),
            temperature_c=round(_drift(rng, 36.9, 0.2, phase * 0.3), 1),
            on_supplemental_o2=True,
            avpu="A",
        )

    # ICU-BED-03 — deterministic scripted ramp, no jitter (see _SEPSIS_STAGES).
    return sepsis_stage_at((elapsed_s % SEPSIS_LOOP_SECONDS) / SEPSIS_LOOP_SECONDS)


# ── HL7 v2.5.1 ORU^R01 construction ─────────────────────────────────────────


def _hl7_timestamp(moment: datetime) -> str:
    """HL7 DTM, second precision: YYYYMMDDHHMMSS."""
    return moment.strftime("%Y%m%d%H%M%S")


def build_oru_r01(
    profile: BedProfile,
    vitals: Vitals,
    sequence: int,
    moment: datetime | None = None,
) -> str:
    """
    Build one HL7 v2.5.1 ORU^R01, segment by segment.

    Field separator `|`, encoding characters `^~\\&`, MSH-7 in
    YYYYMMDDHHMMSS, OBX-11 result status `F` (Final), OBX-14 observation
    date/time on every OBX. Segments are CR-terminated per HL7, NOT LF.
    """
    moment = moment or datetime.now(tz=timezone.utc)
    ts = _hl7_timestamp(moment)
    control_id = f"{profile.bed_id.replace('-', '')}{ts}{sequence:04d}"
    codes = profile.obx3_codes

    segments: list[str] = [
        f"MSH|^~\\&|{profile.sending_application}|ICU_UNIT|EHR|HOSPITAL|{ts}"
        f"||ORU^R01|{control_id}|P|2.5.1",
        f"PID|1||{profile.patient_id}^^^HOSP^MR||DEMO^SYNTHETIC||19700101|U",
        f"OBR|1||ORDER-{control_id}|||||{ts}",
    ]

    numeric_observations: tuple[tuple[str, float, str], ...] = (
        (codes["heart_rate"], vitals.heart_rate, "/min"),
        (codes["resp_rate"], vitals.resp_rate, "/min"),
        (codes["spo2"], vitals.spo2, "%"),
        (codes["systolic_bp"], vitals.systolic_bp, "mmHg"),
        (codes["temperature"], vitals.temperature_c, "Cel"),
    )

    def _obx(index: int, value_type: str, obx3: str, value: str, unit: str) -> str:
        """
        One OBX segment with every field in its correct ordinal position.

        Built through a single helper rather than per-observation f-strings
        because the unit field (OBX-6) must be PRESENT-BUT-EMPTY for
        unitless observations, not omitted: omitting it shifts OBX-11
        (result status) and OBX-14 (observation timestamp) one position to
        the left, silently producing structurally invalid HL7 that the
        adapter still happens to parse (it reads OBX-3/OBX-5 and does not
        require OBX-11). Positions asserted by
        tests/unit/test_demo_streamer.py::TestHl7StructuralConformance.

        Fields: OBX-1 set ID | OBX-2 value type | OBX-3 identifier |
        OBX-4 sub-ID | OBX-5 value | OBX-6 units | OBX-7 reference range |
        OBX-8..10 unused | OBX-11 result status | OBX-12..13 unused |
        OBX-14 observation date/time.
        """
        return f"OBX|{index}|{value_type}|{obx3}||{value}|{unit}|||||F|||{ts}"

    index = 0
    for obx3, value, unit in numeric_observations:
        index += 1
        segments.append(_obx(index, "NM", obx3, str(value), unit))

    index += 1
    o2_value = "1" if vitals.on_supplemental_o2 else "0"
    segments.append(_obx(index, "NM", codes["supplemental_o2"], o2_value, ""))

    # AVPU is an ST (string) observation, not NM -- the adapter maps OBX-5
    # through _AVPU_STRINGS, and a numeric value here would be skipped.
    index += 1
    segments.append(_obx(index, "ST", codes["avpu"], vitals.avpu, ""))

    return "\r".join(segments) + "\r"


# ── Transports ──────────────────────────────────────────────────────────────


async def _send_http(
    host: str,
    port: int,
    message: str,
    spo2_scale: str,
    timeout_s: float,
) -> tuple[str, dict[str, str]]:
    """
    POST the raw HL7 to /api/v1/ingest as text/plain.

    Unlike MLLP, this path carries the SpO2 scale explicitly as a query
    parameter (HAZARD-API-001) -- this is what makes BED-02's Scale 1 vs
    Scale 2 contrast demonstrable at all. Returns (summary, response headers)
    so the caller can log the gateway's own X-NEWS2-* values.
    """
    import urllib.request  # noqa: PLC0415 - optional path, import kept local

    # device_vendor is deliberately NOT sent: it is an optional MonitorVendor
    # enum override, and omitting it is what makes the endpoint auto-detect
    # the vendor from MSH-3 -- which is the behaviour this demo is showing
    # off. (There is no "auto" enum member; sending one returns 422.)
    url = f"http://{host}:{port}/api/v1/ingest?spo2_scale={spo2_scale}"
    request = urllib.request.Request(  # nosec B310 - fixed http scheme, local demo host
        url,
        data=message.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
        method="POST",
    )
    loop = asyncio.get_running_loop()

    def _do() -> tuple[str, dict[str, str]]:
        with urllib.request.urlopen(  # nosec B310 - see above
            request, timeout=timeout_s
        ) as response:
            # Keys are lower-cased deliberately: uvicorn emits response
            # header names in lower case, and flattening urllib's
            # case-insensitive HTTPMessage into a plain dict would otherwise
            # lose that insensitivity and make every "X-NEWS2-Total" lookup
            # silently miss.
            headers = {k.lower(): v for k, v in response.headers.items()}
            return f"HTTP {response.status}", headers

    return await loop.run_in_executor(None, _do)


async def _send_one(
    profile: BedProfile,
    message: str,
    args: argparse.Namespace,
) -> tuple[str, dict[str, str]]:
    """Dispatch one message over the selected transport."""
    if args.transport == "http":
        scale = args.spo2_scale or profile.clinical_spo2_scale
        return await _send_http(
            args.gateway_host, args.http_port, message, scale, args.timeout
        )
    ack = await _send_mllp(args.gateway_host, args.mllp_port, message)
    return ack.replace("\r", " ").strip(), {}


# ── Live NEWS2 correlation (optional observer) ──────────────────────────────


class _News2Observer:
    """
    Consumes the live dashboard WebSocket and records the latest NEWS2 per
    patient, so each send can be logged with the score the gateway actually
    produced rather than one this script computed.

    Purely observational. If the socket is unavailable the streamer keeps
    sending and simply logs no score -- a broken observer must never stop the
    demonstration data flowing.
    """

    def __init__(self, ws_url: str) -> None:
        self._ws_url = ws_url
        self._latest: dict[str, dict] = {}
        self._task: asyncio.Task[None] | None = None

    def latest_for(self, patient_id: str) -> dict | None:
        return self._latest.get(patient_id)

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                async with websockets.connect(self._ws_url, open_timeout=5.0) as ws:
                    async for raw in ws:
                        try:
                            delta = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        patient_id = delta.get("patient_id")
                        news2 = delta.get("news2")
                        if patient_id and news2:
                            self._latest[patient_id] = news2
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - observer must never kill the stream
                await asyncio.sleep(2.0)


# ── Continuous run loop ─────────────────────────────────────────────────────


async def _await_gateway(args: argparse.Namespace, attempts: int = 10) -> bool:
    """
    Wait for the gateway to accept a connection, with exponential backoff.

    The launcher starts the gateway and this streamer in parallel, so "not up
    yet" is the expected first state, not an error.
    """
    port = args.http_port if args.transport == "http" else args.mllp_port
    delay = 0.5
    for attempt in range(1, attempts + 1):
        try:
            _, writer = await asyncio.open_connection(args.gateway_host, port)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return True
        except OSError:
            if attempt == attempts:
                return False
            print(
                f"[demo_inject] gateway not reachable on port {port} yet "
                f"(attempt {attempt}/{attempts}); retrying in {delay:.1f}s",
                file=sys.stderr,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2.0, 8.0)
    return False


def _print_banner(args: argparse.Namespace, profiles: tuple[BedProfile, ...]) -> None:
    rule = "=" * 74
    duration = "unlimited" if args.duration == 0 else f"{args.duration}s"
    print(rule, file=sys.stderr)
    print(f"  {BANNER}", file=sys.stderr)
    print(rule, file=sys.stderr)
    for profile in profiles:
        print(
            f"  {profile.bed_id}  {profile.patient_id}  "
            f"{profile.vendor_label} - {profile.narrative}",
            file=sys.stderr,
        )
    print(
        f"  transport={args.transport}  interval={args.interval}s  "
        f"seed={args.seed}  duration={duration}",
        file=sys.stderr,
    )
    print(rule, file=sys.stderr)


async def _run_continuous(args: argparse.Namespace) -> int:
    bed_count = max(1, min(args.beds, len(BED_PROFILES)))
    profiles = BED_PROFILES[:bed_count]
    _print_banner(args, profiles)

    if not await _await_gateway(args):
        print("[demo_inject] FAILED: gateway never became reachable.", file=sys.stderr)
        return 1

    observer: _News2Observer | None = None
    if not args.no_observer:
        observer = _News2Observer(
            f"ws://{args.gateway_host}:{args.http_port}/api/v1/live/vitals"
        )
        observer.start()
        await asyncio.sleep(0.5)  # let the WS register before the first send

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        signal_number = getattr(signal, signal_name, None)
        if signal_number is None:
            continue
        # add_signal_handler is POSIX-only; on Windows the KeyboardInterrupt
        # path in main() handles Ctrl+C instead.
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(signal_number, stop_event.set)

    rngs = {p.bed_id: random.Random(f"{args.seed}:{p.bed_id}") for p in profiles}
    started = time.monotonic()
    tick = 0
    sent = 0

    try:
        while not stop_event.is_set():
            elapsed = time.monotonic() - started
            if args.duration and elapsed >= args.duration:
                break

            for profile in profiles:
                stage, vitals = vitals_for_bed(
                    profile, tick, elapsed, rngs[profile.bed_id]
                )
                message = build_oru_r01(profile, vitals, sent)
                send_started = time.monotonic()
                try:
                    summary, headers = await _send_one(profile, message, args)
                except (OSError, asyncio.IncompleteReadError) as exc:
                    print(
                        f"[demo_inject] {profile.bed_id} send failed: {exc}",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(1.0)
                    continue
                latency_ms = (time.monotonic() - send_started) * 1000.0
                sent += 1

                # Prefer the HTTP response headers when this transport
                # provides them -- they are this exact message's score. The
                # WebSocket observer is a fallback for MLLP, where the ACK
                # carries no score, and is therefore one message behind.
                news2 = observer.latest_for(profile.patient_id) if observer else None
                if headers.get("x-news2-total") is not None:
                    news2 = {
                        "total": headers.get("x-news2-total"),
                        "risk_level": headers.get("x-news2-risk-level"),
                    }
                score_text = (
                    f"NEWS2={news2.get('total')} {news2.get('risk_level')}"
                    if news2
                    else "NEWS2=(awaiting delta)"
                )
                print(
                    f"[demo_inject] {profile.bed_id} {profile.patient_id} "
                    f"stage={stage} {score_text} "
                    f"rtt={latency_ms:.1f}ms ack={summary[:60]}",
                    file=sys.stderr,
                )

            tick += 1
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=args.interval)
    finally:
        if observer is not None:
            await observer.stop()

    print(f"[demo_inject] stopped cleanly after {sent} messages.", file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """
    CLI surface.

    The single-shot flags (--patient-id, --gateway-host, --mllp-port,
    --http-port, --timeout) are UNCHANGED and remain the default mode, since
    scripts/demo_run.sh invokes exactly those and parses this script's stdout
    as the resulting delta JSON. Continuous mode is opt-in via --continuous
    and writes only to stderr, so it can never corrupt that contract.
    """
    parser = argparse.ArgumentParser(description=__doc__)

    # ── Single-shot mode (default; demo_run.sh's contract) ──────────────────
    parser.add_argument(
        "--patient-id",
        help="Single-shot mode: patient ID to inject. Required unless --continuous.",
    )
    parser.add_argument(
        "--gateway-host", "--host", dest="gateway_host", default="localhost"
    )
    parser.add_argument("--mllp-port", type=int, default=2575)
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--timeout", type=float, default=20.0)

    # ── Continuous three-bed narrative mode (Phase 5) ───────────────────────
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run the looping three-bed demonstration narrative.",
    )
    parser.add_argument(
        "--beds",
        type=int,
        default=len(BED_PROFILES),
        help=f"Number of beds to drive, 1-{len(BED_PROFILES)} (default: all).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between message rounds (default: 2.0).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed; identical seeds produce identical output (default: 42).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Total seconds to run; 0 = run until interrupted (default: 0).",
    )
    parser.add_argument(
        "--transport",
        choices=("mllp", "http"),
        default="mllp",
        help="mllp = framed TCP to the MLLP listener; http = POST /api/v1/ingest.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override the transport's port (MLLP port, or HTTP port for --transport http).",
    )
    parser.add_argument(
        "--spo2-scale",
        choices=("SCALE_1", "SCALE_2"),
        default=None,
        help=(
            "HTTP transport only: SpO2 scale sent as a query parameter "
            "(HAZARD-API-001). MLLP cannot carry this -- see module docstring."
        ),
    )
    parser.add_argument(
        "--no-observer",
        action="store_true",
        help="Do not open the live WebSocket to correlate NEWS2 back into the log.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    # --port is a transport-relative alias; resolve it to the concrete port
    # the selected transport actually uses.
    if args.port is not None:
        if args.transport == "http":
            args.http_port = args.port
        else:
            args.mllp_port = args.port

    if args.continuous:
        try:
            return asyncio.run(_run_continuous(args))
        except KeyboardInterrupt:
            # Windows Ctrl+C path: loop.add_signal_handler is unavailable
            # there, so the interrupt surfaces here instead.
            print("\n[demo_inject] interrupted; stopping.", file=sys.stderr)
            return 0

    if not args.patient_id:
        parser.error("--patient-id is required unless --continuous is given.")

    try:
        delta = asyncio.run(_run(args))
    except (TimeoutError, OSError) as exc:
        print(f"[demo_inject] FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(delta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
