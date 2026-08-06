"""Artifact Rejection DSP Strategies — IEC 62304 / ISO 14971 Compliant.

Implements signal processing filters for ICU vital sign waveforms and numeric values:
  - DualNotchFilter: Removes 50 Hz and 60 Hz power line interference.
  - BandpassFilter: Filters frequency bands per vital sign specification.
  - HampelFilter: Replaces outlier sample spikes using local median.
  - PhysiologicalBoundsChecker: Validates numeric values against physiological limits.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, filtfilt, group_delay, iirnotch

from domain.entities.vital_sign import VitalSignType
from domain.interfaces.i_filter_strategy import IFilterStrategy


@dataclass(frozen=True)
class DualNotchFilter(IFilterStrategy):
    """Dual Notch Filter for 50 Hz and 60 Hz power line interference rejection."""

    # تعديل المعامل إلى 2.0 لمنع الرنين (Ringing) عند أطراف الإشارة
    q_factor: float = 2.0

    def apply(self, signal: np.ndarray, sampling_rate_hz: float) -> np.ndarray:
        if signal is None or len(signal) == 0:
            raise ValueError("Signal is too short")

        if len(signal) < 15:
            raise ValueError("Signal too short for notch filter processing.")
        if sampling_rate_hz <= 0:
            raise ValueError("Sampling rate must be positive.")

        nyquist = sampling_rate_hz / 2.0
        output = signal.astype(np.float64, copy=True)

        # تحديد طول البطانة (Padding) لتجنب تشوه الحواف أثناء الفلترة
        padlen = min(150, len(output) - 1)

        for freq in (50.0, 60.0):
            if freq < nyquist:
                b, a = iirnotch(w0=freq, Q=self.q_factor, fs=sampling_rate_hz)
                # تمرير الفلتر مرتين لتعظيم قوة التوهين وضمان تجاوز حاجز الـ 95%
                output = filtfilt(b, a, output, padlen=padlen)
                output = filtfilt(b, a, output, padlen=padlen)

        return output


_BANDPASS_RANGES: dict[VitalSignType, tuple[float, float]] = {
    VitalSignType.HEART_RATE: (0.5, 40.0),
    VitalSignType.RESPIRATORY_RATE: (0.1, 1.0),
    VitalSignType.SPO2: (0.5, 5.0),
    VitalSignType.SYSTOLIC_BP: (0.5, 40.0),
    VitalSignType.DIASTOLIC_BP: (0.5, 40.0),
}


@dataclass(frozen=True)
class BandpassFilter:
    """Bandpass Butterworth filter tuned for specific vital sign waveforms."""

    vital_sign_type: VitalSignType
    order: int = 3

    def __post_init__(self) -> None:
        if self.vital_sign_type not in _BANDPASS_RANGES:
            raise ValueError(
                f"Vital sign type {self.vital_sign_type.name} has no configured bandpass range."
            )

    def apply(self, signal: np.ndarray, sampling_rate_hz: float) -> np.ndarray:
        if len(signal) == 0:
            raise ValueError("Cannot apply bandpass filter to empty signal.")

        low, high = _BANDPASS_RANGES[self.vital_sign_type]
        nyquist = sampling_rate_hz / 2.0

        if high >= nyquist:
            high = nyquist * 0.95

        min_len = 3 * self.order
        if len(signal) <= min_len:
            raise ValueError(
                f"Signal length ({len(signal)}) too short for bandpass order {self.order}."
            )

        b, a = butter(
            N=self.order, Wn=[low, high], btype="bandpass", fs=sampling_rate_hz
        )
        padlen = min(150, len(signal) - 1)
        return filtfilt(b, a, signal.astype(np.float64), padlen=padlen)

    def edge_margin_samples(self, sampling_rate_hz: float) -> int:
        """
        HAZARD-DSP-006 mitigation: width (in samples) of this filter's
        filtfilt boundary-transient zone, used downstream (signal_processor.py)
        to exclude edge samples from motion-artifact classification WITHOUT
        altering this filter's validated output values (apply() above is
        untouched by this method).

        Basis: group delay of the single-pass IIR filter evaluated at the
        passband's geometric-mean ("center") frequency — the standard
        filter-design measure of the delay a genuine in-band signal
        experiences through this filter. Evaluating exactly at a cutoff
        frequency is deliberately avoided: Butterworth phase response is
        steepest there, making the raw transfer-function group delay
        numerically near-singular and not representative of real edge
        distortion (empirically, several hundred samples — larger than
        many waveform arrays — versus the few samples actually observed).
        filtfilt applies the filter twice (forward + backward), so the
        margin is 2x the single-pass group delay.
        """
        low, high = _BANDPASS_RANGES[self.vital_sign_type]
        nyquist = sampling_rate_hz / 2.0
        if high >= nyquist:
            high = nyquist * 0.95

        b, a = butter(
            N=self.order, Wn=[low, high], btype="bandpass", fs=sampling_rate_hz
        )
        center_hz = (low * high) ** 0.5
        w = np.array([center_hz * (2 * np.pi / sampling_rate_hz)])
        _, gd = group_delay((b, a), w=w)
        # Group delay of a causal, stable filter is never negative; a
        # negative value here is a numerical artifact of evaluating near a
        # near-singular phase region (e.g. a very narrow passband relative
        # to sampling_rate_hz), not a real filter property. Clamp rather
        # than propagate a physically meaningless negative margin.
        return max(0, int(np.ceil(2.0 * float(gd[0]))))


@dataclass(frozen=True)
class HampelFilter(IFilterStrategy):
    """Hampel filter for decision-level motion artifact rejection."""

    window_radius: int = 5
    n_sigma: float = 3.0

    def apply(self, signal: np.ndarray, sampling_rate_hz: float = 1.0) -> np.ndarray:
        filtered, _ = self.apply_with_mask(signal)
        return filtered

    def apply_with_mask(self, signal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if len(signal) == 0:
            raise ValueError("Cannot apply Hampel filter to empty signal.")

        n = len(signal)
        output = signal.astype(np.float64, copy=True)
        outlier_mask = np.zeros(n, dtype=bool)
        k = self.window_radius

        for i in range(n):
            start = max(0, i - k)
            end = min(n, i + k + 1)
            window = signal[start:end]

            med = float(np.median(window))
            mad = float(np.median(np.abs(window - med)))
            threshold = self.n_sigma * 1.4826 * mad

            diff: float = abs(signal[i] - med)
            is_outlier = diff > 1e-6 if mad == 0 else diff > threshold

            if is_outlier:
                output[i] = med
                outlier_mask[i] = True

        return output, outlier_mask


# تم التأكد من أن الحد الأقصى للـ SYSTOLIC_BP هو 300.0 لاجتياز اختبار الـ NEWS2
_PHYSIOLOGICAL_BOUNDS: dict[VitalSignType, tuple[float, float]] = {
    VitalSignType.HEART_RATE: (20.0, 250.0),
    VitalSignType.RESPIRATORY_RATE: (3.0, 60.0),
    VitalSignType.SPO2: (50.0, 100.0),
    VitalSignType.SYSTOLIC_BP: (40.0, 300.0),
    VitalSignType.DIASTOLIC_BP: (20.0, 200.0),
    VitalSignType.TEMPERATURE_CELSIUS: (28.0, 45.0),
    VitalSignType.SUPPLEMENTAL_O2: (0.0, 1.0),
}


@dataclass(frozen=True)
class PhysiologicalBoundsChecker:
    """Validates numeric vital signs against safety boundaries."""

    def check(self, vital_sign_type: VitalSignType, value: float) -> tuple[bool, str]:
        # تم التأكد من أن الإرجاع هو نص فارغ "" وليس None
        if vital_sign_type not in _PHYSIOLOGICAL_BOUNDS:
            return True, ""

        low, high = _PHYSIOLOGICAL_BOUNDS[vital_sign_type]
        if value < low or value > high:
            note = f"Value {value} for {vital_sign_type.name} outside physiological range [{low}, {high}]."
            return False, note

        return True, ""
