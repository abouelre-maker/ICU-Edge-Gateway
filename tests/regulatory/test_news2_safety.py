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

import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from domain.entities.news2_score import NEWS2RiskLevel, NEWS2Score
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.artifact_rejector import PhysiologicalBoundsChecker
from domain.services.news2_calculator import NEWS2Calculator, NEWS2InsufficientDataError
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


# ── HAZARD-DSP-007: NaN Scalar Rejection (Phase 5-Stream Section D) ──────────


class TestHazardDsp007NanSpo2ExcludedNotScoredNormal:
    """
    ISO 14971 HAZARD-DSP-007, SpO2-specific case: this is the ASYMMETRIC,
    clinically dangerous direction of the finding (see the register entry
    for the full table across all five threshold-ladder parameters). Unlike
    HR/RR/SBP/Temp, whose `<=`-chains all fall through to their HIGHEST-
    severity band on NaN (false alarm -- safe direction, verified
    separately), _score_spo2's Scale-1 ladder falls through to its LOWEST-
    severity band (`return 0`, "normal") on NaN. A NaN SpO2 that reached
    scoring, pre-fix, would have looked EXACTLY like a healthy 96%+ reading
    -- false reassurance masking a real desaturation, the actual worst-case
    direction for this hazard. Run through the FULL pipeline
    (VitalSignProcessor.process() -> NEWS2Calculator.calculate()), not just
    the scoring function in isolation, to prove the fix is effective at the
    boundary that actually matters (is_within_physiological_bounds and the
    mandatory-parameter check), not just at the arithmetic level.
    """

    def test_nan_spo2_is_excluded_not_silently_scored_normal(self) -> None:
        """
        Post-fix: SPO2 is a _REQUIRED_VITAL_TYPES member (news2_calculator.py)
        -- once PhysiologicalBoundsChecker correctly flags a NaN scalar as
        is_within_physiological_bounds=False, NEWS2Calculator._extract_value()
        excludes it as a candidate entirely, and
        _assert_required_parameters_present() must then find SPO2 missing
        and refuse to score AT ALL -- not silently substitute score=0.
        Otherwise-normal RR/HR/SBP/Temp (all real, valid values) to isolate
        the SpO2 effect specifically.
        """
        vitals = _vitals(rr=16, spo2=float("nan"), sbp=120, hr=72, temp=37.0)

        # Precondition: PhysiologicalBoundsChecker actually flagged it --
        # if this assertion ever fails, the test below would pass for the
        # wrong reason (SpO2 legitimately absent, not NaN-rejected).
        spo2_processed = next(
            p
            for p in vitals
            if p.original.vital_sign_type is VitalSignType.SPO2
        )
        assert spo2_processed.is_within_physiological_bounds is False, (
            "Precondition failed: PhysiologicalBoundsChecker did not flag "
            "the NaN SpO2 sample -- HAZARD-DSP-007 regression."
        )

        with pytest.raises(NEWS2InsufficientDataError, match="SPO2"):
            _CALC.calculate(vitals, _S1)

    def test_nan_spo2_never_produces_a_spo2_score_of_zero(self) -> None:
        """
        Explicit negative assertion, stated the way the hazard is actually
        dangerous: this is NOT "raises some error" in the abstract -- it is
        specifically "a NaN SpO2 must never be indistinguishable from a
        genuinely healthy SpO2 reading (score 0)". NEWS2InsufficientDataError
        IS that guarantee (no NEWS2Score object -- and therefore no
        spo2_score -- is ever produced at all when SpO2 is unusable), proven
        here by confirming calculate() does not return.
        """
        vitals = _vitals(rr=16, spo2=float("nan"), sbp=120, hr=72, temp=37.0)
        with pytest.raises(NEWS2InsufficientDataError):
            score = _CALC.calculate(vitals, _S1)
            # Unreachable if the fix works -- documents what would have to
            # be true (and wrong) for this test to pass for the wrong reason.
            assert score.spo2_score != 0  # pragma: no cover


# ── HAZARD-NEWS2-003 / Bandit B101 nosec pin: filter parity + -O survival ────
#
# Closes a specific gap this session's own code review flagged (Bandit B101
# nosec review of the 6 `assert X is not None` lines in
# NEWS2Calculator.calculate() / _extract_avpu()): those asserts were judged
# safe to suppress because they merely re-confirm what
# _assert_required_parameters_present()'s real `if missing: raise
# NEWS2InsufficientDataError(...)` already established -- never the actual
# safety-relevant validation. That judgment was argued in a code-review
# comment, not proven. The two classes below prove it, using the same
# "test the boundary that actually matters, through the real pipeline"
# methodology as TestHazardDsp007NanSpo2ExcludedNotScoredNormal above,
# generalized from that test's single SpO2 case to all 5 required types,
# plus a genuine `python -O` run (not an assumption about what -O does).


class TestNews2CalculatorFilterParityNeverDrifts:
    """
    _assert_required_parameters_present() and _extract_value() both read
    the SAME `ProcessedVitalSign.is_within_physiological_bounds` flag off
    the SAME `vitals` sequence -- they cannot disagree today. The only way
    they could ever silently drift apart is a future edit that adds an
    extra condition to one filter without mirroring it in the other (e.g.
    _extract_value() starts also checking `outlier_count == 0` while
    _assert_required_parameters_present() does not, or vice versa). This
    class pins today's correct, agreeing behavior for all 5 required
    types so such a drift fails a test immediately instead of surfacing
    later as a silent None reaching an assert-guarded (and, per the nosec
    review, potentially -O-stripped) scoring call.

    PhysiologicalBoundsChecker.check() is monkeypatched to a minimal,
    test-owned NaN-rejection contract (ok=False for NaN, ok=True
    otherwise) rather than exercising the real scipy-adjacent checker --
    this isolates the test to NEWS2Calculator's OWN internal consistency,
    per Clean Architecture's "domain services tested independently"
    principle already stated in signal_processor.py's docstring. The real
    checker's NaN handling is what
    TestHazardDsp007NanSpo2ExcludedNotScoredNormal already proves, through
    the full DSP pipeline, for the SpO2 case.
    """

    @pytest.fixture(autouse=True)
    def _pin_nan_rejection_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_check(
            self: PhysiologicalBoundsChecker,
            vital_sign_type: VitalSignType,
            value: float,
        ) -> tuple[bool, str]:
            if math.isnan(value):
                return False, f"[test-pinned] NaN rejected for {vital_sign_type.name}."
            return True, ""

        monkeypatch.setattr(PhysiologicalBoundsChecker, "check", _fake_check)

    @pytest.mark.parametrize(
        "kwarg, vital_type",
        [
            ("rr", VitalSignType.RESPIRATORY_RATE),
            ("spo2", VitalSignType.SPO2),
            ("sbp", VitalSignType.SYSTOLIC_BP),
            ("hr", VitalSignType.HEART_RATE),
            ("temp", VitalSignType.TEMPERATURE_CELSIUS),
        ],
    )
    def test_nan_in_any_required_type_raises_via_the_real_check_not_the_assert(
        self, kwarg: str, vital_type: VitalSignType
    ) -> None:
        """
        Make ONLY the parametrized type NaN (all other required types
        stay real/valid). Precondition (same style as
        TestHazardDsp007NanSpo2ExcludedNotScoredNormal): confirm the
        (pinned) checker actually flagged it -- if this fails, the test
        below would pass for the wrong reason. Then confirm
        NEWS2Calculator.calculate() raises NEWS2InsufficientDataError
        naming that exact type. If _assert_required_parameters_present()
        and _extract_value() had drifted apart such that the former
        considered this type present while the latter found no usable
        candidate for it, calculate() would instead reach the
        assert-guarded code path with a None value for this parameter.
        """
        vitals = _vitals(**{kwarg: float("nan")})

        target = next(p for p in vitals if p.original.vital_sign_type is vital_type)
        assert target.is_within_physiological_bounds is False, (
            f"Precondition failed: the pinned bounds checker did not flag "
            f"the NaN {vital_type.name} sample -- test would pass for the "
            f"wrong reason."
        )

        with pytest.raises(NEWS2InsufficientDataError, match=vital_type.value):
            _CALC.calculate(vitals, _S1)


class TestNews2CalculatorAssertsAreProvablyRedundantUnderDashO:
    """
    TestNews2CalculatorFilterParityNeverDrifts proves the two filters
    agree today, under normal (non-optimized) execution -- the same mode
    every other test in this suite runs under, where the 6 nosec'd
    asserts are still live. That leaves the actual claim in the nosec
    comments -- "even if `python -O` stripped these, the values are
    guaranteed non-None by [_assert_required_parameters_present()], not
    by these asserts" -- unverified by anything in this suite. This class
    verifies it directly: spawns a REAL `python -O` subprocess (CPython's
    documented assert-stripping flag, not a simulation of it) reproducing
    the missing-required-vital scenario, and confirms
    NEWS2InsufficientDataError is still what happens -- not a silent
    score, not (impossible under -O anyway) an AssertionError.

    One representative required type (HEART_RATE) is used, not all 5 --
    the parity test above already proves the 5 types are structurally
    identical in how the two filters treat them; this subprocess check
    exists to verify the -O claim once, not to re-prove per-type parity a
    second time at subprocess cost. All verification inside the child
    script uses explicit if/raise/sys.exit, never `assert` -- an `assert`
    written inside a script that is itself invoked with `-O` would be
    stripped too, which would silently defeat the very thing being
    tested.
    """

    def test_missing_heart_rate_still_raises_insufficient_data_under_python_dash_o(
        self,
    ) -> None:
        src_dir = Path(__file__).resolve().parents[2] / "src"
        script = """
import sys

if __debug__:
    print("SETUP-FAIL: __debug__ is True -- this process is not actually running under -O.")
    sys.exit(2)

from datetime import datetime, timezone

from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import VitalSignSample, VitalSignType, VitalSignUnit
from domain.services.news2_calculator import NEWS2Calculator, NEWS2InsufficientDataError
from domain.services.signal_processor import VitalSignProcessor

ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
proc = VitalSignProcessor()
samples = [
    VitalSignSample(VitalSignType.RESPIRATORY_RATE, 16, VitalSignUnit.BREATHS_PER_MIN, ts),
    VitalSignSample(VitalSignType.SPO2, 98.0, VitalSignUnit.PERCENT, ts),
    VitalSignSample(VitalSignType.SYSTOLIC_BP, 120.0, VitalSignUnit.MMHG, ts),
    VitalSignSample(VitalSignType.HEART_RATE, float("nan"), VitalSignUnit.BPM, ts),
    VitalSignSample(VitalSignType.TEMPERATURE_CELSIUS, 37.0, VitalSignUnit.CELSIUS, ts),
]
vitals = [proc.process(s) for s in samples]
ctx = PatientContext(patient_id="PT-REG-OFLAG", spo2_scale=SpO2Scale.SCALE_1)

try:
    score = NEWS2Calculator().calculate(vitals, ctx)
except NEWS2InsufficientDataError as exc:
    if "HEART_RATE" not in str(exc):
        print(f"FAIL: raised but did not name HEART_RATE: {exc}")
        sys.exit(1)
    print("OK: NEWS2InsufficientDataError raised and names HEART_RATE, under -O.")
    sys.exit(0)
else:
    print(f"FAIL: calculate() returned a score instead of raising: {score!r}")
    sys.exit(1)
"""
        result = subprocess.run(
            [sys.executable, "-O", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PYTHONPATH": str(src_dir)},
        )
        assert result.returncode == 0, (
            "python -O subprocess did not confirm the expected fail-safe "
            f"behavior.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK: NEWS2InsufficientDataError raised" in result.stdout, (
            f"Unexpected subprocess stdout: {result.stdout}"
        )
