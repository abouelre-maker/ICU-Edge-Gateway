"""
A1 — False NORMAL: missing consciousness / O2 status must never default to
Alert / room air, and O2 / AVPU encodings must not be misread as "normal".

See regulatory/findings/A1.md (unsigned PROPOSAL).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from domain.entities.patient_context import PatientContext
from domain.entities.score_outcome import ReasonCode, ScoreOutcome
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.vitals_orchestrator import VitalsOrchestrator
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter

_T = VitalSignType
_U = VitalSignUnit
_CTX = PatientContext(patient_id="PT-A1")


def _numeric_five(ts: datetime) -> list[VitalSignSample]:
    return [
        VitalSignSample(vital_sign_type=_T.RESPIRATORY_RATE, value=16, unit=_U.BREATHS_PER_MIN, timestamp=ts),
        VitalSignSample(vital_sign_type=_T.SPO2, value=97, unit=_U.PERCENT, timestamp=ts),
        VitalSignSample(vital_sign_type=_T.SYSTOLIC_BP, value=120, unit=_U.MMHG, timestamp=ts),
        VitalSignSample(vital_sign_type=_T.HEART_RATE, value=75, unit=_U.BPM, timestamp=ts),
        VitalSignSample(vital_sign_type=_T.TEMPERATURE_CELSIUS, value=37.0, unit=_U.CELSIUS, timestamp=ts),
    ]


def _avpu(ts: datetime) -> VitalSignSample:
    return VitalSignSample(
        vital_sign_type=_T.CONSCIOUSNESS, value=0.0, unit=_U.AVPU_SCALE,
        timestamp=ts, avpu_level=AVPULevel.ALERT,
    )


def _o2(ts: datetime, on: bool = False) -> VitalSignSample:
    return VitalSignSample(
        vital_sign_type=_T.SUPPLEMENTAL_O2, value=1.0 if on else 0.0,
        unit=_U.BOOLEAN, timestamp=ts,
    )


class TestMissingInputsAreIncomplete:
    def test_missing_consciousness_is_incomplete_not_alert(self) -> None:
        ts = datetime.now(tz=timezone.utc)
        r = VitalsOrchestrator().analyse([*_numeric_five(ts), _o2(ts)], _CTX)
        assert r.news2_score is None
        assert r.assessment.outcome is ScoreOutcome.INCOMPLETE
        assert ReasonCode.MISSING_CONSCIOUSNESS.value in r.assessment.reason_codes

    def test_missing_o2_status_is_incomplete_not_room_air(self) -> None:
        ts = datetime.now(tz=timezone.utc)
        r = VitalsOrchestrator().analyse([*_numeric_five(ts), _avpu(ts)], _CTX)
        assert r.news2_score is None
        assert r.assessment.outcome is ScoreOutcome.INCOMPLETE
        assert ReasonCode.MISSING_O2_STATUS.value in r.assessment.reason_codes

    def test_all_seven_present_is_scored(self) -> None:
        ts = datetime.now(tz=timezone.utc)
        r = VitalsOrchestrator().analyse([*_numeric_five(ts), _avpu(ts), _o2(ts)], _CTX)
        assert r.assessment.outcome is ScoreOutcome.SCORED
        assert r.news2_score is not None and r.news2_score.total == 0


_MSH = "MSH|^~\\&|MON|ICU|EHR|HOSP|20260101120000||ORU^R01|C1|P|2.5.1\rPID|1||P1^^^H^MR\r"


def _parse_one(obx: str) -> tuple[list[VitalSignSample], tuple[str, ...]]:
    res = HL7v2Adapter().parse(_MSH + obx)
    return list(res.samples), tuple(f.code.value for f in res.findings)


class TestO2Parsing:
    @pytest.mark.parametrize(
        ("obx5", "obx6", "expected_on_o2"),
        [
            ("0.4", "", 1.0),        # FiO2 as a fraction
            ("0.21", "", 0.0),       # room-air fraction
            ("2", "L/min", 1.0),     # flow in L/min
            ("15", "L/min", 1.0),
            ("0", "L/min", 0.0),     # no flow
            ("40", "%", 1.0),        # FiO2 percent
            ("21", "%", 0.0),
            ("1", "", 1.0),          # boolean encodings unchanged
            ("0", "", 0.0),
        ],
    )
    def test_o2_encodings(self, obx5: str, obx6: str, expected_on_o2: float) -> None:
        samples, _ = _parse_one(f"OBX|1|NM|3151-8^O2 flow^LN||{obx5}|{obx6}|||||F")
        assert len(samples) == 1
        assert samples[0].value == expected_on_o2

    @pytest.mark.parametrize("obx5", ["2", "15", "5"])
    def test_unitless_flow_like_number_is_ambiguous_not_room_air(self, obx5: str) -> None:
        samples, codes = _parse_one(f"OBX|1|NM|3151-8^O2 flow^LN||{obx5}||||||F")
        assert samples == []
        assert ReasonCode.AMBIGUOUS_UNIT.value in codes


class TestAvpuParsing:
    def test_cwe_coded_avpu_uses_first_component(self) -> None:
        samples, _ = _parse_one("OBX|1|CWE|67775-7^Responsiveness^LN||V^Voice^L|||||F")
        assert len(samples) == 1 and samples[0].avpu_level is AVPULevel.VOICE

    def test_cwe_coded_avpu_text_component(self) -> None:
        samples, _ = _parse_one("OBX|1|CWE|67775-7^Responsiveness^LN||X^Alert^L|||||F")
        assert len(samples) == 1 and samples[0].avpu_level is AVPULevel.ALERT

    def test_unmapped_avpu_string_is_reported(self) -> None:
        samples, codes = _parse_one("OBX|1|ST|AVPU^LOC^L||Drowsy|||||F")
        assert samples == []
        assert ReasonCode.UNMAPPED_AVPU.value in codes

    def test_unmapped_avpu_makes_score_incomplete(self) -> None:
        now = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        msg = (
            f"MSH|^~\\&|MON|ICU|EHR|HOSP|{now}||ORU^R01|C1|P|2.5.1\rPID|1||P1^^^H^MR\r"
            "OBX|1|NM|9279-1^RR^LN||16|/min|||||F\r"
            "OBX|2|NM|59408-5^SpO2^LN||97|%|||||F\r"
            "OBX|3|NM|8480-6^SBP^LN||120|mmHg|||||F\r"
            "OBX|4|NM|8867-4^HR^LN||75|/min|||||F\r"
            "OBX|5|NM|8310-5^Temp^LN||37.0|Cel|||||F\r"
            "OBX|6|NM|3151-8^O2^LN||0||||||F\r"
            "OBX|7|ST|AVPU^LOC^L||Drowsy|||||F"
        )
        res = HL7v2Adapter().parse(msg)
        r = VitalsOrchestrator().analyse(
            list(res.samples), _CTX, upstream_findings=res.findings
        )
        assert r.news2_score is None
        codes = r.assessment.reason_codes
        assert ReasonCode.UNMAPPED_AVPU.value in codes
        assert ReasonCode.MISSING_CONSCIOUSNESS.value in codes
