# ICU Edge-to-FHIR Interoperability Gateway
## Phase 5 Technical Package — Verified Baseline, Gap Analysis, SAD, Traceability Matrix, HL7↔FHIR Specification

**Document status:** Draft for internal engineering and regulatory review.
**Basis:** This document is derived exclusively from the source code actually present in the
uploaded project (`icu_full_code.txt`, 37 source/test files, reconstructed and executed).
No claim below is asserted without a corresponding line of code, test result, or explicit
"NOT YET IMPLEMENTED" flag. Where information could not be verified from the artifacts
provided, it is marked **UNVERIFIED** rather than assumed.

---

## 0. Verification Method

The concatenated code dump was parsed back into its real package structure
(`src/`, `tests/unit`, `tests/integration`, `tests/regulatory`), dependencies were installed
from the project's own `requirements.txt` / `requirements-dev.txt`, and the test suite was
executed with coverage instrumentation. This is a live, reproducible result, not a restatement
of the project brief.

```
299 tests collected
299 passed, 12 warnings in 4.29s
TOTAL statement coverage: 90% (915 / 1021 statements — 89.6%, rounds to 90)
```

This **confirms** the "299 passing tests" and "~90% coverage" figures in the project brief.
It does **not** by itself confirm production readiness — coverage percentage measures lines
executed, not clinical correctness of every branch, and one high-value pipeline is essentially
untested end-to-end (see Finding 1).

Per-module coverage (from the executed run):

| Module | Stmts | Miss | Cover | Notes |
|---|---:|---:|---:|---|
| `api/v1/health.py` | 23 | 0 | 100% | |
| `api/v1/ingest.py` | 44 | 1 | 98% | |
| `api/v1/vitals.py` | 81 | 9 | 89% | |
| `domain/entities/device_context.py` | 29 | 1 | 97% | |
| `domain/entities/news2_score.py` | 51 | 1 | 98% | |
| `domain/entities/patient_context.py` | 16 | 1 | 94% | |
| `domain/entities/vital_sign.py` | 48 | 4 | 92% | |
| `domain/interfaces/i_filter_strategy.py` | 6 | 0 | 100% | |
| `domain/services/artifact_rejector.py` | 84 | 5 | 94% | |
| `domain/services/news2_calculator.py` | 133 | 2 | 98% | |
| **`domain/services/signal_processor.py`** | **58** | **27** | **53%** | **Waveform DSP orchestration path untested — see Finding 1** |
| `domain/services/vitals_orchestrator.py` | 59 | 5 | 92% | |
| `infrastructure/adapters/hl7v2_adapter.py` | 195 | 30 | 85% | Vendor-code edge branches, see §4 |
| `infrastructure/fhir/bundle_assembler.py` | 51 | 6 | 88% | |
| `infrastructure/fhir/news2_builder.py` | 32 | 1 | 97% | |
| `infrastructure/fhir/observation_builder.py` | 74 | 5 | 93% | |
| `main.py` | 37 | 8 | 78% | Startup/uvicorn entrypoint lines — expected, benign |

---

## 1. Critical Findings (must be resolved before "production-ready" is claimed)

### Finding 1 — Waveform DSP pipeline is not reachable from the primary HL7 ingestion path (P0)

The project brief lists "real-time artifact rejection via dual notch filters and Hampel outlier
detection" as a core invariant of the HL7-fed pipeline. The code confirms the filters exist and
are individually correct (`DualNotchFilter`, `BandpassFilter`, `HampelFilter` — all unit-verified
in `tests/unit/test_artifact_rejector.py`, meeting the stated ≥95% RMS attenuation and QRS-preservation
requirements). However:

- `src/infrastructure/adapters/hl7v2_adapter.py`, `_parse_obx()`, explicitly **skips** OBX value types
  `NA` and `ED` — these are the HL7 v2.x waveform-carrying types — with the comment
  *"waveform data — not supported in v1.0... Phase 4 waveform streaming support"*.
- `src/domain/services/signal_processor.py` (`VitalSignProcessor.process`) only runs
  notch → bandpass → Hampel when `sample.waveform is not None`. Since the HL7 adapter never
  populates `waveform`, this branch (lines 118–157) is **never exercised when data arrives via
  `POST /api/v1/ingest`** — the primary bedside-monitor ingestion route.
- Confirmed independently by coverage: `signal_processor.py` sits at 53%, and the missing lines
  are exactly the notch/bandpass/Hampel orchestration block.
- The waveform path *is* reachable — but only via `POST /api/v1/vitals` (the JSON-normalized
  endpoint), where a caller can supply `waveform` + `sampling_rate_hz` directly.

**Implication:** The claim "biomedical signal processing" is applied to "HL7 v2.x bedside monitor
feeds" is currently **not true end-to-end**. The two capabilities exist but are architecturally
disconnected. This is the single highest-priority engineering item for Phase 5/6 — see §6, Step 1.

### Finding 2 — CORS is wide open (`allow_origins=["*"]`)

`src/main.py` sets `allow_origins=["*"]`. The code already contains the developer's own note:
*"In production, restrict allow_origins to specific EHR endpoints."* For a gateway that carries
patient identifiers and vital signs, this must be closed before any real deployment — flagged
as self-acknowledged technical debt, not yet resolved.

### Finding 3 — Regulatory citations in source comments are engineering design assumptions, not regulatory determinations

Docstrings throughout the codebase assert *"FDA CDS Non-Device Exemption (21 CFR §880.3780)
applies"* and *"Health Canada SaMD Class II."* These are reasonable engineering assumptions for
an advisory-only, clinician-reviewed scoring display — the code's behavior (NEWS2 output is
never used to trigger automated action, and every FHIR Observation carries an explicit
advisory-only extension/note) is consistent with that intent. But **whether this software
actually qualifies for the exemption, and how it is classified in Canada, KSA, UAE, and Egypt, is
a regulatory determination that must be made by qualified regulatory affairs / legal counsel
against the current, in-force text of each jurisdiction's rules** — it cannot be self-certified
by a code comment, and I have not independently verified current FDA/Health Canada/SFDA/MOHAP/EDA
requirements against this build. Treat every "FDA CDS" / "Class II" comment in the code as a
**design intent marker for engineering**, not as a completed regulatory submission artifact.

### Finding 4 (minor, non-blocking) — Code hygiene items for configuration control

- Several source comments are written in Arabic embedded inside otherwise English-only,
  IEC 62304-styled docstrings (`artifact_rejector.py`). On inspection, the underlying engineering
  decisions they describe are sound and traceable to real declared requirements (e.g., the
  `SYSTOLIC_BP` physiological ceiling of 300 mmHg is deliberately set above the NEWS2-scoreable
  220 mmHg threshold precisely so a clinically valid hypertensive-emergency reading is never
  wrongly excluded from scoring — verified by `test_sbp_220_is_out_of_bounds`). The content is not
  the problem; the **mixed-language, non-standard comment format is** — a regulated codebase under
  IEC 62304 configuration management should have a single documented comment-language policy so
  every reviewer/auditor can read every rationale without translation.
- `infrastructure/fhir/observation_builder.py` re-imports `from datetime import timezone` at the
  bottom of the file (with `# noqa: E402`) instead of at the top. Functionally harmless (verified:
  93% coverage, all tests pass) but should be cleaned up — it reads like a patched-in fix rather
  than a considered import block, which is exactly the kind of thing a design-history-file reviewer
  will ask about.

None of the above are safety defects in the *scoring logic itself*. The NEWS2 algorithm
(`news2_calculator.py`) was checked line-by-line against the RCP NEWS2 2017 scoring table
(respiratory rate, SpO2 Scale 1/Scale 2, supplemental O2, systolic BP, heart rate — including the
non-monotonic 41–50 bpm band, AVPU, and temperature) and matches the published table exactly,
including the correct risk-level priority order (HIGH ≥7 → MEDIUM 5–6 → LOW_MEDIUM on any single
parameter = 3 → LOW 1–4 → NORMAL 0).

---

## 2. Software Architecture Description (SAD)

### 2.1 Architectural style

Layered / hexagonal (ports-and-adapters), enforced by `pyproject.toml`'s `pythonpath = ["src"]`
and by import direction discipline observed throughout the code:

```
┌─────────────────────────────────────────────────────────────────┐
│  API Layer (src/api)                                             │
│   GET  /health              — liveness/readiness                 │
│   POST /api/v1/ingest       — raw HL7 v2.x ORU^R01 (text/plain)   │
│   POST /api/v1/vitals       — normalized JSON vitals              │
├─────────────────────────────────────────────────────────────────┤
│  Infrastructure Layer (src/infrastructure)                        │
│   adapters/hl7v2_adapter.py      — HL7 v2.x → VitalSignSample     │
│   fhir/observation_builder.py    — ProcessedVitalSign → FHIR Obs  │
│   fhir/news2_builder.py          — NEWS2Score → FHIR Obs (7 comp) │
│   fhir/bundle_assembler.py       — assembles the FHIR R4 Bundle   │
├─────────────────────────────────────────────────────────────────┤
│  Domain Layer (src/domain)  — no framework/infra dependencies     │
│   entities/   vital_sign, patient_context, device_context,        │
│               news2_score                                        │
│   interfaces/ i_filter_strategy.py  (Strategy contract)           │
│   services/   artifact_rejector.py  (DualNotch/Bandpass/Hampel/   │
│               PhysiologicalBoundsChecker)                         │
│               signal_processor.py   (4-stage DSP orchestration)   │
│               news2_calculator.py   (RCP NEWS2 2017 scoring)      │
│               vitals_orchestrator.py (Facade: DSP → NEWS2)        │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Design patterns actually in use (verified in code, not aspirational)

| Pattern | Where | Purpose |
|---|---|---|
| Strategy | `IFilterStrategy` + `DualNotchFilter`/`HampelFilter` | Swappable DSP filter implementations |
| Adapter | `HL7v2Adapter` | Isolates `hl7apy` (SOUP) from domain entities |
| Builder | `ObservationBuilder`, `NEWS2ObservationBuilder` | Isolates FHIR schema knowledge from domain |
| Facade | `VitalsOrchestrator.analyse()` | Single entry point: DSP → NEWS2 → result |
| Factory Method | `main.create_app()` | Deterministic, testable ASGI app construction |

### 2.3 Data flow (as implemented today)

```
POST /api/v1/ingest (raw HL7)
  → HL7v2Adapter.parse()            [numeric/AVPU/O2 OBX only; NA/ED waveform OBX skipped]
  → VitalsOrchestrator.analyse()
      → VitalSignProcessor.process()   [Stage 1 bounds check only — no waveform present]
      → NEWS2Calculator.calculate()
  → BundleAssembler.assemble()      → FHIR R4 Bundle (collection)

POST /api/v1/vitals (normalized JSON, optional waveform[] + sampling_rate_hz)
  → VitalsOrchestrator.analyse()
      → VitalSignProcessor.process()   [Stages 1–4 run IF waveform supplied — currently 0% test-exercised]
      → NEWS2Calculator.calculate()
  → BundleAssembler.assemble()      → FHIR R4 Bundle (collection)
```

### 2.4 Error-handling model

Two global FastAPI exception handlers in `main.py`:
- `ValueError` → HTTP 422 with a domain-readable message (no stack trace leakage).
- `Exception` (catch-all) → HTTP 500, generic message, full detail logged server-side via
  `structlog`.

Per-observation failures inside `BundleAssembler.assemble()` do not abort the whole Bundle — a
failed FHIR Observation is replaced with an `OperationOutcome` entry so partial results are still
returned and auditable (`_build_error_entry`).

---

## 3. Traceability Matrix (Hazard / Requirement → Source → Verifying Test)

Extracted directly from in-code `ISO 14971 HAZARD-*` and `IEC 62304 REQ-*` tags and cross-checked
against the executed, passing test suite.

| Hazard / Req ID | Risk Description | Source | Verifying Test(s) |
|---|---|---|---|
| HAZARD-NEWS2-001/002/003 | Incorrect / partial / manipulated NEWS2 score | `news2_calculator.py`, `news2_score.py` | `tests/regulatory/test_news2_safety.py`, `tests/unit/test_news2_calculator.py` |
| HAZARD-SPO2-001 | Scale 1 applied to a COPD (hypercapnic) patient underscores by up to 3 pts | `news2_calculator.py::_score_spo2`, `patient_context.py` | `TestSpO2Scale1Scoring`, `TestSpO2Scale2Scoring` |
| HAZARD-RR-001 | Missed respiratory depression | `_score_respiratory_rate` | `TestRespiratoryRateScoring` boundary set |
| HAZARD-SBP-001 | Missed hypotensive shock / hypertensive emergency | `_score_systolic_bp` | `TestSystolicBPScoring` |
| HAZARD-HR-001 | Non-monotonic 41–50 bpm band regression | `_score_heart_rate` | `TestHeartRateScoring` (explicit 41/50 boundary case) |
| HAZARD-CON-001 | Missed new confusion / non-alert state | `_score_consciousness`, `AVPULevel` | `TestConsciousnessScoring` |
| HAZARD-TEMP-001 | Missed hypothermia/hyperthermia | `_score_temperature` | `TestTemperatureScoring` |
| HAZARD-O2-001 | O2-masking of true SpO2 reserve | `_score_supplemental_o2` | `TestSupplementalO2Scoring` |
| HAZARD-TIME-001 | Naive timestamps corrupt audit trail | `vital_sign.py.__post_init__`, `api/v1/vitals.py` validator | integration + unit fixture assertions |
| HAZARD-PROTO-001 | Vendor dialect misidentification silently drops OBX | `hl7v2_adapter.py` vendor maps | `tests/integration/test_hl7v2_adapter.py` |
| HAZARD-FHIR-001/002/003 | Wrong LOINC code / score encoding / missing Bundle.timestamp | `observation_builder.py`, `news2_builder.py`, `bundle_assembler.py` | `tests/integration/test_fhir_bundle.py`, `test_fhir_conformance.py` |
| HAZARD-ARCH-001 | Wrong pipeline execution order (NEWS2 before DSP cleaning) | `vitals_orchestrator.py` | `tests/integration/*` (order asserted implicitly by orchestration test) |
| HAZARD-BOUNDS-001 | Instrument-error values silently included in scoring | `PhysiologicalBoundsChecker` | `TestPhysiologicalBoundsChecker` |
| HAZARD-DSP-001/002/003 | Notch/bandpass/Hampel filter defects | `artifact_rejector.py` (filters, unit-level) | `tests/unit/test_artifact_rejector.py` |
| **HAZARD-DSP-00x (integration)** | **Waveform DSP orchestration wiring** | `signal_processor.py` lines 118–157 | **No integration test currently exercises this path — OPEN** |

The last row is the one open item in this matrix and corresponds directly to Finding 1.

---

## 4. HL7 v2.x → FHIR R4 Mapping Specification (as implemented)

### 4.1 Supported input

- HL7 v2.3 – v2.8, message type `ORU^R01`.
- OBX value types accepted: `NM` (numeric), `ST` (string, used for AVPU), `SN` (structured numeric,
  first component extracted). **`NA`/`ED` (waveform) are parsed by the message but the segment is
  discarded — see Finding 1.**
- OBX-11 result status: only `F` (Final) and `P` (Preliminary) accepted; `C`/`W` rejected.
- Vendor dialects with explicit code tables: Philips IntelliVue, GE CARESCAPE, Dräger Infinity,
  Mindray Beneview, Nihon Kohden; unrecognized MSH-3 falls back to `GENERIC` (LOINC-only).

### 4.2 Observation code mapping (LOINC primary, SNOMED CT secondary, UCUM units)

| Vital Sign | LOINC | SNOMED CT | UCUM |
|---|---|---|---|
| Heart Rate | 8867-4 | 364075005 | `/min` |
| Respiratory Rate | 9279-1 | 86290005 | `/min` |
| SpO2 | 59408-5 (alt. 2708-6) | 431314004 | `%` |
| Systolic BP | 8480-6 | 271649006 | `mm[Hg]` |
| Diastolic BP | 8462-4 | 271650006 | `mm[Hg]` |
| Temperature | 8310-5 | 276885007 | `Cel` |
| Consciousness (AVPU) | 67775-7 / 76270-8 | per-level (248234008 Alert … 40917007 Clouded consciousness) | n/a (`valueCodeableConcept`) |
| Supplemental O2 | 57834-7 / 3151-8 | 371825009 | n/a (`valueBoolean`) |

NEWS2 composite Observation: SNOMED CT `1239842005` ("National Early Warning Score 2"), total
score in `valueInteger` (never float, to prevent rounding corruption of the risk-level derivation),
with all 7 component sub-scores emitted individually under `Observation.component[]` for full
retrospective audit, plus a `v3-ObservationInterpretation` code (N/L/A/H/HH) and three custom
extensions: software version, NEWS2 risk level, and the FDA-CDS advisory-only flag.

### 4.3 Bundle structure

`Bundle.type = "collection"`, one Bundle per HL7 message or API call. Entries: optional `Device`,
0..N vital-sign `Observation`s, optional `NEWS2` composite `Observation`, and any
`OperationOutcome` entries for individual build failures. `Bundle.note[]` carries the full DSP/parse
audit trail (pipeline warnings) for traceability.

---

## 5. Honest Regulatory Positioning

The codebase is **engineered with regulatory structure in mind** (IEC 62304 §5.x traceability tags,
ISO 14971 hazard tags, advisory-only FHIR extensions, deterministic/testable scoring). That is a
genuinely strong starting position relative to typical early-stage SaMD codebases. It is **not**,
by itself, a completed regulatory submission for any of the target markets, because:

- FDA 21 CFR 820.30 requires a live, maintained Design History File, formal design reviews, and
  verification/validation records under an actual Quality Management System — not comments in
  source files.
- ISO 14971 requires a maintained Risk Management File (risk register, not docstrings) with
  residual-risk sign-off by a responsible person.
- Health Canada, Saudi SFDA, UAE MOHAP/DHA, and Egyptian EDA each have their own device
  classification and submission processes, which are IMDRF-aligned in structure but differ in
  specific documentation and local-representative requirements. I have not verified the current,
  in-force requirements for any of these four jurisdictions against this build, and I'm not going
  to fabricate citation numbers I can't confirm — this needs a regulatory affairs specialist (or a
  targeted web-verified research pass, which I can run if you want it as its own task) before any
  jurisdiction-specific claim is made in a pitch deck or submission.
- A cybersecurity/SBOM package (FDA premarket cybersecurity expectations) and a post-market
  surveillance plan do not yet exist in the artifacts provided.

None of this blocks continued engineering work. It does mean "enterprise pitch decks" claiming
regulatory clearance would be inaccurate to produce right now — a pitch deck describing the
*engineering maturity and regulatory-readiness posture* (accurately) is appropriate today; a pitch
deck implying clearance is not, and I won't draft the latter.

---

## 6. Execution Plan to Close the Gaps (phased)

**Step 1 — Close the waveform integration gap (P0, blocks the DSP claim).**
Decide the real target: does Phase 5/6 need HL7 waveform ingestion (parsing `NA`/`ED` OBX
segments into `VitalSignSample.waveform`), or is the JSON `/api/v1/vitals` waveform path the
intended production route for now? Either is defensible — but the answer must be written down
and the docs/marketing claims must match it exactly.

**Step 2 — Add the missing integration test.**
Whichever path is chosen, add an integration test that pushes a realistic waveform (synthetic
ECG-like signal with injected 50/60 Hz interference and a motion-artifact spike) through the full
`VitalsOrchestrator.analyse()` call and asserts the FHIR Observation's
`dsp-outlier-count` extension and pipeline notes reflect real filtering — closing the 53% coverage
gap in `signal_processor.py` with a real assertion, not a coverage-chasing stub.

**Step 3 — Lock down CORS** to explicit EHR/consumer origins before any non-lab deployment.

**Step 4 — Normalize code comments to a single language policy** (recommend English-only for the
regulated `src/` tree) and remove the dead-code-looking bottom-of-file import in
`observation_builder.py`.

**Step 5 — Stand up the actual Risk Management File and Design History File** as living documents
(spreadsheet/PLM tool, not source comments) that reference the hazard IDs already in the code —
the traceability matrix in §3 is the starting skeleton for this.

**Step 6 — Engage regulatory affairs** for a real classification determination per target market
before any commercial or clearance claim is made externally.

**Step 7 — Security/SBOM pass**: `pip-audit` and `bandit` are already declared in
`requirements-dev.txt` but I did not find evidence they've been run in the artifacts provided —
run them and remediate findings as part of the audit trail.

---

## 7. Phase 5 Closure Note (2026-08-06)

This section records what changed after this document's initial draft, closing out the
items opened in §1 and §6.

**Finding 1 (P0 — waveform DSP pipeline disconnected from HL7 ingestion): CLOSED.**
`hl7v2_adapter.py` now parses NA (Numeric Array) and ED (Encapsulated Data) OBX segments
into `VitalSignSample.waveform`, wired end-to-end through `VitalsOrchestrator` to the DSP
pipeline. Verified by actually running the suite, not by inspection alone:

```
Before: 299 passed, 90% total coverage, signal_processor.py at 53%
After:  311 passed, 1 xfailed, 91% total coverage, signal_processor.py at 81%
```

New design decisions made explicit in code and now tracked as **HAZARD-PROTO-002** (open,
requires per-monitor-model validation before clinical use — HL7 v2.x has no standardized
sampling-rate field) and **HAZARD-WAVE-001** (closed — fail-whole-array rule on any
unparseable sample).

**New finding discovered during this work — HAZARD-DSP-005:** empirically confirmed that in
the current Notch → Bandpass → Hampel stage order, `HampelFilter` loses local-outlier
sensitivity to short-duration artifacts once they've passed through the 0.5 Hz-cutoff
bandpass stage (reproducible even at 200x signal amplitude). `HampelFilter` itself is
confirmed correct in isolation (pre-bandpass) — this is a stage-ordering interaction, not a
defect in the filter. **Decision (recorded 2026-08-06, this project's engineering lead): do
not reorder the DSP pipeline stages; accept as a documented residual risk for the current
release.** Rationale for the acceptance being reasonable: NEWS2 scoring is verified
architecturally decoupled from waveform data (the placeholder scalar on waveform-only samples
is always excluded from scoring by the pre-existing `PhysiologicalBoundsChecker`, regression-
guarded by `TestWaveformNeverFeedsNews2Score`), so today's actual clinical exposure is bounded
to the `cleaned_waveform` / `dsp-outlier-count` FHIR extension under-reporting artifact
presence — not to the NEWS2 score itself. Severity must be re-escalated if any future feature
derives scoring or clinical display directly from waveform data. This chat-recorded decision
is **provisional pending formal ratification by the organization's designated Clinical Safety
/ Risk Management responsible person** before being cited in a regulatory submission (see
QMS-002 in the risk register).

**A second, separate finding — HAZARD-DSP-006 — was also identified** (a persistent,
artifact-*independent* pair of flagged samples at the tail of every filtered waveform array,
an apparent `filtfilt` edge/padding effect, opposite failure direction from DSP-005: false-
positive rather than false-negative). **This has not yet been addressed by the project owner**
and is tracked separately as "Open — Awaiting Decision" — it is not covered by the HAZARD-
DSP-005 acceptance.

**Formal risk register:** all of the above, plus every hazard ID referenced elsewhere in this
document, is now maintained as a structured ISO 14971-style workbook —
`ICU_Edge_Gateway_Risk_Register.xlsx` — with Severity × Probability risk indices (as live
spreadsheet formulas, not hardcoded), mitigation evidence citing exact test names, and a
disclaimer that these ratings are an engineering-drafted starting point requiring qualified
clinical-safety sign-off, not a certified determination. Treat that workbook, not the
traceability table in §3 above, as the authoritative, living version going forward.

**Still open, unchanged from §1/§6:** CORS wildcard (`HAZARD-CORS-001`), regulatory
classification determination (`REG-001`), and standing up a real QMS-hosted Design History
File (`QMS-001`) — all now tracked in the risk register's "Process Items" sheet rather than
only in this document's prose.

### Phase 5 — Officially Closed (2026-08-06)

The project owner formally closed Phase 5 on 2026-08-06. Closure basis: the P0 finding is
resolved and verified (311 passed, 1 xfailed, 91% total coverage), and every hazard
identified during this phase is now tracked in a living ISO 14971-style Risk Register with
an explicit decision recorded for each — including the one deliberately accepted as residual
risk (HAZARD-DSP-005) rather than mitigated by code change.

**Carried into the Phase 6 backlog**, per the project owner's explicit instruction plus two
items included by the same "genuinely still open, non-blocking" reasoning (flagged below for
confirmation rather than silently assumed):

| ID | One-line description | Source |
|---|---|---|
| HAZARD-DSP-006 | Artifact-independent flagged samples at waveform-array tail (filtfilt edge effect) | Named explicitly by project owner |
| HAZARD-CORS-001 | CORS wildcard in main.py | Named explicitly by project owner |
| REG-001 | Regulatory classification unverified per target market | "Regulatory/QMS items," named by project owner |
| QMS-001 | No live QMS-hosted Design History File / Risk Management File | "Regulatory/QMS items," named by project owner |
| QMS-002 | HAZARD-DSP-005 acceptance needs formal Clinical Safety Officer ratification | "Regulatory/QMS items," named by project owner |
| HAZARD-PROTO-002 | Waveform sampling-rate default table needs per-monitor-model validation | Included by inference — same "open, non-blocking" category; not explicitly named, confirm or remove |
| HAZARD-DSP-004 | Undefined hazard-ID reference in source (documentation gap) | Included for internal consistency — its Status field already read "Open - Requires Action" before this closure; not explicitly named, confirm or remove |

Full detail, including the phase tag on every register row, is in the risk register
workbook's new "Phase Sign-Off Log" sheet and "Phase Assignment" column.


## 8. Resume Checkpoint

```
PROJECT: ICU Edge Gateway (icu-edge-gateway v0.1.0)
PHASE 5: OFFICIALLY CLOSED by project owner, 2026-08-06.
  - P0 finding (waveform DSP disconnected from HL7) CLOSED. 311 passed, 1 xfailed,
    91% total coverage, signal_processor.py at 81% (was 53%). Verified by actually
    running the suite.
  - Formal ISO 14971-style Risk Register established: 24 hazard entries + 3 process
    items, all with recorded decisions. Authoritative file:
    ICU_Edge_Gateway_Risk_Register.xlsx.
  - HAZARD-DSP-005 (Hampel sensitivity loss after bandpass): accepted as residual
    risk per engineering decision 2026-08-06; DSP stage order NOT changed; pending
    formal Clinical Safety Officer ratification (QMS-002).

PHASE 6 BACKLOG (opening items, all non-blocking for Phase 5 closure):
  - HAZARD-DSP-006 (filtfilt edge artifact, false-positive direction) - awaiting triage
  - HAZARD-CORS-001 (CORS wildcard in main.py)
  - HAZARD-PROTO-002 (waveform sampling-rate default table - per-monitor-model validation)
  - HAZARD-DSP-004 (undefined hazard-ID reference - documentation gap)
  - REG-001 (regulatory classification unverified per target market)
  - QMS-001 (no live QMS-hosted Design History File / Risk Management File)
  - QMS-002 (HAZARD-DSP-005 acceptance needs formal ratification)

NEXT SESSION START POINT: Phase 6 kickoff - prioritize the backlog above (none are
  code-blocking; all are pre-deployment or pre-regulatory-submission gates).
```

