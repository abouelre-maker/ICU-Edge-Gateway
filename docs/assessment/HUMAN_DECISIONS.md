# Human Decisions Required

Each item: what is needed, options, recommendation, and what it blocks. Status is
`OPEN` until Housam answers; the answer and date are then recorded under the item.

## Engineering

### HD-E1 — IP ownership written confirmation (shared with HD-C1)
- **Blocks:** any external distribution; repository access for anyone else.
- **Options:** (a) obtain written confirmation from the university / any employer that
  Housam owns the code; (b) proceed without it (not recommended).
- **Recommendation:** (a), before any outreach. See `docs/commercial/2026-10/04_HUMAN_GATES_CHECKLIST.md`.
- **Status:** OPEN

### HD-E2 — Regulatory counsel engagement
- **Blocks:** any exemption or classification statement, internal or external.
- **Options:** one-hour consult with regulatory counsel using the single question list
  in `04_HUMAN_GATES_CHECKLIST.md`; or defer and keep all regulatory statements as open
  hypotheses.
- **Recommendation:** consult before any external regulatory statement.
- **Status:** OPEN

### HD-E3 — A real de-identified HL7 sample
- **Blocks:** true closure of V-01 (vendor mappings stay `inferred-UNVERIFIED`).
- **Options:** request via the sample protocol in `02_DISCOVERY_KIT.md` §2.7; or keep V-01
  closed only as "data-driven + provenance-labelled".
- **Recommendation:** request from the first integrator or research partner.
- **Status:** OPEN

### HD-E4 — Appointing a clinical safety reviewer
- **Blocks:** signing any `regulatory/findings/*` PROPOSAL note.
- **Options:** an intensivist / critical-care nurse / clinical-safety officer willing to
  review; or leave all notes unsigned.
- **Recommendation:** seek through the Segment C pilot champion search.
- **Status:** OPEN

### HD-E5 — Target platform and TLS termination location
- **Blocks:** F-09 deployment side; S-08 details.
- **Options:** (a) hardened VM, TLS terminated in-app; (b) k3s appliance, TLS at ingress;
  (c) sidecar proxy.
- **Recommendation:** implement app-level TLS capability regardless (Phase 4); choose the
  deployment option only when a pilot site's IT constraints are known.
- **Status:** OPEN

### HD-E6 — BLOCKED-TEST-CONFLICT items
- **Blocks:** each affected finding.
- **Status:** OPEN — 4 entries (A2-1, A5-1, A5-2, A8-1).

#### A8-1 — MLLP idempotency (duplicate MSH-10 re-processed)
- **Test:** `tests/integration/test_mllp_listener.py::TestValidFrameAccepted::test_multiple_frames_on_one_persistent_connection`.
- **Assertion locked in:** the identical message (MSH-10 `MSG001`) sent three times ⇒
  `assert listener.forward_buffer.size() == 3`.
- **Behaviour it locks in:** retransmissions of the same message are processed and forwarded
  again, so downstream receives duplicates.
- **Why that is wrong:** MLLP senders retransmit when an ACK is lost; without de-duplication by
  (sender, MSH-10), one observation becomes several downstream records (A8).
- **Options:** (1) amend the test to send three distinct MSH-10 values (and add a test that a
  repeated MSH-10 is ACKed AA without re-forwarding) — **recommended**; (2) keep re-processing,
  WONTFIX (duplicates handled downstream).
- **State now:** de-duplication **not implemented**; the rest of A8 is implemented.

#### A5-1 — site-unspecified `T1`/`T2` mapped to core temperature
- **Tests (5):** `tests/unit/test_demo_streamer.py::TestEveryEmittedObxCodeIsAlreadyMapped::test_no_obx_is_skipped_for_any_stage_of_any_bed[ICU-BED-03]`,
  `...::test_all_seven_news2_parameters_are_present[ICU-BED-03]`,
  `tests/unit/test_demo_streamer.py::TestSepsisRampTrajectory::{test_trajectory_is_monotonically_non_decreasing,test_trajectory_visits_normal_low_medium_and_high,test_trajectory_starts_normal_and_ends_high}`.
- **Assertion locked in:** every OBX the demo emits for ICU-BED-03 is mapped, including
  `T1^Temperature Channel 1^DRAEGER` (`scripts/demo_inject.py:280`), and the scripted
  sepsis ramp scores from it.
- **Behaviour it locks in:** the generic channel label `T1` is treated as core body temperature.
- **Why that is wrong:** `T1`/`T2` do not say which body site they measure; a skin probe
  reading feeds the NEWS2 temperature row as if it were core temperature (A5).
- **Options:** (1) amend the demo to emit a site-specific code (e.g. `TEMPCORE` or LOINC 8310-5)
  and keep `T1`/`T2` unmapped — **recommended**; the tests would then pass unchanged;
  (2) keep the `T1`/`T2` mapping, WONTFIX.
- **State now:** mapping kept; desired behaviour recorded as strict-xfail
  `tests/unit/test_a5_code_mapping.py::test_site_unspecified_temperature_is_not_core`.

#### A5-2 — LOINC-looking identifier under a non-LOINC coding system still resolves as LOINC
- **Tests (2):** `tests/integration/test_hl7v2_vendor_edge_cases.py::TestLoincCodeMislabelledCodingSystemStillResolves::{test_loinc_code_with_non_loinc_coding_system_still_resolves,test_loinc_code_with_non_loinc_coding_system_on_generic_vendor}`.
- **Assertions locked in:** `skipped_obx_count == 0`, one sample, `vital_sign_type is HEART_RATE` / `SPO2`
  for a LOINC-shaped identifier declared under a non-LOINC system.
- **Behaviour it locks in:** the declared coding system is ignored when the identifier happens
  to match a LOINC code.
- **Why that is wrong:** in a local code system the same string can mean something else;
  honouring OBX-3.3 is the A5 requirement. (The opposite direction — `HR^...^LN` no longer
  falls back to the proprietary table — is implemented and did not conflict.)
- **Options:** (1) amend the two tests to expect `UNRECOGNISED_CODE` — **recommended**;
  (2) keep the best-effort fallback, WONTFIX.
- **State now:** fallback kept (marked interim in code); desired behaviour recorded as
  strict-xfail `tests/unit/test_a5_code_mapping.py::test_non_loinc_system_does_not_fall_back_to_loinc_table`.

#### A2-1 — `tests/integration/test_hl7v2_vendor_edge_cases.py::TestMalformedOrTruncatedMsh3::test_msh_with_only_the_required_leading_fields_does_not_crash`
- **Assertion:** `assert len(result.samples) == 1` for a message with MSH-7 absent and
  no OBX-14 (the OBX has status in OBX-10 and a timestamp in OBX-13, so OBX-14 is empty).
- **Behaviour it locks in:** a sample is produced even though the message has **no
  usable observation time**; previously that time was silently set to `now()`.
- **Why that is wrong:** a sample without an observation time looks current. That is
  exactly the A2 / N-03 hazard.
- **Why it was not amended under the delegated A1/A2 rule:** it fails solely because of A2,
  but condition 3 speaks of replacing an *expected score*. This test asserts a sample count,
  not a score, so not all five conditions clearly hold. Per R8, no judgement is used.
- **Interim now in the code (keeps the test green, stays fail-safe for scoring):** when
  both OBX-14 and MSH-7 are absent, the sample is kept with the receipt time as a
  placeholder. `UNPARSEABLE_TIMESTAMP` is always recorded, and that forces
  INCOMPLETE: no NEWS2 score is ever computed from it. A present-but-unparseable
  OBX-14 is always skipped. Residual: the per-vital FHIR Observation for such a sample
  shows the receipt time as its effective time.
- **Options:**
  1. **Amend the test** to expect 0 samples plus an `UNPARSEABLE_TIMESTAMP` finding (full A2;
     the sample is dropped with an explicit reason). **Recommended.**
  2. **Keep the interim** placeholder behaviour and close this sub-item WONTFIX.

### Delegated design decisions (Step 3) — decided by delegation 2026-09-29, pending clinical review

Each is also recorded as an unsigned PROPOSAL in `regulatory/findings/<ID>.md` when the
finding is implemented.

| Q | Decision | Finding |
|---|---|---|
| Q1 | Staleness: option (b). Production strict and fail-closed (NEWS2 enabled + any window unset ⇒ refuse to start); no clinical default in `src/`. Test-only windows appended to `tests/conftest.py`. Delegated A1/A2 test amendments only under the five conditions of the continuation directive. | A2 |
| Q2 | Critical values: compute NEWS2 normally, outcome `OUT_OF_RANGE_CRITICAL`, reason `CRITICAL_VALUE_REVIEW_REQUIRED`, measured value preserved, HTTP 200. Implausible values stay artifacts (no score). No threshold value changes. | A6 |
| Q3 | Future-timestamp tolerance: default 60 s, configurable (clock-skew engineering parameter). | A2 |
| Q4 | Cross-message MLLP merging deferred; each fragment yields INCOMPLETE. Recorded as a known gap. | A2 |

### HD-E7 — Per-parameter staleness windows (clinical values)
- **Blocks:** enabling NEWS2 in any deployment (service refuses to start with NEWS2 on and
  any window unset).
- **Options:** values set by a clinical safety reviewer per parameter (RR, SpO2, O2
  status, SBP, HR, consciousness, temperature).
- **Recommendation:** no engineering default is invented; tests use fixture values only.
- **Status:** OPEN

### HD-E8 — Final between-band policy (N-01)
- **Blocks:** N-01 closure.
- **Interim rule (decided by Housam, unsigned PROPOSAL):** assign the more severe adjacent
  band and attach `BETWEEN_BANDS_VALUE`. Band boundaries unchanged.
- **Options:** confirm interim rule; or replace with a rounding rule chosen by a clinical
  reviewer (e.g. round half up to the recorded precision).
- **Status:** OPEN

## Commercial

| ID | Decision | Recommendation | Status |
|---|---|---|---|
| HD-C1 | IP ownership document (Gate 1) | Obtain before any outreach | OPEN |
| HD-C2 | Counsel consult (Gate 2) | Before any external regulatory statement | OPEN |
| HD-C3 | Outreach identity: student address vs another | Assess credibility impact per segment; do not invent a domain | OPEN |
| HD-C4 | Postal address for commercial email | No US cold email in the first 90 days (makes CAN-SPAM moot); never publish a home address | OPEN |
| HD-C5 | Legal name for contracts ("Housam Abouelreish" vs "Housam Ashraf" in earlier docs) | Needed before any SOW is signed | OPEN |
| HD-C6 | Pilot price approval before quoting anyone | Validate in interviews first | OPEN |
| HD-C7 | Company formation timing | Only when a paying pilot is concrete | OPEN |
