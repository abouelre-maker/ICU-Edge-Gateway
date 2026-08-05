"""
PatientContext Domain Entity.

IEC 62304 §5.2: Contextual metadata required for clinically correct NEWS2 scoring.
ISO 14971 HAZARD-SPO2-001: Applying Scale 1 to a known COPD patient causes
systematic NEWS2 underestimation — SpO2 target range differs by 6+ percentage points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SpO2Scale(str, Enum):
    """
    NEWS2 defines two mutually exclusive SpO2 scoring scales.

    RCP NEWS2 2017 §2.4: Scale 2 MUST only be used for patients with a confirmed
    diagnosis of hypercapnic respiratory failure (e.g., COPD type 2).
    A clinician must explicitly assign Scale 2 — it must NEVER be inferred
    from SpO2 values alone.

    ISO 14971 HAZARD-SPO2-001: Incorrect scale assignment is a patient safety
    defect. Default is SCALE_1 to ensure conservative (higher) scoring.
    """

    SCALE_1 = "SCALE_1"  # All patients — standard scale
    SCALE_2 = "SCALE_2"  # Confirmed hypercapnic respiratory failure ONLY


@dataclass(frozen=True)
class PatientContext:
    """
    Clinical context required for NEWS2 Score calculation.

    IEC 62304 REQ-CTX-001: Must be provided before NEWS2Calculator.calculate().
    FDA CDS: This context is set by clinicians — the software is advisory only.

    Attributes:
        patient_id:       FHIR Patient logical ID. Used in all FHIR resource references.
        spo2_scale:       SpO2 scoring scale (Scale 1 = default; Scale 2 = COPD only).
        encounter_id:     Optional FHIR Encounter ID for audit trail.
        assigned_at:      UTC timestamp when context was clinician-confirmed.
    """

    patient_id: str
    spo2_scale: SpO2Scale = SpO2Scale.SCALE_1
    encounter_id: str | None = None
    assigned_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def __post_init__(self) -> None:
        if not self.patient_id or not self.patient_id.strip():
            raise ValueError(
                "patient_id must be a non-empty string. "
                "All FHIR resources require a valid Patient logical ID."
            )