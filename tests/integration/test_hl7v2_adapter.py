"""
Integration Tests — HL7v2Adapter.

IEC 62304 §5.7: Integration tests verify correct OBX segment mapping
across vendor dialects and edge cases.
ISO 14971 HAZARD-PROTO-001: Tests cover vendor detection and code mapping.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from domain.entities.vital_sign import AVPULevel, VitalSignType
from infrastructure.adapters.hl7v2_adapter import (
    HL7v2Adapter,
    _parse_hl7_datetime,
    _parse_numeric,
)

_ADAPTER = HL7v2Adapter()

# ── Sample HL7 Messages ────────────────────────────────────────────────────────

# Generic ORU^R01 with LOINC codes — represents a standards-compliant monitor.
GENERIC_ORU = (
    "MSH|^~\\&|GENERIC_MONITOR|ICU_UNIT|EHR|HOSPITAL|20240115100000||ORU^R01|MSG001|P|2.5.1\r"
    "PID|1||PT-001^^^HOSP^MR||DOE^JOHN||19800101|M\r"
    "OBR|1||ORDER-001|||||20240115100000\r"
    "OBX|1|NM|8867-4^Heart rate^LN||72|/min|60-100||||F|||20240115100000\r"
    "OBX|2|NM|59408-5^SpO2^LN||98|%|95-100||||F|||20240115100000\r"
    "OBX|3|NM|9279-1^Respiratory rate^LN||16|/min|12-20||||F|||20240115100000\r"
    "OBX|4|NM|8480-6^Systolic BP^LN||120|mmHg|90-140||||F|||20240115100000\r"
    "OBX|5|NM|8462-4^Diastolic BP^LN||80|mmHg|60-90||||F|||20240115100000\r"
    "OBX|6|NM|8310-5^Temperature^LN||37.0|Cel|36.1-38.0||||F|||20240115100000\r"
)

# Philips IntelliVue with proprietary codes (MSH-3 = PHILIPS)
PHILIPS_ORU = (
    "MSH|^~\\&|PHILIPS|ICU-BED-7|EHR|HOSPITAL|20240115100000||ORU^R01|MSG002|P|2.3.1\r"
    "PID|1||PT-002^HOSP^MR\r"
    "OBR|1\r"
    "OBX|1|NM|HR^Heart Rate^MDC||88|bpm|60-100||||F|||20240115100000\r"
    "OBX|2|NM|SPO2^SpO2^MDC||95|%|95-100||||F|||20240115100000\r"
    "OBX|3|NM|RESP^Respiratory Rate^MDC||22|/min|12-20||||F|||20240115100000\r"
    "OBX|4|NM|NIBP-S^Systolic BP^MDC||90|mmHg||||F|||20240115100000\r"
    "OBX|5|NM|TEMP^Temperature^MDC||38.5|Cel||||F|||20240115100000\r"
)

# Message with AVPU consciousness (ST type OBX)
AVPU_ORU = (
    "MSH|^~\\&|GE_CARESCAPE|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG003|P|2.5.1\r"
    "PID|1||PT-003\r"
    "OBX|1|NM|8867-4^HR^LN||90|/min||||F|||20240115100000\r"
    "OBX|2|ST|AVPU^Level of Consciousness^MDC||NEW_CONFUSION|avpu||||F|||20240115100000\r"
    "OBX|3|NM|57834-7^O2 Therapy^LN||1||||||F|||20240115100000\r"
)

# Message with waveform (NA type OBX) — now parsed into a waveform-carrying
# VitalSignSample (placeholder scalar value=0.0) alongside the companion NM
# scalar heart rate OBX. See TestWaveformHandling below.
WAVEFORM_ORU = (
    "MSH|^~\\&|DRAEGER|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG004|P|2.5.1\r"
    "PID|1||PT-004\r"
    "OBX|1|NA|8867-4^ECG Waveform^LN||0.1^0.2^0.3^0.4^0.1|mV||||F|||20240115100000\r"
    "OBX|2|NM|8867-4^Heart rate^LN||88|/min||||F|||20240115100000\r"
)

# Message with bad OBX (non-final status and missing value)
PARTIAL_ORU = (
    "MSH|^~\\&|GENERIC|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG005|P|2.5.1\r"
    "PID|1||PT-005\r"
    "OBX|1|NM|8867-4^HR^LN||72|/min|||||F|||20240115100000\r"
    "OBX|2|NM|UNKNOWN_CODE^Unknown^MDC||||||||F\r"  # Unknown code, empty value
    "OBX|3|NM|8480-6^SBP^LN||120|mmHg|||||X|||20240115100000\r"  # Status X (entered-in-error) — skip
)

# Message without PID segment
NO_PID_ORU = (
    "MSH|^~\\&|GENERIC|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG006|P|2.5.1\r"
    "OBX|1|NM|8867-4^HR^LN||72|/min||||F|||20240115100000\r"
)


# ── Parser Tests ───────────────────────────────────────────────────────────────


class TestGenericLOINCParsing:
    """Tests with standard LOINC codes — most interoperable case."""

    def test_parses_six_vital_sign_types(self) -> None:
        result = _ADAPTER.parse(GENERIC_ORU)
        types = {s.vital_sign_type for s in result.samples}
        expected = {
            VitalSignType.HEART_RATE,
            VitalSignType.SPO2,
            VitalSignType.RESPIRATORY_RATE,
            VitalSignType.SYSTOLIC_BP,
            VitalSignType.DIASTOLIC_BP,
            VitalSignType.TEMPERATURE_CELSIUS,
        }
        assert types == expected

    def test_extracts_correct_hr_value(self) -> None:
        result = _ADAPTER.parse(GENERIC_ORU)
        hr = next(
            s for s in result.samples if s.vital_sign_type is VitalSignType.HEART_RATE
        )
        assert hr.value == 72.0

    def test_extracts_correct_temperature(self) -> None:
        result = _ADAPTER.parse(GENERIC_ORU)
        temp = next(
            s
            for s in result.samples
            if s.vital_sign_type is VitalSignType.TEMPERATURE_CELSIUS
        )
        assert temp.value == 37.0

    def test_extracts_patient_id(self) -> None:
        result = _ADAPTER.parse(GENERIC_ORU)
        assert result.patient_id == "PT-001"

    def test_detects_generic_vendor(self) -> None:
        from domain.entities.device_context import MonitorVendor

        result = _ADAPTER.parse(GENERIC_ORU)
        assert result.detected_vendor is MonitorVendor.GENERIC

    def test_timestamps_are_timezone_aware(self) -> None:
        result = _ADAPTER.parse(GENERIC_ORU)
        for sample in result.samples:
            assert sample.timestamp.tzinfo is not None, (
                "All timestamps must be timezone-aware. " "ISO 14971 HAZARD-TIME-001."
            )

    def test_zero_skipped_obx_on_clean_message(self) -> None:
        result = _ADAPTER.parse(GENERIC_ORU)
        assert result.skipped_obx_count == 0


class TestPhilipsVendorDialect:
    """Tests with Philips IntelliVue proprietary OBX codes."""

    def test_detects_philips_vendor_from_msh3(self) -> None:
        from domain.entities.device_context import MonitorVendor

        result = _ADAPTER.parse(PHILIPS_ORU)
        assert result.detected_vendor is MonitorVendor.PHILIPS

    def test_maps_philips_hr_code(self) -> None:
        result = _ADAPTER.parse(PHILIPS_ORU)
        types = {s.vital_sign_type for s in result.samples}
        assert VitalSignType.HEART_RATE in types

    def test_maps_philips_spo2_code(self) -> None:
        result = _ADAPTER.parse(PHILIPS_ORU)
        types = {s.vital_sign_type for s in result.samples}
        assert VitalSignType.SPO2 in types

    def test_philips_hr_value_correct(self) -> None:
        result = _ADAPTER.parse(PHILIPS_ORU)
        hr = next(
            (
                s
                for s in result.samples
                if s.vital_sign_type is VitalSignType.HEART_RATE
            ),
            None,
        )
        assert hr is not None
        assert hr.value == 88.0


class TestAVPUConsciousnessOBX:
    """Tests for AVPU level parsing from ST-type OBX segments."""

    def test_parses_new_confusion_avpu(self) -> None:
        result = _ADAPTER.parse(AVPU_ORU)
        consciousness = next(
            (
                s
                for s in result.samples
                if s.vital_sign_type is VitalSignType.CONSCIOUSNESS
            ),
            None,
        )
        assert consciousness is not None
        assert consciousness.avpu_level is AVPULevel.NEW_CONFUSION, (
            "NEW_CONFUSION string in OBX-5 must map to AVPULevel.NEW_CONFUSION. "
            "ISO 14971 HAZARD-CON-001."
        )

    def test_parses_supplemental_o2_boolean(self) -> None:
        result = _ADAPTER.parse(AVPU_ORU)
        o2 = next(
            (
                s
                for s in result.samples
                if s.vital_sign_type is VitalSignType.SUPPLEMENTAL_O2
            ),
            None,
        )
        assert o2 is not None
        assert o2.value == 1.0  # "1" → on O2


class TestWaveformHandling:
    """
    NA/ED type OBX (waveform) parsing.

    BEHAVIOR CHANGE (documented, deliberate): prior to this revision, NA/ED
    OBX segments were unconditionally skipped ("Phase 4+ roadmap"). This
    class previously asserted that skip behavior. The product decision is now
    to parse NA/ED into a waveform-carrying VitalSignSample so the DSP
    artifact-rejection pipeline (notch/bandpass/Hampel) can run against real
    HL7-sourced waveform data. The two tests below that encoded the old
    "must be skipped" requirement have been renamed and rewritten to assert
    the new, intentional behavior. `test_na_warning_recorded` needed no
    change — it only asserts an audit trail entry exists, which remains true.
    """

    def test_na_waveform_is_parsed_into_sample(self) -> None:
        result = _ADAPTER.parse(WAVEFORM_ORU)
        assert result.skipped_obx_count == 0, (
            "Both OBX segments (NA waveform + NM scalar) must parse "
            "successfully now that waveform support is implemented."
        )
        waveform_samples = [
            s
            for s in result.samples
            if s.vital_sign_type is VitalSignType.HEART_RATE and s.waveform is not None
        ]
        assert len(waveform_samples) == 1
        sample = waveform_samples[0]
        assert sample.waveform == (0.1, 0.2, 0.3, 0.4, 0.1)
        assert sample.sampling_rate_hz == 250.0  # default table, OBX-6="mV" not numeric
        assert sample.value == 0.0, (
            "Scalar value on a waveform-only sample is a fixed, documented "
            "placeholder — never a clinical reading."
        )

    def test_na_warning_recorded(self) -> None:
        result = _ADAPTER.parse(WAVEFORM_ORU)
        assert any("NA" in w or "waveform" in w.lower() for w in result.parse_warnings)

    def test_companion_numeric_obx_still_parses_as_scalar(self) -> None:
        result = _ADAPTER.parse(WAVEFORM_ORU)
        scalar_samples = [
            s
            for s in result.samples
            if s.vital_sign_type is VitalSignType.HEART_RATE and s.waveform is None
        ]
        assert len(scalar_samples) == 1, (
            "The companion NM OBX after the NA OBX must still be parsed as "
            "the scalar NEWS2 input. IEC 62304 REQ-HL7-003: one segment's "
            "handling must not affect another's."
        )
        assert scalar_samples[0].value == 88.0

    def test_unsupported_waveform_type_is_skipped(self) -> None:
        """TEMPERATURE_CELSIUS has no configured waveform support (no default
        sampling rate, and not in the DSP-pipeline's waveform-capable set) —
        an NA OBX for it must be skipped, not guessed."""
        msg = (
            "MSH|^~\\&|DRAEGER|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG099|P|2.5.1\r"
            "PID|1||PT-099\r"
            "OBX|1|NA|8310-5^Temperature Waveform^LN||36.5^36.6^36.5|Cel||||F|||20240115100000\r"
        )
        result = _ADAPTER.parse(msg)
        assert result.skipped_obx_count == 1
        assert any("OBX-WAVEFORM-UNSUPPORTED" in w for w in result.parse_warnings)

    def test_corrupted_waveform_sample_rejects_whole_array(self) -> None:
        """ISO 14971 HAZARD-WAVE-001: one non-numeric component anywhere in
        the array must reject the entire segment, not silently drop it."""
        msg = (
            "MSH|^~\\&|DRAEGER|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG098|P|2.5.1\r"
            "PID|1||PT-098\r"
            "OBX|1|NA|8867-4^ECG^LN||0.1^BAD^0.3|mV||||F|||20240115100000\r"
        )
        result = _ADAPTER.parse(msg)
        assert result.skipped_obx_count == 1
        assert any("OBX-WAVEFORM-UNPARSEABLE" in w for w in result.parse_warnings)

    def test_obx6_numeric_override_takes_precedence_over_default(self) -> None:
        msg = (
            "MSH|^~\\&|DRAEGER|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG097|P|2.5.1\r"
            "PID|1||PT-097\r"
            "OBX|1|NA|8867-4^ECG^LN||0.1^0.2^0.3^0.4^0.1^0.2^0.3^0.4^0.1^0.2^0.3^0.4^0.1^0.2^0.3|500||||F|||20240115100000\r"
        )
        result = _ADAPTER.parse(msg)
        sample = next(s for s in result.samples if s.waveform is not None)
        assert sample.sampling_rate_hz == 500.0
        assert any("OBX-6 explicit override" in w for w in result.parse_warnings)

    def test_ed_base64_waveform_is_parsed(self) -> None:
        import base64

        payload = base64.b64encode(b"0.5,0.6,0.7,0.6,0.5").decode("ascii")
        msg = (
            "MSH|^~\\&|MINDRAY|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG096|P|2.5.1\r"
            "PID|1||PT-096\r"
            f"OBX|1|ED|59408-5^Pleth^LN||LOCAL^WAVEFORM^PLETH^Base64^{payload}|%||||F|||20240115100000\r"
            "OBX|2|NM|59408-5^SpO2^LN||97|%||||F|||20240115100000\r"
        )
        result = _ADAPTER.parse(msg)
        assert result.skipped_obx_count == 0
        wave = next(s for s in result.samples if s.waveform is not None)
        assert wave.vital_sign_type is VitalSignType.SPO2
        assert wave.waveform == (0.5, 0.6, 0.7, 0.6, 0.5)
        assert wave.sampling_rate_hz == 62.5  # SPO2 default

    def test_ed_unsupported_encoding_is_skipped(self) -> None:
        msg = (
            "MSH|^~\\&|MINDRAY|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG095|P|2.5.1\r"
            "PID|1||PT-095\r"
            "OBX|1|ED|59408-5^Pleth^LN||LOCAL^WAVEFORM^PLETH^RawBinary^somebytes|%||||F|||20240115100000\r"
        )
        result = _ADAPTER.parse(msg)
        assert result.skipped_obx_count == 1
        assert any("OBX-ED-ENCODING" in w for w in result.parse_warnings)


class TestPartialAndErrorHandling:
    """Robustness tests for malformed and partial messages."""

    def test_unknown_obx_code_is_skipped(self) -> None:
        result = _ADAPTER.parse(PARTIAL_ORU)
        types = {s.vital_sign_type for s in result.samples}
        # UNKNOWN_CODE should not produce a sample
        assert VitalSignType.HEART_RATE in types  # known code parses
        # skipped count includes: UNKNOWN_CODE (missing value) + X-status SBP
        assert result.skipped_obx_count >= 2

    def test_x_status_obx_is_skipped(self) -> None:
        """OBX-11 = X (entered-in-error) must be excluded per IEC 62304 REQ-HL7-002."""
        result = _ADAPTER.parse(PARTIAL_ORU)
        # SBP from the X-status OBX must not appear
        sbp_values = [
            s.value
            for s in result.samples
            if s.vital_sign_type is VitalSignType.SYSTOLIC_BP
        ]
        assert not sbp_values, "X-status OBX must not produce a VitalSignSample."

    def test_missing_pid_returns_unknown_patient(self) -> None:
        result = _ADAPTER.parse(NO_PID_ORU)
        assert result.patient_id == "UNKNOWN"
        assert any("PID" in w for w in result.parse_warnings)

    def test_invalid_hl7_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="hl7apy cannot parse"):
            _ADAPTER.parse("NOT AN HL7 MESSAGE AT ALL")

    def test_crlf_normalised_correctly(self) -> None:
        """Messages with \\r\\n or \\n endings must parse identically to \\r."""
        crlf_msg = GENERIC_ORU.replace("\r", "\r\n")
        result = _ADAPTER.parse(crlf_msg)
        assert len(result.samples) == 6


# ── Utility Function Tests ─────────────────────────────────────────────────────


class TestParseHL7Datetime:
    def test_full_datetime_string(self) -> None:
        dt = _parse_hl7_datetime("20240115100000")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.tzinfo is not None

    def test_datetime_with_positive_offset(self) -> None:
        dt = _parse_hl7_datetime("20240115100000+0500")
        # Should convert to offset-aware
        assert dt.tzinfo is not None
        # UTC equivalent is 05:00:00
        utc_equivalent = dt.utctimetuple()
        assert utc_equivalent.tm_hour == 5

    def test_partial_date_only(self) -> None:
        dt = _parse_hl7_datetime("20240115")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15

    def test_empty_string_returns_now(self) -> None:
        before = datetime.now(tz=timezone.utc)
        dt = _parse_hl7_datetime("")
        after = datetime.now(tz=timezone.utc)
        assert before <= dt <= after

    def test_returns_timezone_aware_datetime(self) -> None:
        dt = _parse_hl7_datetime("20240115100000")
        assert dt.tzinfo is not None


class TestParseNumeric:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("72", 72.0),
            ("98.6", 98.6),
            (">100", 100.0),  # SN comparison operator stripped
            ("^72", 72.0),  # SN caret-component
            ("72^100", 72.0),  # SN range — first component
            ("72bpm", 72.0),  # Trailing unit suffix
            ("-5.5", -5.5),  # Negative value
        ],
    )
    def test_numeric_parsing(self, raw: str, expected: float) -> None:
        result = _parse_numeric(raw)
        assert result is not None
        assert abs(result - expected) < 0.001

    def test_empty_string_returns_none(self) -> None:
        assert _parse_numeric("") is None

    def test_pure_text_returns_none(self) -> None:
        assert _parse_numeric("ALERT") is None

