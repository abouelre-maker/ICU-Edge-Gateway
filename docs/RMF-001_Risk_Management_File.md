# RMF-001 — ISO 14971 Risk Management File

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
> ratify, any other hazard in this file.
>
> **HAZARD-DSP-005 and HAZARD-DSP-006 remain outside ANY sign-off scope** — interim or
> otherwise. Both require a credentialed Clinical Safety Officer's formal ratification per
> [QMS-002_CSO_Ratification_Protocol.md](QMS-002_CSO_Ratification_Protocol.md), which has not
> occurred. Do not read either as accepted, closed, or clinically reviewed.
>
> **FDA / Health Canada regulatory classification is an engineering assumption, not a
> regulatory determination.** Per Finding 3 of
> [docs/ICU_Edge_Gateway_Phase5_Technical_Package.md](ICU_Edge_Gateway_Phase5_Technical_Package.md)
> ("Regulatory citations in source comments are engineering design assumptions, not regulatory
> determinations"): the Dockerfile's `samd.regulatory.fda="CDS-Non-Device"` and
> `samd.regulatory.canada="Class-II"` labels, and every "FDA CDS Non-Device Exemption (21 CFR
> §880.3780)" / "Health Canada SaMD Class II" citation embedded in source docstrings throughout
> this codebase, are engineering design-intent markers, self-asserted in code comments —
> **not** a completed regulatory submission, not reviewed by regulatory affairs or legal
> counsel, and not verified against the current, in-force text of any jurisdiction's rules.
> [REG-001_Intended_Use_and_CDS_Exemption_Draft.md](REG-001_Intended_Use_and_CDS_Exemption_Draft.md)
> §B.4 remains an open, unresolved determination.
>
> This banner is not boilerplate. Every section below inherits these three facts; none of them
> are re-litigated or softened further down in this document.

---

**Document ID:** RMF-001
**Status:** DRAFT — engineering-compiled working document. Not a certified ISO 14971 Risk
Management File until reviewed and adopted per an actual Quality Management System, which does
not yet exist at this company stage (see [QMS-001_DHF_Structure.md](QMS-001_DHF_Structure.md)
§1 — "This repo has no QMS of record").
**Prepared:** 2026-08-10, Phase 5-Stream Section E, per project owner instruction.
**Seeded from:** `ICU_Edge_Gateway_Risk_Register_2.xlsx` ("Risk Register" sheet), the existing
informal register this file is intended to formalize per
[QMS-001 §4](QMS-001_DHF_Structure.md#4-06_risk_management_file-iso-14971--unified-module-tagged)'s
own recommendation ("Recommend this DHF module becomes the trigger to actually create that
file"). **40 hazard entries** as of this correction (2026-08-10, same-day follow-up to this
file's original compilation) — every row currently in the workbook, not a curated subset. (Note:
an earlier estimate this session cited "13" tracked hazards; that number matches only the
original Phase 5 core-NEWS2-scoring subset — see §3.A below — and has been superseded by growth
across Sections B/C/D of this Phase. This file uses the accurate, current count.)

**CORRECTION, 2026-08-10 (verified row-by-row against the actual workbook, not by
arithmetic):** this file's original compilation stated "34 hazard entries... every row
currently in the workbook, not a curated subset." That claim was already inaccurate on the day
it was written — the workbook has had **35** populated rows (34 `HAZARD-*`-numbered entries plus
one additional row, `(unassigned -- awaiting Risk ID)`, carrying no hazard ID and therefore
omitted from this file's per-ID Appendix A enumeration even though it was, and is, a real
populated row) since before this file existed. That row is now assigned the placeholder
reference **UNASSIGNED-PVC-001** in this file (§3.F, Appendix A) so it is no longer omitted.
Separately, five additional rows (HAZARD-STREAM-001 through -005) were added to the workbook
this same day, closing a source-tagged/register-absent gap surfaced by
[RTM-001](RTM-001_Requirements_Traceability_Matrix.md) §6. 35 (corrected baseline) + 5 (new) =
**40**, re-verified by counting populated `Risk ID`-column cells in the workbook directly, not
by adding these two numbers on faith. Every count below this point in the document has been
corrected to match.
**Supersedes (informally, not yet adopted):** the partial 7-row illustrative table in
[QMS-001 §4.2](QMS-001_DHF_Structure.md#42-risk-traceability--entries-explicitly-requested-for-this-draft).

---

## 0. Purpose and Scope

This is the Risk Management File required by ISO 14971 ("Application of risk management to
medical devices") for the ICU Edge-to-FHIR Interoperability Gateway — a software system that
ingests HL7 v2.x / structured-JSON vital sign data, applies DSP artifact rejection, computes a
NEWS2 (National Early Warning Score 2, RCP 2017) early-warning score, and emits FHIR R4
resources for downstream clinical systems, plus a Phase 5-Stream cloud provisioning/streaming
layer (MQTT, WebSocket dashboard, FHIR Subscriptions, mTLS device enrollment).

Scope covers the whole system as a single risk-management activity, not split by module — a
hazard in the streaming/provisioning layer can affect a patient outcome mediated through the
NEWS2 display layer, so this file does not fragment risk management by code module (see
QMS-001 §0's identical rationale, restated here for this file specifically).

**Out of scope for this document:** regulatory classification (REG-001, unresolved), clinical
validation studies (none performed — this is an engineering-verified, not clinically-validated,
system), and formal Quality Management System procedures (none exist).

## 1. Applicable Standards and Referenced Documents

| Standard / Document | Role here |
|---|---|
| ISO 14971:2019 | Primary standard this file implements |
| IEC 62304 | Referenced throughout source code (Class B); governs the SDLC this RMF sits alongside |
| RCP NEWS2 (2017), ISBN 978-1-86016-693-6 | Clinical scoring algorithm this system implements — the ground truth for HAZARD-NEWS2-*/SPO2-*/RR-*/SBP-*/HR-*/CON-*/TEMP-*/O2-* |
| [QMS-001_DHF_Structure.md](QMS-001_DHF_Structure.md) | Design History File structure; §4 is this RMF's stated origin |
| [QMS-002_CSO_Ratification_Protocol.md](QMS-002_CSO_Ratification_Protocol.md) | Formal ratification procedure for HAZARD-DSP-005/006 — not yet executed |
| [CSO_Role_Appointment_Brief.md](CSO_Role_Appointment_Brief.md) | §5 — the only sign-off authority record that exists, and its explicit limits |
| [REG-001_Intended_Use_and_CDS_Exemption_Draft.md](REG-001_Intended_Use_and_CDS_Exemption_Draft.md) | Open regulatory classification determination |
| `ICU_Edge_Gateway_Risk_Register_2.xlsx` | Source-of-truth workbook this file is seeded from |

## 2. Risk Management Plan

### 2.1 Risk management activities and responsibilities

| ISO 14971 activity | Status in this project |
|---|---|
| Risk management plan (this section) | Drafted here for the first time as a standalone artifact — previously only implicit in the workbook's structure |
| Risk analysis (hazard identification, hazardous situations, harm) | Performed per-hazard, iteratively, across Phases 5 through 5-Stream — see §3 |
| Risk evaluation (Sev × Prob against acceptability criteria) | Performed for 25 of 40 entries, including a pre-mitigation-only score for HAZARD-PROTO-002 (post-mitigation left blank, genuinely still open); **NOT yet performed at all** (no Sev/Prob score of any kind) for 15 entries — HAZARD-DSP-004 (administrative gap, not a scoreable hazard), the 8 Phase 5-Stream-era hazards (STREAM-006 through STREAM-012, DSP-007), HAZARD-STREAM-001 through -005 (added 2026-08-10, deferred by scope decision), and UNASSIGNED-PVC-001 (added 2026-08-10, no hazard ID assigned yet) — shown as blank in §3, not defaulted |
| Risk control (implementation + verification) | Performed per-hazard where a fix exists — see each entry's Mitigation/Verification Evidence fields |
| Residual risk evaluation | **Not yet performed as a formal, single roll-up activity** — no organization-wide risk acceptability policy/matrix exists beyond the Severity/Probability scale definitions in the workbook's own Legend sheet (restated in §2.2) |
| Risk management report | **Not yet issued** — would require the credentialed CSO sign-off this file's banner states does not exist |
| Production and post-production information | **Not yet implemented** — no post-market surveillance process exists; see §6 |

### 2.2 Risk acceptability criteria (as currently defined — engineering-drafted, not QMS-adopted)

From the source workbook's Legend sheet, restated here verbatim in substance:

**Severity (1–5):** 1 = Negligible (no clinical impact) · 2 = Minor (temporary/reversible, no
intervention needed) · 3 = Serious (requires clinical intervention, reversible) · 4 = Critical
(life-threatening or major irreversible harm) · 5 = Catastrophic (death or permanent major
harm, especially if propagated silently across a population of patients).

**Probability (1–5):** 1 = Improbable · 2 = Remote · 3 = Occasional · 4 = Probable · 5 =
Frequent.

**Risk Index bands (Severity × Probability):** 1–4 = Acceptable · 5–9 = ALARP (As Low As
Reasonably Practicable — acceptable with ongoing monitoring/justification) · 10–25 =
Unacceptable, requiring further mitigation OR an explicit, justified, sign-off-backed
acceptance decision (HAZARD-DSP-005, §3.B, is the one worked example of this path in the
current file — and its acceptance is itself still pending the credentialed ratification this
banner describes).

Per the workbook's own disclaimer, restated here: these ratings are engineering-drafted
starting points produced by an AI engineering assistant, not a licensed clinical risk manager
— a structured starting point for qualified review, not a completed determination.

---

## 3. Risk Analysis & Evaluation

40 hazard entries, grouped by module (see the correction note in the front matter above for how this count was re-verified). Sev/Prob use the 1-5 scales defined in the source workbook's Legend sheet (restated in §2.2 below); Risk Index = Severity × Probability, computed here directly from the Sev/Prob columns (the source workbook stores these as spreadsheet formulas referencing the same cells, not as separately-entered numbers — recomputed here, not re-typed, so there is no transcription drift). A blank Sev/Prob/Risk Index means the source workbook has never scored that entry — shown as blank here too, not defaulted to 0 or 1, so an unscored hazard is never misread as low-risk.

### 3.A Module A — Core NEWS2 Scoring Engine

| ID | Potential Harm | Sev | Prob (pre) | Risk Index (pre) | Prob (post) | Risk Index (post) | Status |
|---|---|---|---|---|---|---|---|
| HAZARD-NEWS2-001 | Missed clinical deterioration or false escalation | 5 | 3 | 15 | 1 | 5 | Closed - Mitigated |
| HAZARD-NEWS2-002 | Delayed emergency response | 5 | 2 | 10 | 1 | 5 | Closed - Mitigated |
| HAZARD-NEWS2-003 | False confidence in an incomplete risk assessment | 5 | 3 | 15 | 1 | 5 | Closed - Mitigated |
| HAZARD-SPO2-001 | Missed deterioration in a COPD/hypercapnic patient | 5 | 3 | 15 | 1 | 5 | Closed - Mitigated |
| HAZARD-RR-001 | Missed respiratory depression / failure | 5 | 2 | 10 | 1 | 5 | Closed - Mitigated |
| HAZARD-SBP-001 | Missed hypotensive shock or hypertensive emergency | 5 | 2 | 10 | 1 | 5 | Closed - Mitigated |
| HAZARD-HR-001 | Missed bradycardia at 41-50 bpm | 5 | 2 | 10 | 1 | 5 | Closed - Mitigated |
| HAZARD-CON-001 | Missed acute neurological deterioration | 5 | 2 | 10 | 1 | 5 | Closed - Mitigated |
| HAZARD-TEMP-001 | Missed hypothermia or hyperthermia | 5 | 2 | 10 | 1 | 5 | Closed - Mitigated |
| HAZARD-O2-001 | O2-masking of true SpO2 reserve goes uncompensated | 4 | 2 | 8 | 1 | 4 | Closed - Mitigated |
| HAZARD-TIME-001 | Stale or mis-ordered value silently used for a scoring parameter | 3 | 3 | 9 | 1 | 3 | Closed - Mitigated |
| HAZARD-ARCH-001 | Instrument-artifact values silently scored | 5 | 2 | 10 | 1 | 5 | Closed - Mitigated |
| HAZARD-BOUNDS-001 | Scoring corrupted by a non-physiological instrument artifact | 4 | 3 | 12 | 1 | 4 | Closed - Mitigated |

### 3.B Module B — DSP Artifact-Rejection Pipeline

| ID | Potential Harm | Sev | Prob (pre) | Risk Index (pre) | Prob (post) | Risk Index (post) | Status |
|---|---|---|---|---|---|---|---|
| HAZARD-DSP-001 | Downstream waveform quality degraded (does not currently affect NEWS2 scoring - see architecture note) | 3 | 3 | 9 | 1 | 3 | Closed - Mitigated |
| HAZARD-DSP-002 | Downstream waveform quality degraded | 2 | 3 | 6 | 1 | 2 | Closed - Mitigated |
| HAZARD-DSP-003 | False-negative or false-positive artifact rejection | 3 | 3 | 9 | 1 | 3 | Closed - Mitigated |
| HAZARD-DSP-004 | N/A - administrative gap |  |  |  |  |  | Open - Requires Action |
| HAZARD-DSP-005 | Bounded today: NEWS2 scoring is verified DECOUPLED from waveform data (scalar NEWS2 inputs come only from companion NM OBX segments —... (see Appendix A) | 3 | 4 | 12 | 4 | 12 | Open - Accepted Residual Risk |
| HAZARD-DSP-006 | False-positive artifact flag (opposite direction from HAZARD-DSP-005); low direct harm — errs toward caution, not toward missing a real... (see Appendix A) | 2 | 5 | 10 |  |  | Open - Awaiting Decision |
| HAZARD-DSP-007 | SEVERITY IS DIRECTION-DEPENDENT, NOT UNIFORM -- the two halves of this hazard have OPPOSITE clinical risk profiles and must be... (see Appendix A) |  |  |  |  |  | Open - INTERIM engineering sign-off recorded 2026-08-10 (see docs/CSO_Role_Appointment_Brief.md |

### 3.C Module C — HL7v2 Protocol Adapter

| ID | Potential Harm | Sev | Prob (pre) | Risk Index (pre) | Prob (post) | Risk Index (post) | Status |
|---|---|---|---|---|---|---|---|
| HAZARD-PROTO-001 | A vital sign parameter is missing from scoring input (mitigated further downstream by HAZARD-NEWS2-003 fail-fast) | 4 | 3 | 12 | 2 | 8 | Closed - Mitigated |
| HAZARD-PROTO-002 | Incorrect sampling rate corrupts every downstream DSP stage (notch target frequency, bandpass range, Hampel timing) for that channel | 3 | 4 | 12 |  |  | Open - Requires Action |
| HAZARD-WAVE-001 | Sample timing corrupted ahead of notch/bandpass/Hampel processing | 3 | 3 | 9 | 1 | 3 | Closed - Mitigated |

### 3.D Module D — FHIR Output Layer

| ID | Potential Harm | Sev | Prob (pre) | Risk Index (pre) | Prob (post) | Risk Index (post) | Status |
|---|---|---|---|---|---|---|---|
| HAZARD-FHIR-001 | Clinical record corruption / wrong parameter displayed | 4 | 2 | 8 | 1 | 4 | Closed - Mitigated |
| HAZARD-FHIR-002 | Wrong risk level acted upon downstream | 4 | 2 | 8 | 1 | 4 | Closed - Mitigated |
| HAZARD-FHIR-003 | Loss of audit/temporal correlation | 2 | 2 | 4 | 1 | 2 | Closed - Mitigated |

### 3.E Module E — Cross-Cutting API Security

| ID | Potential Harm | Sev | Prob (pre) | Risk Index (pre) | Prob (post) | Risk Index (post) | Status |
|---|---|---|---|---|---|---|---|
| HAZARD-CORS-001 | Unauthorized cross-origin data exposure | 3 | 4 | 12 | 1 | 3 | Closed - Mitigated |

### 3.F Module F — Streaming & Provisioning Infrastructure (Phase 5-Stream)

| ID | Potential Harm | Sev | Prob (pre) | Risk Index (pre) | Prob (post) | Risk Index (post) | Status |
|---|---|---|---|---|---|---|---|
| HAZARD-STREAM-006 | Clinical Bundle data delivered to, or internal-network reconnaissance via, an unintended internal endpoint |  |  |  |  |  | Open - PROPOSED, pending human security/risk-management sign-off |
| HAZARD-STREAM-007 | Subscriber-side missed/delayed clinical notification, mistaken for normal quiet monitoring |  |  |  |  |  | Open - PROPOSED, pending human security/risk-management sign-off |
| HAZARD-STREAM-008 | Subscriber misses that specific clinical delta permanently for that occurrence (contrast: the MQTT edge->cloud path DOES requeue... (see Appendix A) |  |  |  |  |  | Open - PROPOSED, pending human security/risk-management sign-off |
| HAZARD-STREAM-009 | Unauthorized registration of a data-exfiltration webhook, disclosure of other subscribers' webhook credentials, or deletion of a... (see Appendix A) |  |  |  |  |  | Open - mitigation applied this session, NOT self-closed, pending human sign-off |
| HAZARD-STREAM-010 | An illegitimate device gains a trusted mTLS identity able to participate in the fleet (submit telemetry, be treated as a genuine edge... (see Appendix A) |  |  |  |  |  | Open - PROPOSED, pending human security/risk-management sign-off (CA-pinning mitigation narrows, |
| HAZARD-STREAM-011 | A revoked/decommissioned device retains a working clinical-data-capable identity for longer than the operator intended |  |  |  |  |  | Open - PROPOSED, pending human security/risk-management sign-off (scheduling gap closed this |
| HAZARD-STREAM-012 | Compromise: an attacker able to mint certificates trusted by every device in the fleet simultaneously -- a single-point failure with... (see Appendix A) |  |  |  |  |  | Open - INTERIM engineering sign-off recorded 2026-08-10 (see docs/CSO_Role_Appointment_Brief.md |
| HAZARD-STREAM-001 | Corrupted vital-sign data silently parsed and scored as if valid (MLLP frame integrity) |  |  |  |  |  | Open - Deferred by Scope Decision |
| HAZARD-STREAM-002 | Clinical telemetry loss during extended outages, or edge-appliance memory exhaustion (store-and-forward ring buffer) |  |  |  |  |  | Open - Deferred by Scope Decision |
| HAZARD-STREAM-003 | Loss of clinical telemetry, or edge ingestion outage triggered by a downstream cloud-connectivity failure (MQTT publisher) |  |  |  |  |  | Open - Deferred by Scope Decision |
| HAZARD-STREAM-004 | Confidentiality/integrity compromise of in-transit clinical telemetry (MQTT TLS optionally disabled) |  |  |  |  |  | Open - Deferred by Scope Decision |
| HAZARD-STREAM-005 | Edge/cloud resource exhaustion from one slow dashboard client, or delayed/dropped live-dashboard delta delivery to other clinicians |  |  |  |  |  | Open - Deferred by Scope Decision |
| UNASSIGNED-PVC-001 | A leaked device.key from unencrypted underlying storage is functionally the same device-impersonation risk as HAZARD-STREAM-010, via a different path |  |  |  |  |  | Open - awaiting Risk ID assignment and triage decision |

**Rows added 2026-08-10 (this correction), not part of the file's original compilation:**
HAZARD-STREAM-001 through -005 and UNASSIGNED-PVC-001. See the front-matter correction note and
§9 for the discovery/verification record; see Appendix A below for their full transcribed
records (added in the same pass, not summarized differently from the other 34 entries).

---
## 4. Risk Control Summary

Of the 40 hazard entries in §3/Appendix A:

| Status bucket | Count | Notes |
|---|---:|---|
| Closed - Mitigated | 22 | Verified by test evidence cited per-entry; NONE of these have been reviewed by a credentialed CSO — "Closed" here means "engineering-verified," not "clinically ratified" |
| Open (various: Requires Action / Awaiting Decision / PROPOSED pending sign-off / INTERIM engineering sign-off / Deferred by Scope Decision / awaiting Risk ID assignment) | 17 | 11 pre-existing + HAZARD-STREAM-001 through -005 (5, added 2026-08-10) + UNASSIGNED-PVC-001 (1, added 2026-08-10). See §5 for the sign-off-scope breakdown of these |
| Open - Accepted Residual Risk | 1 | HAZARD-DSP-005 only — engineering-decided, explicitly NOT self-closed, formal ratification blocked on QMS-002 (unexecuted) |

**No hazard in this file has ever received a credentialed clinical sign-off.** The banner at
the top of this document is the load-bearing fact for this entire section, not a formality.

## 5. Sign-Off Scope — precisely which hazards the interim appointment covers

Per [CSO_Role_Appointment_Brief.md](CSO_Role_Appointment_Brief.md) §5, the interim,
non-clinically-credentialed engineering appointment's scope is **explicitly limited to
engineering-identified hazards**, named there as HAZARD-DSP-007 and HAZARD-STREAM-012 only:

| Hazard | Interim sign-off scope? | Actual current status |
|---|---|---|
| HAZARD-DSP-007 | ✅ In scope (interim, engineering-only) | Fix applied + verified; **credentialed-CSO ratification still required before clinical closure** — entry remains Open |
| HAZARD-STREAM-012 | ✅ In scope (interim, engineering-only) | Gap 1 resolved, gap 2 open; **credentialed-CSO ratification still required before clinical closure** — entry remains Open |
| HAZARD-DSP-005 | ❌ Explicitly OUT of scope | Accepted as residual risk by engineering decision only; **blocked on QMS-002's unexecuted formal ratification procedure** |
| HAZARD-DSP-006 | ❌ Explicitly OUT of scope | Mitigated (edge-margin reclassification) but **not clinically ratified**; same QMS-002 blocker |
| HAZARD-STREAM-006 through -011 | ❌ Out of scope (not named in the appointment) | All "Open - PROPOSED, pending human security/risk-management sign-off" — no sign-off of any kind, interim or otherwise, exists for these |
| HAZARD-DSP-004 | ❌ Out of scope | Administrative/documentation gap, unresolved — needs a Quality/Regulatory decision on whether to retire or redefine the ID |
| PROTO-002 | ❌ Out of scope | Genuinely open — per-monitor-model sampling-rate validation is a site/vendor-specific gate, not resolvable from source code alone |
| HAZARD-STREAM-001 through -005 | ❌ Out of scope (not named in the appointment; added to the register 2026-08-10, after the interim appointment was recorded) | "Open - Deferred by Scope Decision" — entry only, no risk evaluation, sign-off, or clinical review of any kind performed |
| UNASSIGNED-PVC-001 | ❌ Out of scope (no `HAZARD-*` ID exists yet for the appointment to name) | "Open - awaiting Risk ID assignment and triage decision" |
| All 22 "Closed - Mitigated" entries (incl. HAZARD-CORS-001, closed 2026-08-10 — see §9) | ❌ Out of scope (not proposed for sign-off — the interim authority was only ever asked to cover DSP-007/STREAM-012) | Engineering-verified only, as stated in §4 |

## 6. Overall Residual Risk Evaluation (ISO 14971 §7)

**Not performed.** ISO 14971 §7 requires a documented judgment, made by the manufacturer, that
the overall residual risk of the device is acceptable when weighed against its benefits. That
judgment requires (a) a completed risk evaluation across every hazard (§2.1 shows this is
incomplete — 15 of 40 entries have no Sev/Prob score at all), and (b) the qualified clinical
judgment this file's banner states does not exist at this company stage. Neither precondition
is met. This section is left as an explicit gap, not filled with a placeholder conclusion.

## 7. Risk Management Report (ISO 14971 §8)

**Not issued.** A Risk Management Report is the summary document a manufacturer produces to
declare risk management complete for a given release. Issuing one now would misrepresent the
state described throughout this file (incomplete risk evaluation, one hazard's acceptance
unratified, seventeen hazards fully open, no credentialed clinical authority). This section
records that the report does not exist, rather than fabricating one.

## 8. Production and Post-Production Information (ISO 14971 §10)

**Not implemented.** No post-market surveillance process, no field-data feedback loop into this
RMF, and no defined trigger for re-opening a "Closed" hazard based on real-world use exist yet.
Several individual hazard entries (e.g. HAZARD-DSP-005, HAZARD-PROTO-002) already name their
own specific re-evaluation triggers (see each entry's "Next Review Trigger" field in Appendix
A) — those are the only production-phase risk-management mechanisms that currently exist, and
they are per-hazard, not a systematic §10 process.

## 9. Known Gaps in This RMF Itself (compiled transparently, not omitted)

- **No credentialed CSO** (banner, §5) — the single largest gap; blocks §6/§7 entirely.
- **15 of 40 hazards have no Severity/Probability score at all** — the 8 Phase 5-Stream-era
  hazards (STREAM-006/007/008/009/010/011/012, DSP-007), HAZARD-DSP-004 (administrative gap,
  not a scoreable hazard), HAZARD-STREAM-001 through -005 (added 2026-08-10, deferred by scope
  decision), and UNASSIGNED-PVC-001 (added 2026-08-10, no hazard ID assigned yet). These need a
  risk evaluation pass before §6 can even be attempted. (HAZARD-PROTO-002 is scored
  pre-mitigation only — post-mitigation genuinely still open, not counted in this 15.)
- **This file's original "34 hazard entries... every row currently in the workbook, not a
  curated subset" claim was inaccurate the day it was written** — **RESOLVED 2026-08-10 (same
  correction pass)**: the workbook already had 35 populated rows at that time (see the
  front-matter correction note); the 35th, `(unassigned -- awaiting Risk ID)`, carries no
  `HAZARD-*` ID and was silently excluded from this file's per-ID enumeration rather than
  flagged. It is now entered as UNASSIGNED-PVC-001 (§3.F, Appendix A). Found and corrected
  while re-verifying every count in this file row-by-row against the actual workbook, per
  explicit instruction, not by re-trusting this file's own prior arithmetic.
- ~~HAZARD-CORS-001's register row was stale relative to the actual codebase~~ — **RESOLVED
  2026-08-10**: found while compiling the first draft of this file (flagged, not silently
  corrected, per this document's own convention), confirmed with the project owner that
  `config.py:373-388`/`main.py:205-211` is the intended final fix (not an interim measure),
  and the register row was then updated to Closed - Mitigated with Prob(post)/Risk-Index(post)
  scored. This file was regenerated from the corrected register — left here as a record that
  the gap existed and was closed, not deleted without a trace.
- **HAZARD-DSP-004 is an unresolved administrative question**, not a technical hazard: does it
  represent a real, distinct control gap, or should it be formally retired as a duplicate
  reference? No one has decided.
- **This file has not been cross-validated against QMS-001's own §4.2 table** beyond noting it
  supersedes that table's 7 illustrative rows (front matter) — a full reconciliation of every
  claim in QMS-001 against this file was not performed as part of this compilation.
- **~~No independent verification that all 34 rows in the source workbook were captured~~ beyond
  this file's own generation script's internal completeness assertion (`len(hazards) == 34`...)**
  — **PARTIALLY RESOLVED 2026-08-10:** this correction pass re-verified the count directly
  against the workbook (`openpyxl`, counting populated `Risk ID`-column cells row-by-row,
  rows 5-44), not by re-running or trusting the original generation script's internal
  assertion — which is exactly what this note previously said had NOT been done, and is why the
  35-vs-34 discrepancy above went uncaught for as long as it did. Still not independently
  verified: that every cell's *content* (not just row count/ID presence) was transcribed
  correctly into Appendix A — this pass checked counts and IDs, not a field-by-field diff of
  every one of the original 34 entries' 18 columns.

---

## Appendix A — Full Hazard Records

One record per hazard ID, all fields transcribed verbatim from `ICU_Edge_Gateway_Risk_Register_2.xlsx`'s "Risk Register" sheet (the single source of truth this RMF is seeded from), grouped in the same module order as §3. Nothing below is summarized, reworded, or omitted from the source row's text content.

### Module A — Core NEWS2 Scoring Engine

#### HAZARD-NEWS2-001

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 15
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** Incorrect / manipulated NEWS2 component or total score
- **Hazardous Situation:** Clinician relies on a NEWS2 score that does not match the RCP 2017 algorithm
- **Potential Harm:** Missed clinical deterioration or false escalation
- **Existing Risk Control / Mitigation:** Deterministic scoring in news2_calculator.py; total/risk_level are derived, non-settable properties (frozen dataclass)
- **Verification Evidence:** tests/regulatory/test_news2_safety.py; tests/unit/test_news2_calculator.py (all RCP 2017 boundaries)
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified against RCP NEWS2 2017 table cell-by-cell during Phase 5 review; all boundaries test-covered.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to news2_calculator.py
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-NEWS2-002

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 10
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** risk_level derivation error (e.g. HIGH downgraded to MEDIUM)
- **Hazardous Situation:** Total score correctly computed but risk_level property misclassifies urgency
- **Potential Harm:** Delayed emergency response
- **Existing Risk Control / Mitigation:** Explicit priority-ordered branching in NEWS2Score.risk_level; has_extreme_single_parameter rule implemented
- **Verification Evidence:** tests/regulatory/test_news2_safety.py
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified: HIGH>=7, MEDIUM 5-6, LOW_MEDIUM on any single param=3, LOW 1-4, NORMAL 0.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to NEWS2Score.risk_level
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-NEWS2-003

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 15
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** Partial/incomplete vital sign set silently scored
- **Hazardous Situation:** One or more mandatory NEWS2 parameters missing or artifact-flagged
- **Potential Harm:** False confidence in an incomplete risk assessment
- **Existing Risk Control / Mitigation:** NEWS2Calculator fails fast (NEWS2InsufficientDataError) rather than partially scoring
- **Verification Evidence:** tests/unit/test_news2_calculator.py::TestInsufficientDataHandling
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Fail-fast confirmed for RR and SpO2 missing cases and empty-vitals case.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _REQUIRED_VITAL_TYPES
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-SPO2-001

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 15
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** SpO2 Scale 1 applied to a confirmed hypercapnic (COPD) patient
- **Hazardous Situation:** Scale 1 systematically underscores SpO2 by up to 3 points vs. Scale 2
- **Potential Harm:** Missed deterioration in a COPD/hypercapnic patient
- **Existing Risk Control / Mitigation:** Explicit clinician-set PatientContext.spo2_scale; SCALE_1 default is conservative (never over-scores)
- **Verification Evidence:** tests/unit/test_news2_calculator.py::TestSpO2Scale1Scoring / TestSpO2Scale2Scoring
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** All Scale 1 and Scale 2 boundaries verified, incl. on-O2 vs on-air branching.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _score_spo2
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-RR-001

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 10
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** Respiratory rate scoring error at extreme values
- **Hazardous Situation:** RR <=8 or >=25 not scored as 3
- **Potential Harm:** Missed respiratory depression / failure
- **Existing Risk Control / Mitigation:** Deterministic boundary logic per RCP 2017 table
- **Verification Evidence:** tests/unit/test_news2_calculator.py::TestRespiratoryRateScoring
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** All boundaries verified.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _score_respiratory_rate
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-SBP-001

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 10
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** Systolic BP scoring error at extreme values
- **Hazardous Situation:** SBP <=90 or >=220 not scored as 3
- **Potential Harm:** Missed hypotensive shock or hypertensive emergency
- **Existing Risk Control / Mitigation:** Deterministic boundary logic per RCP 2017 table
- **Verification Evidence:** tests/unit/test_news2_calculator.py::TestSystolicBPScoring
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** All boundaries verified.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _score_systolic_bp
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-HR-001

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 10
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** Heart rate non-monotonic band regression (41-50 bpm = 1, then 51-90 = 0)
- **Hazardous Situation:** A refactor silently 'simplifies' the non-monotonic scoring curve
- **Potential Harm:** Missed bradycardia at 41-50 bpm
- **Existing Risk Control / Mitigation:** Explicit boundary logic with an inline regression-risk comment
- **Verification Evidence:** tests/unit/test_news2_calculator.py::TestHeartRateScoring (explicit 41/50 boundary case)
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Non-monotonic band explicitly verified.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _score_heart_rate
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-CON-001

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 10
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** Non-Alert AVPU state not scored as 3
- **Hazardous Situation:** Voice/Pain/Unresponsive/New-Confusion incorrectly scored 0-2
- **Potential Harm:** Missed acute neurological deterioration
- **Existing Risk Control / Mitigation:** Binary scoring (0 or 3 only) enforced by enum + explicit branch
- **Verification Evidence:** tests/unit/test_news2_calculator.py::TestConsciousnessScoring
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** All 4 non-Alert AVPU levels verified to score 3.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _score_consciousness
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-TEMP-001

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 10
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** Temperature scoring error at extreme values
- **Hazardous Situation:** Temp <=35.0 or >=39.1 not scored correctly
- **Potential Harm:** Missed hypothermia or hyperthermia
- **Existing Risk Control / Mitigation:** Deterministic boundary logic per RCP 2017 table
- **Verification Evidence:** tests/unit/test_news2_calculator.py::TestTemperatureScoring
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** All boundaries verified.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _score_temperature
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-O2-001

- **Severity:** 4 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 8
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 4
- **Hazard (Cause):** Supplemental O2 status not reflected in scoring
- **Hazardous Situation:** Patient on O2 scored as if on room air (or vice versa)
- **Potential Harm:** O2-masking of true SpO2 reserve goes uncompensated
- **Existing Risk Control / Mitigation:** Explicit +2 / 0 binary scoring, defaults conservatively to room air (False) when absent
- **Verification Evidence:** tests/unit/test_news2_calculator.py::TestSupplementalO2Scoring
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _score_supplemental_o2
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-TIME-001

- **Severity:** 3 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 9
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 3
- **Hazard (Cause):** Naive (non-timezone-aware) timestamps accepted
- **Hazardous Situation:** Sample ordering across timezone boundaries becomes ambiguous; wrong 'most recent' value selected for scoring
- **Potential Harm:** Stale or mis-ordered value silently used for a scoring parameter
- **Existing Risk Control / Mitigation:** tz-aware enforcement at both VitalSignSample.__post_init__ and the Pydantic API boundary
- **Verification Evidence:** domain/entities/vital_sign.py validation; api/v1/vitals.py field_validator
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Enforced at two independent layers (domain + API).
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any relaxation of tz-aware enforcement
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-ARCH-001

- **Severity:** 5 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 10
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 5
- **Hazard (Cause):** Pipeline stages executed out of order (NEWS2 scoring before DSP cleaning)
- **Hazardous Situation:** Refactor accidentally feeds un-cleaned data into NEWS2Calculator
- **Potential Harm:** Instrument-artifact values silently scored
- **Existing Risk Control / Mitigation:** VitalsOrchestrator Facade enforces DSP-then-NEWS2 order structurally
- **Verification Evidence:** tests/integration/* (order implicitly exercised by every orchestrator test)
- **Residual Risk Acceptability:** ALARP - monitored
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Order enforced by design; add an explicit order-assertion test as a future hardening item.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to VitalsOrchestrator.analyse
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-BOUNDS-001

- **Severity:** 4 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 12
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 4
- **Hazard (Cause):** Instrument-error / out-of-range values included in NEWS2 scoring
- **Hazardous Situation:** A physiologically-impossible value (sensor fault) is scored as if valid
- **Potential Harm:** Scoring corrupted by a non-physiological instrument artifact
- **Existing Risk Control / Mitigation:** PhysiologicalBoundsChecker excludes out-of-bounds values via is_within_physiological_bounds flag, consumed by NEWS2Calculator._extract_value
- **Verification Evidence:** tests/unit/test_artifact_rejector.py::TestPhysiologicalBoundsChecker
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified, including SBP=300 ceiling rationale (kept wide enough to admit the clinically-valid, NEWS2-scoreable 220 mmHg reading).
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _PHYSIOLOGICAL_BOUNDS
- **Phase Assignment:** Phase 5 - Closed

### Module B — DSP Artifact-Rejection Pipeline

#### HAZARD-DSP-001

- **Severity:** 3 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 9
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 3
- **Hazard (Cause):** Notch filter fails to attenuate 50/60 Hz mains interference
- **Hazardous Situation:** Residual mains interference remains in the cleaned waveform
- **Potential Harm:** Downstream waveform quality degraded (does not currently affect NEWS2 scoring - see architecture note)
- **Existing Risk Control / Mitigation:** Double-pass filtfilt notch to meet REQ-DSP-001 (>=95% RMS attenuation)
- **Verification Evidence:** tests/unit/test_artifact_rejector.py::TestDualNotchFilter
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified >=95% RMS attenuation at both 50 Hz and 60 Hz; 10 Hz physiological content >90% preserved.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to DualNotchFilter
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-DSP-002

- **Severity:** 2 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 6
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 2
- **Hazard (Cause):** Bandpass filter fails to remove DC offset / baseline wander, or attenuates in-band content
- **Hazardous Situation:** Baseline wander or in-band signal loss corrupts the cleaned waveform
- **Potential Harm:** Downstream waveform quality degraded
- **Existing Risk Control / Mitigation:** Butterworth bandpass per vital-sign-specific range
- **Verification Evidence:** tests/unit/test_artifact_rejector.py::TestBandpassFilter
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified: DC offset removed, >85% in-band content preserved.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _BANDPASS_RANGES
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-DSP-003

- **Severity:** 3 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 9
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 3
- **Hazard (Cause):** Hampel filter fails to detect a motion-artifact spike, OR falsely flags a genuine physiological feature (e.g. QRS peak)
- **Hazardous Situation:** Isolated (single-stage) Hampel filter behavior
- **Potential Harm:** False-negative or false-positive artifact rejection
- **Existing Risk Control / Mitigation:** Local median/MAD-based outlier detection with explicit QRS-preservation regression test
- **Verification Evidence:** tests/unit/test_artifact_rejector.py::TestHampelFilter (incl. test_preserves_physiological_qrs_slope)
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified in isolation. NOTE: see HAZARD-DSP-005 for a distinct, full-pipeline (post-bandpass) finding.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to HampelFilter
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-DSP-004

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** Referenced in source (tests/unit/test_artifact_rejector.py module docstring: 'ISO 14971 HAZARD-DSP-001 through HAZARD-DSP-004') without an independently identifiable distinct definition in the code reviewed
- **Hazardous Situation:** Documentation/traceability gap, not a functional defect
- **Potential Harm:** N/A - administrative gap
- **Existing Risk Control / Mitigation:** N/A
- **Verification Evidence:** N/A
- **Residual Risk Acceptability:** N/A
- **Status:** Open - Requires Action
- **Decision / Rationale:** Recommend the risk owner either (a) retire this ID as a duplicate reference, or (b) formally define its distinct scope at the next risk register review.
- **Decision Owner:** Quality/Regulatory
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Next scheduled risk register review
- **Phase Assignment:** Phase 6 - Backlog

#### HAZARD-DSP-005

- **Severity:** 3 &nbsp;|&nbsp; **Probability (pre-mitigation):** 4 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 12
- **Probability (post-mitigation):** 4 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 12
- **Hazard (Cause):** HampelFilter loses local-outlier sensitivity to short-duration artifacts once they have passed through the 0.5 Hz-cutoff, order-3 Butterworth bandpass stage (current Notch->Bandpass->Hampel order)
- **Hazardous Situation:** A genuine short-duration motion artifact (e.g. brief lead movement) occurs in a waveform channel; by the time Hampel runs (3rd of 3 stages), the artifact's local statistical signature has been smoothed below Hampel's window_radius=5 detection threshold
- **Potential Harm:** Bounded today: NEWS2 scoring is verified DECOUPLED from waveform data (scalar NEWS2 inputs come only from companion NM OBX segments — see HAZARD-BOUNDS-001 / TestWaveformNeverFeedsNews2Score). Current harm pathway is limited to the exposed cleaned_waveform and dsp-outlier-count FHIR extension under-reporting artifact presence, which could mislead a downstream consumer that independently trusts that data. SEVERITY MUST BE RE-ESCALATED if any future feature derives scoring or clinical display directly from waveform/outlier-count data.
- **Existing Risk Control / Mitigation:** None applied (stage order intentionally NOT changed - see Decision). HampelFilter itself confirmed correct in isolation (pre-bandpass) - see HAZARD-DSP-003.
- **Verification Evidence:** tests/integration/test_hl7v2_waveform_pipeline.py::TestKnownArtifactDetectionLimitation (xfail(strict=True), reproducible even at 200x signal amplitude)
- **Residual Risk Acceptability:** Requires justification (index remains in Unacceptable band; accepted below as a documented exception, not via risk reduction)
- **Status:** Open - Accepted Residual Risk
- **Decision / Rationale:** Engineering decision recorded 2026-08-06: DO NOT reorder DSP pipeline stages (Notch->Bandpass->Hampel) to preserve the validated, already-tested sequencing. Risk accepted as-is for the current release under the compensating condition that severity is re-assessed before any feature relies on waveform-derived data for scoring or independent clinical display. NOTE: this chat-recorded decision is provisional pending formal ratification by the organization's designated Clinical Safety / Risk Management responsible person under its QMS before being cited in any regulatory submission.
- **Decision Owner:** [Project Engineering Lead - per this conversation] / pending Clinical Safety Officer ratification
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Before any feature derives scoring/display from waveform or outlier-count data; or next scheduled risk review
- **Phase Assignment:** Phase 5 - Closed (Accepted Risk; ratification pending, see QMS-002)

#### HAZARD-DSP-006

- **Severity:** 2 &nbsp;|&nbsp; **Probability (pre-mitigation):** 5 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 10
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** Persistent, artifact-INDEPENDENT flagged samples at the tail of every array processed through Notch->Bandpass->Hampel (apparent filtfilt edge/padding effect)
- **Hazardous Situation:** The last ~2 samples of a filtered waveform are flagged as outliers by Hampel regardless of whether any genuine artifact is present
- **Potential Harm:** False-positive artifact flag (opposite direction from HAZARD-DSP-005); low direct harm — errs toward caution, not toward missing a real artifact — but could cause unnecessary alerting or under-reported effective sample count if consumed literally
- **Existing Risk Control / Mitigation:** None applied yet — newly identified during Phase 5 HL7 waveform integration work, not yet triaged
- **Verification Evidence:** Reproduced in every trial during construction of tests/integration/test_hl7v2_waveform_pipeline.py (see chat record); not yet formally captured as an automated regression test
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - Awaiting Decision
- **Decision / Rationale:** NEWLY IDENTIFIED, NOT YET ADDRESSED BY THE PROJECT OWNER. Distinct from HAZARD-DSP-005 (opposite failure direction) - requires its own explicit decision, not implicitly covered by the HAZARD-DSP-005 acceptance.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Awaiting triage decision
- **Phase Assignment:** Phase 6 - Backlog

#### HAZARD-DSP-007

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** NaN/Inf values silently accepted by the DSP artifact-rejection pipeline instead of being explicitly rejected -- found during Phase 5-Stream Section D's edge-case sweep, not previously documented (distinct from HAZARD-DSP-001/002/003, the notch/bandpass/Hampel filters' own correctness, and HAZARD-DSP-004, an unrelated prior documentation-only finding already resolved)
- **Hazardous Situation:** (a) Waveform path: a NaN/Inf sample anywhere in a waveform array was NOT rejected by DualNotchFilter/BandpassFilter/HampelFilter -- scipy's filtfilt propagates a single NaN/Inf sample through its ENTIRE output via IIR feedback, with no exception raised. (b) Scalar path, ASYMMETRIC by parameter -- verified empirically against the pre-fix code for all five threshold-ladder NEWS2 parameters, not assumed: PhysiologicalBoundsChecker previously compared NaN with plain </>, both always False for NaN (IEEE-754), so a NaN scalar was silently reported is_within_physiological_bounds=True and reached NEWS2Calculator._score_*(). Each scorer's threshold-ladder falls through NaN to whichever band its `if/elif` chain ends on -- NOT a uniform effect:
  - HEART_RATE, RESPIRATORY_RATE, SYSTOLIC_BP: ladder ends on the HIGHEST-severity band -> NaN scores 3/3 (confirmed: HR ladder falls through all 5 thresholds to the bare `return 3`, identical to a genuine ≥131 bpm tachycardia).
  - TEMPERATURE_CELSIUS: ladder ends on its second-highest band -> NaN scores 2/3.
  - SPO2 (Scale 1): ladder ends on the NORMAL band -> NaN scores 0/3, i.e. indistinguishable from a genuinely healthy ≥96% reading. Confirmed via full pipeline repro (VitalSignProcessor.process() -> NEWS2Calculator.calculate()): otherwise-normal RR/HR/SBP/Temp + SpO2=NaN pre-fix produced spo2_score=0, total=0, risk_level=NORMAL -- no exception, no warning, no distinguishing signal anywhere in the returned NEWS2Score.
- **Potential Harm:** SEVERITY IS DIRECTION-DEPENDENT, NOT UNIFORM -- the two halves of this hazard have OPPOSITE clinical risk profiles and must be sign-off-reviewed as such, not as one generic 'NaN handling bug':
  - SAFE-ISH direction (HR, RR, SBP, and to a lesser extent Temp): NaN fails TOWARD false alarm -- a NaN reading is scored as if it were a genuine severe abnormality (e.g. HR treated as ≥131 bpm tachycardia), which would over-escalate total NEWS2 score and risk_level. Costly (unnecessary clinical attention) but NOT the silent-harm direction -- a clinician reviewing an escalated advisory score would investigate and quickly find the underlying data is invalid, not act on a false negative.
  - DANGEROUS direction (SpO2, Scale 1): NaN fails TOWARD FALSE REASSURANCE -- a NaN SpO2 (e.g. probe disconnected, sensor fault) would have been silently scored identically to a healthy reading, excluded from nothing, flagged nowhere, potentially masking a real desaturation event. This is the classic ISO 14971 'missed deterioration' harm pattern (same shape as HAZARD-NEWS2-003), and is the direction that actually matters clinically for this hazard.
  - WIRE-LEVEL confirmation (beyond the NEWS2 score itself): the raw NaN value, pre-fix, DID reach the FHIR Observation's valueQuantity.value field as a plain, unflagged number (no dataAbsentReason, no physiological-bounds-flag extension) -- confirmed directly against ObservationBuilder.build(). Delivery-path behavior differed further: the HTTP JSON API (POST /api/v1/vitals) was incidentally protected -- Starlette's JSONResponse.render() calls json.dumps(..., allow_nan=False), so the corrupted Bundle was rejected with a generic 422 rather than delivered (confirmed via a real ASGI request). MQTT publishing (mqtt_publisher.py) and FHIR Subscription webhook delivery (subscription_dispatcher.py) both call plain json.dumps(bundle) (default allow_nan=True, NOT protected) -- pre-fix, these would have SILENTLY transmitted a bare, non-RFC-8259 `NaN` JSON token to an external cloud consumer or a hospital's own EHR Subscription endpoint, with zero indication anything was wrong. This was incidental protection on one path, not a designed safeguard, and did not exist on the other two.
- **Existing Risk Control / Mitigation:** FIXED this session, in domain/services/artifact_rejector.py: (1) a shared _require_finite() check added to DualNotchFilter.apply, BandpassFilter.apply, and HampelFilter.apply_with_mask -- each now explicitly raises ValueError on any non-finite sample, consistent with (and using the same exception type as) each filter's pre-existing empty/too-short-signal guards, so signal_processor.py's existing per-stage try/except degrade-and-log orchestration handles it with no orchestration-level change required. (2) PhysiologicalBoundsChecker.check() now explicitly rejects math.isnan(value) BEFORE any bound comparison and before the 'no bounds configured' early return, for every VitalSignType -- closing the SOURCE of the asymmetry described in column D, for ALL five parameters uniformly (the fix itself is parameter-agnostic; only the PRE-FIX failure mode was asymmetric). This also closes the FHIR/wire-level leak at its source (is_within_physiological_bounds=False triggers dataAbsentReason/physiological-bounds-flag universally in ObservationBuilder, upstream of ALL THREE delivery paths -- HTTP API, MQTT, Subscription webhook -- so no downstream serializer's allow_nan behavior matters anymore). (3) Also newly explicit-checked: BandpassFilter.apply raises a domain-specific message when an implausibly low sampling_rate_hz Nyquist-clamps its passband into an inverted/degenerate band.
- **Verification Evidence:** tests/unit/test_artifact_rejector.py::TestNonFiniteRejection, ::TestZeroLengthAndSingleSampleArrays, ::TestSamplingRateExtremes, and the 4 NaN/Inf TestPhysiologicalBoundsChecker tests; tests/unit/test_signal_processor_edge_cases.py (orchestrator-level); tests/regulatory/test_news2_safety.py::TestHazardDsp007NanSpo2ExcludedNotScoredNormal (full-pipeline VitalSignProcessor->NEWS2Calculator repro of the dangerous-direction case specifically -- proven failing against pre-fix code, then passing, both runs captured); tests/integration/test_fhir_bundle.py::TestObservationBuilderHazardDsp007NanNeverReachesOutput (confirms the raw value never reaches valueQuantity in FHIR output, and that json.dumps() with default allow_nan=True -- the actual MQTT/webhook serialization behavior -- never emits a bare NaN token).
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - INTERIM engineering sign-off recorded 2026-08-10 (see docs/CSO_Role_Appointment_Brief.md §5), NOT a final/clinical closure. Fix + defense-in-depth (allow_nan=False at every external-transmission boundary) applied and verified this session (failing-then-passing tests, both directions of the asymmetry independently reproduced pre-fix). Credentialed-CSO ratification of the SpO2/false-reassurance half specifically (see column D) still required before Phase 5-Stream is considered clinically closed.
- **Decision / Rationale:** INTERIM ENGINEERING SIGN-OFF RECORDED (NOT a clinical/final closure): docs/CSO_Role_Appointment_Brief.md §5, Effective Date 2026-08-10 -- Housam Abouelreish, project owner, self-appointed Interim/Acting Engineering Sign-Off Authority. That record states explicitly, and is repeated here so it is not lost to a status-column summary: the appointee is NOT clinically credentialed per the same document's own §2 bar; this is a self-appointment with no Quality Manual delegation behind it (none exists at this company stage); scope is LIMITED to engineering-identified hazards (this one and HAZARD-STREAM-012) and explicitly does NOT substitute for credentialed clinical review before any patient-facing production use of the NEWS2/DSP pipeline. A credentialed CSO MUST formally ratify or revisit this hazard before Phase 5-Stream is considered clinically closed -- this entry remains OPEN pending that ratification, not resolved by this interim sign-off.
- **Decision Owner:** Housam Abouelreish (project owner) -- INTERIM, non-clinically-credentialed
- **Decision Date:** 2026-08-10
- **Next Review Trigger:** Credentialed-CSO ratification of this interim sign-off (see docs/CSO_Role_Appointment_Brief.md §5's forward-reference) -- REQUIRED, not optional, before clinical closure. Reviewer should prioritize the SpO2 (false-reassurance/masked-deterioration) half of column D.
- **Phase Assignment:** Phase 5-Stream - Backlog

### Module C — HL7v2 Protocol Adapter

#### HAZARD-PROTO-001

- **Severity:** 4 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 12
- **Probability (post-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 8
- **Hazard (Cause):** Vendor dialect misidentification causes OBX segments to be silently dropped
- **Hazardous Situation:** Monitor MSH-3 / OBX-3 code not recognized by adapter tables
- **Potential Harm:** A vital sign parameter is missing from scoring input (mitigated further downstream by HAZARD-NEWS2-003 fail-fast)
- **Existing Risk Control / Mitigation:** Explicit MSH-3 vendor map + LOINC fallback for all OBX-3 identifiers; every skip is logged with an actionable warning
- **Verification Evidence:** tests/integration/test_hl7v2_adapter.py (Philips/GE/Draeger/Mindray/generic cases)
- **Residual Risk Acceptability:** ALARP - requires ongoing table maintenance
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Residual probability not fully eliminable — new/unlisted vendor codes will occur in real deployments; requires living maintenance of _VENDOR_TO_TYPE.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Each new monitor model/vendor onboarded
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-PROTO-002

- **Severity:** 3 &nbsp;|&nbsp; **Probability (pre-mitigation):** 4 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 12
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** HL7 v2.x has no standardized field for continuous-waveform sampling rate
- **Hazardous Situation:** Adapter resolves sampling rate via OBX-6 override or a documented per-type default table, not a universal standard
- **Potential Harm:** Incorrect sampling rate corrupts every downstream DSP stage (notch target frequency, bandpass range, Hampel timing) for that channel
- **Existing Risk Control / Mitigation:** Explicit, logged resolution order (OBX-6 override -> documented default); every use is recorded in parse_warnings with its source
- **Verification Evidence:** infrastructure/adapters/hl7v2_adapter.py::_resolve_sampling_rate_hz; tests/integration/test_hl7v2_adapter.py override/default cases
- **Residual Risk Acceptability:** Contingent - see Status
- **Status:** Open - Requires Action
- **Decision / Rationale:** NOT yet mitigated fleet-wide. Default table MUST be validated against each specific connected monitor model's interface spec before that model's waveform pipeline is used clinically. Gate item, not a permanent residual risk.
- **Decision Owner:** Regulatory/Clinical Engineering (site validation)
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Before clinical use of the waveform pipeline against any new monitor model
- **Phase Assignment:** Phase 6 - Backlog

#### HAZARD-WAVE-001

- **Severity:** 3 &nbsp;|&nbsp; **Probability (pre-mitigation):** 3 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 9
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 3
- **Hazard (Cause):** Partially-corrupted waveform array silently truncated or reindexed
- **Hazardous Situation:** One non-numeric sample among many valid ones in an OBX-5 NA/ED array
- **Potential Harm:** Sample timing corrupted ahead of notch/bandpass/Hampel processing
- **Existing Risk Control / Mitigation:** Fail-whole-array rule: any single unparseable sample rejects the entire segment (never partial)
- **Verification Evidence:** tests/integration/test_hl7v2_adapter.py::test_corrupted_waveform_sample_rejects_whole_array
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _parse_numeric_array
- **Phase Assignment:** Phase 5 - Closed

### Module D — FHIR Output Layer

#### HAZARD-FHIR-001

- **Severity:** 4 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 8
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 4
- **Hazard (Cause):** Incorrect LOINC/SNOMED code in Observation.code
- **Hazardous Situation:** Downstream EHR/CDSS misclassifies the observation type
- **Potential Harm:** Clinical record corruption / wrong parameter displayed
- **Existing Risk Control / Mitigation:** Single source-of-truth mapping table (_VITAL_SIGN_FHIR_MAP)
- **Verification Evidence:** tests/integration/test_fhir_bundle.py; test_fhir_conformance.py
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to _VITAL_SIGN_FHIR_MAP
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-FHIR-002

- **Severity:** 4 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 8
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 4
- **Hazard (Cause):** NEWS2 total/score encoded incorrectly in FHIR (e.g. float rounding)
- **Hazardous Situation:** Downstream CDSS misreads the total score due to encoding error
- **Potential Harm:** Wrong risk level acted upon downstream
- **Existing Risk Control / Mitigation:** valueInteger (not float) for total; 7 component sub-observations for full transparency/audit
- **Verification Evidence:** tests/integration/test_fhir_bundle.py
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to NEWS2ObservationBuilder
- **Phase Assignment:** Phase 5 - Closed

#### HAZARD-FHIR-003

- **Severity:** 2 &nbsp;|&nbsp; **Probability (pre-mitigation):** 2 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 4
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 2
- **Hazard (Cause):** Bundle.timestamp missing
- **Hazardous Situation:** Downstream CDSS cannot correlate observations with the clinical encounter time
- **Potential Harm:** Loss of audit/temporal correlation
- **Existing Risk Control / Mitigation:** Bundle.timestamp always set to UTC now, even on empty-entries bundles
- **Verification Evidence:** tests/integration/test_fhir_bundle.py
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to BundleAssembler.assemble
- **Phase Assignment:** Phase 5 - Closed

### Module E — Cross-Cutting API Security

#### HAZARD-CORS-001

- **Severity:** 3 &nbsp;|&nbsp; **Probability (pre-mitigation):** 4 &nbsp;|&nbsp; **Risk Index (pre-mitigation):** 12
- **Probability (post-mitigation):** 1 &nbsp;|&nbsp; **Risk Index (post-mitigation):** 3
- **Hazard (Cause):** CORS allow_origins=['*'] in main.py
- **Hazardous Situation:** Any web origin can call the API carrying patient vitals/identifiers
- **Potential Harm:** Unauthorized cross-origin data exposure
- **Existing Risk Control / Mitigation:** Explicit CORS_ALLOWED_ORIGINS environment-variable allow-list, enforced fail-closed at application startup: get_cors_allowed_origins() (src/config.py:373-388) raises ValueError on a wildcard '*', an empty value, or a whitespace/commas-only value -- called directly at create_app() time (src/main.py:205-211), so a misconfigured value prevents the app from starting at all, not just a runtime warning. When CORS_ALLOWED_ORIGINS is simply unset (not misconfigured, absent), falls back to a narrow single dev origin (http://localhost:3000), never a wildcard -- the unset-in-production failure mode is a loud, visible CORS rejection in the browser, not silent data exposure. Also hardened beyond the hazard's original wording: allow_credentials=False, allow_methods restricted to [GET, POST], allow_headers restricted to an explicit list (main.py:205-211).
- **Verification Evidence:** src/config.py:373-388 (get_cors_allowed_origins); src/main.py:205-211 (CORSMiddleware wiring); tests/unit/test_config.py -- TestGetCorsAllowedOriginsDefault, TestGetCorsAllowedOriginsValid, TestGetCorsAllowedOriginsRejectsUnsafeValues (11 tests total, all passing as of 2026-08-10: default fallback, multi-origin parsing, whitespace/trailing-comma handling, and every unsafe-input rejection case -- bare wildcard, wildcard mixed with real origins, empty string, whitespace-only, commas-only).
- **Residual Risk Acceptability:** Acceptable
- **Status:** Closed - Mitigated
- **Decision / Rationale:** Verified 2026-08-10 (Phase 5-Stream Section E RMF compilation): the fail-closed mechanism structurally eliminates the wildcard-CORS hazard as originally defined (the code can no longer start with allow_origins=['*']). Fix commit 7aa2531 (2026-08-06 13:07:50) predates this register update -- QMS-001_DHF_Structure.md §4.2, written after that commit, already independently recorded this same conclusion (✅ Mitigated); this row was simply never reconciled with the code until now. Per-deployment selection of the ACTUAL production origin list remains an operational/deployment-configuration task for each deployer -- normal and expected for a template gateway product, not a residual code defect, and not a reason to keep this hazard open.
- **Decision Owner:** Engineering
- **Decision Date:** 2026-08-06
- **Next Review Trigger:** Any change to get_cors_allowed_origins() or the CORSMiddleware wiring in main.py
- **Phase Assignment:** Phase 6 - Closed

### Module F — Streaming & Provisioning Infrastructure (Phase 5-Stream)

#### HAZARD-STREAM-006

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** FHIR Subscription channel.endpoint is a caller-supplied URL; outbound webhook delivery to it is SSRF-exposed beyond validate_webhook_endpoint()'s baseline deny-list
- **Hazardous Situation:** A registered rest-hook endpoint resolves (directly, or via DNS rebinding after registration-time validation passed) to an internal/private address
- **Potential Harm:** Clinical Bundle data delivered to, or internal-network reconnaissance via, an unintended internal endpoint
- **Existing Risk Control / Mitigation:** validate_webhook_endpoint() baseline deny-list (loopback/link-local/private/reserved/multicast IP literals, blocked hostnames, https-only default); enforced at registration time (url_safety.py), trusted (not re-checked) by subscription_dispatcher.py at delivery time; redirects not followed by default
- **Verification Evidence:** tests/unit/test_url_safety.py
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - PROPOSED, pending human security/risk-management sign-off
- **Decision / Rationale:** Best-effort deny-list only, by the module's own docstring -- explicitly NOT a guarantee against DNS rebinding (hostname resolves safely at registration, rebinds to an internal IP before/at delivery time).
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Before any deployment where webhook subscribers are outside an operator-trusted allowlist
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-007

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** Subscription criteria accepted at registration but never actually matches any Bundle
- **Hazardous Situation:** Subscriber believes they are receiving live delta notifications, but criteria (e.g. a misspelled patient_id) never matches -- indistinguishable from 'no events have occurred yet'
- **Potential Harm:** Subscriber-side missed/delayed clinical notification, mistaken for normal quiet monitoring
- **Existing Risk Control / Mitigation:** MAX_CONSECUTIVE_DELIVERY_ERRORS-based error state moves a subscription that FAILS delivery to a non-matched 'error' status (no reactivation path -- delete+recreate only); does NOT address criteria that is well-formed but simply never matches (no delivery is ever attempted, so the failure counter never increments)
- **Verification Evidence:** tests/unit/test_subscription_registry.py
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - PROPOSED, pending human security/risk-management sign-off
- **Decision / Rationale:** No liveness/health-check signal exists for 'this subscription has never fired even once' -- gap remains per the module's own docstring.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Before Subscription delivery is relied on as a sole notification channel without an independent liveness check
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-008

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** Failed Subscription delivery is attempted once and never retried or requeued
- **Hazardous Situation:** A subscriber endpoint is transiently down (deploy, restart, brief network blip) at the exact moment a matching Bundle is produced
- **Potential Harm:** Subscriber misses that specific clinical delta permanently for that occurrence (contrast: the MQTT edge->cloud path DOES requeue undelivered telemetry indefinitely, per HAZARD-STREAM-003)
- **Existing Risk Control / Mitigation:** Consecutive-failure count is tracked per subscription (subscription_registry.py); after MAX_CONSECUTIVE_DELIVERY_ERRORS the subscription moves to 'error' status. No requeue-and-retry of the individual missed delivery -- deliberate per the module's docstring (fire-and-forget, must never block delivery to another subscriber or the producing caller)
- **Verification Evidence:** tests/unit/test_subscription_dispatcher.py
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - PROPOSED, pending human security/risk-management sign-off
- **Decision / Rationale:** Design tradeoff explicitly documented in source, not yet reviewed by a human risk owner against clinical-notification requirements.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Before Subscription delivery is relied on where a single missed delta is clinically significant
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-009

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** Missing authentication on FHIR Subscription CRUD routes (POST/GET/GET-list/DELETE /api/v1/fhir/Subscription)
- **Hazardous Situation:** Any caller (no credential required, as originally shipped) could register/read/delete rest-hook Subscriptions, including reading other subscribers' channel.header webhook credentials via GET
- **Potential Harm:** Unauthorized registration of a data-exfiltration webhook, disclosure of other subscribers' webhook credentials, or deletion of a legitimate subscriber's Subscription
- **Existing Risk Control / Mitigation:** Pre-shared-secret auth dependency added to all 4 routes this session (commit cb928ed): config.get_fhir_subscription_registration_secret() fail-closed (503 if unconfigured); secrets.compare_digest constant-time comparison; 401 vs 503 distinguished; WWW-Authenticate header
- **Verification Evidence:** tests/integration/test_fhir_subscription_api.py::TestRegistrationAuthentication
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - mitigation applied this session, NOT self-closed, pending human sign-off
- **Decision / Rationale:** Per this session's own commit message: 'No hazard marked resolved without human sign-off.' Code fix shipped; formal risk acceptance still requires the designated Clinical Safety / Risk Management responsible person.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Next scheduled risk register review
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-010

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** Enrollment-token brute-force/replay against the provisioning bootstrap endpoint (device-identity zero-touch enrollment)
- **Hazardous Situation:** An attacker obtains or guesses a single-use enrollment token and enrolls an illegitimate device, receiving a valid mTLS device certificate -- i.e. device impersonation, not just unauthorized resource access
- **Potential Harm:** An illegitimate device gains a trusted mTLS identity able to participate in the fleet (submit telemetry, be treated as a genuine edge appliance by the control plane)
- **Existing Risk Control / Mitigation:** Device-side: bounded/backed-off retries (PROVISIONING_MAX_ENROLL_ATTEMPTS, default 5); token never logged; 401/403/409 never retried. Server-authentication leg (added this session): TLS now pinned to the control plane's specific CA bundle (config.get_provisioning_ca_bundle_path(), fail-closed) instead of the system default trust store; optional independently-sourced expected_hostname construction-time check available. PRIMARY mitigation (token single-use enforcement, rate-limiting) is necessarily control-plane-side, out of this repo's scope.
- **Verification Evidence:** tests/integration/test_enrollment_client.py; tests/integration/test_enrollment_client_ca_pinning.py (real local-TLS CA-pinning tests, added this session); tests/unit/test_bootstrap_cli.py
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - PROPOSED, pending human security/risk-management sign-off (CA-pinning mitigation narrows, does not close)
- **Decision / Rationale:** Control-plane-side token enforcement (single-use, rate-limiting) cannot be verified from this repo -- it is the device/client side of the protocol only.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Before any production enrollment token is issued; when the control plane implementation is available for review
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-011

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** Revocation of a decommissioned/compromised edge appliance's mTLS certificate
- **Hazardous Situation:** A device certificate needs to stop being trusted before its natural expiry (decommission, suspected compromise)
- **Potential Harm:** A revoked/decommissioned device retains a working clinical-data-capable identity for longer than the operator intended
- **Existing Risk Control / Mitigation:** Short-lived certs (control-plane policy) + periodic reattest() (401/403 -> CertStore.quarantine()). UPDATE this session: reattest() is now actually SCHEDULED via reattestation_loop(), a background asyncio.Task started in main.py's ASGI lifespan when PROVISIONING_ENABLED=true (previously implemented but never called from anywhere in the codebase). Two gaps remain even now that it runs on schedule: (1) an already-open mTLS session is not torn down mid-flight by a revocation discovered on the NEXT tick; (2) a network-partitioned device cannot complete reattest() at all and keeps its last-known-valid cert until natural expiry.
- **Verification Evidence:** tests/integration/test_enrollment_client.py::TestReattestRevocation; tests/unit/test_reattestation.py; tests/integration/test_main_reattestation_lifespan.py (all added this session)
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - PROPOSED, pending human security/risk-management sign-off (scheduling gap closed this session; 2 gaps remain, see mitigation column)
- **Decision / Rationale:** Human review requested on whether the mid-session and network-partition gaps require a stronger fail-closed policy (e.g. 'stop operating if reattest has not succeeded in N hours').
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Before any deployment with a compliance requirement stricter than best-effort periodic revocation checking
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-012

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** Root CA (step-ca, modules/ca) private key custody and the fleet-wide blast radius of its compromise -- distinct from the device-level HAZARD-STREAM-010/011, which concern a single device's token/certificate, not the CA that issues every device's certificate
- **Hazardous Situation:** The CA's root private key (held only inside step-ca's own process/EFS volume) is exfiltrated or misused, OR an operator cannot retrieve the CA's public root certificate through the channel the design documentation itself describes
- **Potential Harm:** Compromise: an attacker able to mint certificates trusted by every device in the fleet simultaneously -- a single-point failure with fleet-wide, not per-device, blast radius. Over-restriction (gap 1, now resolved): an operator following DESIGN.md §1's own documented bootstrap step could not actually complete it without separate, undocumented VPN/bastion access -- a design-documentation/implementation inconsistency, not a compromise path itself, but a real operational gap
- **Existing Risk Control / Mitigation:** Mitigated: EFS at-rest encryption (aws_efs_file_system.ca_state, encrypted=true); the CA private key never leaves step-ca's own process (nothing in this Terraform handles it directly). GAP 1 -- RESOLVED this session: /roots.pem used to share network exposure with step-ca's admin/signing/ACME API (same port, SG, internal-only NLB), over-restricting DESIGN.md §1's documented bootstrap curl to VPN/bastion-only reachability. Resolved via a new modules/roots-proxy (public ALB + Lambda) permitting GET /roots.pem ONLY -- every other path/method hits the ALB's default_action (403) before ever reaching a Lambda; step-ca's own NLB, listener, and security-group ingress rule are unchanged. GAP 2 -- OPEN, NOT addressed this session: no fleet-wide CA-compromise recovery runbook exists (no re-issuance-at-scale process, no plan for physically-deployed edge appliances unable to promptly reach a re-pointed control plane, no CRL/OCSP or equivalent revocation signal beyond HAZARD-STREAM-011's per-device reattest() gaps). A device unable to re-enroll during such an event keeps operating on stale local data forwarding -- a clinical availability concern, not just an infrastructure one.
- **Verification Evidence:** infra/terraform/DESIGN.md §4 (full writeup + manual verification runbook); modules/ca/main.tf's HAZARD-STREAM-012 docstring; modules/roots-proxy/main.tf (the gap-1 fix); envs/dev/main.tf's MANUAL BOOTSTRAP STEPS #9 (documented manual verification -- no terraform/cloud account available in this sandbox to assert this with an automated test against real AWS resources)
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - INTERIM engineering sign-off recorded 2026-08-10 (see docs/CSO_Role_Appointment_Brief.md §5), NOT a final/clinical closure. Gap 1 (network over-restriction vs. documented bootstrap flow) RESOLVED and covered by this interim sign-off's engineering scope. Gap 2 (fleet-wide CA-compromise recovery runbook) remains OPEN and unaddressed regardless of sign-off status. Credentialed-CSO ratification of this entire hazard (both gaps) still required before Phase 5-Stream is considered clinically closed.
- **Decision / Rationale:** INTERIM ENGINEERING SIGN-OFF RECORDED (NOT a clinical/final closure): docs/CSO_Role_Appointment_Brief.md §5, Effective Date 2026-08-10 -- Housam Abouelreish, project owner, self-appointed Interim/Acting Engineering Sign-Off Authority. That record states explicitly, and is repeated here so it is not lost to a status-column summary: the appointee is NOT clinically credentialed per the same document's own §2 bar; this is a self-appointment with no Quality Manual delegation behind it (none exists at this company stage); scope is LIMITED to engineering-identified hazards (this one and HAZARD-STREAM-012) and explicitly does NOT substitute for credentialed clinical review before any patient-facing production use of the NEWS2/DSP pipeline. A credentialed CSO MUST formally ratify or revisit this hazard before Phase 5-Stream is considered clinically closed -- this entry remains OPEN pending that ratification, not resolved by this interim sign-off.
- **Decision Owner:** Housam Abouelreish (project owner) -- INTERIM, non-clinically-credentialed
- **Decision Date:** 2026-08-10
- **Next Review Trigger:** Credentialed-CSO ratification of this interim sign-off (see docs/CSO_Role_Appointment_Brief.md §5's forward-reference) -- REQUIRED, not optional, before clinical closure. Also: before any production cutover of modules/ca; when a fleet-wide CA-compromise recovery runbook is drafted (gap 2).
- **Phase Assignment:** Phase 5-Stream - Backlog

**UPDATE 2026-08-10 (this correction, source-traceability only, no change to the above):** a
cross-reference comment naming HAZARD-STREAM-012 was added in
`src/infrastructure/provisioning/enrollment_client.py`, at the exact line the device places its
cryptographic trust in the CA bundle. This closes a register/design-doc-to-`src/`-code dead end
(this hazard previously had zero presence in `src/`, unlike every other hazard in this module)
-- it does not restate this record, and does not change any Sev/Prob/Status field above.

#### HAZARD-STREAM-001

*(Added 2026-08-10, this correction — see the front-matter correction note. Transcribed
directly from the Risk Register row entered the same day, which was itself transcribed from
`src/infrastructure/streaming/mllp_listener.py`'s module docstring — not summarized further or
independently reworded here.)*

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** MLLP frames arrive as raw TCP bytes with no integrity check beyond the start-block/end-block/carriage-return framing characters -- a malformed, truncated, or concatenated frame passed to HL7v2Adapter risks the parser treating corrupted or partial data as complete, valid HL7.
- **Hazardous Situation:** Byte-level corruption inside an otherwise well-framed MLLP message (e.g. a bit-flip) reaches HL7v2Adapter.parse() -- HL7 v2.x has no per-message checksum.
- **Potential Harm:** Corrupted vital-sign data silently parsed and scored as if valid.
- **Existing Risk Control / Mitigation:** Framing validated strictly (VT...FS CR) via asyncio readuntil() before any bytes reach the parser; incomplete-on-close or non-UTF-8 frames rejected (NAK, discarded), never passed to the parser in partial/best-effort form; oversized frames (default cap 1 MiB) rejected rather than buffered unbounded; stray pre-start-block bytes discarded and logged. NOT mitigated: in-frame byte-level corruption -- residual risk inherent to the wire protocol, not specific to this listener.
- **Verification Evidence:** tests/integration/test_mllp_listener.py::TestMalformedFrameRejected; ::TestOversizedFrameRejected
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - Deferred by Scope Decision
- **Decision / Rationale:** Referenced in source (mllp_listener.py module docstring) since Phase 5 Section A but explicitly deferred, by project-owner scope decision, from entry as a scored Risk Register row (see Process Items PROC-002). Entered as a row this session (2026-08-10) to close the source-tagged/register-absent gap surfaced by docs/RTM-001_Requirements_Traceability_Matrix.md §6 -- entry alone, not risk evaluation; Sev/Prob remain unscored pending human risk-management review.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Human risk-management sign-off on residual in-frame corruption risk; any change to mllp_listener.py framing logic
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-002

*(Added 2026-08-10, this correction. Transcribed from the Risk Register row, itself transcribed
from `src/infrastructure/streaming/ring_buffer.py`'s module docstring.)*

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** During a prolonged WAN/cloud outage, telemetry can accumulate faster than it can be forwarded once connectivity resumes.
- **Hazardous Situation:** An unbounded StoreAndForwardRingBuffer risks unbounded edge-appliance memory growth; a bounded buffer that silently discards on overflow risks losing clinical telemetry with no audit trail.
- **Potential Harm:** Clinical telemetry loss during extended outages, or edge-appliance memory exhaustion.
- **Existing Risk Control / Mitigation:** Fixed-capacity buffer with explicit drop-oldest-on-overflow policy; every drop counted AND logged at WARNING level, so loss is visible in the audit trail even though the dropped payload itself is gone. Does NOT eliminate the residual risk of telemetry loss during extended outages -- only makes it observable/countable. Buffer capacity sizing (how much outage a given clinical deployment must tolerate before loss begins) is an unresolved clinical risk-acceptance decision.
- **Verification Evidence:** tests/unit/test_ring_buffer.py::TestOverflowDropOldest
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - Deferred by Scope Decision
- **Decision / Rationale:** Referenced in source (ring_buffer.py module docstring) since Phase 5 Section A but explicitly deferred, by project-owner scope decision, from entry as a scored Risk Register row (see Process Items PROC-002). Entered as a row this session (2026-08-10) to close the source-tagged/register-absent gap surfaced by docs/RTM-001_Requirements_Traceability_Matrix.md §6 -- entry alone, not risk evaluation; Sev/Prob remain unscored pending human risk-management review.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Production buffer-capacity sizing decision; any change to StoreAndForwardRingBuffer's overflow policy
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-003

*(Added 2026-08-10, this correction. Transcribed from the Risk Register row, itself transcribed
from `src/infrastructure/streaming/mqtt_publisher.py`'s module docstring.)*

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** The cloud MQTT broker may be unreachable (WAN outage, broker down, auth failure) for an extended period.
- **Hazardous Situation:** A publisher that raises/crashes on connection failure would take down the edge appliance's ingestion path with it; a publisher that silently drops undelivered telemetry on failure would lose clinical data with no record.
- **Potential Harm:** Loss of clinical telemetry, or an edge ingestion outage triggered by a downstream cloud-connectivity failure.
- **Existing Risk Control / Mitigation:** paho-mqtt connect_async()+loop_start()+reconnect_delay_set() so connection loss triggers the library's own bounded-backoff reconnect rather than an unhandled exception; a drained batch that fails partway is requeued in full, in original order, via StoreAndForwardRingBuffer.requeue_front() (subject to HAZARD-STREAM-002's own bounded-capacity/drop-oldest policy); default QoS 1 with wait_for_publish() confirms a broker PUBACK, not merely local enqueue. NOT mitigated: end-to-end delivery confirmation to a downstream subscriber -- QoS 1 confirms broker receipt only.
- **Verification Evidence:** tests/unit/test_mqtt_publisher.py::TestRunLoopRequeueOnFailure::test_failed_item_is_requeued_not_dropped
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - Deferred by Scope Decision
- **Decision / Rationale:** Referenced in source (mqtt_publisher.py module docstring) since Phase 5 Section A follow-up but explicitly deferred, by project-owner scope decision, from entry as a scored Risk Register row (see Process Items PROC-002). Entered as a row this session (2026-08-10) to close the source-tagged/register-absent gap surfaced by docs/RTM-001_Requirements_Traceability_Matrix.md §6 -- entry alone, not risk evaluation; Sev/Prob remain unscored pending human risk-management review.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Human risk-management sign-off; any change to mqtt_publisher.py reconnect/requeue logic
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-004

*(Added 2026-08-10, this correction. Transcribed from the Risk Register row, itself transcribed
from `src/infrastructure/streaming/mqtt_publisher.py`'s module docstring.)*

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** MQTT_USE_TLS can be disabled via config.get_mqtt_config().
- **Hazardous Situation:** Clinical telemetry is published over a WAN link without TLS.
- **Potential Harm:** Confidentiality/integrity compromise of in-transit clinical telemetry.
- **Existing Risk Control / Mitigation:** TLS defaults to enabled; disabling it (intended for local-network development against a test broker) logs a WARNING at connect time naming the risk explicitly, so a misconfiguration is visible in the edge appliance's audit trail rather than silent.
- **Verification Evidence:** N/A -- no dedicated test found for the TLS-disabled warning path at compilation time (checked: no 'tls' match in tests/unit/test_mqtt_publisher.py) -- flagged as a gap, not assumed covered.
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - Deferred by Scope Decision
- **Decision / Rationale:** Referenced in source (mqtt_publisher.py module docstring) since Phase 5 Section A follow-up but explicitly deferred, by project-owner scope decision, from entry as a scored Risk Register row (see Process Items PROC-002). Entered as a row this session (2026-08-10) to close the source-tagged/register-absent gap surfaced by docs/RTM-001_Requirements_Traceability_Matrix.md §6 -- entry alone, not risk evaluation; Sev/Prob remain unscored pending human risk-management review. Also lacks dedicated test coverage for its warning-log mitigation -- a second, independent gap on top of the scoring gap.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Human risk-management sign-off; add a dedicated test for the TLS-disabled warning path
- **Phase Assignment:** Phase 5-Stream - Backlog

#### HAZARD-STREAM-005

*(Added 2026-08-10, this correction. Transcribed from the Risk Register row, itself transcribed
from `src/infrastructure/streaming/live_dashboard_channel.py`'s module docstring.)*

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** A dashboard WebSocket client stops reading (slow network, backgrounded browser tab, crashed JS).
- **Hazardous Situation:** With an unbounded per-client queue, memory grows without limit; with a naive blocking send, the broadcaster stalls and delays/drops delivery to every other client.
- **Potential Harm:** Edge/cloud resource exhaustion from one slow dashboard client, or delayed/dropped live-dashboard delta delivery to other clinicians' dashboards.
- **Existing Risk Control / Mitigation:** Bounded per-client queue (default 200 deltas) with drop-oldest-on-overflow (recency preferred over completeness for a live view); broadcast() only enqueues via non-blocking put_nowait() and never awaits a per-client send, so one slow/dead client cannot delay or block delivery to others or the producer. NOT mitigated: no acknowledgement/delivery guarantee/store-and-forward -- a disconnected dashboard permanently misses deltas during the outage. Deliberate scope boundary (a dashboard is a live view, not a system of record), distinct from the MQTT/MLLP telemetry paths (HAZARD-STREAM-002/003) where that data must not be lost.
- **Verification Evidence:** tests/unit/test_live_dashboard_channel.py::TestQueueOverflowPolicy::test_overflow_drops_oldest_delta_keeps_newest
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - Deferred by Scope Decision
- **Decision / Rationale:** Referenced in source (live_dashboard_channel.py module docstring) since Phase 5 Section A but explicitly deferred, by project-owner scope decision, from entry as a scored Risk Register row (see Process Items PROC-002). Entered as a row this session (2026-08-10) to close the source-tagged/register-absent gap surfaced by docs/RTM-001_Requirements_Traceability_Matrix.md §6 -- entry alone, not risk evaluation; Sev/Prob remain unscored pending human risk-management review.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Human risk-management sign-off on the display-only/no-store-and-forward scope boundary
- **Phase Assignment:** Phase 5-Stream - Backlog

#### UNASSIGNED-PVC-001

*(Added 2026-08-10, this correction — see the front-matter correction note. This row existed in
the workbook since before this file's original 2026-08-10 compilation; it was omitted from that
compilation's Appendix A because it carries no `HAZARD-*` ID, not because it was newly added.
`UNASSIGNED-PVC-001` is a placeholder reference invented for this file only, per explicit
instruction, so the row is no longer omitted from enumeration — it is NOT a Risk ID recorded in
the workbook itself, where the Risk ID cell still literally reads
`(unassigned -- awaiting Risk ID)`. Transcribed directly from that workbook row, verbatim.)*

- **Severity:** *(not yet scored)* &nbsp;|&nbsp; **Probability (pre-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (pre-mitigation):** *(not yet scored)*
- **Probability (post-mitigation):** *(not yet scored)* &nbsp;|&nbsp; **Risk Index (post-mitigation):** *(not yet scored)*
- **Hazard (Cause):** device.key (device private key, cert_store.py) is stored on a Kubernetes PVC (icu-edge-gateway-pki) with no storageClassName set
- **Hazardous Situation:** The PVC falls through to whatever the target cluster's default StorageClass is; at-rest encryption of that storage class is unstated by this repo and entirely environment-dependent
- **Potential Harm:** A leaked device.key from unencrypted underlying storage is functionally the same device-impersonation risk as HAZARD-STREAM-010 (token brute-force), via a different path (storage-layer exposure instead of token guessing)
- **Existing Risk Control / Mitigation:** None applied -- deploy/k3s/edge-appliance.yaml's PVC spec declares only accessModes/storage size, no storageClassName. Project owner decision this session: track as an open item here rather than edit the manifest without knowing the target cluster's actual default StorageClass and its encryption posture.
- **Verification Evidence:** N/A -- not yet triaged
- **Residual Risk Acceptability:** Not yet assessed
- **Status:** Open - awaiting Risk ID assignment and triage decision
- **Decision / Rationale:** Explicitly NOT assigned a HAZARD ID yet, per project owner's instruction this session -- deferred to a future explicit step, not because the item isn't real.
- **Decision Owner:** Awaiting assignment
- **Decision Date:** TBD
- **Next Review Trigger:** Before any production deployment; when the target cluster's default StorageClass is known
- **Phase Assignment:** Phase 5-Stream - Backlog
