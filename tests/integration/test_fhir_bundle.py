"""
Integration Tests — FHIR R4 Bundle and Observation Construction.

IEC 62304 §5.7: Integration tests verify ObservationBuilder, NEWS2ObservationBuilder,
and BundleAssembler produce correctly structured FHIR R4 resources.
ISO 14971 HAZARD-FHIR-001/002/003: Validates all FHIR safety-critical fields.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.entities.device_context import DeviceContext, HL7Version, MonitorVendor
from domain.entities.news2_score import NEWS2Score
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import AVPULevel, VitalSignSample, VitalSignType, VitalSignUnit
from domain.services.signal_processor import VitalSignProcessor
from domain.services.vitals_orchestrator import VitalsOrchestrator
from infrastructure.fhir.bundle_assembler import BundleAssembler
from infrastructure.fhir.news2_builder import NEWS2ObservationBuilder
from infrastructure.fhir.observation_builder import ObservationBuilder

_UTC = timezone.utc
_TS = datetime(2024, 1, 15, 10, 0, 0, tzinfo=_UTC)
_PROC = VitalSignProcessor()
_OBS_BUILDER = ObservationBuilder()
_NEWS2_BUILDER = NEWS2ObservationBuilder()
_BUNDLE_ASSEMBLER = BundleAssembler()
_PATIENT_CTX = PatientContext(patient_id="PT-FHIR-001", spo2_scale=SpO2Scale.SCALE_1)
_DEVICE_CTX = DeviceContext(
    device_id="DEV-ICU-001",
    vendor=MonitorVendor.PHILIPS,
    model="IntelliVue MX800",
    hl7_version=HL7Version.V2_5_1,
    location="ICU-BED-07-A",
)


def _make_processed(vital_type: VitalSignType, value: float, avpu: AVPULevel | None = None):  # type: ignore[return]
    sample = VitalSignSample(
        vital_sign_type=vital_type,
        value=value,
        unit=VitalSignUnit.BPM,  # unit unused in tests — builder uses FHIR map
        timestamp=_TS,
        avpu_level=avpu,
    )
    return _PROC.process(sample)


def _make_news2_score(total_override: int = 0) -> NEWS2Score:
    return NEWS2Score(
        resp_rate_score=0,
        spo2_score=0,
        supplemental_o2_score=0,
        systolic_bp_score=total_override,
        heart_rate_score=0,
        consciousness_score=0,
        temperature_score=0,
        calculated_at=_TS,
    )


# ── ObservationBuilder Tests ───────────────────────────────────────────────────


class TestObservationBuilderHeartRate:
    def test_resource_type_is_observation(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.HEART_RATE, 72.0),
            patient_id="PT-001",
        )
        assert obs["resourceType"] == "Observation"

    def test_status_is_final(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.HEART_RATE, 72.0),
            patient_id="PT-001",
        )
        assert obs["status"] == "final"

    def test_code_contains_loinc_8867_4(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.HEART_RATE, 72.0),
            patient_id="PT-001",
        )
        loinc_codes = [
            c["code"]
            for c in obs["code"]["coding"]
            if c["system"] == "http://loinc.org"
        ]
        assert "8867-4" in loinc_codes, (
            "Heart rate Observation must have LOINC 8867-4. "
            "ISO 14971 HAZARD-FHIR-001."
        )

    def test_code_contains_snomed_364075005(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.HEART_RATE, 72.0),
            patient_id="PT-001",
        )
        snomed_codes = [
            c["code"]
            for c in obs["code"]["coding"]
            if c["system"] == "http://snomed.info/sct"
        ]
        assert "364075005" in snomed_codes

    def test_value_quantity_is_correct(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.HEART_RATE, 72.0),
            patient_id="PT-001",
        )
        vq = obs.get("valueQuantity")
        assert vq is not None
        assert vq["value"] == 72.0
        assert vq["system"] == "http://unitsofmeasure.org"

    def test_subject_reference_set(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.HEART_RATE, 72.0),
            patient_id="PT-FHIR-001",
        )
        assert obs["subject"]["reference"] == "Patient/PT-FHIR-001"

    def test_device_reference_set_when_provided(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.HEART_RATE, 72.0),
            patient_id="PT-001",
            device_id="DEV-001",
        )
        assert obs["device"]["reference"] == "Device/DEV-001"

    def test_iec62304_extension_present(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.HEART_RATE, 72.0),
            patient_id="PT-001",
        )
        ext_urls = [e["url"] for e in obs.get("extension", [])]
        assert any("iec62304" in url for url in ext_urls)

    def test_empty_patient_id_raises(self) -> None:
        with pytest.raises(ValueError, match="patient_id"):
            _OBS_BUILDER.build(
                _make_processed(VitalSignType.HEART_RATE, 72.0),
                patient_id="",
            )


class TestObservationBuilderConsciousness:
    """AVPU consciousness observations use valueCodeableConcept, not valueQuantity."""

    def test_avpu_uses_value_codeable_concept(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.CONSCIOUSNESS, 0.0, avpu=AVPULevel.ALERT),
            patient_id="PT-001",
        )
        assert "valueCodeableConcept" in obs
        assert "valueQuantity" not in obs

    def test_new_confusion_maps_to_correct_snomed(self) -> None:
        obs = _OBS_BUILDER.build(
            _make_processed(VitalSignType.CONSCIOUSNESS, 0.0, avpu=AVPULevel.NEW_CONFUSION),
            patient_id="PT-001",
        )
        vcc = obs["valueCodeableConcept"]
        snomed_codes = [c["code"] for c in vcc["coding"]]
        assert "40917007" in snomed_codes, (
            "NEW_CONFUSION must map to SNOMED 40917007 (Clouded consciousness). "
            "ISO 14971 HAZARD-CON-001."
        )


class TestObservationBuilderOutOfBounds:
    """Out-of-bounds samples get dataAbsentReason instead of valueQuantity."""

    def test_out_of_bounds_sets_data_absent_reason(self) -> None:
        # HR=5 is outside physiological bounds (min=10 bpm)
        processed = _make_processed(VitalSignType.HEART_RATE, 5.0)
        obs = _OBS_BUILDER.build(processed, patient_id="PT-001")
        assert "dataAbsentReason" in obs
        assert "valueQuantity" not in obs

    def test_out_of_bounds_code_is_out_of_range(self) -> None:
        processed = _make_processed(VitalSignType.HEART_RATE, 5.0)
        obs = _OBS_BUILDER.build(processed, patient_id="PT-001")
        codes = [c["code"] for c in obs["dataAbsentReason"]["coding"]]
        assert "out-of-range" in codes


# ── NEWS2ObservationBuilder Tests ──────────────────────────────────────────────


class TestNEWS2ObservationBuilder:
    def test_resource_type_is_observation(self) -> None:
        score = _make_news2_score()
        obs = _NEWS2_BUILDER.build(score, patient_id="PT-001")
        assert obs["resourceType"] == "Observation"

    def test_code_contains_news2_snomed(self) -> None:
        score = _make_news2_score()
        obs = _NEWS2_BUILDER.build(score, patient_id="PT-001")
        snomed_codes = [
            c["code"]
            for c in obs["code"]["coding"]
            if c["system"] == "http://snomed.info/sct"
        ]
        assert "1239842005" in snomed_codes, (
            "NEWS2 Observation must use SNOMED CT 1239842005. "
            "ISO 14971 HAZARD-FHIR-002."
        )

    def test_total_score_is_integer(self) -> None:
        score = _make_news2_score(total_override=3)
        obs = _NEWS2_BUILDER.build(score, patient_id="PT-001")
        assert obs["valueInteger"] == 3
        assert isinstance(obs["valueInteger"], int), (
            "NEWS2 total must be integer — float would corrupt downstream derivation. "
            "ISO 14971 HAZARD-FHIR-002."
        )

    def test_has_seven_component_scores(self) -> None:
        score = _make_news2_score()
        obs = _NEWS2_BUILDER.build(score, patient_id="PT-001")
        assert len(obs["component"]) == 7

    def test_fda_cds_advisory_extension_present(self) -> None:
        score = _make_news2_score()
        obs = _NEWS2_BUILDER.build(score, patient_id="PT-001")
        advisory_exts = [
            e for e in obs["extension"]
            if "cds-advisory-only" in e.get("url", "")
        ]
        assert len(advisory_exts) == 1
        assert advisory_exts[0]["valueBoolean"] is True

    def test_risk_level_extension_present(self) -> None:
        score = NEWS2Score.zero()
        obs = _NEWS2_BUILDER.build(score, patient_id="PT-001")
        risk_exts = [
            e for e in obs["extension"]
            if "news2-risk-level" in e.get("url", "")
        ]
        assert len(risk_exts) == 1
        assert risk_exts[0]["valueCode"] == "NORMAL"

    def test_note_contains_advisory_text(self) -> None:
        score = _make_news2_score()
        obs = _NEWS2_BUILDER.build(score, patient_id="PT-001")
        all_notes = " ".join(n["text"] for n in obs.get("note", []))
        assert "advisory" in all_notes.lower()

    def test_category_is_survey(self) -> None:
        score = _make_news2_score()
        obs = _NEWS2_BUILDER.build(score, patient_id="PT-001")
        codes = [
            c["code"]
            for cat in obs["category"]
            for c in cat["coding"]
        ]
        assert "survey" in codes


# ── BundleAssembler Tests ──────────────────────────────────────────────────────


class TestBundleAssembler:
    def _make_full_result(self):  # type: ignore[return]
        from domain.services.vitals_orchestrator import VitalsOrchestrator
        orch = VitalsOrchestrator()
        samples = [
            VitalSignSample(VitalSignType.HEART_RATE, 72.0, VitalSignUnit.BPM, _TS),
            VitalSignSample(VitalSignType.RESPIRATORY_RATE, 16.0, VitalSignUnit.BREATHS_PER_MIN, _TS),
            VitalSignSample(VitalSignType.SPO2, 98.0, VitalSignUnit.PERCENT, _TS),
            VitalSignSample(VitalSignType.SYSTOLIC_BP, 120.0, VitalSignUnit.MMHG, _TS),
            VitalSignSample(VitalSignType.TEMPERATURE_CELSIUS, 37.0, VitalSignUnit.CELSIUS, _TS),
            VitalSignSample(VitalSignType.SUPPLEMENTAL_O2, 0.0, VitalSignUnit.BOOLEAN, _TS),
            VitalSignSample(
                VitalSignType.CONSCIOUSNESS, 0.0, VitalSignUnit.AVPU_SCALE, _TS,
                avpu_level=AVPULevel.ALERT
            ),
        ]
        return orch.analyse(samples, _PATIENT_CTX)

    def test_resource_type_is_bundle(self) -> None:
        result = self._make_full_result()
        bundle = _BUNDLE_ASSEMBLER.assemble(result, _PATIENT_CTX, _DEVICE_CTX)
        assert bundle["resourceType"] == "Bundle"

    def test_bundle_type_is_collection(self) -> None:
        result = self._make_full_result()
        bundle = _BUNDLE_ASSEMBLER.assemble(result, _PATIENT_CTX, _DEVICE_CTX)
        assert bundle["type"] == "collection"

    def test_bundle_has_timestamp(self) -> None:
        result = self._make_full_result()
        bundle = _BUNDLE_ASSEMBLER.assemble(result, _PATIENT_CTX, _DEVICE_CTX)
        assert "timestamp" in bundle, (
            "Bundle.timestamp is required. ISO 14971 HAZARD-FHIR-003."
        )

    def test_bundle_contains_device_entry(self) -> None:
        result = self._make_full_result()
        bundle = _BUNDLE_ASSEMBLER.assemble(result, _PATIENT_CTX, _DEVICE_CTX)
        device_entries = [
            e for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Device"
        ]
        assert len(device_entries) == 1
        assert device_entries[0]["resource"]["manufacturer"] == "PHILIPS"

    def test_bundle_contains_news2_observation(self) -> None:
        result = self._make_full_result()
        bundle = _BUNDLE_ASSEMBLER.assemble(result, _PATIENT_CTX, _DEVICE_CTX)
        news2_entries = [
            e for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Observation"
            and any(
                c.get("code") == "1239842005"
                for cat in e["resource"].get("code", {}).get("coding", [])
                for c in [cat]
            )
        ]
        assert len(news2_entries) == 1

    def test_bundle_total_matches_entry_count(self) -> None:
        result = self._make_full_result()
        bundle = _BUNDLE_ASSEMBLER.assemble(result, _PATIENT_CTX, _DEVICE_CTX)
        assert bundle["total"] == len(bundle["entry"])

    def test_bundle_without_device_has_no_device_entry(self) -> None:
        result = self._make_full_result()
        bundle = _BUNDLE_ASSEMBLER.assemble(result, _PATIENT_CTX, device_context=None)
        device_entries = [
            e for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Device"
        ]
        assert len(device_entries) == 0