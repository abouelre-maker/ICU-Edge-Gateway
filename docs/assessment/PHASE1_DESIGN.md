# Phase 1 Design — ScoreOutcome / ReasonCode contract (Step 3 design stop)

**Status:** PROPOSED — awaiting Housam's decision. No code written yet.

## 1. Types (new file `src/domain/entities/score_outcome.py`, not protected)

```python
class ScoreOutcome(str, Enum):
    SCORED = "scored"
    INCOMPLETE = "incomplete"            # required input missing / stale / ambiguous
    OUT_OF_RANGE_CRITICAL = "critical"   # physiologically extreme — NOT an artifact

class ReasonCode(str, Enum):
    # required by the brief
    MISSING_CONSCIOUSNESS = "MISSING_CONSCIOUSNESS"
    MISSING_O2_STATUS = "MISSING_O2_STATUS"
    UNMAPPED_AVPU = "UNMAPPED_AVPU"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    UNPARSEABLE_TIMESTAMP = "UNPARSEABLE_TIMESTAMP"
    AMBIGUOUS_UNIT = "AMBIGUOUS_UNIT"
    UNRECOGNISED_CODE = "UNRECOGNISED_CODE"
    CRITICAL_VALUE_REVIEW_REQUIRED = "CRITICAL_VALUE_REVIEW_REQUIRED"
    CORRECTION_PENDING = "CORRECTION_PENDING"
    PRELIMINARY_RESULT = "PRELIMINARY_RESULT"
    BETWEEN_BANDS_VALUE = "BETWEEN_BANDS_VALUE"
    # additions (needed so no existing path collapses to free text)
    MISSING_PARAMETER = "MISSING_PARAMETER"            # one of RR/SpO2/SBP/HR/Temp absent
    ARTIFACT_EXCLUDED = "ARTIFACT_EXCLUDED"            # NaN / physically impossible value
    STALENESS_POLICY_UNSET = "STALENESS_POLICY_UNSET"  # HD-E7 not yet answered
    AMBIGUOUS_PATIENT_ID = "AMBIGUOUS_PATIENT_ID"      # A7: empty / multiple PID-3
    UNSUPPORTED_MESSAGE_TYPE = "UNSUPPORTED_MESSAGE_TYPE"  # A7: MSH-9 not ORU^R01

@dataclass(frozen=True)
class Finding:
    code: ReasonCode
    parameter: VitalSignType | None
    detail: str                        # human-readable, no patient identifiers
    measured_value: float | None = None  # preserved for critical values (A6)

@dataclass(frozen=True)
class ScoringAssessment:
    outcome: ScoreOutcome
    findings: tuple[Finding, ...]
```

**Precedence:** `OUT_OF_RANGE_CRITICAL` > `INCOMPLETE` > `SCORED`. Findings accumulate
whatever the outcome, so one message can carry several reason codes.

## 2. Where it lives in each layer

| Layer | Change | Protected file touched? |
|---|---|---|
| Adapter (`hl7v2_adapter.py`) | `HL7ParseResult` gains `findings: tuple[Finding, ...] = ()` for A3/A4/A5/A7/N-02/unparseable timestamps. `VitalSignSample` gains `result_status: str = "F"` (N-02). Defaults keep every existing constructor call valid. | no |
| Domain — new `ScoringGate` service (`src/domain/services/scoring_gate.py`) | Runs **before** `NEWS2Calculator`. Checks presence of all 7 inputs, staleness/future (A2), between-band values (N-01), critical vs artifact (A6), upstream findings. Returns a `ScoringAssessment`. | no |
| Orchestrator (`vitals_orchestrator.py`) | Calls `ScoringGate`; calls the calculator **only** when the outcome is `SCORED`. `VitalsAnalysisResult` gains `assessment: ScoringAssessment` (with default). `analyse()` gains optional `upstream_findings=()`. | no |
| `NEWS2Calculator` | **Unchanged** (R6). Its own docstring fix (5 vs 6 params, `21 CFR 880.3780`) belongs to R-06 / Phase 7. | not in Phase 1 |
| `artifact_rejector.py` | **Unchanged.** A6's critical/artifact split is decided in `ScoringGate` from the processed vitals, not by changing `PhysiologicalBoundsChecker`. | no |
| API (`ingest.py`, `vitals.py`) | HTTP **200** (decided). New headers `X-Score-Outcome`, `X-Score-Reasons` (comma-separated codes). `/vitals` honours `unit` (A4). | no |
| FHIR (`bundle_assembler.py`) | Adds **one `OperationOutcome` entry** per bundle when the outcome ≠ `SCORED`. `issue.details.coding` uses a local CodeSystem for the reason codes (URL marked TODO-VERIFY, *not* a standard system); critical values carry the measured value in `issue.diagnostics`. This is valid R4 today. Moving `Bundle.note` / `Bundle.extension` out is H-01 (Phase 3). | no |
| MLLP (`mllp_listener.py`) | A8: MSA-2 echoes MSH-10; `AR` for unusable or unsupported messages; unique ACK IDs. | no |

## 3. A6 — how "critical" is separated from "artifact"

Proposal (unsigned PROPOSAL for the clinical safety reviewer):

- **Artifact** (`ARTIFACT_EXCLUDED`) means only data that cannot be physical:
  - NaN or Inf;
  - negative values;
  - SpO2 > 100;
  - O2 status outside {0, 1}.
- **Critical** means any finite, physically possible value outside the current plausibility bounds (HR<20, RR<3, SpO2<50, SBP<40, T<28 °C and the upper bounds).
  - These now produce `OUT_OF_RANGE_CRITICAL` with the value preserved.
  - They are no longer called artifacts.
- Existing bounds values are **not changed**. Only the label for extreme-but-possible values changes, from "artifact, silently dropped" to "critical, review required".

## 4. Questions for Housam (the design stop)

### Q1 — A2 staleness policy vs existing tests (the real conflict)

The brief says the service must refuse to start when NEWS2 is enabled and a staleness
window is unset (HD-E7). Today NEWS2 is always on (the flag comes in Phase 6), and
the test suite builds the app with no windows configured.

**Measured** (EXECUTED 2026-09-30, with a scratch pytest plugin; repo not modified):

| Scenario | Existing tests failing |
|---|---|
| A1 alone (missing AVPU/O2 → no score, applied at the orchestrator) | **4** |
| Any rule that withholds all scores when windows are unset | **11**, including `tests/regulatory/test_hazard_arch_001_pipeline_order.py::…::test_calculator_only_ever_receives_processed_vital_signs` (protected) |

**Options:**

- **(a) Strict now.** Windows unset ⇒ every outcome `INCOMPLETE` with `STALENESS_POLICY_UNSET`; refuse-to-start arrives with the Phase 6 flag.
  - Cost: 11 `BLOCKED-TEST-CONFLICT` entries for you to adjudicate.
- **(b) Strict now, and permission to add fixture windows in `tests/conftest.py`.** This file is test infrastructure, not a test.
  - Cost: brings conflicts back down to about 4 (the A1 ones).
  - Still an edit to an existing test file, so it needs your explicit yes.
- **(c) Staleness enforced only when windows are configured.** Unset ⇒ a `STALENESS_POLICY_UNSET` finding attached, but the score is still produced.
  - Cost: 0 extra conflicts.
  - **This is a reassuring default and violates R7.** Not recommended.

**Recommendation: (b).** It keeps R7, keeps protected regulatory tests untouched, and
turns 11 conflicts into about 4 real ones that need your judgement anyway.

### Q2 — Critical outcome: withhold the NEWS2 total, or compute it?

- **Recommendation:** withhold the total (`news2_score=None`) and emit `OUT_OF_RANGE_CRITICAL` with the measured value. Rationale:
  - a total built from a possibly-disconnected lead can look falsely precise;
  - the critical state itself is the higher-priority signal.
- **Alternative:** compute the total too and attach the critical flag.

### Q3 — Future-timestamp tolerance (clock skew)

This is an engineering value, not a clinical one. **Recommendation:**
- configurable `FUTURE_TIMESTAMP_TOLERANCE_SECONDS`;
- no default: the same fail-closed rule as the staleness windows, set in the test fixture.

### Q4 — A2 cross-message state (vitals split across MLLP messages)

**Recommendation:**
- Phase 1 does **not** combine vitals across messages, because combining needs a per-patient store, which is a durability and PHI design;
- split vitals will score `INCOMPLETE` (fail-safe), and the cross-message store is recorded as deferred;
- Alternative: build an in-memory per-patient window now.

## 5. Order after approval

**A6 → A1 → A2 → N-01 → A3 → N-02 → A4 → A5 → A7 → A8 → V-01.** Each follows R5:
1. a failing test first;
2. `regulatory/findings/<ID>.md` PROPOSAL;
3. the fix;
4. one commit.

A finding stops with `BLOCKED-TEST-CONFLICT` whenever a correct fix breaks an
existing test (R8).
