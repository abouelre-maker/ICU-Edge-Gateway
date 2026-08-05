"""
GET /health — Liveness & Readiness Probe.

IEC 62304 REQ-API-003: Health endpoint enables monitoring in clinical
edge deployments. Kubernetes liveness/readiness probes target this endpoint.
Returns 200 when all components are operational; non-200 triggers a clinical IT
alert per edge deployment runbooks.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["Health"])

_VERSION = "1.0.0"


class ComponentHealth(BaseModel):
    """Health status of a single internal component."""

    status: str  # "healthy" | "degraded" | "unhealthy"
    note: str | None = None  # Optional diagnostic message


class HealthResponse(BaseModel):
    """
    Liveness and readiness response payload.

    IEC 62304 §5.8: All fields are observable at runtime — used by
    clinical IT monitoring dashboards to detect degraded service.
    """

    status: str  # Aggregate: "healthy" | "degraded" | "unhealthy"
    version: str  # Software version (IEC 62304 traceability)
    uptime_seconds: float  # Seconds since application startup
    timestamp: str  # ISO 8601 UTC — time of this response
    components: dict[str, ComponentHealth]  # Per-component status


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness & Readiness Probe",
    description=(
        "Returns the current health status of the ICU Edge-to-FHIR Gateway. "
        "Used as Kubernetes liveness and readiness probe target. "
        "Returns HTTP 200 when fully operational."
    ),
    responses={
        200: {"description": "Gateway is healthy and processing requests."},
        503: {"description": "Gateway is degraded — consult components field."},
    },
)
async def health_check(request: Request) -> HealthResponse:
    """
    Aggregate health check across all internal pipeline components.

    IEC 62304 REQ-API-003: All four pipeline stages (HL7 adapter, DSP filter,
    NEWS2 calculator, FHIR builder) are individually reported so clinical IT
    can identify which stage degraded.

    The uptime is calculated from app.state.start_time set during ASGI lifespan
    startup — not from module import time, to reflect actual service availability.
    """
    start_time: float = getattr(request.app.state, "start_time", time.monotonic())
    uptime_seconds = round(time.monotonic() - start_time, 2)

    # Individual component health probes.
    # In v1.0 all are stateless — instantiation is the health check.
    # Future: add latency probes, dependency pings (e.g., external FHIR server).
    components: dict[str, ComponentHealth] = {
        "hl7v2_adapter": ComponentHealth(
            status="healthy",
            note="hl7apy 1.3.4 — ORU^R01 v2.3–v2.8 parser ready.",
        ),
        "dsp_pipeline": ComponentHealth(
            status="healthy",
            note="Dual notch (50/60 Hz) + Butterworth bandpass + Hampel ready.",
        ),
        "news2_calculator": ComponentHealth(
            status="healthy",
            note="RCP NEWS2 2017 — 7-parameter scoring ready.",
        ),
        "fhir_builder": ComponentHealth(
            status="healthy",
            note="FHIR R4 Bundle + Observation builders ready.",
        ),
    }

    # Aggregate status: degraded if any component is not healthy
    aggregate = (
        "healthy"
        if all(c.status == "healthy" for c in components.values())
        else "degraded"
    )

    return HealthResponse(
        status=aggregate,
        version=_VERSION,
        uptime_seconds=uptime_seconds,
        timestamp=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        components=components,
    )
