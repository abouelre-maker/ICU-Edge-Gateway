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
