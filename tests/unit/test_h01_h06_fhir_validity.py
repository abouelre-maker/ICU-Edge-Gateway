"""H-01..H-06 (approved 2026-11-19): FHIR R4 validity of the produced Bundle."""

from __future__ import annotations

import re
from typing import Any

from httpx import AsyncClient

from tests.integration.test_api_vitals import FULL_VITALS
from tests.integration.test_live_websocket import FULL_ORU

_UUID_URN = re.compile(r"^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


async def _ingest(client: AsyncClient, msg: str = FULL_ORU, **params: str) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/ingest", content=msg, params=params, headers={"Content-Type": "text/plain"}
    )
    assert r.status_code == 200
    return r.json()


async def test_h01_bundle_has_no_note_or_extension(client: AsyncClient) -> None:
    b = await _ingest(client)
    assert "note" not in b and "extension" not in b
    assert {"system": "https://samd.icu-edge/fhir/extensions/iec62304-software-version", "code": "1.0.0"} in b["meta"]["tag"]


async def test_h01_advisory_statement_still_present(client: AsyncClient) -> None:
    r = await client.post("/api/v1/vitals", json=FULL_VITALS)
    b = r.json()
    news2 = [
        e["resource"] for e in b["entry"]
        if e["resource"]["resourceType"] == "Observation" and "note" in e["resource"]
    ]
    assert news2 and any("advisory" in n["text"].lower() for n in news2[0]["note"])


async def test_h02_collection_has_no_total(client: AsyncClient) -> None:
    b = await _ingest(client)
    assert b["type"] == "collection" and "total" not in b


async def test_h03_same_message_gives_same_ids(client: AsyncClient) -> None:
    a = await _ingest(client)
    b = await _ingest(client)
    assert [e["fullUrl"] for e in a["entry"]] == [e["fullUrl"] for e in b["entry"]]
    assert a["id"] == b["id"]


async def test_h03_different_values_give_different_ids(client: AsyncClient) -> None:
    a = await client.post("/api/v1/vitals", json=FULL_VITALS)
    other = {**FULL_VITALS, "patient_id": "PT-OTHER-9"}
    b = await client.post("/api/v1/vitals", json=other)
    ids_a = {e["fullUrl"] for e in a.json()["entry"]}
    ids_b = {e["fullUrl"] for e in b.json()["entry"]}
    assert not ids_a & ids_b


async def test_h04_every_fullurl_is_a_uuid_urn(client: AsyncClient) -> None:
    b = await _ingest(client, device_vendor="PHILIPS")
    assert any(e["resource"]["resourceType"] == "Device" for e in b["entry"])
    for e in b["entry"]:
        assert _UUID_URN.match(e["fullUrl"]), e["fullUrl"]


async def test_h05_unsafe_identifier_is_a_logical_reference(client: AsyncClient) -> None:
    b = await _ingest(client, FULL_ORU.replace("PT-WS-001", "MRN 77/x"))
    subjects = [e["resource"]["subject"] for e in b["entry"] if "subject" in e["resource"]]
    assert subjects
    for s in subjects:
        assert "reference" not in s
        assert s["identifier"]["value"] == "MRN 77/x"


async def test_h05_unsafe_identifier_is_never_scored(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/ingest",
        content=FULL_ORU.replace("PT-WS-001", "MRN 77/x"),
        headers={"Content-Type": "text/plain"},
    )
    assert r.headers["X-Score-Outcome"] != "scored"


async def test_h06_consciousness_code_differs_from_value(client: AsyncClient) -> None:
    b = await _ingest(client)
    for e in b["entry"]:
        res = e["resource"]
        if res.get("valueCodeableConcept"):
            codes = {c["code"] for c in res["code"]["coding"]}
            values = {c["code"] for c in res["valueCodeableConcept"]["coding"]}
            assert not codes & values


def test_h01_dashboard_reads_warnings_from_operation_outcome() -> None:
    import sys

    sys.path.insert(0, "demo")
    from dashboard_logic import extract_warnings

    bundle = {
        "entry": [
            {
                "resource": {
                    "resourceType": "OperationOutcome",
                    "issue": [
                        {
                            "severity": "information",
                            "code": "informational",
                            "details": {"coding": [{"code": "PIPELINE_WARNING"}]},
                            "diagnostics": "SPO2 excluded",
                        }
                    ],
                }
            }
        ]
    }
    assert extract_warnings(bundle) == ["SPO2 excluded"]
    assert extract_warnings({"note": [{"text": "legacy"}]}) == ["legacy"]
