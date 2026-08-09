"""
Runtime configuration — environment-driven, fail-closed on unsafe values.

ISO 14971: A misconfigured CORS origin is a confidentiality hazard
(HAZARD-CORS-001). This module refuses to start with a wildcard origin.
"""
from __future__ import annotations

import os

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
