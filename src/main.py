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
from api.v1.health import router as health_router
from api.v1.ingest import router as ingest_router
from api.v1.vitals import router as vitals_router
from config import (
    get_cors_allowed_origins,
    get_mllp_enabled,
    get_mllp_host,
    get_mllp_port,
    get_mqtt_config,
    get_mqtt_enabled,
)
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from infrastructure.streaming.mllp_listener import MLLPListener
from infrastructure.streaming.mqtt_publisher import MQTTPublisher
from infrastructure.streaming.ring_buffer import StoreAndForwardRingBuffer

_log: structlog.BoundLogger = structlog.get_logger(__name__)

_FORWARD_BUFFER_CAPACITY = 10_000


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """
    ASGI lifespan: startup → yield → shutdown.

    IEC 62304 §5.8: Startup and shutdown events are timestamped and logged
    for clinical environment audit trails.
    app.state.start_time is set here — read by GET /health for uptime.

    Phase 5 Section A: when MLLP_ENABLED=true, an MLLPListener is started
    alongside the HTTP app so the edge appliance can accept HL7 v2.x
    directly over MLLP (port 2575 by default) in addition to
    POST /api/v1/ingest. Disabled by default — existing HTTP-only
    deployments are unaffected. See infrastructure/streaming/mllp_listener.py.

    When MQTT_ENABLED=true, an MQTTPublisher drains the same
    StoreAndForwardRingBuffer and forwards each FHIR Bundle to a cloud
    broker. The buffer is created unconditionally (cheap, in-memory) so
    either component can be enabled independently. Disabled by default.
    See infrastructure/streaming/mqtt_publisher.py.
    """
    app.state.start_time = time.monotonic()
    app.state.forward_buffer = StoreAndForwardRingBuffer(
        capacity=_FORWARD_BUFFER_CAPACITY
    )
    app.state.mllp_listener = None
    app.state.mqtt_publisher = None

    if get_mllp_enabled():
        listener = MLLPListener(
            host=get_mllp_host(),
            port=get_mllp_port(),
            forward_buffer=app.state.forward_buffer,
        )
        await listener.start()
        app.state.mllp_listener = listener
        _log.info(
            "icu_edge_gateway.mllp_listener.started",
            host=get_mllp_host(),
            port=listener.port,
        )

    if get_mqtt_enabled():
        mqtt_config = get_mqtt_config()
        publisher = MQTTPublisher(
            buffer=app.state.forward_buffer,
            broker_host=mqtt_config.broker_host,
            broker_port=mqtt_config.broker_port,
            topic_prefix=mqtt_config.topic_prefix,
            client_id=mqtt_config.client_id,
            use_tls=mqtt_config.use_tls,
            qos=mqtt_config.qos,
            username=mqtt_config.username,
            password=mqtt_config.password,
            publish_interval_seconds=mqtt_config.publish_interval_seconds,
            drain_batch_size=mqtt_config.drain_batch_size,
        )
        await publisher.start()
        app.state.mqtt_publisher = publisher
        _log.info(
            "icu_edge_gateway.mqtt_publisher.started",
            broker_host=mqtt_config.broker_host,
            broker_port=mqtt_config.broker_port,
        )

    _log.info("icu_edge_gateway.startup", version=app.version)
    yield
    if app.state.mqtt_publisher is not None:
        await app.state.mqtt_publisher.stop()
    if app.state.mllp_listener is not None:
        await app.state.mllp_listener.stop()
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
    # HAZARD-CORS-001: origins come from CORS_ALLOWED_ORIGINS (explicit
    # allow-list); wildcard is rejected at startup by get_cors_allowed_origins().
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_allowed_origins(),
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
    app.include_router(health_router)  # GET  /health
    app.include_router(ingest_router, prefix="/api/v1")  # POST /api/v1/ingest
    app.include_router(vitals_router, prefix="/api/v1")  # POST /api/v1/vitals

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
