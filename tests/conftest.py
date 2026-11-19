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


# ── Test-only API key (F01-1 / F08-1; HD-E6 option 1 approved 2026-11-19) ────
# APPEND-ONLY block. Production refuses to start without GATEWAY_API_KEYS
# (fail closed). The suite gets ONE test-only key, sent by default by:
#   * the `client` fixture below (redefines the one above: same app, same
#     transport, plus the Authorization header), and
#   * every starlette TestClient constructed WITHOUT an explicit `headers=`
#     argument (HTTP and WebSocket share the client's default headers).
# A test that needs an unauthenticated request passes `headers={}` to
# TestClient, or uses the `unauthenticated_client` fixture. No existing test
# or assertion is edited. setdefault: an explicit environment still wins.
TEST_API_KEY = "test-only-gateway-api-key-not-a-secret-0001"
TEST_AUTH_HEADERS = {"Authorization": f"Bearer {TEST_API_KEY}"}
_os.environ.setdefault("GATEWAY_API_KEYS", TEST_API_KEY)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:  # noqa: F811
    """Authenticated async client (see the block comment above)."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=30.0,
        headers=TEST_AUTH_HEADERS,
    ) as test_client:
        yield test_client


@pytest.fixture
async def unauthenticated_client() -> AsyncGenerator[AsyncClient, None]:
    """Same app, no credentials: for tests that assert a 401."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
    ) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _default_test_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.testclient import TestClient

    original_init = TestClient.__init__

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("headers", TEST_AUTH_HEADERS)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", _init)


# ── Test-only MQTT topic key (F04-1; HD-E6 option 1 approved 2026-11-19) ─────
# APPEND-ONLY block. With MQTT enabled the gateway refuses to start without
# MQTT_TOPIC_KEY (opaque per-patient topics). TEST value, not a secret.
TEST_MQTT_TOPIC_KEY = "test-only-mqtt-topic-key-not-a-secret-00001"
_os.environ.setdefault("MQTT_TOPIC_KEY", TEST_MQTT_TOPIC_KEY)
