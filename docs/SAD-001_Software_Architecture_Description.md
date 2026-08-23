# SAD-001 — Software Architecture Description

## ICU Edge-to-FHIR Interoperability Gateway v1.0.0

> ## ⚠ STATUS BANNER — READ BEFORE USING THIS DOCUMENT FOR ANY PURPOSE
>
> **No credentialed Clinical Safety Officer is appointed.** The only sign-off authority that
> exists is an **interim, non-clinically-credentialed engineering appointment**
> ([docs/CSO_Role_Appointment_Brief.md](CSO_Role_Appointment_Brief.md) §5 — Housam Abouelreish,
> project owner, effective 2026-08-10), scoped to HAZARD-DSP-007 and HAZARD-STREAM-012 only. It
> does **not** ratify anything in this document.
>
> **This document describes architecture, not requirements or risk status.** For
> requirement-to-test traceability, see
> [RTM-001](RTM-001_Requirements_Traceability_Matrix.md). For hazard analysis, see
> [RMF-001](RMF-001_Risk_Management_File.md). For the functional requirement statements
> themselves, see [SRS-001](SRS-001_Software_Requirements_Specification.md). This document does
> not repeat those documents' findings except where architecture and traceability status
> intersect (§9).
>
> **FDA / Health Canada regulatory classification is an engineering assumption, not a regulatory
> determination** — see RMF-001's banner, which this document inherits unchanged.

---

**Document ID:** SAD-001
**Status:** DRAFT — engineering-compiled working document. Not a certified architecture
description.
**Prepared:** 2026-08-10, Phase 5-Stream Section E, deliverable 4.
**Method:** Every class, module, file path, and line number cited below was checked directly
against source this session (`grep -nE "^class |^def |^async def "` per file, plus targeted
reads of module docstrings and `main.py`'s composition root) — not transcribed from memory or
from other documents' prior citations without re-verification. Counts in §1.3 were computed by
enumeration, not estimated.

---

## 1. Introduction

### 1.1 Purpose

This document describes the software architecture of the ICU Edge-to-FHIR Interoperability
Gateway: its layering, its components, the design patterns it applies, how those components are
wired together at runtime, and how a request flows through the system along each of its six
entry points (two HTTP REST routes, one WebSocket route, one MLLP TCP listener, one FHIR
Subscription CRUD surface, and one background provisioning/reattestation task).

### 1.2 Scope

**In scope**, per the requesting instruction:

- The core Clean Architecture layers as originally implemented: `src/domain/`,
  `src/infrastructure/adapters/`, `src/infrastructure/fhir/`, `src/api/` (§3-§5).
- The Phase 5-Stream additions: the MLLP listener, the MQTT publisher, the WebSocket live
  dashboard channel, FHIR Subscriptions, zero-touch device provisioning/enrollment, the
  periodic re-attestation loop, and CA pinning (§6-§7).
- The composition root (`src/main.py`) that wires every one of the above together (§8).
- Cross-cutting concerns: error handling, CORS, logging, configuration (§9).
- Deployment topology as it exists in this repository today (§10).

**Out of scope:**

- The cloud control-plane Terraform stack (`infra/terraform/` — the CA, provisioning API, and
  telemetry modules). That stack is the *server side* of the enrollment/CA-pinning protocol this
  document's §7 describes from the *device side*; it is a separate deployable with its own
  design document (`infra/terraform/DESIGN.md`) and is referenced, not duplicated, here (§7.4).
- Requirement statements, hazard analysis, and test traceability — see the banner.
- The mock-control-plane / multi-vendor HL7 simulator local-dev tooling (`docker-compose.yml`'s
  non-`gateway` services) — referenced briefly in §10.2 as a development aid, not architected
  here as if it were part of the shipped system.

### 1.3 Source Inventory (counted, not estimated)

| Metric | Count | Method |
|---|---:|---|
| Non-`__init__.py` Python source files in `src/` | 35 | `find src -name "*.py" ! -name "__init__.py"`, excluding `__pycache__` |
| Test files | 37 | `find tests -name "test_*.py"`, excluding `__pycache__` |
| Test suites | 3 (`tests/unit/`, `tests/integration/`, `tests/regulatory/`) | directory listing |

### 1.4 References

[SRS-001](SRS-001_Software_Requirements_Specification.md) ·
[RMF-001](RMF-001_Risk_Management_File.md) ·
[RTM-001](RTM-001_Requirements_Traceability_Matrix.md) ·
[QMS-001_DHF_Structure.md](QMS-001_DHF_Structure.md) ·
`infra/terraform/DESIGN.md` (cloud control-plane architecture, out of scope here)

## 2. Architectural Style

### 2.1 Clean Architecture Layering

The application follows Clean Architecture (Robert C. Martin) with three layers, each importing
only inward or from itself, never outward:

```
┌─────────────────────────────────────────────────────────────────┐
│  api/            HTTP/WebSocket routes, request/response schemas │
│  (src/api/)      → depends on infrastructure and domain           │
├─────────────────────────────────────────────────────────────────┤
│  infrastructure/ HL7 adapter, FHIR builders, streaming,           │
│  (src/           provisioning — talks to the outside world        │
│  infrastructure/)→ depends on domain only                         │
├─────────────────────────────────────────────────────────────────┤
│  domain/         Entities, value objects, domain services —       │
│  (src/domain/)   zero framework/IO dependencies                   │
│                  → depends on nothing else in this codebase       │
└─────────────────────────────────────────────────────────────────┘
```

Confirmed by import direction, not asserted: `src/domain/services/vitals_orchestrator.py`
imports only from `domain.entities` and `domain.services` (no `infrastructure` or `api`
import); `src/infrastructure/adapters/hl7v2_adapter.py` imports from `domain.entities` but
never from `api`; `src/api/v1/ingest.py` imports from both `domain` and `infrastructure`. This
is the layering's actual, checked shape, not a diagram drawn independently of the code.

### 2.2 Design Patterns Applied (per source docstrings, not inferred)

| Pattern (GoF) | Where | Docstring citation |
|---|---|---|
| Strategy | `IFilterStrategy` (ABC) implemented by `DualNotchFilter`, `HampelFilter` | `src/domain/interfaces/i_filter_strategy.py:15`; `src/domain/services/artifact_rejector.py:61,198` |
| Facade | `VitalsOrchestrator.analyse()` — single entry point over the DSP→NEWS2 pipeline | `src/domain/services/vitals_orchestrator.py:68` |
| Factory Method | `create_app()` — assembles the full ASGI application | `src/main.py:176`, docstring at line 178 |

### 2.3 Two Architectural Eras in One Codebase

This codebase contains two additions layered onto the original pipeline, each with a distinct
traceability posture — stated here plainly because §9 depends on the distinction:

1. **Original Phase 5 core** (`domain/`, `infrastructure/adapters/`, `infrastructure/fhir/`,
   `api/v1/ingest.py`, `api/v1/vitals.py`, `api/v1/health.py`, `main.py`'s error handlers): every
   architecturally significant invariant is tagged `REQ-*` in source and traced in SRS-001/RTM-001.
2. **Phase 5-Stream** (`infrastructure/streaming/`, `infrastructure/provisioning/`,
   `api/v1/live.py`, `api/v1/fhir_subscription.py`): extensively `HAZARD-STREAM-*`-tagged
   (risk-managed) but carries **zero** `REQ-*` tags anywhere in source. This is documented as an
   explicit architectural-documentation limitation in §9, not silently omitted from this SAD.

## 3. Domain Layer (`src/domain/`)

Zero framework or I/O dependencies — pure Python, `dataclass`-based entities and stateless
services. This is the layer SRS-001's 17 `REQ-*` requirements are anchored to most densely.

### 3.1 Entities (`src/domain/entities/`)

| Class | File:line | Responsibility |
|---|---|---|
| `MonitorVendor`, `HL7Version` (enums) | `device_context.py:16,34` | Vendor/protocol-version identifiers used to select parsing strategy |
| `DeviceContext` | `device_context.py:47` | Immutable metadata about the source ICU monitor (device ID, vendor, model) — `@dataclass(frozen=True)` |
| `NEWS2RiskLevel` (enum) | `news2_score.py:21` | RCP 2017 risk-level classification (NORMAL/LOW/LOW_MEDIUM/MEDIUM/HIGH) |
| `NEWS2Score` | `news2_score.py:46` | Immutable aggregate of all seven NEWS2 component scores; `total`/`risk_level` are derived, non-settable properties |
| `SpO2Scale` (enum) | `patient_context.py:16` | Scale 1 (default) vs. Scale 2 (COPD/hypercapnic) |
| `PatientContext` | `patient_context.py:34` | Immutable clinical context (patient ID, SpO2 scale, encounter ID) required before NEWS2 scoring |
| `VitalSignType`, `VitalSignUnit`, `AVPULevel` (enums) | `vital_sign.py:16,36,49` | NEWS2-aligned vital sign identifiers, units, consciousness levels |
| `VitalSignSample` | `vital_sign.py:67` | Immutable, sole data unit flowing from adapter to DSP stage — `@dataclass(frozen=True)` |

### 3.2 Interfaces (`src/domain/interfaces/`)

| Interface | File:line | Role |
|---|---|---|
| `IFilterStrategy` (ABC) | `i_filter_strategy.py:15` | GoF Strategy contract implemented by the DSP filter classes (§3.3) |

### 3.3 Services (`src/domain/services/`)

| Class | File:line | Responsibility |
|---|---|---|
| `_require_finite()` (module function) | `artifact_rejector.py:46` | Shared non-finite (NaN/Inf) rejection guard used by all three filters below |
| `DualNotchFilter` (implements `IFilterStrategy`) | `artifact_rejector.py:61` | 50/60 Hz mains-interference notch filter, double-pass `filtfilt` |
| `BandpassFilter` | `artifact_rejector.py:103` | Vital-sign-specific Butterworth bandpass; removes DC offset/baseline wander |
| `HampelFilter` (implements `IFilterStrategy`) | `artifact_rejector.py:198` | Local median/MAD-based motion-artifact outlier detector |
| `PhysiologicalBoundsChecker` | `artifact_rejector.py:250` | Rejects out-of-range and non-finite scalar values before they can reach scoring |
| `NEWS2InsufficientDataError` (Exception) | `news2_calculator.py:36` | Raised when a mandatory NEWS2 parameter is absent/excluded — fail-fast, not partial-score |
| `NEWS2Calculator` | `news2_calculator.py:59` | Computes all seven RCP 2017 NEWS2 component scores |
| `ProcessedVitalSign` | `signal_processor.py:49` | Immutable DSP-stage output (`cleaned_value`, `is_within_physiological_bounds`, `pipeline_notes`) |
| `VitalSignProcessor` | `signal_processor.py:74` | Applies the appropriate filter chain to one `VitalSignSample` |
| `VitalsAnalysisResult` | `vitals_orchestrator.py:35` | Immutable top-level pipeline output — passed to the FHIR layer |
| `VitalsOrchestrator` | `vitals_orchestrator.py:61` | **Facade.** `analyse()` runs DSP→NEWS2 in the enforced order (HAZARD-ARCH-001 control) |

## 4. Infrastructure Layer — Adapters (`src/infrastructure/adapters/`)

| Class/function | File:line | Responsibility |
|---|---|---|
| `HL7ParseResult` | `hl7v2_adapter.py:206` | Parse output: samples, patient ID, detected vendor, skip/parse warnings |
| `HL7v2Adapter` | `hl7v2_adapter.py:231` | GoF Strategy context — parses HL7 v2.x ORU^R01 into `VitalSignSample` tuples, vendor-code-table-driven |
| `_safe_field()` | `hl7v2_adapter.py:788` | Single point of contact with `hl7apy`'s field API — absorbs field-access exceptions (REQ-HL7-003) |
| `_parse_hl7_datetime()`, `_parse_numeric()`, `_parse_numeric_array()`, `_decode_ed_payload()` | `hl7v2_adapter.py:808,860,895,925` | Field-level parsing helpers |

## 5. Infrastructure Layer — FHIR Output (`src/infrastructure/fhir/`)

| Class/function | File:line | Responsibility |
|---|---|---|
| `BundleAssembler` | `bundle_assembler.py:36` | Assembles the FHIR R4 `Bundle`; a single failed Observation becomes an `OperationOutcome` entry, never aborts the whole Bundle (REQ-FHIR-001) |
| `NEWS2ObservationBuilder` | `news2_builder.py:106` | Builds the NEWS2-total + 7-component-subobservation FHIR structure |
| `ObservationBuilder` | `observation_builder.py:128` | Builds a single vital-sign `Observation` resource |
| `_format_fhir_datetime()` | `observation_builder.py:346` | FHIR-conformant datetime serialization |
| `SubscriptionStatus`, `SubscriptionChannelType` (enums) | `subscription.py:63,72` | FHIR R4 `Subscription` status/channel-type vocabulary |
| `SubscriptionChannel` | `subscription.py:88` | Webhook delivery target (endpoint URL, headers) |
| `Subscription` | `subscription.py:98` | FHIR R4 `Subscription` resource (Phase 5-Stream — see §6.4) |
| `parse_patient_filter()`, `create_subscription_from_fhir_request()` | `subscription.py:146,167` | Criteria-string parsing and request-to-domain-object construction |

## 6. Phase 5-Stream — Streaming Layer (`src/infrastructure/streaming/`)

Everything in this section is new relative to the original Phase 5 core (§2.3). Each component
below is independently opt-in via an environment variable, wired at `src/main.py`'s ASGI
lifespan (§8).

### 6.1 MLLP Listener — Edge-Side TCP Ingestion

| Class | File:line | Responsibility |
|---|---|---|
| `MLLPIngestOutcome` | `mllp_listener.py:81` | Per-frame outcome record (ACK/NAK + bundle) |
| `MLLPFramingError` (ValueError subclass) | `mllp_listener.py:90` | Raised on malformed/oversized/non-UTF-8 frames |
| `MLLPListener` | `mllp_listener.py:94` | `__init__` (108), `start()`/`stop()` (151/157), async context manager (164/168), `_handle_connection()` (173), `_read_frame()` (200), `_process_frame()` (232) |

Wraps `HL7v2Adapter` behind MLLP (VT...FS CR) TCP framing — the same domain pipeline
(`HL7v2Adapter` → `VitalsOrchestrator` → `BundleAssembler`) used by `POST /api/v1/ingest`, for
devices/interface engines that speak MLLP instead of HTTP. Runs no DSP/NEWS2/FHIR logic itself
(HAZARD-ARCH-001 is inherited structurally, not reimplemented — `mllp_listener.py:17-20`).

### 6.2 Store-and-Forward Ring Buffer

| Class | File:line | Responsibility |
|---|---|---|
| `StoreAndForwardRingBuffer[T]` (Generic) | `ring_buffer.py:44` | Bounded FIFO with drop-oldest-on-overflow, used to decouple edge ingestion from cloud/broker availability |

Shared by the MLLP listener (producer) and the MQTT publisher (consumer) — see §8's lifespan
wiring for the concrete instance (`app.state.forward_buffer`, capacity 10,000).

### 6.3 MQTT Publisher — Edge→Cloud Telemetry

| Class | File:line | Responsibility |
|---|---|---|
| `MQTTPublisher` | `mqtt_publisher.py:85` | `__init__` (96), `start()`/`stop()` (143/187), async context manager (201/205), `_run_loop()` (210), `_publish_batch_sync()` (237), `_on_connect`/`_on_disconnect` (317/327) |

Drains `StoreAndForwardRingBuffer`, publishes each Bundle to a cloud MQTT broker (`paho-mqtt`
SOUP, pinned `2.1.0`). Reconnect via `connect_async()`+`loop_start()`+`reconnect_delay_set()`;
failed batches requeued via `StoreAndForwardRingBuffer.requeue_front()`, not dropped.

### 6.4 Live Dashboard Channel — WebSocket Fan-Out

| Function/class | File:line | Responsibility |
|---|---|---|
| `build_delta()` | `live_dashboard_channel.py:66` | Builds the compact delta envelope pushed to dashboard clients |
| `LiveDashboardChannel` | `live_dashboard_channel.py:84` | `__init__` (94), `connect()`/`disconnect()` (105/118), `broadcast()` (125), `schedule_broadcast()` (144), `_enqueue_with_overflow_policy()` (155) |

One bounded (`default 200`) `asyncio.Queue` per connected client, drop-oldest-on-overflow.
`broadcast()` never awaits a per-client send — one slow client cannot block delivery to any
other client or the producer. Consumed by the WebSocket route (`WS /api/v1/live/vitals`,
`src/api/v1/live.py:35`).

### 6.5 FHIR Subscriptions — Registry and Dispatch

| Class | File:line | Responsibility |
|---|---|---|
| `SubscriptionRegistry` | `subscription_registry.py:63` | `create()`/`get()`/`delete()`/`list_all()`/`count()` (70,81,85,92,97); `match()` (101) — criteria matching against a produced Bundle; `record_delivery_success/failure()` (124,129) — consecutive-failure tracking |
| `_parse_header_lines()` | `subscription_dispatcher.py:69` | Parses stored `channel.header` lines into a headers dict |
| `SubscriptionDispatcher` | `subscription_dispatcher.py:88` | `__init__` (96), `dispatch()` (109) — awaits delivery to every matching subscription, `schedule_dispatch()` (121) — fire-and-forget variant used by non-blocking producers, `aclose()` (129), `_deliver()` (132) |
| `UnsafeWebhookEndpointError` (ValueError subclass) | `url_safety.py:52` | Raised by the SSRF-baseline deny-list check |
| `validate_webhook_endpoint()` | `url_safety.py:56` | Registration-time deny-list (loopback/link-local/private/reserved/multicast, blocked hostnames, https-only default) |

HTTP surface (`src/api/v1/fhir_subscription.py`): `POST /api/v1/fhir/Subscription` (line 96,
201 Created), `GET /api/v1/fhir/Subscription/{id}` (line 133), `GET /api/v1/fhir/Subscription`
list (line 154), `DELETE /api/v1/fhir/Subscription/{id}` (line 179) — all four gated by
`_require_registration_secret()` (line 48), a pre-shared-secret dependency added per
HAZARD-STREAM-009.

## 7. Phase 5-Stream — Provisioning Layer (`src/infrastructure/provisioning/`)

Zero-touch mTLS device enrollment: a device generates its own keypair, requests a certificate
from the cloud control plane using a single-use enrollment token, and periodically re-attests to
detect revocation.

### 7.1 Device Identity Generation

| Function | File:line | Responsibility |
|---|---|---|
| `generate_private_key()` | `device_identity.py:49` | ECDSA keypair generation |
| `serialize_private_key()` / `load_private_key()` | `device_identity.py:57,68` | PEM serialization round-trip |
| `write_private_key_file()` | `device_identity.py:78` | Persists the key to `CertStore`'s path |
| `build_csr()` | `device_identity.py:107` | Constructs the Certificate Signing Request sent to the enrollment endpoint |

### 7.2 Enrollment Client and CA Pinning

| Class | File:line | Responsibility |
|---|---|---|
| `EnrollmentError`, `TokenRejectedError`, `EnrollmentNetworkError` | `enrollment_client.py:105,109,125` | Exception hierarchy — token rejection is never retried; network failure is retried with backoff |
| `ReattestationResult` | `enrollment_client.py:133` | Outcome of one `reattest()` call (still-valid / renewed / revoked) |
| `DeviceEnrollmentClient` | `enrollment_client.py:140` | Constructor pins TLS to the control plane's specific CA bundle (`ca_bundle_path` → `httpx.AsyncClient(verify=ca_bundle_path)`, `enrollment_client.py:186-198`, **not** the system default trust store) — the HAZARD-STREAM-010 server-authentication control; optional independently-sourced `expected_hostname` construction-time check |

**CA pinning cross-reference (added 2026-08-10, per explicit instruction):** the comment at
`enrollment_client.py:186-194` names HAZARD-STREAM-012 (fleet-wide CA private-key custody and
compromise blast radius) and points to `infra/terraform/modules/ca/main.tf:13-43`'s full hazard
record rather than restating it — this is the one place in `src/` where the device-side code
actually exercises trust in that CA. See RMF-001 §3.F / Appendix A (`HAZARD-STREAM-012`) for the
hazard record itself; RTM-001 §6.2 for how this cross-reference was verified.

### 7.3 Certificate Storage, Bootstrap, and Re-Attestation

| Class/function | File:line | Responsibility |
|---|---|---|
| `IssuedCredentials` | `cert_store.py:82` | Value object for a freshly issued cert+key+CA-chain triple |
| `CertStore` | `cert_store.py:89` | `load_or_generate_key()` (111), `write_issued_credentials()` (125), `load_certificate()` (137), `has_valid_identity()` (143), `quarantine()` (157) — moves a revoked/expired identity out of the active path |
| `ensure_device_identity()` | `bootstrap.py:30` | Container-entrypoint step, run **before** `uvicorn` starts (`docker/entrypoint.sh`); idempotent — a no-op if a valid identity already exists in the mounted cert store |
| `_main()` (CLI entry) | `bootstrap_cli.py:42` | `python -m` invocation wrapping `ensure_device_identity()` |
| `_reattest_once()`, `reattestation_loop()` | `reattestation.py:50,89` | Runs `DeviceEnrollmentClient.reattest()` on an interval for the lifetime of the ASGI process — the HAZARD-STREAM-011 mitigation that was previously reachable but never scheduled before this addition |

**Why the reattestation loop lives in the ASGI lifespan, not `bootstrap_cli.py`** (per
`reattestation.py:10-15`, verified against source): `bootstrap_cli.py` is a one-shot pre-flight
check that exits before `uvicorn` starts; "is this device still trusted" is a continuous concern
matching the running app's lifetime, not a startup-only check.

### 7.4 Out-of-Scope Boundary: Cloud Control Plane

The CA server (`step-ca`), the provisioning API, and the telemetry pipeline this section's
components talk to are implemented in `infra/terraform/` (Terraform, AWS ECS Fargate/EFS/NLB) —
a separate deployable, not Python application code, and explicitly out of this document's scope
(§1.2). `infra/terraform/DESIGN.md` is that stack's own design document.

### 7.5 Companion Document — Cloud Control Plane Architecture

[`infra/terraform/DESIGN.md`](../infra/terraform/DESIGN.md) is the companion architecture
document for the other side of the enrollment/reattestation/CA-pinning protocol §7.1-§7.3
describe: it states plainly, in its own opening section, that it implements "the SERVER side of
the protocol `infrastructure/provisioning/enrollment_client.py` (device side, already shipped)
codifies as a contract." **SAD-001 covers the device/edge side of that contract only** — the
`DeviceEnrollmentClient`, `CertStore`, `device_identity` key/CSR generation, and the
reattestation loop, all running on the edge appliance itself (§7.1-§7.3). **`DESIGN.md` covers
the server side** — the `step-ca` CA, the provisioning API that issues certificates against
enrollment tokens, the telemetry pipeline, and the AWS infrastructure (Fargate/EFS/NLB) hosting
all three. The two documents describe opposite ends of one wire protocol and are meant to be
read together for a complete picture of enrollment; **this is a cross-reference, not a merge**
— SAD-001 does not restate `DESIGN.md`'s content (§7.4 already establishes this same boundary
for the hazard/mitigation material specifically; this subsection states it once, explicitly, at
the document level).

## 8. Composition Root (`src/main.py`)

### 8.1 `create_app()` — Factory Method (`main.py:176`)

Builds the `FastAPI` instance, registers `CORSMiddleware` (fail-closed allow-list,
HAZARD-CORS-001), registers two global exception handlers
(`value_error_handler`/`unhandled_exception_handler` at lines 217/240 — REQ-API-001/REQ-API-002,
§9.2), and includes five routers: `health_router` (`GET /health`), `ingest_router`
(`POST /api/v1/ingest`), `vitals_router` (`POST /api/v1/vitals`), `live_router`
(`WS /api/v1/live/vitals`), `fhir_subscription_router` (`/api/v1/fhir/Subscription*`).

### 8.2 `lifespan()` — Component Wiring (`main.py:54`)

Unconditional (always constructed, cheap/in-memory), stored on `app.state`:

- `forward_buffer` — `StoreAndForwardRingBuffer(capacity=10_000)` (`main.py:96-98`)
- `live_dashboard_channel` — `LiveDashboardChannel()` (`main.py:99`)
- `subscription_registry` / `subscription_dispatcher` (`main.py:100-103`)

Conditional (opt-in via environment variable, each independently toggleable):

| Component | Env var (via `config.py`) | Wiring |
|---|---|---|
| `MLLPListener` | `get_mllp_enabled()` | `main.py:108-122` — bound to `forward_buffer`, `live_dashboard_channel`, `subscription_dispatcher` |
| `MQTTPublisher` | `get_mqtt_enabled()` | `main.py:124-145` — drains `forward_buffer` |
| Reattestation background task | `get_provisioning_enabled()` | `main.py:147-159` — `asyncio.create_task(reattestation_loop(...))`, cancelled and awaited (not abandoned) on shutdown (`main.py:163-166`) |

Shutdown order (`main.py:163-173`, reverse of startup-significance, verified against source):
reattestation task cancelled first, then MQTT publisher stopped, then MLLP listener stopped,
then subscription dispatcher's `httpx.AsyncClient` closed.

## 9. Cross-Cutting Concerns

### 9.1 Requirement/Hazard Tagging Status — Stated Limitation, Not Silent Omission

Per explicit instruction, this section documents the Phase 5-Stream layer's lack of `REQ-*`
tagging as an architectural-documentation limitation of this SAD, cross-referenced against
RTM-001 rather than re-litigated here:

- **RTM-001 §2** made the explicit decision **not** to retroactively add `REQ-*` tags to
  `src/infrastructure/streaming/` or `src/infrastructure/provisioning/` for traceability-matrix
  purposes, reasoning that doing so would invert SRS-001's reverse-derivation method (tags would
  be manufactured to fill a matrix, not extracted from pre-existing source intent).
- **RTM-001 §6** shows the consequence precisely: the streaming/provisioning layer is
  **hazard-tracked** (every `HAZARD-STREAM-*`/`HAZARD-ARCH-001`/`HAZARD-DSP-007` reference in
  §6-§7 above traces to a source location, and as of RTM-001 §6.1's follow-up, all twelve
  `HAZARD-STREAM-*` IDs also trace into the Risk Register) but **not requirement-tracked** — no
  `REQ-*` ID exists anywhere in `src/infrastructure/streaming/` or
  `src/infrastructure/provisioning/`, confirmed by `grep -rno "REQ-[A-Z0-9-]*"` against both
  directories returning zero matches (re-run this session, same result as RTM-001's).
- **This SAD's own architectural descriptions in §6-§7 are therefore traced to hazard IDs and
  source citations, not to `REQ-*` IDs**, unlike §3-§5's original-core descriptions, several of
  which reference the `REQ-*` ID governing that component (e.g. §3.1's `DeviceContext` →
  REQ-DEV-001; §5's `BundleAssembler` → REQ-FHIR-001). A reader should not infer from this
  document's uniform table formatting that §6-§7's components carry the same
  requirement-traceability weight as §3-§5's — they do not, and RTM-001 is the authoritative
  record of that gap, not this document.

### 9.2 Error Handling

Two global exception handlers registered in `create_app()` (§8.1):

- `value_error_handler` (`main.py:217-238`, REQ-API-001): domain `ValueError` → HTTP 422 with
  `{"error": "validation_error", "detail": str(exc)}`.
- `unhandled_exception_handler` (`main.py:240-267`, REQ-API-002): any other exception → HTTP 500
  with a fixed generic body; the actual exception type/message/traceback is logged server-side
  only (`structlog` ERROR level), never returned to the caller. Regression-tested by
  `tests/integration/test_main_exception_handler.py` (added in a prior session, per RTM-001 §5).

### 9.3 CORS (HAZARD-CORS-001)

`get_cors_allowed_origins()` (`config.py:371`) raises `ValueError` at `create_app()` time on a
wildcard, empty, or whitespace-only value — a misconfigured deployment fails to start rather
than silently exposing the API to any origin. `allow_credentials=False`; `allow_methods`
restricted to `["GET", "POST"]` (`main.py:207-213`).

### 9.4 Logging

`structlog` throughout — every module-level logger is `structlog.get_logger(__name__)`. No
central logging-configuration call exists anywhere in `src/` (`grep -rn "structlog.configure"
src/` — zero matches across all 35 files, not a scope-limited check); structlog's default
processor chain is used as-is, confirmed by a prior session's
`structlog.testing.capture_logs()`-based test working without any explicit configuration.

### 9.5 Configuration (`src/config.py`)

17 accessor functions (`get_mllp_enabled()` through `get_cors_allowed_origins()`), one per
environment variable, each with an explicit default and, where a hazard depends on it
(`get_cors_allowed_origins()`, `get_provisioning_ca_bundle_path()`), fail-closed validation
rather than a silent fallback to an unsafe value.

## 10. Deployment View

### 10.1 Container Image (`Dockerfile`)

Two-stage build: `python:3.11-alpine3.19` builder (compiles `scipy`/`numpy`'s native
dependencies) → minimal Alpine runtime stage (`libstdc++`, `openblas` only). Non-root user
(`gateway`, uid/gid 1001). `ENTRYPOINT ["/app/entrypoint.sh"]` runs
`ensure_device_identity()`'s CLI wrapper (`bootstrap_cli.py`, no-op unless
`PROVISIONING_ENABLED=true`) before `exec`-ing `uvicorn`. `HEALTHCHECK` polls `GET /health`
every 30s. Single-worker `uvicorn` — horizontal scale is Kubernetes pods, not multiple workers
per container (`main.py:284-292`).

### 10.2 Local Development (`docker-compose.yml`)

Provides a `gateway` service plus a mock control-plane / multi-vendor HL7 simulator for
exercising the Phase 5-Stream provisioning and MLLP paths without a real cloud CA — a
development aid, not part of the deployed system's architecture (§1.2 scope boundary).

### 10.3 Edge Deployment (`deploy/k3s/edge-appliance.yaml`)

Kubernetes/k3s manifest for the edge-appliance deployment target this Dockerfile is built for —
referenced here as the deployment artifact; its `storageClassName` gap for the device-key PVC is
a risk-management finding (`UNASSIGNED-PVC-001`, RMF-001 §3.F), not an architectural one, and is
not re-described here.

### 10.4 Third-Party Runtime Dependencies (SOUP, IEC 62304 §8.1.2)

Per `requirements.txt`: `paho-mqtt==2.1.0` (MQTT publisher, §6.3), `httpx==0.25.2` (Subscription
dispatcher §6.5 and enrollment client §7.2), `cryptography==50.0.0` (device identity §7.1) — all
three carry an explicit vetting note in `requirements.txt` stating they are web-sourced, not
Endor-SCA-verified determinations, flagged for human re-verification before production sign-off.
This document does not re-assert their safety beyond citing that existing note.

## 11. Self-Flagged Gaps (this document)

- **§9.1 is the load-bearing section for the requested Phase 5-Stream `REQ-*` limitation** — it
  is stated once, precisely, and cross-referenced to RTM-001 rather than repeated per-component
  in §6-§7's tables, to avoid diluting it into boilerplate. A reader skimming only §6-§7 without
  reading §9.1 could miss the distinction; this is a structural risk of the chosen presentation,
  noted rather than hedged against with repeated inline caveats.
- **No sequence/data-flow diagrams included** — this document is component- and class-level
  (what exists, where, and how it is wired at startup), not a request-by-request sequence
  diagram for each of the six entry points. A reader wanting "what happens, in order, for one
  MLLP frame" must currently combine §6.1's table with `mllp_listener.py`'s own docstring; this
  document does not restate that sequence.
- **`infra/terraform/` (cloud control plane) is referenced, not architected** — §7.4 states the
  scope boundary explicitly; a complete system architecture description spanning edge and cloud
  would need a companion document merging this SAD with `infra/terraform/DESIGN.md`, which does
  not exist.
- **Docker-compose's mock-control-plane/simulator services are named but not individually
  cataloged** (§10.2) — out of scope per §1.2, but a reader building local-dev familiarity from
  this document alone will need to read `docker-compose.yml` directly.
- **§10.4's SOUP vetting note is reported, not independently re-verified** — this document
  cites `requirements.txt`'s existing self-disclosed "web-sourced, not Endor-verified" caveat
  rather than re-running or re-confirming that determination itself.
