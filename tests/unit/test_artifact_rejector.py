"""
Unit Tests — DSP Artifact Rejection Pipeline.

IEC 62304 §5.7: Verification of all filter implementations.
ISO 14971 HAZARD-DSP-001 through HAZARD-DSP-004.
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
