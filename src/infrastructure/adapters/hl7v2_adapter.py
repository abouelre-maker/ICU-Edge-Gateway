"""
HL7 v2.x ORU^R01 Adapter — ICU Monitor Protocol Bridge.

Bridges the legacy HL7 v2.x wire protocol (dominant in 80%+ of North American
hospitals) to the domain's VitalSignSample entities.

Supported protocol variants:
  - HL7 v2.3 – v2.8 ORU^R01 messages
  - OBX value types: NM (Numeric), ST (String), SN (Structured Numeric)
  - NA (Numeric Array) and ED (Encapsulated Data) waveform: parsed into
    VitalSignSample.waveform for the DSP artifact-rejection pipeline. See
    _build_waveform_sample for the exact supported subset and known limits.
  - Vendor dialects: Philips IntelliVue / GE CARESCAPE / Dräger Infinity /
    Mindray Beneview / Nihon Kohden / Generic (LOINC fallback)

IEC 62304 §5.3: GoF Adapter pattern — isolates legacy protocol complexity
from the pure domain model.
ISO 14971 HAZARD-PROTO-001: Vendor dialect misidentification silently drops OBX
segments. Mitigation: explicit MSH-3 vendor map + LOINC fallback for all OBX-3
identifiers.
ISO 14971 HAZARD-PROTO-002: HL7 v2.x has no standardized field for continuous
waveform sampling rate. This adapter resolves it via an explicit, documented
per-VitalSignType default table with an optional OBX-6 numeric override —
NOT a claim of a universal HL7 standard. The default table MUST be validated
against each connected monitor's actual interface specification before the
waveform DSP pipeline is used clinically against that monitor model.
ISO 14971 HAZARD-WAVE-001: A waveform array with any single unparseable sample
is rejected in its entirety (never silently truncated/reindexed) — a partial
array would corrupt sample timing ahead of notch/bandpass/Hampel processing.
SOUP: hl7apy==1.3.4 — version pinned in requirements.txt per IEC 62304 §8.1.2.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

import structlog
from domain.entities.device_context import DeviceContext, MonitorVendor
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from hl7apy.parser import parse_message as _hl7apy_parse

_log: structlog.BoundLogger = structlog.get_logger(__name__)

# ── Code Mapping Tables ────────────────────────────────────────────────────────

# LOINC observation identifiers → VitalSignType.
# Source: LOINC.org — codes validated against NLM VSAC value sets.
_LOINC_TO_TYPE: Final[dict[str, VitalSignType]] = {
    "8867-4": VitalSignType.HEART_RATE,  # Heart rate
    "59408-5": VitalSignType.SPO2,  # SpO2 by pulse ox
    "2708-6": VitalSignType.SPO2,  # Oxygen saturation (alternate)
    "9279-1": VitalSignType.RESPIRATORY_RATE,  # Respiratory rate
    "8480-6": VitalSignType.SYSTOLIC_BP,  # Systolic BP
    "8462-4": VitalSignType.DIASTOLIC_BP,  # Diastolic BP
    "8310-5": VitalSignType.TEMPERATURE_CELSIUS,  # Body temperature
    "67775-7": VitalSignType.CONSCIOUSNESS,  # Level of responsiveness
    "76270-8": VitalSignType.CONSCIOUSNESS,  # AVPU score
    "57834-7": VitalSignType.SUPPLEMENTAL_O2,  # Oxygen therapy
    "3151-8": VitalSignType.SUPPLEMENTAL_O2,  # Inhaled O2 flow rate
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
    "PR": VitalSignType.HEART_RATE,  # Pulse Rate (GE)
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
    "TEMPBLA": VitalSignType.TEMPERATURE_CELSIUS,  # Bladder temp (Philips)
    "TEMPCORE": VitalSignType.TEMPERATURE_CELSIUS,
    # Consciousness (AVPU)
    "AVPU": VitalSignType.CONSCIOUSNESS,
    "LOC": VitalSignType.CONSCIOUSNESS,
    "CONS": VitalSignType.CONSCIOUSNESS,
    # Supplemental O2
    "FIO2": VitalSignType.SUPPLEMENTAL_O2,  # FiO2 > 0.21 = on O2
    "O2FLOW": VitalSignType.SUPPLEMENTAL_O2,
    "O2DELIVERY": VitalSignType.SUPPLEMENTAL_O2,
    "AIROROXYGEN": VitalSignType.SUPPLEMENTAL_O2,
}

# MSH-3 Sending Application → MonitorVendor.
# Case-insensitive substring match against upper-cased MSH-3 value.
_VENDOR_SUBSTRINGS: Final[list[tuple[str, MonitorVendor]]] = [
    ("PHILIPS", MonitorVendor.PHILIPS),
    ("INTELLIVUE", MonitorVendor.PHILIPS),
    ("ISL", MonitorVendor.PHILIPS),  # Philips Information System Link
    ("CARESCAPE", MonitorVendor.GE),
    ("GE ", MonitorVendor.GE),  # Trailing space avoids matching "GENERAL"
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

# Documented default sampling rates (Hz) for continuous waveform channels, by
# VitalSignType. HL7 v2.x has NO dedicated, universally-standardized field for
# waveform sampling rate — this table is an explicit engineering decision, not
# a claim of a single HL7 standard. Values reflect commonly observed ICU
# bedside-monitor waveform export rates for these channel types.
#
# ISO 14971 HAZARD-PROTO-002: An incorrect sampling rate corrupts every
# downstream DSP stage (notch target frequency, bandpass range, Hampel
# timing). This table MUST be validated against the specific connected
# monitor's interface specification before clinical use of the waveform
# pipeline against that monitor model. An explicit OBX-6 numeric override is
# also honored — see _resolve_sampling_rate_hz.
#
# This set of keys MUST stay in sync with
# domain.services.signal_processor._WAVEFORM_CAPABLE_TYPES — guarded by
# tests/integration/test_hl7v2_waveform_pipeline.py::
# test_waveform_capable_types_match_signal_processor.
_WAVEFORM_DEFAULT_SAMPLING_RATE_HZ: Final[dict[VitalSignType, float]] = {
    VitalSignType.HEART_RATE: 250.0,  # ECG-derived waveform
    VitalSignType.RESPIRATORY_RATE: 62.5,  # Impedance respiration waveform
    VitalSignType.SPO2: 62.5,  # Plethysmograph (pleth) waveform
    VitalSignType.SYSTOLIC_BP: 125.0,  # Arterial pressure waveform
    VitalSignType.DIASTOLIC_BP: 125.0,  # Arterial pressure waveform
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

        warnings.append(
            "[PID-MISSING] PID-3 Patient Identifier absent — using 'UNKNOWN'."
        )
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
        - OBX-2 value type is NA/ED but the resolved VitalSignType has no
          configured waveform support, or the array is empty/unparseable
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

        # OBX-3: Observation Identifier → VitalSignType.
        # Resolved before the value-type branch below so waveform handling can
        # consult the per-type sampling-rate default table.
        obx_3_str = _safe_field(obx, "obx_3")
        vital_type = self._resolve_vital_type(obx_3_str, vendor, warnings)
        if vital_type is None:
            return None

        # OBX-2: Value Type — NA (Numeric Array) / ED (Encapsulated Data) carry
        # continuous waveform data and are routed to the dedicated builder.
        value_type = _safe_field(obx, "obx_2").upper().strip()
        if value_type in {"NA", "ED"}:
            return self._build_waveform_sample(
                obx=obx,
                value_type=value_type,
                vital_type=vital_type,
                device_id=device_id,
                msg_timestamp=msg_timestamp,
                warnings=warnings,
            )

        # OBX-5: Observation Value
        raw_value = _safe_field(obx, "obx_5").strip()
        if not raw_value:
            warnings.append(
                f"[OBX-SKIP] OBX-5 is empty for {vital_type.name}. " "Segment skipped."
            )
            return None

        # OBX-6: Units
        unit = self._resolve_unit(
            unit_str=_safe_field(obx, "obx_6"),
            vital_type=vital_type,
        )

        # OBX-14: Date/Time of Observation (use message timestamp as fallback)
        obs_ts_str = _safe_field(obx, "obx_14")
        obs_timestamp = _parse_hl7_datetime(obs_ts_str) if obs_ts_str else msg_timestamp

        # Parse value based on VitalSignType
        if vital_type is VitalSignType.CONSCIOUSNESS:
            return self._build_consciousness_sample(
                raw_value, obs_timestamp, device_id, warnings
            )

        if vital_type is VitalSignType.SUPPLEMENTAL_O2:
            return self._build_o2_sample(raw_value, obs_timestamp, device_id, warnings)

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

    def _build_waveform_sample(
        self,
        obx: object,
        value_type: str,
        vital_type: VitalSignType,
        device_id: str,
        msg_timestamp: datetime,
        warnings: list[str],
    ) -> VitalSignSample | None:
        """
        Parse an HL7 NA (Numeric Array) or ED (Encapsulated Data) OBX segment
        into a waveform-carrying VitalSignSample for the DSP pipeline.

        Supported:
          - NA: OBX-5 is a caret-separated list of numeric samples
            (e.g. "72.1^72.3^72.5"), per the HL7 v2.x NA data type definition.
          - ED: OBX-5 is SourceApplication^TypeOfData^DataSubtype^Encoding^Data.
            Encoding "A" (plain text) or "Base64" is supported; the decoded
            payload must itself be a caret- or comma-separated numeric list.

        OUT OF SCOPE, explicitly (not silently guessed): raw binary waveform
        encodings (e.g. int16 PCM, IEEE-754 float arrays) inside an ED payload.
        If the decoded content is not delimited numeric text, the segment is
        skipped with a warning.

        Sampling rate resolution and the fail-whole-array rule are documented
        in _resolve_sampling_rate_hz and _parse_numeric_array respectively —
        see ISO 14971 HAZARD-PROTO-002 and HAZARD-WAVE-001 in the module
        docstring.

        The scalar `value` field on the returned sample is fixed at 0.0 and is
        NOT a clinical reading — VitalSignSample.value is a mandatory field
        with no meaning for a pure waveform channel. 0.0 is deliberately below
        every currently configured PhysiologicalBoundsChecker lower bound for
        every waveform-capable type (HEART_RATE, RESPIRATORY_RATE, SPO2,
        SYSTOLIC_BP, DIASTOLIC_BP — see domain/services/artifact_rejector.py
        _PHYSIOLOGICAL_BOUNDS), so PhysiologicalBoundsChecker.check() marks
        is_within_physiological_bounds=False and NEWS2Calculator._extract_value()
        (which filters on exactly that flag) can never select this placeholder
        as a scoring input. The scalar NEWS2 value for this vital sign type
        MUST arrive via a companion NM OBX segment — unchanged pre-existing
        design, exercised by tests/regulatory/test_news2_safety.py. This
        invariant is regression-guarded by
        tests/integration/test_hl7v2_waveform_pipeline.py::
        TestWaveformNeverFeedsNews2Score.

        Known side effect (documented, non-hazardous): because the placeholder
        is out-of-bounds by design, ObservationBuilder currently renders its
        FHIR Observation with dataAbsentReason="out-of-range" rather than a
        more semantically precise code. This is a cosmetic FHIR labeling item
        for a follow-up change to infrastructure/fhir/observation_builder.py —
        not a clinical or DSP defect — and is out of scope for this change.
        """
        if vital_type not in _WAVEFORM_DEFAULT_SAMPLING_RATE_HZ:
            warnings.append(
                f"[OBX-WAVEFORM-UNSUPPORTED] {value_type} waveform for "
                f"{vital_type.name} has no configured DSP waveform support "
                "(supported: HEART_RATE, RESPIRATORY_RATE, SPO2, SYSTOLIC_BP, "
                "DIASTOLIC_BP). Segment skipped."
            )
            return None

        raw_value = _safe_field(obx, "obx_5").strip()
        if not raw_value:
            warnings.append(
                f"[OBX-WAVEFORM-EMPTY] OBX-5 is empty for {value_type} "
                f"{vital_type.name} waveform. Segment skipped."
            )
            return None

        if value_type == "NA":
            array_text: str | None = raw_value
        else:  # ED
            array_text = _decode_ed_payload(raw_value, warnings)
            if array_text is not None:
                array_text = array_text.replace(",", "^")

        samples = _parse_numeric_array(array_text) if array_text is not None else None
        if not samples:
            warnings.append(
                f"[OBX-WAVEFORM-UNPARSEABLE] Could not parse {value_type} "
                f"waveform array for {vital_type.name} from OBX-5 "
                "(ED payload decode failed, or one or more samples were "
                "non-numeric). ISO 14971 HAZARD-WAVE-001: the entire array is "
                "rejected rather than partially parsed. Segment skipped."
            )
            return None

        obx_6 = _safe_field(obx, "obx_6")
        sampling_rate_hz, rate_source = self._resolve_sampling_rate_hz(
            unit_str=obx_6,
            vital_type=vital_type,
        )
        if sampling_rate_hz is None:
            warnings.append(
                f"[OBX-WAVEFORM-NO-RATE] No sampling rate available for "
                f"{vital_type.name} waveform (no OBX-6 override, no default "
                "configured). Segment skipped."
            )
            return None

        obs_ts_str = _safe_field(obx, "obx_14")
        obs_timestamp = _parse_hl7_datetime(obs_ts_str) if obs_ts_str else msg_timestamp
        unit = self._resolve_unit(unit_str=obx_6, vital_type=vital_type)

        warnings.append(
            f"[OBX-WAVEFORM] Parsed {value_type} waveform for {vital_type.name}: "
            f"{len(samples)} sample(s) at {sampling_rate_hz:.1f} Hz ({rate_source}). "
            "Scalar NEWS2 value for this vital sign, if any, must arrive via a "
            "companion NM OBX segment."
        )

        return VitalSignSample(
            vital_sign_type=vital_type,
            value=0.0,  # Placeholder — see docstring. Never used for NEWS2 scoring.
            unit=unit,
            timestamp=obs_timestamp,
            waveform=samples,
            sampling_rate_hz=sampling_rate_hz,
            device_id=device_id,
        )

    @staticmethod
    def _resolve_sampling_rate_hz(
        unit_str: str,
        vital_type: VitalSignType,
    ) -> tuple[float | None, str]:
        """
        Resolve the waveform sampling rate in Hz, plus a human-readable source
        label for the audit log.

        HL7 v2.x has no standardized field for continuous-waveform sampling
        rate. Resolution order:
          1. OBX-6 explicit numeric override — some vendor interfaces place the
             rate directly in the units field for waveform channels; accepted
             only if the leading component parses as a positive number.
          2. Documented per-VitalSignType clinical default
             (_WAVEFORM_DEFAULT_SAMPLING_RATE_HZ).
          3. (None, ...) if neither is available — caller must skip the segment.

        ISO 14971 HAZARD-PROTO-002: see module docstring. The default table is
        an engineering decision requiring site-specific validation, not a
        universal HL7 standard.
        """
        override = _parse_numeric(unit_str.split("^")[0].strip())
        if override is not None and override > 0:
            return override, "OBX-6 explicit override"

        default = _WAVEFORM_DEFAULT_SAMPLING_RATE_HZ.get(vital_type)
        if default is not None:
            return (
                default,
                "default table — validate against connected monitor's interface spec",
            )

        return None, "no source available"

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
            value=0.0,  # Numeric value unused for consciousness — avpu_level is authoritative
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


def _parse_numeric_array(raw: str) -> tuple[float, ...] | None:
    """
    Parse an HL7 NA (Numeric Array) OBX-5 value: a caret-separated list of
    numeric samples, e.g. "72.1^72.3^72.5^72.2".

    ISO 14971 HAZARD-WAVE-001: If ANY component fails to parse as a number,
    the entire array is rejected (returns None) rather than silently dropping
    the bad sample. A partially-parsed / re-indexed array would corrupt
    sample timing ahead of notch/bandpass/Hampel processing — rejecting the
    whole segment (and letting the caller warn + skip) is the safer failure
    mode for a signal about to be filtered.

    Returns None if the string is empty, contains no components, or any
    component is not numeric.
    """
    parts = [p.strip() for p in raw.split("^")]
    parts = [p for p in parts if p != ""]
    if not parts:
        return None

    values: list[float] = []
    for part in parts:
        numeric = _parse_numeric(part)
        if numeric is None:
            return None  # fail the whole array — see docstring
        values.append(numeric)

    return tuple(values)


def _decode_ed_payload(raw: str, warnings: list[str]) -> str | None:
    """
    Decode an HL7 ED (Encapsulated Data) OBX-5 value into a plain delimited
    numeric-array string, ready for _parse_numeric_array.

    HL7 v2.x ED components: SourceApplication^TypeOfData^DataSubtype^Encoding^Data.
    Supported encodings:
      - "A"      : Data is already plain text (no decoding needed).
      - "Base64" : Data is Base64-encoded ASCII text of a delimited numeric
                   array (caret- or comma-separated).

    OUT OF SCOPE, explicitly: raw binary sample formats (e.g. int16 PCM,
    IEEE-754 float arrays) inside the Base64 payload are vendor-specific and
    are NOT decoded here. If the decoded bytes are not valid ASCII text, the
    segment is skipped with a warning rather than guessed at.
    """
    components = raw.split("^")
    if len(components) < 5:
        warnings.append(
            "[OBX-ED-MALFORMED] ED value has fewer than 5 components — "
            "expected SourceApplication^TypeOfData^DataSubtype^Encoding^Data."
        )
        return None

    encoding = components[3].strip().upper()
    data = components[4]

    if encoding in {"A", ""}:
        return data

    if encoding in {"BASE64", "B64"}:
        try:
            decoded_bytes = base64.b64decode(data, validate=False)
            return decoded_bytes.decode("ascii", errors="strict")
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            warnings.append(
                f"[OBX-ED-DECODE] Base64 ED payload did not decode to ASCII "
                f"text: {exc}. Raw binary waveform formats (e.g. int16 PCM, "
                "IEEE-754 float arrays) are out of scope for this parser."
            )
            return None

    warnings.append(
        f"[OBX-ED-ENCODING] Unsupported ED encoding '{encoding}'. "
        "Only 'A' (plain text) and 'Base64' (ASCII-encoded numeric text) "
        "are supported."
    )
    return None


