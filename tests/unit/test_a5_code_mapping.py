"""
A5 — OBX-3 mapping must honour the coding system and must not map different
physiological quantities onto one NEWS2 input.
See regulatory/findings/A5.md (unsigned PROPOSAL).
"""

from __future__ import annotations

import pytest
from domain.entities.score_outcome import ReasonCode
from domain.entities.vital_sign import VitalSignType
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter

_MSH = "MSH|^~\\&|MON|ICU|EHR|HOSP|20260929110000||ORU^R01|C1|P|2.5.1\rPID|1||P1^^^H^MR\r"


def _parse(obx3: str, value: str = "97", unit: str = ""):  # noqa: ANN202
    return HL7v2Adapter().parse(_MSH + f"OBX|1|NM|{obx3}||{value}|{unit}|||||F")


def test_loinc_2708_6_arterial_saturation_is_not_spo2() -> None:
    res = _parse("2708-6^Oxygen saturation in Arterial blood^LN", "97", "%")
    assert res.samples == ()
    assert ReasonCode.UNRECOGNISED_CODE in [f.code for f in res.findings]


@pytest.mark.parametrize("code", ["ABP-S", "ART-S", "ABP-D", "ART-D"])
def test_arterial_pressure_does_not_collide_with_nibp(code: str) -> None:
    res = _parse(f"{code}^Arterial^L", "120", "mmHg")
    assert res.samples == ()
    assert ReasonCode.UNRECOGNISED_CODE in [f.code for f in res.findings]


@pytest.mark.xfail(
    strict=True,
    reason="BLOCKED-TEST-CONFLICT A5-1 (HD-E6): demo tests lock in T1/T2 mapping",
)
@pytest.mark.parametrize("code", ["T1", "T2"])
def test_site_unspecified_temperature_is_not_core(code: str) -> None:
    res = _parse(f"{code}^Temp^L", "33.0", "Cel")
    assert res.samples == ()


@pytest.mark.parametrize("code", ["SO2", "SAO2", "STO2"])
def test_non_pulse_oximetry_saturations_are_not_spo2(code: str) -> None:
    res = _parse(f"{code}^Sat^L", "97", "%")
    assert res.samples == ()


def test_loinc_system_does_not_fall_back_to_vendor_table() -> None:
    # "HR" declared as a LOINC code is not a LOINC code.
    res = _parse("HR^Heart rate^LN", "72", "/min")
    assert res.samples == ()
    assert ReasonCode.UNRECOGNISED_CODE in [f.code for f in res.findings]


@pytest.mark.xfail(
    strict=True,
    reason="BLOCKED-TEST-CONFLICT A5-2 (HD-E6): vendor edge-case tests lock in the fallback",
)
def test_non_loinc_system_does_not_fall_back_to_loinc_table() -> None:
    res = _parse("8867-4^Something local^99LOCAL", "72", "/min")
    assert res.samples == ()


def test_loinc_heart_rate_still_maps() -> None:
    res = _parse("8867-4^Heart rate^LN", "72", "/min")
    assert len(res.samples) == 1
    assert res.samples[0].vital_sign_type is VitalSignType.HEART_RATE


def test_nibp_systolic_still_maps() -> None:
    res = _parse("NIBP-S^NIBP systolic^MDC", "120", "mmHg")
    assert len(res.samples) == 1
    assert res.samples[0].vital_sign_type is VitalSignType.SYSTOLIC_BP
