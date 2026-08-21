"""
Integration Tests — HL7v2Adapter vendor-dialect edge cases.

Phase 5-Stream Section D. ISO 14971 HAZARD-PROTO-001: vendor
misidentification / unmapped-code handling must never silently drop an
observation without an audit trail, and must never crash the whole
message on one malformed field.

Covers, per the section's priority list:
  - Malformed/truncated MSH-3 (empty, partial-match substring, degenerate
    MSH segment)
  - Mixed-case vendor strings
  - A vendor string matching two _VENDOR_SUBSTRINGS entries simultaneously
    (documents the deterministic first-match-wins tie-break)
  - An OBX-3 identifier that IS a recognised LOINC code but is NOT in
    _VENDOR_TO_TYPE (as expected -- LOINC and vendor-proprietary codes are
    different namespaces) and is tagged with neither "LN"/"LOINC" nor a
    blank coding system -- must still resolve via _resolve_vital_type's
    best-effort LOINC fallback (step 3), not be silently dropped.

SYNTHETIC TEST DATA — FOR AUTOMATED TESTING ONLY, NOT CLINICAL VALIDATION
EVIDENCE. All HL7 messages below are synthetically constructed to exercise
specific parser code paths and are not derived from real patient monitor
output or real hospital traffic.
"""

from __future__ import annotations

from domain.entities.device_context import MonitorVendor
from domain.entities.vital_sign import VitalSignType
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter

_ADAPTER = HL7v2Adapter()


def _oru(msh_3: str, obx_lines: str) -> str:
    """Minimal ORU^R01 with a caller-supplied MSH-3 and OBX segment(s)."""
    return (
        f"MSH|^~\\&|{msh_3}|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG-EDGE|P|2.5.1\r"
        "PID|1||PT-EDGE\r"
        f"{obx_lines}"
    )


class TestMalformedOrTruncatedMsh3:
    """MSH-3 (Sending Application) arriving empty, partial, or otherwise
    degenerate must never crash parsing -- it must fall back to GENERIC."""

    def test_empty_msh3_defaults_to_generic(self) -> None:
        msg = _oru("", "OBX|1|NM|8867-4^HR^LN||72|/min||||F|||20240115100000\r")
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.GENERIC

    def test_empty_msh3_does_not_drop_the_loinc_obx(self) -> None:
        """A degenerate MSH-3 must not cascade into dropping otherwise-valid
        OBX segments -- vendor detection failure and code-mapping failure
        are independent failure modes."""
        msg = _oru("", "OBX|1|NM|8867-4^HR^LN||72|/min||||F|||20240115100000\r")
        result = _ADAPTER.parse(msg)
        assert result.skipped_obx_count == 0
        assert len(result.samples) == 1
        assert result.samples[0].vital_sign_type is VitalSignType.HEART_RATE

    def test_truncated_partial_vendor_name_does_not_partial_match(self) -> None:
        """"PHI" is a truncated fragment of "PHILIPS" -- _VENDOR_SUBSTRINGS
        does substring matching (`substring in msh_3`), so this documents
        that a too-short fragment simply does not match (no accidental
        partial-substring hit either direction) and falls back to GENERIC,
        rather than crashing or guessing."""
        msg = _oru("PHI", "OBX|1|NM|8867-4^HR^LN||72|/min||||F|||20240115100000\r")
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.GENERIC

    def test_msh_with_only_the_required_leading_fields_does_not_crash(self) -> None:
        """A minimal/degenerate MSH segment (no trailing fields beyond what
        MSH-3 detection reads) must still parse without raising."""
        msg = (
            "MSH|^~\\&|GENERIC\r"
            "PID|1||PT-EDGE\r"
            "OBX|1|NM|8867-4^HR^LN||72|/min||||F|||20240115100000\r"
        )
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.GENERIC
        assert len(result.samples) == 1


class TestMixedCaseVendorStrings:
    """_detect_vendor upper-cases MSH-3 before substring matching -- these
    tests pin that behavior explicitly rather than relying on it implicitly
    via the all-uppercase fixtures used elsewhere in this test suite."""

    def test_lowercase_philips_is_detected(self) -> None:
        msg = _oru("philips", "OBX|1|NM|HR^HR^MDC||88|bpm||||F|||20240115100000\r")
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.PHILIPS

    def test_mixed_case_draeger_is_detected(self) -> None:
        msg = _oru("DrAeGeR", "OBX|1|NM|HR^HR^MDC||88|bpm||||F|||20240115100000\r")
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.DRAEGER

    def test_mixed_case_mindray_beneview_is_detected(self) -> None:
        msg = _oru("Beneview_T8", "OBX|1|NM|HR^HR^MDC||88|bpm||||F|||20240115100000\r")
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.MINDRAY

    def test_lowercase_nihon_kohden_is_detected(self) -> None:
        msg = _oru("nihon_kohden_gw", "OBX|1|NM|HR^HR^MDC||88|bpm||||F|||20240115100000\r")
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.NIHON_KOHDEN


class TestAmbiguousVendorStringMatchesTwoEntries:
    """
    A single MSH-3 string can legitimately contain substrings that map to
    TWO DIFFERENT vendors simultaneously (e.g. a gateway/interface engine
    that concatenates source + destination system names). _VENDOR_SUBSTRINGS
    is checked in list order and returns on the FIRST match -- these tests
    pin that this is deterministic (not e.g. dict-ordering-dependent) and
    document, rather than silently rely on, the resulting tie-break.
    """

    def test_philips_wins_over_ge_when_both_substrings_present(self) -> None:
        """PHILIPS is earlier in _VENDOR_SUBSTRINGS than "GE " -- both
        substrings are present in this MSH-3, PHILIPS must win."""
        msg = _oru(
            "PHILIPS-TO-GE_BRIDGE",
            "OBX|1|NM|8867-4^HR^LN||72|/min||||F|||20240115100000\r",
        )
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.PHILIPS

    def test_draeger_wins_over_mindray_when_both_substrings_present(self) -> None:
        """DRAEGER appears before MINDRAY in _VENDOR_SUBSTRINGS."""
        msg = _oru(
            "DRAEGER_MINDRAY_GATEWAY",
            "OBX|1|NM|8867-4^HR^LN||72|/min||||F|||20240115100000\r",
        )
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.DRAEGER

    def test_result_is_deterministic_across_repeated_parses(self) -> None:
        """Same ambiguous MSH-3, parsed twice, must resolve to the same
        vendor both times -- guards against any non-deterministic iteration
        order ever creeping into _VENDOR_SUBSTRINGS's data structure."""
        msg = _oru(
            "PHILIPS-TO-GE_BRIDGE",
            "OBX|1|NM|8867-4^HR^LN||72|/min||||F|||20240115100000\r",
        )
        first = _ADAPTER.parse(msg).detected_vendor
        second = _ADAPTER.parse(msg).detected_vendor
        assert first is second is MonitorVendor.PHILIPS

    def test_ambiguous_match_does_not_affect_obx_mapping(self) -> None:
        """Vendor detection is informational/audit-only for LOINC-coded OBX
        segments (see _resolve_vital_type -- the `vendor` parameter is not
        actually used to gate resolution, only logged) -- the ambiguous
        vendor string must not prevent the OBX from being parsed."""
        msg = _oru(
            "PHILIPS-TO-GE_BRIDGE",
            "OBX|1|NM|8867-4^HR^LN||72|/min||||F|||20240115100000\r",
        )
        result = _ADAPTER.parse(msg)
        assert result.skipped_obx_count == 0
        assert len(result.samples) == 1


class TestLoincCodeMislabelledCodingSystemStillResolves:
    """
    ISO 14971 HAZARD-PROTO-001: a recognised LOINC identifier (present in
    _LOINC_TO_TYPE) is, by construction, never also present in
    _VENDOR_TO_TYPE (different namespaces -- numeric LOINC IDs like
    "8867-4" vs. short vendor mnemonics like "HR"). If OBX-3's coding
    system component is something OTHER than "LN"/"LOINC"/blank (so step 1
    of _resolve_vital_type is skipped), and the identifier is also not a
    vendor mnemonic (so step 2 fails too), the code must still resolve via
    step 3's best-effort LOINC fallback rather than being silently dropped
    as "unknown code, vendor=<whatever>".
    """

    def test_loinc_code_with_non_loinc_coding_system_still_resolves(self) -> None:
        # Coding system "MDC" (not LN/LOINC/blank) deliberately mislabels a
        # real LOINC heart-rate code.
        msg = _oru(
            "PHILIPS",
            "OBX|1|NM|8867-4^Heart rate^MDC||81|/min||||F|||20240115100000\r",
        )
        result = _ADAPTER.parse(msg)
        assert result.skipped_obx_count == 0
        assert len(result.samples) == 1
        assert result.samples[0].vital_sign_type is VitalSignType.HEART_RATE
        assert result.samples[0].value == 81.0

    def test_loinc_code_with_non_loinc_coding_system_on_generic_vendor(self) -> None:
        """Same fallback, but with vendor detection also landing on GENERIC
        (unrecognised MSH-3) -- both independent lookups (vendor detection,
        code resolution) must succeed/degrade on their own, not couple."""
        msg = _oru(
            "SOME_UNKNOWN_GATEWAY",
            "OBX|1|NM|59408-5^SpO2^MDC||96|%||||F|||20240115100000\r",
        )
        result = _ADAPTER.parse(msg)
        assert result.detected_vendor is MonitorVendor.GENERIC
        assert result.skipped_obx_count == 0
        assert len(result.samples) == 1
        assert result.samples[0].vital_sign_type is VitalSignType.SPO2

    def test_truly_unrecognised_code_is_still_dropped_with_audit_warning(self) -> None:
        """Contrast case: a code that is in NEITHER _LOINC_TO_TYPE NOR
        _VENDOR_TO_TYPE (regardless of coding system) is the one case that
        legitimately IS skipped -- and it must leave an audit trail, not
        disappear silently."""
        msg = _oru(
            "PHILIPS",
            "OBX|1|NM|99999-9^Totally Unknown Parameter^LN||1||||||F|||20240115100000\r",
        )
        result = _ADAPTER.parse(msg)
        assert result.skipped_obx_count == 1
        assert len(result.samples) == 0
        assert any("OBX-UNKNOWN" in w for w in result.parse_warnings)
