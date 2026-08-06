"""
Runtime configuration — environment-driven, fail-closed on unsafe values.

ISO 14971: A misconfigured CORS origin is a confidentiality hazard
(HAZARD-CORS-001). This module refuses to start with a wildcard origin.
"""
from __future__ import annotations

import os

_DEFAULT_DEV_ORIGINS = ("http://localhost:3000",)


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
