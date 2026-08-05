"""
VitalSignProcessor — DSP Pipeline Orchestrator.

Applies the full artifact rejection pipeline to a VitalSignSample:
  Stage 1: Physiological bounds checking (numeric value)
  Stage 2: Dual notch filter 50/60 Hz (waveform — if present)
  Stage 3: Bandpass filter (waveform — if present and type is supported)
  Stage 4: Hampel motion artifact rejection (waveform — if present)

IEC 62304 §5.3: Single-responsibility orchestrator — contains no filter logic itself.
ISO 14971 HAZARD-DSP-001 through HAZARD-DSP-004: Controls addressed by the
injected filter instances; this class manages execution order only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from domain.entities.vital_sign import VitalSignSample, VitalSignType
from domain.services.artifact_rejector import (
    BandpassFilter,
    DualNotchFilter,
    HampelFilter,
    PhysiologicalBoundsChecker,
)

# Vital sign types that support waveform processing (have bandpass ranges)
_WAVEFORM_CAPABLE_TYPES: frozenset[VitalSignType] = frozenset({
    VitalSignType.HEART_RATE,
    VitalSignType.RESPIRATORY_RATE,
    VitalSignType.SPO2,
    VitalSignType.SYSTOLIC_BP,
    VitalSignType.DIASTOLIC_BP,
})


@dataclass(frozen=True)
class ProcessedVitalSign:
    """
    Immutable result of the DSP pipeline applied to one VitalSignSample.

    IEC 62304 §5.2 REQ-PROC-001: Primary data unit flowing into NEWS2Calculator.
    Fields:
        original:                    Input sample (preserved for audit).
        cleaned_value:               Validated numeric value (artifact-checked).
        cleaned_waveform:            Filtered waveform (None if no waveform input).
        is_within_physiological_bounds: False = instrument error; exclude from NEWS2.
        outlier_count:               Waveform samples replaced by Hampel filter.
        pipeline_notes:              Ordered audit log of processing decisions.
        processed_at:                UTC timestamp of processing completion.
    """

    original: VitalSignSample
    cleaned_value: float
    cleaned_waveform: tuple[float, ...] | None
    is_within_physiological_bounds: bool
    outlier_count: int
    pipeline_notes: tuple[str, ...]
    processed_at: datetime


@dataclass
class VitalSignProcessor:
    """
    Orchestrates the four-stage DSP pipeline for a single VitalSignSample.

    Injected dependencies (GoF Strategy — all satisfy IFilterStrategy):
        notch_filter:     DualNotchFilter (50/60 Hz)
        hampel_filter:    HampelFilter (motion artifact)
        bounds_checker:   PhysiologicalBoundsChecker

    BandpassFilter is constructed per-sample (requires VitalSignType).

    IEC 62304 §5.3: All filter dependencies are injected — enables isolated
    unit testing of each filter stage without constructing the full pipeline.
    """

    notch_filter: DualNotchFilter = field(default_factory=DualNotchFilter)
    hampel_filter: HampelFilter = field(default_factory=HampelFilter)
    bounds_checker: PhysiologicalBoundsChecker = field(
        default_factory=PhysiologicalBoundsChecker
    )

    def process(self, sample: VitalSignSample) -> ProcessedVitalSign:
        """
        Apply the full four-stage artifact rejection pipeline.

        Stage 1: Physiological bounds check on the numeric value.
        Stage 2: Dual notch filter (waveform only — if present).
        Stage 3: Bandpass filter (waveform only — if type is supported).
        Stage 4: Hampel outlier rejection (waveform only).

        Args:
            sample: Immutable VitalSignSample from the adapter layer.

        Returns:
            ProcessedVitalSign with cleaned data and full audit trail.
        """
        notes: list[str] = []
        outlier_count = 0
        cleaned_waveform: tuple[float, ...] | None = None

        # ── Stage 1: Physiological Bounds Check ───────────────────────────────
        is_within_bounds, bounds_note = self.bounds_checker.check(
            vital_sign_type=sample.vital_sign_type,
            value=sample.value,
        )
        if bounds_note:
            notes.append(f"[BOUNDS] {bounds_note}")

        # ── Stages 2–4: Waveform Processing (only if waveform data present) ───
        if sample.waveform is not None and sample.sampling_rate_hz is not None:
            raw = np.array(sample.waveform, dtype=np.float64)
            rate = sample.sampling_rate_hz

            # Stage 2: Dual Notch (50 Hz + 60 Hz)
            try:
                notched = self.notch_filter.apply(raw, rate)
                notes.append("[NOTCH] 50/60 Hz power line interference removed.")
            except ValueError as e:
                notched = raw
                notes.append(f"[NOTCH-SKIP] {e}")

            # Stage 3: Bandpass (signal-type specific)
            if sample.vital_sign_type in _WAVEFORM_CAPABLE_TYPES:
                try:
                    bp_filter = BandpassFilter(
                        vital_sign_type=sample.vital_sign_type
                    )
                    bandpassed = bp_filter.apply(notched, rate)
                    notes.append(
                        f"[BANDPASS] Applied for {sample.vital_sign_type.name}."
                    )
                except ValueError as e:
                    bandpassed = notched
                    notes.append(f"[BANDPASS-SKIP] {e}")
            else:
                bandpassed = notched

            # Stage 4: Hampel Motion Artifact Rejection
            try:
                result_arr, mask = self.hampel_filter.apply_with_mask(bandpassed)
                outlier_count = int(np.sum(mask))
                if outlier_count > 0:
                    notes.append(
                        f"[HAMPEL] {outlier_count} motion artifact sample(s) "
                        "detected and replaced with local median."
                    )
                else:
                    notes.append("[HAMPEL] No motion artifacts detected.")
                cleaned_waveform = tuple(float(v) for v in result_arr)
            except ValueError as e:
                notes.append(f"[HAMPEL-SKIP] {e}")
                cleaned_waveform = tuple(sample.waveform)
        else:
            notes.append(
                "[WAVEFORM-SKIP] No raw waveform provided — "
                "numeric value validation only."
            )

        return ProcessedVitalSign(
            original=sample,
            cleaned_value=sample.value,
            cleaned_waveform=cleaned_waveform,
            is_within_physiological_bounds=is_within_bounds,
            outlier_count=outlier_count,
            pipeline_notes=tuple(notes),
            processed_at=datetime.now(tz=timezone.utc),
        )