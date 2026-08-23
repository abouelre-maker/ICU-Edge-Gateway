# SRS-001 — Software Requirements Specification

## ICU Edge-to-FHIR Interoperability Gateway v1.0.0

> ## ⚠ STATUS BANNER — READ BEFORE USING THIS DOCUMENT FOR ANY PURPOSE
>
> **No credentialed Clinical Safety Officer is appointed.** The only sign-off authority that
> exists is an **interim, non-clinically-credentialed engineering appointment**
> ([docs/CSO_Role_Appointment_Brief.md](CSO_Role_Appointment_Brief.md) §5 — Housam Abouelreish,
> project owner, effective 2026-08-10) — the appointee explicitly does **not** meet that same
> document's own §2 credential bar (active clinical license, critical/acute care experience).
> That interim authority's scope is limited to engineering-identified hazards
> (HAZARD-DSP-007, HAZARD-STREAM-012 only) and does **not** extend to, and does **not**
> ratify, any requirement or hazard link in this document.
>
> **HAZARD-DSP-005 and HAZARD-DSP-006 remain outside ANY sign-off scope** — interim or
> otherwise. Both require a credentialed Clinical Safety Officer's formal ratification per
> [QMS-002_CSO_Ratification_Protocol.md](QMS-002_CSO_Ratification_Protocol.md), which has not
> occurred.
>
> **FDA / Health Canada regulatory classification is an engineering assumption, not a
> regulatory determination.** Per Finding 3 of
> [docs/ICU_Edge_Gateway_Phase5_Technical_Package.md](ICU_Edge_Gateway_Phase5_Technical_Package.md):
> every "FDA CDS Non-Device Exemption (21 CFR §880.3780)" / "Health Canada SaMD Class II"
> citation in this document or the source code it describes is an engineering design-intent
> marker, not a completed regulatory submission.
>
> This banner is not boilerplate. Every section below inherits these three facts.

---

**Document ID:** SRS-001
**Status:** DRAFT — engineering-compiled working document, not a certified SRS.
**Prepared:** 2026-08-10, Phase 5-Stream Section E.
**Seeded from:** every `REQ-[A-Z0-9-]+` identifier found in `src/` at compilation time — **17
unique requirement IDs**, listed exhaustively in §3. Each requirement statement below is
derived directly from the docstring/comment at its cited source location, not invented —
where a docstring's wording is a design note rather than a crisp "shall" statement, this
document restates it as one and flags that restatement explicitly, rather than presenting an
engineering comment as if it were already a formal requirement.

---

## 1. Introduction

### 1.1 Purpose

This SRS specifies the functional requirements the ICU Edge-to-FHIR Interoperability Gateway's
existing implementation already encodes as `REQ-*`-tagged docstrings/comments in source. It is
a **reverse-derived** SRS — requirements were extracted from shipped code and tests, not
written first and implemented second. This is stated plainly because it affects how this
document should be read: it documents what the system *does* (and cites where), not an
independently-authored specification the system was built to satisfy.

### 1.2 Scope

Covers the HL7 v2.x/JSON ingestion → DSP artifact rejection → NEWS2 scoring → FHIR R4 output
pipeline (`src/domain/`, `src/infrastructure/adapters/`, `src/infrastructure/fhir/`,
`src/api/`) and the cross-cutting API/error-handling layer (`src/main.py`).

**Not covered — a finding of this compilation, not a scoping choice:** the Phase 5-Stream
layer (`src/infrastructure/streaming/` — MQTT, WebSocket live dashboard, FHIR Subscriptions;
`src/infrastructure/provisioning/` — mTLS device enrollment/reattestation) contains **zero**
`REQ-*` tags anywhere in source, confirmed by the same grep this document was seeded from. That
layer is extensively `HAZARD-STREAM-*`-tagged (risk-managed) but has no corresponding
requirements-traceability tagging convention applied to it yet. See §6.

### 1.3 Definitions, Acronyms

| Term | Meaning |
|---|---|
| NEWS2 | National Early Warning Score 2 (RCP 2017) |
| OBX | HL7 v2.x Observation segment |
| DSP | Digital Signal Processing (notch/bandpass/Hampel filters) |
| SaMD | Software as a Medical Device |

### 1.4 References

[QMS-001_DHF_Structure.md](QMS-001_DHF_Structure.md) · [RMF-001_Risk_Management_File.md](RMF-001_Risk_Management_File.md)
· [ICU_Edge_Gateway_Phase5_Technical_Package.md](ICU_Edge_Gateway_Phase5_Technical_Package.md)
· RCP NEWS2 (2017), ISBN 978-1-86016-693-6

## 2. Overall Description

The system is a single-tenant-per-deployment gateway: an ICU bedside monitor (or a structured
JSON caller) sends vital sign data in; the gateway runs it through DSP artifact rejection,
computes a NEWS2 score, and emits FHIR R4 `Observation`/`Bundle` resources for a downstream
EHR/CDSS to consume. Output is advisory-only (FDA CDS framing — see banner). Two ingestion
paths exist (`POST /api/v1/ingest` for raw HL7 v2.x, `POST /api/v1/vitals` for pre-normalized
JSON), converging on one shared domain pipeline (`VitalsOrchestrator`).

## 3. Specific Requirements

One entry per `REQ-*` ID found in source, grouped by subsystem in the order a request flows
through the system. **Verification** cites the test file(s) that exercise the requirement,
checked to exist at compilation time — not asserted from memory.

### 3.1 Device / Vendor Context

#### REQ-DEV-001
- **Source:** `src/domain/entities/device_context.py:51,67`
- **Statement:** `DeviceContext.device_id` SHALL be a non-empty string, and the system SHALL
  use `DeviceContext` to select the vendor-specific HL7 parsing strategy (GoF Strategy
  pattern) and to populate `Device.manufacturer`/`Device.model` in the emitted FHIR Bundle.
- **Rationale / Hazard link:** Prerequisite for HAZARD-PROTO-001 (vendor dialect
  misidentification) mitigation — the adapter cannot select the right vendor code table
  without a valid device context.
- **Verification:** `tests/integration/test_hl7v2_adapter.py` (vendor-specific parsing cases)

### 3.2 Vital Sign Domain Entity

#### REQ-VITAL-001
- **Source:** `src/domain/entities/vital_sign.py:20`
- **Statement:** Each `VitalSignType` enum value SHALL map to exactly one NEWS2 scoring
  component (RCP 2017).
- **Rationale / Hazard link:** HAZARD-NEWS2-001 — an ambiguous or missing mapping would corrupt
  scoring at the type level, before any value is even read.
- **Verification:** `tests/regulatory/test_news2_safety.py`, `tests/unit/test_news2_calculator.py`

#### REQ-VITAL-002
- **Source:** `src/domain/entities/vital_sign.py:71`
- **Statement:** `VitalSignSample` SHALL be the sole, immutable data unit flowing through the
  pipeline from adapter to DSP stage.
- **Rationale / Hazard link:** Immutability is a stated risk control against accidental
  downstream mutation (module docstring, ISO 14971 general note).
- **Verification:** Structural — `@dataclass(frozen=True)`; exercised implicitly by every
  pipeline test (`tests/integration/`, `tests/unit/test_signal_processor_edge_cases.py`)

#### REQ-VITAL-003
- **Source:** `src/domain/entities/vital_sign.py:93,104`
- **Statement:** A `VitalSignSample` carrying `waveform` data SHALL also carry a positive
  `sampling_rate_hz` — construction SHALL raise `ValueError` otherwise (an unsampled waveform
  cannot be filtered).
- **Rationale / Hazard link:** HAZARD-PROTO-002 (sampling-rate ambiguity) — this is the
  entity-level backstop that makes a missing rate a construction-time error, not a later
  silent failure.
- **Verification:** `tests/unit/test_signal_processor_edge_cases.py::TestSamplingRateExtremesOrchestrator::test_negative_sampling_rate_rejected_at_entity_construction`

### 3.3 Patient Context

#### REQ-CTX-001
- **Source:** `src/domain/entities/patient_context.py:38`
- **Statement:** A `PatientContext` (carrying, at minimum, the clinician-assigned SpO2 scale)
  SHALL be provided before `NEWS2Calculator.calculate()` is invoked.
- **Rationale / Hazard link:** HAZARD-SPO2-001 — SpO2 scale is a clinician judgment call
  (Scale 1 vs. Scale 2/COPD) the software must never infer; this requirement makes the
  dependency explicit at the API boundary rather than defaulting silently deep in the call
  stack.
- **Verification:** `tests/unit/test_news2_calculator.py::TestSpO2Scale1Scoring` /
  `TestSpO2Scale2Scoring`

### 3.4 HL7 v2.x Adapter

#### REQ-HL7-001
- **Source:** `src/infrastructure/adapters/hl7v2_adapter.py:272`
- **Statement:** The adapter SHALL raise `ValueError` if the supplied input is not a
  syntactically valid HL7 v2.x ORU^R01 message — it SHALL NOT attempt partial/best-effort
  parsing of a structurally invalid message.
- **Rationale / Hazard link:** Fail-fast boundary distinct from HAZARD-WAVE-001's
  per-segment fail-whole-array rule — this one is message-level, not segment-level.
- **Verification:** `tests/integration/test_hl7v2_adapter.py::test_invalid_hl7_raises_value_error`

#### REQ-HL7-002
- **Source:** `src/infrastructure/adapters/hl7v2_adapter.py:404,412`
- **Statement:** The adapter SHALL accept only OBX segments with result status Final (`F`) or
  Preliminary (`P`) — Corrected (`C`) and entered-in-error (`W`) status segments SHALL be
  excluded from scoring input.
- **Rationale / Hazard link:** A corrected/retracted value silently scored would be a
  HAZARD-BOUNDS-001-adjacent data-provenance defect.
- **Verification:** `tests/integration/test_hl7v2_adapter.py::test_x_status_obx_is_skipped`

#### REQ-HL7-003
- **Source:** `src/infrastructure/adapters/hl7v2_adapter.py:796`
- **Statement:** A field-access failure against the underlying HL7 parser (`hl7apy`) SHALL
  never abort message parsing — it SHALL be absorbed at the single point of contact
  (`_safe_field`) and treated as an empty value.
- **Rationale / Hazard link:** Isolates one malformed field from taking down the whole
  message, the same fail-isolated philosophy as HAZARD-PROTO-001's per-OBX skip-and-warn.
- **Verification:** `tests/integration/test_hl7v2_vendor_edge_cases.py` (malformed/truncated
  MSH-3 cases exercise this path indirectly)

### 3.5 DSP Pipeline

#### REQ-PROC-001
- **Source:** `src/domain/services/signal_processor.py:53`
- **Statement:** `ProcessedVitalSign` SHALL be the sole, immutable data unit flowing from the
  DSP stage into `NEWS2Calculator` — carrying `cleaned_value`,
  `is_within_physiological_bounds`, and a full `pipeline_notes` audit trail.
- **Rationale / Hazard link:** HAZARD-ARCH-001 (pipeline stage ordering) — this is the typed
  seam that makes "DSP before NEWS2" structurally enforceable, not just a call-order
  convention.
- **Verification:** `tests/regulatory/test_hazard_arch_001_pipeline_order.py`

### 3.6 NEWS2 Scoring

#### REQ-NEWS2-001
- **Source:** `src/domain/entities/news2_score.py:50`; `src/domain/services/news2_calculator.py:82`
- **Statement:** All seven RCP NEWS2 2017 scoring parameters (respiratory rate, SpO2,
  supplemental O2, systolic BP, heart rate, consciousness, temperature) SHALL be independently
  evaluated and their component scores independently stored on `NEWS2Score`.
- **Rationale / Hazard link:** HAZARD-NEWS2-001 — a merged/derived-only score would hide which
  parameter drove an escalation.
- **Verification:** `tests/regulatory/test_news2_safety.py::TestHazardNEWS2001ScoringAccuracy`

#### REQ-NEWS2-002
- **Source:** `src/domain/entities/news2_score.py:80,101`
- **Statement:** Each `NEWS2Score` component score SHALL be validated within RCP 2017's
  defined bounds at construction time — component score integrity SHALL be enforced
  structurally (immutable dataclass + `__post_init__` guard), not by caller discipline.
- **Rationale / Hazard link:** HAZARD-NEWS2-002 — prevents a scoring-function bug from ever
  producing an out-of-table score that reaches `risk_level` derivation.
- **Verification:** `tests/regulatory/test_news2_safety.py::TestHazardNEWS2002RiskLevel`

#### REQ-NEWS2-003
- **Source:** `src/domain/services/news2_calculator.py:40,135,153`
- **Statement:** `NEWS2Calculator.calculate()` SHALL raise `NEWS2InsufficientDataError` (fail
  fast) rather than compute a partial score when one or more of the five mandatory parameters
  (RR, SpO2, SBP, HR, Temp) is absent or flagged out-of-bounds — it SHALL NOT silently
  substitute a default or omit the missing component.
- **Rationale / Hazard link:** HAZARD-NEWS2-003 / HAZARD-DSP-007 (the SpO2/NaN case is the
  concrete regression this requirement was proven against — see
  `tests/regulatory/test_news2_safety.py::TestHazardDsp007NanSpo2ExcludedNotScoredNormal`).
- **Verification:** `tests/unit/test_news2_calculator.py::TestInsufficientDataHandling`;
  `tests/integration/test_api_vitals.py::TestVitalsHazardDsp007NanExcludedNotOpaqueFailure`
  (confirms the *shape* of that failure — good data still returned alongside the explicit
  exclusion, not an opaque total failure)

### 3.7 FHIR Output

#### REQ-FHIR-001
- **Source:** `src/infrastructure/fhir/bundle_assembler.py:111,203`
- **Statement:** A single Observation build failure SHALL NOT abort assembly of the containing
  Bundle — it SHALL be logged and represented as an `OperationOutcome` entry in the Bundle in
  place of the failed Observation.
- **Rationale / Hazard link:** Availability control — one bad Observation must not hide every
  other good one in the same Bundle (the same principle later reinforced, for a different
  failure mode, by HAZARD-DSP-007's response-shape confirmation — see REQ-NEWS2-003 above).
- **Verification:** `tests/integration/test_fhir_bundle.py`

### 3.8 API / Cross-Cutting

#### REQ-API-001
- **Source:** `src/main.py:225`
- **Statement:** A domain-layer `ValueError` reaching the API boundary SHALL be translated to
  HTTP 422 with a structured `{"error": "validation_error", "detail": ...}` body — the
  original stack trace SHALL NOT reach the API consumer.
- **Rationale / Hazard link:** Information-disclosure control (implementation details/internal
  paths must not leak in error responses to an external EHR integration).
- **Verification:** `tests/integration/test_api_ingest.py::TestIngestErrorHandling`

#### REQ-API-002
- **Source:** `src/main.py:248`
- **Statement:** Any unhandled exception (not caught by a more specific handler) SHALL be
  logged server-side at ERROR level and returned to the caller as a generic HTTP 500 — with no
  exception type, message, or trace exposed in the response body.
- **Rationale / Hazard link:** Same information-disclosure control as REQ-API-001, for the
  catch-all case.
- **Verification:** Exercised indirectly wherever a 500 path is tested; no dedicated test file
  found for this handler specifically at compilation time — **flagged as a gap**, not assumed
  covered (see §6).

#### REQ-API-003
- **Source:** `src/api/v1/health.py:4,63`
- **Statement:** `GET /health` SHALL report the status of all four pipeline stages (HL7
  adapter, DSP filter, NEWS2 calculator, FHIR builder) individually, returning HTTP 200 only
  when all are operational, so clinical IT tooling (Kubernetes probes, edge deployment
  runbooks) can identify which specific stage degraded rather than only "the service is down."
- **Rationale / Hazard link:** Operational/availability requirement, not a clinical-scoring
  hazard control.
- **Verification:** `tests/integration/test_api_health.py::TestHealthEndpoint` (13 tests,
  confirmed present — component-status reporting, expected-components list, uptime monotonicity)

#### REQ-API-010
- **Source:** `src/api/v1/vitals.py:49`
- **Statement:** The `POST /api/v1/vitals` JSON payload SHALL be fully type/format-validated
  by the Pydantic request model **before** any domain-layer code executes — the domain layer
  SHALL receive only well-formed inputs from this path.
- **Rationale / Hazard link:** Directly relevant to, but does **not** fully close,
  HAZARD-DSP-007's scalar path: Pydantic's `float` type accepts NaN/Infinity by default
  (confirmed empirically this Phase — see RMF-001, HAZARD-DSP-007) — "type/format-validated"
  is true (the field IS a float) but was not, at the time HAZARD-DSP-007 was found, sufficient
  to exclude non-finite values. This requirement's statement is accurate to what the code
  does; it should not be read as a claim that Pydantic validation alone made NaN
  unreachable — the actual mitigation is downstream, in `PhysiologicalBoundsChecker`.
- **Verification:** `tests/integration/test_api_vitals.py::TestVitalsValidationErrors`

## 4. Non-Functional Requirements (observed, not separately REQ-tagged)

The following are implemented and tested but have no dedicated `REQ-*` tag in source — listed
here for SRS completeness, distinguished from §3's tagged requirements:

- **Advisory-only output:** every FHIR Observation/Bundle carries an
  `X-CDS-Advisory-Only: true` header and/or Bundle-level note (FDA CDS framing — see banner).
- **Timezone-aware timestamps only:** enforced at both the domain entity (`VitalSignSample.__post_init__`)
  and API boundary (Pydantic `field_validator`) — see HAZARD-TIME-001 in RMF-001.
- **CORS allow-list, fail-closed:** `config.py:373-388` — see HAZARD-CORS-001 in RMF-001
  (closed 2026-08-10).

## 5. Traceability Preview

Full Requirement → Design → Hazard → Test traceability is deliverable 3 of this Section
(next). §3 above already inlines each requirement's Hazard link and Verification reference as
a preview; deliverable 3 formalizes this into a single matrix and adds the Design-artifact
column (which class/function implements each requirement).

## 6. Known Gaps in This SRS (compiled transparently, not omitted)

- **The entire Phase 5-Stream layer has zero `REQ-*` tags** (§1.2) — MQTT publishing, the
  WebSocket live dashboard, FHIR Subscriptions, and mTLS device enrollment/reattestation are
  all `HAZARD-STREAM-*`-risk-tagged but have no corresponding functional-requirement tagging
  convention applied. This SRS cannot specify requirements that were never written down as
  such in source — recommend Section F (or a future pass) either retrofit `REQ-*` tags onto
  that layer's key invariants, or adopt a documented reason this layer is intentionally
  requirements-untagged.
- **REQ-API-002 has no dedicated test confirmed for its specific no-leak guarantee** — checked
  directly: `tests/integration/test_api_ingest.py::test_error_response_has_detail_field`
  accepts either a 422 or a 500 outcome and only asserts a `detail` field is present, which
  does not specifically verify the catch-all handler never leaks exception type/message/trace.
  A dedicated regression test for that exact guarantee does not appear to exist yet.
- **REQ-API-010's statement was written to be accurate, not reassuring** — it does NOT claim
  Pydantic validation excludes NaN/Infinity, because it doesn't by default. See that entry's
  Rationale for the precise, hazard-relevant distinction.
- **This document restates several docstrings as "SHALL" statements** that were originally
  written as design-intent prose, not formal requirements language — a deliberate, disclosed
  transformation (§1.1), not a claim that the original authors wrote IEEE-830-style
  requirements from the start.
