"""
ScoringGate — decides whether a NEWS2 score may be computed, and from what.

Runs between VitalSignProcessor (DSP) and NEWS2Calculator. It never changes
the RCP 2017 band tables (R6): NEWS2Calculator is untouched and remains the
only place a score is computed. The gate only decides *what reaches* the
calculator and records every reason in machine-readable form.

A6 (docs/assessment/PHASE1_DESIGN.md §3, decision Q2): a finite, physically
possible value outside PhysiologicalBoundsChecker's plausibility bounds is
CRITICAL, not an artifact. It is passed to the calculator (so a downstream
consumer that reads only the number sees a high score, never "no score") and
flagged CRITICAL_VALUE_REVIEW_REQUIRED with the measured value preserved.
Only physically impossible data stays an artifact. No bound value changes.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from dataclasses import dataclass

from domain.entities.patient_context import PatientContext
from domain.entities.score_outcome import (
    Finding,
    ReasonCode,
    ScoringAssessment,
    resolve_outcome,
)
from domain.entities.vital_sign import VitalSignType
from domain.services.signal_processor import ProcessedVitalSign

# The five numeric NEWS2 inputs (same set as news2_calculator._REQUIRED_VITAL_TYPES).
_NUMERIC_REQUIRED: tuple[VitalSignType, ...] = (
    VitalSignType.RESPIRATORY_RATE,
    VitalSignType.SPO2,
    VitalSignType.SYSTOLIC_BP,
    VitalSignType.HEART_RATE,
    VitalSignType.TEMPERATURE_CELSIUS,
)


def is_physically_impossible(vital_type: VitalSignType, value: float) -> bool:
    """
    True only for data that cannot be a real measurement. This is a definition
    of impossibility, not a clinical threshold: NaN/Inf, negative magnitudes,
    saturation above 100 %, or an O2 flag that is neither 0 nor 1.
    """
    if not math.isfinite(value) or value < 0:
        return True
    if vital_type is VitalSignType.SPO2 and value > 100.0:
        return True
    return vital_type is VitalSignType.SUPPLEMENTAL_O2 and value not in (0.0, 1.0)


@dataclass(frozen=True)
class GateResult:
    assessment: ScoringAssessment
    # What the calculator may see: critical values re-admitted, artifacts not.
    scoring_inputs: tuple[ProcessedVitalSign, ...]


class ScoringGate:
    def assess(
        self,
        processed: Sequence[ProcessedVitalSign],
        context: PatientContext,  # noqa: ARG002 - used by later checks (scale-aware bands)
        upstream_findings: Sequence[Finding] = (),
    ) -> GateResult:
        findings: list[Finding] = list(upstream_findings)
        inputs: list[ProcessedVitalSign] = []

        for pv in processed:
            sample = pv.original
            # Waveform samples carry a 0.0 placeholder scalar by design
            # (hl7v2_adapter._build_waveform_sample); they are never scalar
            # readings and are classified neither critical nor artifact.
            if pv.is_within_physiological_bounds or sample.waveform is not None:
                inputs.append(pv)
                continue
            if is_physically_impossible(sample.vital_sign_type, sample.value):
                findings.append(
                    Finding(
                        ReasonCode.ARTIFACT_EXCLUDED,
                        sample.vital_sign_type,
                        "Physically impossible value excluded as artifact.",
                        None if math.isnan(sample.value) else sample.value,
                    )
                )
                inputs.append(pv)  # stays out-of-bounds: calculator ignores it
                continue
            findings.append(
                Finding(
                    ReasonCode.CRITICAL_VALUE_REVIEW_REQUIRED,
                    sample.vital_sign_type,
                    "Value outside plausibility bounds but physically possible: "
                    "scored per RCP 2017 tables; review required.",
                    sample.value,
                )
            )
            inputs.append(dataclasses.replace(pv, is_within_physiological_bounds=True))

        admitted = {
            pv.original.vital_sign_type
            for pv in inputs
            if pv.is_within_physiological_bounds and pv.original.waveform is None
        }
        for vt in _NUMERIC_REQUIRED:
            if vt not in admitted:
                findings.append(
                    Finding(
                        ReasonCode.MISSING_PARAMETER,
                        vt,
                        "Required NEWS2 input absent or excluded.",
                    )
                )

        # A1: consciousness and O2 status are mandatory NEWS2 inputs. Their
        # absence must never default to Alert / room air (a false NORMAL).
        if not any(
            pv.original.vital_sign_type is VitalSignType.CONSCIOUSNESS
            and pv.original.avpu_level is not None
            for pv in inputs
        ):
            findings.append(
                Finding(
                    ReasonCode.MISSING_CONSCIOUSNESS,
                    VitalSignType.CONSCIOUSNESS,
                    "No level-of-consciousness (ACVPU) observation; not assumed Alert.",
                )
            )
        if VitalSignType.SUPPLEMENTAL_O2 not in admitted:
            findings.append(
                Finding(
                    ReasonCode.MISSING_O2_STATUS,
                    VitalSignType.SUPPLEMENTAL_O2,
                    "No air/supplemental-oxygen observation; not assumed room air.",
                )
            )

        used = [
            pv.original.timestamp
            for pv in inputs
            if pv.is_within_physiological_bounds and pv.original.waveform is None
        ]
        frozen = tuple(findings)
        return GateResult(
            assessment=ScoringAssessment(
                outcome=resolve_outcome(frozen),
                findings=frozen,
                observation_time=max(used) if used else None,
            ),
            scoring_inputs=tuple(inputs),
        )
