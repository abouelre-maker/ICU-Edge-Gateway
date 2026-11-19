# Canonical Claims — Single Source of Truth

**Status:** authoritative from 2026-09-30. **Supersedes `claude/verified_claims_sheet.md`**,
which still contains now-disproven wording. Both engineering (Track E) and
commercial (Track C) work use this file until Phase 7 reconciles the old sheet.

Update the test counts below at the end of every Track E phase, with the date.

## Latest verified test status

| Date | Commit / branch | Result | Coverage | Lint / types | Interpreter |
|---|---|---|---|---|---|
| 2026-09-29 | `main` @ `83f3a7f` | 816 passed, 1 xfailed | 95% statements | ruff clean, mypy clean | Python 3.11.9 |
| 2026-09-30 | `hardening/assessment-2026-09` (Step 1 start) | 816 passed, 1 xfailed | 95% | ruff clean, mypy clean | Python 3.11.9 |
| 2026-09-30 | `hardening/assessment-2026-09` @ `96d59cb` (end of Phase 1) | 943 passed, 4 xfailed (1 original + 3 strict-xfail documenting blocked A5 sub-items) | 95% | ruff clean, mypy clean | Python 3.11.9 |
| 2026-09-30 | `hardening/assessment-2026-09` @ `6deea8d` (Phase 2, gate not passed) | 973 passed, 4 xfailed | 95% (last measured at Phase 1) | ruff clean, mypy clean | Python 3.11.9 |

## TRUE — may be said

- 816 automated tests pass, 1 expected failure, 95% statement coverage, lint and type
  checks clean (verified 2026-09-29, Python 3.11.9). Always quote the latest row above
  with its date.
- NEWS2 threshold tables verified against RCP 2017, including SpO2 Scale 2.
- Artifact rejection is designed to suppress a score rather than fake one.
- Advisory-only design. Deterministic, traceable scoring logic.
- A documented, maintained list of open risks and findings.
- All inputs so far are **synthetic**.
- The demo stack ran end to end on the owner's Windows machine on 2026-08-23 (a single
  local observation, not a benchmark).

## NOT TRUE — must never be claimed

- clinically validated; tested on real monitors or real patient data
- production-ready; certified, compliant, cleared, or approved by anyone
- "IEC 62304 Class B" → say instead: **"developed with reference to IEC 62304 and
  ISO 14971 practices; software safety classification pending"**
- multi-vendor support proven (vendor code tables are inferred, not taken from vendor
  specifications or observed traffic)
- "without custom mapping" / "no per-vendor configuration"
- edge-optimized or lightweight (the image was 372 MB in CI)
- secure for clinical network use today
- any throughput or latency figure

## KNOWN GAPS — disclose honestly

Status column is updated as Track E closes findings (see `ASSESSMENT_2026-09.md`).

| Gap | Findings | Status |
|---|---|---|
| No authentication or TLS on ingest paths | F-01, F-08, F-09/10 | OPEN — HTTP/WS auth implemented but NOT enabled (F01-1/F08-1); MLLP limited to an allow-list (loopback by default); no TLS |
| Some missing inputs default to "normal" | A1 | CLOSED 2026-09-30 (missing ACVPU/O2 ⇒ INCOMPLETE) |
| No staleness logic | A2 | CLOSED 2026-09-30, except sub-item A2-1 (absent MSH-7 + OBX-14 ⇒ placeholder time, never scored) awaiting decision |
| FHIR bundles with warnings are not strictly valid R4 | H-01 | OPEN |
| MLLP ACKs not fully conformant | A8, F-03 | PARTIAL: A8 fixed except MSH-10 de-duplication (A8-1); F-03 fixed except AR on above-cap frames (F03-1) |
| No durable queue | A8 | OPEN |
| No high availability | — | OPEN (not in scope) |
| Regulatory classification unresolved | R-01, R-02 | OPEN |
| Vitals split across multiple MLLP messages are not merged; each fragment yields INCOMPLETE | A2 (Q4, deferred) | OPEN (deferred by decision 2026-09-29) |

## REGULATORY HYPOTHESES — never assert; for counsel only

- The FDA CDS guidance (issued **6 January 2026**; the FDA page shows "current as of
  29 January 2026") probably does not exempt a streaming ICU scoring product. The
  "15 January" date found in this repo is unsourced and is fixed under R-05 in Phase 7.
- Medical Device Data System (21 CFR 880.6310): **unlikely to cover live streaming** —
  the regulation excludes devices intended for active patient monitoring, and FDA's 2022
  MDDS guidance treats active-monitoring functions as device functions. Possibly relevant
  to retrospective / replay use only; counsel to confirm.
- EU MDR Rule 11 likely classifies decision-support software IIa or higher.
- Egypt EDA pathway for medical-device software: unknown; to be researched.
- Consequence: for the next 6–12 months the software is offered **only** for
  non-clinical use, research use, integration testing, and shadow-mode evaluation.
  Outputs are never used for patient-care decisions. **The default pilot offer is the
  Replay pilot** (retrospective, de-identified, offline); a live shadow pilot is optional
  and gated on counsel and on the Track E findings closed at that time.
- Egypt Personal Data Protection Law 151/2020: executive regulations issued November
  2025; the grace period ends approximately October/November 2026.
