"""
A7 — patient identity and message-type handling.
See regulatory/findings/A7.md (unsigned PROPOSAL).
"""

from __future__ import annotations

import pytest
from domain.entities.score_outcome import ReasonCode
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter

_OBX = "OBX|1|NM|8867-4^HR^LN||72|/min|||||F"


def _msg(pid3: str, msh9: str = "ORU^R01", enc: str = "^~\\&") -> str:
    return (
        f"MSH|{enc}|MON|ICU|EHR|HOSP|20260929110000||{msh9}|CTRL-42|P|2.5.1\r"
        f"PID|1||{pid3}\r{_OBX}"
    )


def _codes(res) -> list[ReasonCode]:  # noqa: ANN001
    return [f.code for f in res.findings]


def test_mr_identifier_is_chosen_among_repetitions() -> None:
    res = HL7v2Adapter().parse(_msg("NID-9^^^GOV^NI~MRN-1^^^HOSP^MR"))
    assert res.patient_id == "MRN-1"
    assert ReasonCode.AMBIGUOUS_PATIENT_ID not in _codes(res)


def test_multiple_repetitions_without_single_mr_are_ambiguous() -> None:
    res = HL7v2Adapter().parse(_msg("A-1^^^H1^MR~B-2^^^H2^MR"))
    assert ReasonCode.AMBIGUOUS_PATIENT_ID in _codes(res)


def test_single_repetition_is_used() -> None:
    res = HL7v2Adapter().parse(_msg("PT-7^^^HOSP^MR"))
    assert res.patient_id == "PT-7"
    assert ReasonCode.AMBIGUOUS_PATIENT_ID not in _codes(res)


def test_empty_pid3_is_reported_and_blocks_scoring() -> None:
    res = HL7v2Adapter().parse(_msg(""))
    assert res.patient_id == "UNKNOWN"
    assert ReasonCode.AMBIGUOUS_PATIENT_ID in _codes(res)


def test_escaped_characters_are_decoded_in_identifier() -> None:
    res = HL7v2Adapter().parse(_msg("P\\T\\1^^^HOSP^MR"))
    assert res.patient_id == "P&1"


@pytest.mark.parametrize("msh9", ["ADT^A01", "ORM^O01", ""])
def test_non_oru_message_type_is_reported(msh9: str) -> None:
    res = HL7v2Adapter().parse(_msg("PT-7^^^HOSP^MR", msh9=msh9))
    assert ReasonCode.UNSUPPORTED_MESSAGE_TYPE in _codes(res)


def test_oru_r01_with_structure_component_is_supported() -> None:
    res = HL7v2Adapter().parse(_msg("PT-7^^^HOSP^MR", msh9="ORU^R01^ORU_R01"))
    assert ReasonCode.UNSUPPORTED_MESSAGE_TYPE not in _codes(res)
    assert res.message_type == "ORU^R01"


def test_message_control_id_is_exposed() -> None:
    res = HL7v2Adapter().parse(_msg("PT-7^^^HOSP^MR"))
    assert res.message_control_id == "CTRL-42"


def test_non_standard_encoding_characters_are_rejected_explicitly() -> None:
    with pytest.raises(ValueError, match="encoding characters"):
        HL7v2Adapter().parse(_msg("PT-7^^^HOSP^MR", enc="$~\\&"))
