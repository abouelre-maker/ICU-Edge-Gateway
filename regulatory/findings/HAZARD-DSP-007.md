# HAZARD-DSP-007 — Non-Finite Vital-Sign Values Reaching NEWS2 Scoring

**Status:** 🔶 **PROPOSAL — AWAITING HUMAN RISK-MANAGEMENT SIGN-OFF**
**Raised:** 2026-08-21 (Phase 5-Stream Section D edge-case sweep)
**Standard:** ISO 14971:2019 — risk management for medical devices
**Software item:** IEC 62304 Class B — `domain/services/artifact_rejector.py`

> **This entry is NOT self-certified.** Severity and probability below are
> engineering's proposed values, not accepted determinations. A clinical risk
> assessor must review and either accept, adjust, or reject them. The code fix
> is already merged (commit `b34fe99`) because leaving a known silent
> under-scoring defect in place was the worse option; the *risk acceptance*
> for the residual items in §8 remains open.

---

## 1. Hazard

A non-finite numeric value (IEEE-754 `NaN`) present in a vital-sign
observation is accepted as physiologically valid and carried into NEWS2
scoring, where it produces a component score of 0 — the lowest-risk band —
for a parameter whose true value is unknown.

**Hazardous situation:** a patient's NEWS2 total is reported LOWER than their
actual physiological state warrants, on input the system had every
opportunity to reject.

## 2. Sequence of events

1. A vital-sign source produces `NaN` — a disconnected or dislodged lead, a
   sensor fault, a malformed `OBX-5` field, or an upstream parse producing
   `float('nan')`.
2. `PhysiologicalBoundsChecker.check()` evaluates `value < low` and
   `value > high`. **Both are `False` for `NaN` under IEEE-754**, so neither
   bound is breached and the checker returns `(True, "")` — "within
   physiological bounds".
3. `VitalSignProcessor.process()` records
   `is_within_physiological_bounds=True` on the resulting
   `ProcessedVitalSign`.
4. `NEWS2Calculator._assert_required_parameters_present()` filters **only**
   on that flag, so the parameter counts as present. No
   `NEWS2InsufficientDataError` is raised.
5. `NEWS2Calculator._extract_value()` selects the **most recent**
   within-bounds sample for the type. A `NaN` arriving *after* a valid
   reading therefore **displaces it**.
6. Inside the scoring bands, every comparison against `NaN` is also `False`,
   so the parameter falls through to the default branch and scores **0**.
7. The Bundle, the WebSocket delta, the MQTT telemetry and the FHIR
   Subscription delivery all carry a total that is too low, with **no
   warning, no exception, and no audit note** — because from the pipeline's
   point of view nothing went wrong.

## 3. Harm

Delayed recognition of clinical deterioration.

NEWS2 exists to trigger escalation thresholds (RCP 2017: ≥5 urgent
assessment, ≥7 emergency response). An under-estimated total can leave a
deteriorating patient below the threshold that would have summoned help.

**Worst case measured in this codebase**, not hypothesised: a patient with a
true heart rate of 130 bpm scores 2 on the pulse component. With a subsequent
`NaN` displacing that reading, the component scores **0** — a two-point
under-estimate on a single parameter, sufficient on its own to move a total
of 5 (urgent assessment) to 3 (routine 12-hourly observations).

This is the direction of error ISO 14971 **HAZARD-NEWS2-003** already exists
to prevent ("partial scoring underestimates clinical risk"). HAZARD-DSP-007
is a previously-undetected *path into* that same harm.

## 4. Pre-fix risk evaluation (PROPOSED — for assessor review)

| Dimension | Proposed | Reasoning |
|---|---|---|
| **Severity** | **Serious** | Delayed escalation of a deteriorating ICU patient. Not *Critical*: the score is advisory, a clinician remains in the loop, and bedside observation is not removed by this failure. An assessor may reasonably argue Critical given the ICU population. |
| **Probability** | **Occasional** | Requires a `NaN` to reach the checker. Lead disconnection and sensor dropout are routine ICU events; whether they surface as `NaN` rather than an absent OBX depends on the specific monitor and interface engine, and was not characterised against real devices. |
| **Detectability** | **Very low** | The defining property of this hazard. No exception, no warning, no audit note, no operator-visible symptom. The score simply reads lower than it should. |
| **Pre-fix risk index** | **Unacceptable without control** | Engineering's view; the assessor owns the final placement. |

The probability estimate is the weakest input here and is flagged as such:
it was **not** derived from device data or field reports. Characterising how
often connected monitors actually emit `NaN` would materially improve it.

## 5. Control implemented

**Type:** Inherent safety by design (ISO 14971 §7.1 preferred control) —
reject the input rather than warn about it.

`domain/services/artifact_rejector.py`:

1. **Scalar path.** `PhysiologicalBoundsChecker.check()` now rejects `NaN`
   explicitly via `math.isnan()` **before** any bound comparison, and before
   the "no bounds configured" early return — so `NaN` is rejected for every
   `VitalSignType`, including those with no configured range.

2. **Array path.** `_require_finite()` guards `DualNotchFilter`,
   `BandpassFilter` and `HampelFilter`. A linear IIR filter given one
   non-finite sample propagates it through the *entire* output via feedback;
   the pre-existing empty/too-short guards did not check for this. The guard
   raises the same `ValueError` type as those guards, so
   `signal_processor.py`'s existing per-stage try/except degrade-and-log
   handles it with **no orchestration change**.

3. **Degenerate band.** `BandpassFilter` raises a domain-specific message
   when a low sampling rate collapses the passband. `scipy` already failed
   closed here; this only removes reliance on scipy's internal wording.

**No clinical algorithm was altered.** NEWS2 band boundaries, component
weightings and risk-level thresholds are untouched. The change is confined to
which inputs are permitted to reach them.

**Defense in depth (commit `567c4bc`):** the four external-transmission
boundaries now also reject non-finite values at serialization. Two were
genuinely unsafe — `websocket.send_json()` and `json.dumps()` both default to
`allow_nan=True` and would have emitted a bare `NaN` token (invalid RFC 8259)
to dashboard clients and to a subscriber's webhook respectively.

## 6. Verification evidence

**`tests/regulatory/test_hazard_dsp_007_nan.py` — 42 tests.**

| Claim | Evidence |
|---|---|
| `NaN` rejected for every `VitalSignType`, with a populated audit note | Parametrised over the full enum, plus a guard test that fails if a new enum member is added without coverage |
| `±Inf` rejected for every bounded type | Parametrised over `_PHYSIOLOGICAL_BOUNDS` derived from the production table, so a new bounded type extends coverage automatically |
| `NaN` excluded from NEWS2 input through the real pipeline | Driven through `VitalSignProcessor` → `NEWS2Calculator`, not the checker in isolation |
| **A later `NaN` cannot displace an earlier valid reading** | The §3 worst case, locked directly: HR 130 followed by `NaN` must still score 2 |
| `NEWS2InsufficientDataError` raised when a mandatory parameter is `NaN`-only | Parametrised across all five mandatory types |
| `None` fails loud rather than reporting in-bounds | Asserts `TypeError`, so a future "defensive" change swallowing it into `(True, "")` is caught |

**The evidence was confirmed load-bearing, not assumed.** Reverting
`artifact_rejector.py` to its pre-fix state fails **18 of the 42** tests,
including the displacement guard. A test suite that passes against both the
broken and fixed code proves nothing; this one does not.

Supporting: `tests/unit/test_artifact_rejector.py` (filter-level),
`tests/unit/test_signal_processor_edge_cases.py` (orchestrator-level).

**Regression:** 667 → 709 passed, 1 xfailed at the time of the fix
(+42 new, zero regressions). Current suite total: 816 passed, 1 xfailed.

## 7. Post-fix risk evaluation (PROPOSED)

| Dimension | Proposed |
|---|---|
| Severity | **Serious** — unchanged; controls reduce probability of occurrence, not the harm if it occurred |
| Probability | **Improbable** for the controlled paths |
| Detectability | **High** — rejection is recorded in `ProcessedVitalSign.pipeline_notes` and surfaced in `Bundle.note`, so exclusion is visible to operators and auditors instead of silent |
| Residual risk | **Proposed acceptable for the controlled paths**, subject to §8 |

## 8. Residual risk — STATED, NOT DISMISSED

### 8a. `CONSCIOUSNESS` is absent from `_PHYSIOLOGICAL_BOUNDS`

`CONSCIOUSNESS` is the one `VitalSignType` with no configured bounds. The
`NaN` check precedes the "no bounds configured" early return, so **`NaN` is
correctly rejected** for it — but **`±Inf` returns `(True, "")`** via that
early return.

**Assessed clinically inert, with the reasoning stated so an assessor can
disagree:**

- `_score_consciousness()` reads `avpu_level`, never the numeric `value`.
- `VitalSignSample.__post_init__` makes a `CONSCIOUSNESS` sample without
  `avpu_level` unconstructable.
- Asserted explicitly in `TestConsciousnessInfIsInertNotRejected`, which
  proves an `Inf`-valued sample still scores 0 for `ALERT` and 3 for
  `NEW_CONFUSION`.

**Why it was not simply fixed:** adding `CONSCIOUSNESS` to
`_PHYSIOLOGICAL_BOUNDS` would mean inventing a numeric range for a
categorical AVPU scale, which is semantically wrong and would make the bounds
table lie about what it represents. Rejecting non-finite values for
unbounded types generally is the cleaner fix, but it changes behaviour for a
frozen clinical module and belongs in its own reviewed change.

**Requested determination:** accept as inert, or direct a follow-up change.
It is recorded here so it is a *decision*, not an oversight.

### 8b. Probability estimate is not evidence-based

§4's *Occasional* rating is engineering judgement, not device data. No
characterisation exists of how connected Philips / GE / Dräger / Mindray /
Nihon Kohden monitors actually represent a disconnected lead through this
interface path — `NaN`, a sentinel value, or an absent segment. That
distinction changes both the probability and whether other sentinel
representations (e.g. `-99`, `9999`) need their own control.

### 8c. Sentinel values are out of scope of this control

This hazard covers non-finite IEEE-754 values only. A monitor emitting a
numeric sentinel *inside* physiological bounds would pass every check here.
That is a **different, uncontrolled hazard** and is not mitigated by
HAZARD-DSP-007. Flagged rather than silently folded in.

### 8d. Byte-level corruption within a well-formed message

HL7 v2.x has no per-message checksum. A bit-flip producing a plausible
in-range value is undetectable at this layer. Pre-existing residual risk of
the wire protocol, noted for completeness.

## 9. Traceability

| Artefact | Reference |
|---|---|
| Control | `src/domain/services/artifact_rejector.py` — commit `b34fe99` |
| Defense in depth | `src/api/v1/{ingest,vitals,live}.py`, `mqtt_publisher.py`, `subscription_dispatcher.py` — commit `567c4bc` |
| Regulatory evidence | `tests/regulatory/test_hazard_dsp_007_nan.py` |
| Unit evidence | `tests/unit/test_artifact_rejector.py`, `tests/unit/test_signal_processor_edge_cases.py` |
| Related hazards | HAZARD-NEWS2-003 (partial scoring), HAZARD-DSP-005/006 (orchestration), HAZARD-STREAM-005 (dashboard delivery) |

## 10. Requested sign-off

1. Accept or adjust the proposed severity and probability in §4 and §7.
2. Determine §8a — `CONSCIOUSNESS`/`Inf` accepted as inert, or follow-up change?
3. Decide whether §8b warrants device characterisation before production.
4. Confirm §8c (numeric sentinels) is raised as its own hazard.
5. Record the accepted residual risk against the Risk Management File
   (`docs/RMF-001_Risk_Management_File.md`).

Until items 1–5 are answered, this entry remains **PROPOSED**. The code
control is live; the *risk acceptance* is not.
