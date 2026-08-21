"""
Unit Tests — DSP Artifact Rejection Pipeline.

IEC 62304 §5.7: Verification of all filter implementations.
ISO 14971 HAZARD-DSP-001/002/003, plus HAZARD-DSP-006 edge-margin coverage,
and HAZARD-DSP-007 (below: zero-length/single-sample/NaN-Inf/sampling-rate-
extreme edge cases, Phase 5-Stream Section D).

SYNTHETIC TEST DATA — FOR AUTOMATED TESTING ONLY, NOT CLINICAL VALIDATION
EVIDENCE. All signals below are synthetically constructed to exercise
specific code paths (including deliberately invalid/degenerate inputs) and
are not derived from, or representative of, real patient monitor output.
"""

from __future__ import annotations

import numpy as np
import pytest
from domain.entities.vital_sign import VitalSignType
from domain.services.artifact_rejector import (
    BandpassFilter,
    DualNotchFilter,
    HampelFilter,
    PhysiologicalBoundsChecker,
)

_FS = 500.0  # 500 Hz — standard clinical waveform sampling rate


def _pure_sine(freq_hz: float, duration_s: float = 2.0, fs: float = _FS) -> np.ndarray:
    t = np.linspace(0, duration_s, int(duration_s * fs), endpoint=False)
    return np.sin(2 * np.pi * freq_hz * t)


class TestDualNotchFilter:
    """IEC 62304 REQ-DSP-001: Notch must attenuate 50/60 Hz by ≥ 40 dB."""

    def test_attenuates_60hz_signal(self) -> None:
        sig = _pure_sine(60.0)
        f = DualNotchFilter()
        filtered = f.apply(sig, _FS)
        original_rms = float(np.sqrt(np.mean(sig**2)))
        filtered_rms = float(np.sqrt(np.mean(filtered**2)))
        assert filtered_rms < original_rms * 0.05, (
            "60 Hz notch must attenuate RMS by >95% (≥26 dB). " "IEC 62304 REQ-DSP-001."
        )

    def test_attenuates_50hz_signal(self) -> None:
        sig = _pure_sine(50.0)
        f = DualNotchFilter()
        filtered = f.apply(sig, _FS)
        original_rms = float(np.sqrt(np.mean(sig**2)))
        filtered_rms = float(np.sqrt(np.mean(filtered**2)))
        assert (
            filtered_rms < original_rms * 0.05
        ), "50 Hz notch must attenuate RMS by >95%."

    def test_preserves_10hz_content(self) -> None:
        sig = _pure_sine(10.0)
        f = DualNotchFilter()
        filtered = f.apply(sig, _FS)
        original_rms = float(np.sqrt(np.mean(sig**2)))
        filtered_rms = float(np.sqrt(np.mean(filtered**2)))
        # 10 Hz content should be >90% preserved after notch filter
        assert filtered_rms > original_rms * 0.90, (
            "Notch filter must not attenuate 10 Hz content. "
            "ISO 14971 HAZARD-DSP-001: signal fidelity preservation."
        )

    def test_both_frequencies_simultaneously(self) -> None:
        sig = _pure_sine(50.0) + _pure_sine(60.0) + _pure_sine(10.0)
        f = DualNotchFilter()
        filtered = f.apply(sig, _FS)
        # 10 Hz component should dominate after filtering
        assert float(np.max(np.abs(filtered))) < float(np.max(np.abs(sig)))

    def test_raises_on_empty_signal(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            DualNotchFilter().apply(np.array([1.0, 2.0]), _FS)

    def test_raises_on_zero_sampling_rate(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            DualNotchFilter().apply(_pure_sine(10.0), 0.0)

    def test_skips_frequency_above_nyquist(self) -> None:
        # At 100 Hz sampling rate, 60 Hz > Nyquist — should not raise
        sig = np.random.default_rng(42).standard_normal(200)
        result = DualNotchFilter().apply(sig, 100.0)
        assert result.shape == sig.shape


class TestBandpassFilter:
    def test_removes_dc_offset(self) -> None:
        dc = np.ones(int(2 * _FS)) * 5.0  # Pure DC at 5.0
        sig = dc + 0.5 * _pure_sine(10.0)
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        filtered = f.apply(sig, _FS)
        # After bandpass, DC should be gone — mean near zero
        assert abs(float(np.mean(filtered))) < 0.1, (
            "Bandpass must remove DC offset (baseline wander). "
            "ISO 14971 HAZARD-DSP-002."
        )

    def test_passes_in_band_content(self) -> None:
        sig = _pure_sine(10.0)  # 10 Hz — within HEART_RATE passband (0.5–40 Hz)
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        filtered = f.apply(sig, _FS)
        original_rms = float(np.sqrt(np.mean(sig**2)))
        filtered_rms = float(np.sqrt(np.mean(filtered**2)))
        assert (
            filtered_rms > original_rms * 0.85
        ), "Bandpass must pass >85% of in-band 10 Hz content."

    def test_raises_for_non_waveform_type(self) -> None:
        with pytest.raises(ValueError, match="no configured bandpass range"):
            BandpassFilter(vital_sign_type=VitalSignType.TEMPERATURE_CELSIUS)

    def test_raises_on_too_short_signal(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
            f.apply(np.array([1.0, 2.0, 3.0]), _FS)


class TestBandpassFilterEdgeMarginSamples:
    """
    ISO 14971 HAZARD-DSP-006: filtfilt boundary-transient margin.

    Golden values derived independently via scipy.signal.group_delay at each
    filter's passband geometric-mean frequency, x2 for filtfilt's
    forward+backward pass, ceil'd. See conversation record / risk register
    for the full derivation. Recomputing these inline (rather than importing
    the golden constants) would make the test tautological.
    """

    def test_heart_rate_margin_at_default_250hz(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        assert f.edge_margin_samples(250.0) == 8

    def test_heart_rate_margin_at_200hz_override(self) -> None:
        """
        Matches the empirically observed HAZARD-DSP-006 reproduction:
        DualNotch -> Bandpass(200 Hz) -> Hampel flagged indices [398, 399]
        of a 400-sample array — within the last 7 samples this margin
        computes.
        """
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        assert f.edge_margin_samples(200.0) == 7

    def test_respiratory_rate_margin_is_the_documented_worst_case(self) -> None:
        """
        RESPIRATORY_RATE has the lowest passband (0.1-1.0 Hz) of all
        configured types, hence the slowest group delay and the largest
        margin among the five vital sign types.
        """
        f = BandpassFilter(vital_sign_type=VitalSignType.RESPIRATORY_RATE)
        assert f.edge_margin_samples(62.5) == 89

    def test_spo2_margin_at_default_62_5hz(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.SPO2)
        assert f.edge_margin_samples(62.5) == 18

    def test_systolic_bp_margin_at_default_125hz(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.SYSTOLIC_BP)
        assert f.edge_margin_samples(125.0) == 4

    def test_diastolic_bp_margin_at_default_125hz(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.DIASTOLIC_BP)
        assert f.edge_margin_samples(125.0) == 4

    def test_margin_is_never_negative(self) -> None:
        for vital_type in (
            VitalSignType.HEART_RATE,
            VitalSignType.RESPIRATORY_RATE,
            VitalSignType.SPO2,
            VitalSignType.SYSTOLIC_BP,
            VitalSignType.DIASTOLIC_BP,
        ):
            f = BandpassFilter(vital_sign_type=vital_type)
            assert f.edge_margin_samples(_FS) >= 0

    def test_margin_is_deterministic(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        assert f.edge_margin_samples(250.0) == f.edge_margin_samples(250.0)


class TestHampelFilter:
    """ISO 14971 HAZARD-DSP-003: Motion artifact spike detection."""

    def test_detects_and_replaces_single_outlier(self) -> None:
        sig = np.zeros(100)
        sig[50] = 100.0  # Single spike outlier
        h = HampelFilter(window_radius=5, n_sigma=3.0)
        cleaned, mask = h.apply_with_mask(sig)
        assert mask[50], "Spike at index 50 must be detected as outlier."
        assert abs(cleaned[50]) < 1.0, (
            "Spike must be replaced with local median (~0.0). "
            "ISO 14971 HAZARD-DSP-003."
        )

    def test_does_not_flag_clean_signal(self) -> None:
        rng = np.random.default_rng(42)
        sig = rng.standard_normal(200)  # No outliers
        h = HampelFilter(window_radius=5, n_sigma=3.0)
        _, mask = h.apply_with_mask(sig)
        outlier_rate = float(np.mean(mask))
        assert outlier_rate < 0.02, (
            f"Hampel must not flag >2% of clean Gaussian signal. "
            f"Got {outlier_rate:.1%}. IEC 62304 REQ-DSP-003."
        )

    def test_returns_same_length_as_input(self) -> None:
        sig = np.linspace(0, 1, 50)
        h = HampelFilter()
        cleaned, mask = h.apply_with_mask(sig)
        assert cleaned.shape == sig.shape
        assert mask.shape == sig.shape

    def test_raises_on_empty_signal(self) -> None:
        with pytest.raises(ValueError, match="empty signal"):
            HampelFilter().apply_with_mask(np.array([]))

    def test_preserves_physiological_qrs_slope(self) -> None:
        """
        Regression: Hampel must not erroneously flag QRS peaks as artifacts.
        QRS peak amplitude ~1.5 mV is within expected range for healthy adults.
        """
        # Simulate a simplified ECG QRS complex
        t = np.linspace(0, 0.1, 50)
        qrs = np.exp(-100 * (t - 0.05) ** 2)  # Gaussian QRS ~1.0 mV
        background = np.zeros(200)
        background[75:125] = qrs
        h = HampelFilter(window_radius=3, n_sigma=3.0)
        _, mask = h.apply_with_mask(background)
        # The QRS peak itself should not be flagged (it's a physiological signal)
        assert not mask[100], (
            "QRS peak must not be flagged as artifact. "
            "ISO 14971 HAZARD-DSP-003: false positive artifact rejection "
            "causes false R-peak loss and incorrect HR calculation."
        )


class TestPhysiologicalBoundsChecker:
    """ISO 14971 HAZARD-BOUNDS-001: Instrument error values excluded from NEWS2."""

    def test_normal_hr_is_within_bounds(self) -> None:
        checker = PhysiologicalBoundsChecker()
        ok, note = checker.check(VitalSignType.HEART_RATE, 72.0)
        assert ok
        assert note == ""

    def test_extreme_low_hr_is_out_of_bounds(self) -> None:
        checker = PhysiologicalBoundsChecker()
        ok, note = checker.check(VitalSignType.HEART_RATE, 5.0)
        assert not ok
        assert "physiological range" in note

    def test_spo2_above_100_is_out_of_bounds(self) -> None:
        checker = PhysiologicalBoundsChecker()
        ok, _ = checker.check(VitalSignType.SPO2, 101.0)
        assert not ok

    def test_normal_temperature_is_within_bounds(self) -> None:
        checker = PhysiologicalBoundsChecker()
        ok, _ = checker.check(VitalSignType.TEMPERATURE_CELSIUS, 37.0)
        assert ok

    def test_consciousness_has_no_bounds_check(self) -> None:
        checker = PhysiologicalBoundsChecker()
        ok, note = checker.check(VitalSignType.CONSCIOUSNESS, 0.0)
        assert ok  # No bounds configured → always passes
        assert note == ""

    def test_sbp_220_is_out_of_bounds(self) -> None:
        """SBP 220 is within NEWS2 scoring but NOT beyond physiological bounds (300)."""
        checker = PhysiologicalBoundsChecker()
        ok, _ = checker.check(VitalSignType.SYSTOLIC_BP, 220.0)
        assert (
            ok
        ), "SBP=220 is within physiological bounds (max=300). NEWS2 should score it."

    def test_nan_hr_is_explicitly_rejected_not_silently_in_bounds(self) -> None:
        """
        ISO 14971 HAZARD-DSP-007 regression: `NaN < low` and `NaN > high` are
        both always False (IEEE-754), so before the fix this silently
        returned ok=True and NEWS2Calculator._extract_value() (which selects
        on exactly this flag) would have used it as a scoring input.
        """
        checker = PhysiologicalBoundsChecker()
        ok, note = checker.check(VitalSignType.HEART_RATE, float("nan"))
        assert ok is False
        assert "NaN" in note

    def test_nan_is_rejected_even_for_a_type_with_no_configured_bounds(self) -> None:
        """CONSCIOUSNESS has no _PHYSIOLOGICAL_BOUNDS entry -- NaN must still
        not fall through the "no bounds configured -> always ok" early return."""
        checker = PhysiologicalBoundsChecker()
        ok, note = checker.check(VitalSignType.CONSCIOUSNESS, float("nan"))
        assert ok is False
        assert "NaN" in note

    def test_inf_hr_was_already_correctly_rejected(self) -> None:
        """Inf > high is True, so this direction was never the gap -- regression
        guard proving the NaN fix above didn't change this pre-existing behavior."""
        checker = PhysiologicalBoundsChecker()
        ok, note = checker.check(VitalSignType.HEART_RATE, float("inf"))
        assert ok is False
        assert "physiological range" in note


class TestNonFiniteRejection:
    """
    ISO 14971 HAZARD-DSP-007: a NaN/Inf sample anywhere mid-array must be
    explicitly rejected (ValueError) by every filter, never silently
    filtered -- scipy's filtfilt propagates a single NaN/Inf sample through
    its ENTIRE output via IIR feedback with no exception raised on its own.
    """

    def _signal_with_nan_mid_array(self, n: int = 20) -> np.ndarray:
        sig = np.full(n, 0.1)
        sig[n // 2] = np.nan
        return sig

    def _signal_with_inf_mid_array(self, n: int = 20) -> np.ndarray:
        sig = np.full(n, 0.1)
        sig[n // 2] = np.inf
        return sig

    def test_notch_rejects_nan_mid_array(self) -> None:
        with pytest.raises(ValueError, match="NaN or Inf"):
            DualNotchFilter().apply(self._signal_with_nan_mid_array(), _FS)

    def test_notch_rejects_inf_mid_array(self) -> None:
        with pytest.raises(ValueError, match="NaN or Inf"):
            DualNotchFilter().apply(self._signal_with_inf_mid_array(), _FS)

    def test_notch_does_not_silently_propagate_nan(self) -> None:
        """Regression proof of the pre-fix defect: without _require_finite,
        this call returned a fully-NaN array with NO exception."""
        sig = self._signal_with_nan_mid_array()
        with pytest.raises(ValueError):
            DualNotchFilter().apply(sig, _FS)

    def test_bandpass_rejects_nan_mid_array(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        with pytest.raises(ValueError, match="NaN or Inf"):
            f.apply(self._signal_with_nan_mid_array(), _FS)

    def test_bandpass_rejects_inf_mid_array(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        with pytest.raises(ValueError, match="NaN or Inf"):
            f.apply(self._signal_with_inf_mid_array(), _FS)

    def test_hampel_rejects_nan_mid_array(self) -> None:
        with pytest.raises(ValueError, match="NaN or Inf"):
            HampelFilter().apply_with_mask(self._signal_with_nan_mid_array())

    def test_hampel_rejects_inf_mid_array(self) -> None:
        with pytest.raises(ValueError, match="NaN or Inf"):
            HampelFilter().apply_with_mask(self._signal_with_inf_mid_array())


class TestZeroLengthAndSingleSampleArrays:
    """
    Explicit zero-length and single-sample array coverage for every filter --
    each must fail closed (raise) rather than crash unpredictably or return
    a misleadingly "processed" result from a degenerate input.
    """

    def test_notch_raises_on_zero_length_array(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            DualNotchFilter().apply(np.array([]), _FS)

    def test_notch_raises_on_single_sample_array(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            DualNotchFilter().apply(np.array([72.0]), _FS)

    def test_bandpass_raises_on_zero_length_array(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        with pytest.raises(ValueError, match="empty signal"):
            f.apply(np.array([]), _FS)

    def test_bandpass_raises_on_single_sample_array(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        with pytest.raises(ValueError, match="too short"):
            f.apply(np.array([72.0]), _FS)

    def test_hampel_raises_on_zero_length_array(self) -> None:
        with pytest.raises(ValueError, match="empty signal"):
            HampelFilter().apply_with_mask(np.array([]))

    def test_hampel_accepts_single_sample_array_as_a_trivial_no_op(self) -> None:
        """
        Documented, deliberate contrast with the other two filters: a
        single-sample median window is well-defined (nothing to compare
        against, so nothing can be flagged as an outlier) -- Hampel does
        NOT raise here, unlike DualNotchFilter/BandpassFilter which need a
        minimum window to be meaningful at all. This is not a gap: the
        orchestrator (signal_processor.py) only ever reaches Hampel with
        whatever notch/bandpass already skipped-and-passed-through, so a
        single-sample waveform still ends up correctly un-"cleaned" rather
        than fabricated.
        """
        cleaned, mask = HampelFilter().apply_with_mask(np.array([72.0]))
        assert cleaned.tolist() == [72.0]
        assert mask.tolist() == [False]


class TestSamplingRateExtremes:
    """
    ISO 14971 HAZARD-DSP-007: sampling_rate_hz at implausible extremes must
    not produce a silently-wrong filtered output -- either it fails closed
    (explicit ValueError) or it completes with a numerically sane, finite
    result. Neither filter is allowed to return NaN/Inf without raising.
    """

    def test_notch_near_zero_rate_is_a_documented_no_op_not_a_crash(self) -> None:
        """
        At an implausibly low sampling_rate_hz, Nyquist collapses below
        both 50 Hz and 60 Hz, so DualNotchFilter's own `if freq < nyquist`
        guard means neither notch stage ever runs -- this is a genuine,
        deliberate no-op (output == input), not a crash and not corrupted
        data. It does NOT raise (this is existing, pre-fix behavior,
        unchanged here -- see test_skips_frequency_above_nyquist above for
        the same pattern at a more realistic rate).
        """
        sig = np.random.default_rng(0).standard_normal(50)
        result = DualNotchFilter().apply(sig, 1e-6)
        assert np.all(np.isfinite(result))
        np.testing.assert_array_equal(result, sig)

    def test_bandpass_near_zero_rate_fails_closed(self) -> None:
        """
        Unlike notch, BandpassFilter's Nyquist-clamp can invert its passband
        at a near-zero rate (`high` clamped below `low`) -- explicitly
        rejected (see artifact_rejector.py's low >= high guard) rather than
        handed to scipy.signal.butter with a degenerate band.
        """
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        sig = np.random.default_rng(0).standard_normal(50)
        with pytest.raises(ValueError, match="too low"):
            f.apply(sig, 1e-6)

    def test_notch_extremely_high_rate_completes_finite(self) -> None:
        sig = np.random.default_rng(0).standard_normal(500)
        result = DualNotchFilter().apply(sig, 1e9)
        assert np.all(np.isfinite(result))

    def test_bandpass_extremely_high_rate_completes_finite(self) -> None:
        f = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        sig = np.random.default_rng(0).standard_normal(500)
        result = f.apply(sig, 1e9)
        assert np.all(np.isfinite(result))

    def test_notch_raises_on_zero_rate(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            DualNotchFilter().apply(np.random.default_rng(0).standard_normal(50), 0.0)

    def test_notch_raises_on_negative_rate(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            DualNotchFilter().apply(np.random.default_rng(0).standard_normal(50), -500.0)
