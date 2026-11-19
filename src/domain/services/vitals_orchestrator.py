"""
VitalsOrchestrator — Top-Level Domain Pipeline Service.

Wires the full domain pipeline in the correct sequence:
  1. VitalSignProcessor  → artifact rejection on each sample
  2. NEWS2Calculator     → aggregate clinical scoring
  3. VitalsAnalysisResult → immutable output ready for FHIR layer

IEC 62304 §5.8: This class is the domain integration seam — all domain
components are exercised together here. Its tests are integration tests
(tests/integration/).
ISO 14971 HAZARD-ARCH-001: The correct execution order is a risk control.
Swapping steps 1 and 2 would feed un-cleaned data into NEWS2 calculation.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

from domain.entities.news2_score import NEWS2Score
from domain.entities.patient_context import PatientContext
from domain.entities.score_outcome import Finding, ReasonCode, ScoringAssessment
from domain.entities.vital_sign import VitalSignSample, VitalSignType
from domain.services.news2_calculator import NEWS2Calculator, NEWS2InsufficientDataError
from domain.services.scoring_gate import ScoringGate
from domain.services.signal_processor import ProcessedVitalSign, VitalSignProcessor

_log: structlog.BoundLogger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class VitalsAnalysisResult:
    """
    Immutable top-level output of the ICU Edge Gateway domain pipeline.

    IEC 62304 §5.8: Primary artifact passed to the infrastructure FHIR layer.
    ISO 14971: All fields are read-only — prevents post-analysis score mutation.

    Attributes:
        patient_id:               From PatientContext.
        analysis_timestamp:       UTC time of result creation.
        processed_vitals:         Ordered tuple of DSP-cleaned vital signs.
        news2_score:              Complete NEWS2 Score (None if data insufficient).
        news2_missing_parameters: Vital types absent from input (incomplete score).
        processing_duration_ms:   End-to-end pipeline latency in milliseconds.
        pipeline_warnings:        Audit notes from processing stages.
        assessment:               Machine-readable outcome + reason codes
                                  (docs/assessment/PHASE1_DESIGN.md).
    """

    patient_id: str
    analysis_timestamp: datetime
    processed_vitals: tuple[ProcessedVitalSign, ...]
    news2_score: NEWS2Score | None
    news2_missing_parameters: tuple[VitalSignType, ...]
    processing_duration_ms: float
    pipeline_warnings: tuple[str, ...]
    assessment: ScoringAssessment


class VitalsOrchestrator:
    """
    Orchestrates the full domain pipeline from raw VitalSignSamples to a
    complete VitalsAnalysisResult containing NEWS2 Score.

    Stateless — safe for concurrent use within a FastAPI service.

    IEC 62304 §5.3: GoF Facade pattern — exposes a single analyse() method
    that encapsulates the full domain processing sequence.
    """

    def __init__(
        self,
        processor: VitalSignProcessor | None = None,
        calculator: NEWS2Calculator | None = None,
        gate: ScoringGate | None = None,
    ) -> None:
        self._processor = processor or VitalSignProcessor()
        self._calculator = calculator or NEWS2Calculator()
        self._gate = gate or ScoringGate()

    def analyse(
        self,
        samples: Sequence[VitalSignSample],
        context: PatientContext,
        upstream_findings: Sequence[Finding] = (),
    ) -> VitalsAnalysisResult:
        """
        Execute the full domain pipeline on a set of vital sign samples.

        IEC 62304 §5.8: Integration entry point — exercises all domain services.
        ISO 14971 HAZARD-ARCH-001: Processing order is enforced by design.
        FDA CDS: Returned NEWS2 score is advisory only — for display, not action.

        Args:
            samples: Raw VitalSignSample objects (from HL7 adapter or API).
            context: Patient context with SpO2 scale and patient ID.

        Returns:
            VitalsAnalysisResult with processed vitals, NEWS2 score, and audit data.
        """
        t_start = time.perf_counter()
        warnings: list[str] = []

        log = _log.bind(
            patient_id=context.patient_id,
            sample_count=len(samples),
        )
        log.info("vitals_orchestrator.analyse.start")

        # ── Stage 1: DSP Artifact Rejection ───────────────────────────────────
        processed: list[ProcessedVitalSign] = []
        for sample in samples:
            try:
                result = self._processor.process(sample)
                processed.append(result)
            except Exception as e:
                warn = (
                    f"[PROCESSOR-ERROR] Failed to process "
                    f"{sample.vital_sign_type.name}: {e}"
                )
                warnings.append(warn)
                log.warning("vitals_orchestrator.processor.error", error=str(e))

        # ── Stage 2: Scoring gate (A6 and later Phase 1 checks) ───────────────
        gate_result = self._gate.assess(processed, context, upstream_findings)
        assessment = gate_result.assessment
        critical_types = {
            f.parameter
            for f in assessment.findings
            if f.code is ReasonCode.CRITICAL_VALUE_REVIEW_REQUIRED
        }

        # Collect artifact / critical flags from processing
        for pv in processed:
            if not pv.is_within_physiological_bounds:
                vt = pv.original.vital_sign_type
                if vt in critical_types:
                    warnings.append(
                        f"[CRITICAL] {vt.name} value {pv.original.value!r} outside "
                        "plausibility bounds but physically possible — scored per "
                        "RCP 2017 tables; clinical review required."
                    )
                else:
                    warnings.append(
                        f"[ARTIFACT] {vt.name} value "
                        f"{pv.original.value!r} outside physiological bounds — "
                        "excluded from NEWS2 calculation."
                    )
            for note in pv.pipeline_notes:
                if "[HAMPEL]" in note and "0 motion" not in note:
                    warnings.append(note)

        # ── Stage 3: NEWS2 Calculation (only when the gate allows it) ─────────
        news2: NEWS2Score | None = None
        missing_types: tuple[VitalSignType, ...] = tuple(
            sorted(
                {
                    f.parameter
                    for f in assessment.findings
                    if f.code is ReasonCode.MISSING_PARAMETER
                    and f.parameter is not None
                },
                key=lambda t: t.value,
            )
        )

        if assessment.blocks_scoring:
            warnings.append(
                "[NEWS2-INCOMPLETE] No score computed. Reasons: "
                + ", ".join(assessment.reason_codes)
            )
            log.warning(
                "vitals_orchestrator.news2.withheld",
                reasons=list(assessment.reason_codes),
            )
        else:
            try:
                news2 = self._calculator.calculate(gate_result.scoring_inputs, context)
                log.info(
                    "vitals_orchestrator.news2.calculated",
                    total_score=news2.total,
                    risk_level=news2.risk_level.value,
                    outcome=assessment.outcome.value,
                )
            except NEWS2InsufficientDataError as e:  # defensive: gate should prevent
                warnings.append(f"[NEWS2-INCOMPLETE] {e}")
                log.warning("vitals_orchestrator.news2.insufficient_data", error=str(e))

        duration_ms = (time.perf_counter() - t_start) * 1000.0
        log.info(
            "vitals_orchestrator.analyse.complete",
            duration_ms=round(duration_ms, 2),
            warning_count=len(warnings),
        )

        return VitalsAnalysisResult(
            patient_id=context.patient_id,
            analysis_timestamp=datetime.now(tz=timezone.utc),
            processed_vitals=tuple(processed),
            news2_score=news2,
            news2_missing_parameters=missing_types,
            processing_duration_ms=duration_ms,
            pipeline_warnings=tuple(warnings),
            assessment=assessment,
        )
