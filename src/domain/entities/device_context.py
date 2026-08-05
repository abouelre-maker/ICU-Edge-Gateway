"""
DeviceContext Domain Entity.

IEC 62304 §5.2: Device metadata required for HL7 v2.x parsing and
FHIR Device reference population.
ISO 14971 HAZARD-PROTO-001: Incorrect vendor identification causes
HL7 segment parsing failures and silent data loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MonitorVendor(str, Enum):
    """
    ICU monitor vendors whose HL7 v2.x dialects are explicitly supported.

    IEC 62304: SOUP declaration — each vendor produces HL7 v2.x with
    non-standard extensions. Parser behavior varies per vendor.
    ISO 14971 HAZARD-PROTO-001: Unknown vendor → GENERIC fallback parser;
    non-standard OBX segments may be silently dropped.
    """

    PHILIPS = "PHILIPS"          # IntelliVue series (MX/MP/MX800)
    GE = "GE"                    # CARESCAPE B series
    DRAEGER = "DRAEGER"          # Infinity series
    MINDRAY = "MINDRAY"          # Beneview/ePM series
    NIHON_KOHDEN = "NIHON_KOHDEN"
    GENERIC = "GENERIC"          # Fallback — standard ORU^R01 only


class HL7Version(str, Enum):
    """HL7 v2.x versions observed in North American ICU environments."""

    V2_3 = "2.3"    # Legacy — still common in older Philips/GE devices
    V2_3_1 = "2.3.1"
    V2_4 = "2.4"
    V2_5 = "2.5"
    V2_5_1 = "2.5.1"  # Most common in US hospitals
    V2_6 = "2.6"
    V2_8 = "2.8"      # Emerging in newer deployments


@dataclass(frozen=True)
class DeviceContext:
    """
    Metadata about the source ICU monitor.

    IEC 62304 REQ-DEV-001: Required by HL7Adapter to select the correct
    vendor-specific parsing strategy (GoF Strategy pattern).
    FHIR: Populates Device.manufacturer and Device.model in the FHIR Bundle.
    """

    device_id: str                             # FHIR Device logical ID
    vendor: MonitorVendor
    model: str                                 # e.g., "IntelliVue MX800"
    hl7_version: HL7Version = HL7Version.V2_5_1
    location: str | None = None                # e.g., "ICU-BED-07-A"
    firmware_version: str | None = None

    def __post_init__(self) -> None:
        if not self.device_id or not self.device_id.strip():
            raise ValueError(
                "device_id must be a non-empty string. "
                "IEC 62304 REQ-DEV-001: FHIR Device reference requires valid ID."
            )