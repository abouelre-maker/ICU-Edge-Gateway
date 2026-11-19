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
| A1 | C-R | Critical | OPEN | | | False NORMAL. FiO2 `0.4`, `2`, `15` L/min all parse to room air; "Drowsy" and CWE `A^Alert^…` parse to None, then silently default to Alert (`news2_calculator.py:199-200, 223-224`). Mandatory set is 5 parameters; the docstring claims 6. |
| A2 | C | Critical | OPEN | | | No staleness logic. `calculated_at=now()` becomes `effectiveDateTime`. No cross-message state. Includes N-03: an unparseable HL7 timestamp becomes `now()` (`hl7v2_adapter.py:857`). |
| A3 | C-R | High | OPEN | | | OBX-11 `C` drops the result (0 samples); `''` and lowercase `f` accepted. |
| A4 | C-R | High | OPEN | | | `39,5`→39.0; `120/80`→120; `<50`→50; °F recognised, never converted; no kPa; `/vitals` ignores `unit`. |
| A5 | C (partial) | High | OPEN | | | NIBP/ABP collide; T1/T2 → core temperature; coding system ignored for proprietary codes. LOINC `2708-6` (SaO2) mapped as SpO2 in the adapter input table (`:61`). "Pulse pressure → HR" not reproduced. |
| A6 | C | Critical | OPEN | | | Critical values are classed as artifacts → no score, HTTP 200, no machine-readable outcome; the value is tagged `[ARTIFACT]`, so it cannot be told apart from a lead-off. |
| A7 | C-R | High | OPEN | | | Only the first PID-3 repetition is read; empty PID-3 → `UNKNOWN` (patient merge); MSH-9 not checked (`ADT^A01` accepted); HL7 escapes not decoded. |
| A8 | C | High | OPEN | | | MSA-2 does not echo MSH-10; AR is never sent; AA for any parseable message; ACK IDs collide at 1 s resolution; SpO2 scale is global; ACK precedes durable storage. FHS/BHS batch: NRC. |
| N-01 | C | High | OPEN | | | Fractional values between integer bands: RR=8.5 scores 1 (reassuring direction). No discretisation policy. |
| N-02 | C | Medium | OPEN | | | OBX-11 `P` emitted in FHIR as `status: "final"`. |
| V-01 | C | High | OPEN | | | Vendor OBX tables (5 vendors) are unsourced; docs claim multi-vendor support. |

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
| H-01 | C | High | OPEN | | | `Bundle.note` / `Bundle.extension` are not valid R4 (`bundle_assembler.py:154,164`). |
| H-02 | C | Medium | OPEN | | | `Bundle.total` on a collection bundle (bdl-1). |
| H-03 | C | Medium | OPEN | | | `uuid4` resource IDs → non-idempotent retries. |
| H-04 | C | Medium | OPEN | | | `urn:uuid:DEVICE-PHILIPS` is not a valid UUID URN (`ingest.py:176`). |
| H-05 | C | Medium | OPEN | | | `Patient/{id}` unsanitised against the FHIR id rule. |
| H-06 | C | Medium | OPEN | | | SNOMED `248234008` used as both code and value. |
| H-07 | C | Medium | OPEN | | | Interpretation mapping wrong (risk LOW → `L` "Low"). |
| H-08 | C | Low | OPEN | | | SNOMED `1239842005` for NEWS2 is TODO-VERIFY. Input-side `2708-6` moved to A5. |

## Security

| ID | Phase 0 | Severity | Status | Commit | Tests | Finding |
|---|---|---|---|---|---|---|
| F-01 | C | Critical | OPEN | | | No authentication on `/ingest`, `/vitals`, WebSocket, MLLP; binds `0.0.0.0`. |
| F-02 | C / NRC | High | OPEN | | | No body caps; sync parsing/DSP inside async handlers. Stall figures not yet measured. |
| F-03 | C-R | High | OPEN | | | 200 KB MLLP frame → connection reset, no NAK; 1 MiB cap is dead code; no timeout, no connection cap. |
| F-04 | C-R | High | OPEN | | | `+`/`#`/over-long patient_id → paho `ValueError` → requeued forever (queue halt). `/` injects topic levels. PHI in topic. |
| F-05 | C-R | High | OPEN | | | SSRF guard: all seven bypass forms accepted. |
| F-06/07 | C-R (partial) | High | OPEN | | | Shared secret; `compare_digest` TypeError on non-ASCII; unbounded subscriptions/tasks; CRLF accepted; raw header lines logged; cross-subscriber credential read. |
| F-08 | C | High | OPEN | | | WebSocket: no auth, no Origin check. |
| F-09/10 | C | High | OPEN | | | No TLS on HTTP/WS/MLLP; device cert unused on data path; MQTT system CA + password. |
| F-12 | C | Medium | OPEN | | | Patient identifiers in logs and 422 bodies. |
| F-13 | C | Medium | OPEN | | | `/docs` public; versions at `/health`; CORS falls back to `localhost:3000`. |

## Supply chain / container / infrastructure

| ID | Phase 0 | Severity | Status | Commit | Tests | Finding |
|---|---|---|---|---|---|---|
| S-01 | C | High | OPEN | | | `python:3.11-alpine3.19` EOL, no digest. |
| S-02 | C | Medium | OPEN | | | No lockfile, no `--require-hashes`. |
| S-03 | C | Low | OPEN | | | `pytest-cov` in production `requirements.txt`. |
| S-04 | C | Low | OPEN | | | `pyproject` lists 3 dependencies only. |
| S-05 | NRC | Medium | OPEN | | | `pytest==7.4.4`; advisory ID needs `pip-audit` with network. |
| S-06 | C | High | OPEN | | | Trivy `@master`, `exit-code: 0`; Actions not SHA-pinned; no SBOM/cosign. |
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
| R-08 | C | Medium | OPEN | | | Earlier commercial artifacts repeat disproven claims. Superseded in Step 1 (see `docs/commercial/SUPERSEDED.md`). |

## Change log of this register

- 2026-09-30 — created from the Phase 0 report (Step 1, E0).
