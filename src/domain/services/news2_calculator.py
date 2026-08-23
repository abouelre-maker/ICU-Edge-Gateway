"""
NEWS2 Score Calculator — RCP 2017 Clinical Algorithm.

Clinical Reference: Royal College of Physicians. National Early Warning Score (NEWS) 2.
London: RCP, December 2017. ISBN 978-1-86016-693-6.

IEC 62304 §5.5: Every scoring boundary is traceable to a specific table cell
in the RCP 2017 publication. Traceability is enforced by test docstrings in
tests/regulatory/test_news2_safety.py.

ISO 14971 HAZARD-NEWS2-001: Incorrect NEWS2 scoring causes missed clinical
deterioration or false escalation. All boundary conditions are verified by
parametrized regulatory tests.

FDA CDS Non-Device Exemption (21 CFR §880.3780):
  - Output is advisory only — requires clinician review before clinical action.
  - Software does NOT trigger automated treatment.
  - Display to clinician for independent decision is mandatory per exemption criteria.

Health Canada SaMD Class II:
  - Risk Management File (ISO 14971) required.
  - All scoring logic is deterministic and auditable.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from domain.entities.news2_score import NEWS2RiskLevel, NEWS2Score  # noqa: F401
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import AVPULevel, VitalSignType
from domain.services.signal_processor import ProcessedVitalSign


class NEWS2InsufficientDataError(Exception):
    """
    Raised when mandatory vital sign parameters are absent from the input.

    IEC 62304 REQ-NEWS2-003: NEWS2 MUST have all six mandatory parameters.
    ISO 14971 HAZARD-NEWS2-003: Partial scoring underestimates clinical risk.
    Mitigation: fail fast rather than return a dangerously incomplete score.
    """


# Required VitalSignTypes for a complete NEWS2 calculation.
# Supplemental O2 and Consciousness default safely when absent.
_REQUIRED_VITAL_TYPES: frozenset[VitalSignType] = frozenset(
    {
        VitalSignType.RESPIRATORY_RATE,
        VitalSignType.SPO2,
        VitalSignType.SYSTOLIC_BP,
        VitalSignType.HEART_RATE,
        VitalSignType.TEMPERATURE_CELSIUS,
    }
)


class NEWS2Calculator:
    """
    Implements the complete RCP NEWS2 2017 seven-parameter scoring algorithm.

    IEC 62304: Class B — safety classification applies to every scoring method.
    ISO 14971 HAZARD-NEWS2-001: Controls risk of missed clinical deterioration.
    FDA CDS: Advisory output — clinician review is the mandatory risk control.

    Usage:
        calculator = NEWS2Calculator()
        score = calculator.calculate(processed_vitals, patient_context)
        if score.risk_level == NEWS2RiskLevel.HIGH:
            # Trigger clinical advisory display (NOT automated treatment)
    """

    def calculate(
        self,
        vitals: Sequence[ProcessedVitalSign],
        context: PatientContext,
    ) -> NEWS2Score:
        """
        Calculate the complete NEWS2 score from a sequence of processed vital signs.

        IEC 62304 REQ-NEWS2-001: All seven scoring parameters must be evaluated.
        ISO 14971 HAZARD-NEWS2-001: Each boundary implements a specific RCP 2017
        table cell — do not modify thresholds without updating the Risk Register.

        Args:
            vitals:  Processed vital signs from VitalSignProcessor.
            context: Patient context containing SpO2 scale assignment.

        Returns:
            NEWS2Score with all component scores, total, and risk level.

        Raises:
            NEWS2InsufficientDataError: If any mandatory vital sign type is absent.
        """
        self._assert_required_parameters_present(vitals)

        # Extract values (returns None if type absent — handled by defaults)
        rr = self._extract_value(VitalSignType.RESPIRATORY_RATE, vitals)
        spo2 = self._extract_value(VitalSignType.SPO2, vitals)
        sbp = self._extract_value(VitalSignType.SYSTOLIC_BP, vitals)
        hr = self._extract_value(VitalSignType.HEART_RATE, vitals)
        temp = self._extract_value(VitalSignType.TEMPERATURE_CELSIUS, vitals)

        # O2 defaults to air (conservative: under-scores, never over-scores)
        on_o2 = self._extract_on_supplemental_o2(vitals)

        # Consciousness defaults to Alert (conservative: 0 points)
        avpu = self._extract_avpu(vitals)

        # Bandit B101 (assert_used): these are pure type-narrowing aids for
        # mypy, not the actual safety-relevant validation -- that already
        # happened above via _assert_required_parameters_present(), which
        # raises NEWS2InsufficientDataError before this point if any of
        # rr/spo2/sbp/hr/temp were absent or out-of-bounds. Even if
        # `python -O` stripped these (this project's Dockerfile/entrypoint
        # never enables optimized mode), the values are guaranteed non-None
        # by that prior check, not by these asserts.
        assert rr is not None  # nosec B101
        assert spo2 is not None  # nosec B101
        assert sbp is not None  # nosec B101
        assert hr is not None  # nosec B101
        assert temp is not None  # nosec B101

        return NEWS2Score(
            resp_rate_score=self._score_respiratory_rate(rr),
            spo2_score=self._score_spo2(spo2, context.spo2_scale, on_o2),
            supplemental_o2_score=self._score_supplemental_o2(on_o2),
            systolic_bp_score=self._score_systolic_bp(sbp),
            heart_rate_score=self._score_heart_rate(hr),
            consciousness_score=self._score_consciousness(avpu),
            temperature_score=self._score_temperature(temp),
            calculated_at=datetime.now(tz=timezone.utc),
        )

    # ── Mandatory Parameter Check ──────────────────────────────────────────────

    def _assert_required_parameters_present(
        self,
        vitals: Sequence[ProcessedVitalSign],
    ) -> None:
        """
        IEC 62304 REQ-NEWS2-003: Fail fast if mandatory parameters are absent.
        ISO 14971 HAZARD-NEWS2-003: Partial scoring is worse than no scoring —
        it creates false confidence in an incomplete risk assessment.
        """
        available = frozenset(
            v.original.vital_sign_type
            for v in vitals
            if v.is_within_physiological_bounds
        )
        missing = _REQUIRED_VITAL_TYPES - available
        if missing:
            missing_names = ", ".join(
                t.name for t in sorted(missing, key=lambda x: x.value)
            )
            raise NEWS2InsufficientDataError(
                f"NEWS2 calculation requires: {missing_names}. "
                "None of these vital signs were present in the processed vitals, "
                "or all were flagged as instrument artifacts. "
                "IEC 62304 REQ-NEWS2-003 / ISO 14971 HAZARD-NEWS2-003."
            )

    # ── Value Extraction Helpers ───────────────────────────────────────────────

    @staticmethod
    def _extract_value(
        vital_type: VitalSignType,
        vitals: Sequence[ProcessedVitalSign],
    ) -> float | None:
        """
        Extract the most recent within-bounds numeric value for a vital sign type.
        Returns None if no valid sample exists for the requested type.
        """
        candidates = [
            v
            for v in vitals
            if v.original.vital_sign_type is vital_type
            and v.is_within_physiological_bounds
        ]
        if not candidates:
            return None
        most_recent = max(candidates, key=lambda v: v.original.timestamp)
        return most_recent.cleaned_value

    @staticmethod
    def _extract_avpu(vitals: Sequence[ProcessedVitalSign]) -> AVPULevel:
        """
        Extract AVPU level. Defaults to ALERT when absent.
        ALERT is the conservative default — it contributes 0 points,
        never inflating the score beyond what is clinically supported.
        """
        candidates = [
            v
            for v in vitals
            if v.original.vital_sign_type is VitalSignType.CONSCIOUSNESS
            and v.original.avpu_level is not None
        ]
        if not candidates:
            return AVPULevel.ALERT
        most_recent = max(candidates, key=lambda v: v.original.timestamp)
        avpu = most_recent.original.avpu_level
        # Bandit B101 (assert_used): type-narrowing only -- `avpu` is
        # guaranteed non-None by the `and v.original.avpu_level is not None`
        # filter in the list comprehension above; this assert documents
        # that invariant for mypy, it is not the actual validation.
        assert avpu is not None  # nosec B101
        return avpu

    @staticmethod
    def _extract_on_supplemental_o2(vitals: Sequence[ProcessedVitalSign]) -> bool:
        """
        Returns True if patient is documented as receiving supplemental oxygen.
        Encoding: value 1.0 = on O2, value 0.0 = on room air.
        Default: False (room air) — conservative for Scale 1 patients
        (supplemental O2 adds +2; defaulting to False avoids false escalation).
        """
        candidates = [
            v
            for v in vitals
            if v.original.vital_sign_type is VitalSignType.SUPPLEMENTAL_O2
        ]
        if not candidates:
            return False
        most_recent = max(candidates, key=lambda v: v.original.timestamp)
        return most_recent.cleaned_value >= 0.5

    # ── NEWS2 Scoring Functions (RCP 2017 Table) ──────────────────────────────
    # Each function implements exactly one row of the RCP NEWS2 2017 scoring table.
    # Boundary values are inclusive on the stated side per the RCP table notation.

    @staticmethod
    def _score_respiratory_rate(rr: float) -> int:
        """
        RCP NEWS2 2017 Table: Respiration rate (breaths/min).

        ≤8  : 3 | 9–11  : 1 | 12–20 : 0 | 21–24 : 2 | ≥25 : 3

        ISO 14971 HAZARD-RR-001: Score 3 at ≤8 controls missed respiratory
        depression (e.g., opioid overdose, brainstem compromise).
        """
        if rr <= 8:
            return 3
        if rr <= 11:
            return 1
        if rr <= 20:
            return 0
        if rr <= 24:
            return 2
        return 3  # ≥25

    @staticmethod
    def _score_spo2(spo2: float, scale: SpO2Scale, on_o2: bool) -> int:
        """
        RCP NEWS2 2017 Table: SpO2 (%).

        Scale 1 (standard — all patients without confirmed hypercapnic failure):
            ≤91: 3 | 92–93: 2 | 94–95: 1 | ≥96: 0

        Scale 2 (hypercapnic respiratory failure e.g. COPD type 2 ONLY):
            ≤83: 3 | 84–85: 2 | 86–87: 1 | 88–92: 0
            93–94 on O2: 1 | 95–96 on O2: 2 | ≥97 on O2: 3

        ISO 14971 HAZARD-SPO2-001: Scale 1 applied to COPD patient causes
        underscoring by up to 3 points. Mitigation: clinician must explicitly
        assign Scale 2 via PatientContext — software cannot infer it from values.
        """
        if scale is SpO2Scale.SCALE_1:
            if spo2 <= 91:
                return 3
            if spo2 <= 93:
                return 2
            if spo2 <= 95:
                return 1
            return 0  # ≥96

        # Scale 2 (COPD / hypercapnic respiratory failure)
        if spo2 <= 83:
            return 3
        if spo2 <= 85:
            return 2
        if spo2 <= 87:
            return 1
        if spo2 <= 92:
            return 0  # Target range for COPD patients (88–92%) — on air or O2
        # SpO2 ≥ 93% on Scale 2: score depends on whether patient is on O2
        # (above target range for COPD on O2 = paradoxically high)
        if not on_o2:
            return 0  # ≥93% on room air for COPD — not abnormal
        if spo2 <= 94:
            return 1
        if spo2 <= 96:
            return 2
        return 3  # ≥97% on O2

    @staticmethod
    def _score_supplemental_o2(on_o2: bool) -> int:
        """
        RCP NEWS2 2017 Table: Air or Supplemental Oxygen.

        Supplemental O2: +2 | Room air: 0

        Applies to ALL patients on both scales.
        ISO 14971 HAZARD-O2-001: Supplemental O2 score compensates for the
        masking effect of O2 therapy on true SpO2 reserve.
        """
        return 2 if on_o2 else 0

    @staticmethod
    def _score_systolic_bp(sbp: float) -> int:
        """
        RCP NEWS2 2017 Table: Systolic blood pressure (mmHg).

        ≤90: 3 | 91–100: 2 | 101–110: 1 | 111–219: 0 | ≥220: 3

        ISO 14971 HAZARD-SBP-001: Score 3 at ≥220 controls hypertensive emergency.
        Score 3 at ≤90 controls hypotensive shock. Both carry equal clinical urgency.
        """
        if sbp <= 90:
            return 3
        if sbp <= 100:
            return 2
        if sbp <= 110:
            return 1
        if sbp <= 219:
            return 0
        return 3  # ≥220

    @staticmethod
    def _score_heart_rate(hr: float) -> int:
        """
        RCP NEWS2 2017 Table: Pulse rate (bpm).

        ≤40: 3 | 41–50: 1 | 51–90: 0 | 91–110: 1 | 111–130: 2 | ≥131: 3

        ISO 14971 HAZARD-HR-001: Non-monotonic scoring (1 at 41–50, then 0)
        reflects clinical reality: sinus bradycardia in athletes is normal.
        Test must explicitly verify the 41–50 range to prevent regression.
        """
        if hr <= 40:
            return 3
        if hr <= 50:
            return 1
        if hr <= 90:
            return 0
        if hr <= 110:
            return 1
        if hr <= 130:
            return 2
        return 3  # ≥131

    @staticmethod
    def _score_consciousness(avpu: AVPULevel) -> int:
        """
        RCP NEWS2 2017 Table: Level of consciousness (AVPU).

        Alert (A): 0 | Voice (V), Pain (P), Unresponsive (U), New Confusion (C): 3

        ISO 14971 HAZARD-CON-001: Any deviation from Alert is a safety-critical
        finding in the ICU context. The binary nature (0 or 3) reflects this.
        NEW_CONFUSION (C) was added in NEWS2 2017 — absent from original NEWS.
        """
        if avpu is AVPULevel.ALERT:
            return 0
        return 3

    @staticmethod
    def _score_temperature(temp_celsius: float) -> int:
        """
        RCP NEWS2 2017 Table: Temperature (°C).

        ≤35.0: 3 | 35.1–36.0: 1 | 36.1–38.0: 0 | 38.1–39.0: 1 | ≥39.1: 2

        ISO 14971 HAZARD-TEMP-001: Hypothermia (≤35.0) scores 3; max fever (≥39.1)
        scores only 2 because fever alone (without other derangements) is less
        acutely dangerous than profound hypothermia in the ICU context.
        """
        if temp_celsius <= 35.0:
            return 3
        if temp_celsius <= 36.0:
            return 1
        if temp_celsius <= 38.0:
            return 0
        if temp_celsius <= 39.0:
            return 1
        return 2  # ≥39.1
