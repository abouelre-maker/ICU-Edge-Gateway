"""
FHIR R4 Conformance Tests — Structural Validation.

IEC 62304 §5.7: Conformance tests verify FHIR R4 structural requirements
independent of clinical content.
ISO 14971 HAZARD-FHIR-001: All required fields must be present for EHR
interoperability — missing fields cause silent data loss in downstream systems.

Validation rules based on:
  - FHIR R4 Observation resource: http://hl7.org/fhir/R4/observation.html
  - FHIR R4 Bundle resource: http://hl7.org/fhir/R4/bundle.html
  - FHIR Vital Signs profile: http://hl7.org/fhir/StructureDefinition/vitalsigns
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.signal_processor import VitalSignProcessor
from domain.services.vitals_orchestrator import VitalsOrchestrator
from infrastructure.fhir.bundle_assembler import BundleAssembler
from infrastructure.fhir.news2_builder import NEWS2ObservationBuilder
from infrastructure.fhir.observation_builder import ObservationBuilder

_TS = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
_PROC = VitalSignProcessor()
_OBS_BUILDER = ObservationBuilder()
_NEWS2_BUILDER = NEWS2ObservationBuilder()
_ASSEMBLER = BundleAssembler()
_CTX = PatientContext(patient_id="PT-CONF-001", spo2_scale=SpO2Scale.SCALE_1)


def _obs(
    vital_type: VitalSignType, value: float, avpu: AVPULevel | None = None
) -> dict:  # type: ignore[type-arg]
    sample = VitalSignSample(
        vital_sign_type=vital_type,
        value=value,
        unit=VitalSignUnit.BPM,
        timestamp=_TS,
        avpu_level=avpu,
    )
    processed = _PROC.process(sample)
    return _OBS_BUILDER.build(processed, patient_id="PT-CONF-001")


# ── FHIR Observation Required Fields ──────────────────────────────────────────


@pytest.mark.parametrize(
    "vital_type,value,avpu",
    [
        (VitalSignType.HEART_RATE, 72.0, None),
        (VitalSignType.SPO2, 98.0, None),
        (VitalSignType.RESPIRATORY_RATE, 16.0, None),
        (VitalSignType.SYSTOLIC_BP, 120.0, None),
        (VitalSignType.TEMPERATURE_CELSIUS, 37.0, None),
        (VitalSignType.CONSCIOUSNESS, 0.0, AVPULevel.ALERT),
        (VitalSignType.SUPPLEMENTAL_O2, 0.0, None),
    ],
)
class TestObservationRequiredFields:
    """
    FHIR R4 Observation: Required fields must be present for all vital sign types.
    http://hl7.org/fhir/R4/observation.html
    """

    def test_has_resource_type(
        self, vital_type: VitalSignType, value: float, avpu: AVPULevel | None
    ) -> None:
        assert _obs(vital_type, value, avpu)["resourceType"] == "Observation"

    def test_has_id(
        self, vital_type: VitalSignType, value: float, avpu: AVPULevel | None
    ) -> None:
        assert "id" in _obs(vital_type, value, avpu)

    def test_has_status(
        self, vital_type: VitalSignType, value: float, avpu: AVPULevel | None
    ) -> None:
        assert "status" in _obs(vital_type, value, avpu)

    def test_has_code(
        self, vital_type: VitalSignType, value: float, avpu: AVPULevel | None
    ) -> None:
        obs = _obs(vital_type, value, avpu)
        assert "code" in obs
        assert "coding" in obs["code"]
        assert len(obs["code"]["coding"]) >= 1

    def test_has_subject(
        self, vital_type: VitalSignType, value: float, avpu: AVPULevel | None
    ) -> None:
        obs = _obs(vital_type, value, avpu)
        assert "subject" in obs
        assert "reference" in obs["subject"]

    def test_has_effective_date_time(
        self, vital_type: VitalSignType, value: float, avpu: AVPULevel | None
    ) -> None:
        obs = _obs(vital_type, value, avpu)
        assert "effectiveDateTime" in obs, (
            "Observation.effectiveDateTime required for vital sign timestamp. "
            "ISO 14971 HAZARD-TIME-001."
        )

    def test_has_category_vital_signs(
        self, vital_type: VitalSignType, value: float, avpu: AVPULevel | None
    ) -> None:
        obs = _obs(vital_type, value, avpu)
        assert "category" in obs
        category_codes = [
            c["code"] for cat in obs["category"] for c in cat.get("coding", [])
        ]
        assert "vital-signs" in category_codes or "survey" in category_codes

    def test_has_loinc_code(
        self, vital_type: VitalSignType, value: float, avpu: AVPULevel | None
    ) -> None:
        obs = _obs(vital_type, value, avpu)
        loinc_codings = [
            c for c in obs["code"]["coding"] if c.get("system") == "http://loinc.org"
        ]
        assert len(loinc_codings) >= 1, (
            f"All Observations must have a LOINC code. "
            f"VitalSignType.{vital_type.name} missing LOINC. "
            "ISO 14971 HAZARD-FHIR-001."
        )

    def test_effective_datetime_is_iso8601_with_timezone(
        self, vital_type: VitalSignType, value: float, avpu: AVPULevel | None
    ) -> None:
        obs = _obs(vital_type, value, avpu)
        dt_str: str = obs["effectiveDateTime"]
        # Must contain timezone info (Z or +HH:MM)
        assert "Z" in dt_str or "+" in dt_str or "-" in dt_str[10:], (
            f"effectiveDateTime '{dt_str}' must include timezone. "
            "FHIR R4 dateTime with timezone required for cross-system interop."
        )


# ── FHIR Observation Value Presence ───────────────────────────────────────────


class TestObservationValuePresence:
    """
    In-bounds observations must have a value[x] field.
    Out-of-bounds observations must have dataAbsentReason.
    Both must NEVER be present simultaneously (FHIR R4 §10.1.5).
    """

    def test_normal_hr_has_value_quantity(self) -> None:
        obs = _obs(VitalSignType.HEART_RATE, 72.0)
        assert "valueQuantity" in obs
        assert "dataAbsentReason" not in obs

    def test_out_of_range_hr_has_absent_reason(self) -> None:
        obs = _obs(VitalSignType.HEART_RATE, 5.0)  # Below 10 bpm — out of bounds
        assert "dataAbsentReason" in obs
        assert "valueQuantity" not in obs

    def test_value_quantity_has_ucum_system(self) -> None:
        obs = _obs(VitalSignType.HEART_RATE, 72.0)
        assert obs["valueQuantity"]["system"] == "http://unitsofmeasure.org"

    def test_consciousness_has_value_codeable_concept(self) -> None:
        obs = _obs(VitalSignType.CONSCIOUSNESS, 0.0, avpu=AVPULevel.ALERT)
        assert "valueCodeableConcept" in obs
        assert "valueQuantity" not in obs

    def test_supplemental_o2_has_value_boolean(self) -> None:
        obs = _obs(VitalSignType.SUPPLEMENTAL_O2, 0.0)
        assert "valueBoolean" in obs
        assert isinstance(obs["valueBoolean"], bool)


# ── FHIR Bundle Conformance ────────────────────────────────────────────────────


class TestBundleConformance:
    """
    FHIR R4 Bundle required fields.
    http://hl7.org/fhir/R4/bundle.html
    """

    def _build_bundle(self) -> dict:  # type: ignore[type-arg]
        orch = VitalsOrchestrator()
        samples = [
            VitalSignSample(VitalSignType.HEART_RATE, 72.0, VitalSignUnit.BPM, _TS),
            VitalSignSample(
                VitalSignType.RESPIRATORY_RATE, 16.0, VitalSignUnit.BREATHS_PER_MIN, _TS
            ),
            VitalSignSample(VitalSignType.SPO2, 98.0, VitalSignUnit.PERCENT, _TS),
            VitalSignSample(VitalSignType.SYSTOLIC_BP, 120.0, VitalSignUnit.MMHG, _TS),
            VitalSignSample(
                VitalSignType.TEMPERATURE_CELSIUS, 37.0, VitalSignUnit.CELSIUS, _TS
            ),
            VitalSignSample(
                VitalSignType.SUPPLEMENTAL_O2, 0.0, VitalSignUnit.BOOLEAN, _TS
            ),
            VitalSignSample(
                VitalSignType.CONSCIOUSNESS,
                0.0,
                VitalSignUnit.AVPU_SCALE,
                _TS,
                avpu_level=AVPULevel.ALERT,
            ),
        ]
        result = orch.analyse(samples, _CTX)
        return _ASSEMBLER.assemble(result, _CTX)

    def test_bundle_has_resource_type(self) -> None:
        assert self._build_bundle()["resourceType"] == "Bundle"

    def test_bundle_has_id(self) -> None:
        assert "id" in self._build_bundle()

    def test_bundle_type_is_collection(self) -> None:
        assert self._build_bundle()["type"] == "collection"

    def test_bundle_has_timestamp(self) -> None:
        assert "timestamp" in self._build_bundle()

    def test_all_entries_have_full_url(self) -> None:
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            assert "fullUrl" in entry, (
                "All Bundle entries must have fullUrl. "
                "FHIR R4 §3.3.1: fullUrl uniquely identifies each entry."
            )

    def test_all_entries_have_resource(self) -> None:
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            assert "resource" in entry

    def test_full_urls_are_unique(self) -> None:
        bundle = self._build_bundle()
        full_urls = [e["fullUrl"] for e in bundle["entry"]]
        assert len(full_urls) == len(set(full_urls)), (
            "All Bundle entry fullUrls must be unique. " "FHIR R4 §3.3.1."
        )

    def test_bundle_entry_ids_are_unique(self) -> None:
        bundle = self._build_bundle()
        resource_ids = [
            e["resource"].get("id", "")
            for e in bundle["entry"]
            if e["resource"]["resourceType"] != "OperationOutcome"
        ]
        assert len(resource_ids) == len(set(resource_ids))
