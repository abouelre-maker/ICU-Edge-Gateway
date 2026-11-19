"""
FHIR R4 Bundle Assembler — ICU Edge Gateway Output.

Assembles all per-sample FHIR Observations and the NEWS2 Score Observation
into a single FHIR R4 Bundle of type 'collection'.

IEC 62304 §5.3: Single-responsibility — assembles, does not build.
ISO 14971 HAZARD-FHIR-003: Bundle.timestamp must be present for downstream
CDSS to correlate observations with the clinical encounter time.
FDA CDS: Bundle-level note provides the advisory-only disclaimer for all consumers.

FHIR R4 Reference: http://hl7.org/fhir/R4/bundle.html
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Final

from domain.entities.device_context import DeviceContext
from domain.entities.patient_context import PatientContext
from domain.services.vitals_orchestrator import VitalsAnalysisResult

from infrastructure.fhir.news2_builder import NEWS2ObservationBuilder
from infrastructure.fhir.observation_builder import (
    ObservationBuilder,
    _format_fhir_datetime,
)

_BUNDLE_PROFILE: Final = "http://hl7.org/fhir/StructureDefinition/Bundle"
_IEC62304_EXT: Final = "https://samd.icu-edge/fhir/extensions/iec62304-software-version"
_SW_VERSION: Final = "1.0.0"
# Local code system for ScoreOutcome reason codes. Not a published standard
# terminology — TODO-VERIFY: replace the host with the owner's real domain.
_REASON_CODE_SYS: Final = "https://samd.icu-edge/fhir/CodeSystem/score-reason"


class BundleAssembler:
    """
    Orchestrates FHIR R4 Bundle construction from a VitalsAnalysisResult.

    One Bundle per HL7 message / API call. Contains:
    - 0..N Observation entries: one per valid processed vital sign
    - 0..1 Device entry: source ICU monitor metadata
    - 0..1 NEWS2 Observation entry: total score + 7 components (if score present)

    All observations reference the same Patient/{patient_id} subject.
    All observations optionally reference the same Device/{device_id}.

    IEC 62304 §5.3: The BundleAssembler coordinates ObservationBuilder and
    NEWS2ObservationBuilder — it contains no observation logic itself.
    """

    def __init__(
        self,
        obs_builder: ObservationBuilder | None = None,
        news2_builder: NEWS2ObservationBuilder | None = None,
    ) -> None:
        self._obs_builder = obs_builder or ObservationBuilder()
        self._news2_builder = news2_builder or NEWS2ObservationBuilder()

    def assemble(
        self,
        result: VitalsAnalysisResult,
        patient_context: PatientContext,
        device_context: DeviceContext | None = None,
        encounter_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Assemble a complete FHIR R4 Bundle from a VitalsAnalysisResult.

        Args:
            result:           Domain pipeline output from VitalsOrchestrator.
            patient_context:  Patient metadata (id, SpO2 scale).
            device_context:   Optional ICU monitor metadata for Device resource.
            encounter_id:     Optional FHIR Encounter reference.

        Returns:
            FHIR R4 Bundle dict (type: 'collection').
            Always returned — empty entries list if no valid vitals present.

        ISO 14971 HAZARD-FHIR-003: Bundle.timestamp is always set to UTC now
        even if no observations were produced, to preserve the audit record.
        """
        patient_id = patient_context.patient_id
        device_id = device_context.device_id if device_context else None
        bundle_ts = _format_fhir_datetime(datetime.now(tz=timezone.utc))

        entries: list[dict[str, Any]] = []

        # ── Device Resource Entry (if device context provided) ─────────────────
        if device_context:
            device_entry = self._build_device_entry(device_context)
            entries.append(device_entry)

        # ── Vital Sign Observation Entries ─────────────────────────────────────
        for processed in result.processed_vitals:
            try:
                obs_dict = self._obs_builder.build(
                    processed=processed,
                    patient_id=patient_id,
                    device_id=device_id,
                    encounter_id=encounter_id,
                )
                entries.append(
                    {
                        "fullUrl": f"urn:uuid:{obs_dict['id']}",
                        "resource": obs_dict,
                    }
                )
            except Exception as exc:
                # Individual observation failure must not abort bundle assembly.
                # IEC 62304 REQ-FHIR-001: Log and continue.
                entries.append(
                    self._build_error_entry(
                        vital_type=processed.original.vital_sign_type.value,
                        error=str(exc),
                    )
                )

        # ── NEWS2 Score Observation Entry ──────────────────────────────────────
        if result.news2_score is not None:
            try:
                news2_dict = self._news2_builder.build(
                    score=result.news2_score,
                    patient_id=patient_id,
                    device_id=device_id,
                    encounter_id=encounter_id,
                )
                if "PRELIMINARY_RESULT" in result.assessment.reason_codes:
                    news2_dict["status"] = "preliminary"  # N-02
                # A2: effective time is when the inputs were observed, not
                # when the score was calculated; calculation time → issued.
                news2_dict["issued"] = news2_dict["effectiveDateTime"]
                if result.assessment.observation_time is not None:
                    news2_dict["effectiveDateTime"] = _format_fhir_datetime(
                        result.assessment.observation_time
                    )
                entries.append(
                    {
                        "fullUrl": f"urn:uuid:{news2_dict['id']}",
                        "resource": news2_dict,
                    }
                )
            except Exception as exc:
                entries.append(
                    self._build_error_entry(
                        vital_type="NEWS2Score",
                        error=str(exc),
                    )
                )

        # ── Scoring outcome (A6): valid R4 OperationOutcome entry ────────────
        if result.assessment.findings:
            entries.append(self._build_outcome_entry(result))

        # ── Bundle Assembly ────────────────────────────────────────────────────
        bundle: dict[str, Any] = {
            "resourceType": "Bundle",
            "id": str(uuid.uuid4()),
            "meta": {
                "profile": [_BUNDLE_PROFILE],
                "lastUpdated": bundle_ts,
            },
            "type": "collection",
            "timestamp": bundle_ts,
            "total": len(entries),
            "entry": entries,
            "extension": [
                {
                    "url": _IEC62304_EXT,
                    "valueString": _SW_VERSION,
                }
            ],
        }

        # Pipeline warnings as Bundle.note (audit trail)
        if result.pipeline_warnings:
            bundle["note"] = [{"text": warning} for warning in result.pipeline_warnings]

        return bundle

    # ── Private Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _build_device_entry(ctx: DeviceContext) -> dict[str, Any]:
        """
        Build a minimal FHIR R4 Device resource entry from DeviceContext.
        FHIR R4: Device.manufacturer and Device.deviceName are optional.
        """
        device_resource: dict[str, Any] = {
            "resourceType": "Device",
            "id": ctx.device_id,
            "status": "active",
            "manufacturer": ctx.vendor.value,
            "deviceName": [
                {
                    "name": ctx.model,
                    "type": "model-name",
                }
            ],
        }
        if ctx.firmware_version:
            device_resource["version"] = [{"value": ctx.firmware_version}]
        if ctx.location:
            device_resource["location"] = {"display": ctx.location}

        return {
            "fullUrl": f"urn:uuid:{ctx.device_id}",
            "resource": device_resource,
        }

    @staticmethod
    def _build_outcome_entry(result: VitalsAnalysisResult) -> dict[str, Any]:
        """
        One OperationOutcome carrying the machine-readable scoring outcome and
        every reason code (docs/assessment/PHASE1_DESIGN.md §2). Critical values
        keep their measured value in issue.diagnostics (A6).
        """
        # Local import keeps the module import graph unchanged at load time.
        from domain.entities.score_outcome import (  # noqa: PLC0415
            INCOMPLETE_CODES,
            ReasonCode,
        )

        assessment = result.assessment
        issues: list[dict[str, Any]] = []
        for f in assessment.findings:
            if f.code is ReasonCode.CRITICAL_VALUE_REVIEW_REQUIRED:
                severity, issue_code = "warning", "business-rule"
            elif f.code in INCOMPLETE_CODES:
                severity, issue_code = "warning", "incomplete"
            else:
                severity, issue_code = "information", "informational"
            diag = f.detail
            if f.parameter is not None:
                diag = f"{f.parameter.name}: {diag}"
            if f.measured_value is not None:
                diag = f"{diag} Measured value: {f.measured_value:g}."
            issues.append(
                {
                    "severity": severity,
                    "code": issue_code,
                    "details": {
                        "coding": [{"system": _REASON_CODE_SYS, "code": f.code.value}],
                        "text": f"Scoring outcome: {assessment.outcome.value}",
                    },
                    "diagnostics": diag,
                }
            )
        return {
            "fullUrl": f"urn:uuid:{uuid.uuid4()}",
            "resource": {"resourceType": "OperationOutcome", "issue": issues},
        }

    @staticmethod
    def _build_error_entry(vital_type: str, error: str) -> dict[str, Any]:
        """
        Build a Bundle entry representing a failed observation build.

        IEC 62304 REQ-FHIR-001: Errors in individual observations must not
        silently disappear — they are recorded as OperationOutcome entries.
        """
        return {
            "fullUrl": f"urn:uuid:{uuid.uuid4()}",
            "resource": {
                "resourceType": "OperationOutcome",
                "issue": [
                    {
                        "severity": "warning",
                        "code": "processing",
                        "details": {
                            "text": (
                                f"Failed to build FHIR Observation for "
                                f"{vital_type}: {error}"
                            )
                        },
                    }
                ],
            },
        }
