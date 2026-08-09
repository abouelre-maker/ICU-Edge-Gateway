"""
Runtime configuration — environment-driven, fail-closed on unsafe values.

ISO 14971: A misconfigured CORS origin is a confidentiality hazard
(HAZARD-CORS-001). This module refuses to start with a wildcard origin.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_DEV_ORIGINS = ("http://localhost:3000",)


def get_mllp_enabled() -> bool:
    """
    MLLP_ENABLED (default: false). Edge deployments that receive HL7 v2.x
    directly over MLLP (rather than only via HTTP POST /api/v1/ingest) opt
    in explicitly — disabled by default so existing HTTP-only deployments
    are unaffected by Phase 5 Section A.
    """
    return os.getenv("MLLP_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def get_mllp_host() -> str:
    """MLLP_HOST (default: 0.0.0.0 — edge appliance listens for LAN-side monitors)."""
    return os.getenv("MLLP_HOST", "0.0.0.0")


def get_mllp_port() -> int:
    """
    MLLP_PORT (default: 2575 — conventional HL7 MLLP port).

    0 is permitted and means "ask the OS for an ephemeral port" (the
    standard asyncio.start_server convention) — used by tests and by
    deployments where the port is discovered after bind rather than fixed.
    """
    raw = os.getenv("MLLP_PORT", "2575")
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"MLLP_PORT must be an integer. Got {raw!r}.") from exc
    if not (0 <= port < 65536):
        raise ValueError(f"MLLP_PORT must be between 0 and 65535. Got {port}.")
    return port


def get_mqtt_enabled() -> bool:
    """
    MQTT_ENABLED (default: false). Edge->cloud telemetry publishing is opt-in
    — disabled by default so existing deployments without a configured MQTT
    broker are unaffected by Phase 5 Section A.
    """
    return os.getenv("MQTT_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class MQTTConfig:
    """Validated MQTT publisher configuration. Only meaningful when MQTT is enabled."""

    broker_host: str
    broker_port: int
    topic_prefix: str
    client_id: str
    use_tls: bool
    qos: int
    username: str | None
    password: str | None
    publish_interval_seconds: float
    drain_batch_size: int


def get_mqtt_config() -> MQTTConfig:
    """
    Read and validate MQTT_* environment variables.

    ISO 14971: a broker connection with TLS silently disabled is a
    confidentiality/integrity hazard for clinical telemetry leaving the
    edge appliance over an untrusted WAN link. TLS defaults to enabled;
    disabling it (MQTT_USE_TLS=false, e.g. for local-network development
    against a test broker) is permitted but logged loudly by the publisher
    at connect time — this function does not refuse to start, since a
    local-only development broker without TLS is a legitimate use case,
    unlike CORS's wildcard (HAZARD-CORS-001), which has no legitimate
    production use.
    """
    host = os.getenv("MQTT_BROKER_HOST", "localhost")

    port_raw = os.getenv("MQTT_BROKER_PORT", "8883")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError(
            f"MQTT_BROKER_PORT must be an integer. Got {port_raw!r}."
        ) from exc
    if not (0 < port < 65536):
        raise ValueError(f"MQTT_BROKER_PORT must be between 1 and 65535. Got {port}.")

    use_tls = os.getenv("MQTT_USE_TLS", "true").strip().lower() in {"1", "true", "yes"}

    qos_raw = os.getenv("MQTT_QOS", "1")
    try:
        qos = int(qos_raw)
    except ValueError as exc:
        raise ValueError(
            f"MQTT_QOS must be an integer (0, 1, or 2). Got {qos_raw!r}."
        ) from exc
    if qos not in (0, 1, 2):
        raise ValueError(f"MQTT_QOS must be 0, 1, or 2 per the MQTT spec. Got {qos}.")

    interval_raw = os.getenv("MQTT_PUBLISH_INTERVAL_SECONDS", "1.0")
    try:
        interval = float(interval_raw)
    except ValueError as exc:
        raise ValueError(
            f"MQTT_PUBLISH_INTERVAL_SECONDS must be a number. Got {interval_raw!r}."
        ) from exc
    if interval <= 0:
        raise ValueError(
            f"MQTT_PUBLISH_INTERVAL_SECONDS must be positive. Got {interval}."
        )

    batch_raw = os.getenv("MQTT_DRAIN_BATCH_SIZE", "50")
    try:
        batch_size = int(batch_raw)
    except ValueError as exc:
        raise ValueError(
            f"MQTT_DRAIN_BATCH_SIZE must be an integer. Got {batch_raw!r}."
        ) from exc
    if batch_size <= 0:
        raise ValueError(f"MQTT_DRAIN_BATCH_SIZE must be positive. Got {batch_size}.")

    return MQTTConfig(
        broker_host=host,
        broker_port=port,
        topic_prefix=os.getenv("MQTT_TOPIC_PREFIX", "icu-edge/vitals"),
        client_id=os.getenv("MQTT_CLIENT_ID", "icu-edge-gateway"),
        use_tls=use_tls,
        qos=qos,
        username=os.getenv("MQTT_USERNAME") or None,
        password=os.getenv("MQTT_PASSWORD") or None,
        publish_interval_seconds=interval,
        drain_batch_size=batch_size,
    )


def get_cors_allowed_origins() -> list[str]:
    """
    Read CORS_ALLOWED_ORIGINS (comma-separated) from the environment.

    Raises ValueError if a wildcard is configured — CORS must be an
    explicit allow-list of trusted EHR/frontend origins in production.
    Falls back to a local-dev default only when unset.
    """
    raw = os.getenv("CORS_ALLOWED_ORIGINS")
    if raw is None:
        return list(_DEFAULT_DEV_ORIGINS)

    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if not origins or "*" in origins:
        raise ValueError(
            "CORS_ALLOWED_ORIGINS must be a non-empty, comma-separated "
            "allow-list of explicit origins. Wildcard '*' is prohibited "
            "(HAZARD-CORS-001)."
        )
    return origins
