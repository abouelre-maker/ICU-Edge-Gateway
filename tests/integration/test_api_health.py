"""
Integration Tests — GET /health endpoint.

IEC 62304 §5.7: Verifies health endpoint contract.
All tests use the shared `client` fixture from tests/conftest.py.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestHealthEndpoint:
    """GET /health — liveness & readiness probe."""

    async def test_returns_http_200(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert response.status_code == 200

    async def test_content_type_is_json(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert "application/json" in response.headers["content-type"]

    async def test_status_is_healthy(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert response.json()["status"] == "healthy"

    async def test_version_is_1_0_0(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert response.json()["version"] == "1.0.0"

    async def test_uptime_seconds_is_non_negative(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        uptime = response.json()["uptime_seconds"]
        assert isinstance(uptime, float)
        assert uptime >= 0.0, (
            f"uptime_seconds must be non-negative. Got {uptime}. "
            "IEC 62304 REQ-API-003: uptime is measured from app.state.start_time."
        )

    async def test_timestamp_is_present(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert "timestamp" in response.json()

    async def test_timestamp_has_timezone_suffix(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        ts: str = response.json()["timestamp"]
        assert ts.endswith("Z") or "+" in ts[10:] or "-" in ts[10:], (
            f"timestamp '{ts}' must include timezone. " "ISO 14971 HAZARD-TIME-001."
        )

    async def test_components_field_present(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert "components" in response.json()

    async def test_components_dict_non_empty(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert len(response.json()["components"]) > 0

    async def test_all_components_are_healthy(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        components = response.json()["components"]
        for name, comp in components.items():
            assert comp["status"] == "healthy", (
                f"Component '{name}' must be 'healthy'. Got '{comp['status']}'. "
                "IEC 62304 REQ-API-003."
            )

    async def test_expected_components_present(self, client: AsyncClient) -> None:
        """All four pipeline components must be individually reported."""
        response = await client.get("/health")
        components = response.json()["components"]
        expected = {
            "hl7v2_adapter",
            "dsp_pipeline",
            "news2_calculator",
            "fhir_builder",
        }
        assert expected.issubset(set(components.keys())), (
            f"Missing components: {expected - set(components.keys())}. "
            "IEC 62304 REQ-API-003: all pipeline stages must be individually reported."
        )

    async def test_second_call_uptime_is_greater(self, client: AsyncClient) -> None:
        """Uptime must increase monotonically between calls."""
        r1 = await client.get("/health")
        r2 = await client.get("/health")
        uptime1 = r1.json()["uptime_seconds"]
        uptime2 = r2.json()["uptime_seconds"]
        assert uptime2 >= uptime1, (
            "Uptime must not decrease between calls. "
            "IEC 62304 REQ-API-003: monotonic clock required."
        )
