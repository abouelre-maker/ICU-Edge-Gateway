"""
NEWS2Score Domain Entities.

Clinical Reference: Royal College of Physicians. National Early Warning Score (NEWS) 2.
London: RCP, December 2017. ISBN 978-1-86016-693-6.

IEC 62304 §5.2: Core output entity of the NEWS2Calculator service.
ISO 14971 HAZARD-NEWS2-001: This entity is read-only; its risk_level property
drives clinical escalation recommendations. Mutation is prevented by frozen=True.
FDA CDS: Output must be displayed to clinician for independent review —
software does NOT trigger automated treatment (CDS Non-Device Exemption criteria).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class NEWS2RiskLevel(str, Enum):
    """
    Clinical risk classification derived from total NEWS2 score.

    RCP NEWS2 2017 §3 (Response thresholds):
        NORMAL     → Score 0       : Minimum 12-hourly monitoring
        LOW        → Score 1-4     : Minimum 12-hourly monitoring
        LOW_MEDIUM → Score 3 (single parameter = 3, total < 5)
                                   : Minimum 1-hourly monitoring
        MEDIUM     → Score 5-6     : Urgent assessment required
        HIGH       → Score ≥7      : Emergency response required

    ISO 14971 HAZARD-NEWS2-002: Downgrading a HIGH to MEDIUM is a
    patient safety critical defect. All risk_level property logic
    is verified by tests/regulatory/test_news2_safety.py.
    """

    NORMAL = "NORMAL"
    LOW = "LOW"
    LOW_MEDIUM = "LOW_MEDIUM"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class NEWS2Score:
    """
    Immutable aggregate of all seven NEWS2 component scores.

    IEC 62304 §5.2 REQ-NEWS2-001: Each component score field is independently
    testable and traceable to a specific RCP 2017 scoring table row.

    ISO 14971 HAZARD-NEWS2-001: total and risk_level are derived properties —
    they cannot be set independently, preventing score manipulation.

    Component score ranges (RCP 2017):
        resp_rate_score       : 0, 1, 2, 3
        spo2_score            : 0, 1, 2, 3
        supplemental_o2_score : 0 or 2 (binary)
        systolic_bp_score     : 0, 1, 2, 3
        heart_rate_score      : 0, 1, 2, 3
        consciousness_score   : 0 or 3 (binary: Alert vs. any deviation)
        temperature_score     : 0, 1, 2, 3
    """

    resp_rate_score: int
    spo2_score: int
    supplemental_o2_score: int
    systolic_bp_score: int
    heart_rate_score: int
    consciousness_score: int
    temperature_score: int
    calculated_at: datetime

    def __post_init__(self) -> None:
        self._validate_component_ranges()

    def _validate_component_ranges(self) -> None:
        """
        IEC 62304 REQ-NEWS2-002: Component scores must be within RCP 2017 bounds.
        ISO 14971: Out-of-range scores indicate algorithmic defects.
        """
        valid_standard = {0, 1, 2, 3}
        valid_binary = {0, 2}
        valid_consciousness = {0, 3}

        checks: list[tuple[str, int, set[int]]] = [
            ("resp_rate_score", self.resp_rate_score, valid_standard),
            ("spo2_score", self.spo2_score, valid_standard),
            ("supplemental_o2_score", self.supplemental_o2_score, valid_binary),
            ("systolic_bp_score", self.systolic_bp_score, valid_standard),
            ("heart_rate_score", self.heart_rate_score, valid_standard),
            ("consciousness_score", self.consciousness_score, valid_consciousness),
            ("temperature_score", self.temperature_score, valid_standard),
        ]
        for field_name, value, valid_set in checks:
            if value not in valid_set:
                raise ValueError(
                    f"NEWS2Score.{field_name} = {value!r} is outside the valid "
                    f"RCP 2017 range {sorted(valid_set)}. "
                    "IEC 62304 REQ-NEWS2-002: Component score integrity violated."
                )

    @property
    def total(self) -> int:
        """
        Aggregate NEWS2 score (sum of all 7 components).
        RCP NEWS2 2017: Total range is 0–20 (theoretical maximum).
        """
        return (
            self.resp_rate_score
            + self.spo2_score
            + self.supplemental_o2_score
            + self.systolic_bp_score
            + self.heart_rate_score
            + self.consciousness_score
            + self.temperature_score
        )

    @property
    def has_extreme_single_parameter(self) -> bool:
        """
        True when ANY single clinical parameter scores 3 points.

        RCP NEWS2 2017 §3: A score of 3 in any single parameter triggers
        LOW_MEDIUM risk level regardless of total score.
        Note: supplemental_o2_score (max=2) is excluded — cannot reach 3.
        """
        return any(
            score == 3
            for score in [
                self.resp_rate_score,
                self.spo2_score,
                self.systolic_bp_score,
                self.heart_rate_score,
                self.consciousness_score,
                self.temperature_score,
            ]
        )

    @property
    def risk_level(self) -> NEWS2RiskLevel:
        """
        Clinical risk classification per RCP NEWS2 2017 §3 response thresholds.

        ISO 14971 HAZARD-NEWS2-002: This property is the primary safety-critical
        output. All branches are verified in tests/regulatory/test_news2_safety.py.
        FDA CDS: Result is advisory — clinician review is mandatory before action.

        Priority order (from most to least urgent):
            1. Total ≥ 7   → HIGH (emergency response)
            2. Total ≥ 5   → MEDIUM (urgent assessment)
            3. Any single parameter = 3 → LOW_MEDIUM (1-hourly monitoring)
            4. Total 1-4   → LOW (12-hourly monitoring)
            5. Total 0     → NORMAL (routine monitoring)
        """
        t = self.total
        if t >= 7:
            return NEWS2RiskLevel.HIGH
        if t >= 5:
            return NEWS2RiskLevel.MEDIUM
        if self.has_extreme_single_parameter:
            return NEWS2RiskLevel.LOW_MEDIUM
        if t >= 1:
            return NEWS2RiskLevel.LOW
        return NEWS2RiskLevel.NORMAL

    @classmethod
    def zero(cls) -> "NEWS2Score":
        """
        Factory: a fully-normal NEWS2Score (all parameters within target range).
        Useful as a safe default in test fixtures.
        """
        return cls(
            resp_rate_score=0,
            spo2_score=0,
            supplemental_o2_score=0,
            systolic_bp_score=0,
            heart_rate_score=0,
            consciousness_score=0,
            temperature_score=0,
            calculated_at=datetime.now(tz=timezone.utc),
        )