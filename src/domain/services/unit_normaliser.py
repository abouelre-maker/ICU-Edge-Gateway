"""
Unit normalisation for scalar vital signs (A4).

Only physical unit conversions live here — never clinical thresholds:
  °F → °C:   (F − 32) × 5/9
  kPa → mmHg: × 7.50062 (1 kPa = 7.50062 mmHg)
A unit that is not dimensionally compatible with the vital sign type is
rejected (None) — the caller must report AMBIGUOUS_UNIT, never guess.
"""

from __future__ import annotations

from typing import Final

from domain.entities.vital_sign import VitalSignType, VitalSignUnit

KPA_TO_MMHG: Final = 7.50062

_T = VitalSignType
_U = VitalSignUnit

# Units accepted per type. "/min" is mapped to BPM by the HL7 adapter for both
# rate types, so both per-minute units are accepted for HR and RR.
_COMPATIBLE: Final[dict[VitalSignType, frozenset[VitalSignUnit]]] = {
    _T.HEART_RATE: frozenset({_U.BPM, _U.BREATHS_PER_MIN}),
    _T.RESPIRATORY_RATE: frozenset({_U.BPM, _U.BREATHS_PER_MIN}),
    _T.SPO2: frozenset({_U.PERCENT}),
    _T.SYSTOLIC_BP: frozenset({_U.MMHG}),
    _T.DIASTOLIC_BP: frozenset({_U.MMHG}),
    _T.TEMPERATURE_CELSIUS: frozenset({_U.CELSIUS, _U.FAHRENHEIT}),
    _T.SUPPLEMENTAL_O2: frozenset({_U.BOOLEAN}),
}


def normalise(
    vital_type: VitalSignType, value: float, unit: VitalSignUnit
) -> tuple[float, VitalSignUnit] | None:
    """Return (value, canonical unit), or None if the unit is incompatible."""
    if vital_type is _T.CONSCIOUSNESS:
        return value, unit  # categorical: avpu_level is authoritative
    allowed = _COMPATIBLE.get(vital_type)
    if allowed is None or unit not in allowed:
        return None
    if unit is _U.FAHRENHEIT:
        return (value - 32.0) * 5.0 / 9.0, _U.CELSIUS
    return value, unit
