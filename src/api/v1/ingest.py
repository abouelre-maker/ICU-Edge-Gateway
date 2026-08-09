"""
POST /api/v1/ingest — Raw HL7 v2.x ORU^R01 Ingestion Endpoint.

Accepts a raw HL7 v2.x ORU^R01 message body (text/plain), parses it using
the HL7v2Adapter, runs the full domain pipeline, and returns a FHIR R4 Bundle.

IEC 62304 §5.3: Single responsibility — HTTP adaptation layer only.
All clinical logic is in the domain layer. This endpoint converts between
HTTP request/response and domain types.

ISO 14971 HAZARD-API-001: spo2_scale must be explicitly provided when the
patient is known to have hypercapnic respiratory failure (COPD). Defaulting
to SCALE_1 is conservative — it will not underscore a non-COPD patient.

FDA CDS Non-Device Exemption: The FHIR Bundle returned is advisory only.
The X-CDS-Advisory-Only response header signals this to downstream consumers.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from domain.entities.device_context import DeviceContext, HL7Version, MonitorVendor
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.services.vitals_orchestrator import VitalsOrchestrator
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter
from infrastructure.fhir.bundle_assembler import BundleAssembler

_log: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["HL7 Ingestion"])

# Shared stateless service instances (safe for concurrent use)
_adapter = HL7v2Adapter()
_orchestrator = VitalsOrchestrator()
_assembler = BundleAssembler()


@router.post(
    "/ingest",
    status_code=status.HTTP_200_OK,
    summary="Ingest Raw HL7 v2.x ORU^R01 Message",
    description=(
        "Accepts a raw HL7 v2.x ORU^R01 message (text/plain body). "
        "Parses OBX segments, applies DSP artifact rejection, calculates "
        "NEWS2 score, and returns a FHIR R4 Bundle.\n\n"
        "**Patient ID** is extracted from PID-3 of the HL7 message.\n\n"
        "**SpO2 Scale:** Set `spo2_scale=SCALE_2` **only** for patients "
        "with confirmed hypercapnic respiratory failure (COPD type 2). "
        "Default is SCALE_1 for all other patients."
    ),
    responses={
        200: {
            "description": "FHIR R4 Bundle (application/fhir+json)",
            "content": {
                "application/fhir+json": {
                    "schema": {"type": "object"},
                }
            },
        },
        422: {"description": "Invalid HL7 message or missing required content."},
        500: {"description": "Unexpected internal error — consult gateway logs."},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "text/plain": {
                    "schema": {
                        "type": "string",
                        "example": (
                            "MSH|^~\\&|MONITOR|ICU|EHR|HOSPITAL|20240115100000"
                            "||ORU^R01|MSG001|P|2.5.1\r"
                            "PID|1||PT-001^^^HOSP^MR\r"
                            "OBX|1|NM|8867-4^Heart rate^LN||72|/min||||F"
                        ),
                    }
                }
            },
        }
    },
)
async def ingest_hl7(
    request: Request,
    spo2_scale: Annotated[
        SpO2Scale,
        Query(
            description=(
                "SpO2 scoring scale. "
                "SCALE_1 (default) = all patients. "
                "SCALE_2 = confirmed hypercapnic respiratory failure ONLY."
                " ISO 14971 HAZARD-SPO2-001."
            )
        ),
    ] = SpO2Scale.SCALE_1,
    encounter_id: Annotated[
        str | None,
        Query(
            description="FHIR Encounter logical ID. Populates Observation.encounter."
        ),
    ] = None,
    device_id: Annotated[
        str | None,
        Query(
            description="FHIR Device logical ID override. Auto-detected from MSH-3 if absent."
        ),
    ] = None,
    device_vendor: Annotated[
        MonitorVendor | None,
        Query(
            description="Monitor vendor override. Auto-detected from MSH-3 if absent."
        ),
    ] = None,
    device_model: Annotated[
        str | None,
        Query(description="Monitor model string (e.g., 'IntelliVue MX800')."),
    ] = None,
) -> JSONResponse:
    """
    Full HL7 → DSP → NEWS2 → FHIR pipeline.

    IEC 62304 §5.8: This endpoint is the integration seam between
    the HL7 wire protocol and the domain pipeline.
    ISO 14971 HAZARD-API-001: SpO2 scale selection is the caller's
    responsibility — this endpoint cannot infer COPD status from HL7 alone.
    FDA CDS: Response carries X-CDS-Advisory-Only: true header.
    """
    # ── Read raw body ──────────────────────────────────────────────────────────
    raw_bytes = await request.body()
    if not raw_bytes or not raw_bytes.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Request body is empty. "
                "Expected a raw HL7 v2.x ORU^R01 message (text/plain)."
            ),
        )

    raw_hl7 = raw_bytes.decode("utf-8", errors="replace")

    log = _log.bind(
        spo2_scale=spo2_scale.value,
        device_vendor=device_vendor.value if device_vendor else "auto",
    )
    log.info("api.ingest.start")

    # ── Stage 1: HL7 Parsing (may raise ValueError for invalid HL7) ───────────
    # ValueError is caught by global handler in main.py → HTTP 422
    device_context_hint: DeviceContext | None = None
    if device_vendor is not None or device_model is not None or device_id is not None:
        device_context_hint = DeviceContext(
            device_id=device_id or "DEVICE-OVERRIDE",
            vendor=device_vendor or MonitorVendor.GENERIC,
            model=device_model or "Unknown",
        )

    parse_result = _adapter.parse(raw_hl7, device_context=device_context_hint)

    # ── Stage 2: Build PatientContext & DeviceContext ──────────────────────────
    patient_context = PatientContext(
        patient_id=parse_result.patient_id,
        spo2_scale=spo2_scale,
        encounter_id=encounter_id,
    )

    # Build final DeviceContext from parsed result or provided override
    device_context: DeviceContext | None = device_context_hint
    if (
        device_context is None
        and parse_result.detected_vendor is not MonitorVendor.GENERIC
    ):
        device_context = DeviceContext(
            device_id=device_id or f"DEVICE-{parse_result.detected_vendor.value}",
            vendor=parse_result.detected_vendor,
            model=device_model or "ICU Monitor",
            hl7_version=HL7Version.V2_5_1,
        )

    # ── Stage 3: Domain Pipeline (DSP + NEWS2) ─────────────────────────────────
    analysis_result = _orchestrator.analyse(
        samples=list(parse_result.samples),
        context=patient_context,
    )

    # ── Stage 4: FHIR Bundle Assembly ─────────────────────────────────────────
    bundle = _assembler.assemble(
        result=analysis_result,
        patient_context=patient_context,
        device_context=device_context,
        encounter_id=encounter_id,
    )

    log.info(
        "api.ingest.complete",
        patient_id=parse_result.patient_id,
        sample_count=len(parse_result.samples),
        skipped_obx=parse_result.skipped_obx_count,
        news2_total=analysis_result.news2_score.total
        if analysis_result.news2_score
        else None,
        duration_ms=round(analysis_result.processing_duration_ms, 2),
    )

    # Phase 5 Section A: live dashboard delta push. getattr-guarded rather
    # than a hard app.state access — the channel is always set by main.py's
    # lifespan in production, but some test fixtures build a bare app.
    live_channel = getattr(request.app.state, "live_dashboard_channel", None)
    if live_channel is not None:
        await live_channel.broadcast(bundle, source="http-ingest")

    return JSONResponse(
        content=bundle,
        media_type="application/fhir+json",
        headers=_pipeline_headers(analysis_result),
    )


def _pipeline_headers(result: object) -> dict[str, str]:
    """
    Build response headers exposing pipeline metadata.

    These headers allow monitoring systems (Prometheus, Grafana) to track
    NEWS2 risk levels and processing latency without parsing FHIR Bundles.
    """
    from domain.services.vitals_orchestrator import (
        VitalsAnalysisResult,  # noqa: PLC0415
    )

    if not isinstance(result, VitalsAnalysisResult):
        return {"X-CDS-Advisory-Only": "true"}

    headers: dict[str, str] = {
        "X-CDS-Advisory-Only": "true",
        "X-Pipeline-Duration-Ms": str(round(result.processing_duration_ms, 2)),
        "X-Warning-Count": str(len(result.pipeline_warnings)),
    }
    if result.news2_score is not None:
        headers["X-NEWS2-Total"] = str(result.news2_score.total)
        headers["X-NEWS2-Risk-Level"] = result.news2_score.risk_level.value

    return headers
