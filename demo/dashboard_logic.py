"""
Pure presentation logic for the ICU Edge Gateway clinical demonstration
dashboard. NO Streamlit, Plotly, or pandas import appears in this module.

WHY THIS MODULE IS SEPARATE FROM dashboard.py
Two reasons, both deliberate:

  1. TESTABILITY. Every function here is importable and callable without a
     Streamlit runtime and without Streamlit installed at all, so
     tests/unit/test_dashboard_logic.py runs inside the pinned production
     venv (venv311) alongside the rest of the suite. dashboard.py, which
     does import Streamlit, is never imported by a test.

  2. REGULATORY SCOPE. This whole directory sits OUTSIDE src/ on purpose.
     The Dockerfile does `COPY --chown=gateway:gateway src/ ./src/`, so
     anything under src/ ships inside the SaMD image and widens its
     regulatory scope (IEC 62304 Class B). Placing the demonstration
     dashboard here makes that exclusion STRUCTURAL — the COPY never sees
     it — rather than relying on a .dockerignore entry that a future edit
     could silently drop. .dockerignore still excludes demo/ as well, and
     .github/workflows/docker-verify.yml asserts the file is absent from
     the built image: three independent layers, because a demonstration
     tool inside a medical-device image is a scope defect, not a bug.

WHAT THIS MODULE DOES NOT DO
It computes NO clinical values. NEWS2 totals, component sub-scores and risk
levels are READ from what the gateway already produced and are never
recomputed, re-derived, or adjusted for display. The colour and escalation
tables below map an ALREADY-DECIDED NEWS2RiskLevel to pixels; they never
decide a risk level themselves.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# ── Constants mirrored from the gateway ─────────────────────────────────────
# SNOMED CT code of the NEWS2 Observation, from
# src/infrastructure/fhir/news2_builder.py. The dashboard locates the NEWS2
# Observation inside a Bundle by this code, exactly as
# infrastructure/streaming/fhir_bundle_utils.py does server-side.
NEWS2_SNOMED_CODE: str = "1239842005"

# The seven NEWS2 component identifiers, in the fixed order
# news2_builder.py::_build_components() emits them. Order matters: the
# component bar chart must read top-to-bottom the way a clinician reads a
# NEWS2 chart, not in dict-insertion order.
COMPONENT_ORDER: tuple[tuple[str, str], ...] = (
    ("resp_rate", "Respiratory rate"),
    ("spo2", "SpO2"),
    ("supplemental_o2", "Supplemental O2"),
    ("systolic_bp", "Systolic BP"),
    ("heart_rate", "Heart rate"),
    ("consciousness", "Consciousness"),
    ("temperature", "Temperature"),
)

# LOINC code -> (component_id, display label, unit) for the numeric vital
# Observations the bundle carries. Taken from news2_builder.py's component
# table and observation_builder.py's coding.
LOINC_TO_VITAL: dict[str, tuple[str, str, str]] = {
    "9279-1": ("resp_rate", "RR", "/min"),
    "59408-5": ("spo2", "SpO2", "%"),
    "2708-6": ("spo2", "SpO2", "%"),
    "8480-6": ("systolic_bp", "SBP", "mmHg"),
    # Diastolic BP is audit-only (not a NEWS2 parameter) but MUST appear
    # here: when it is out of bounds the gateway emits an Observation with
    # dataAbsentReason, and omitting the code would make that rejected
    # reading invisible instead of showing it as a caught artifact.
    "8462-4": ("diastolic_bp", "DBP", "mmHg"),
    "8867-4": ("heart_rate", "HR", "bpm"),
    "8310-5": ("temperature", "Temp", "°C"),
    "57834-7": ("supplemental_o2", "O2", ""),
    "3151-8": ("supplemental_o2", "O2", ""),
    # Consciousness: the gateway INGESTS OBX-3 76270-8 ("AVPU score") but
    # EMITS Observations coded 67775-7 ("Level of responsiveness") -- see
    # observation_builder.py. Both are accepted here because this table
    # reads gateway OUTPUT, and assuming the input code silently dropped
    # the consciousness reading.
    "67775-7": ("consciousness", "AVPU", ""),
    "76270-8": ("consciousness", "AVPU", ""),
}

# Vitals plotted on the rolling trend charts.
TREND_VITALS: tuple[str, ...] = ("heart_rate", "resp_rate", "spo2", "systolic_bp")


# ── Risk presentation ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class RiskStyle:
    """
    How one NEWS2RiskLevel is rendered.

    `greyscale_weight` exists because risk must NOT be encoded by hue alone:
    a red/amber/green-only scheme is unreadable to a colour-blind clinician
    and vanishes in a greyscale print or a projector with poor colour. The
    weights below are monotonically increasing luminance steps, so the five
    states remain distinguishable with all colour removed. `marker` adds a
    third, non-colour channel (shape/text).
    """

    level: str
    label: str
    background: str
    foreground: str
    escalation: str
    greyscale_weight: int
    marker: str


# RCP NEWS2 2017 §3 response thresholds. The escalation text is quoted from
# the clinical response table -- it is what makes the score actionable, and
# is the half of the product a nursing director actually buys.
#
# LOW_MEDIUM is deliberately given a visually distinct treatment from LOW:
# it is the "single parameter scored 3, total still < 5" case, which
# escalates to 1-hourly monitoring even though the total looks reassuring.
# Collapsing it into LOW would hide exactly the patient this rule exists to
# catch.
RISK_STYLES: dict[str, RiskStyle] = {
    "NORMAL": RiskStyle(
        level="NORMAL",
        label="NORMAL",
        background="#1b5e20",
        foreground="#ffffff",
        escalation="Routine — minimum 12-hourly observations",
        greyscale_weight=1,
        marker="●",
    ),
    "LOW": RiskStyle(
        level="LOW",
        label="LOW",
        background="#558b2f",
        foreground="#ffffff",
        escalation="Low — minimum 12-hourly observations",
        greyscale_weight=2,
        marker="●●",
    ),
    "LOW_MEDIUM": RiskStyle(
        level="LOW_MEDIUM",
        label="LOW-MEDIUM",
        background="#f9a825",
        foreground="#1a1a1a",
        escalation=(
            "Single parameter scored 3 — minimum 1-hourly observations, "
            "urgent review by ward-based clinician"
        ),
        greyscale_weight=3,
        marker="▲",
    ),
    "MEDIUM": RiskStyle(
        level="MEDIUM",
        label="MEDIUM",
        background="#ef6c00",
        foreground="#ffffff",
        escalation=(
            "Urgent review by ward-based clinician and escalation to acute team"
        ),
        greyscale_weight=4,
        marker="▲▲",
    ),
    "HIGH": RiskStyle(
        level="HIGH",
        label="HIGH",
        background="#b71c1c",
        foreground="#ffffff",
        escalation="Emergency assessment by critical-care team — continuous monitoring",
        greyscale_weight=5,
        marker="■■■",
    ),
}

UNKNOWN_RISK_STYLE: RiskStyle = RiskStyle(
    level="UNKNOWN",
    label="NO SCORE",
    background="#37474f",
    foreground="#eceff1",
    escalation="No NEWS2 score in this message — see warnings",
    greyscale_weight=0,
    marker="—",
)


def risk_style(risk_level: str | None) -> RiskStyle:
    """
    Map a NEWS2 risk level to its presentation.

    An unknown or absent level renders as an explicit "NO SCORE" state, never
    as green: a missing score must never be mistaken for a reassuring one.
    """
    if not risk_level:
        return UNKNOWN_RISK_STYLE
    return RISK_STYLES.get(risk_level.upper(), UNKNOWN_RISK_STYLE)


# ── Bed mapping ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BedInfo:
    bed_id: str
    patient_id: str
    vendor: str
    narrative: str
    copd_scale_demo: bool = False


BED_MAP: dict[str, BedInfo] = {
    "PT-DEMO-001": BedInfo(
        bed_id="ICU-BED-01",
        patient_id="PT-DEMO-001",
        vendor="Philips IntelliVue MX800",
        narrative="Stable post-operative",
    ),
    "PT-DEMO-002": BedInfo(
        bed_id="ICU-BED-02",
        patient_id="PT-DEMO-002",
        vendor="GE CARESCAPE B650",
        narrative="COPD — hypercapnic respiratory failure, on supplemental O2",
        copd_scale_demo=True,
    ),
    "PT-DEMO-003": BedInfo(
        bed_id="ICU-BED-03",
        patient_id="PT-DEMO-003",
        vendor="Draeger Infinity Delta",
        narrative="Progressive sepsis with deterioration",
    ),
}

# Patient ID used by the SpO2 what-if comparison panel. Its traffic goes
# through the same real endpoint as everything else and therefore appears on
# the live WebSocket too -- it is filtered out of the bed wall by
# is_whatif_patient() so a hypothetical never sits among the live beds.
WHATIF_PATIENT_ID: str = "PT-DEMO-002-WHATIF"


def is_whatif_patient(patient_id: str | None) -> bool:
    return bool(patient_id) and str(patient_id).endswith("-WHATIF")


def bed_for_patient(patient_id: str | None) -> BedInfo | None:
    """
    Resolve a patient to a configured bed, or None if unrecognised.

    None is NOT a signal to discard the delta -- callers must render
    unrecognised patients in an "Unassigned" area. An unexpected patient
    appearing on an ICU gateway is information (a misconfigured monitor, a
    real patient on a demo unit), not noise to be swallowed.
    """
    if not patient_id:
        return None
    return BED_MAP.get(patient_id)


# ── Bundle parsing ──────────────────────────────────────────────────────────


def find_news2_observation(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    """Locate the NEWS2 Observation in a Bundle by its SNOMED CT code."""
    if not isinstance(bundle, dict):
        return None
    for entry in bundle.get("entry", []) or []:
        resource = (entry or {}).get("resource", {}) or {}
        if resource.get("resourceType") != "Observation":
            continue
        codings = (resource.get("code", {}) or {}).get("coding", []) or []
        if any(c.get("code") == NEWS2_SNOMED_CODE for c in codings):
            return resource
    return None


def extract_components(bundle: dict[str, Any] | None) -> dict[str, int]:
    """
    Read the seven NEWS2 component sub-scores from the NEWS2 Observation.

    Returns {} when no NEWS2 Observation is present (incomplete vitals) --
    the caller renders "no score" rather than seven zeroes, since zeroes
    would read as "all parameters normal", the opposite of the truth.
    """
    observation = find_news2_observation(bundle)
    if observation is None:
        return {}

    scores: dict[str, int] = {}
    for component in observation.get("component", []) or []:
        value = component.get("valueInteger")
        if value is None:
            continue
        codings = (component.get("code", {}) or {}).get("coding", []) or []
        for component_id, _label in COMPONENT_ORDER:
            if component_id in scores:
                continue
            if _component_matches(component_id, codings):
                scores[component_id] = int(value)
                break
    return scores


# Accepted codes per NEWS2 component, mirroring
# news2_builder.py::_COMPONENT_CODES. BOTH the LOINC and the SNOMED CT code
# are listed for each: every component[] entry carries both codings, and
# matching on either makes extraction robust to one of them changing.
#
# Note "consciousness": the component is coded LOINC 67775-7 ("Level of
# responsiveness") on OUTPUT, which is NOT the 76270-8 ("AVPU score") code
# accepted on INPUT. Assuming the input code here silently dropped the
# seventh component and produced a six-component breakdown that still summed
# correctly -- caught only because a test compared the component count
# against a real captured Bundle.
_COMPONENT_CODES: dict[str, frozenset[str]] = {
    "resp_rate": frozenset({"9279-1", "86290005"}),
    "spo2": frozenset({"59408-5", "431314004"}),
    "supplemental_o2": frozenset({"57834-7", "371825009"}),
    "systolic_bp": frozenset({"8480-6", "271649006"}),
    "heart_rate": frozenset({"8867-4", "364075005"}),
    "consciousness": frozenset({"67775-7", "76270-8", "248234008"}),
    "temperature": frozenset({"8310-5", "276885007"}),
}


def _component_matches(component_id: str, codings: list[dict[str, Any]]) -> bool:
    accepted = _COMPONENT_CODES.get(component_id, frozenset())
    return any(str(c.get("code")) in accepted for c in codings)


def extract_warnings(bundle: dict[str, Any] | None) -> list[str]:
    """
    Read pipeline warnings from Bundle.note.

    bundle_assembler.py sets note only when the pipeline produced warnings,
    so its absence means "no warnings", not "warnings unavailable".
    """
    if not isinstance(bundle, dict):
        return []
    return [
        note.get("text", "")
        for note in bundle.get("note", []) or []
        if isinstance(note, dict) and note.get("text")
    ]


@dataclass(frozen=True)
class VitalReading:
    """
    One vital-sign Observation as the dashboard displays it.

    `rejected` is the important field: an Observation carrying
    dataAbsentReason "out-of-range" means the DSP pipeline EXCLUDED that
    reading from scoring (observation_builder.py). It must render as an
    explicit rejected-artifact marker, never as a blank -- a blank looks
    like a missing sensor, while the truth is that the gateway caught a bad
    reading and prevented a false alarm. That distinction is the entire
    alarm-fatigue argument.
    """

    component_id: str
    label: str
    value: float | None
    unit: str
    rejected: bool
    display_text: str


def extract_vitals(bundle: dict[str, Any] | None) -> dict[str, VitalReading]:
    """Read the numeric/coded vital-sign Observations out of a Bundle."""
    if not isinstance(bundle, dict):
        return {}

    readings: dict[str, VitalReading] = {}
    for entry in bundle.get("entry", []) or []:
        resource = (entry or {}).get("resource", {}) or {}
        if resource.get("resourceType") != "Observation":
            continue

        codings = (resource.get("code", {}) or {}).get("coding", []) or []
        if any(c.get("code") == NEWS2_SNOMED_CODE for c in codings):
            continue  # the NEWS2 Observation itself, not a vital sign

        matched: tuple[str, str, str] | None = None
        for coding in codings:
            candidate = LOINC_TO_VITAL.get(str(coding.get("code")))
            if candidate is not None:
                matched = candidate
                break
        if matched is None:
            continue

        component_id, label, unit = matched
        rejected = "dataAbsentReason" in resource
        value = _observation_value(resource)
        readings[component_id] = VitalReading(
            component_id=component_id,
            label=label,
            value=value,
            unit=unit,
            rejected=rejected,
            display_text=_format_reading(resource, value, unit, rejected),
        )
    return readings


def _observation_value(resource: dict[str, Any]) -> float | None:
    quantity = resource.get("valueQuantity")
    if isinstance(quantity, dict) and quantity.get("value") is not None:
        try:
            return float(quantity["value"])
        except (TypeError, ValueError):
            return None
    return None


def _format_reading(
    resource: dict[str, Any],
    value: float | None,
    unit: str,
    rejected: bool,
) -> str:
    if rejected:
        return "REJECTED"
    if value is not None:
        text = f"{value:g}"
        return f"{text} {unit}".strip()

    # Coded (non-numeric) observations: AVPU arrives as valueCodeableConcept,
    # supplemental O2 as valueBoolean.
    coded = resource.get("valueCodeableConcept")
    if isinstance(coded, dict):
        codings = coded.get("coding", []) or []
        if codings:
            return str(codings[0].get("display") or codings[0].get("code") or "—")
        if coded.get("text"):
            return str(coded["text"])
    boolean = resource.get("valueBoolean")
    if boolean is not None:
        return "On O2" if boolean else "Room air"
    return "—"


# ── Delta -> bed state ──────────────────────────────────────────────────────


@dataclass
class BedState:
    """Everything the dashboard knows about one bed, accumulated from deltas."""

    patient_id: str
    bed: BedInfo | None
    source: str = ""
    received_at: str = ""
    news2_total: int | None = None
    risk_level: str | None = None
    components: dict[str, int] = field(default_factory=dict)
    vitals: dict[str, VitalReading] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    bundle: dict[str, Any] = field(default_factory=dict)
    updated_monotonic: float = 0.0


def bed_state_from_delta(delta: dict[str, Any], now_monotonic: float) -> BedState:
    """
    Build a BedState from one `vitals.delta` frame.

    Tolerant of every optional field the real frame may omit: news2 is null
    when the pipeline could not produce a score, and note is absent when
    there were no warnings. Neither is an error.
    """
    news2 = delta.get("news2") or {}
    bundle = delta.get("bundle") or {}
    patient_id = str(delta.get("patient_id") or "UNKNOWN")

    total = news2.get("total")
    return BedState(
        patient_id=patient_id,
        bed=bed_for_patient(patient_id),
        source=str(delta.get("source") or ""),
        received_at=str(delta.get("received_at") or ""),
        news2_total=int(total) if isinstance(total, (int | float)) else None,
        risk_level=news2.get("risk_level"),
        components=extract_components(bundle),
        vitals=extract_vitals(bundle),
        warnings=extract_warnings(bundle),
        bundle=bundle,
        updated_monotonic=now_monotonic,
    )


# ── Trend accumulation ──────────────────────────────────────────────────────

# ~5 minutes of history. At the streamer's default 2 s interval that is 150
# points; the default is generous so a slower interval still covers 5 min.
TREND_MAXLEN: int = 300


def new_trend_store() -> dict[str, dict[str, deque]]:
    """Fresh per-patient, per-vital bounded history."""
    return {}


def append_trend(
    store: dict[str, dict[str, deque]],
    state: BedState,
    timestamp: datetime | None = None,
) -> None:
    """
    Append this bed's current readings to its rolling history.

    Bounded per series by TREND_MAXLEN. This is the dashboard's OWN history:
    it must never read StoreAndForwardRingBuffer, whose drain() is
    destructive and would consume telemetry the MQTT forwarder still needs.
    """
    timestamp = timestamp or datetime.now(tz=timezone.utc)
    series = store.setdefault(state.patient_id, {})

    for component_id in TREND_VITALS:
        reading = state.vitals.get(component_id)
        if reading is None or reading.value is None or reading.rejected:
            continue
        series.setdefault(component_id, deque(maxlen=TREND_MAXLEN)).append(
            (timestamp, reading.value)
        )

    if state.news2_total is not None:
        series.setdefault("news2_total", deque(maxlen=TREND_MAXLEN)).append(
            (timestamp, float(state.news2_total))
        )


# ── Connection state ────────────────────────────────────────────────────────

ConnectionState = Literal["AWAITING_FIRST_MESSAGE", "LIVE", "DISCONNECTED"]

# A delta older than this means the feed is stale even if the socket looks
# open. Sized well above the streamer's default 2 s interval so ordinary
# jitter never flickers the badge.
STALE_AFTER_SECONDS: float = 12.0


@dataclass(frozen=True)
class ConnectionStatus:
    state: ConnectionState
    label: str
    detail: str
    colour: str
    is_error: bool


def connection_status(
    *,
    socket_connected: bool,
    last_delta_monotonic: float | None,
    now_monotonic: float,
    reconnect_in_seconds: float | None = None,
    stale_after: float = STALE_AFTER_SECONDS,
) -> ConnectionStatus:
    """
    Classify the live feed into exactly three states.

    AWAITING_FIRST_MESSAGE is explicitly NOT an error. WS /api/v1/live/vitals
    is push-only and sends no snapshot frame on connect (by design -- see
    live_dashboard_channel.py), so a freshly-connected dashboard legitimately
    has nothing to show until the next message is ingested. Rendering that as
    a failure would train a presenter to distrust a correctly working system.
    """
    if socket_connected and last_delta_monotonic is None:
        return ConnectionStatus(
            state="AWAITING_FIRST_MESSAGE",
            label="AWAITING FIRST MESSAGE",
            detail=(
                "Connected to the live channel. This stream is push-only and "
                "sends no snapshot on connect by design, so beds appear as "
                "soon as the next message is ingested — usually within a few "
                "seconds."
            ),
            colour="#546e7a",
            is_error=False,
        )

    age = (
        None
        if last_delta_monotonic is None
        else max(0.0, now_monotonic - last_delta_monotonic)
    )

    if socket_connected and age is not None and age <= stale_after:
        return ConnectionStatus(
            state="LIVE",
            label="LIVE",
            detail=f"Last update {age:.1f}s ago",
            colour="#2e7d32",
            is_error=False,
        )

    if age is None:
        detail = "No data has been received. Reconnecting…"
    else:
        detail = (
            f"Last good data {age:.0f}s ago — shown dimmed and stamped with its age"
        )
    if reconnect_in_seconds is not None:
        detail += f" · retrying in {reconnect_in_seconds:.0f}s"

    return ConnectionStatus(
        state="DISCONNECTED",
        label="DISCONNECTED",
        detail=detail,
        colour="#c62828",
        is_error=True,
    )


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential reconnect backoff, capped."""
    return min(cap * 1.0, base * (2 ** max(0, attempt - 1)))


def messages_per_minute(
    delta_monotonic_times: list[float], now_monotonic: float, window: float = 60.0
) -> float:
    """
    Client-side throughput over a trailing window.

    Measured from frames this dashboard actually received -- it is a client
    observation, never presented as a gateway-side metric.
    """
    if not delta_monotonic_times:
        return 0.0
    cutoff = now_monotonic - window
    recent = [t for t in delta_monotonic_times if t >= cutoff]
    if not recent:
        return 0.0
    elapsed = max(1e-6, now_monotonic - min(recent))
    return len(recent) * 60.0 / max(elapsed, 1.0)


# ── SpO2 what-if comparison ─────────────────────────────────────────────────

# UCUM units the /api/v1/vitals payload expects per vital type, mirroring
# domain/entities/vital_sign.py::VitalSignUnit.
_WHATIF_UNITS: dict[str, tuple[str, str]] = {
    "resp_rate": ("RESPIRATORY_RATE", "breaths/min"),
    "spo2": ("SPO2", "%"),
    "systolic_bp": ("SYSTOLIC_BP", "mmHg"),
    "heart_rate": ("HEART_RATE", "bpm"),
    "temperature": ("TEMPERATURE_CELSIUS", "Cel"),
}


def build_whatif_payload(
    state: BedState,
    spo2_scale: str,
    *,
    patient_id: str = WHATIF_PATIENT_ID,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """
    Build a POST /api/v1/vitals body from a bed's current in-bounds readings.

    Only in-bounds numeric readings are included: a rejected artifact must
    not be smuggled into a what-if comparison, or the comparison would be
    scoring data the pipeline already refused.

    Both scales are sent to the REAL endpoint and scored by the REAL
    validated NEWS2Calculator. This function performs no scoring itself --
    it only reshapes readings the gateway already returned.
    """
    moment = (
        (timestamp or datetime.now(tz=timezone.utc)).isoformat().replace("+00:00", "Z")
    )
    samples: list[dict[str, Any]] = []

    for component_id, (vital_type, unit) in _WHATIF_UNITS.items():
        reading = state.vitals.get(component_id)
        if reading is None or reading.value is None or reading.rejected:
            continue
        samples.append(
            {
                "vital_sign_type": vital_type,
                "value": reading.value,
                "unit": unit,
                "timestamp": moment,
            }
        )

    o2_reading = state.vitals.get("supplemental_o2")
    if o2_reading is not None and not o2_reading.rejected:
        on_o2 = o2_reading.display_text.strip().lower() == "on o2"
        samples.append(
            {
                "vital_sign_type": "SUPPLEMENTAL_O2",
                "value": 1.0 if on_o2 else 0.0,
                "unit": "bool",
                "timestamp": moment,
            }
        )

    return {
        "patient_id": patient_id,
        "spo2_scale": spo2_scale,
        "samples": samples,
    }


def read_news2_headers(headers: dict[str, str]) -> tuple[int | None, str | None]:
    """
    Read X-NEWS2-Total / X-NEWS2-Risk-Level case-INSENSITIVELY.

    uvicorn emits response header names in lower case, so a case-sensitive
    lookup for the documented "X-NEWS2-Total" spelling silently misses every
    time. Normalising here rather than at each call site keeps that trap in
    one place.
    """
    normalised = {str(k).lower(): v for k, v in (headers or {}).items()}
    raw_total = normalised.get("x-news2-total")
    total: int | None
    try:
        total = int(raw_total) if raw_total is not None else None
    except (TypeError, ValueError):
        total = None
    return total, normalised.get("x-news2-risk-level")


@dataclass(frozen=True)
class ScaleComparison:
    """Result of scoring identical vitals under both SpO2 scales."""

    scale_1_total: int | None
    scale_1_risk: str | None
    scale_2_total: int | None
    scale_2_risk: str | None

    @property
    def difference(self) -> int | None:
        if self.scale_1_total is None or self.scale_2_total is None:
            return None
        return self.scale_1_total - self.scale_2_total

    @property
    def crosses_risk_band(self) -> bool:
        return (
            self.scale_1_risk is not None
            and self.scale_2_risk is not None
            and self.scale_1_risk != self.scale_2_risk
        )
