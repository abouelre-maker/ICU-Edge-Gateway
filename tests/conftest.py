"""
Root pytest fixtures — shared across all test modules.

IEC 62304 §5.7: Shared test infrastructure. Changes here affect the
entire test suite. Modify with care and re-run all 245+ tests.

asyncio_mode = "auto" (pyproject.toml): all async fixtures and test
functions are automatically detected — no @pytest.mark.asyncio required.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from main import create_app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP test client connected to a fresh, isolated app instance.

    Uses httpx.ASGITransport — tests execute against the ASGI app directly
    with no network I/O. The ASGITransport context manager triggers the
    FastAPI lifespan (startup + shutdown), so app.state.start_time is set.

    IEC 62304 §5.7: Each test receives a fresh app to prevent state leakage
    between tests (e.g., uptime_seconds, mutable state).
    """
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=30.0,
    ) as test_client:
        yield test_client


# ── Test-only NEWS2 staleness configuration (A2, decision Q1(b)) ─────────────
# APPEND-ONLY block (continuation directive §4). Production refuses to start
# unless every NEWS2_STALENESS_WINDOW_<TYPE>_SECONDS is set; no clinical value
# exists anywhere in src/. These are TEST FIXTURE values, not clinical values:
# ten years, so the suite's fixed historical timestamps (e.g. 2024-01-15) stay
# inside the window. Tests that exercise staleness construct ScoringGate with
# their own explicit policy. setdefault: an explicit environment still wins.
import os as _os  # noqa: E402

for _vital_type in (
    "RESPIRATORY_RATE",
    "SPO2",
    "SUPPLEMENTAL_O2",
    "SYSTOLIC_BP",
    "HEART_RATE",
    "CONSCIOUSNESS",
    "TEMPERATURE_CELSIUS",
):
    _os.environ.setdefault(
        f"NEWS2_STALENESS_WINDOW_{_vital_type}_SECONDS", str(10 * 365 * 24 * 3600)
    )
