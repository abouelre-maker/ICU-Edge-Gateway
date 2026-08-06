# REG-001 — Intended Use Statement & FDA CDS Non-Device Exemption Analysis (DRAFT)

**Status:** DRAFT — engineering-drafted starting point, same category as the Phase 5 Risk
Register. **Not a legal or regulatory determination.** Requires review and sign-off by
qualified Regulatory Affairs / legal counsel before use in any submission, labeling, or
marketing claim.

**Prepared:** 2026-08-06, per project owner instruction (Phase 7 kickoff, REG-001).
**Basis:** Direct inspection of the current codebase (commit `b166b17` and prior) — every
factual claim below cites a specific file/line. No claim is asserted from general knowledge
of "what this kind of product usually does."

---

## Part A — Draft Intended Use Statement

### A.1 Device / Software Name

ICU Edge-to-FHIR Interoperability Gateway ("ICU Edge Gateway"), v1.0.0
— per [src/main.py:51](../src/main.py#L51).

### A.2 Description of Function

The software is a middleware gateway that:

1. Ingests HL7 v2.x ORU^R01 messages (or pre-normalized JSON) from ICU bedside monitors —
   [src/api/v1/ingest.py](../src/api/v1/ingest.py), [src/api/v1/vitals.py](../src/api/v1/vitals.py).
2. Parses scalar vital sign observations (heart rate, respiratory rate, SpO₂, systolic/
   diastolic blood pressure, temperature, AVPU consciousness level, supplemental O₂ status)
   — [src/infrastructure/adapters/hl7v2_adapter.py](../src/infrastructure/adapters/hl7v2_adapter.py).
3. **Separately**, parses continuous waveform channels (ECG, plethysmograph, etc., via HL7
   NA/ED OBX segments) and runs them through a three-stage digital signal processing
   pipeline: 50/60 Hz notch filtering, frequency-band-specific Butterworth bandpass
   filtering, and Hampel-filter motion-artifact rejection —
   [src/domain/services/signal_processor.py](../src/domain/services/signal_processor.py),
   [src/domain/services/artifact_rejector.py](../src/domain/services/artifact_rejector.py).
4. Calculates a NEWS2 (National Early Warning Score 2, RCP 2017) total score and per-
   parameter sub-scores **from the scalar vital signs only** — the waveform-derived data is
   architecturally excluded from this calculation, enforced by
   `PhysiologicalBoundsChecker` and regression-tested by
   `TestWaveformNeverFeedsNews2Score` —
   [src/domain/services/news2_calculator.py](../src/domain/services/news2_calculator.py),
   [tests/integration/test_hl7v2_waveform_pipeline.py](../tests/integration/test_hl7v2_waveform_pipeline.py).
5. Returns a FHIR R4 Bundle containing: the NEWS2 total score, seven per-parameter
   component Observations, and (when present) the cleaned waveform data — all served over a
   REST API with **no automated action taken on the result** —
   [src/infrastructure/fhir/bundle_assembler.py](../src/infrastructure/fhir/bundle_assembler.py),
   [src/infrastructure/fhir/news2_builder.py](../src/infrastructure/fhir/news2_builder.py).

**IMPORTANT — this is two distinguishable software functions, not one.** See §B.2 for why
this matters to the exemption analysis.

### A.3 Intended Use / Indications for Use (draft language)

> The ICU Edge Gateway is intended to convert vital sign data received from compatible ICU
> bedside monitoring equipment via HL7 v2.x into FHIR R4-conformant resources, and to
> calculate and display the NEWS2 early warning score and its component sub-scores as a
> reference aid for use by qualified healthcare professionals monitoring adult inpatients.
> The software does not provide a diagnosis, does not recommend a specific treatment, and
> does not initiate any automated clinical action. All NEWS2 output is advisory only and
> requires independent clinical judgment before any care decision is made.

This draft is a starting point for your Regulatory Affairs function, not a finished
Indications for Use statement suitable for a submission.

### A.4 Intended User

Qualified healthcare professionals (nurses, physicians) in an inpatient/ICU setting,
consistent with the NEWS2 algorithm's design for use by trained clinical staff (RCP NEWS2
2017). The API itself has no user-facing UI in this codebase — it is consumed by an
upstream EHR or clinical display system, per [src/main.py:61-64](../src/main.py#L61)
(contact metadata references an EHR integration context) and the `/api/v1/ingest`,
`/api/v1/vitals` endpoint design.

**Open item:** nothing in the code enforces or verifies that only credentialed clinical
staff can consume the API output — this is presumably a deployment/access-control
responsibility outside this repository. Confirm and document where that control lives.

### A.5 Intended Patient Population

**Gap identified, not previously flagged in the Phase 5/6 record:** RCP NEWS2 2017 is
validated for **adult** patients only and is explicitly not intended for use in pregnancy,
pediatric patients, or certain other populations without modification. The codebase's
`PhysiologicalBoundsChecker` bounds
([src/domain/services/artifact_rejector.py:138-146](../src/domain/services/artifact_rejector.py#L138))
are generic physiological range checks (e.g., HR 20–250 bpm) and **do not enforce an adult
population restriction** — a pediatric HR of 140 bpm, for instance, would pass bounds
checking and be scored by an algorithm not validated for that population.

This is a genuine population-scope gap between the intended use (adult NEWS2) and what the
software technically accepts. It should be resolved either by (a) adding an explicit
population/age guard in code, or (b) documenting it as a deployment-time/workflow control
(e.g., only connected to adult ICU beds) with that control named explicitly in the
Intended Use Statement's limitations section. Flagging for your decision — this is not
something I should silently code around.

### A.6 Environment of Use

Hospital ICU setting; software-only middleware (no physical device component); deployed as
an ASGI application (`uvicorn`, [src/main.py:146-154](../src/main.py#L146)) between bedside
monitors (via HL7) and downstream EHR/FHIR-consuming systems.

### A.7 Contraindications / Limitations (draft)

- Not intended for use as the sole basis for a clinical diagnosis or treatment decision.
- Not intended for pediatric, pregnant, or non-adult-validated populations (see §A.5 gap).
- Not intended to replace direct clinical observation of the patient.
- Waveform-derived data (`cleaned_waveform`) is provided for display/audit purposes and is
  explicitly excluded from NEWS2 scoring — it must not be used as an independent diagnostic
  signal without further clinical validation, per the open residual risks HAZARD-DSP-005 and
  HAZARD-DSP-006 in the risk register.
- Not validated for use with monitor models whose actual waveform sampling rate has not been
  confirmed against the documented default table (HAZARD-PROTO-002 — still open).

---

## Part B — FDA Clinical Decision Support (CDS) Non-Device Exemption Checklist

### B.1 Legal basis (correction to an in-code citation)

The current codebase cites the exemption as **"21 CFR §880.3780"** in
[src/domain/services/news2_calculator.py:15](../src/domain/services/news2_calculator.py#L15).
**This citation could not be verified and should be checked against your regulatory
counsel's records before further use** — the CDS non-device exemption is a statutory
provision, not a CFR part: it derives from the 21st Century Cures Act §3060(a) (2016),
codified at **FD&C Act §520(o)(1)(E)**, with FDA's current interpretation in the September
2022 final guidance *"Clinical Decision Support Software."* If `880.3780` refers to
something else your regulatory function is tracking, please reconcile — I'm flagging the
mismatch rather than silently repeating or silently correcting a regulatory citation I
cannot independently verify.

### B.2 Critical framing: evaluate as two separate software functions

FDA's CDS guidance directs that each **distinct software function** be evaluated against
the four criteria independently — a single product can contain both device and non-device
functions. This codebase contains two functions with materially different profiles against
Criterion 1 below:

| Function | What it does | Where |
|---|---|---|
| **Function A — NEWS2 scoring/FHIR reporting** | Computes NEWS2 from scalar vitals; renders FHIR Observations | `news2_calculator.py`, `news2_builder.py` |
| **Function B — Waveform DSP pipeline** | Notch/bandpass/Hampel filtering of continuous physiological waveform signals | `signal_processor.py`, `artifact_rejector.py` |

### B.3 The four criteria, evaluated per function

**Criterion 1 — NOT intended to acquire, process, or analyze a medical image, an IVD
signal, or a pattern/signal from a signal acquisition system.**

- **Function A:** Consumes scalar values (e.g., `HR=78`) already reduced to numbers by the
  upstream monitor before HL7 transmission. It performs no signal processing itself. This
  plausibly satisfies Criterion 1, though whether an already-numeric vital sign parameter
  still counts as "a signal from a signal acquisition system" for exemption purposes is a
  genuine interpretive question I cannot resolve — it needs your regulatory counsel's read
  of current FDA guidance and any relevant precedent/warning letters.
- **Function B: FAILS this criterion as currently implemented.** The code explicitly
  performs digital signal processing — notch filtering, Butterworth bandpass filtering, and
  Hampel artifact detection — directly on continuous waveform data from an ICU monitor's
  signal acquisition system
  ([src/domain/services/artifact_rejector.py:1-8](../src/domain/services/artifact_rejector.py#L1),
  module docstring: *"Implements signal processing filters for ICU vital sign
  waveforms"*). This is squarely the activity Criterion 1 excludes from Non-Device CDS
  status, independent of what the output is subsequently used for.

**Criterion 2 — Intended to display, analyze, or print medical information about a
patient.**

- **Function A:** Satisfied — output is a FHIR Observation Bundle for display
  ([src/infrastructure/fhir/bundle_assembler.py](../src/infrastructure/fhir/bundle_assembler.py)).
- **Function B:** The filtered waveform is also returned for display
  (`cleaned_waveform` field). Satisfied in isolation, but Criterion 1 already disqualifies
  this function regardless.

**Criterion 3 — Intended to support or provide recommendations to a healthcare
professional about prevention, diagnosis, or treatment.**

- **Function A:** Satisfied — NEWS2 is explicitly a clinical deterioration early-warning
  recommendation, RCP 2017 algorithm
  ([src/domain/services/news2_calculator.py:1-5](../src/domain/services/news2_calculator.py#L1)).
- **Function B:** The DSP pipeline's direct output (filtered waveform samples) is not
  itself a recommendation — it's conditioned signal data. Not clearly satisfied on its own;
  moot given Criterion 1 failure.

**Criterion 4 — Intended to let the healthcare professional independently review the basis
for the recommendation, not primarily rely on it.**

- **Function A:** Evidence of design intent to satisfy this is genuinely present in the
  code, not just asserted in comments:
  - Per-parameter NEWS2 component Observations are always included, not just the total
    score — [src/infrastructure/fhir/news2_builder.py:44-52](../src/infrastructure/fhir/news2_builder.py#L44)
    ("seven component sub-observations, one per NEWS2 scoring parameter").
  - An explicit machine-readable advisory-only flag is attached to every response:
    `X-CDS-Advisory-Only: true` header
    ([src/api/v1/ingest.py:226](../src/api/v1/ingest.py#L226),
    [src/api/v1/vitals.py:296](../src/api/v1/vitals.py#L296)) and a FHIR extension
    (`_FDA_CDS_EXT`,
    [src/infrastructure/fhir/news2_builder.py:101](../src/infrastructure/fhir/news2_builder.py#L101)).
  - A human-readable disclaimer is embedded in the Bundle itself: *"This is a clinical
    decision support advisory output only"*
    ([src/infrastructure/fhir/news2_builder.py:215](../src/infrastructure/fhir/news2_builder.py#L215)).
  - The underlying NEWS2 algorithm (RCP 2017) is a published, independently-known clinical
    scoring system, not a proprietary black-box model — supports independent
    reviewability by design, not just by disclaimer.
  - **No automated treatment action is triggered anywhere in the codebase** — confirmed by
    inspection; the pipeline terminates at API response, no order-entry, no alerting/paging
    integration, no closed-loop device control exists in this repository.
  - This is reasonably strong, code-verifiable evidence for Function A.
- **Function B:** Moot given Criterion 1 failure, but note the filtered waveform carries no
  comparable "basis for recommendation" framing since it isn't a recommendation.

### B.4 Conclusion (draft, pending your regulatory/legal review)

1. **Function A (NEWS2 scoring/FHIR reporting)** has real, code-verifiable design evidence
   supporting Criteria 2, 3, and 4. Criterion 1 is plausible but rests on an interpretive
   question (numeric vital sign vs. "signal") that I cannot resolve — this is exactly the
   kind of call that needs your regulatory counsel, not an engineering read of the statute.

2. **Function B (waveform DSP pipeline) does not meet Criterion 1 as currently
   implemented**, and therefore, on the plain text of the exemption, does not qualify as
   Non-Device CDS. This is the most concrete, lowest-ambiguity finding in this analysis.

3. **The blanket claim currently embedded in the code** — `"FDA CDS Non-Device Exemption"`
   in [src/main.py:56](../src/main.py#L56) and *"FDA CDS Non-Device Exemption (21 CFR
   §880.3780)"* in `news2_calculator.py` — **applies this label to the whole product**,
   which this analysis suggests is not accurate once Function B is in scope. Since both
   functions are exposed by the same deployed API and the same FHIR Bundle can carry both
   NEWS2 scores and waveform data in one response, "the software" as currently shipped is
   not cleanly separable into an exempt product and a non-exempt product without a
   deliberate scoping decision on your part.

4. **This needs an explicit decision from you / your regulatory function**, likely one of:
   - **(a)** Treat the whole product as in-scope for device regulation (Class II — this
     matches the pre-existing "Health Canada SaMD Class II" note already in
     `news2_calculator.py:20-22`) and pursue the appropriate premarket pathway; or
   - **(b)** Formally scope the "exempt" claim to Function A only, with Function B
     documented, labeled, and *technically firewalled* (e.g., a build/deployment flag that
     disables waveform ingestion) as a separately regulated or separately deployed
     component; or
   - **(c)** Obtain a formal regulatory reading that resolves the Criterion 1 ambiguity in
     Function A's favor and a corresponding determination for Function B specifically.

   I am not in a position to choose between these — it's a business/regulatory strategy
   decision requiring qualified counsel, not something derivable from the code.

### B.5 Other discrepancies found while researching this (flagging, not fixing)

- `pyproject.toml` declares `readme = "README.md"` but no `README.md` exists in the repo —
  unrelated to REG-001 substantively, but worth knowing about if a build/packaging step
  depends on it.
- The `21 CFR §880.3780` citation (§B.1) needs verification/correction by whoever owns that
  comment.

---

*This document was generated by inspecting source code only. It contains no external
regulatory research beyond citing the publicly known statutory basis for the CDS
exemption (21st Century Cures Act §3060 / FD&C Act §520(o)(1)(E)) for correction purposes.
Every functional claim above is traceable to a specific file and line in this repository as
of commit `b166b17`.*
