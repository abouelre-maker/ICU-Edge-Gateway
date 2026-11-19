"""
N-01 — values that fall between integer (or 0.1 °C) NEWS2 bands.

Interim rule (decided by Housam, unsigned PROPOSAL; final policy HD-E8): assign
the MORE SEVERE adjacent band and attach BETWEEN_BANDS_VALUE. The RCP 2017
band boundaries are unchanged — the neighbours are scored by NEWS2Calculator's
own band functions.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.score_outcome import ReasonCode, ScoreOutcome
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.vitals_orchestrator import VitalsOrchestrator

_T = VitalSignType
_U = VitalSignUnit


def _seven(on_o2: bool = False, **overrides: float) -> list[VitalSignSample]:
    ts = datetime.now(tz=timezone.utc)
    values = {
        _T.RESPIRATORY_RATE: (16.0, _U.BREATHS_PER_MIN),
        _T.SPO2: (97.0, _U.PERCENT),
        _T.SYSTOLIC_BP: (120.0, _U.MMHG),
        _T.HEART_RATE: (75.0, _U.BPM),
        _T.TEMPERATURE_CELSIUS: (37.0, _U.CELSIUS),
        _T.SUPPLEMENTAL_O2: (1.0 if on_o2 else 0.0, _U.BOOLEAN),
    }
    for name, v in overrides.items():
        values[_T[name]] = (v, values[_T[name]][1])
    out = [
        VitalSignSample(vital_sign_type=t, value=v, unit=u, timestamp=ts)
        for t, (v, u) in values.items()
    ]
    out.append(
        VitalSignSample(
            vital_sign_type=_T.CONSCIOUSNESS, value=0.0, unit=_U.AVPU_SCALE,
            timestamp=ts, avpu_level=AVPULevel.ALERT,
        )
    )
    return out


@pytest.mark.parametrize(
    ("param", "value", "component", "expected"),
    [
        ("RESPIRATORY_RATE", 8.5, "resp_rate_score", 3),   # 8 → 3 vs 9 → 1
        ("RESPIRATORY_RATE", 20.5, "resp_rate_score", 2),  # 20 → 0 vs 21 → 2
        ("HEART_RATE", 40.5, "heart_rate_score", 3),       # 40 → 3 vs 41 → 1
        ("HEART_RATE", 90.5, "heart_rate_score", 1),       # 90 → 0 vs 91 → 1
        ("SYSTOLIC_BP", 90.5, "systolic_bp_score", 3),     # 90 → 3 vs 91 → 2
        ("SPO2", 91.5, "spo2_score", 3),                   # 91 → 3 vs 92 → 2
        ("TEMPERATURE_CELSIUS", 35.05, "temperature_score", 3),  # 35.0 → 3 vs 35.1 → 1
        ("TEMPERATURE_CELSIUS", 38.05, "temperature_score", 1),  # 38.0 → 0 vs 38.1 → 1
    ],
)
def test_between_band_value_takes_more_severe_band(
    param: str, value: float, component: str, expected: int
) -> None:
    r = VitalsOrchestrator().analyse(
        _seven(**{param: value}), PatientContext(patient_id="PT-N01")
    )
    assert r.assessment.outcome is ScoreOutcome.SCORED
    assert r.news2_score is not None
    assert getattr(r.news2_score, component) == expected
    bb = [f for f in r.assessment.findings if f.code is ReasonCode.BETWEEN_BANDS_VALUE]
    assert len(bb) == 1 and bb[0].parameter is _T[param] and bb[0].measured_value == value


def test_scale2_on_oxygen_uses_scale_aware_neighbours() -> None:
    # Scale 2: 92 → 0, 93 on O2 → 1  ⇒ 92.5 takes 1
    r = VitalsOrchestrator().analyse(
        _seven(on_o2=True, SPO2=92.5),
        PatientContext(patient_id="PT-N01", spo2_scale=SpO2Scale.SCALE_2),
    )
    assert r.news2_score is not None and r.news2_score.spo2_score == 1
    assert ReasonCode.BETWEEN_BANDS_VALUE.value in r.assessment.reason_codes


@pytest.mark.parametrize(
    ("param", "value"),
    [("RESPIRATORY_RATE", 15.5), ("HEART_RATE", 72.5), ("TEMPERATURE_CELSIUS", 37.25)],
)
def test_fraction_inside_one_band_is_not_flagged(param: str, value: float) -> None:
    r = VitalsOrchestrator().analyse(
        _seven(**{param: value}), PatientContext(patient_id="PT-N01")
    )
    assert r.assessment.outcome is ScoreOutcome.SCORED
    assert ReasonCode.BETWEEN_BANDS_VALUE.value not in r.assessment.reason_codes


def test_measured_value_itself_is_not_altered() -> None:
    r = VitalsOrchestrator().analyse(
        _seven(RESPIRATORY_RATE=8.5), PatientContext(patient_id="PT-N01")
    )
    rr = [p for p in r.processed_vitals if p.original.vital_sign_type is _T.RESPIRATORY_RATE]
    assert rr[0].cleaned_value == 8.5  # FHIR output keeps the measured value
