"""
Regulatory Test — ISO 14971 HAZARD-ARCH-001 Structural Pipeline-Order Guard.

Phase 5 Section A requires: "Preserve the existing invariant (HAZARD-ARCH-001):
DSP cleaning must execute before NEWS2 scoring, enforced structurally, verified
by a new automated test that would fail if the order were ever swapped."

This file adds NO changes to domain/services/news2_calculator.py,
domain/services/signal_processor.py, or domain/entities/news2_score.py
(HARD CONSTRAINT #1) — it is a pure regression lock around the existing,
unmodified VitalsOrchestrator.analyse() seam, using method-spying rather than
behavior changes.

The test fails if either:
  (a) NEWS2Calculator.calculate() is invoked before VitalSignProcessor.process()
      has completed for every sample handed to VitalsOrchestrator.analyse(), or
  (b) NEWS2Calculator.calculate() is ever invoked with an object that is not a
      ProcessedVitalSign — i.e. someone routes raw, un-cleaned VitalSignSample
      data directly into NEWS2 scoring, bypassing the DSP stage entirely.

Guard (b) is the stronger structural check: ProcessedVitalSign instances can
only be produced by VitalSignProcessor.process(), so calculate() receiving
one is proof DSP cleaning ran first for that sample — not just proof the two
calls happened in the right order in this one execution.
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
from domain.services.news2_calculator import NEWS2Calculator
from domain.services.signal_processor import ProcessedVitalSign, VitalSignProcessor
from domain.services.vitals_orchestrator import VitalsOrchestrator

_UTC = timezone.utc
_TS = datetime(2024, 1, 15, 10, 0, 0, tzinfo=_UTC)


def _full_valid_samples() -> list[VitalSignSample]:
    return [
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


class TestHazardArch001PipelineOrder:
    def test_calculator_only_ever_receives_processed_vital_signs(self) -> None:
        """Guard (b): calculate() must never see a raw VitalSignSample."""
        real_calculate = NEWS2Calculator.calculate
        received_types: list[type] = []

        def spying_calculate(self, processed, *args, **kwargs):  # type: ignore[no-untyped-def]
            received_types.extend(type(p) for p in processed)
            return real_calculate(self, processed, *args, **kwargs)

        orchestrator = VitalsOrchestrator()
        context = PatientContext(patient_id="PT-ARCH-001", spo2_scale=SpO2Scale.SCALE_1)

        NEWS2Calculator.calculate = spying_calculate  # type: ignore[method-assign]
        try:
            result = orchestrator.analyse(
                samples=_full_valid_samples(), context=context
            )
        finally:
            NEWS2Calculator.calculate = real_calculate  # type: ignore[method-assign]

        assert result.news2_score is not None, (
            "Test fixture must produce a complete NEWS2 score — "
            "otherwise calculate() is never reached and this guard is vacuous."
        )
        assert received_types, "NEWS2Calculator.calculate() was never invoked."
        assert all(t is ProcessedVitalSign for t in received_types), (
            f"HAZARD-ARCH-001 VIOLATION: NEWS2Calculator.calculate() received "
            f"non-ProcessedVitalSign object(s): {received_types}. DSP artifact "
            "rejection was bypassed."
        )

    def test_every_processed_sample_precedes_the_calculate_call(self) -> None:
        """Guard (a): process() must be called for every sample before calculate()."""
        real_process = VitalSignProcessor.process
        real_calculate = NEWS2Calculator.calculate
        call_order: list[str] = []

        def spying_process(self, sample, *args, **kwargs):  # type: ignore[no-untyped-def]
            result = real_process(self, sample, *args, **kwargs)
            call_order.append("process")
            return result

        def spying_calculate(self, processed, *args, **kwargs):  # type: ignore[no-untyped-def]
            call_order.append("calculate")
            return real_calculate(self, processed, *args, **kwargs)

        orchestrator = VitalsOrchestrator()
        context = PatientContext(
            patient_id="PT-ARCH-001b", spo2_scale=SpO2Scale.SCALE_1
        )
        samples = _full_valid_samples()

        VitalSignProcessor.process = spying_process  # type: ignore[method-assign]
        NEWS2Calculator.calculate = spying_calculate  # type: ignore[method-assign]
        try:
            orchestrator.analyse(samples=samples, context=context)
        finally:
            VitalSignProcessor.process = real_process  # type: ignore[method-assign]
            NEWS2Calculator.calculate = real_calculate  # type: ignore[method-assign]

        assert call_order.count("process") == len(samples)
        assert call_order.count("calculate") == 1
        first_calculate_index = call_order.index("calculate")
        assert all(call == "process" for call in call_order[:first_calculate_index]), (
            f"HAZARD-ARCH-001 VIOLATION: calculate() was invoked before all "
            f"{len(samples)} samples finished DSP processing. Call order was: "
            f"{call_order}"
        )
        assert call_order[:first_calculate_index].count("process") == len(
            samples
        ), "Not all samples were processed before NEWS2 calculation began."
