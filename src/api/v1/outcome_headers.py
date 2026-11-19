"""Machine-readable scoring outcome headers shared by /ingest and /vitals (A6)."""

from __future__ import annotations

from domain.services.vitals_orchestrator import VitalsAnalysisResult


def outcome_headers(result: VitalsAnalysisResult) -> dict[str, str]:
    """
    X-Score-Outcome: scored | incomplete | critical
    X-Score-Reasons: comma-separated ReasonCode values (empty when none)

    HTTP status stays 200 for a valid, accepted message whatever the outcome
    (decision Q2, docs/assessment/PHASE1_DESIGN.md): rejecting it would drop data.
    """
    return {
        "X-Score-Outcome": result.assessment.outcome.value,
        "X-Score-Reasons": ",".join(result.assessment.reason_codes),
    }
