"""
VitalSign Domain Entities.

IEC 62304 §5.2: Immutable value objects — primary data artifacts of the pipeline.
ISO 14971: VitalSignType maps 1-to-1 with NEWS2 scoring parameters (Risk Register §3).
FDA CDS: Entities represent the clinical information layer per 21 CFR Part 880.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class VitalSignType(str, Enum):
    """
    NEWS2-aligned vital sign identifiers.

    IEC 62304 REQ-VITAL-001: Each value maps to exactly one NEWS2 component
    in the RCP 2017 clinical algorithm (ISBN 978-1-86016-693-6).
    Adding a new value here requires a corresponding NEWS2Calculator update
    and a new traceability entry in regulatory/risk_register.xlsx.
    """

    HEART_RATE = "HEART_RATE"  # NEWS2-P  : Pulse (bpm)
    RESPIRATORY_RATE = "RESPIRATORY_RATE"  # NEWS2-RR : Respirations/min
    SPO2 = "SPO2"  # NEWS2-O2 : Peripheral O2 sat (%)
    SYSTOLIC_BP = "SYSTOLIC_BP"  # NEWS2-BP : Systolic BP (mmHg)
    DIASTOLIC_BP = "DIASTOLIC_BP"  # Audit only — not in NEWS2
    TEMPERATURE_CELSIUS = "TEMPERATURE_CELSIUS"  # NEWS2-T  : Temperature (°C)
    CONSCIOUSNESS = "CONSCIOUSNESS"  # NEWS2-A  : AVPU level
    SUPPLEMENTAL_O2 = "SUPPLEMENTAL_O2"  # NEWS2-O2 : Air vs. O2 flag


class VitalSignUnit(str, Enum):
    """Clinical and SI units for FHIR UCUM encoding."""

    BPM = "bpm"
    BREATHS_PER_MIN = "breaths/min"
    PERCENT = "%"
    MMHG = "mmHg"
    CELSIUS = "Cel"  # UCUM canonical: "Cel" not "°C"
    FAHRENHEIT = "[degF]"  # UCUM canonical
    BOOLEAN = "bool"  # SUPPLEMENTAL_O2: 1.0 = on O2, 0.0 = on air
    AVPU_SCALE = "avpu"  # CONSCIOUSNESS: encoded via AVPULevel enum


class AVPULevel(str, Enum):
    """
    AVPU Scale — Level of Consciousness.

    RCP NEWS2 2017: Any deviation from Alert — including new confusion (C) —
    scores 3 points regardless of cause.
    ISO 14971 HAZARD-CON-001: Incorrect AVPU assignment causes NEWS2
    underestimation. Mitigation: explicit enum prevents free-text encoding.
    """

    ALERT = "A"
    VOICE = "V"
    PAIN = "P"
    UNRESPONSIVE = "U"
    NEW_CONFUSION = "C"  # Absent from original AVPU; added by NEWS2 2017


@dataclass(frozen=True)
class VitalSignSample:
    """
    Immutable snapshot of a single vital sign observation from an ICU monitor.

    IEC 62304 §5.2 REQ-VITAL-002: Primary data unit flowing through the pipeline.
    ISO 14971: Immutability prevents downstream accidental mutation of clinical values.

    For CONSCIOUSNESS samples: set avpu_level; value is ignored in scoring.
    For SUPPLEMENTAL_O2 samples: value = 1.0 (on O2) or 0.0 (on room air).
    For waveform samples (HL7 ED/NA OBX types): populate waveform + sampling_rate_hz.
    """

    vital_sign_type: VitalSignType
    value: float
    unit: VitalSignUnit
    timestamp: datetime  # MUST be timezone-aware (UTC)
    avpu_level: AVPULevel | None = None  # Required for CONSCIOUSNESS type
    waveform: tuple[float, ...] | None = None  # Raw waveform from HL7 ED/NA OBX
    sampling_rate_hz: float | None = None  # Required when waveform is set
    is_artifact_flagged: bool = False
    device_id: str | None = None  # FHIR Device/{id} reference

    def __post_init__(self) -> None:
        """
        Pre-condition guards.
        ISO 14971 HAZARD-TIME-001: Naive timestamps corrupt the audit trail.
        IEC 62304 REQ-VITAL-003: Waveform without rate is clinically unusable.
        """
        if self.timestamp.tzinfo is None:
            raise ValueError(
                "VitalSignSample.timestamp must be timezone-aware. "
                "Naive datetimes violate ISO 14971 HAZARD-TIME-001 "
                "(audit trail integrity). Use datetime.now(tz=timezone.utc)."
            )
        if self.waveform is not None and self.sampling_rate_hz is None:
            raise ValueError(
                "sampling_rate_hz is required when waveform data is present. "
                "IEC 62304 REQ-VITAL-003: unsampled waveform cannot be filtered."
            )
        if self.sampling_rate_hz is not None and self.sampling_rate_hz <= 0.0:
            raise ValueError(
                f"sampling_rate_hz must be a positive number. "
                f"Got {self.sampling_rate_hz!r}."
            )
        if (
            self.vital_sign_type is VitalSignType.CONSCIOUSNESS
            and self.avpu_level is None
        ):
            raise ValueError(
                "VitalSignSample with type CONSCIOUSNESS must set avpu_level. "
                "ISO 14971 HAZARD-CON-001: missing AVPU causes scoring error."
            )
