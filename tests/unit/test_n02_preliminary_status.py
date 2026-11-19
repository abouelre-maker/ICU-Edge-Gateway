"""
N-02 — OBX-11 'P' (preliminary) must never be emitted as FHIR status 'final'.
See regulatory/findings/N-02.md (unsigned PROPOSAL).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from domain.entities.patient_context import PatientContext
from domain.entities.score_outcome import ReasonCode
from domain.services.vitals_orchestrator import VitalsOrchestrator
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter
from infrastructure.fhir.bundle_assembler import BundleAssembler

_CTX = PatientContext(patient_id="P1")


def _msg(hr_status: str) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    return (
        f"MSH|^~\\&|MON|ICU|EHR|HOSP|{ts}||ORU^R01|C1|P|2.5.1\rPID|1||P1^^^H^MR\r"
        f"OBX|1|NM|8867-4^HR^LN||75|/min|||||{hr_status}\r"
        "OBX|2|NM|9279-1^RR^LN||16|/min|||||F\r"
        "OBX|3|NM|59408-5^SpO2^LN||97|%|||||F\r"
        "OBX|4|NM|8480-6^SBP^LN||120|mmHg|||||F\r"
        "OBX|5|NM|8310-5^Temp^LN||37.0|Cel|||||F\r"
        "OBX|6|NM|57834-7^O2^LN||0||||||F\r"
        "OBX|7|ST|67775-7^Resp^LN||A||||||F"
    )


def _bundle(hr_status: str) -> tuple[dict, object]:  # type: ignore[type-arg]
    res = HL7v2Adapter().parse(_msg(hr_status))
    r = VitalsOrchestrator().analyse(list(res.samples), _CTX, upstream_findings=res.findings)
    return BundleAssembler().assemble(r, _CTX), r


def _obs(bundle: dict, code: str) -> dict:  # type: ignore[type-arg]
    return next(
        e["resource"]
        for e in bundle["entry"]
        if e["resource"]["resourceType"] == "Observation"
        and e["resource"]["code"]["coding"][0]["code"] == code
    )


@pytest.mark.parametrize(("status", "fhir"), [("P", "preliminary"), ("C", "corrected"), ("F", "final")])
def test_vital_observation_status_follows_obx11(status: str, fhir: str) -> None:
    bundle, _ = _bundle(status)
    assert _obs(bundle, "8867-4")["status"] == fhir


def test_news2_is_preliminary_when_any_input_is_preliminary() -> None:
    bundle, r = _bundle("P")
    assert r.news2_score is not None  # still scored
    assert ReasonCode.PRELIMINARY_RESULT.value in r.assessment.reason_codes
    assert _obs(bundle, "1239842005")["status"] == "preliminary"


def test_news2_is_final_when_all_inputs_final() -> None:
    bundle, r = _bundle("F")
    assert ReasonCode.PRELIMINARY_RESULT.value not in r.assessment.reason_codes
    assert _obs(bundle, "1239842005")["status"] == "final"
