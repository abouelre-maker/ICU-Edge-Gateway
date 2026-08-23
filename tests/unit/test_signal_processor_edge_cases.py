"""
Unit Tests — VitalSignProcessor orchestrator edge cases.

Phase 5-Stream Section D. ISO 14971 HAZARD-DSP-001 through 004 (this
file's scope, per the section's priority list): zero-length signal array,
single-sample array, NaN/Inf values mid-array, and sampling_rate_hz at
implausible extremes -- confirmed here to fail closed at the orchestrator
level (VitalSignProcessor.process(), not just the individual filters
already covered in tests/unit/test_artifact_rejector.py) rather than
producing a silently-wrong cleaned_waveform or cleaned_value that could
feed NEWS2Calculator.

SYNTHETIC TEST DATA — FOR AUTOMATED TESTING ONLY, NOT CLINICAL VALIDATION
EVIDENCE. All samples below are synthetically constructed, including
deliberately invalid/degenerate waveforms, and are not derived from real
patient monitor output.

IMPORTANT, established elsewhere and re-confirmed by these tests: NEWS2
scoring reads ONLY ProcessedVitalSign.cleaned_value (the raw scalar
sample.value, untouched by the waveform DSP stages) and
is_within_physiological_bounds (Stage 1, PhysiologicalBoundsChecker) --
never cleaned_waveform. So even in the worst case below (a NaN/Inf mid-
array waveform that every filter stage explicitly rejects and falls back
to raw), cleaned_waveform being non-finite cannot, by itself, corrupt a
NEWS2 score -- see tests/regulatory/test_news2_safety.py and
test_hl7v2_waveform_pipeline.py's TestWaveformNeverFeedsNews2Score for
that separate guarantee. What THESE tests confirm is narrower and
specific to this section's ask: that the DSP pipeline itself never raises
an uncaught exception or silently fabricates a plausible-looking
"cleaned" value from a degenerate/invalid input -- every rejection is
explicit and shows up in pipeline_notes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from domain.entities.vital_sign import VitalSignSample, VitalSignType, VitalSignUnit
from domain.services.signal_processor import VitalSignProcessor

_TS = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def _waveform_sample(
    waveform: tuple[float, ...], sampling_rate_hz: float
) -> VitalSignSample:
    """Minimal HEART_RATE waveform sample for direct VitalSignProcessor calls."""
    return VitalSignSample(
        vital_sign_type=VitalSignType.HEART_RATE,
        value=0.0,
        unit=VitalSignUnit.BPM,
        timestamp=_TS,
        waveform=waveform,
        sampling_rate_hz=sampling_rate_hz,
    )


class TestZeroLengthAndSingleSampleWaveforms:
    def test_zero_length_waveform_does_not_raise(self) -> None:
        sample = _waveform_sample((), 250.0)
        processed = VitalSignProcessor().process(sample)
        assert processed.cleaned_waveform == ()
        assert processed.outlier_count == 0

    def test_zero_length_waveform_every_stage_explicitly_skips(self) -> None:
        sample = _waveform_sample((), 250.0)
        processed = VitalSignProcessor().process(sample)
        notes_text = " | ".join(processed.pipeline_notes)
        assert "NOTCH-SKIP" in notes_text
        assert "BANDPASS-SKIP" in notes_text
        assert "HAMPEL-SKIP" in notes_text

    def test_single_sample_waveform_does_not_raise(self) -> None:
        sample = _waveform_sample((72.0,), 250.0)
        processed = VitalSignProcessor().process(sample)
        assert processed.cleaned_waveform == (72.0,)
        assert processed.outlier_count == 0

    def test_single_sample_waveform_notch_and_bandpass_explicitly_skip(self) -> None:
        """Notch/bandpass both need a minimum window and explicitly refuse a
        single sample; Hampel accepts it trivially (nothing to flag) -- see
        test_artifact_rejector.py::TestZeroLengthAndSingleSampleArrays for
        why that asymmetry is deliberate, not a gap."""
        sample = _waveform_sample((72.0,), 250.0)
        processed = VitalSignProcessor().process(sample)
        notes_text = " | ".join(processed.pipeline_notes)
        assert "NOTCH-SKIP" in notes_text
        assert "BANDPASS-SKIP" in notes_text


class TestNonFiniteWaveformMidArray:
    """
    ISO 14971 HAZARD-DSP-007 (artifact_rejector.py): every stage now
    explicitly rejects a NaN/Inf sample rather than silently propagating it
    through filtfilt's IIR feedback. These tests confirm that rejection is
    visible end-to-end through the orchestrator, not just at the filter
    unit-test level.
    """

    def _waveform_with_nan(self, n: int = 20) -> tuple[float, ...]:
        values = [0.1 * i for i in range(n)]
        values[n // 2] = float("nan")
        return tuple(values)

    def _waveform_with_inf(self, n: int = 20) -> tuple[float, ...]:
        values = [0.1 * i for i in range(n)]
        values[n // 2] = float("inf")
        return tuple(values)

    def test_nan_mid_array_does_not_raise_out_of_process(self) -> None:
        """process() itself must never propagate the ValueError -- each
        stage catches its own and degrades-and-logs, matching the existing
        pattern for empty/too-short signals."""
        sample = _waveform_sample(self._waveform_with_nan(), 250.0)
        processed = VitalSignProcessor().process(sample)
        assert processed is not None

    def test_nan_mid_array_every_stage_explicitly_rejects(self) -> None:
        sample = _waveform_sample(self._waveform_with_nan(), 250.0)
        processed = VitalSignProcessor().process(sample)
        notes_text = " | ".join(processed.pipeline_notes)
        assert "NOTCH-SKIP" in notes_text
        assert "NaN or Inf" in notes_text
        assert "BANDPASS-SKIP" in notes_text
        assert "HAMPEL-SKIP" in notes_text

    def test_inf_mid_array_every_stage_explicitly_rejects(self) -> None:
        sample = _waveform_sample(self._waveform_with_inf(), 250.0)
        processed = VitalSignProcessor().process(sample)
        notes_text = " | ".join(processed.pipeline_notes)
        assert "NOTCH-SKIP" in notes_text
        assert "NaN or Inf" in notes_text
        assert "BANDPASS-SKIP" in notes_text
        assert "HAMPEL-SKIP" in notes_text

    def test_nan_scalar_value_is_flagged_out_of_bounds_not_silently_scored(
        self,
    ) -> None:
        """
        The other half of HAZARD-DSP-007 (PhysiologicalBoundsChecker, not
        the waveform path): a NaN scalar `value` -- e.g. from an
        unparseable OBX-5 that upstream code failed to filter out -- must
        come out of Stage 1 flagged is_within_physiological_bounds=False,
        never True. This is the one path that COULD have fed NEWS2 a
        silently-wrong value before the fix.
        """
        sample = VitalSignSample(
            vital_sign_type=VitalSignType.HEART_RATE,
            value=float("nan"),
            unit=VitalSignUnit.BPM,
            timestamp=_TS,
        )
        processed = VitalSignProcessor().process(sample)
        assert processed.is_within_physiological_bounds is False


class TestSamplingRateExtremesOrchestrator:
    def test_near_zero_sampling_rate_does_not_raise(self) -> None:
        waveform = tuple(float(v) for v in np.linspace(0, 1, 50))
        sample = _waveform_sample(waveform, 1e-6)
        processed = VitalSignProcessor().process(sample)
        assert processed is not None
        # Bandpass explicitly rejects a degenerate Nyquist-clamped band at
        # this rate (see artifact_rejector.py); notch is a documented no-op.
        notes_text = " | ".join(processed.pipeline_notes)
        assert "BANDPASS-SKIP" in notes_text

    def test_extremely_high_sampling_rate_completes_with_finite_output(self) -> None:
        rng = np.random.default_rng(0)
        waveform = tuple(float(v) for v in rng.standard_normal(500))
        sample = _waveform_sample(waveform, 1e9)
        processed = VitalSignProcessor().process(sample)
        assert processed.cleaned_waveform is not None
        assert all(np.isfinite(v) for v in processed.cleaned_waveform)

    def test_negative_sampling_rate_rejected_at_entity_construction(self) -> None:
        """
        VitalSignSample.__post_init__ already rejects sampling_rate_hz<=0 --
        this is the earliest possible fail-closed point, before the DSP
        pipeline is even reached. Documented here as the counterpart to the
        near-zero-but-positive case above.
        """
        with pytest.raises(ValueError, match="positive"):
            _waveform_sample((1.0, 2.0, 3.0), -250.0)

        with pytest.raises(ValueError, match="positive"):
            _waveform_sample((1.0, 2.0, 3.0), 0.0)
