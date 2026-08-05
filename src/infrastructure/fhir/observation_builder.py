"""
FHIR R4 Observation Builder — Vital Sign Observations.

Converts ProcessedVitalSign domain objects into FHIR R4 Observation resources
with dual LOINC + SNOMED CT coding and UCUM units.

IEC 62304 §5.3: Builder pattern (GoF) — separates FHIR JSON construction from
domain logic. The domain layer has no knowledge of FHIR schemas.
ISO 14971 HAZARD-FHIR-001: Incorrect LOINC code causes downstream EHR to
misclassify the observation type, corrupting the clinical record.
Mitigation: _VITAL_SIGN_FHIR_MAP is the single source of truth for all codes.

FHIR R4 Conformance:
  - Vital signs profile: http://hl7.org/fhir/StructureDefinition/vitalsigns
  - Observation-status: 'final' for all adapter-produced observations
  - Category: vital-signs
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Final

from domain.entities.vital_sign import AVPULevel, VitalSignType
from domain.services.signal_processor import ProcessedVitalSign

# ── Coding Maps ───────────────────────────────────────────────────────────────

_LOINC_SYS: Final = "http://loinc.org"
_SNOMED_SYS: Final = "http://snomed.info/sct"
_UCUM_SYS: Final = "http://unitsofmeasure.org"
_OBS_CAT_SYS: Final = "http://terminology.hl7.org/CodeSystem/observation-category"
_VS_PROFILE: Final = "http://hl7.org/fhir/StructureDefinition/vitalsigns"
_IEC62304_EXT: Final = "https://samd.icu-edge/fhir/extensions/iec62304-software-version"
_OUTLIER_EXT: Final = "https://samd.icu-edge/fhir/extensions/dsp-outlier-count"
_ARTIFACT_EXT: Final = "https://samd.icu-edge/fhir/extensions/physiological-bounds-flag"

# Software version stamp injected into every Observation extension.
_SW_VERSION: Final = "1.0.0"

# Vital sign FHIR coding table.
# Each entry: (loinc_code, loinc_display, snomed_code, snomed_display, ucum_code, ucum_unit_display)
# ISO 14971 HAZARD-FHIR-001: These codes are the primary risk control for EHR interoperability.
_VITAL_SIGN_FHIR_MAP: Final[
    dict[VitalSignType, tuple[str, str, str, str, str, str]]
] = {
    VitalSignType.HEART_RATE: (
        "8867-4",
        "Heart rate",
        "364075005",
        "Heart rate (observable entity)",
        "/min",
        "beats/minute",
    ),
    VitalSignType.RESPIRATORY_RATE: (
        "9279-1",
        "Respiratory rate",
        "86290005",
        "Respiratory rate (observable entity)",
        "/min",
        "breaths/minute",
    ),
    VitalSignType.SPO2: (
        "59408-5",
        "Oxygen saturation in Arterial blood by Pulse oximetry",
        "431314004",
        "Peripheral oxygen saturation (observable entity)",
        "%",
        "%",
    ),
    VitalSignType.SYSTOLIC_BP: (
        "8480-6",
        "Systolic blood pressure",
        "271649006",
        "Systolic blood pressure (observable entity)",
        "mm[Hg]",
        "mmHg",
    ),
    VitalSignType.DIASTOLIC_BP: (
        "8462-4",
        "Diastolic blood pressure",
        "271650006",
        "Diastolic blood pressure (observable entity)",
        "mm[Hg]",
        "mmHg",
    ),
    VitalSignType.TEMPERATURE_CELSIUS: (
        "8310-5",
        "Body temperature",
        "276885007",
        "Core body temperature (observable entity)",
        "Cel",
        "°C",
    ),
    VitalSignType.CONSCIOUSNESS: (
        "67775-7",
        "Level of responsiveness",
        "248234008",
        "Neurological state finding (finding)",
        "",  # No UCUM unit for categorical value
        "",
    ),
    VitalSignType.SUPPLEMENTAL_O2: (
        "57834-7",
        "Oxygen therapy",
        "371825009",
        "Patient on oxygen (finding)",
        "",  # Boolean — no UCUM unit
        "",
    ),
}

# AVPU level → FHIR CodeableConcept (SNOMED CT).
# RCP NEWS2 2017 §1.4: AVPU is a categorical value, not numeric.
_AVPU_SNOMED: Final[dict[AVPULevel, tuple[str, str]]] = {
    AVPULevel.ALERT: ("248234008", "Alert (finding)"),
    AVPULevel.VOICE: ("304289007", "Responds to voice (finding)"),
    AVPULevel.PAIN: ("304290003", "Responds to pain (finding)"),
    AVPULevel.UNRESPONSIVE: ("422768004", "Unresponsive (finding)"),
    AVPULevel.NEW_CONFUSION: ("40917007", "Clouded consciousness (finding)"),
}


# ── Builder ────────────────────────────────────────────────────────────────────


class ObservationBuilder:
    """
    Converts a ProcessedVitalSign into a FHIR R4 Observation resource dict.

    Returns a plain Python dict (FHIR R4 JSON-serializable structure) rather
    than a fhir.resources model object, to decouple from library version changes.
    The dict can be passed directly to fhir.resources.Observation.model_validate()
    or serialised with json.dumps() for EHR API calls.

    IEC 62304 §5.3: Each build() call is stateless — safe for concurrent use.
    """

    def build(
        self,
        processed: ProcessedVitalSign,
        patient_id: str,
        device_id: str | None = None,
        encounter_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a FHIR R4 Observation resource for one processed vital sign.

        Args:
            processed:    DSP-cleaned vital sign from VitalSignProcessor.
            patient_id:   FHIR Patient logical ID (required for subject reference).
            device_id:    Optional FHIR Device logical ID.
            encounter_id: Optional FHIR Encounter logical ID.

        Returns:
            FHIR R4 Observation dict. If the VitalSignType has no FHIR mapping
            (should not occur given current enum), returns a minimal observation
            with a data-absent-reason extension.

        Raises:
            ValueError: If patient_id is empty.
        """
        if not patient_id or not patient_id.strip():
            raise ValueError(
                "patient_id must be non-empty. "
                "FHIR R4: Observation.subject is required for patient observations."
            )

        sample = processed.original
        vital_type = sample.vital_sign_type

        # Core Observation skeleton
        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "meta": {
                "profile": [_VS_PROFILE],
            },
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": _OBS_CAT_SYS,
                            "code": "vital-signs",
                            "display": "Vital Signs",
                        }
                    ]
                }
            ],
            "code": self._build_code(vital_type),
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": _format_fhir_datetime(sample.timestamp),
            "extension": self._build_extensions(processed),
        }

        # Optional references
        if device_id:
            obs["device"] = {"reference": f"Device/{device_id}"}
        if encounter_id:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}

        # Value: type-specific
        if not processed.is_within_physiological_bounds:
            obs["dataAbsentReason"] = {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
                        "code": "out-of-range",
                        "display": "Out of Range",
                    }
                ]
            }
        else:
            value_block = self._build_value(processed)
            if value_block:
                obs.update(value_block)

        return obs

    # ── Private: Code Construction ─────────────────────────────────────────────

    @staticmethod
    def _build_code(vital_type: VitalSignType) -> dict[str, Any]:
        """Build Observation.code with LOINC + SNOMED CT dual coding."""
        mapping = _VITAL_SIGN_FHIR_MAP.get(vital_type)
        if mapping is None:
            # Defensive fallback — should not occur with current VitalSignType enum
            return {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
                        "code": "unknown",
                    }
                ],
                "text": vital_type.value,
            }

        loinc_code, loinc_display, snomed_code, snomed_display, _, _ = mapping
        codings: list[dict[str, str]] = [
            {
                "system": _LOINC_SYS,
                "code": loinc_code,
                "display": loinc_display,
            }
        ]
        if snomed_code:
            codings.append(
                {
                    "system": _SNOMED_SYS,
                    "code": snomed_code,
                    "display": snomed_display,
                }
            )

        return {"coding": codings, "text": loinc_display}

    @staticmethod
    def _build_value(
        processed: ProcessedVitalSign,
    ) -> dict[str, Any] | None:
        """
        Build the value[x] block appropriate for the vital sign type.

        - CONSCIOUSNESS     → valueCodeableConcept (AVPU SNOMED CT)
        - SUPPLEMENTAL_O2  → valueBoolean
        - All others       → valueQuantity (UCUM)
        """
        sample = processed.original
        vital_type = sample.vital_sign_type
        mapping = _VITAL_SIGN_FHIR_MAP.get(vital_type)

        if vital_type is VitalSignType.CONSCIOUSNESS:
            avpu = sample.avpu_level
            if avpu is None:
                return None
            snomed_code, snomed_display = _AVPU_SNOMED.get(
                avpu, ("248234008", "Alert (finding)")
            )
            return {
                "valueCodeableConcept": {
                    "coding": [
                        {
                            "system": _SNOMED_SYS,
                            "code": snomed_code,
                            "display": snomed_display,
                        }
                    ],
                    "text": avpu.value,
                }
            }

        if vital_type is VitalSignType.SUPPLEMENTAL_O2:
            return {"valueBoolean": processed.cleaned_value >= 0.5}

        if mapping is None:
            return None

        _, _, _, _, ucum_code, ucum_display = mapping
        if not ucum_code:
            return None

        return {
            "valueQuantity": {
                "value": round(processed.cleaned_value, 4),
                "unit": ucum_display,
                "system": _UCUM_SYS,
                "code": ucum_code,
            }
        }

    @staticmethod
    def _build_extensions(processed: ProcessedVitalSign) -> list[dict[str, Any]]:
        """
        Build IEC 62304 + DSP audit extensions.

        Includes:
        - Software version (IEC 62304 traceability)
        - Outlier count (Hampel filter — number of replaced samples)
        - Physiological bounds flag (ISO 14971 HAZARD-BOUNDS-001)
        """
        extensions: list[dict[str, Any]] = [
            {
                "url": _IEC62304_EXT,
                "valueString": _SW_VERSION,
            },
            {
                "url": _OUTLIER_EXT,
                "valueInteger": processed.outlier_count,
            },
        ]
        if not processed.is_within_physiological_bounds:
            extensions.append(
                {
                    "url": _ARTIFACT_EXT,
                    "valueBoolean": True,
                }
            )
        return extensions


# ── Utility ────────────────────────────────────────────────────────────────────


def _format_fhir_datetime(dt: datetime) -> str:
    """
    Format a datetime to FHIR R4 dateTime string (ISO 8601 with timezone offset).
    FHIR R4 requires timezone offset — UTC 'Z' suffix is valid per spec.
    """
    # Convert to UTC if not already, then format
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


# ── Import fix ────────────────────────────────────────────────────────────────
from datetime import timezone  # noqa: E402  # Required by _format_fhir_datetime
