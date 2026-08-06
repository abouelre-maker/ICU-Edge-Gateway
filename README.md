# ICU Edge-to-FHIR Interoperability Gateway

**SaMD middleware** that converts legacy ICU bedside monitor data (HL7 v2.x) into FHIR R4
Bundles with embedded NEWS2 (National Early Warning Score 2) clinical scoring.

> **Regulatory status: IN PROGRESS, not finalized.** This project has an active Phase 7
> regulatory/QMS workstream (see [§ Regulatory & QMS Package](#regulatory--qms-package)
> below). The product's FDA classification is **not yet determined** — do not treat any
> comment or label in this codebase claiming "FDA CDS Non-Device Exemption" as a settled
> fact; it is under active review. See
> [docs/REG-001_Intended_Use_and_CDS_Exemption_Draft.md](docs/REG-001_Intended_Use_and_CDS_Exemption_Draft.md).

---

## What this does

1. **Ingests** vital sign data from ICU bedside monitors — either raw HL7 v2.x ORU^R01
   messages (`POST /api/v1/ingest`) or pre-normalized JSON (`POST /api/v1/vitals`).
2. **Parses** scalar vitals (heart rate, respiratory rate, SpO₂, systolic/diastolic BP,
   temperature, AVPU consciousness, supplemental O₂) across five vendor dialects (Philips
   IntelliVue, GE CARESCAPE, Dräger Infinity, Mindray Beneview, Nihon Kohden) plus a
   LOINC-fallback generic path.
3. **Parses continuous waveform channels** (ECG, plethysmograph, etc. via HL7 NA/ED OBX
   segments, including Base64-encoded ED payloads) and runs them through a DSP
   artifact-rejection pipeline: 50/60 Hz dual-notch filtering → vital-sign-specific
   Butterworth bandpass filtering → Hampel-filter motion-artifact rejection.
4. **Calculates NEWS2** (RCP 2017 algorithm) total score and seven per-parameter
   sub-scores, from **scalar vitals only** — waveform data is architecturally and
   test-guarded from ever feeding the score (`TestWaveformNeverFeedsNews2Score`).
5. **Emits a FHIR R4 Bundle** — NEWS2 Observation with per-component sub-observations,
   individual vital-sign Observations, and cleaned waveform data — with an explicit,
   machine-readable `X-CDS-Advisory-Only: true` marker on every response. No automated
   clinical action is ever triggered by this software.

## Architecture

Clean Architecture / hexagonal layering, enforced by IEC 62304 §5.3 single-responsibility
comments throughout the codebase:

```
┌─────────────────────────────────────────────────────────────────────┐
│  api/v1/          FastAPI routers — HTTP adaptation only             │
│    ingest.py         POST /api/v1/ingest  (raw HL7 v2.x)             │
│    vitals.py         POST /api/v1/vitals  (normalized JSON)          │
│    health.py         GET  /health         (liveness/readiness)       │
├─────────────────────────────────────────────────────────────────────┤
│  domain/           Pure clinical logic — no I/O, no framework deps   │
│    entities/          VitalSignSample, PatientContext, NEWS2Score…   │
│    services/                                                         │
│      artifact_rejector.py    DualNotch / Bandpass / Hampel filters   │
│      signal_processor.py     4-stage DSP pipeline orchestrator       │
│      news2_calculator.py     RCP 2017 NEWS2 scoring algorithm        │
│      vitals_orchestrator.py  Top-level analysis entry point          │
├─────────────────────────────────────────────────────────────────────┤
│  infrastructure/   Adapters to the outside world                     │
│    adapters/hl7v2_adapter.py     HL7 v2.x → domain entities          │
│    fhir/                          domain entities → FHIR R4 resources│
├─────────────────────────────────────────────────────────────────────┤
│  config.py          CORS_ALLOWED_ORIGINS-driven, fail-closed CORS    │
│  main.py             FastAPI app factory, exception handlers, ASGI   │
└─────────────────────────────────────────────────────────────────────┘
```

## API Reference

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness/readiness probe |
| `POST` | `/api/v1/ingest` | Accepts a raw HL7 v2.x ORU^R01 message body, returns a FHIR R4 Bundle |
| `POST` | `/api/v1/vitals` | Accepts pre-normalized JSON vital signs, returns a FHIR R4 Bundle |
| `GET` | `/docs` | OpenAPI (Swagger) interactive documentation |
| `GET` | `/openapi.json` | OpenAPI schema |

Every clinical response carries an `X-CDS-Advisory-Only: true` header and a matching FHIR
extension — this software never initiates automated treatment.

## Quickstart

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Run the test suite:

```bash
pytest --cov=src
```

Run the server locally:

```bash
export CORS_ALLOWED_ORIGINS="http://localhost:3000"   # required in production; see below
python -m uvicorn main:app --app-dir src --host 0.0.0.0 --port 8000
```

Then visit `http://localhost:8000/docs` for interactive API documentation, or `/health` for
a liveness check.

**`CORS_ALLOWED_ORIGINS` is mandatory to set explicitly for any non-local deployment.** If
unset, the gateway falls back to a `http://localhost:3000` dev default; if set to `*`, the
gateway refuses to start ([src/config.py](src/config.py) — HAZARD-CORS-001 mitigation).

For containerized deployment, see the multi-stage `Dockerfile` (Alpine 3.19, non-root,
<150 MB target image) and [docs/DEPLOYMENT_RUNBOOK.md](docs/DEPLOYMENT_RUNBOOK.md) for the
full step-by-step procedure.

## Test Suite & Quality Gates

```
332 passed, 1 xfailed (intentional, strict — see HAZARD-DSP-005), 91% line coverage
ruff check src tests: clean
```

- **Unit tests** (`tests/unit/`) — individual filter/algorithm correctness (DSP filters,
  NEWS2 boundary conditions, bounds checking, CORS config).
- **Integration tests** (`tests/integration/`) — full pipeline: HL7 parsing → DSP → NEWS2 →
  FHIR output; API-level request/response behavior.
- **Regulatory tests** (`tests/regulatory/`) — NEWS2 safety-critical boundary verification,
  each test docstring traceable to a specific RCP 2017 table cell.

The one `xfail(strict=True)` test is not a skipped or ignored failure — it's a deliberately
inverted assertion documenting a known, characterized residual risk (HAZARD-DSP-005). If it
ever starts passing unexpectedly, the suite fails loudly, forcing a conscious risk-register
update rather than a silent behavior change.

Run linting and the full gate locally:

```bash
ruff check src tests
pytest --cov=src --cov-report=term-missing
```

## Regulatory & QMS Package

Phase 7 (Regulatory/QMS Preparation) is in progress. Current artifacts, all explicitly
marked as drafts pending human sign-off — **none of these constitute a completed regulatory
submission or a certified QMS**:

| Document | Purpose | Status |
|---|---|---|
| [docs/REG-001_Intended_Use_and_CDS_Exemption_Draft.md](docs/REG-001_Intended_Use_and_CDS_Exemption_Draft.md) | Draft Intended Use Statement + FDA CDS Non-Device exemption analysis | 🔶 Draft — classification decision pending regulatory/legal review |
| [docs/QMS-001_DHF_Structure.md](docs/QMS-001_DHF_Structure.md) | Design History File & Risk Management File structure, modular by software function | 🔶 Draft structure — most underlying records not yet formalized |
| [docs/QMS-002_CSO_Ratification_Protocol.md](docs/QMS-002_CSO_Ratification_Protocol.md) | Formal risk-acceptance package for HAZARD-DSP-005 / HAZARD-DSP-006 | 🔶 Draft — blocked on CSO appointment (see next row) |
| [docs/CSO_Role_Appointment_Brief.md](docs/CSO_Role_Appointment_Brief.md) | Template for appointing the Clinical Safety Officer / Medical Director who executes QMS-002 | 🔶 Template — no appointment made yet |
| [docs/ICU_Edge_Gateway_Phase5_Technical_Package.md](docs/ICU_Edge_Gateway_Phase5_Technical_Package.md) | Phase 5 closure record: P0 waveform-DSP gap closure, initial risk register | ✅ Historical record |
| [docs/DEPLOYMENT_RUNBOOK.md](docs/DEPLOYMENT_RUNBOOK.md) | Step-by-step install, verify, and release-tagging procedure | ✅ Current |

**Known open items** (not resolved by any document above): REG-001's classification decision
itself; QMS-002's actual sign-off execution (needs a named CSO — no such role is currently
appointed anywhere in this project); HAZARD-PROTO-002 (waveform default sampling-rate table
needs per-connected-monitor-model validation before clinical use against that model).

## Risk Management Summary

| Hazard ID | Status |
|---|---|
| HAZARD-CORS-001 (CORS wildcard) | ✅ Mitigated — [config.py](src/config.py) |
| HAZARD-DSP-006 (filtfilt edge false-positives) | ✅ Mitigated, residual trade-off documented — pending CSO ratification |
| HAZARD-DSP-005 (bandpass/Hampel sensitivity interaction) | 🟡 Accepted as engineering-level residual risk — pending CSO ratification |
| HAZARD-DSP-004 (dangling hazard-ID doc reference) | ✅ Resolved |
| HAZARD-WAVE-001 (partial waveform array corruption) | ✅ Mitigated — fail-whole-array rule |
| HAZARD-PROTO-002 (per-monitor sampling-rate validation) | 🔲 Open — needs real device data |

Full traceability: [docs/QMS-001_DHF_Structure.md §4.2](docs/QMS-001_DHF_Structure.md#42-risk-traceability--entries-explicitly-requested-for-this-draft).

## Project Structure

```
src/
  api/v1/                  FastAPI routers (ingest, vitals, health)
  domain/
    entities/              Immutable clinical value objects
    interfaces/            Strategy pattern contracts (IFilterStrategy)
    services/               DSP pipeline, NEWS2 calculator, orchestrator
  infrastructure/
    adapters/hl7v2_adapter.py  HL7 v2.x parsing (5 vendor dialects + generic)
    fhir/                       FHIR R4 resource builders
  config.py                CORS origin resolution (fail-closed)
  main.py                  ASGI app factory
tests/
  unit/                    Filter/algorithm-level tests
  integration/              Full-pipeline and API-level tests
  regulatory/               NEWS2 safety boundary verification
docs/                      Phase 5-7 technical and regulatory/QMS documentation
Dockerfile                 Multi-stage, Alpine, non-root, IEC 62304-annotated
```

## License

Proprietary — IEC 62304 Class B SaMD (per `pyproject.toml` / Dockerfile OCI labels).

## Contact

Housam Abouelreish — [linkedin.com/in/housam-abouelreish-805352226](https://linkedin.com/in/housam-abouelreish-805352226)
