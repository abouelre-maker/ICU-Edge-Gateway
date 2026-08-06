# QMS-001 — Design History File (DHF) & Risk Management File (RMF) Structure (DRAFT)

**Status:** DRAFT — engineering-drafted starting point. **Not a certified QMS document.**
Requires review and adoption by a qualified Quality/Regulatory Affairs function before use
as an actual controlled DHF. This document defines *structure and traceability*, not the
records themselves — most referenced records do not yet exist as controlled documents; they
currently exist as this chat's history, code comments, and test files.

**Prepared:** 2026-08-06, Phase 7, per project owner instruction.

**Depends on REG-001 (open):** this structure is deliberately **modular** so it does not
presuppose the outcome of REG-001 §B.4 (whether Function A ships as exempt CDS, whether
Function B requires a full Class II pathway, or some other scoping). If REG-001 resolves to
"whole product is Class II," Module A folders below simply get absorbed into the standard
DHF instead of staying a separate lightweight track. Do not read the "Function A / Function
B" split below as confirming Function A's exempt status — that is still an open decision per
[REG-001 draft, §B.4](REG-001_Intended_Use_and_CDS_Exemption_Draft.md#b4-conclusion-draft-pending-your-regulatoryLegal-review).

---

## 0. Governing structure

```
DHF Root
├── 00_QMS_GOVERNANCE/
├── 01_DESIGN_INPUTS/
├── 02_DESIGN_OUTPUTS/                 (split A/B — see §3)
├── 03_DESIGN_REVIEWS/
├── 04_VERIFICATION/                    (split A/B — see §3)
├── 05_VALIDATION/
├── 06_RISK_MANAGEMENT_FILE/            (ISO 14971 — see §4; cross-cutting, not split)
├── 07_DESIGN_TRANSFER/
├── 08_DESIGN_CHANGES/
└── 09_POST_MARKET/
```

Rationale for the split at §3/§4: IEC 62304 / 21 CFR 820.30 design-control records are
naturally scoped to what's being built (so Function A and Function B artifacts differ), but
ISO 14971 risk management is scoped to the *system* — a hazard in Function B's waveform
pipeline can still affect a patient outcome mediated through Function A's display, so the
RMF stays a single, unified file (§4) with a module tag per entry rather than being split
into two documents.

---

## 1. 00_QMS_GOVERNANCE/

| Record | Status | Notes |
|---|---|---|
| Quality Manual reference | ❌ Not started | This repo has no QMS of record — CLAUDE.md/docs/ are engineering artifacts, not a controlled QMS |
| Document control procedure (numbering, revision, approval) | ❌ Not started | Every document in this DHF needs a real doc-control ID once adopted — this draft uses filenames only |
| Roles & responsibilities (incl. Clinical Safety Officer) | ❌ Not started | **Blocks QMS-002** — HAZARD-DSP-005's acceptance cannot be formally ratified until this role is designated |
| Design & Development Plan | ❌ Not started | Should reference Phases 4–7 as the de facto plan already executed; needs formalizing, not re-deriving |

---

## 2. 01_DESIGN_INPUTS/

| Record | Current evidence (informal) | Gap |
|---|---|---|
| Intended Use Statement | [REG-001 draft §A](REG-001_Intended_Use_and_CDS_Exemption_Draft.md#part-a--draft-intended-use-statement) | Draft only — needs formal adoption |
| User needs | Implicit in `main.py` description, NEWS2/FHIR feature set | Never formally elicited/documented as "user needs" |
| Clinical requirement: RCP NEWS2 2017 algorithm | [src/domain/services/news2_calculator.py](../src/domain/services/news2_calculator.py) docstring cites ISBN 978-1-86016-693-6 | Adequate — real, cited, external standard |
| Interoperability requirement: HL7 v2.x → FHIR R4 | [src/infrastructure/adapters/hl7v2_adapter.py](../src/infrastructure/adapters/hl7v2_adapter.py), [src/infrastructure/fhir/](../src/infrastructure/fhir/) | Adequate |
| Regulatory requirement set | [REG-001 draft](REG-001_Intended_Use_and_CDS_Exemption_Draft.md) | **Open — REG-001 undecided** |
| Software safety classification (IEC 62304 Class B) | Referenced throughout code comments and CLAUDE.md | Never formally justified via a documented Class A/B/C rationale (IEC 62304 §4.3) — should be added |

---

## 3. 02_DESIGN_OUTPUTS/ and 04_VERIFICATION/ — modular by function

### 3.1 Module A — NEWS2 Scoring / FHIR Reporting (candidate exempt-CDS scope)

| Record | Evidence | Location |
|---|---|---|
| Software Requirements | Docstrings + RCP NEWS2 2017 traceability | [news2_calculator.py](../src/domain/services/news2_calculator.py) |
| Software Design | Domain entities, calculator, FHIR builders | [src/domain/entities/news2_score.py](../src/domain/entities/news2_score.py), [src/infrastructure/fhir/news2_builder.py](../src/infrastructure/fhir/news2_builder.py) |
| Unit Verification | Boundary-condition tests | [tests/unit/test_news2_calculator.py](../tests/unit/test_news2_calculator.py) |
| Regulatory Verification | Advisory-only behavior, no automated action | [tests/regulatory/test_news2_safety.py](../tests/regulatory/test_news2_safety.py) |
| Integration Verification | FHIR Bundle conformance | [tests/integration/test_fhir_bundle.py](../tests/integration/test_fhir_bundle.py), [tests/integration/test_fhir_conformance.py](../tests/integration/test_fhir_conformance.py) |

### 3.2 Module B — Waveform DSP Pipeline (candidate Class II scope, per REG-001 §B.3)

| Record | Evidence | Location |
|---|---|---|
| Software Requirements | Filter specs (notch freq, bandpass ranges per vital type, Hampel params) | [src/domain/services/artifact_rejector.py](../src/domain/services/artifact_rejector.py) |
| Software Design | `BandpassFilter`, `DualNotchFilter`, `HampelFilter`, `VitalSignProcessor` orchestration | [artifact_rejector.py](../src/domain/services/artifact_rejector.py), [signal_processor.py](../src/domain/services/signal_processor.py) |
| Unit Verification | Per-filter attenuation/detection tests | [tests/unit/test_artifact_rejector.py](../tests/unit/test_artifact_rejector.py) |
| Integration Verification | End-to-end HL7 waveform → DSP → output | [tests/integration/test_hl7v2_waveform_pipeline.py](../tests/integration/test_hl7v2_waveform_pipeline.py) |
| **Known open findings** | HAZARD-DSP-005 (accepted residual risk, pending QMS-002), HAZARD-DSP-006 (mitigated) | See §4.2 |

### 3.3 Shared/Core (used by both modules — not split)

HL7 parsing (`hl7v2_adapter.py`), API layer (`api/v1/`), CORS/config (`config.py`),
exception handling (`main.py`). Verified by
[tests/integration/test_api_ingest.py](../tests/integration/test_api_ingest.py),
[tests/integration/test_api_vitals.py](../tests/integration/test_api_vitals.py),
[tests/integration/test_api_health.py](../tests/integration/test_api_health.py).

---

## 4. 06_RISK_MANAGEMENT_FILE/ (ISO 14971) — unified, module-tagged

**This is the successor to the informal "risk register" described in the Phase 5 technical
package.** It does not yet exist as a real controlled file (the Phase 5 doc references
`ICU_Edge_Gateway_Risk_Register.xlsx`, which does not exist in this repository — confirmed
by search; only referenced in prose). Recommend this DHF module becomes the trigger to
actually create that file, using the entries below as the seed content.

### 4.1 Risk Management Plan

Scope: covers Module A and Module B jointly (see §0 rationale). Must define risk acceptability
criteria — not yet documented anywhere in this repo as a standalone artifact (severity ×
probability matrix is referenced as "spreadsheet formulas" in the Phase 5 doc but the
spreadsheet itself doesn't exist here).

### 4.2 Risk Traceability — entries explicitly requested for this draft

| Hazard ID | Description | Module | Status | Evidence / Mitigation | Verifying Test |
|---|---|---|---|---|---|
| **HAZARD-CORS-001** | CORS wildcard (`allow_origins=["*"]`) permitted any origin to receive clinical FHIR data | Shared/Core | ✅ Mitigated | Explicit `CORS_ALLOWED_ORIGINS` allow-list; fails closed on `*` or empty — [config.py](../src/config.py) | [tests/unit/test_config.py](../tests/unit/test_config.py) (10 tests, 100% coverage on `config.py`) |
| **HAZARD-DSP-005** | Bandpass smoothing (0.5 Hz cutoff) reduces Hampel filter's sensitivity to short-duration artifacts in the current Notch→Bandpass→Hampel stage order | Module B | 🟡 **Accepted residual risk — engineering decision 2026-08-06, PENDING formal ratification (QMS-002)** | Stage order deliberately NOT changed; exposure bounded because waveform data is architecturally excluded from NEWS2 scoring (`TestWaveformNeverFeedsNews2Score`) | `tests/integration/test_hl7v2_waveform_pipeline.py::TestKnownArtifactDetectionLimitation` — xfail(strict=True), so any silent change is caught |
| **HAZARD-DSP-006** | filtfilt boundary-padding produces artifact-independent false-positive motion-artifact flags at waveform array edges | Module B | ✅ Mitigated | Edge samples reclassified via group-delay-derived margin (`BandpassFilter.edge_margin_samples()`); filter numerics unchanged; known trade-off (real artifact inside margin is undercounted) explicitly tested, not hidden | `tests/unit/test_artifact_rejector.py::TestBandpassFilterEdgeMarginSamples`, `tests/integration/test_hl7v2_waveform_pipeline.py::TestHazardDsp006EdgeMitigation` |
| HAZARD-DSP-001/002/003 | Notch/bandpass/Hampel filter defects (referenced for completeness — not requested this round, but they're the parents of the DSP-005/006 findings above) | Module B | ✅ Mitigated (pre-existing) | Filter implementations | `tests/unit/test_artifact_rejector.py` (`TestDualNotchFilter`, `TestBandpassFilter`, `TestHampelFilter`) |
| HAZARD-DSP-004 | Dangling `HAZARD-DSP-004` reference in source with no corresponding control | Shared docs | ✅ Resolved | Docstring corrected to accurate `001/002/003` range | N/A (documentation-only; no test applicable) |
| HAZARD-PROTO-002 | HL7 v2.x has no standardized waveform sampling-rate field; default table requires per-monitor-model validation | Module B | 🔲 **Open — not started, needs external device data** | Documented default table + explicit OBX-6 override path | `tests/integration/test_hl7v2_waveform_pipeline.py::TestWaveformCapableTypeInvariant` (only guards internal consistency, not real-world rate accuracy) |
| HAZARD-WAVE-001 | Partially-parseable waveform array silently truncated/reindexed would corrupt sample timing | Module B | ✅ Closed | Fail-whole-array rule in `_parse_numeric_array` | `tests/integration/test_hl7v2_adapter.py::test_corrupted_waveform_sample_rejects_whole_array` |

**Not fabricated:** every row above is either a hazard ID you named explicitly in this
conversation, or one I found already referenced in existing code/docs during this session's
work (DSP-004, PROTO-002, WAVE-001, DSP-001/002/003) — I did not invent new hazard IDs for
this table.

### 4.3 Overall Residual Risk Evaluation

Not yet performed as a formal QMS activity — requires the risk acceptability criteria from
§4.1 and, per your framing, real ratification of HAZARD-DSP-005 (QMS-002) before this section
can be considered complete.

---

## 5. 03_DESIGN_REVIEWS/, 05_VALIDATION/, 07_DESIGN_TRANSFER/, 08_DESIGN_CHANGES/, 09_POST_MARKET/

All ❌ **not started** — flagging explicitly rather than filling with placeholder content
that could be mistaken for real records:

- **Design Reviews**: this conversation's back-and-forth (plan → approval → implementation)
  is arguably informal design review evidence for the Phase 6 hazards, but has not been
  captured in a form a QMS would recognize as a documented review record.
- **Validation**: no clinical validation (as opposed to verification) has occurred —
  everything in this repo is unit/integration test *verification* against specifications,
  not validation against actual clinical use.
- **Design Transfer**: no manufacturing/deployment transfer process defined.
- **Design Changes**: the commit history (`7aa2531`, `bdfd370`, `7842ec7`, `b166b17`) is a
  reasonable *input* to a formal change-control record but isn't itself one — no change-
  control form/approval trail exists outside git.
- **Post-Market**: no post-market surveillance process defined (complaint handling, adverse
  event reporting, etc.) — entirely out of scope until a marketing/classification decision
  is made under REG-001.

---

## 6. Immediate next actions this structure implies

1. **QMS-002** cannot be closed until §00_QMS_GOVERNANCE's "Roles & responsibilities" item
   names an actual Clinical Safety Officer — currently no such role exists in this project's
   record.
2. **REG-001's decision** determines whether §3.1/§3.2's A/B split survives as real
   structure or collapses into one Class II track for design-control purposes (the RMF in
   §4 stays unified either way).
3. The Phase 5 doc's referenced `ICU_Edge_Gateway_Risk_Register.xlsx` does not exist in this
   repository. Recommend either creating it from §4.2 above, or formally designating this
   markdown file (kept under version control, unlike a spreadsheet) as the RMF's authoritative
   form going forward — your call, flagging the discrepancy rather than silently picking one.
