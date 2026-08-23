"""
Unit Tests — infrastructure.streaming.fhir_bundle_utils.

extract_news2_summary() is verified against a Bundle produced by the real
domain pipeline + BundleAssembler (not a hand-crafted fixture) so a change
to news2_builder.py's FHIR encoding would break this test rather than
silently making the dashboard delta's `news2` field wrong.
"""

from __future__ import annotations

from datetime import datetime, timezone

from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.vitals_orchestrator import VitalsOrchestrator
from infrastructure.fhir.bundle_assembler import BundleAssembler
from infrastructure.streaming.fhir_bundle_utils import (
    extract_news2_summary,
    extract_patient_id,
)

_TS = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def _full_vitals_bundle(patient_id: str = "PT-UTIL-001") -> dict:
    samples = [
        VitalSignSample(
            VitalSignType.RESPIRATORY_RATE, 16, VitalSignUnit.BREATHS_PER_MIN, _TS
        ),
        VitalSignSample(VitalSignType.SPO2, 98.0, VitalSignUnit.PERCENT, _TS),
        VitalSignSample(VitalSignType.SYSTOLIC_BP, 120.0, VitalSignUnit.MMHG, _TS),
        VitalSignSample(VitalSignType.HEART_RATE, 72.0, VitalSignUnit.BPM, _TS),
        VitalSignSample(
            VitalSignType.TEMPERATURE_CELSIUS, 37.0, VitalSignUnit.CELSIUS, _TS
        ),
        VitalSignSample(VitalSignType.SUPPLEMENTAL_O2, 0.0, VitalSignUnit.BOOLEAN, _TS),
        VitalSignSample(
            VitalSignType.CONSCIOUSNESS,
            0.0,
            VitalSignUnit.AVPU_SCALE,
            _TS,
            avpu_level=AVPULevel.ALERT,
        ),
    ]
    context = PatientContext(patient_id=patient_id, spo2_scale=SpO2Scale.SCALE_1)
    result = VitalsOrchestrator().analyse(samples=samples, context=context)
    return BundleAssembler().assemble(result=result, patient_context=context)


def _partial_vitals_bundle_no_news2() -> dict:
    samples = [
        VitalSignSample(VitalSignType.HEART_RATE, 72.0, VitalSignUnit.BPM, _TS),
    ]
    context = PatientContext(patient_id="PT-UTIL-002", spo2_scale=SpO2Scale.SCALE_1)
    result = VitalsOrchestrator().analyse(samples=samples, context=context)
    return BundleAssembler().assemble(result=result, patient_context=context)


class TestExtractPatientId:
    def test_extracts_from_real_bundle(self) -> None:
        bundle = _full_vitals_bundle(patient_id="PT-UTIL-001")
        assert extract_patient_id(bundle) == "PT-UTIL-001"

    def test_returns_unknown_for_empty_bundle(self) -> None:
        assert extract_patient_id({"entry": []}) == "UNKNOWN"


class TestExtractNews2Summary:
    def test_extracts_total_and_risk_level_from_real_bundle(self) -> None:
        bundle = _full_vitals_bundle()
        summary = extract_news2_summary(bundle)
        assert summary is not None
        assert summary["total"] == 0  # all-normal vitals -> NEWS2 total 0
        assert summary["risk_level"] == "NORMAL"

    def test_returns_none_when_bundle_has_no_news2_observation(self) -> None:
        bundle = _partial_vitals_bundle_no_news2()
        assert extract_news2_summary(bundle) is None

    def test_returns_none_for_empty_bundle(self) -> None:
        assert extract_news2_summary({"entry": []}) is None
