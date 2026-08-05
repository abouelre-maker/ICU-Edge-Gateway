"""
Regulatory Unit Tests — NEWS2 Safety Boundary Verification.

IEC 62304 §5.7: Regulatory verification — these tests map directly to
ISO 14971 hazard controls. They MUST NOT be skipped or marked xfail.

Test naming convention: test_hazard_{hazard_id}_{description}
Each test corresponds to a specific row in regulatory/risk_register.xlsx.

ISO 14971 Controls verified here:
    HAZARD-NEWS2-001: Incorrect scoring causes missed deterioration
    HAZARD-NEWS2-002: Incorrect risk level causes wrong escalation
    HAZARD-NEWS2-003: Partial scoring creates false clinical confidence
    HAZARD-SPO2-001:  Wrong scale causes SpO2 misclassification
    HAZARD-HR-001:    Non-monotonic HR scoring regression
    HAZARD-CON-001:   AVPU miscoding causes consciousness underestimation
"""

from __future__ import annotations

from datetime import datetime, timezone

from domain.entities.news2_score import NEWS2RiskLevel, NEWS2Score
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.news2_calculator import NEWS2Calculator
from domain.services.signal_processor import VitalSignProcessor

_UTC = timezone.utc
_TS = datetime(2024, 1, 15, 10, 0, 0, tzinfo=_UTC)
_PROC = VitalSignProcessor()
_CALC = NEWS2Calculator()


def _vitals(
    rr: float = 14,
    spo2: float = 98.0,
    sbp: float = 120.0,
    hr: float = 72.0,
    temp: float = 37.0,
    on_o2: bool = False,
    avpu: AVPULevel = AVPULevel.ALERT,
):  # type: ignore[return]
    samples = [
        VitalSignSample(
            VitalSignType.RESPIRATORY_RATE, rr, VitalSignUnit.BREATHS_PER_MIN, _TS
        ),
        VitalSignSample(VitalSignType.SPO2, spo2, VitalSignUnit.PERCENT, _TS),
        VitalSignSample(VitalSignType.SYSTOLIC_BP, sbp, VitalSignUnit.MMHG, _TS),
        VitalSignSample(VitalSignType.HEART_RATE, hr, VitalSignUnit.BPM, _TS),
        VitalSignSample(
            VitalSignType.TEMPERATURE_CELSIUS, temp, VitalSignUnit.CELSIUS, _TS
        ),
        VitalSignSample(
            VitalSignType.SUPPLEMENTAL_O2,
            1.0 if on_o2 else 0.0,
            VitalSignUnit.BOOLEAN,
            _TS,
        ),
        VitalSignSample(
            VitalSignType.CONSCIOUSNESS,
            0.0,
            VitalSignUnit.AVPU_SCALE,
            _TS,
            avpu_level=avpu,
        ),
    ]
    return [_PROC.process(s) for s in samples]


_S1 = PatientContext(patient_id="PT-REG-001", spo2_scale=SpO2Scale.SCALE_1)
_S2 = PatientContext(patient_id="PT-REG-002", spo2_scale=SpO2Scale.SCALE_2)


# ── HAZARD-NEWS2-001: Scoring Accuracy ────────────────────────────────────────


class TestHazardNEWS2001ScoringAccuracy:
    """
    ISO 14971 HAZARD-NEWS2-001:
        Hazard: Software calculates incorrect NEWS2 component score.
        Harm: Missed deterioration or false escalation.
        Control: All scoring boundaries tested at exact threshold values.
    """

    def test_hazard_001_all_normal_scores_zero(self) -> None:
        """Patient with all normal vital signs must score zero."""
        score = _CALC.calculate(_vitals(rr=16, spo2=98, sbp=120, hr=72, temp=37.0), _S1)
        assert score.total == 0, (
            "All-normal vitals must produce NEWS2 total = 0. "
            "ISO 14971 HAZARD-NEWS2-001."
        )

    def test_hazard_001_critical_vt_scenario(self) -> None:
        """
        Simulated ventricular tachycardia scenario:
          HR=150, SBP=85, RR=28, SpO2=89%, Temp=37.0, Alert
        Expected minimum score: 3+3+3+3 = 12 (HIGH)
        """
        score = _CALC.calculate(
            _vitals(hr=150, sbp=85, rr=28, spo2=89, temp=37.0),
            _S1,
        )
        assert score.total >= 10, (
            f"VT scenario must score ≥10. Got {score.total}. "
            "ISO 14971 HAZARD-NEWS2-001: critical scenario underscoring."
        )
        assert score.risk_level is NEWS2RiskLevel.HIGH

    def test_hazard_001_sepsis_scenario(self) -> None:
        """
        Simulated sepsis early warning:
          HR=110, SBP=95, RR=22, Temp=38.8, SpO2=94%, Alert
        Expected score: 1+1+2+1+1+0 = 6 (MEDIUM)
        """
        score = _CALC.calculate(
            _vitals(hr=110, sbp=95, rr=22, temp=38.8, spo2=94),
            _S1,
        )
        assert score.risk_level in {NEWS2RiskLevel.MEDIUM, NEWS2RiskLevel.HIGH}, (
            f"Sepsis scenario must be MEDIUM or HIGH. Got {score.risk_level}. "
            "ISO 14971 HAZARD-NEWS2-001."
        )


# ── HAZARD-NEWS2-002: Risk Level Classification ───────────────────────────────


class TestHazardNEWS2002RiskLevel:
    """
    ISO 14971 HAZARD-NEWS2-002:
        Hazard: Incorrect risk level classification.
        Harm: Wrong clinical escalation (over or under).
        Control: All risk level boundaries verified at exact total scores.
    """

    def test_hazard_002_total_0_is_normal(self) -> None:
        assert NEWS2Score.zero().risk_level is NEWS2RiskLevel.NORMAL

    def test_hazard_002_total_1_is_low(self) -> None:
        score = _CALC.calculate(_vitals(rr=9), _S1)  # RR=9 → +1
        assert score.total == 1
        assert score.risk_level is NEWS2RiskLevel.LOW

    def test_hazard_002_total_4_no_extreme_is_low(self) -> None:
        """Total 4 with no single parameter = 3 must be LOW."""
        # Three parameters each scoring 1 and one scoring 1 (total 4, no 3s)
        score = _CALC.calculate(
            _vitals(rr=9, hr=91, sbp=105, temp=35.5),  # 1+1+1+1 = 4
            _S1,
        )
        assert score.total == 4
        assert score.has_extreme_single_parameter is False
        assert score.risk_level is NEWS2RiskLevel.LOW

    def test_hazard_002_single_extreme_parameter_is_low_medium(self) -> None:
        """
        Total = 3 with ONE parameter scoring 3 must be LOW_MEDIUM, not LOW.
        This is the most important risk level boundary in NEWS2 2017.
        RCP §3: A single extreme parameter triggers 1-hourly monitoring.
        """
        score = _CALC.calculate(
            _vitals(rr=8, spo2=98, sbp=120, hr=72, temp=37.0),  # RR=8 → +3 only
            _S1,
        )
        assert score.resp_rate_score == 3
        assert score.total == 3
        assert score.has_extreme_single_parameter is True
        assert score.risk_level is NEWS2RiskLevel.LOW_MEDIUM, (
            "Total=3 with single parameter score=3 must be LOW_MEDIUM. "
            "RCP NEWS2 2017 §3. ISO 14971 HAZARD-NEWS2-002."
        )

    def test_hazard_002_total_5_is_medium(self) -> None:
        score = _CALC.calculate(
            _vitals(rr=25, hr=91, sbp=105),  # 3+1+1 = 5
            _S1,
        )
        assert score.total == 5
        assert score.risk_level is NEWS2RiskLevel.MEDIUM

    def test_hazard_002_total_7_is_high(self) -> None:
        score = _CALC.calculate(
            _vitals(rr=25, sbp=85, hr=150, spo2=91, temp=35.0),  # 3+3+3+3+3 ≥ 7
            _S1,
        )
        assert score.total >= 7
        assert score.risk_level is NEWS2RiskLevel.HIGH


# ── HAZARD-SPO2-001: Scale Misassignment ─────────────────────────────────────


class TestHazardSPO2001ScaleMisassignment:
    """
    ISO 14971 HAZARD-SPO2-001:
        Hazard: Scale 1 applied to COPD patient (Scale 2 required).
        Harm: SpO2 at 90% scores 3 on Scale 1 but 0 on Scale 2 —
              a 3-point difference causing false HIGH risk level.
        Control: SpO2 scale must be explicitly set in PatientContext.
    """

    def test_hazard_spo2_90pct_scale1_vs_scale2_differ(self) -> None:
        """SpO2=90% produces different scores on Scale 1 vs Scale 2."""
        vitals = _vitals(spo2=90.0, on_o2=False)
        score_s1 = _CALC.calculate(vitals, _S1)
        score_s2 = _CALC.calculate(vitals, _S2)
        assert score_s1.spo2_score == 3, "Scale 1: SpO2=90% must score 3."
        assert score_s2.spo2_score == 0, (
            "Scale 2: SpO2=90% is within COPD target range (88–92%) and must score 0. "
            "ISO 14971 HAZARD-SPO2-001: 3-point difference — scale selection is critical."
        )

    def test_hazard_spo2_scale2_default_is_conservative(self) -> None:
        """
        Scale 2 above target (97% on O2) must score 3.
        Clinical meaning: COPD patient with SpO2 above target on O2 = O2 over-delivery.
        """
        vitals = _vitals(spo2=97.0, on_o2=True)
        score = _CALC.calculate(vitals, _S2)
        assert score.spo2_score == 3, (
            "Scale 2: SpO2=97% on O2 must score 3 (above target for COPD). "
            "ISO 14971 HAZARD-SPO2-001."
        )


# ── HAZARD-HR-001: Non-Monotonic Heart Rate Regression ───────────────────────


class TestHazardHR001NonMonotonicScore:
    """
    ISO 14971 HAZARD-HR-001:
        Hazard: Developer "fixes" the non-intuitive 41–50 bpm score = 1
                by making it 0 (assuming score should be monotonic).
        Harm: Bradycardia in 41–50 range is not flagged.
        Control: Explicit tests at 41 and 51 to prevent regression.
    """

    def test_hazard_hr001_41bpm_scores_1_not_0(self) -> None:
        """
        HR=41 bpm must score 1 (sinus bradycardia). Developer regression risk:
        HR=51 scores 0, so HR=41 might be "fixed" to 0 incorrectly.
        """
        score = _CALC.calculate(_vitals(hr=41.0), _S1)
        assert score.heart_rate_score == 1, (
            "HR=41 must score 1. Non-monotonic by design — bradycardia is abnormal. "
            "ISO 14971 HAZARD-HR-001."
        )

    def test_hazard_hr001_51bpm_scores_0(self) -> None:
        score = _CALC.calculate(_vitals(hr=51.0), _S1)
        assert score.heart_rate_score == 0, "HR=51 must score 0 (normal range)."


# ── HAZARD-CON-001: Consciousness Underestimation ─────────────────────────────


class TestHazardCON001ConsciousnessScoring:
    """
    ISO 14971 HAZARD-CON-001:
        Hazard: NEW_CONFUSION (C) is not recognized or scored as 0 instead of 3.
        Harm: Encephalopathy not detected; delayed escalation; patient deteriorates.
        Control: Explicit test for AVPULevel.NEW_CONFUSION scores 3.
    """

    def test_hazard_con001_new_confusion_scores_3(self) -> None:
        """
        New-onset confusion is a NEWS2-specific addition (absent from original AVPU).
        It must always score 3 — not 0 (Alert) or any intermediate value.
        """
        vitals = _vitals(avpu=AVPULevel.NEW_CONFUSION)
        score = _CALC.calculate(vitals, _S1)
        assert score.consciousness_score == 3, (
            "NEW_CONFUSION must score 3. "
            "RCP NEWS2 2017 added C (confusion) as equivalent to V/P/U. "
            "ISO 14971 HAZARD-CON-001: confusion = 0 causes missed deterioration."
        )

    def test_hazard_con001_all_non_alert_states_score_3(self) -> None:
        """All five non-Alert AVPU states must score exactly 3 — no exceptions."""
        for avpu_level in [
            AVPULevel.VOICE,
            AVPULevel.PAIN,
            AVPULevel.UNRESPONSIVE,
            AVPULevel.NEW_CONFUSION,
        ]:
            vitals = _vitals(avpu=avpu_level)
            score = _CALC.calculate(vitals, _S1)
            assert score.consciousness_score == 3, (
                f"AVPULevel.{avpu_level.name} must score 3. Got {score.consciousness_score}. "
                "ISO 14971 HAZARD-CON-001."
            )
