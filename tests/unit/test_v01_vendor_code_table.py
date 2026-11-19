"""
V-01 — the proprietary OBX-3 code table is data with explicit provenance.

Every current entry is inferred, not taken from a vendor specification or
observed traffic: provenance "inferred-UNVERIFIED", source_ref "TODO-VERIFY".
Closing V-01 for real needs a de-identified real sample (HD-E3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from domain.entities.vital_sign import VitalSignType
from infrastructure.adapters import hl7v2_adapter
from infrastructure.adapters.vendor_codes import (
    VENDOR_CODES_PATH,
    VendorCodeTableError,
    load_vendor_codes,
)


def test_table_file_exists_and_every_entry_is_marked_unverified() -> None:
    records = json.loads(VENDOR_CODES_PATH.read_text(encoding="utf-8"))["codes"]
    assert records, "table must not be empty"
    for r in records:
        assert set(r) == {"code", "system", "maps_to", "provenance", "source_ref"}
        assert r["provenance"] == "inferred-UNVERIFIED"
        assert r["source_ref"] == "TODO-VERIFY"


def test_adapter_mapping_comes_from_the_data_file() -> None:
    assert load_vendor_codes() == hl7v2_adapter._VENDOR_TO_TYPE
    assert hl7v2_adapter._VENDOR_TO_TYPE["NIBP-S"] is VitalSignType.SYSTOLIC_BP


def _write(tmp_path: Path, codes: list[dict[str, str]]) -> Path:
    p = tmp_path / "codes.json"
    p.write_text(json.dumps({"codes": codes}), encoding="utf-8")
    return p


_GOOD = {
    "code": "HR",
    "system": "proprietary",
    "maps_to": "HEART_RATE",
    "provenance": "inferred-UNVERIFIED",
    "source_ref": "TODO-VERIFY",
}


@pytest.mark.parametrize(
    "bad",
    [
        {**_GOOD, "provenance": "vendor-ish"},
        {**_GOOD, "maps_to": "PULSE_PRESSURE"},
        {k: v for k, v in _GOOD.items() if k != "source_ref"},
        {**_GOOD, "extra": "x"},
        {**_GOOD, "source_ref": ""},
    ],
)
def test_loader_rejects_invalid_records(tmp_path: Path, bad: dict[str, str]) -> None:
    with pytest.raises(VendorCodeTableError):
        load_vendor_codes(_write(tmp_path, [bad]))


def test_loader_rejects_duplicate_codes(tmp_path: Path) -> None:
    with pytest.raises(VendorCodeTableError, match="duplicate"):
        load_vendor_codes(_write(tmp_path, [_GOOD, {**_GOOD, "code": "hr"}]))


def test_verified_provenance_values_are_accepted(tmp_path: Path) -> None:
    good = [
        {**_GOOD, "code": "A", "provenance": "vendor-spec", "source_ref": "doc-1 §2"},
        {**_GOOD, "code": "B", "provenance": "observed-traffic", "source_ref": "sample-3"},
    ]
    assert load_vendor_codes(_write(tmp_path, good)) == {
        "A": VitalSignType.HEART_RATE,
        "B": VitalSignType.HEART_RATE,
    }


def test_adapter_docstring_makes_no_multi_vendor_claim() -> None:
    doc = hl7v2_adapter.__doc__ or ""
    assert "Philips IntelliVue / GE CARESCAPE" not in doc
    assert "inferred" in doc.lower()
