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
- **Entries:** none yet. Each will be appended below with node ID, assertion, locked-in
  behaviour, why it is wrong, and the two options.
- **Status:** OPEN (empty)

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
