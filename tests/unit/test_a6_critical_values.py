"""
A6 — critical values must not be indistinguishable from sensor artifacts.

Decision (delegated 2026-09-29, pending clinical review; see
regulatory/findings/A6.md): a finite, physically possible value outside the
existing plausibility bounds is CRITICAL, not an artifact. NEWS2 is computed
normally from the unchanged RCP tables, the outcome is OUT_OF_RANGE_CRITICAL,
reason CRITICAL_VALUE_REVIEW_REQUIRED, and the measured value is preserved.
Only physically impossible data (NaN/Inf, negative, SpO2 > 100, O2 flag not
0/1) remains an artifact.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest
from domain.entities.patient_context import PatientContext
from domain.entities.score_outcome import ReasonCode, ScoreOutcome
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.vitals_orchestrator import VitalsOrchestrator
from httpx import AsyncClient

_T = VitalSignType
_U = VitalSignUnit


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _full_set(**overrides: float) -> list[VitalSignSample]:
    """All seven NEWS2 inputs, fresh timestamps, normal values unless overridden."""
    values = {
        _T.RESPIRATORY_RATE: 16.0,
        _T.SPO2: 97.0,
        _T.SYSTOLIC_BP: 120.0,
        _T.HEART_RATE: 75.0,
        _T.TEMPERATURE_CELSIUS: 37.0,
        _T.SUPPLEMENTAL_O2: 0.0,
    }
    for name, v in overrides.items():
        values[_T[name]] = v
    units = {
        _T.RESPIRATORY_RATE: _U.BREATHS_PER_MIN,
        _T.SPO2: _U.PERCENT,
        _T.SYSTOLIC_BP: _U.MMHG,
        _T.HEART_RATE: _U.BPM,
        _T.TEMPERATURE_CELSIUS: _U.CELSIUS,
        _T.SUPPLEMENTAL_O2: _U.BOOLEAN,
    }
    ts = _now()
    samples = [
        VitalSignSample(vital_sign_type=t, value=v, unit=units[t], timestamp=ts)
        for t, v in values.items()
    ]
    samples.append(
        VitalSignSample(
            vital_sign_type=_T.CONSCIOUSNESS,
            value=0.0,
            unit=_U.AVPU_SCALE,
            timestamp=ts,
            avpu_level=AVPULevel.ALERT,
        )
    )
    return samples


_CTX = PatientContext(patient_id="PT-A6")


class TestCriticalIsNotArtifact:
    @pytest.mark.parametrize(
        ("param", "value", "expected_component"),
        [
            ("HEART_RATE", 15.0, "heart_rate_score"),
            ("RESPIRATORY_RATE", 2.0, "resp_rate_score"),
            ("SPO2", 45.0, "spo2_score"),
            ("SYSTOLIC_BP", 35.0, "systolic_bp_score"),
            ("TEMPERATURE_CELSIUS", 27.0, "temperature_score"),
            ("HEART_RATE", 0.0, "heart_rate_score"),  # asystole or lead-off: flag, score high
        ],
    )
    def test_extreme_value_is_scored_and_flagged_critical(
        self, param: str, value: float, expected_component: str
    ) -> None:
        result = VitalsOrchestrator().analyse(_full_set(**{param: value}), _CTX)

        assert result.assessment.outcome is ScoreOutcome.OUT_OF_RANGE_CRITICAL
        crit = [
            f
            for f in result.assessment.findings
            if f.code is ReasonCode.CRITICAL_VALUE_REVIEW_REQUIRED
        ]
        assert len(crit) == 1
        assert crit[0].parameter is VitalSignType[param]
        assert crit[0].measured_value == value
        # NEWS2 is computed from the unchanged RCP tables — extreme band scores 3.
        assert result.news2_score is not None
        assert getattr(result.news2_score, expected_component) == 3

    def test_critical_warning_is_not_labelled_artifact(self) -> None:
        result = VitalsOrchestrator().analyse(_full_set(HEART_RATE=15.0), _CTX)
        hr_warnings = [w for w in result.pipeline_warnings if "HEART_RATE" in w]
        assert any(w.startswith("[CRITICAL]") for w in hr_warnings)
        assert not any(w.startswith("[ARTIFACT]") for w in hr_warnings)


class TestImpossibleValuesRemainArtifacts:
    @pytest.mark.parametrize(
        ("param", "value"),
        [
            ("HEART_RATE", math.nan),
            ("HEART_RATE", -5.0),
            ("SPO2", 101.0),
        ],
    )
    def test_impossible_value_is_artifact_and_not_scored(
        self, param: str, value: float
    ) -> None:
        result = VitalsOrchestrator().analyse(_full_set(**{param: value}), _CTX)

        assert result.news2_score is None
        assert result.assessment.outcome is ScoreOutcome.INCOMPLETE
        codes = {f.code for f in result.assessment.findings}
        assert ReasonCode.ARTIFACT_EXCLUDED in codes
        assert ReasonCode.MISSING_PARAMETER in codes
        assert ReasonCode.CRITICAL_VALUE_REVIEW_REQUIRED not in codes


class TestNormalValuesStillScored:
    def test_full_normal_set_is_scored(self) -> None:
        result = VitalsOrchestrator().analyse(_full_set(), _CTX)
        assert result.assessment.outcome is ScoreOutcome.SCORED
        assert result.news2_score is not None
        assert result.news2_score.total == 0


def _payload(**overrides: float) -> dict[str, object]:
    ts = _now().isoformat()
    samples: list[dict[str, object]] = []
    for s in _full_set(**overrides):
        item: dict[str, object] = {
            "vital_sign_type": s.vital_sign_type.value,
            "value": s.value,
            "unit": s.unit.value,
            "timestamp": ts,
        }
        if s.avpu_level is not None:
            item["avpu_level"] = s.avpu_level.value
        samples.append(item)
    return {"patient_id": "PT-A6", "samples": samples}


class TestApiSurfacesCriticalOutcome:
    async def test_vitals_endpoint_returns_200_with_explicit_critical_outcome(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post("/api/v1/vitals", json=_payload(HEART_RATE=15.0))

        assert resp.status_code == 200
        assert resp.headers["X-Score-Outcome"] == "critical"
        assert "CRITICAL_VALUE_REVIEW_REQUIRED" in resp.headers["X-Score-Reasons"]
        assert "X-NEWS2-Total" in resp.headers

        outcomes = [
            e["resource"]
            for e in resp.json()["entry"]
            if e["resource"]["resourceType"] == "OperationOutcome"
        ]
        assert len(outcomes) == 1
        issue_codes = [
            c["code"]
            for i in outcomes[0]["issue"]
            for c in i["details"]["coding"]
        ]
        assert "CRITICAL_VALUE_REVIEW_REQUIRED" in issue_codes
        assert any("15" in i.get("diagnostics", "") for i in outcomes[0]["issue"])
