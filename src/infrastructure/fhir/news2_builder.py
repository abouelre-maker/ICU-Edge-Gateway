"""
FHIR R4 NEWS2 Score Observation Builder.

Converts a NEWS2Score domain entity into a FHIR R4 Observation resource
with seven component sub-observations, one per NEWS2 scoring parameter.

Clinical reference: RCP NEWS2 2017.
FHIR primary code: SNOMED CT 1239842005 (National Early Warning Score 2).
LOINC panel: Component codes align with individual vital sign LOINC codes.

IEC 62304 §5.3: Builder pattern — FHIR schema knowledge is contained here only.
ISO 14971 HAZARD-FHIR-002: Incorrect NEWS2 FHIR encoding causes downstream
CDSS to misread the total score. Mitigation: total in valueInteger (integer,
not float) with component observations for full transparency.
FDA CDS Non-Device: FHIR output must include note that this is advisory only.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from domain.entities.news2_score import NEWS2RiskLevel, NEWS2Score

from infrastructure.fhir.observation_builder import (
    _LOINC_SYS,
    _SNOMED_SYS,
    _format_fhir_datetime,
)

# NEWS2 primary FHIR coding
_NEWS2_SNOMED_CODE: Final = "1239842005"
_NEWS2_SNOMED_DISPLAY: Final = "National Early Warning Score 2 (assessment scale)"
_NEWS2_CAT_SYS: Final = "http://terminology.hl7.org/CodeSystem/observation-category"

# Risk level → FHIR interpretation code (HL7 V3 ObservationInterpretation)
_RISK_INTERPRETATION: Final[dict[NEWS2RiskLevel, tuple[str, str]]] = {
    NEWS2RiskLevel.NORMAL: ("N", "Normal"),
    NEWS2RiskLevel.LOW: ("L", "Low"),
    NEWS2RiskLevel.LOW_MEDIUM: ("A", "Abnormal"),  # Closest HL7 standard code
    NEWS2RiskLevel.MEDIUM: ("H", "High"),
    NEWS2RiskLevel.HIGH: ("HH", "Critical high"),
}

# NEWS2 component code definitions:
# (component_id, loinc_code, loinc_display, snomed_code, snomed_display)
_COMPONENT_CODES: Final[list[tuple[str, str, str, str, str]]] = [
    (
        "resp_rate",
        "9279-1",
        "Respiratory rate",
        "86290005",
        "Respiratory rate (observable entity)",
    ),
    (
        "spo2",
        "59408-5",
        "Oxygen saturation in Arterial blood by Pulse oximetry",
        "431314004",
        "Peripheral oxygen saturation (observable entity)",
    ),
    (
        "supplemental_o2",
        "57834-7",
        "Oxygen therapy",
        "371825009",
        "Patient on oxygen (finding)",
    ),
    (
        "systolic_bp",
        "8480-6",
        "Systolic blood pressure",
        "271649006",
        "Systolic blood pressure (observable entity)",
    ),
    (
        "heart_rate",
        "8867-4",
        "Heart rate",
        "364075005",
        "Heart rate (observable entity)",
    ),
    (
        "consciousness",
        "67775-7",
        "Level of responsiveness",
        "248234008",
        "Neurological state finding (finding)",
    ),
    (
        "temperature",
        "8310-5",
        "Body temperature",
        "276885007",
        "Core body temperature (observable entity)",
    ),
]

# NEWS2 risk level extension URL
_RISK_LEVEL_EXT: Final = "https://samd.icu-edge/fhir/extensions/news2-risk-level"
_FDA_CDS_EXT: Final = "https://samd.icu-edge/fhir/extensions/cds-advisory-only"
_IEC62304_EXT: Final = "https://samd.icu-edge/fhir/extensions/iec62304-software-version"
_SW_VERSION: Final = "1.0.0"


class NEWS2ObservationBuilder:
    """
    Converts a NEWS2Score into a FHIR R4 Observation with component sub-scores.

    The resulting resource:
    - Uses SNOMED CT 1239842005 as the primary observation code
    - Carries total score in valueInteger
    - Exposes each of the 7 component scores in Observation.component[]
    - Includes risk level as a custom extension (display use only)
    - Carries the FDA CDS advisory-only flag (for Non-Device exemption audit trail)

    IEC 62304 §5.3: All FHIR schema knowledge in this class only.
    ISO 14971 HAZARD-FHIR-002: Integer total prevents rounding errors that
    would corrupt downstream risk level derivation.
    """

    def build(
        self,
        score: NEWS2Score,
        patient_id: str,
        device_id: str | None = None,
        encounter_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a FHIR R4 Observation for a complete NEWS2 Score.

        Args:
            score:        Immutable NEWS2Score from NEWS2Calculator.
            patient_id:   FHIR Patient logical ID.
            device_id:    Optional FHIR Device reference.
            encounter_id: Optional FHIR Encounter reference.

        Returns:
            FHIR R4 Observation dict with seven component scores.

        Raises:
            ValueError: If patient_id is empty.
        """
        if not patient_id or not patient_id.strip():
            raise ValueError(
                "patient_id must be non-empty for NEWS2 FHIR Observation. "
                "FHIR R4: Observation.subject is required."
            )

        interpretation_code, interpretation_display = _RISK_INTERPRETATION[
            score.risk_level
        ]

        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": _NEWS2_CAT_SYS,
                            "code": "survey",
                            "display": "Survey",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": _SNOMED_SYS,
                        "code": _NEWS2_SNOMED_CODE,
                        "display": _NEWS2_SNOMED_DISPLAY,
                    }
                ],
                "text": "National Early Warning Score 2 (NEWS2)",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": _format_fhir_datetime(score.calculated_at),
            "valueInteger": score.total,
            "interpretation": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                            "code": interpretation_code,
                            "display": interpretation_display,
                        }
                    ],
                    "text": score.risk_level.value,
                }
            ],
            "component": self._build_components(score),
            "extension": [
                {
                    "url": _RISK_LEVEL_EXT,
                    "valueCode": score.risk_level.value,
                },
                {
                    "url": _IEC62304_EXT,
                    "valueString": _SW_VERSION,
                },
                {
                    # FDA CDS Non-Device Exemption audit trail.
                    # All NEWS2 outputs are advisory — clinician review required.
                    "url": _FDA_CDS_EXT,
                    "valueBoolean": True,
                },
            ],
            "note": [
                {
                    "text": (
                        "NEWS2 score calculated per RCP 2017 guidelines. "
                        "This is a clinical decision support advisory output only. "
                        "Independent clinician review is required before any action."
                    )
                }
            ],
        }

        if device_id:
            obs["device"] = {"reference": f"Device/{device_id}"}
        if encounter_id:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}

        return obs

    # ── Private: Component Sub-Observations ───────────────────────────────────

    @staticmethod
    def _build_components(score: NEWS2Score) -> list[dict[str, Any]]:
        """
        Build the 7 NEWS2 component sub-score observations.

        Each component has:
        - code: LOINC + SNOMED for the clinical parameter
        - valueInteger: the 0–3 score for that parameter
        RCP NEWS2 2017: Component scores enable retrospective audit of how
        the total was reached — critical for clinical governance.
        """
        # Map component_id → score value
        score_values: dict[str, int] = {
            "resp_rate": score.resp_rate_score,
            "spo2": score.spo2_score,
            "supplemental_o2": score.supplemental_o2_score,
            "systolic_bp": score.systolic_bp_score,
            "heart_rate": score.heart_rate_score,
            "consciousness": score.consciousness_score,
            "temperature": score.temperature_score,
        }

        components: list[dict[str, Any]] = []
        for (
            comp_id,
            loinc_code,
            loinc_display,
            snomed_code,
            snomed_display,
        ) in _COMPONENT_CODES:
            components.append(
                {
                    "code": {
                        "coding": [
                            {
                                "system": _LOINC_SYS,
                                "code": loinc_code,
                                "display": loinc_display,
                            },
                            {
                                "system": _SNOMED_SYS,
                                "code": snomed_code,
                                "display": snomed_display,
                            },
                        ],
                        "text": loinc_display,
                    },
                    "valueInteger": score_values[comp_id],
                }
            )

        return components
