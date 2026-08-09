"""
Integration Tests — MLLP Listener ASGI Lifespan Wiring (Phase 5 Section A).

Verifies main.py's lifespan starts/stops an MLLPListener when MLLP_ENABLED=true
and leaves it entirely off (app.state.mllp_listener is None, no port bound)
when unset — the default, backward-compatible state for existing HTTP-only
deployments.

Drives `lifespan()` directly rather than through httpx.ASGITransport: this
version of httpx does not send ASGI lifespan protocol events on its own
(confirmed against src/api/v1/health.py's `getattr(..., "start_time", ...)`
fallback, which exists precisely because lifespan startup is not guaranteed
to have run under the `client` fixture). Driving lifespan() directly is the
accurate way to test startup/shutdown behavior itself.
"""

from __future__ import annotations

import asyncio

import pytest
from main import create_app, lifespan


@pytest.mark.integration
class TestMllpDisabledByDefault:
    async def test_mllp_listener_not_started_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MLLP_ENABLED", raising=False)
        app = create_app()
        async with lifespan(app):
            assert app.state.mllp_listener is None


@pytest.mark.integration
class TestMllpEnabledViaEnv:
    async def test_mllp_listener_starts_and_accepts_connections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MLLP_ENABLED", "true")
        monkeypatch.setenv("MLLP_HOST", "127.0.0.1")
        monkeypatch.setenv("MLLP_PORT", "0")  # ephemeral port — avoid collisions
        app = create_app()
        async with lifespan(app):
            listener = app.state.mllp_listener
            assert listener is not None
            bound_port = listener.port
            assert bound_port != 0

            reader, writer = await asyncio.open_connection("127.0.0.1", bound_port)
            writer.close()
            await writer.wait_closed()

    async def test_mllp_listener_stopped_after_lifespan_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MLLP_ENABLED", "true")
        monkeypatch.setenv("MLLP_HOST", "127.0.0.1")
        monkeypatch.setenv("MLLP_PORT", "0")
        app = create_app()
        async with lifespan(app):
            captured_port = app.state.mllp_listener.port

        with pytest.raises((ConnectionRefusedError, OSError)):
            await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", captured_port), timeout=2
            )
