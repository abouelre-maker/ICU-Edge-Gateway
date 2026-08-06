# ICU Edge Gateway — Project Handoff & Status Summary

**Prepared:** 2026-08-06
**As of:** Git tag `v1.0.0`, commit `13324af`
**Audience:** Strategic advisor / executive stakeholder briefing
**Grounding:** Every claim below is traceable to a specific file, test, or commit in the
repository — this is a status report, not a marketing document.

---

## 1. Executive Project Overview

**What it is:** The ICU Edge Gateway is a Software as a Medical Device (SaMD) middleware
system that sits between legacy ICU bedside monitors and modern EHR/clinical systems. It
receives vital sign data in the hospital-standard **HL7 v2.x** messaging format, converts it
to the modern **FHIR R4** interoperability standard, and calculates the **NEWS2** (National
Early Warning Score 2 — the UK Royal College of Physicians' 2017 clinical deterioration
scoring algorithm) as a clinical decision support output.

**Architecture:** Clean Architecture / hexagonal design — a pure `domain/` layer containing
all clinical logic (scoring, signal processing) with zero framework dependencies, wrapped by
an `infrastructure/` layer (HL7 parsing, FHIR resource building) and a thin `api/` layer
(FastAPI HTTP routing). This separation is enforced throughout the codebase, not just
described in comments — the domain layer's test suite runs entirely independent of the web
framework.

**Primary intent:** Close the interoperability gap between older bedside monitors (which
speak only HL7 v2.x, a decades-old messaging standard) and modern digital health
infrastructure (which expects FHIR R4), while adding real-time clinical deterioration
scoring as a value-added advisory layer.

**High-level capabilities:**
- Parses vital signs from 5 named ICU monitor vendor dialects (Philips IntelliVue, GE
  CARESCAPE, Dräger Infinity, Mindray Beneview, Nihon Kohden) plus a generic LOINC-code
  fallback path.
- Parses continuous physiological waveforms (ECG, plethysmograph) with a dedicated digital
  signal processing pipeline.
- Calculates NEWS2 scores from scalar vital signs, with full per-parameter transparency.
- Outputs standards-compliant FHIR R4 Bundles over a REST API.
- Every clinical output is explicitly marked advisory-only, machine-readably, with no
  automated treatment action taken anywhere in the system.

---

## 2. Engineering & Codebase State

### 2.1 Release status

| Item | Value |
|---|---|
| Version tag | `v1.0.0` (annotated git tag) |
| Tag commit | `13324af` |
| `pyproject.toml` version | `1.0.0` — reconciled to match `main.py`'s FastAPI app version and the Dockerfile's OCI label (previously inconsistent at `0.1.0`) |
| Commit history (this release cycle) | 6 commits: security hardening (CORS), two DSP hazard resolutions, HL7 waveform-parsing feature, and the Phase 7 documentation/release commit |

### 2.2 Verified test suite results

```
332 tests passed
1 intentional xfail (strict) — HAZARD-DSP-005, documented residual risk
91% line coverage across src/
ruff check src tests: clean (zero lint violations)
```

The single `xfail` is not a skipped or hidden failure — it is a deliberately inverted
assertion (`xfail(strict=True)`) that documents a known, characterized limitation. If that
test ever unexpectedly starts passing, the entire suite fails automatically, forcing a
conscious re-evaluation rather than allowing a silent behavior change to go unnoticed.

### 2.3 Core technical capabilities (verified, not aspirational)

| Capability | Implementation | Verification |
|---|---|---|
| HL7 v2.x parsing | `src/infrastructure/adapters/hl7v2_adapter.py` — 5 vendor dialects + LOINC fallback, scalar + waveform (NA/ED, including Base64) OBX segments | `tests/integration/test_hl7v2_adapter.py` |
| FHIR R4 mapping | `src/infrastructure/fhir/` — Observation, Bundle, NEWS2-specific resource builders | `tests/integration/test_fhir_bundle.py`, `test_fhir_conformance.py` |
| NEWS2 calculator | `src/domain/services/news2_calculator.py` — RCP 2017 algorithm, every scoring boundary traceable to the published standard | `tests/regulatory/test_news2_safety.py`, `tests/unit/test_news2_calculator.py` |
| Waveform DSP pipeline | `src/domain/services/signal_processor.py`, `artifact_rejector.py` — dual-notch, Butterworth bandpass, Hampel artifact rejection | `tests/unit/test_artifact_rejector.py`, `tests/integration/test_hl7v2_waveform_pipeline.py` |

### 2.4 Runtime readiness

- **Application framework:** FastAPI (ASGI), served by `uvicorn` in production.
- **Containerization:** Multi-stage Dockerfile, Alpine 3.19 base, non-root execution
  (uid 1001), target image size <150 MB, built-in Kubernetes-compatible health check
  polling `GET /health`.
- **Dependency manifests:** `requirements.txt` and `requirements-dev.txt` — both verified
  complete and installable this session. Two gaps found and fixed during this engagement:
  `hl7apy` and, most recently, `fastapi`/`uvicorn` were missing from `requirements.txt`
  despite being hard runtime dependencies; both are now present.
- **Security control:** CORS origins are environment-driven and fail closed — the
  application refuses to start if `CORS_ALLOWED_ORIGINS` is set to a wildcard or left empty
  (`src/config.py`), closing the previously open HAZARD-CORS-001 finding.

---

## 3. Regulatory & Quality Management System (QMS) Deliverables (Phase 7)

All five documents below are explicitly marked as **drafts** requiring human/regulatory/
clinical sign-off — none constitute a completed regulatory submission or a certified QMS.

### 3.1 REG-001 — FDA CDS Exemption Assessment
*(`docs/REG-001_Intended_Use_and_CDS_Exemption_Draft.md`)*

Identifies that the codebase implements **two distinguishable software functions** with
different regulatory profiles:
- **Function A** (NEWS2 scoring/FHIR reporting, scalar vitals only) — has real,
  code-verifiable design evidence supporting 3 of the FDA's 4 Non-Device CDS criteria
  (display of information, clinical recommendation purpose, independent-review-enabling
  design). The fourth criterion (no signal/image processing) is plausible but rests on an
  interpretive legal question not resolvable by engineering analysis alone.
- **Function B** (the waveform DSP pipeline) — **does not meet** the FDA's Criterion 1 as
  currently implemented, since it explicitly processes continuous physiological signal data.
  On the plain text of the exemption criteria, this function does not qualify as Non-Device
  CDS.
- **Key finding:** the blanket *"FDA CDS Non-Device Exemption"* label already present in the
  existing codebase's comments (`main.py`, `news2_calculator.py`) applies to the whole
  product, which this analysis indicates is not accurate once Function B is in scope. A
  likely-incorrect regulatory citation (`21 CFR §880.3780`) was also flagged for correction.

### 3.2 QMS-001 — Modular DHF & ISO 14971 Risk Traceability Matrix
*(`docs/QMS-001_DHF_Structure.md`)*

Defines a Design History File structure split by software function (Module A / Module B)
for design-control records, with a **unified** Risk Management File (risk can propagate
across module boundaries). Contains a risk traceability table covering **6 hazard IDs**
(HAZARD-CORS-001, DSP-001/002/003, DSP-004, DSP-005, DSP-006, WAVE-001, PROTO-002), each
citing its actual mitigating code and verifying test. Honestly documents that most other DHF
sections (governance, formal design reviews, clinical validation, design transfer,
post-market surveillance) do not yet exist as real records — this is a structure to
populate, not a completed file. Also surfaces that the Phase 5 documentation's referenced
risk-register spreadsheet does not actually exist in the repository.

### 3.3 QMS-002 — Clinical Safety Officer Ratification Protocol
*(`docs/QMS-002_CSO_Ratification_Protocol.md`)*

A structured decision package for a qualified Clinical Safety Officer (CSO) to formally
accept, reject, or conditionally accept two residual risks:
- **HAZARD-DSP-005** (bandpass/Hampel filter interaction reduces motion-artifact detection
  sensitivity post-bandpass) — an **open, unmitigated** risk with a proposed ALARP-band
  severity/probability/detectability score, bounded in exposure because waveform data is
  architecturally and test-guarded from ever feeding the NEWS2 score.
- **HAZARD-DSP-006** (filtfilt boundary artifacts) — an **already-mitigated** risk requiring
  narrower concurrence-only ratification of one accepted, tested trade-off (edge-zone
  artifacts are still value-corrected but under-counted in audit reporting).

Includes a formal fillable sign-off template with decision options, required justification
fields, and re-review triggers. **Currently blocked**: no individual has been appointed to
the CSO role anywhere in this project's record, so this protocol cannot yet be executed.

### 3.4 Supporting deliverables

| Document | Purpose |
|---|---|
| `docs/CSO_Role_Appointment_Brief.md` | Ready-to-use template defining required credentials, scope of authority, a 30-day onboarding checklist, and a fillable appointment record for whoever fills the CSO role |
| `README.md` (repo root) | Architecture overview, API reference, quickstart instructions, verified test/coverage status, and a regulatory-status table linking to all Phase 7 documents |
| `docs/DEPLOYMENT_RUNBOOK.md` | Step-by-step install/verify/run/containerize/release-tag procedure, with an explicit scope note that software version tagging is a configuration-management milestone, not a regulatory clearance event |

---

## 4. Open Decisions & Actionable Dependencies

These are the concrete blockers to further progress — none can be resolved by further
engineering work alone.

### 4.1 REG-001 — Classification path selection

A decision is needed among (at minimum) three paths, each with different downstream QMS and
go-to-market implications:

- **(a) Full Class II SaMD pathway** for the entire product (consistent with the
  pre-existing Health Canada Class II classification note already in the codebase).
- **(b) Firewalled exempt-CDS approach** — scope the Non-Device CDS claim to Function A
  only, with Function B (waveform DSP) technically and organizationally separated
  (e.g., a deployment flag disabling waveform ingestion) and regulated/labeled independently.
- **(c) Formal regulatory/legal opinion** resolving the open interpretive question in
  Function A's Criterion 1 analysis, with a corresponding determination for Function B.

**This decision gates the scope of QMS-001's design-control requirements and the overall
go-to-market timeline** — it should be prioritized above the other open items.

### 4.2 CSO appointment — required for QMS-002

No Clinical Safety Officer or Medical Director is currently designated. Until this
appointment is made (using `docs/CSO_Role_Appointment_Brief.md` as the template), the
HAZARD-DSP-005 and HAZARD-DSP-006 risk-acceptance decisions remain formally unratified,
even though the underlying technical mitigations for DSP-006 are complete and tested.

### 4.3 HAZARD-PROTO-002 — per-monitor sampling-rate validation (not requested in your list, included for completeness)

The waveform pipeline's default sampling-rate table (per vital sign type) is an engineering
default, not a universal HL7 standard — it requires validation against each specific
connected monitor model's actual interface specification before clinical use of the
waveform DSP pipeline against that model. This needs real device data from clinical/
biomedical engineering, not further code changes.

---

## 5. Recommended Next Steps for Business Operations

1. **Convene a regulatory/legal review to resolve REG-001** (§4.1) as the top priority — it
   determines the shape of everything else, including whether Function B needs to be
   descoped from the near-term product or pursued as a Class II submission.
2. **Appoint a Clinical Safety Officer or Medical Director** (§4.2) using the prepared brief,
   and have them execute the two pending QMS-002 sign-offs.
3. **Stand up real QMS governance infrastructure** — document control numbering, a formal
   Design & Development Plan, and population of the still-empty DHF sections identified in
   QMS-001 (design reviews, clinical validation, design transfer, post-market surveillance).
   This is process work, not code work.
4. **Commission per-monitor-model validation** for HAZARD-PROTO-002 before any clinical
   deployment claim against a specific monitor model.
5. **Housekeeping items**, low priority but worth tracking: correct the unverified `21 CFR
   §880.3780` citation in `news2_calculator.py`; create a `CHANGELOG.md` if your release
   process expects one (currently absent).
6. **Do not represent this release as regulatory-cleared or market-authorized** in any
   external communication until REG-001 is formally resolved — the engineering work is
   complete and verified, but "software-ready" and "market-ready" are not the same claim for
   a SaMD product, and this repository's own documentation is careful to keep that
   distinction explicit throughout.

---

*This summary was generated by direct inspection of the repository at commit `13324af` /
tag `v1.0.0`. No claim above is asserted from general knowledge of "what this kind of
product usually looks like" — every technical and regulatory statement traces to a specific
file, test, or prior decision recorded in this project's history.*
