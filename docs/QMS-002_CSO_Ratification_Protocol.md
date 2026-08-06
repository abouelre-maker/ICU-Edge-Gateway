# QMS-002 — Clinical Safety Officer Risk Acceptance & Ratification Protocol (DRAFT)

**Status:** DRAFT — engineering-drafted starting point. **This document is not itself a
ratification.** It is the structured package a designated Clinical Safety Officer (CSO) or
Medical Director uses to *perform* one. Nothing in HAZARD-DSP-005's or HAZARD-DSP-006's
status changes until Section 5's sign-off is actually executed by a named, qualified
individual.

**Prepared:** 2026-08-06, Phase 7, per project owner instruction.
**Predecessor:** [QMS-001_DHF_Structure.md §4.2](QMS-001_DHF_Structure.md#42-risk-traceability--entries-explicitly-requested-for-this-draft),
which first flagged that QMS-002 blocks on no CSO role being designated yet.

---

## Section 1 — Protocol Purpose & Authority

### 1.1 Purpose

To provide a single, ratifiable package — technical evidence, clinical exposure analysis,
and a structured decision framework — that lets a qualified individual formally accept,
reject, or conditionally accept two specific, already-characterized residual risks in the
ICU Edge Gateway's waveform DSP pipeline, without requiring that individual to re-derive the
underlying signal-processing analysis themselves.

### 1.2 Who may execute Section 5

This protocol requires a **Clinical Safety Officer or Medical Director** meeting, at
minimum:

- Clinical qualification relevant to acute/ICU patient monitoring (e.g., critical care
  physician, or a clinical engineer/biomedical safety officer working under a physician's
  delegated authority — your organization's QMS should specify which).
- Authority, per your organization's Quality Manual, to accept residual risk on behalf of
  the manufacturer under ISO 14971 §7 (Evaluation of overall residual risk).
- **No such role is currently designated anywhere in this project's record** — confirmed in
  QMS-001 §00_QMS_GOVERNANCE. This is the actual blocker: this document cannot be
  meaningfully executed until that appointment is made. I am not able to appoint one or
  simulate one being appointed.

### 1.3 What this protocol does NOT cover

- It does not cover REG-001 (regulatory classification) — that determines *whether* this
  product needs this kind of ratification at all, or under what pathway. This protocol
  assumes SaMD-level risk management rigor regardless of REG-001's outcome, since both
  candidate paths (Class II, or exempt-CDS-with-a-Class-II-adjacent-component) benefit from
  documented residual risk acceptance for the waveform pipeline.
- It does not cover other open hazards (HAZARD-PROTO-002, etc.) — scoped narrowly to
  DSP-005 and DSP-006 per your instruction.
- It is not a substitute for the CSO's own independent clinical judgment. The "Clinical
  Justification Criteria" in Section 2 are a structured aid, not a predetermined answer.

---

## Section 2 — Residual Risk Evaluation Framework

No severity/probability/detectability matrix currently exists as an adopted document in this
project (QMS-001 §4.1 confirmed the Phase 5 doc's referenced risk-register spreadsheet does
not exist in the repository). The table below is a standard ISO 14971-style 1–5 matrix
offered as a **starting template** — your organization may already have an adopted matrix
that should be used instead; do not treat the scoring below as authoritative if so.

### 2.1 Severity (S) — harm to the patient if the hazard manifests

| Level | Descriptor | This context |
|---|---|---|
| 1 | Negligible | No perceptible clinical impact |
| 2 | Minor | Temporary discomfort/inconvenience, no clinical action needed |
| 3 | Serious | Requires clinical intervention, no permanent harm expected |
| 4 | Critical | Permanent harm or major intervention required |
| 5 | Catastrophic | Death or irreversible major harm |

### 2.2 Probability (P) — likelihood the hazard's failure mode occurs in clinical use

| Level | Descriptor |
|---|---|
| 1 | Improbable |
| 2 | Remote |
| 3 | Occasional |
| 4 | Probable |
| 5 | Frequent |

### 2.3 Detectability (D) — likelihood a clinician catches the failure before harm occurs

| Level | Descriptor |
|---|---|
| 1 | Almost certain to be caught (obvious, immediate, redundant checks) |
| 2 | High |
| 3 | Moderate |
| 4 | Low |
| 5 | Almost certain to be missed |

### 2.4 Risk Index & Acceptability Bands (template — confirm against your adopted policy)

`Risk Index = S × P × D` (range 1–125). Suggested bands, **for the CSO to confirm or
override**:

| Index range | Band | Action |
|---|---|---|
| 1–12 | Acceptable | Accept as residual risk, log only |
| 13–36 | ALARP (As Low As Reasonably Practicable) | Accept with documented justification + monitoring |
| 37–75 | Undesirable | Requires mitigation before acceptance, or strong justification |
| 76–125 | Unacceptable | Must not ship without further mitigation |

---

## Section 3 — Case Package A: HAZARD-DSP-005

### 3.1 Technical Summary

In the current Notch → Bandpass → Hampel execution order
([src/domain/services/signal_processor.py](../src/domain/services/signal_processor.py)),
a short-duration injected artifact that is trivially detected by `HampelFilter` immediately
after the notch stage becomes **undetectable** by that same `HampelFilter` once the 0.5 Hz-
cutoff, order-3 Butterworth bandpass stage has also run. The bandpass filter's impulse
response is long enough, relative to Hampel's local window (radius=5 samples), to smear the
artifact's local statistical signature below Hampel's detection threshold — confirmed
reproducible even at 100× the surrounding signal amplitude.

`HampelFilter` is confirmed correct in isolation (pre-bandpass) — this is a **stage-ordering
interaction**, not a defect in any individual filter. Evidence:
[tests/integration/test_hl7v2_waveform_pipeline.py::TestKnownArtifactDetectionLimitation](../tests/integration/test_hl7v2_waveform_pipeline.py).

### 3.2 Prior Engineering Decision (input to this ratification, not a substitute for it)

Recorded 2026-08-06: do not reorder the DSP pipeline stages; accept as a documented residual
risk for the current release. This was an engineering-level decision made to keep the
already-validated DSP path stable while this exact ratification package was prepared — it is
explicitly **provisional pending this Section 5 sign-off**.

### 3.3 Clinical Exposure Analysis

**What is actually at risk, precisely:** if a short-duration motion artifact occurs in a
patient's waveform channel, it may pass through the full DSP chain without being flagged as
an artifact by `HampelFilter`, `outlier_count`, or the `[HAMPEL]` audit note.

**What is NOT at risk, by architectural guarantee (not just intent):** the NEWS2 score — the
actual early-warning number a clinician acts on — **cannot** be derived from waveform data,
under any circumstance in the current codebase. This is enforced by
`PhysiologicalBoundsChecker` marking every waveform-only sample's placeholder value (0.0) as
out-of-bounds, which excludes it from `NEWS2Calculator`'s candidate pool. This is not merely
asserted — it is regression-tested by
`tests/integration/test_hl7v2_waveform_pipeline.py::TestWaveformNeverFeedsNews2Score`, which
would fail the entire suite if that architectural separation were ever broken.

**Therefore:** today's actual clinical exposure is bounded to the `cleaned_waveform` /
`dsp-outlier-count` FHIR extension under-reporting artifact presence in **displayed waveform
data only** — not to any scored/actionable clinical output. This is the load-bearing claim
of this entire case package; if the CSO disagrees with this architectural read, the ratified
decision should reflect that disagreement, not silently defer to the engineering framing.

### 3.4 Suggested Severity/Probability/Detectability Scoring (CSO to confirm/override)

| Factor | Suggested | Rationale |
|---|---|---|
| Severity (S) | 2 (Minor) | Only affects displayed waveform trace fidelity, not the scored/actionable NEWS2 output — see §3.3 |
| Probability (P) | 3 (Occasional) | Motion artifacts in ICU waveform channels are a routine occurrence, not rare |
| Detectability (D) | 3 (Moderate) | A trained clinician visually inspecting a waveform trace may notice an unflagged artifact; an automated system relying solely on `outlier_count` would not |
| **Risk Index** | **18 (ALARP band, per §2.4 template)** | — |

### 3.5 Mandatory Escalation Trigger (already documented; restating for the sign-off record)

**Severity must be re-escalated if any future feature derives scoring or clinical display
directly from waveform data** — i.e., if the architectural separation in §3.3 is ever
weakened, this entire risk acceptance is void and must be re-ratified.

### 3.6 Questions for the CSO to resolve (not pre-answered)

1. Does §3.3's architectural-separation claim satisfy you as a genuine control, or do you
   require independent verification beyond reading the cited test?
2. Is "clinician may visually notice an unflagged waveform artifact" a detectability
   argument you accept, given your knowledge of actual ICU bedside display practice?
3. Should this decision expire on a fixed date (e.g., annual re-review) rather than only on
   the trigger in §3.5?

---

## Section 4 — Case Package B: HAZARD-DSP-006

### 4.1 Technical Summary

`filtfilt`'s zero-phase boundary padding produces artifact-independent, false-positive
motion-artifact flags at the edges of every bandpass-filtered waveform array — reproducible
regardless of whether a real artifact is present. Empirically characterized as variable in
count and exact offset (not a fixed "always the last 2 samples") depending on sampling rate
and array length. Full derivation in this session's working history and code comments at
[src/domain/services/artifact_rejector.py](../src/domain/services/artifact_rejector.py)
(`edge_margin_samples` docstring).

### 4.2 Mitigation Already Implemented (this is a verification/concurrence ratification, not an open-risk acceptance)

Unlike DSP-005, this hazard has an implemented, tested mitigation: `BandpassFilter.
edge_margin_samples()` computes a mathematically-derived exclusion zone (group delay at the
passband's geometric-mean frequency, ×2 for filtfilt's forward+backward pass) and
`VitalSignProcessor.process()` reclassifies edge-zone Hampel flags out of `outlier_count`
into a distinct `[HAMPEL-EDGE]` audit note — **without altering any filter's numeric
output**. See
[tests/unit/test_artifact_rejector.py::TestBandpassFilterEdgeMarginSamples](../tests/unit/test_artifact_rejector.py)
and
[tests/integration/test_hl7v2_waveform_pipeline.py::TestHazardDsp006EdgeMitigation](../tests/integration/test_hl7v2_waveform_pipeline.py).

**What the CSO is being asked to ratify here is narrower than DSP-005**: not "should this
ship unmitigated," but "is the mitigation's known trade-off clinically acceptable."

### 4.3 The Residual Trade-Off (the actual thing requiring sign-off)

Because Hampel's local statistics cannot distinguish "filtfilt boundary ringing" from "a
genuine motion artifact that happens to land inside the edge margin," a **real** artifact
inside that margin is:
- ✅ Still corrected numerically in `cleaned_waveform` (median-substituted, identical
  treatment to any other detected artifact).
- ❌ **Not** counted in `outlier_count` or reported via the `[HAMPEL]` audit note — it
  under-reports as a motion artifact event in that specific zone.

This is explicitly tested and regression-guarded, not left as a silent gap:
`test_known_limitation_real_artifact_inside_edge_margin_is_undercounted` in
`test_hl7v2_waveform_pipeline.py`.

### 4.4 Clinical Exposure Analysis

The margin width is derived per-filter from real sampling-rate-dependent group delay (worst
case ~89 samples for RESPIRATORY_RATE's narrow 0.1–1.0 Hz band at 62.5 Hz — see the
`edge_margin_samples` docstring and this session's derivation). At typical array lengths
this affects a small fraction of total samples, concentrated at array boundaries — not
uniformly across the recording.

As with DSP-005, this cannot affect the NEWS2 score (§3.3's architectural separation applies
identically here — waveform data of any kind never feeds NEWS2 scoring).

### 4.5 Suggested Severity/Probability/Detectability Scoring (CSO to confirm/override)

| Factor | Suggested | Rationale |
|---|---|---|
| Severity (S) | 1 (Negligible) | Value is still corrected; only the audit-trail *count/classification* is affected, and only for display/audit purposes, never scoring |
| Probability (P) | 2 (Remote) | Requires a genuine artifact to land specifically within a narrow, filter-dependent edge window |
| Detectability (D) | 3 (Moderate) | Same reasoning as §3.4 — visual trace inspection may catch it, aggregate `outlier_count` alone would not |
| **Risk Index** | **6 (Acceptable band, per §2.4 template)** | — |

### 4.6 Questions for the CSO to resolve

1. Is "the value is still corrected, only its audit classification changes" a sufficient
   clinical distinction from DSP-005 (where nothing is corrected at all)?
2. Do you concur that a Severity=1 rating is appropriate given the value-correction
   distinction in §4.3, or do you view any under-reported artifact — regardless of whether
   the underlying value was fixed — as warranting the same severity as DSP-005?

---

## Section 5 — Formal Sign-Off Template

*(One copy per hazard. Reproduce this block for HAZARD-DSP-005 and HAZARD-DSP-006
separately — they may receive different decisions.)*

```
═══════════════════════════════════════════════════════════════════════════
CLINICAL SAFETY OFFICER RISK ACCEPTANCE RECORD
═══════════════════════════════════════════════════════════════════════════

Hazard ID:                    [ HAZARD-DSP-005 / HAZARD-DSP-006 ]
Document reference:           QMS-002_CSO_Ratification_Protocol.md, Section [3/4]
Product / Version:            ICU Edge-to-FHIR Interoperability Gateway v1.0.0

CSO / Medical Director Name:  _________________________________________
Credentials / Role:           _________________________________________
Organizational Authority:     _________________________________________
                               (cite the Quality Manual provision granting
                               risk-acceptance authority)

Severity (S):        [1-5]    Confirmed as proposed?  [ Yes / Overridden: __ ]
Probability (P):     [1-5]    Confirmed as proposed?  [ Yes / Overridden: __ ]
Detectability (D):   [1-5]    Confirmed as proposed?  [ Yes / Overridden: __ ]
Risk Index (S×P×D):  [1-125]  Band: [ Acceptable / ALARP / Undesirable / Unacceptable ]

DECISION (select one):
  [ ] ACCEPT as residual risk, no further action
  [ ] ACCEPT with conditions (specify below)
  [ ] CONDITIONAL — accept pending [specific additional evidence/action]
  [ ] REJECT — mitigation required before release; hazard remains OPEN

Conditions / monitoring requirements (if any):
_____________________________________________________________________
_____________________________________________________________________

Re-review trigger(s):
  [ ] Fixed expiration date: __________________
  [ ] Event-triggered: as specified in the hazard's escalation trigger
      (DSP-005 §3.5 / DSP-006 §4.3), and/or: __________________
  [ ] Both

Clinical justification (free text — required if DECISION overrides the
suggested S/P/D scoring, or selects CONDITIONAL/REJECT):
_____________________________________________________________________
_____________________________________________________________________
_____________________________________________________________________

Signature:                    _________________________________________
Date:                          _________________________________________

═══════════════════════════════════════════════════════════════════════════
```

---

## Section 6 — Post-Ratification Actions

Once Section 5 is executed for both hazards:

1. Update [QMS-001_DHF_Structure.md §4.2](QMS-001_DHF_Structure.md#42-risk-traceability--entries-explicitly-requested-for-this-draft) —
   change HAZARD-DSP-005's status from "🟡 Accepted residual risk — PENDING formal
   ratification" to reflect the actual Section 5 decision.
2. If either hazard is rejected or conditionally accepted, open a corresponding engineering
   task before the next release — do not let a REJECT decision sit unresolved against a
   shipped product.
3. File the completed Section 5 record(s) as controlled documents per whatever document-
   control procedure QMS-001 §00_QMS_GOVERNANCE ultimately adopts (not yet defined — another
   open QMS-001 item).
4. If a fixed re-review date was selected, schedule it — this repository has no mechanism to
   track that on its own.

---

*This document was generated by inspecting source code and this session's engineering
history only. The suggested Severity/Probability/Detectability scores in Sections 3.4 and
4.5 are engineering-proposed starting points for the CSO's independent judgment — they are
not clinical determinations and must not be treated as such until explicitly confirmed in a
Section 5 record.*
