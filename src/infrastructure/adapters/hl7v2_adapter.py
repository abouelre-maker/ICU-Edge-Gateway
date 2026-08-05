"""
HL7 v2.x ORU^R01 Adapter — ICU Monitor Protocol Bridge.

Bridges the legacy HL7 v2.x wire protocol (dominant in 80%+ of North American
hospitals) to the domain's VitalSignSample entities.

Supported protocol variants:
  - HL7 v2.3 – v2.8 ORU^R01 messages
  - OBX value types: NM (Numeric), ST (String), SN (Structured Numeric)
  - NA (Numeric Array) waveform: detected and skipped with audit warning
  - Vendor dialects: Philips IntelliVue / GE CARESCAPE / Dräger Infinity /
    Mindray Beneview / Nihon Kohden / Generic (LOINC fallback)

IEC 62304 §5.3: GoF Adapter pattern — isolates legacy protocol complexity
from the pure domain model.
ISO 14971 HAZARD-PROTO-001: Vendor dialect misidentification silently drops OBX
segments. Mitigation: explicit MSH-3 vendor map + LOINC fallback for all OBX-3
identifiers.
SOUP: hl7apy==1.3.4 — version pinned in requirements.txt per IEC 62304 §8.1.2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

import structlog
from hl7apy.parser import parse_message as _hl7apy_parse

from domain.entities.device_context import DeviceContext, MonitorVendor
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)

_log: structlog.BoundLogger = structlog.get_logger(__name__)

# ── Code Mapping Tables ────────────────────────────────────────────────────────

# LOINC observation identifiers → VitalSignType.
# Source: LOINC.org — codes validated against NLM VSAC value sets.
_LOINC_TO_TYPE: Final[dict[str, VitalSignType]] = {
    "8867-4": VitalSignType.HEART_RATE,          # Heart rate
    "59408-5": VitalSignType.SPO2,               # SpO2 by pulse ox
    "2708-6": VitalSignType.SPO2,                # Oxygen saturation (alternate)
    "9279-1": VitalSignType.RESPIRATORY_RATE,    # Respiratory rate
    "8480-6": VitalSignType.SYSTOLIC_BP,         # Systolic BP
    "8462-4": VitalSignType.DIASTOLIC_BP,        # Diastolic BP
    "8310-5": VitalSignType.TEMPERATURE_CELSIUS, # Body temperature
    "67775-7": VitalSignType.CONSCIOUSNESS,      # Level of responsiveness
    "76270-8": VitalSignType.CONSCIOUSNESS,      # AVPU score
    "57834-7": VitalSignType.SUPPLEMENTAL_O2,    # Oxygen therapy
    "3151-8": VitalSignType.SUPPLEMENTAL_O2,     # Inhaled O2 flow rate
}

# Vendor-specific proprietary OBX-3 identifiers → VitalSignType.
# Covers Philips IntelliVue (MX/MP series), GE CARESCAPE B/DASH,
# Dräger Infinity, Mindray Beneview, and Nihon Kohden.
# ISO 14971 HAZARD-PROTO-001: Unlisted codes → type=None → OBX skipped.
_VENDOR_TO_TYPE: Final[dict[str, VitalSignType]] = {
    # Heart Rate
    "HR": VitalSignType.HEART_RATE,
    "PULSE": VitalSignType.HEART_RATE,
    "HEART RATE": VitalSignType.HEART_RATE,
    "PR": VitalSignType.HEART_RATE,              # Pulse Rate (GE)
    # SpO2
    "SPO2": VitalSignType.SPO2,
    "SO2": VitalSignType.SPO2,
    "SAO2": VitalSignType.SPO2,
    "STO2": VitalSignType.SPO2,
    "SPO2-%": VitalSignType.SPO2,
    # Respiratory Rate
    "RESP": VitalSignType.RESPIRATORY_RATE,
    "RR": VitalSignType.RESPIRATORY_RATE,
    "RESPRATE": VitalSignType.RESPIRATORY_RATE,
    # Systolic BP (NIBP = Non-Invasive, ABP = Arterial)
    "NIBP-S": VitalSignType.SYSTOLIC_BP,
    "NIBP_S": VitalSignType.SYSTOLIC_BP,
    "NBP-S": VitalSignType.SYSTOLIC_BP,
    "NBP_S": VitalSignType.SYSTOLIC_BP,
    "SBP": VitalSignType.SYSTOLIC_BP,
    "ABP-S": VitalSignType.SYSTOLIC_BP,
    "ART-S": VitalSignType.SYSTOLIC_BP,
    # Diastolic BP
    "NIBP-D": VitalSignType.DIASTOLIC_BP,
    "NIBP_D": VitalSignType.DIASTOLIC_BP,
    "NBP-D": VitalSignType.DIASTOLIC_BP,
    "NBP_D": VitalSignType.DIASTOLIC_BP,
    "DBP": VitalSignType.DIASTOLIC_BP,
    "ABP-D": VitalSignType.DIASTOLIC_BP,
    "ART-D": VitalSignType.DIASTOLIC_BP,
    # Temperature
    "TEMP": VitalSignType.TEMPERATURE_CELSIUS,
    "T1": VitalSignType.TEMPERATURE_CELSIUS,
    "T2": VitalSignType.TEMPERATURE_CELSIUS,
    "TEMPBLA": VitalSignType.TEMPERATURE_CELSIUS, # Bladder temp (Philips)
    "TEMPCORE": VitalSignType.TEMPERATURE_CELSIUS,
    # Consciousness (AVPU)
    "AVPU": VitalSignType.CONSCIOUSNESS,
    "LOC": VitalSignType.CONSCIOUSNESS,
    "CONS": VitalSignType.CONSCIOUSNESS,
    # Supplemental O2
    "FIO2": VitalSignType.SUPPLEMENTAL_O2,        # FiO2 > 0.21 = on O2
    "O2FLOW": VitalSignType.SUPPLEMENTAL_O2,
    "O2DELIVERY": VitalSignType.SUPPLEMENTAL_O2,
    "AIROROXYGEN": VitalSignType.SUPPLEMENTAL_O2,
}

# MSH-3 Sending Application → MonitorVendor.
# Case-insensitive substring match against upper-cased MSH-3 value.
_VENDOR_SUBSTRINGS: Final[list[tuple[str, MonitorVendor]]] = [
    ("PHILIPS", MonitorVendor.PHILIPS),
    ("INTELLIVUE", MonitorVendor.PHILIPS),
    ("ISL", MonitorVendor.PHILIPS),       # Philips Information System Link
    ("CARESCAPE", MonitorVendor.GE),
    ("GE ", MonitorVendor.GE),            # Trailing space avoids matching "GENERAL"
    ("DASH", MonitorVendor.GE),
    ("DRAEGER", MonitorVendor.DRAEGER),
    ("DRAGER", MonitorVendor.DRAEGER),
    ("INFINITY", MonitorVendor.DRAEGER),
    ("MINDRAY", MonitorVendor.MINDRAY),
    ("BENEVIEW", MonitorVendor.MINDRAY),
    ("NIHON", MonitorVendor.NIHON_KOHDEN),
]

# AVPU string values from OBX-5 (ST type) → AVPULevel.
# Covers full text, abbreviations, and common misspellings from monitors.
_AVPU_STRINGS: Final[dict[str, AVPULevel]] = {
    "A": AVPULevel.ALERT,
    "ALERT": AVPULevel.ALERT,
    "AWAKE": AVPULevel.ALERT,
    "V": AVPULevel.VOICE,
    "VOICE": AVPULevel.VOICE,
    "RESPONDS TO VOICE": AVPULevel.VOICE,
    "P": AVPULevel.PAIN,
    "PAIN": AVPULevel.PAIN,
    "RESPONDS TO PAIN": AVPULevel.PAIN,
    "U": AVPULevel.UNRESPONSIVE,
    "UNRESPONSIVE": AVPULevel.UNRESPONSIVE,
    "C": AVPULevel.NEW_CONFUSION,
    "CONFUSION": AVPULevel.NEW_CONFUSION,
    "CONFUSED": AVPULevel.NEW_CONFUSION,
    "NEW CONFUSION": AVPULevel.NEW_CONFUSION,
    "NEW_CONFUSION": AVPULevel.NEW_CONFUSION,
    "ACVPU-C": AVPULevel.NEW_CONFUSION,
}

# VitalSignType → default VitalSignUnit when OBX-6 is absent or unmapped.
_DEFAULT_UNIT: Final[dict[VitalSignType, VitalSignUnit]] = {
    VitalSignType.HEART_RATE: VitalSignUnit.BPM,
    VitalSignType.RESPIRATORY_RATE: VitalSignUnit.BREATHS_PER_MIN,
    VitalSignType.SPO2: VitalSignUnit.PERCENT,
    VitalSignType.SYSTOLIC_BP: VitalSignUnit.MMHG,
    VitalSignType.DIASTOLIC_BP: VitalSignUnit.MMHG,
    VitalSignType.TEMPERATURE_CELSIUS: VitalSignUnit.CELSIUS,
    VitalSignType.CONSCIOUSNESS: VitalSignUnit.AVPU_SCALE,
    VitalSignType.SUPPLEMENTAL_O2: VitalSignUnit.BOOLEAN,
}


# ── Data Transfer Object ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class HL7ParseResult:
    """
    Immutable result of parsing one HL7 v2.x ORU^R01 message.

    IEC 62304 §5.8: Primary output of the HL7 adapter layer.
    Attributes:
        samples:            Parsed VitalSignSample objects (one per valid OBX).
        patient_id:         Extracted from PID-3; "UNKNOWN" if absent.
        detected_vendor:    MonitorVendor from MSH-3 or device_context.
        message_timestamp:  MSH-7 timestamp (UTC); now() if absent.
        skipped_obx_count:  OBX segments skipped due to unknown type or error.
        parse_warnings:     Ordered audit log from parsing.
    """

    samples: tuple[VitalSignSample, ...]
    patient_id: str
    detected_vendor: MonitorVendor
    message_timestamp: datetime
    skipped_obx_count: int
    parse_warnings: tuple[str, ...]


# ── Adapter Implementation ─────────────────────────────────────────────────────


class HL7v2Adapter:
    """
    Parses HL7 v2.x ORU^R01 messages from ICU monitors into VitalSignSample lists.

    IEC 62304 §5.3: GoF Adapter — bridges hl7apy (SOUP) to domain entities.
    ISO 14971 HAZARD-PROTO-001: all code-mapping decisions are explicit and audited.
    Design guarantee: never raises on a single bad OBX segment — skips + warns.
    Only raises ValueError when the entire HL7 message is syntactically invalid.
    """

    def parse(
        self,
        raw_hl7: str,
        device_context: DeviceContext | None = None,
    ) -> HL7ParseResult:
        """
        Parse a raw HL7 v2.x ORU^R01 message into VitalSignSamples.

        Args:
            raw_hl7:        Raw HL7 string. Accepts \\r, \\n, or \\r\\n line endings.
            device_context: Optional pre-configured device context.
                            If provided, vendor is taken from context (not MSH-3).

        Returns:
            HL7ParseResult — always returned, even with partial OBX failures.

        Raises:
            ValueError: If hl7apy cannot parse the message at all.
        """
        # Normalise line endings — HL7 canonical separator is CR (\r)
        normalised = raw_hl7.replace("\r\n", "\r").replace("\n", "\r")

        try:
            msg = _hl7apy_parse(
                normalised,
                find_groups=False,
                force_validation=False,
            )
        except Exception as exc:
            raise ValueError(
                f"hl7apy cannot parse the supplied HL7 message: {exc}. "
                "IEC 62304 REQ-HL7-001: input must be valid HL7 v2.x ORU^R01."
            ) from exc

        warnings: list[str] = []

        # ── Message-Level Metadata ─────────────────────────────────────────────
        msg_ts = self._extract_message_timestamp(msg)
        patient_id = self._extract_patient_id(msg, warnings)
        vendor = (
            device_context.vendor
            if device_context is not None
            else self._detect_vendor(msg)
        )
        device_id = device_context.device_id if device_context else "UNKNOWN"

        log = _log.bind(patient_id=patient_id, vendor=vendor.value, device_id=device_id)
        log.info("hl7v2_adapter.parse.start")

        # ── OBX Segment Iteration ──────────────────────────────────────────────
        samples: list[VitalSignSample] = []
        skipped = 0

        for child in msg.children:
            seg_name = getattr(child, "name", "").upper()
            if seg_name != "OBX":
                continue

            try:
                sample = self._parse_obx(
                    obx=child,
                    vendor=vendor,
                    device_id=device_id,
                    patient_id=patient_id,
                    msg_timestamp=msg_ts,
                    warnings=warnings,
                )
                if sample is not None:
                    samples.append(sample)
                else:
                    skipped += 1
            except Exception as exc:
                skipped += 1
                warn = f"[OBX-ERROR] Unexpected error parsing OBX segment: {exc}"
                warnings.append(warn)
                log.warning("hl7v2_adapter.obx.unexpected_error", error=str(exc))

        log.info(
            "hl7v2_adapter.parse.complete",
            sample_count=len(samples),
            skipped_count=skipped,
        )

        return HL7ParseResult(
            samples=tuple(samples),
            patient_id=patient_id,
            detected_vendor=vendor,
            message_timestamp=msg_ts,
            skipped_obx_count=skipped,
            parse_warnings=tuple(warnings),
        )

    # ── Private: Message-Level Extraction ─────────────────────────────────────

    def _detect_vendor(self, msg: object) -> MonitorVendor:
        """
        Detect vendor from MSH-3 (Sending Application).

        ISO 14971 HAZARD-PROTO-001: Unknown vendor defaults to GENERIC,
        which uses LOINC-only mapping. Proprietary codes are silently dropped.
        """
        msh_3 = ""
        for child in msg.children:  # type: ignore[attr-defined]
            if getattr(child, "name", "").upper() == "MSH":
                msh_3 = _safe_field(child, "msh_3").upper()
                break

        for substring, vendor in _VENDOR_SUBSTRINGS:
            if substring in msh_3:
                return vendor

        return MonitorVendor.GENERIC

    def _extract_patient_id(
        self,
        msg: object,
        warnings: list[str],
    ) -> str:
        """Extract PID-3 (Patient Identifier List) component 1."""
        for child in msg.children:  # type: ignore[attr-defined]
            if getattr(child, "name", "").upper() == "PID":
                pid_3 = _safe_field(child, "pid_3")
                if pid_3:
                    # PID-3 is CX type: component 1 is the ID value
                    return pid_3.split("^")[0].strip() or "UNKNOWN"
                break

        warnings.append("[PID-MISSING] PID-3 Patient Identifier absent — using 'UNKNOWN'.")
        return "UNKNOWN"

    def _extract_message_timestamp(self, msg: object) -> datetime:
        """Extract MSH-7 (Date/Time of Message). Defaults to UTC now."""
        for child in msg.children:  # type: ignore[attr-defined]
            if getattr(child, "name", "").upper() == "MSH":
                ts_str = _safe_field(child, "msh_7")
                if ts_str:
                    return _parse_hl7_datetime(ts_str)
                break
        return datetime.now(tz=timezone.utc)

    # ── Private: OBX Segment Parsing ──────────────────────────────────────────

    def _parse_obx(
        self,
        obx: object,
        vendor: MonitorVendor,
        device_id: str,
        patient_id: str,  # noqa: ARG002  # reserved for future subject reference
        msg_timestamp: datetime,
        warnings: list[str],
    ) -> VitalSignSample | None:
        """
        Parse a single OBX segment into a VitalSignSample.

        Returns None when:
        - OBX-3 identifier cannot be mapped to a VitalSignType (unknown code)
        - OBX-2 value type is NA or ED (waveform — unsupported in v1.0)
        - OBX-5 value is empty or unparseable
        - OBX-11 result status is not F (Final) or P (Preliminary)

        IEC 62304 REQ-HL7-002: Only Final (F) and Preliminary (P) observations
        are accepted. Corrected (C) and entered-in-error (W) are excluded.
        """
        # OBX-11: Result Status — only accept F (Final) and P (Preliminary)
        status = _safe_field(obx, "obx_11").upper().strip()
        if status and status not in {"F", "P"}:
            warnings.append(
                f"[OBX-SKIP] OBX-11 status '{status}' is not F/P — skipped. "
                "IEC 62304 REQ-HL7-002."
            )
            return None

        # OBX-2: Value Type — skip waveform types (Phase 4+ roadmap)
        value_type = _safe_field(obx, "obx_2").upper().strip()
        if value_type in {"NA", "ED"}:
            warnings.append(
                f"[OBX-SKIP] OBX-2 value type '{value_type}' (waveform data) "
                "is not supported in v1.0. "
                "See roadmap: Phase 4 waveform streaming support."
            )
            return None

        # OBX-3: Observation Identifier → VitalSignType
        obx_3_str = _safe_field(obx, "obx_3")
        vital_type = self._resolve_vital_type(obx_3_str, vendor, warnings)
        if vital_type is None:
            return None

        # OBX-5: Observation Value
        raw_value = _safe_field(obx, "obx_5").strip()
        if not raw_value:
            warnings.append(
                f"[OBX-SKIP] OBX-5 is empty for {vital_type.name}. "
                "Segment skipped."
            )
            return None

        # OBX-6: Units
        unit = self._resolve_unit(
            unit_str=_safe_field(obx, "obx_6"),
            vital_type=vital_type,
        )

        # OBX-14: Date/Time of Observation (use message timestamp as fallback)
        obs_ts_str = _safe_field(obx, "obx_14")
        obs_timestamp = (
            _parse_hl7_datetime(obs_ts_str) if obs_ts_str else msg_timestamp
        )

        # Parse value based on VitalSignType
        if vital_type is VitalSignType.CONSCIOUSNESS:
            return self._build_consciousness_sample(
                raw_value, obs_timestamp, device_id, warnings
            )

        if vital_type is VitalSignType.SUPPLEMENTAL_O2:
            return self._build_o2_sample(
                raw_value, obs_timestamp, device_id, warnings
            )

        # All other types: numeric value
        numeric = _parse_numeric(raw_value)
        if numeric is None:
            warnings.append(
                f"[OBX-SKIP] Cannot parse OBX-5 '{raw_value}' as a number "
                f"for {vital_type.name}. Segment skipped."
            )
            return None

        return VitalSignSample(
            vital_sign_type=vital_type,
            value=numeric,
            unit=unit,
            timestamp=obs_timestamp,
            device_id=device_id,
        )

    def _resolve_vital_type(
        self,
        obx_3: str,
        vendor: MonitorVendor,
        warnings: list[str],
    ) -> VitalSignType | None:
        """
        Map OBX-3 identifier to VitalSignType.

        Resolution order:
          1. LOINC code (OBX-3.3 coding system = "LN" or "LOINC")
          2. Vendor proprietary code (normalized to uppercase)
          3. LOINC lookup of OBX-3.1 regardless of system (best-effort)

        ISO 14971 HAZARD-PROTO-001: Unmapped codes return None (OBX skipped)
        rather than raising — prevents one unknown code crashing the message.
        """
        parts = obx_3.split("^")
        identifier = parts[0].strip()
        coding_system = parts[2].strip().upper() if len(parts) > 2 else ""

        # 1. LOINC lookup
        if coding_system in {"LN", "LOINC", ""} and identifier in _LOINC_TO_TYPE:
            return _LOINC_TO_TYPE[identifier]

        # 2. Vendor proprietary code (non-LOINC)
        normalized = identifier.upper().replace("-", "-")
        if normalized in _VENDOR_TO_TYPE:
            return _VENDOR_TO_TYPE[normalized]

        # 3. Best-effort LOINC without coding system assertion
        if identifier in _LOINC_TO_TYPE:
            return _LOINC_TO_TYPE[identifier]

        warnings.append(
            f"[OBX-UNKNOWN] Cannot map OBX-3 '{obx_3}' to a VitalSignType "
            f"(vendor={vendor.value}). Segment skipped. "
            "ISO 14971 HAZARD-PROTO-001: Add unknown code to _LOINC_TO_TYPE "
            "or _VENDOR_TO_TYPE to enable parsing."
        )
        return None

    @staticmethod
    def _resolve_unit(
        unit_str: str,
        vital_type: VitalSignType,
    ) -> VitalSignUnit:
        """
        Map OBX-6 unit string to VitalSignUnit.
        Falls back to _DEFAULT_UNIT when OBX-6 is absent or unrecognised.
        """
        u = unit_str.split("^")[0].strip().lower()
        unit_map: dict[str, VitalSignUnit] = {
            "/min": VitalSignUnit.BPM,
            "bpm": VitalSignUnit.BPM,
            "beats/min": VitalSignUnit.BPM,
            "breaths/min": VitalSignUnit.BREATHS_PER_MIN,
            "rpm": VitalSignUnit.BREATHS_PER_MIN,
            "%": VitalSignUnit.PERCENT,
            "percent": VitalSignUnit.PERCENT,
            "mmhg": VitalSignUnit.MMHG,
            "mm[hg]": VitalSignUnit.MMHG,
            "cel": VitalSignUnit.CELSIUS,
            "degc": VitalSignUnit.CELSIUS,
            "celsius": VitalSignUnit.CELSIUS,
            "[degf]": VitalSignUnit.FAHRENHEIT,
            "degf": VitalSignUnit.FAHRENHEIT,
            "f": VitalSignUnit.FAHRENHEIT,
        }
        return unit_map.get(u, _DEFAULT_UNIT.get(vital_type, VitalSignUnit.PERCENT))

    @staticmethod
    def _build_consciousness_sample(
        raw_value: str,
        timestamp: datetime,
        device_id: str,
        warnings: list[str],
    ) -> VitalSignSample | None:
        """Parse AVPU string (ST type OBX) into VitalSignSample with avpu_level."""
        key = raw_value.strip().upper()
        avpu = _AVPU_STRINGS.get(key)
        if avpu is None:
            warnings.append(
                f"[OBX-AVPU] Cannot map OBX-5 value '{raw_value}' to AVPULevel. "
                f"Recognised values: {sorted(_AVPU_STRINGS.keys())}. Segment skipped."
            )
            return None
        return VitalSignSample(
            vital_sign_type=VitalSignType.CONSCIOUSNESS,
            value=0.0,        # Numeric value unused for consciousness — avpu_level is authoritative
            unit=VitalSignUnit.AVPU_SCALE,
            timestamp=timestamp,
            avpu_level=avpu,
            device_id=device_id,
        )

    @staticmethod
    def _build_o2_sample(
        raw_value: str,
        timestamp: datetime,
        device_id: str,
        warnings: list[str],
    ) -> VitalSignSample | None:
        """
        Parse supplemental O2 OBX into VitalSignSample (boolean encoding).

        Encoding: 1.0 = on supplemental oxygen, 0.0 = on room air.
        Handles: "1"/"0", "YES"/"NO", "O2"/"AIR", FiO2 % values > 21%.
        """
        v = raw_value.strip().upper()

        # Boolean / string representations
        if v in {"1", "YES", "TRUE", "O2", "OXYGEN", "ON O2"}:
            return VitalSignSample(
                vital_sign_type=VitalSignType.SUPPLEMENTAL_O2,
                value=1.0,
                unit=VitalSignUnit.BOOLEAN,
                timestamp=timestamp,
                device_id=device_id,
            )
        if v in {"0", "NO", "FALSE", "AIR", "ROOM AIR", "RA"}:
            return VitalSignSample(
                vital_sign_type=VitalSignType.SUPPLEMENTAL_O2,
                value=0.0,
                unit=VitalSignUnit.BOOLEAN,
                timestamp=timestamp,
                device_id=device_id,
            )

        # FiO2 percentage: > 21% = on supplemental O2
        numeric = _parse_numeric(v)
        if numeric is not None:
            on_o2 = numeric > 21.0  # Room air FiO2 = 21%
            return VitalSignSample(
                vital_sign_type=VitalSignType.SUPPLEMENTAL_O2,
                value=1.0 if on_o2 else 0.0,
                unit=VitalSignUnit.BOOLEAN,
                timestamp=timestamp,
                device_id=device_id,
            )

        warnings.append(
            f"[OBX-O2] Cannot parse supplemental O2 value '{raw_value}'. Skipped."
        )
        return None


# ── Module-Level Utility Functions ─────────────────────────────────────────────


def _safe_field(segment: object, field_name: str) -> str:
    """
    Safely access an hl7apy segment field value.

    Returns empty string on AttributeError, None value, or any hl7apy exception.
    This is the single point of contact with hl7apy's field API — all exceptions
    are absorbed here so individual OBX parsing failures are isolated.

    IEC 62304 REQ-HL7-003: Field access failures must never abort message parsing.
    """
    try:
        field = getattr(segment, field_name, None)
        if field is None:
            return ""
        val = field.value
        return val if val is not None else ""
    except Exception:  # hl7apy raises various non-standard exception types
        return ""


def _parse_hl7_datetime(hl7_ts: str) -> datetime:
    """
    Parse an HL7 v2.x DTM (Date/Time) string to a timezone-aware datetime (UTC).

    HL7 DTM format: YYYY[MM[DD[HH[MM[SS[.S+]]]]]][+/-ZZZZ]
    Examples:
      "20240115100000"      → 2024-01-15 10:00:00 UTC (assumed)
      "20240115100000+0500" → 2024-01-15 05:00:00 UTC (converted)
      "202401"              → 2024-01-01 00:00:00 UTC (partial)

    Returns datetime.now(UTC) if the string is unparseable.
    ISO 14971 HAZARD-TIME-001: Fallback to now() is safer than raising —
    timestamps are used only for ordering samples, not clinical decisions.
    """
    ts = hl7_ts.strip()
    if not ts:
        return datetime.now(tz=timezone.utc)

    # Extract and strip timezone offset (e.g., "+0500" or "-0800")
    tz = timezone.utc
    tz_match = re.search(r"([+-])(\d{2})(\d{2})$", ts)
    if tz_match:
        sign = 1 if tz_match.group(1) == "+" else -1
        offset = timedelta(
            hours=int(tz_match.group(2)),
            minutes=int(tz_match.group(3)),
        )
        tz = timezone(sign * offset)
        ts = ts[: tz_match.start()]

    # Strip decimal seconds
    if "." in ts:
        ts = ts.split(".")[0]

    # Try formats from most to least specific
    for fmt, length in [
        ("%Y%m%d%H%M%S", 14),
        ("%Y%m%d%H%M", 12),
        ("%Y%m%d%H", 10),
        ("%Y%m%d", 8),
        ("%Y%m", 6),
        ("%Y", 4),
    ]:
        if len(ts) >= length:
            try:
                return datetime.strptime(ts[:length], fmt).replace(tzinfo=tz)
            except ValueError:
                continue

    return datetime.now(tz=timezone.utc)


def _parse_numeric(raw: str) -> float | None:
    """
    Parse an HL7 OBX-5 numeric value to float.

    Handles:
      - Plain numeric: "72", "98.6"
      - Structured Numeric (SN): ">100", "^72", "72^100" → take first numeric part
      - Trailing units embedded in value: "72bpm" → strip non-numeric suffix

    Returns None if no numeric value can be extracted.
    """
    v = raw.strip()
    if not v:
        return None

    # SN type: strip leading comparison operators
    v = re.sub(r"^[><=]+", "", v)

    # SN type caret-component: take first non-empty component (e.g., "^72" → "72")
    if "^" in v:
        components = [c for c in v.split("^") if c.strip()]
        if components:
            v = components[0]

    # Strip trailing non-numeric characters (e.g., "72bpm" → "72")
    m = re.match(r"^-?\d+(\.\d+)?", v.strip())
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            pass

    return None