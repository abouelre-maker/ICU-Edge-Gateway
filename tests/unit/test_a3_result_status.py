"""
A3 — OBX-11 result status handling.

- C (corrected): the corrected value is used and REPLACES an earlier final
  value of the same observation in the same message; CORRECTION_PENDING tells
  downstream consumers to supersede any previously sent result.
- Empty OBX-11: accepted but reported (MISSING_RESULT_STATUS), never silent.
- Lowercase status: normalised.
See regulatory/findings/A3.md (unsigned PROPOSAL).
"""

from __future__ import annotations

from domain.entities.score_outcome import ReasonCode
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter

_MSH = "MSH|^~\\&|MON|ICU|EHR|HOSP|20260929110000||ORU^R01|C1|P|2.5.1\rPID|1||P1^^^H^MR\r"


def _parse(*obx: str):  # noqa: ANN202
    return HL7v2Adapter().parse(_MSH + "\r".join(obx))


def test_corrected_result_is_used_and_flagged() -> None:
    res = _parse("OBX|1|NM|8867-4^HR^LN||88|/min|||||C")
    assert len(res.samples) == 1
    assert res.samples[0].value == 88
    assert res.samples[0].result_status == "C"
    assert ReasonCode.CORRECTION_PENDING in [f.code for f in res.findings]


def test_correction_replaces_prior_final_in_same_message() -> None:
    res = _parse(
        "OBX|1|NM|8867-4^HR^LN||150|/min|||||F|||20260929105900",
        "OBX|2|NM|8867-4^HR^LN||88|/min|||||C|||20260929105900",
    )
    hr = [s for s in res.samples if s.vital_sign_type.name == "HEART_RATE"]
    assert [s.value for s in hr] == [88]


def test_empty_status_is_reported_not_silent() -> None:
    res = _parse("OBX|1|NM|8867-4^HR^LN||72|/min|||||")
    assert len(res.samples) == 1
    assert res.samples[0].result_status == ""
    assert ReasonCode.MISSING_RESULT_STATUS in [f.code for f in res.findings]


def test_lowercase_final_is_normalised() -> None:
    res = _parse("OBX|1|NM|8867-4^HR^LN||72|/min|||||f")
    assert len(res.samples) == 1
    assert res.samples[0].result_status == "F"
    assert res.findings == ()


def test_entered_in_error_is_still_excluded() -> None:
    res = _parse("OBX|1|NM|8867-4^HR^LN||72|/min|||||W")
    assert res.samples == ()
