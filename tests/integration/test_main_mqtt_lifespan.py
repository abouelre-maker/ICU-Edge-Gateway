"""
Integration Tests — MQTT Publisher ASGI Lifespan Wiring (Phase 5 Section A).

Verifies main.py's lifespan starts/stops an MQTTPublisher when MQTT_ENABLED=
true and leaves it off by default. No real MQTT broker is available in this
environment — paho-mqtt's connect_async() + loop_start() is non-blocking and
retries connection on its own network thread, so startup must succeed (and
shutdown must be clean) even against an unreachable broker; that resilience
is exactly what HAZARD-STREAM-003 requires and is what's verified here.

Drives lifespan() directly — see test_main_mllp_lifespan.py for why
(httpx.ASGITransport does not send ASGI lifespan protocol events here).
"""

from __future__ import annotations

import pytest
from main import create_app, lifespan


@pytest.mark.integration
class TestMqttDisabledByDefault:
    async def test_mqtt_publisher_not_started_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MQTT_ENABLED", raising=False)
        app = create_app()
        async with lifespan(app):
            assert app.state.mqtt_publisher is None
            # Buffer is always created (cheap, in-memory) regardless of
            # which forwarder is enabled.
            assert app.state.forward_buffer is not None


@pytest.mark.integration
class TestMqttEnabledViaEnv:
    async def test_publisher_starts_against_unreachable_broker_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MQTT_ENABLED", "true")
        # Port 1 is a reserved, never-listening port -- guaranteed unreachable,
        # without depending on external network state.
        monkeypatch.setenv("MQTT_BROKER_HOST", "127.0.0.1")
        monkeypatch.setenv("MQTT_BROKER_PORT", "1")
        monkeypatch.setenv("MQTT_USE_TLS", "false")
        app = create_app()

        async with lifespan(app):
            assert app.state.mqtt_publisher is not None
            assert app.state.mqtt_publisher.published_count == 0

    async def test_publisher_shares_the_same_buffer_as_mllp_listener(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MQTT_ENABLED", "true")
        monkeypatch.setenv("MQTT_BROKER_HOST", "127.0.0.1")
        monkeypatch.setenv("MQTT_BROKER_PORT", "1")
        monkeypatch.setenv("MQTT_USE_TLS", "false")
        monkeypatch.setenv("MLLP_ENABLED", "true")
        monkeypatch.setenv("MLLP_HOST", "127.0.0.1")
        monkeypatch.setenv("MLLP_PORT", "0")
        app = create_app()

        async with lifespan(app):
            assert app.state.mllp_listener.forward_buffer is app.state.forward_buffer
