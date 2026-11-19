"""
Scoring outcome contract — the explicit result state used by every layer.

Phase 1 of the 2026-09 hardening programme (docs/assessment/PHASE1_DESIGN.md).
Replaces the old implicit contract ("news2_score is None, see free-text
warnings") with a machine-readable outcome plus reason codes.

Fail-safe policy (R7): missing, stale, ambiguous or out-of-range input yields
an explicit INCOMPLETE / OUT_OF_RANGE_CRITICAL state with reason codes —
never a reassuring default, never a silent drop.

Precedence: OUT_OF_RANGE_CRITICAL > INCOMPLETE > SCORED. Findings accumulate
regardless of the outcome, so one message can carry several reason codes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from domain.entities.vital_sign import VitalSignType


class ScoreOutcome(str, Enum):
    SCORED = "scored"
    INCOMPLETE = "incomplete"  # required input missing / stale / ambiguous
    OUT_OF_RANGE_CRITICAL = "critical"  # physiologically extreme — NOT an artifact


class ReasonCode(str, Enum):
    MISSING_CONSCIOUSNESS = "MISSING_CONSCIOUSNESS"
    MISSING_O2_STATUS = "MISSING_O2_STATUS"
    UNMAPPED_AVPU = "UNMAPPED_AVPU"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    UNPARSEABLE_TIMESTAMP = "UNPARSEABLE_TIMESTAMP"
    AMBIGUOUS_UNIT = "AMBIGUOUS_UNIT"
    UNRECOGNISED_CODE = "UNRECOGNISED_CODE"
    CRITICAL_VALUE_REVIEW_REQUIRED = "CRITICAL_VALUE_REVIEW_REQUIRED"
    CORRECTION_PENDING = "CORRECTION_PENDING"
    PRELIMINARY_RESULT = "PRELIMINARY_RESULT"
    BETWEEN_BANDS_VALUE = "BETWEEN_BANDS_VALUE"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    ARTIFACT_EXCLUDED = "ARTIFACT_EXCLUDED"
    STALENESS_POLICY_UNSET = "STALENESS_POLICY_UNSET"
    AMBIGUOUS_PATIENT_ID = "AMBIGUOUS_PATIENT_ID"
    UNSUPPORTED_MESSAGE_TYPE = "UNSUPPORTED_MESSAGE_TYPE"
    MISSING_RESULT_STATUS = "MISSING_RESULT_STATUS"
    NON_EXACT_VALUE = "NON_EXACT_VALUE"


# Findings that make a NEWS2 total untrustworthy: no score is computed while
# any of these is present. Every other code is informational (it is reported,
# but does not by itself withhold a score).
INCOMPLETE_CODES: frozenset[ReasonCode] = frozenset(
    {
        ReasonCode.MISSING_CONSCIOUSNESS,
        ReasonCode.MISSING_O2_STATUS,
        ReasonCode.UNMAPPED_AVPU,
        ReasonCode.STALE_OBSERVATION,
        ReasonCode.FUTURE_TIMESTAMP,
        ReasonCode.UNPARSEABLE_TIMESTAMP,
        ReasonCode.AMBIGUOUS_UNIT,
        ReasonCode.MISSING_PARAMETER,
        ReasonCode.STALENESS_POLICY_UNSET,
        ReasonCode.AMBIGUOUS_PATIENT_ID,
        ReasonCode.UNSUPPORTED_MESSAGE_TYPE,
        ReasonCode.NON_EXACT_VALUE,
    }
)


@dataclass(frozen=True)
class Finding:
    """One machine-readable reason. `detail` must never contain patient identifiers."""

    code: ReasonCode
    parameter: VitalSignType | None
    detail: str
    measured_value: float | None = None


@dataclass(frozen=True)
class ScoringAssessment:
    outcome: ScoreOutcome
    findings: tuple[Finding, ...]
    # Latest timestamp among the inputs actually used for scoring (A2): the
    # clinically meaningful effective time, not the time of calculation.
    observation_time: datetime | None = None

    @property
    def blocks_scoring(self) -> bool:
        return any(f.code in INCOMPLETE_CODES for f in self.findings)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f.code.value for f in self.findings))


def resolve_outcome(findings: tuple[Finding, ...]) -> ScoreOutcome:
    codes = {f.code for f in findings}
    if ReasonCode.CRITICAL_VALUE_REVIEW_REQUIRED in codes:
        return ScoreOutcome.OUT_OF_RANGE_CRITICAL
    if codes & INCOMPLETE_CODES:
        return ScoreOutcome.INCOMPLETE
    return ScoreOutcome.SCORED
