"""
ICU Edge-to-FHIR Interoperability Gateway — ASGI Entry Point.

IEC 62304 §5.3: create_app() GoF Factory Method assembles all application
components. The ASGI `app` instance is the single deployable artifact.
ISO 14971: All request/response lifecycle handlers are registered here,
ensuring consistent audit logging and error handling for every clinical request.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.v1.health import router as health_router
from api.v1.ingest import router as ingest_router
from api.v1.vitals import router as vitals_router

_log: structlog.BoundLogger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """
    ASGI lifespan: startup → yield → shutdown.

    IEC 62304 §5.8: Startup and shutdown events are timestamped and logged
    for clinical environment audit trails.
    app.state.start_time is set here — read by GET /health for uptime.
    """
    app.state.start_time = time.monotonic()
    _log.info("icu_edge_gateway.startup", version=app.version)
    yield
    uptime = round(time.monotonic() - app.state.start_time, 2)
    _log.info("icu_edge_gateway.shutdown", uptime_seconds=uptime)


def create_app() -> FastAPI:
    """
    GoF Factory Method: construct and configure the FastAPI ASGI application.

    IEC 62304 §5.3: All wiring — routers, middleware, exception handlers —
    occurs here. Test fixtures call this to get an isolated app instance.
    """
    app = FastAPI(
        title="ICU Edge-to-FHIR Interoperability Gateway",
        description=(
            "**SaMD Middleware** — Transforms legacy ICU monitor data (HL7 v2.x) "
            "into FHIR R4 Bundles with embedded NEWS2 clinical scoring.\n\n"
            "**Regulatory:** IEC 62304 Class B · ISO 14971 · "
            "FDA CDS Non-Device Exemption · Health Canada Class II.\n\n"
            "**Standards:** HL7 FHIR R4 · LOINC · SNOMED CT · UCUM · RCP NEWS2 2017."
        ),
        version="1.0.0",
        license_info={"name": "Proprietary — IEC 62304 Class B SaMD"},
        contact={
            "name": "Housam Abouelreish",
            "url": "https://linkedin.com/in/housam-abouelreish-805352226",
        },
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── Middleware ─────────────────────────────────────────────────────────────
    # NOTE: In production, restrict allow_origins to specific EHR endpoints.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept", "X-Request-ID"],
    )

    # ── Global Exception Handlers ──────────────────────────────────────────────

    @app.exception_handler(ValueError)
    async def value_error_handler(
        request: Request,
        exc: ValueError,
    ) -> JSONResponse:
        """
        Domain ValueError → HTTP 422 Unprocessable Entity.

        IEC 62304 REQ-API-001: Stack traces must never reach API consumers.
        Covers: invalid HL7 messages, physiological range violations,
        NEWS2 parameter errors caught before Pydantic layer.
        """
        _log.warning(
            "api.domain_validation_error",
            path=str(request.url.path),
            method=request.method,
            error=str(exc),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "validation_error", "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """
        Catch-all: prevents implementation detail leakage.

        IEC 62304 REQ-API-002: All unhandled exceptions are logged at ERROR
        level server-side and returned as generic 500 to the client.
        """
        _log.error(
            "api.unhandled_exception",
            path=str(request.url.path),
            method=request.method,
            exc_type=type(exc).__name__,
            error=str(exc),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_server_error",
                "detail": (
                    "An unexpected error occurred. "
                    "Consult the gateway logs for details."
                ),
            },
        )

    # ── Routers ────────────────────────────────────────────────────────────────
    app.include_router(health_router)                     # GET  /health
    app.include_router(ingest_router, prefix="/api/v1")   # POST /api/v1/ingest
    app.include_router(vitals_router, prefix="/api/v1")   # POST /api/v1/vitals

    return app


# ASGI application instance — used by uvicorn (prod) and ASGITransport (tests)
app: FastAPI = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        reload=False,
        log_config=None,  # structlog handles all logging
    )