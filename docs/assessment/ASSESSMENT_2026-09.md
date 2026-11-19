# ICU-Edge-Gateway — Assessment Register 2026-09

Source: independent third-party assessment, reproduced in Phase 0 on 2026-09-29
(`main` @ `83f3a7f`, Python 3.11.9 via `venv311`).

**Phase 0 status legend:** C = confirmed by reading the code · C-R = confirmed by an
in-process run (probe script outside the repo, output observed) · NRC = needs a
runtime check that has not yet been run.

**Severity** is an engineering triage label for ordering the hardening work
(Critical / High / Medium / Low). It is **not** an ISO 14971 severity rating. Only
a clinical safety reviewer (HD-E4) can assign that.

**Status values:** OPEN · IN-PROGRESS · CLOSED · BLOCKED (see HUMAN_DECISIONS.md) ·
BLOCKED-TEST-CONFLICT · DEFERRED-TO-CI · WONTFIX.

## Clinical correctness

| ID | Phase 0 | Severity | Status | Commit | Tests | Finding |
|---|---|---|---|---|---|---|
| A1 | C-R | Critical | CLOSED | 9d70a0e, ed45f8e, 2e63e8a | tests/unit/test_a1_missing_inputs.py; amended+companion tests in test_api_ingest.py, test_hl7v2_waveform_pipeline.py | False NORMAL. FiO2 `0.4`, `2`, `15` L/min all parse to room air; "Drowsy" and CWE `A^Alert^…` parse to None, then silently default to Alert (`news2_calculator.py:199-200, 223-224`). Mandatory set is 5 parameters; the docstring claims 6. |
| A2 | C | Critical | CLOSED (1 sub-item BLOCKED-TEST-CONFLICT A2-1) | 7cad9b8 | tests/unit/test_a2_staleness.py | No staleness logic. `calculated_at=now()` becomes `effectiveDateTime`. No cross-message state. Includes N-03: an unparseable HL7 timestamp becomes `now()` (`hl7v2_adapter.py:857`). |
| A3 | C-R | High | CLOSED | 6b31cb6 | tests/unit/test_a3_result_status.py | OBX-11 `C` drops the result (0 samples); `''` and lowercase `f` accepted. |
| A4 | C-R | High | CLOSED | bf55396 | tests/unit/test_a4_units.py | `39,5`→39.0; `120/80`→120; `<50`→50; °F recognised, never converted; no kPa; `/vitals` ignores `unit`. |
| A5 | C (partial) | High | PARTIAL — BLOCKED-TEST-CONFLICT A5-1, A5-2 | f1b5730 | tests/unit/test_a5_code_mapping.py (3 strict-xfail) | NIBP/ABP collide; T1/T2 → core temperature; coding system ignored for proprietary codes. LOINC `2708-6` (SaO2) mapped as SpO2 in the adapter input table (`:61`). "Pulse pressure → HR" not reproduced. |
| A6 | C | Critical | CLOSED | 67883d9 | tests/unit/test_a6_critical_values.py | Critical values are classed as artifacts → no score, HTTP 200, no machine-readable outcome; the value is tagged `[ARTIFACT]`, so it cannot be told apart from a lead-off. |
| A7 | C-R | High | CLOSED | 622bd7d | tests/unit/test_a7_patient_identity.py | Only the first PID-3 repetition is read; empty PID-3 → `UNKNOWN` (patient merge); MSH-9 not checked (`ADT^A01` accepted); HL7 escapes not decoded. |
| A8 | C | High | CLOSED except durable queue (A8-1 closed 2026-11-19: MSH-10 de-duplication) | 7a2a175, 99ac5e2, 7e38e62 | tests/integration/test_a8_mllp_ack.py; tests/integration/test_a8_mllp_dedup.py | MSA-2 did not echo MSH-10; AR never sent; retransmissions re-processed. Durable store-and-forward queue still deferred. |
| N-01 | C | High | CLOSED (interim rule; HD-E8) | c73e6e8 | tests/unit/test_n01_between_bands.py | Fractional values between integer bands: RR=8.5 scores 1 (reassuring direction). No discretisation policy. |
| N-02 | C | Medium | CLOSED | 5c3d2ee | tests/unit/test_n02_preliminary_status.py | OBX-11 `P` emitted in FHIR as `status: "final"`. |
| V-01 | C | High | CLOSED as data+provenance; true closure BLOCKED on HD-E3 | 96d59cb | tests/unit/test_v01_vendor_code_table.py | Vendor OBX tables (5 vendors) are unsourced; docs claim multi-vendor support. |

## DSP

| ID | Phase 0 | Severity | Status | Commit | Tests | Finding |
|---|---|---|---|---|---|---|
| D-01 | C / NRC | Medium | OPEN | | | Four `filtfilt` passes at Q=2 (`artifact_rejector.py:83-88`); QRS attenuation not yet measured. |
| D-02 | C | Medium | OPEN | | | At fs ≤ 100 Hz no notch is applied, yet the audit note says "removed" (`signal_processor.py:130`). This is the default for SpO2/RR at 62.5 Hz. |
| D-03 | C | Low | OPEN | | | Hampel half-window 5; pure-Python loop. |
| D-04 | C | Medium | OPEN | | | `cleaned_value=sample.value` (`signal_processor.py:207`): DSP never affects NEWS2. Document; do not wire in without a risk assessment. |

## FHIR R4

| ID | Phase 0 | Severity | Status | Commit | Tests | Finding |
|---|---|---|---|---|---|---|
| H-01 | C | High | CLOSED 2026-11-19 | 52735bd | tests/unit/test_h01_h06_fhir_validity.py | Bundle.note / Bundle.extension removed; version in meta.tag; warnings in the OperationOutcome. |
| H-02 | C | Medium | CLOSED 2026-11-19 | 52735bd | tests/integration/test_fhir_bundle.py | No Bundle.total on collection. |
| H-03 | C | Medium | CLOSED 2026-11-19 | 52735bd | tests/unit/test_h01_h06_fhir_validity.py | Content-derived UUIDv5 IDs. |
| H-04 | C | Medium | CLOSED 2026-11-19 | 52735bd | tests/unit/test_h01_h06_fhir_validity.py | Every fullUrl a valid urn:uuid. |
| H-05 | C | Medium | CLOSED 2026-11-19 | 52735bd | tests/unit/test_h01_h06_fhir_validity.py | Unsafe identifier -> subject.identifier; still never scored. |
| H-06 | C | Medium | CLOSED 2026-11-19 (code TODO-VERIFY) | 52735bd | tests/unit/test_h01_h06_fhir_validity.py | Observation.code SNOMED 6942003; value keeps the AVPU finding. |
| H-07 | C | Medium | OPEN | | | Interpretation mapping wrong (risk LOW → `L` "Low"). |
| H-08 | C | Low | OPEN | | | SNOMED `1239842005` for NEWS2 is TODO-VERIFY. Input-side `2708-6` moved to A5. |

## Security

| ID | Phase 0 | Severity | Status | Commit | Tests | Finding |
|---|---|---|---|---|---|---|
| F-01 | C | Critical | CLOSED 2026-11-19 | 6deea8d, 0ade939, 99ac5e2 | tests/unit/test_f01_f08_auth.py; tests/integration/test_f01_f08_auth_wired.py | No authentication. Now: API key on ingest/vitals (fail-closed startup), MLLP allow-list, MLLP default bind 127.0.0.1. |
| F-02 | C / NRC | High | CLOSED (stall 7754→15 ms, 8460→15 ms measured) | 14ca3ff | tests/integration/test_f02_payload_caps.py | No body caps; sync parsing/DSP inside async handlers. Stall figures not yet measured. |
| F-03 | C-R | High | CLOSED 2026-11-19 | f0a358e, 99ac5e2 | tests/integration/test_f03_mllp_limits.py; tests/integration/test_a8_mllp_dedup.py | 200 KB MLLP frame reset the connection. Now: stream limit, timeouts, connection cap, AR then close on oversize. |
| F-04 | C-R | High | CLOSED 2026-11-19 | e9dc4e3, 99ac5e2 | tests/unit/test_f04_patient_id_and_dead_letter.py; tests/unit/test_f04_opaque_topic.py | Unsafe patient_id halted the queue; identifier in MQTT topic. Now: validation, dead-letter, HMAC topic segment. |
| F-05 | C-R | High | CLOSED (residual: sub-second DNS-rebinding window until IP pinning) 2026-11-19 | 42fe1e6 | tests/unit/test_f05_f07_subscription_hardening.py | SSRF guard accepted seven bypass forms. Now: legacy IPv4 forms, mapped IPv6, wildcard DNS, embedded credentials refused; connect-time public-address check; no redirects. |
| F-06/07 | C-R | High | CLOSED 2026-11-19 (shared registration secret remains by design) | 42fe1e6 | tests/unit/test_f05_f07_subscription_hardening.py; tests/integration/test_f01_f08_auth_wired.py | compare_digest TypeError; unbounded subscriptions/tasks; CRLF; header logging; credential disclosure. All addressed. |
| F-08 | C | High | CLOSED 2026-11-19 | 6deea8d, 0ade939 | tests/integration/test_f01_f08_auth_wired.py | WebSocket had no auth and no Origin check. |
| F-09/10 | C | High | OPEN | | | No TLS on HTTP/WS/MLLP; device cert unused on data path; MQTT system CA + password. |
| F-12 | C | Medium | CLOSED 2026-11-19 | 4a5ae8e | tests/integration/test_f12_f13_privacy.py | Identifiers in logs and 422 bodies. Now pseudonymised in logs; 422 bodies carry no input. |
| F-13 | C | Medium | PARTIAL 2026-11-19 | 4a5ae8e | tests/integration/test_f12_f13_privacy.py | Library version removed from /health. Kept by decision: /docs public (schema is published in this repository); CORS dev default localhost:3000 (test-locked). |

## Supply chain / container / infrastructure

| ID | Phase 0 | Severity | Status | Commit | Tests | Finding |
|---|---|---|---|---|---|---|
| S-01 | C | High | CLOSED 2026-11-19 | ff23e82 | CI docker-verify | Base image now python:3.11-alpine3.23 pinned by digest. |
| S-02 | C | Medium | CLOSED 2026-11-19 | ff23e82 | CI docker build | requirements.lock with hashes; image installs with --require-hashes. |
| S-03 | C | Low | CLOSED 2026-11-19 | ff23e82 | | pytest-cov removed from production requirements. |
| S-04 | C | Low | OPEN | | | `pyproject` lists 3 dependencies only. |
| S-05 | NRC | Medium | CLOSED 2026-11-19 | ff23e82 | pip-audit | pytest 9.2.0; certifi 2026.10.23; production set has no known vulnerabilities. |
| S-06 | C | High | CLOSED except image signing 2026-11-19 | ff23e82 | CI | Actions SHA-pinned; Trivy v0.36.0 fails on fixable HIGH/CRITICAL; CycloneDX SBOM. Signing needs a registry. |
| S-07 | C / NRC | Medium | OPEN | | | CI limit raised to 400 MB (`b54f2f5`); labels carry "< 150 MB" and regulatory claims; 372 MB not measured locally. |
| S-08 | C | Medium | OPEN | | | k3s: no Service, no NetworkPolicy, no 2575; runbook says "no persistent state" despite a PVC. |
| S-09 | C / NRC | Medium | OPEN | | | Enrollment token plaintext, burned before CSR check, not device-bound. Terraform defects: report only. |

## Regulatory / documentation

| ID | Phase 0 | Severity | Status | Commit | Tests | Finding |
|---|---|---|---|---|---|---|
| R-01 | C | High | OPEN | | | "IEC 62304 Class B" asserted in 23 files; no §4.3 rationale exists (QMS-001:66). |
| R-02 | C | High | OPEN | | | REG-001 (2026-08-06) predates the streaming layer. |
| R-03 | C | Low | OPEN | | | Stale test counts (332 / 661 / 816) across 12 files. |
| R-04 | C | Low | OPEN | | | `allow_origins=["*"]` claim in 6 files. |
| R-05 | C / NRC | Low | OPEN | | | `PUSH_READINESS.md` contradicts itself on CI; FDA guidance date unsettled. Research (ledger L1/L2): issued 6 Jan 2026, FDA page current as of 29 Jan 2026; the repo's "15 January" is unsourced — fix in Phase 7. |
| R-06 | C | Medium | OPEN | | | `21 CFR 880.3780` at `news2_calculator.py:15`; contradictory Health Canada / CDS-Non-Device labels. |
| R-07 | C / NRC | Medium | OPEN | | | Outreach kit overclaims; missing CAN-SPAM/CASL elements. |
| R-08 | C | Medium | CLOSED 2026-11-19 | | | Earlier commercial artifacts are not part of the public repository. |

## Change log of this register

- 2026-09-30 — created from the Phase 0 report (Step 1, E0).
- 2026-09-30 — Phase 1 statuses, commits and tests recorded.
- 2026-09-30 — Phase 2 statuses recorded; gate item "POST /ingest without credentials → 401" FAILS (422) pending F01-1.
