"""F-12 (identifiers out of logs and 422 bodies) and F-13 (no library versions on /health)."""

from __future__ import annotations

import structlog
from httpx import AsyncClient
from infrastructure import log_privacy

from tests.integration.test_api_vitals import FULL_VITALS
from tests.integration.test_live_websocket import FULL_ORU


async def test_422_does_not_echo_the_patient_identifier(client: AsyncClient) -> None:
    r = await client.post("/api/v1/vitals", json={**FULL_VITALS, "patient_id": "MRN-SECRET/1"})
    assert r.status_code == 422
    assert "MRN-SECRET" not in r.text
    assert r.json()["detail"][0]["loc"] == ["body", "patient_id"]


async def test_422_does_not_echo_other_input(client: AsyncClient) -> None:
    r = await client.post("/api/v1/vitals", json={**FULL_VITALS, "spo2_scale": "LEAKME"})
    assert r.status_code == 422
    assert "LEAKME" not in r.text


def test_processor_pseudonymises_identifier_keys() -> None:
    out = log_privacy.pseudonymize_identifiers(
        None, "info", {"event": "x", "patient_id": "MRN-123", "sample_count": 3}
    )
    assert out["patient_id"].startswith("pid:") and "MRN-123" not in out["patient_id"]
    assert out["sample_count"] == 3


def test_pseudonym_is_stable_and_distinct() -> None:
    assert log_privacy.pseudonym("MRN-1") == log_privacy.pseudonym("MRN-1")
    assert log_privacy.pseudonym("MRN-1") != log_privacy.pseudonym("MRN-2")


def test_unknown_and_none_are_left_alone() -> None:
    out = log_privacy.pseudonymize_identifiers(
        None, "info", {"patient_id": "UNKNOWN", "patient": None}
    )
    assert out == {"patient_id": "UNKNOWN", "patient": None}


def test_processor_is_installed_by_the_app() -> None:
    import main  # noqa: F401  (import installs it)

    assert log_privacy.pseudonymize_identifiers in structlog.get_config()["processors"]


async def test_ingest_logs_carry_no_identifier(client: AsyncClient, capsys) -> None:  # type: ignore[no-untyped-def]
    r = await client.post(
        "/api/v1/ingest", content=FULL_ORU, headers={"Content-Type": "text/plain"}
    )
    assert r.status_code == 200
    out = capsys.readouterr().out
    assert "PT-WS-001" not in out
    assert "pid:" in out


async def test_health_carries_no_library_version(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert "hl7apy 1." not in r.text
