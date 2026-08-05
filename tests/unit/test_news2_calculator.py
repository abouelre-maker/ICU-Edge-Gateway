"""
Unit Tests — NEWS2Calculator (RCP 2017 Scoring Algorithm).

IEC 62304 §5.7: Complete verification of all scoring functions.
Each test documents its corresponding RCP 2017 table boundary.
ISO 14971: Tests for HAZARD-NEWS2-001 (scoring accuracy).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.entities.news2_score import NEWS2RiskLevel
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import AVPULevel, VitalSignSample, VitalSignType, VitalSignUnit
from domain.services.news2_calculator import NEWS2Calculator, NEWS2InsufficientDataError
from domain.services.signal_processor import ProcessedVitalSign, VitalSignProcessor

_UTC = timezone.utc
_TS = datetime(2024, 1, 15, 10, 0, 0, tzinfo=_UTC)
_PROC = VitalSignProcessor()
_CALC = NEWS2Calculator()
_CTX_S1 = PatientContext(patient_id="PT-001", spo2_scale=SpO2Scale.SCALE_1)
_CTX_S2 = PatientContext(patient_id="PT-002", spo2_scale=SpO2Scale.SCALE_2)


def _make_sample(
    vital_type: VitalSignType,
    value: float,
    unit: VitalSignUnit,
    avpu: AVPULevel | None = None,
) -> VitalSignSample:
    return VitalSignSample(
        vital_sign_type=vital_type,
        value=value,
        unit=unit,
        timestamp=_TS,
        avpu_level=avpu,
    )


def _processed(sample: VitalSignSample) -> ProcessedVitalSign:
    return _PROC.process(sample)


def _full_vitals(
    rr: float = 14,
    spo2: float = 98.0,
    sbp: float = 120.0,
    hr: float = 72.0,
    temp: float = 37.0,
    on_o2: bool = False,
    avpu: AVPULevel = AVPULevel.ALERT,
) -> list[ProcessedVitalSign]:
    samples = [
        _make_sample(VitalSignType.RESPIRATORY_RATE, rr, VitalSignUnit.BREATHS_PER_MIN),
        _make_sample(VitalSignType.SPO2, spo2, VitalSignUnit.PERCENT),
        _make_sample(VitalSignType.SYSTOLIC_BP, sbp, VitalSignUnit.MMHG),
        _make_sample(VitalSignType.HEART_RATE, hr, VitalSignUnit.BPM),
        _make_sample(VitalSignType.TEMPERATURE_CELSIUS, temp, VitalSignUnit.CELSIUS),
        _make_sample(VitalSignType.SUPPLEMENTAL_O2, 1.0 if on_o2 else 0.0, VitalSignUnit.BOOLEAN),
        _make_sample(VitalSignType.CONSCIOUSNESS, 0.0, VitalSignUnit.AVPU_SCALE, avpu),
    ]
    return [_processed(s) for s in samples]


# ── Respiratory Rate Boundaries ───────────────────────────────────────────────


class TestRespiratoryRateScoring:
    """
    RCP NEWS2 2017 Table row: Respiration rate.
    IEC 62304 REQ-NEWS2-RR: Verify all 5 score bands.
    """

    @pytest.mark.parametrize(("rr", "expected"), [
        (8.0, 3),   # RCP: ≤8 = 3
        (9.0, 1),   # RCP: 9–11 = 1
        (11.0, 1),
        (12.0, 0),  # RCP: 12–20 = 0
        (20.0, 0),
        (21.0, 2),  # RCP: 21–24 = 2
        (24.0, 2),
        (25.0, 3),  # RCP: ≥25 = 3
        (40.0, 3),
    ])
    def test_rr_boundary(self, rr: float, expected: int) -> None:
        vitals = _full_vitals(rr=rr)
        score = _CALC.calculate(vitals, _CTX_S1)
        assert score.resp_rate_score == expected, (
            f"RR={rr}: expected score {expected}, got {score.resp_rate_score}. "
            "RCP NEWS2 2017 Table."
        )


# ── SpO2 Scale 1 Boundaries ───────────────────────────────────────────────────


class TestSpO2Scale1Scoring:
    """
    RCP NEWS2 2017: SpO2 Scale 1 (standard).
    ISO 14971 HAZARD-SPO2-001: Controls misclassification of SpO2 range.
    """

    @pytest.mark.parametrize(("spo2", "expected"), [
        (91.0, 3),   # ≤91 = 3
        (92.0, 2),   # 92–93 = 2
        (93.0, 2),
        (94.0, 1),   # 94–95 = 1
        (95.0, 1),
        (96.0, 0),   # ≥96 = 0
        (99.0, 0),
    ])
    def test_spo2_scale1_boundary(self, spo2: float, expected: int) -> None:
        vitals = _full_vitals(spo2=spo2, on_o2=False)
        score = _CALC.calculate(vitals, _CTX_S1)
        assert score.spo2_score == expected, (
            f"SpO2={spo2}% Scale1: expected {expected}, got {score.spo2_score}."
        )


# ── SpO2 Scale 2 Boundaries ───────────────────────────────────────────────────


class TestSpO2Scale2Scoring:
    """
    RCP NEWS2 2017: SpO2 Scale 2 (hypercapnic respiratory failure — COPD).
    ISO 14971 HAZARD-SPO2-001: Scale 2 scoring differs significantly from Scale 1.
    """

    @pytest.mark.parametrize(("spo2", "on_o2", "expected"), [
        (83.0, False, 3),   # ≤83 = 3
        (84.0, False, 2),   # 84–85 = 2
        (85.0, False, 2),
        (86.0, False, 1),   # 86–87 = 1
        (87.0, False, 1),
        (88.0, False, 0),   # 88–92 on air = 0 (COPD target range)
        (92.0, False, 0),
        (93.0, True,  1),   # 93–94 on O2 = 1
        (94.0, True,  1),
        (95.0, True,  2),   # 95–96 on O2 = 2
        (96.0, True,  2),
        (97.0, True,  3),   # ≥97 on O2 = 3
        (99.0, True,  3),
        (93.0, False, 0),   # ≥93 on air for COPD = normal (no penalty)
    ])
    def test_spo2_scale2_boundary(
        self, spo2: float, on_o2: bool, expected: int
    ) -> None:
        vitals = _full_vitals(spo2=spo2, on_o2=on_o2)
        score = _CALC.calculate(vitals, _CTX_S2)
        assert score.spo2_score == expected, (
            f"SpO2={spo2}% Scale2 on_o2={on_o2}: "
            f"expected {expected}, got {score.spo2_score}."
        )


# ── Supplemental O2 ───────────────────────────────────────────────────────────


class TestSupplementalO2Scoring:
    def test_on_o2_scores_2(self) -> None:
        vitals = _full_vitals(on_o2=True)
        assert _CALC.calculate(vitals, _CTX_S1).supplemental_o2_score == 2

    def test_on_air_scores_0(self) -> None:
        vitals = _full_vitals(on_o2=False)
        assert _CALC.calculate(vitals, _CTX_S1).supplemental_o2_score == 0


# ── Systolic Blood Pressure Boundaries ───────────────────────────────────────


class TestSystolicBPScoring:
    @pytest.mark.parametrize(("sbp", "expected"), [
        (90.0, 3),    # ≤90 = 3
        (91.0, 2),    # 91–100 = 2
        (100.0, 2),
        (101.0, 1),   # 101–110 = 1
        (110.0, 1),
        (111.0, 0),   # 111–219 = 0
        (219.0, 0),
        (220.0, 3),   # ≥220 = 3
        (280.0, 3),
    ])
    def test_sbp_boundary(self, sbp: float, expected: int) -> None:
        vitals = _full_vitals(sbp=sbp)
        score = _CALC.calculate(vitals, _CTX_S1)
        assert score.systolic_bp_score == expected, (
            f"SBP={sbp}: expected {expected}, got {score.systolic_bp_score}."
        )


# ── Heart Rate Boundaries ─────────────────────────────────────────────────────


class TestHeartRateScoring:
    """
    ISO 14971 HAZARD-HR-001: Non-monotonic scoring (1 at 41–50 then 0 at 51–90).
    Must be explicitly verified to prevent regression.
    """

    @pytest.mark.parametrize(("hr", "expected"), [
        (40.0, 3),    # ≤40 = 3
        (41.0, 1),    # 41–50 = 1 (non-monotonic!)
        (50.0, 1),
        (51.0, 0),    # 51–90 = 0
        (90.0, 0),
        (91.0, 1),    # 91–110 = 1
        (110.0, 1),
        (111.0, 2),   # 111–130 = 2
        (130.0, 2),
        (131.0, 3),   # ≥131 = 3
        (200.0, 3),
    ])
    def test_hr_boundary(self, hr: float, expected: int) -> None:
        vitals = _full_vitals(hr=hr)
        score = _CALC.calculate(vitals, _CTX_S1)
        assert score.heart_rate_score == expected, (
            f"HR={hr}: expected {expected}, got {score.heart_rate_score}."
        )


# ── Consciousness (AVPU) Scoring ──────────────────────────────────────────────


class TestConsciousnessScoring:
    """
    ISO 14971 HAZARD-CON-001: Binary scoring (0 or 3) — no intermediate values.
    """

    def test_alert_scores_0(self) -> None:
        vitals = _full_vitals(avpu=AVPULevel.ALERT)
        assert _CALC.calculate(vitals, _CTX_S1).consciousness_score == 0

    @pytest.mark.parametrize("avpu", [
        AVPULevel.VOICE,
        AVPULevel.PAIN,
        AVPULevel.UNRESPONSIVE,
        AVPULevel.NEW_CONFUSION,
    ])
    def test_non_alert_scores_3(self, avpu: AVPULevel) -> None:
        vitals = _full_vitals(avpu=avpu)
        score = _CALC.calculate(vitals, _CTX_S1).consciousness_score
        assert score == 3, f"AVPU.{avpu.name} must score 3. Got {score}."


# ── Temperature Boundaries ────────────────────────────────────────────────────


class TestTemperatureScoring:
    @pytest.mark.parametrize(("temp", "expected"), [
        (35.0, 3),    # ≤35.0 = 3
        (35.1, 1),    # 35.1–36.0 = 1
        (36.0, 1),
        (36.1, 0),    # 36.1–38.0 = 0
        (38.0, 0),
        (38.1, 1),    # 38.1–39.0 = 1
        (39.0, 1),
        (39.1, 2),    # ≥39.1 = 2
        (41.0, 2),
    ])
    def test_temperature_boundary(self, temp: float, expected: int) -> None:
        vitals = _full_vitals(temp=temp)
        score = _CALC.calculate(vitals, _CTX_S1)
        assert score.temperature_score == expected, (
            f"Temp={temp}°C: expected {expected}, got {score.temperature_score}."
        )


# ── Insufficient Data Handling ────────────────────────────────────────────────


class TestInsufficientDataHandling:
    def test_missing_rr_raises(self) -> None:
        vitals = [v for v in _full_vitals() if
                  v.original.vital_sign_type is not VitalSignType.RESPIRATORY_RATE]
        with pytest.raises(NEWS2InsufficientDataError, match="RESPIRATORY_RATE"):
            _CALC.calculate(vitals, _CTX_S1)

    def test_missing_spo2_raises(self) -> None:
        vitals = [v for v in _full_vitals() if
                  v.original.vital_sign_type is not VitalSignType.SPO2]
        with pytest.raises(NEWS2InsufficientDataError, match="SPO2"):
            _CALC.calculate(vitals, _CTX_S1)

    def test_empty_vitals_raises(self) -> None:
        with pytest.raises(NEWS2InsufficientDataError):
            _CALC.calculate([], _CTX_S1)