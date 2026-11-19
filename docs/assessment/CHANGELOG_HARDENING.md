# Hardening Changelog

Chronological record of every change on `hardening/assessment-2026-09`.

## Lock-file removals (standing permission, continuation directive §1)

| When | Size | Age at removal | Removed by | Notes |
|---|---|---|---|---|
| 2026-09-29 (reported) | 0 bytes | last written 2026-09-19 00:25 | Housam's assistant (natively on Windows) — not by this session | `Get-Process git` returned nothing; HEAD 83f3a7f at the time |

## Changes

| Date | Commit | Item | Summary |
|---|---|---|---|
| 2026-09-30 | d5b636d | E0 | Phase 0 recorded; canonical claims; superseded commercial artifacts. Note: commits d5b636d…42cf67e have an invisible UTF-8 BOM at the start of the subject line (PowerShell 5.1 `Set-Content -Encoding utf8`); left as-is because amending history is forbidden (R2). |
| 2026-09-30 | 2f058e9 | C-0 | Executive plan |
| 2026-09-30 | 2510b89 | C-1 | First-customer list + tracking sheet |
| 2026-09-30 | d03e2ec | C-2 | Discovery kit EN + AR |
| 2026-09-30 | 42cf67e | C-4.4 | Human-gates checklist + evidence ledger |
| 2026-09-30 | 0ec6549 | E0 | Step 1–2 research corrections (FDA date, MDDS, Replay default, PDPL, evidence labels) |
| 2026-09-30 | 67883d9 | A6 | ScoreOutcome contract; critical vs artifact; headers; OperationOutcome |
| 2026-09-30 | 9d70a0e | A1 | Missing/misread ACVPU and O2 ⇒ INCOMPLETE. Note: 4 existing tests red at this commit by design until the next two commits |
| 2026-09-30 | ed45f8e | A1 | Delegated amendment: test_api_ingest.py (2 tests + 2 companions) |
| 2026-09-30 | 2e63e8a | A1 | Delegated amendment: test_hl7v2_waveform_pipeline.py (2 tests + 2 companions) |
| 2026-09-30 | 7cad9b8 | A2 | Staleness / future / unparseable timestamps; fail-closed startup; conftest append-only windows; interim A2-1 |
| 2026-09-30 | c73e6e8 | N-01 | Between-band values → more severe neighbour |
| 2026-09-30 | 6b31cb6 | A3 | Corrected results accepted; absent status reported |
| 2026-09-30 | 5c3d2ee | N-02 | Preliminary results never emitted as final |
| 2026-09-30 | bf55396 | A4 | Units converted or rejected; comparators/compound values non-exact |
| 2026-09-30 | f1b5730 | A5 | Coding system honoured (partial; A5-1, A5-2 blocked) |
| 2026-09-30 | 622bd7d | A7 | Patient identity from all PID-3 repetitions; MSH-9/MSH-2 checks |
| 2026-09-30 | 7a2a175 | A8 | ACK correctness (partial; A8-1 blocked; durable queue deferred) |
| 2026-09-30 | 96d59cb | V-01 | Vendor code table → provenance-labelled data |
