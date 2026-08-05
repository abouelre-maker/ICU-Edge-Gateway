"""
POST /api/v1/vitals — JSON-Normalized Vital Signs Ingestion Endpoint.

Accepts a structured JSON payload of VitalSignSamples (no HL7 parsing required).
Used when the upstream system can produce normalized vital sign data directly.

IEC 62304 §5.3: Input validation occurs at the Pydantic layer before domain
code runs — domain entities receive only type-checked, range-validated data.
ISO 14971 HAZARD-TIME-001: All timestamps must be timezone-aware.
The Pydantic model enforces this at the API boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from domain.entities.device_context import DeviceContext, MonitorVendor
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.vitals_orchestrator import VitalsOrchestrator
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from infrastructure.fhir.bundle_assembler import BundleAssembler
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_log: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["Normalized Vitals"])

# Shared stateless service instances
_orchestrator = VitalsOrchestrator()
_assembler = BundleAssembler()


# ── Request Models (Pydantic v2) ───────────────────────────────────────────────


class VitalSignPayload(BaseModel):
    """
    Single vital sign observation from a structured JSON source.

    IEC 62304 REQ-API-010: Pydantic validates types and formats before domain
    code executes — the domain layer receives only well-formed inputs.
    """

    model_config = ConfigDict(use_enum_values=False)

    vital_sign_type: VitalSignType
    value: float = Field(
        ...,
        description=(
            "Numeric measurement value. "
            "For CONSCIOUSNESS type, set avpu_level instead — value is ignored."
        ),
    )
    unit: VitalSignUnit
    timestamp: datetime = Field(
        ...,
        description=(
            "ISO 8601 timestamp WITH timezone (e.g., '2024-01-15T10:00:00Z'). "
            "Naive timestamps are rejected. ISO 14971 HAZARD-TIME-001."
        ),
    )
    avpu_level: AVPULevel | None = Field(
        None,
        description=(
            "Required when vital_sign_type is CONSCIOUSNESS. "
            "ISO 14971 HAZARD-CON-001: missing AVPU causes consciousness "
            "underestimation."
        ),
    )
    waveform: list[float] | None = Field(
        None,
        description="Optional raw waveform samples for DSP processing.",
    )
    sampling_rate_hz: float | None = Field(
        None,
        description="Required when waveform is provided. Must be > 0.",
    )
    device_id: str | None = Field(
        None,
        description="FHIR Device logical ID for this sample's source device.",
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_timezone_aware(cls, v: Any) -> datetime:
        """
        Reject naive datetimes at the API boundary.

        ISO 14971 HAZARD-TIME-001: Naive timestamps corrupt the audit trail
        when compared across timezone boundaries in multi-site ICU deployments.
        """
        if isinstance(v, str):
            # Handle 'Z' suffix which Python's fromisoformat doesn't accept before 3.11
            normalised = v.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(normalised)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid timestamp format: {v!r}. "
                    "Expected ISO 8601 with timezone (e.g., '2024-01-15T10:00:00Z')."
                ) from exc
            if dt.tzinfo is None:
                raise ValueError(
                    f"Timestamp {v!r} is missing timezone information. "
                    "ISO 14971 HAZARD-TIME-001: naive timestamps are rejected."
                )
            return dt
        if isinstance(v, datetime):
            if v.tzinfo is None:
                raise ValueError(
                    "datetime object must be timezone-aware. "
                    "Use datetime.now(tz=timezone.utc) or attach tzinfo."
                )
            return v
        raise ValueError(f"Unsupported timestamp type: {type(v).__name__}")

    @model_validator(mode="after")
    def validate_consciousness_has_avpu(self) -> VitalSignPayload:
        """
        ISO 14971 HAZARD-CON-001: CONSCIOUSNESS samples must carry avpu_level.
        Enforced at the API boundary — before domain VitalSignSample is constructed.
        """
        if (
            self.vital_sign_type is VitalSignType.CONSCIOUSNESS
            and self.avpu_level is None
        ):
            raise ValueError(
                "avpu_level is required when vital_sign_type is CONSCIOUSNESS. "
                "ISO 14971 HAZARD-CON-001: missing AVPU causes consciousness "
                "underestimation in NEWS2 scoring."
            )
        return self


class VitalsIngestionRequest(BaseModel):
    """
    Full vitals payload for POST /api/v1/vitals.

    IEC 62304 §5.2: Top-level request entity — contains all clinical context
    required to execute the full domain pipeline.
    """

    model_config = ConfigDict(use_enum_values=False)

    patient_id: str = Field(
        ...,
        min_length=1,
        description="FHIR Patient logical ID. Required for all FHIR resource references.",
    )
    samples: list[VitalSignPayload] = Field(
        ...,
        min_length=1,
        description="One or more vital sign observations. At least one is required.",
    )
    spo2_scale: SpO2Scale = Field(
        SpO2Scale.SCALE_1,
        description=(
            "SpO2 scoring scale. "
            "SCALE_1 = standard (default for all patients). "
            "SCALE_2 = confirmed hypercapnic respiratory failure ONLY. "
            "ISO 14971 HAZARD-SPO2-001."
        ),
    )
    encounter_id: str | None = Field(
        None,
        description="FHIR Encounter logical ID.",
    )
    device_id: str | None = Field(
        None,
        description="FHIR Device logical ID.",
    )
    device_vendor: MonitorVendor | None = Field(
        None,
        description="Source monitor vendor (for FHIR Device resource).",
    )
    device_model: str | None = Field(
        None,
        description="Source monitor model string.",
    )
    device_location: str | None = Field(
        None,
        description="Physical location (e.g., 'ICU-BED-07-A').",
    )


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.post(
    "/vitals",
    status_code=status.HTTP_200_OK,
    summary="Ingest JSON-Normalized Vital Signs",
    description=(
        "Accepts a structured JSON payload of vital sign observations. "
        "Applies DSP artifact rejection, calculates NEWS2 score, and returns "
        "a FHIR R4 Bundle.\n\n"
        "Use this endpoint when the upstream system can produce normalized "
        "data directly (no HL7 parsing required). "
        "For raw HL7 v2.x messages, use `POST /api/v1/ingest` instead."
    ),
    responses={
        200: {"description": "FHIR R4 Bundle (application/fhir+json)"},
        422: {"description": "Validation error — missing fields or invalid values."},
        500: {"description": "Unexpected internal error."},
    },
)
async def ingest_vitals(
    payload: VitalsIngestionRequest,
) -> JSONResponse:
    """
    Full DSP → NEWS2 → FHIR pipeline from structured JSON input.

    IEC 62304 §5.8: Domain pipeline is called after Pydantic validation
    succeeds — domain layer receives only type-safe, pre-validated inputs.
    ISO 14971 HAZARD-API-001: SpO2 scale is an explicit caller decision.
    FDA CDS: Response is advisory — X-CDS-Advisory-Only header signals this.
    """
    log = _log.bind(
        patient_id=payload.patient_id,
        sample_count=len(payload.samples),
        spo2_scale=payload.spo2_scale.value,
    )
    log.info("api.vitals.start")

    # ── Convert Pydantic payloads → domain VitalSignSamples ──────────────────
    samples: list[VitalSignSample] = []
    for item in payload.samples:
        try:
            sample = VitalSignSample(
                vital_sign_type=item.vital_sign_type,
                value=item.value,
                unit=item.unit,
                timestamp=item.timestamp,
                avpu_level=item.avpu_level,
                waveform=tuple(item.waveform) if item.waveform else None,
                sampling_rate_hz=item.sampling_rate_hz,
                device_id=item.device_id,
            )
            samples.append(sample)
        except ValueError as exc:
            # Re-raise — caught by global handler → HTTP 422
            raise ValueError(
                f"Invalid VitalSignSample for type "
                f"{item.vital_sign_type.name}: {exc}"
            ) from exc

    # ── Build Context Objects ─────────────────────────────────────────────────
    patient_context = PatientContext(
        patient_id=payload.patient_id,
        spo2_scale=payload.spo2_scale,
        encounter_id=payload.encounter_id,
    )

    device_context: DeviceContext | None = None
    if any([payload.device_id, payload.device_vendor, payload.device_model]):
        device_context = DeviceContext(
            device_id=payload.device_id or "DEVICE-API",
            vendor=payload.device_vendor or MonitorVendor.GENERIC,
            model=payload.device_model or "Unknown",
            location=payload.device_location,
        )

    # ── Domain Pipeline ───────────────────────────────────────────────────────
    analysis_result = _orchestrator.analyse(
        samples=samples,
        context=patient_context,
    )

    # ── FHIR Bundle Assembly ──────────────────────────────────────────────────
    bundle = _assembler.assemble(
        result=analysis_result,
        patient_context=patient_context,
        device_context=device_context,
        encounter_id=payload.encounter_id,
    )

    log.info(
        "api.vitals.complete",
        news2_total=(
            analysis_result.news2_score.total if analysis_result.news2_score else None
        ),
        duration_ms=round(analysis_result.processing_duration_ms, 2),
    )

    # Build response headers
    headers: dict[str, str] = {
        "X-CDS-Advisory-Only": "true",
        "X-Pipeline-Duration-Ms": str(round(analysis_result.processing_duration_ms, 2)),
        "X-Warning-Count": str(len(analysis_result.pipeline_warnings)),
    }
    if analysis_result.news2_score is not None:
        headers["X-NEWS2-Total"] = str(analysis_result.news2_score.total)
        headers["X-NEWS2-Risk-Level"] = analysis_result.news2_score.risk_level.value

    return JSONResponse(
        content=bundle,
        media_type="application/fhir+json",
        headers=headers,
    )
