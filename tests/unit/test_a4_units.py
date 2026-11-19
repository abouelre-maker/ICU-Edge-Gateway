"""
A4 — units and numeric formats must never be silently misread.
See regulatory/findings/A4.md (unsigned PROPOSAL).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from domain.entities.score_outcome import ReasonCode
from domain.entities.vital_sign import VitalSignType, VitalSignUnit
from httpx import AsyncClient
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter

_MSH = "MSH|^~\\&|MON|ICU|EHR|HOSP|20260929110000||ORU^R01|C1|P|2.5.1\rPID|1||P1^^^H^MR\r"


def _parse(obx: str):  # noqa: ANN202
    return HL7v2Adapter().parse(_MSH + obx)


def test_decimal_comma_is_read_as_decimal() -> None:
    res = _parse("OBX|1|NM|8310-5^Temp^LN||39,5|Cel|||||F")
    assert len(res.samples) == 1 and res.samples[0].value == 39.5


def test_fahrenheit_is_converted_to_celsius() -> None:
    res = _parse("OBX|1|NM|8310-5^Temp^LN||101.3|[degF]|||||F")
    s = res.samples[0]
    assert s.unit is VitalSignUnit.CELSIUS
    assert s.value == pytest.approx(38.5, abs=0.01)


def test_kpa_blood_pressure_is_converted_to_mmhg() -> None:
    res = _parse("OBX|1|NM|8480-6^SBP^LN||16|kPa|||||F")
    s = res.samples[0]
    assert s.unit is VitalSignUnit.MMHG
    assert s.value == pytest.approx(120.0, abs=0.1)


@pytest.mark.parametrize("value", ["<50", ">100", "<^50", ">=^95"])
def test_comparator_values_are_non_exact_and_not_scored(value: str) -> None:
    res = _parse(f"OBX|1|SN|59408-5^SpO2^LN||{value}|%|||||F")
    assert res.samples == ()
    assert ReasonCode.NON_EXACT_VALUE in [f.code for f in res.findings]


def test_compound_value_in_numeric_field_is_rejected() -> None:
    res = _parse("OBX|1|NM|8480-6^SBP^LN||120/80|mmHg|||||F")
    assert res.samples == ()
    assert ReasonCode.NON_EXACT_VALUE in [f.code for f in res.findings]


def test_unknown_unit_is_ambiguous_not_defaulted() -> None:
    res = _parse("OBX|1|NM|8867-4^HR^LN||72|furlongs|||||F")
    assert res.samples == ()
    assert ReasonCode.AMBIGUOUS_UNIT in [f.code for f in res.findings]


def test_incompatible_unit_is_ambiguous() -> None:
    res = _parse("OBX|1|NM|59408-5^SpO2^LN||97|mmHg|||||F")
    assert res.samples == ()
    assert ReasonCode.AMBIGUOUS_UNIT in [f.code for f in res.findings]


def test_absent_unit_uses_type_default() -> None:
    res = _parse("OBX|1|NM|8867-4^HR^LN||72||||||F")
    assert len(res.samples) == 1 and res.samples[0].unit is VitalSignUnit.BPM


def _vitals_payload(temp_value: float, temp_unit: str, hr_unit: str = "bpm") -> dict[str, object]:
    ts = datetime.now(tz=timezone.utc).isoformat()
    rows = [
        ("RESPIRATORY_RATE", 16, "breaths/min"),
        ("SPO2", 97, "%"),
        ("SYSTOLIC_BP", 120, "mmHg"),
        ("HEART_RATE", 75, hr_unit),
        ("TEMPERATURE_CELSIUS", temp_value, temp_unit),
        ("SUPPLEMENTAL_O2", 0, "bool"),
    ]
    samples: list[dict[str, object]] = [
        {"vital_sign_type": t, "value": v, "unit": u, "timestamp": ts} for t, v, u in rows
    ]
    samples.append(
        {"vital_sign_type": "CONSCIOUSNESS", "value": 0, "unit": "avpu",
         "timestamp": ts, "avpu_level": "A"}
    )
    return {"patient_id": "PT-A4", "samples": samples}


class TestVitalsEndpointHonoursUnit:
    async def test_fahrenheit_is_converted(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/vitals", json=_vitals_payload(101.3, "[degF]"))
        assert resp.status_code == 200
        # 101.3 °F = 38.5 °C → temperature score 1 (38.1–39.0); not an artifact.
        assert resp.headers["X-Score-Outcome"] == "scored"
        assert resp.headers["X-NEWS2-Total"] == "1"

    async def test_incompatible_unit_is_excluded_and_reported(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/vitals", json=_vitals_payload(37.0, "Cel", hr_unit="mmHg")
        )
        assert resp.status_code == 200
        assert resp.headers["X-Score-Outcome"] == "incomplete"
        reasons = resp.headers["X-Score-Reasons"]
        assert "AMBIGUOUS_UNIT" in reasons and "MISSING_PARAMETER" in reasons


def test_vital_type_enum_unchanged() -> None:
    assert VitalSignType.TEMPERATURE_CELSIUS.value == "TEMPERATURE_CELSIUS"
