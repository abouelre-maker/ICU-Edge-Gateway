"""
ScoringGate — decides whether a NEWS2 score may be computed, and from what.

Runs between VitalSignProcessor (DSP) and NEWS2Calculator. It never changes
the RCP 2017 band tables (R6): NEWS2Calculator is untouched and remains the
only place a score is computed. The gate only decides *what reaches* the
calculator and records every reason in machine-readable form.

A6 (docs/assessment/PHASE1_DESIGN.md §3, decision Q2): a finite, physically
possible value outside PhysiologicalBoundsChecker's plausibility bounds is
CRITICAL, not an artifact. It is passed to the calculator (so a downstream
consumer that reads only the number sees a high score, never "no score") and
flagged CRITICAL_VALUE_REVIEW_REQUIRED with the measured value preserved.
Only physically impossible data stays an artifact. No bound value changes.

A2 (decisions Q1(b), Q3): every NEWS2 input must be fresh. Per-parameter
staleness windows are mandatory configuration with NO default anywhere in
src/ — they are clinical values owned by a clinical safety reviewer (HD-E7).
With any window unset the gate withholds the score (STALENESS_POLICY_UNSET)
and the service refuses to start (config.validate_news2_scoring_config).
The future-timestamp tolerance is a clock-skew engineering parameter:
default 60 s, configurable.

Design note: the policy is read from the environment *per call* by default,
inside the domain. That is a deliberate exception to "no I/O in the domain":
it guarantees no construction path (a test, a new endpoint, a forgotten
wiring) can ever score without the staleness check.
"""

from __future__ import annotations

import dataclasses
import math
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import ClassVar

from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.score_outcome import (
    Finding,
    ReasonCode,
    ScoringAssessment,
    resolve_outcome,
)
from domain.entities.vital_sign import VitalSignType
from domain.services.news2_calculator import NEWS2Calculator
from domain.services.signal_processor import ProcessedVitalSign

# The five numeric NEWS2 inputs (same set as news2_calculator._REQUIRED_VITAL_TYPES).
_NUMERIC_REQUIRED: tuple[VitalSignType, ...] = (
    VitalSignType.RESPIRATORY_RATE,
    VitalSignType.SPO2,
    VitalSignType.SYSTOLIC_BP,
    VitalSignType.HEART_RATE,
    VitalSignType.TEMPERATURE_CELSIUS,
)


def is_physically_impossible(vital_type: VitalSignType, value: float) -> bool:
    """
    True only for data that cannot be a real measurement. This is a definition
    of impossibility, not a clinical threshold: NaN/Inf, negative magnitudes,
    saturation above 100 %, or an O2 flag that is neither 0 nor 1.
    """
    if not math.isfinite(value) or value < 0:
        return True
    if vital_type is VitalSignType.SPO2 and value > 100.0:
        return True
    return vital_type is VitalSignType.SUPPLEMENTAL_O2 and value not in (0.0, 1.0)


# N-01: recording resolution of each banded input (RCP 2017 bands are integer,
# temperature is 0.1 °C). A value between two grid points whose neighbours
# score differently is "between bands"; the interim rule (HD-E8) takes the
# more severe neighbour. Neighbours are scored by NEWS2Calculator's own band
# functions, so the RCP boundaries are never restated or changed here (R6).
_GRID_FACTOR: dict[VitalSignType, int] = {
    VitalSignType.RESPIRATORY_RATE: 1,
    VitalSignType.SPO2: 1,
    VitalSignType.SYSTOLIC_BP: 1,
    VitalSignType.HEART_RATE: 1,
    VitalSignType.TEMPERATURE_CELSIUS: 10,
}


def _band_score(vt: VitalSignType, v: float, scale: SpO2Scale, on_o2: bool) -> int:
    c = NEWS2Calculator
    if vt is VitalSignType.RESPIRATORY_RATE:
        return c._score_respiratory_rate(v)
    if vt is VitalSignType.SPO2:
        return c._score_spo2(v, scale, on_o2)
    if vt is VitalSignType.SYSTOLIC_BP:
        return c._score_systolic_bp(v)
    if vt is VitalSignType.HEART_RATE:
        return c._score_heart_rate(v)
    return c._score_temperature(v)


def _more_severe_neighbour(
    vt: VitalSignType, v: float, scale: SpO2Scale, on_o2: bool
) -> float | None:
    """Return the more severe grid neighbour if v lies between two bands, else None."""
    factor = _GRID_FACTOR[vt]
    x = round(v * factor, 9)
    lo, hi = math.floor(x), math.ceil(x)
    if lo == hi:
        return None
    lo_v, hi_v = lo / factor, hi / factor
    s_lo = _band_score(vt, lo_v, scale, on_o2)
    s_hi = _band_score(vt, hi_v, scale, on_o2)
    if s_lo == s_hi:
        return None
    return lo_v if s_lo > s_hi else hi_v


WINDOW_ENV_TEMPLATE = "NEWS2_STALENESS_WINDOW_{name}_SECONDS"
TOLERANCE_ENV = "FUTURE_TIMESTAMP_TOLERANCE_SECONDS"
_DEFAULT_FUTURE_TOLERANCE = timedelta(seconds=60)  # Q3: engineering, not clinical


@dataclass(frozen=True)
class ScoringPolicy:
    REQUIRED_TYPES: ClassVar[tuple[VitalSignType, ...]] = (
        VitalSignType.RESPIRATORY_RATE,
        VitalSignType.SPO2,
        VitalSignType.SUPPLEMENTAL_O2,
        VitalSignType.SYSTOLIC_BP,
        VitalSignType.HEART_RATE,
        VitalSignType.CONSCIOUSNESS,
        VitalSignType.TEMPERATURE_CELSIUS,
    )

    staleness_windows: Mapping[VitalSignType, timedelta]
    future_tolerance: timedelta = _DEFAULT_FUTURE_TOLERANCE


def window_env_names() -> list[str]:
    return [WINDOW_ENV_TEMPLATE.format(name=t.name) for t in ScoringPolicy.REQUIRED_TYPES]


def _positive_seconds(name: str, raw: str) -> timedelta:
    try:
        seconds = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number of seconds. Got {raw!r}.") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{name} must be a positive number of seconds. Got {raw!r}.")
    return timedelta(seconds=seconds)


def policy_from_environment() -> ScoringPolicy | None:
    """
    Build the policy from NEWS2_STALENESS_WINDOW_<TYPE>_SECONDS (all seven
    required) and FUTURE_TIMESTAMP_TOLERANCE_SECONDS (default 60).
    Returns None if any window is unset; raises ValueError if any is invalid.
    """
    windows: dict[VitalSignType, timedelta] = {}
    for vt, name in zip(ScoringPolicy.REQUIRED_TYPES, window_env_names(), strict=True):
        raw = os.environ.get(name, "").strip()
        if not raw:
            return None
        windows[vt] = _positive_seconds(name, raw)
    raw_tol = os.environ.get(TOLERANCE_ENV, "").strip()
    tolerance = (
        _positive_seconds(TOLERANCE_ENV, raw_tol) if raw_tol else _DEFAULT_FUTURE_TOLERANCE
    )
    return ScoringPolicy(staleness_windows=windows, future_tolerance=tolerance)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class GateResult:
    assessment: ScoringAssessment
    # What the calculator may see: critical values re-admitted, artifacts not.
    scoring_inputs: tuple[ProcessedVitalSign, ...]


class ScoringGate:
    def __init__(
        self,
        policy_provider: Callable[[], ScoringPolicy | None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy_provider = policy_provider or policy_from_environment
        self._clock = clock or _utc_now

    def assess(
        self,
        processed: Sequence[ProcessedVitalSign],
        context: PatientContext,
        upstream_findings: Sequence[Finding] = (),
    ) -> GateResult:
        findings: list[Finding] = list(upstream_findings)
        inputs: list[ProcessedVitalSign] = []

        for pv in processed:
            sample = pv.original
            # Waveform samples carry a 0.0 placeholder scalar by design
            # (hl7v2_adapter._build_waveform_sample); they are never scalar
            # readings and are classified neither critical nor artifact.
            if pv.is_within_physiological_bounds or sample.waveform is not None:
                inputs.append(pv)
                continue
            if is_physically_impossible(sample.vital_sign_type, sample.value):
                findings.append(
                    Finding(
                        ReasonCode.ARTIFACT_EXCLUDED,
                        sample.vital_sign_type,
                        "Physically impossible value excluded as artifact.",
                        None if math.isnan(sample.value) else sample.value,
                    )
                )
                inputs.append(pv)  # stays out-of-bounds: calculator ignores it
                continue
            findings.append(
                Finding(
                    ReasonCode.CRITICAL_VALUE_REVIEW_REQUIRED,
                    sample.vital_sign_type,
                    "Value outside plausibility bounds but physically possible: "
                    "scored per RCP 2017 tables; review required.",
                    sample.value,
                )
            )
            inputs.append(dataclasses.replace(pv, is_within_physiological_bounds=True))

        # N-01: between-band values → more severe neighbour (scoring input
        # only; the measured value in processed_vitals / FHIR is unchanged).
        o2_inputs = [
            pv
            for pv in inputs
            if pv.original.vital_sign_type is VitalSignType.SUPPLEMENTAL_O2
            and pv.is_within_physiological_bounds
        ]
        on_o2 = (
            max(o2_inputs, key=lambda pv: pv.original.timestamp).cleaned_value >= 0.5
            if o2_inputs
            else False
        )
        for i, pv in enumerate(inputs):
            vt = pv.original.vital_sign_type
            if (
                vt not in _GRID_FACTOR
                or not pv.is_within_physiological_bounds
                or pv.original.waveform is not None
                or not math.isfinite(pv.cleaned_value)
            ):
                continue
            snapped = _more_severe_neighbour(vt, pv.cleaned_value, context.spo2_scale, on_o2)
            if snapped is None:
                continue
            findings.append(
                Finding(
                    ReasonCode.BETWEEN_BANDS_VALUE,
                    vt,
                    "Value lies between two NEWS2 bands; scored in the more severe "
                    f"adjacent band (as {snapped:g}). Interim rule, HD-E8.",
                    pv.cleaned_value,
                )
            )
            inputs[i] = dataclasses.replace(pv, cleaned_value=snapped)

        admitted = {
            pv.original.vital_sign_type
            for pv in inputs
            if pv.is_within_physiological_bounds and pv.original.waveform is None
        }
        for vt in _NUMERIC_REQUIRED:
            if vt not in admitted:
                findings.append(
                    Finding(
                        ReasonCode.MISSING_PARAMETER,
                        vt,
                        "Required NEWS2 input absent or excluded.",
                    )
                )

        # A1: consciousness and O2 status are mandatory NEWS2 inputs. Their
        # absence must never default to Alert / room air (a false NORMAL).
        if not any(
            pv.original.vital_sign_type is VitalSignType.CONSCIOUSNESS
            and pv.original.avpu_level is not None
            for pv in inputs
        ):
            findings.append(
                Finding(
                    ReasonCode.MISSING_CONSCIOUSNESS,
                    VitalSignType.CONSCIOUSNESS,
                    "No level-of-consciousness (ACVPU) observation; not assumed Alert.",
                )
            )
        if VitalSignType.SUPPLEMENTAL_O2 not in admitted:
            findings.append(
                Finding(
                    ReasonCode.MISSING_O2_STATUS,
                    VitalSignType.SUPPLEMENTAL_O2,
                    "No air/supplemental-oxygen observation; not assumed room air.",
                )
            )

        # A2: freshness of the most recent admitted sample of each input.
        policy = self._policy_provider()
        if policy is None:
            findings.append(
                Finding(
                    ReasonCode.STALENESS_POLICY_UNSET,
                    None,
                    "Staleness windows are not configured (HD-E7); no score.",
                )
            )
        else:
            now = self._clock()
            for vt in ScoringPolicy.REQUIRED_TYPES:
                candidates = [
                    pv.original
                    for pv in inputs
                    if pv.original.vital_sign_type is vt
                    and pv.is_within_physiological_bounds
                    and pv.original.waveform is None
                    and (vt is not VitalSignType.CONSCIOUSNESS or pv.original.avpu_level)
                ]
                if not candidates:
                    continue  # already reported as missing
                latest = max(candidates, key=lambda s: s.timestamp)
                if latest.timestamp - now > policy.future_tolerance:
                    findings.append(
                        Finding(
                            ReasonCode.FUTURE_TIMESTAMP,
                            vt,
                            "Observation time is in the future beyond the "
                            f"{policy.future_tolerance.total_seconds():g} s tolerance.",
                        )
                    )
                elif now - latest.timestamp > policy.staleness_windows[vt]:
                    findings.append(
                        Finding(
                            ReasonCode.STALE_OBSERVATION,
                            vt,
                            "Most recent observation is older than the configured "
                            f"{policy.staleness_windows[vt].total_seconds():g} s window.",
                        )
                    )

        used = [
            pv.original.timestamp
            for pv in inputs
            if pv.is_within_physiological_bounds and pv.original.waveform is None
        ]
        frozen = tuple(findings)
        return GateResult(
            assessment=ScoringAssessment(
                outcome=resolve_outcome(frozen),
                findings=frozen,
                observation_time=max(used) if used else None,
            ),
            scoring_inputs=tuple(inputs),
        )
