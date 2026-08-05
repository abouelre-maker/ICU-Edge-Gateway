"""
IFilterStrategy — GoF Strategy Pattern contract for DSP filter implementations.

IEC 62304 §5.3: Abstract interface isolates domain logic from concrete filter
implementations, enabling filter substitution without risk analysis re-work.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class IFilterStrategy(ABC):
    """
    Abstract base for all signal processing filter strategies.

    Any concrete implementation (NotchFilter, BandpassFilter, HampelFilter)
    must satisfy this contract. The VitalSignProcessor depends only on this
    interface — never on a concrete filter class.
    """

    @abstractmethod
    def apply(self, signal: np.ndarray, sampling_rate_hz: float) -> np.ndarray:
        """
        Apply the filter to a 1D signal array.

        Args:
            signal:           1D numpy array of float64 signal samples.
            sampling_rate_hz: Acquisition sampling rate in Hz. Must be > 0.

        Returns:
            Filtered 1D numpy array, same length as input.

        Raises:
            ValueError: If signal is empty or sampling_rate_hz is invalid.
        """
