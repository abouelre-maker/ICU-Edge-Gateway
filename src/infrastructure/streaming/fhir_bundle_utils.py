"""
Shared FHIR Bundle helpers for the streaming layer.

Small, dependency-free utilities used by more than one streaming component
(MQTTPublisher topic routing, LiveDashboardChannel delta envelopes) so the
same "how do I read a patient/NEWS2 summary back out of an assembled Bundle"
logic isn't duplicated across them.
"""

from __future__ import annotations

from typing import Any


def extract_patient_id(bundle: dict[str, Any]) -> str:
    """
    Best-effort extraction of the FHIR Patient logical ID from a Bundle.

    Every Observation entry carries `subject: {"reference": "Patient/{id}"}`
    (see infrastructure/fhir/observation_builder.py) — the first one found is
    authoritative, since all entries in one Bundle share the same subject.
    Falls back to "UNKNOWN" for an empty/malformed Bundle rather than
    raising — a routing/lookup failure must never be allowed to drop
    telemetry that already passed the domain pipeline.
    """
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        reference = resource.get("subject", {}).get("reference", "")
        if reference.startswith("Patient/"):
            return reference.removeprefix("Patient/")
    return "UNKNOWN"


_NEWS2_SNOMED_CODE: str = "1239842005"  # infrastructure/fhir/news2_builder.py
_NEWS2_RISK_LEVEL_EXT: str = "https://samd.icu-edge/fhir/extensions/news2-risk-level"


def extract_news2_summary(bundle: dict[str, Any]) -> dict[str, Any] | None:
    """
    Best-effort extraction of a compact NEWS2 summary from a Bundle, for
    dashboard delta payloads that want the score without the caller having
    to walk the full FHIR Observation structure.

    Identifies the NEWS2 Observation entry built by
    infrastructure/fhir/news2_builder.py by its primary SNOMED CT code
    (1239842005 — "National Early Warning Score 2 (assessment scale)");
    total score is `valueInteger`, risk level is the `news2-risk-level`
    extension's `valueCode`. Returns None if no NEWS2 Observation is
    present (e.g. incomplete vitals) rather than raising — this is a
    display convenience, not clinical data in its own right; the full
    Bundle in the delta remains authoritative.
    """
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") != "Observation":
            continue
        codings = resource.get("code", {}).get("coding", [])
        if not any(c.get("code") == _NEWS2_SNOMED_CODE for c in codings):
            continue
        total = resource.get("valueInteger")
        risk_level = None
        for ext in resource.get("extension", []):
            if ext.get("url") == _NEWS2_RISK_LEVEL_EXT:
                risk_level = ext.get("valueCode")
        return {"total": total, "risk_level": risk_level}
    return None
