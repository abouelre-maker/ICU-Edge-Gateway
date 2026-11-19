"""
Strict loader for the proprietary OBX-3 code table (V-01).

The table (vendor_codes.json) is data, not code, and every record states its
provenance. All current entries are `inferred-UNVERIFIED`: they were not taken
from any vendor interface specification or observed traffic, so no
multi-vendor support may be claimed on their basis.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from domain.entities.vital_sign import VitalSignType

VENDOR_CODES_PATH: Final = Path(__file__).with_name("vendor_codes.json")
PROVENANCE_VALUES: Final = frozenset({"vendor-spec", "observed-traffic", "inferred-UNVERIFIED"})
_FIELDS: Final = frozenset({"code", "system", "maps_to", "provenance", "source_ref"})


class VendorCodeTableError(ValueError):
    """The code table is malformed; the adapter must not start with it."""


def load_vendor_codes(path: Path = VENDOR_CODES_PATH) -> dict[str, VitalSignType]:
    """Return {UPPER-CASE code: VitalSignType}; raise VendorCodeTableError on any defect."""
    try:
        records = json.loads(path.read_text(encoding="utf-8"))["codes"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise VendorCodeTableError(f"Cannot read vendor code table {path}: {exc}") from exc
    if not isinstance(records, list):
        raise VendorCodeTableError("'codes' must be a list.")

    table: dict[str, VitalSignType] = {}
    for i, r in enumerate(records):
        if not isinstance(r, dict) or set(r) != _FIELDS:
            raise VendorCodeTableError(f"Record {i}: fields must be exactly {sorted(_FIELDS)}.")
        if not all(isinstance(r[f], str) and r[f].strip() for f in _FIELDS):
            raise VendorCodeTableError(f"Record {i}: every field must be a non-empty string.")
        if r["provenance"] not in PROVENANCE_VALUES:
            raise VendorCodeTableError(
                f"Record {i}: provenance {r['provenance']!r} not in {sorted(PROVENANCE_VALUES)}."
            )
        try:
            vital_type = VitalSignType[r["maps_to"]]
        except KeyError as exc:
            raise VendorCodeTableError(
                f"Record {i}: maps_to {r['maps_to']!r} is not a VitalSignType."
            ) from exc
        code = r["code"].strip().upper()
        if code in table:
            raise VendorCodeTableError(f"Record {i}: duplicate code {code!r}.")
        table[code] = vital_type
    return table
