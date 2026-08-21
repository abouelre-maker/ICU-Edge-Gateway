"""
ICU Edge Gateway — Clinical Demonstration Dashboard (Streamlit).

Run with:
    streamlit run demo/dashboard.py

REGULATORY SCOPE
This file lives OUTSIDE src/ deliberately. The Dockerfile does
`COPY --chown=gateway:gateway src/ ./src/`, so anything under src/ ships
inside the SaMD image (IEC 62304 Class B) and widens its regulatory scope.
Keeping the dashboard here makes the exclusion structural — the COPY never
sees it — instead of depending on a .dockerignore entry a future edit could
drop. .dockerignore also excludes demo/, and the docker-verify CI workflow
asserts the file is absent from the built image.

FDA CDS: This dashboard is a DISPLAY of the gateway's advisory-only output.
It computes no clinical value. Every NEWS2 total, component sub-score, risk
level and escalation shown here was produced by the gateway's validated
NEWS2Calculator and is read verbatim from the FHIR R4 Bundle. Nothing on
this screen is derived, recomputed, rounded, or adjusted for presentation.

ARCHITECTURE
All pure logic lives in demo/dashboard_logic.py, which imports neither
Streamlit nor Plotly and is unit-tested inside the pinned production venv.
Every st.* call in this file is inside main(), invoked under
`if __name__ == "__main__"` — Streamlit executes the script as __main__, so
this runs normally under `streamlit run` while keeping import side-effects
out of the logic module.

DEPENDENCIES
Streamlit requires websockets<17 while the gateway's requirements.txt pins
websockets==17.0.1. The two cannot share one environment, so the demo layer
installs into its OWN venv (venv-demo) from requirements-demo.txt, leaving
the validated production/test environment untouched. See requirements-demo.txt.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import plotly.graph_objects as go
import streamlit as st
import websockets
from dashboard_logic import (
    COMPONENT_ORDER,
    TREND_VITALS,
    WHATIF_PATIENT_ID,
    BedState,
    ScaleComparison,
    append_trend,
    backoff_delay,
    bed_state_from_delta,
    build_whatif_payload,
    connection_status,
    is_whatif_patient,
    messages_per_minute,
    read_news2_headers,
    risk_style,
)

GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 8000
WS_URL = f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}/api/v1/live/vitals"
BASE_URL = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}"

# Match the streamer's default send interval. Rerunning FASTER than data
# arrives buys nothing and actively harms correctness: st.rerun() tears
# down the script, so if a full render takes longer than this interval the
# LAST-rendered bed card is preempted and silently keeps showing an older
# value while earlier cards update. That is how ICU-BED-03 (rendered third)
# sat at its baseline vitals while the gateway was broadcasting HIGH.
REFRESH_SECONDS = 2.0
HEALTH_POLL_SECONDS = 5.0


# ════════════════════════════════════════════════════════════════════════════
# Background WebSocket reader
# ════════════════════════════════════════════════════════════════════════════


class DeltaReader:
    """
    Reads WS /api/v1/live/vitals on a daemon thread into an unbounded queue.

    Unbounded on purpose: the Streamlit script drains the whole queue on each
    rerun, so a frame that arrived is never dropped by this dashboard. (The
    gateway's own per-client queue is bounded at 200 with a drop-oldest
    policy — HAZARD-STREAM-005 — which is the correct place for that
    backpressure, not here.)

    The main thread never blocks on the socket: it only calls
    queue.get_nowait() until empty.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self.frames: queue.Queue[dict[str, Any]] = queue.Queue()
        self.connected = threading.Event()
        self.reconnect_at: float | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, open_timeout=5) as ws:
                    attempt = 0
                    self.reconnect_at = None
                    self.connected.set()
                    async for raw in ws:
                        try:
                            self.frames.put(json.loads(raw))
                        except json.JSONDecodeError:
                            continue
            except Exception:  # noqa: BLE001 — any failure means "retry"
                pass
            finally:
                self.connected.clear()

            attempt += 1
            delay = backoff_delay(attempt)
            self.reconnect_at = time.monotonic() + delay
            await asyncio.sleep(delay)


# ════════════════════════════════════════════════════════════════════════════
# Gateway HTTP calls
# ════════════════════════════════════════════════════════════════════════════


def fetch_health(timeout: float = 3.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(  # nosec B310 — fixed http scheme, local host
            f"{BASE_URL}/health", timeout=timeout
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — health is advisory; never break the page
        return None


def post_vitals(
    payload: dict[str, Any], timeout: float = 5.0
) -> tuple[int | None, str | None, float | None]:
    """
    POST /api/v1/vitals and return (news2_total, risk_level, duration_ms).

    Headers are read case-insensitively via read_news2_headers(): uvicorn
    lower-cases response header names, so looking for the documented
    "X-NEWS2-Total" spelling verbatim silently misses.
    """
    request = urllib.request.Request(  # nosec B310 — fixed http scheme, local host
        f"{BASE_URL}/api/v1/vitals",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            headers = {k: v for k, v in response.headers.items()}
            response.read()
    except urllib.error.HTTPError as exc:
        st.session_state.whatif_error = f"HTTP {exc.code}: {exc.read()[:300]!r}"
        return None, None, None
    except Exception as exc:  # noqa: BLE001
        st.session_state.whatif_error = str(exc)
        return None, None, None

    duration_ms = (time.monotonic() - started) * 1000.0
    total, risk = read_news2_headers(headers)
    return total, risk, duration_ms


def run_scale_comparison(state: BedState) -> ScaleComparison:
    """Score identical vitals under both SpO2 scales, via the real endpoint."""
    st.session_state.whatif_error = None
    latencies: list[float] = []

    results: dict[str, tuple[int | None, str | None]] = {}
    for scale in ("SCALE_1", "SCALE_2"):
        payload = build_whatif_payload(state, scale, patient_id=WHATIF_PATIENT_ID)
        total, risk, duration = post_vitals(payload)
        results[scale] = (total, risk)
        if duration is not None:
            latencies.append(duration)

    if latencies:
        st.session_state.http_latencies = (
            st.session_state.get("http_latencies", []) + latencies
        )[-20:]

    return ScaleComparison(
        scale_1_total=results["SCALE_1"][0],
        scale_1_risk=results["SCALE_1"][1],
        scale_2_total=results["SCALE_2"][0],
        scale_2_risk=results["SCALE_2"][1],
    )


# ════════════════════════════════════════════════════════════════════════════
# Styling
# ════════════════════════════════════════════════════════════════════════════

_CSS = """
<style>
  .stApp { background: #0e1117; }
  .icu-banner {
      background: #4a1c1c; border-left: 5px solid #ff5252; color: #ffe9e9;
      padding: 0.7rem 1rem; border-radius: 4px; font-size: 0.86rem;
      line-height: 1.5; margin-bottom: 0.8rem;
  }
  .icu-card {
      background: #161b22; border: 1px solid #30363d; border-radius: 8px;
      padding: 1rem; margin-bottom: 0.6rem;
  }
  .icu-card.stale { opacity: 0.45; border-style: dashed; }
  .icu-bed-id {
      font-size: 1.15rem; font-weight: 700; color: #e6edf3; letter-spacing: 0.02em;
  }
  .icu-meta { font-size: 0.75rem; color: #8b949e; margin-bottom: 0.5rem; }
  .icu-total {
      font-size: 3.4rem; font-weight: 800; line-height: 1; color: #ffffff;
      font-variant-numeric: tabular-nums;
  }
  .icu-chip {
      display: inline-block; padding: 0.25rem 0.7rem; border-radius: 4px;
      font-weight: 700; font-size: 0.82rem; letter-spacing: 0.06em;
  }
  .icu-escalation {
      font-size: 0.76rem; color: #c9d1d9; margin-top: 0.35rem; line-height: 1.4;
  }
  .icu-vital {
      font-size: 1.9rem; font-weight: 700; color: #e6edf3;
      font-variant-numeric: tabular-nums; white-space: nowrap;
      line-height: 1.1;
  }
  .icu-vital-label {
      font-size: 0.68rem; color: #8b949e; text-transform: uppercase;
      letter-spacing: 0.08em;
  }
  .icu-rejected {
      color: #ff7043; font-size: 1.05rem; font-weight: 700;
      white-space: nowrap;
  }
  .icu-status {
      display: inline-block; padding: 0.3rem 0.8rem; border-radius: 4px;
      font-weight: 700; font-size: 0.8rem; color: #fff;
  }
  .icu-cmp-row {
      display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.28rem;
  }
  .icu-cmp-label {
      flex: 0 0 8.5rem; font-size: 0.74rem; color: #c9d1d9; text-align: right;
  }
  .icu-cmp-track {
      flex: 1 1 auto; height: 0.72rem; background: #21262d; border-radius: 2px;
      overflow: hidden;
  }
  .icu-cmp-fill { display: block; height: 100%; }
  .icu-cmp-score {
      flex: 0 0 1.1rem; font-size: 0.78rem; font-weight: 700; color: #e6edf3;
      text-align: right; font-variant-numeric: tabular-nums;
  }
  .icu-badge {
      display: block; padding: 0.3rem 0.5rem; margin-bottom: 0.25rem;
      background: #161b22; border-left: 3px solid #58a6ff; color: #c9d1d9;
      font-size: 0.72rem;
  }
</style>
"""

ADVISORY_BANNER = (
    "<div class='icu-banner'>"
    "<b>CLINICAL DECISION SUPPORT — ADVISORY ONLY.</b> "
    "Independent clinician review is required before any clinical action. "
    "This display does not diagnose, treat, or direct therapy. "
    "FDA CDS Non-Device Exemption, 21 CFR §880.3780. "
    "<br><b>SYNTHETIC DEMONSTRATION DATA — NOT REAL PATIENT DATA.</b>"
    "</div>"
)


# ════════════════════════════════════════════════════════════════════════════
# Rendering helpers (Streamlit calls only below this line)
# ════════════════════════════════════════════════════════════════════════════


def _render_bed_card(state: BedState, is_stale: bool, age_s: float) -> None:
    bed = state.bed
    style = risk_style(state.risk_level)
    label = bed.bed_id if bed else "UNASSIGNED"
    vendor = bed.vendor if bed else "Unrecognised monitor / not in bed map"

    st.markdown(
        f"<div class='icu-card{' stale' if is_stale else ''}'>"
        f"<div class='icu-bed-id'>{label}</div>"
        f"<div class='icu-meta'>{state.patient_id} &nbsp;·&nbsp; {vendor}"
        f" &nbsp;·&nbsp; via <code>{state.source or '—'}</code>"
        f"{f' &nbsp;·&nbsp; <b>DATA {age_s:.0f}s OLD</b>' if is_stale else ''}"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    total_col, chip_col = st.columns([1, 2])
    with total_col:
        total_text = "—" if state.news2_total is None else str(state.news2_total)
        st.markdown(
            f"<div class='icu-vital-label'>NEWS2 TOTAL</div>"
            f"<div class='icu-total'>{total_text}</div>",
            unsafe_allow_html=True,
        )
    with chip_col:
        st.markdown(
            f"<span class='icu-chip' style='background:{style.background};"
            f"color:{style.foreground};'>{style.marker} &nbsp;{style.label}</span>"
            f"<div class='icu-escalation'>{style.escalation}</div>",
            unsafe_allow_html=True,
        )

    # Vitals row — large numerals, rejected artifacts marked explicitly.
    cols = st.columns(5)
    for col, component_id in zip(
        cols,
        ("heart_rate", "resp_rate", "spo2", "systolic_bp", "temperature"),
        strict=False,
    ):
        reading = state.vitals.get(component_id)
        with col:
            if reading is None:
                body = "<div class='icu-vital'>—</div>"
                caption = component_id.replace("_", " ").upper()
            elif reading.rejected:
                body = "<div class='icu-rejected'>REJECTED</div>"
                caption = f"{reading.label} · artifact"
            else:
                # Unit goes in the SMALL caption, never beside the numeral.
                # Rendering "121.4 mmHg" inside a narrow column wrapped it
                # across three lines ("121.4" / "mm" / "Hg"), which defeats
                # the whole point of a large across-the-room numeral. The
                # number now owns the big line on its own; nowrap stops any
                # residual wrap for 3-digit + decimal values.
                value_text = (
                    f"{reading.value:g}"
                    if reading.value is not None
                    else reading.display_text
                )
                body = f"<div class='icu-vital'>{value_text}</div>"
                caption = f"{reading.label} {reading.unit}".strip()
            st.markdown(
                f"<div class='icu-vital-label'>{caption}</div>{body}",
                unsafe_allow_html=True,
            )

    _render_components(state)
    _render_warnings(state)
    _render_trends(state)
    _render_bundle(state)


def _render_components(state: BedState) -> None:
    if not state.components:
        st.caption(
            "No NEWS2 component breakdown — the gateway did not produce a score "
            "for this message. See the artifact panel below."
        )
        return

    with st.expander("NEWS2 component breakdown — why the total is what it is", True):
        # Rendered as plain HTML bars, NOT a Plotly figure. Three beds x one
        # chart per rerun was a large share of the render cost that caused the
        # preemption described at REFRESH_SECONDS; these bars are static markup
        # with no JS payload, so the bed wall repaints well inside one cycle.
        rows = []
        for component_id, label in COMPONENT_ORDER:
            score = state.components.get(component_id, 0)
            # 3 is the maximum any single NEWS2 parameter can score, and a
            # parameter at 3 triggers the single-parameter escalation rule on
            # its own -- so it is coloured as severely as a HIGH total.
            colour = (
                "#b71c1c" if score >= 3
                else "#ef6c00" if score == 2
                else "#558b2f" if score == 1
                else "#30363d"
            )
            width = max(4, int(score / 3 * 100))
            rows.append(
                f"<div class='icu-cmp-row'>"
                f"<span class='icu-cmp-label'>{label}</span>"
                f"<span class='icu-cmp-track'>"
                f"<span class='icu-cmp-fill' style='width:{width}%;"
                f"background:{colour};'></span></span>"
                f"<span class='icu-cmp-score'>{score}</span>"
                f"</div>"
            )
        st.markdown("".join(rows), unsafe_allow_html=True)


def _render_warnings(state: BedState) -> None:
    if not state.warnings:
        return
    with st.expander(
        f"Artifact / pipeline warnings ({len(state.warnings)}) — alarm-fatigue mitigation"
    ):
        st.caption(
            "Readings the DSP pipeline excluded before scoring. Each of these "
            "is a false alarm that never reached a clinician."
        )
        for warning in state.warnings:
            st.markdown(f"- `{warning}`")


def _render_trends(state: BedState) -> None:
    series = st.session_state.trends.get(state.patient_id, {})
    if not series:
        return

    with st.expander("Trends — rolling 5 minutes"):
        figure = go.Figure()
        any_series = False
        for component_id in TREND_VITALS:
            points = list(series.get(component_id, []))
            if not points:
                continue
            any_series = True
            figure.add_trace(
                go.Scatter(
                    x=[p[0] for p in points],
                    y=[p[1] for p in points],
                    mode="lines",
                    name=component_id.replace("_", " ").upper(),
                )
            )
        if any_series:
            figure.update_layout(
                height=230,
                margin={"l": 0, "r": 10, "t": 6, "b": 6},
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font={"color": "#c9d1d9", "size": 11},
                legend={"orientation": "h", "y": -0.25},
            )
            st.plotly_chart(
                figure, width="stretch", key=f"tr-{state.patient_id}"
            )

        news2_points = list(series.get("news2_total", []))
        if news2_points:
            step = go.Figure(
                go.Scatter(
                    x=[p[0] for p in news2_points],
                    y=[p[1] for p in news2_points],
                    mode="lines",
                    line_shape="hv",
                    name="NEWS2 total",
                    line={"color": "#58a6ff", "width": 2},
                )
            )
            # RCP 2017 escalation thresholds, drawn so the climb is readable
            # against the clinical boundaries rather than in isolation.
            step.add_hline(
                y=5,
                line_dash="dash",
                line_color="#ef6c00",
                annotation_text="5 — urgent assessment",
                annotation_position="top left",
            )
            step.add_hline(
                y=7,
                line_dash="dash",
                line_color="#b71c1c",
                annotation_text="7 — emergency response",
                annotation_position="top left",
            )
            step.update_layout(
                height=220,
                margin={"l": 0, "r": 10, "t": 20, "b": 6},
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font={"color": "#c9d1d9", "size": 11},
                yaxis={"title": "NEWS2 total", "rangemode": "tozero"},
                showlegend=False,
            )
            st.plotly_chart(
                step, width="stretch", key=f"n2-{state.patient_id}"
            )


def _render_bundle(state: BedState) -> None:
    if not state.bundle:
        return
    with st.expander("View FHIR R4 Bundle"):
        st.caption(
            "The NEWS2 Observation carries SNOMED CT 1239842005 with seven "
            "component[] sub-scores — this is what an EMR ingests natively, "
            "with no custom mapping project."
        )
        st.code(json.dumps(state.bundle, indent=2), language="json")


def _render_scale_panel(state: BedState) -> None:
    st.markdown("---")
    st.subheader("SpO2 Scale 1 vs Scale 2 — what-if analysis")
    st.caption(
        "Both scores below are recomputed by the gateway's validated NEWS2 "
        "calculator via POST /api/v1/vitals — this is not a display "
        "transform. ISO 14971 HAZARD-SPO2-001: scale assignment is a "
        "clinician decision and must NEVER be inferred from SpO2 values. "
        "The MLLP path deliberately carries no scale field, so this "
        "comparison is issued over HTTP where the assignment is explicit."
    )

    if st.button("Run comparison on ICU-BED-02's current vitals", type="primary"):
        st.session_state.scale_comparison = run_scale_comparison(state)

    error = st.session_state.get("whatif_error")
    if error:
        st.error(f"Comparison failed: {error}")

    comparison: ScaleComparison | None = st.session_state.get("scale_comparison")
    if comparison is None:
        return

    left, middle, right = st.columns(3)
    for col, (title, total, risk, note) in zip(
        (left, middle),
        (
            (
                "Scale 2 (COPD — correct for this patient)",
                comparison.scale_2_total,
                comparison.scale_2_risk,
                "Target range 88–92% on supplemental O2",
            ),
            (
                "Scale 1 (default — wrong for this patient)",
                comparison.scale_1_total,
                comparison.scale_1_risk,
                "Target range ≥96%",
            ),
        ),
        strict=False,
    ):
        style = risk_style(risk)
        with col:
            st.markdown(f"**{title}**")
            st.markdown(
                f"<div class='icu-total'>{'—' if total is None else total}</div>"
                f"<span class='icu-chip' style='background:{style.background};"
                f"color:{style.foreground};'>{style.marker} &nbsp;{style.label}</span>"
                f"<div class='icu-escalation'>{note}</div>",
                unsafe_allow_html=True,
            )

    with right:
        difference = comparison.difference
        st.markdown("**Difference**")
        st.markdown(
            f"<div class='icu-total'>{'—' if difference is None else f'+{difference}'}</div>",
            unsafe_allow_html=True,
        )
        if comparison.crosses_risk_band:
            st.markdown(
                f"<div class='icu-escalation'>Crosses a risk band: "
                f"<b>{comparison.scale_2_risk} → {comparison.scale_1_risk}</b>. "
                f"Scoring this COPD patient on Scale 1 would raise a false "
                f"escalation.</div>",
                unsafe_allow_html=True,
            )


def _render_sidebar(health: dict[str, Any] | None, now: float) -> None:
    with st.sidebar:
        st.markdown("### Gateway")
        if health:
            st.success(f"{health.get('status', 'unknown').upper()}")
            st.caption(f"Version {health.get('version', '—')}")
            uptime = health.get("uptime_seconds")
            if uptime is not None:
                st.caption(f"Uptime {float(uptime):.0f}s")
            for name, component in (health.get("components") or {}).items():
                st.markdown(
                    f"<span class='icu-badge'>{name}: "
                    f"{component.get('status', '?')}</span>",
                    unsafe_allow_html=True,
                )
        else:
            st.error("UNREACHABLE")
            st.caption(f"GET {BASE_URL}/health failed")

        st.markdown("### API")
        st.markdown(
            f"- [Swagger UI]({BASE_URL}/docs)\n"
            f"- [ReDoc]({BASE_URL}/redoc)\n"
            f"- [OpenAPI JSON]({BASE_URL}/openapi.json)\n"
            f"- WebSocket: `{WS_URL}`\n"
            f"- MLLP: `{GATEWAY_HOST}:2575`"
        )

        st.markdown("### Client-observed throughput")
        rate = messages_per_minute(st.session_state.delta_times, now)
        st.metric("Frames / min (this client)", f"{rate:.1f}")
        last = st.session_state.last_delta_monotonic
        st.metric(
            "Age of last frame",
            "—" if last is None else f"{now - last:.1f}s",
        )

        latencies = st.session_state.get("http_latencies", [])
        if latencies:
            st.metric(
                "HTTP round-trip (what-if POSTs)",
                f"{sum(latencies) / len(latencies):.0f} ms",
            )
            st.caption(
                "Measured only on the what-if POSTs this dashboard issues. "
                "No per-MLLP-message latency is shown: X-Pipeline-Duration-Ms "
                "is an HTTP response header and is not present in the "
                "WebSocket delta, so any such figure would be fabricated."
            )
        else:
            st.caption(
                "Pipeline latency appears here after a what-if comparison. "
                "MLLP messages carry no latency header, so none is invented."
            )

        st.markdown("### Regulatory")
        for badge in (
            "IEC 62304 — Class B",
            "ISO 14971 — Risk-managed",
            "FDA CDS Non-Device Exemption",
            "Health Canada — Class II",
        ):
            st.markdown(
                f"<span class='icu-badge'>{badge}</span>", unsafe_allow_html=True
            )


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "beds": {},
        "trends": {},
        "delta_times": [],
        "last_delta_monotonic": None,
        "scale_comparison": None,
        "whatif_error": None,
        "http_latencies": [],
        "health": None,
        "health_checked_at": 0.0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "reader" not in st.session_state:
        reader = DeltaReader(WS_URL)
        reader.start()
        st.session_state.reader = reader


def _drain_frames() -> None:
    """Move every queued frame into session state. Never drops an arrival."""
    reader: DeltaReader = st.session_state.reader
    now = time.monotonic()
    while True:
        try:
            delta = reader.frames.get_nowait()
        except queue.Empty:
            break

        if delta.get("type") != "vitals.delta":
            continue

        patient_id = delta.get("patient_id")
        if is_whatif_patient(patient_id):
            # What-if traffic goes through the real endpoint and therefore
            # appears on the live channel too. It is hypothetical, so it must
            # never sit among the live beds.
            continue

        state = bed_state_from_delta(delta, now)
        st.session_state.beds[state.patient_id] = state
        append_trend(st.session_state.trends, state)
        st.session_state.last_delta_monotonic = now
        st.session_state.delta_times = (st.session_state.delta_times + [now])[-400:]


def main() -> None:
    st.set_page_config(
        page_title="ICU Edge Gateway — Clinical Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    _init_state()
    _drain_frames()

    now = time.monotonic()
    reader: DeltaReader = st.session_state.reader

    if now - st.session_state.health_checked_at > HEALTH_POLL_SECONDS:
        st.session_state.health = fetch_health()
        st.session_state.health_checked_at = now

    reconnect_in = (
        None if reader.reconnect_at is None else max(0.0, reader.reconnect_at - now)
    )
    status = connection_status(
        socket_connected=reader.connected.is_set(),
        last_delta_monotonic=st.session_state.last_delta_monotonic,
        now_monotonic=now,
        reconnect_in_seconds=reconnect_in,
    )

    st.markdown("## ICU Edge-to-FHIR Interoperability Gateway")
    st.markdown(ADVISORY_BANNER, unsafe_allow_html=True)
    st.markdown(
        f"<span class='icu-status' style='background:{status.colour};'>"
        f"{status.label}</span> &nbsp; <span style='color:#8b949e;font-size:0.8rem;'>"
        f"{status.detail}</span>",
        unsafe_allow_html=True,
    )

    _render_sidebar(st.session_state.health, now)

    if status.state == "AWAITING_FIRST_MESSAGE":
        st.info(status.detail)

    stale = status.state == "DISCONNECTED"
    known = [
        state for pid, state in st.session_state.beds.items() if state.bed is not None
    ]
    known.sort(key=lambda s: s.bed.bed_id if s.bed else "")
    unassigned = [s for s in st.session_state.beds.values() if s.bed is None]

    if known:
        st.markdown("### Bed wall")
        for row_start in range(0, len(known), 3):
            for col, state in zip(
                st.columns(3), known[row_start : row_start + 3], strict=False
            ):
                with col:
                    age = now - state.updated_monotonic
                    _render_bed_card(state, stale, age)

    if unassigned:
        st.markdown("### Unassigned — patient not in the bed map")
        st.caption(
            "An unrecognised patient appearing on the gateway is information, "
            "not noise: it may be a misconfigured monitor or a real patient on "
            "a demonstration unit. Never silently dropped."
        )
        for row_start in range(0, len(unassigned), 3):
            for col, state in zip(
                st.columns(3), unassigned[row_start : row_start + 3], strict=False
            ):
                with col:
                    age = now - state.updated_monotonic
                    _render_bed_card(state, stale, age)

    copd = next((s for s in known if s.bed is not None and s.bed.copd_scale_demo), None)
    if copd is not None:
        _render_scale_panel(copd)

    time.sleep(REFRESH_SECONDS)
    st.rerun()


if __name__ == "__main__":
    main()
