# ICU Edge-to-FHIR Interoperability Gateway — One-Pager Content

> **Content only.** This is source material for a designed one-pager, not a finished
> visual document. Every fact below is sourced to a specific verification performed
> today (2026-08-14) or an existing `docs/*` file — the source is cited inline after
> each claim so the design pass can be re-verified without re-deriving it.

---

## What It Does

The ICU Edge Gateway is SaMD middleware that converts legacy ICU bedside monitor data
into standards-based clinical output, entirely at the edge:

**HL7 v2.x → DSP artifact rejection → NEWS2 → FHIR R4**

1. **Ingests** raw HL7 v2.x ORU^R01 messages from bedside monitors (five vendor
   dialects plus a LOINC-fallback generic path) over MLLP or HTTP.
2. **Runs a DSP artifact-rejection pipeline** — physiological bounds checking, 50/60 Hz
   dual-notch filtering, vital-sign-specific Butterworth bandpass filtering, and
   Hampel-filter motion-artifact rejection — before any value is eligible for clinical
   scoring.
3. **Calculates NEWS2** (RCP 2017 National Early Warning Score 2 algorithm), scoring
   only artifact-checked, physiologically-valid values.
4. **Emits a FHIR R4 Bundle** — NEWS2 Observation with per-component sub-observations,
   individual vital-sign Observations, and an explicit, machine-readable
   advisory-only marker on every response.
5. Runs **at the edge** — on the appliance in the ICU, not dependent on a cloud
   round-trip for the core ingest → score → output pipeline.

*Source: [README.md § "What this does"](../README.md#what-this-does);
[src/api/v1/ingest.py](../src/api/v1/ingest.py) module docstring.*

---

## Verified Engineering Facts (as of 2026-08-14)

| Fact | Value | Source |
|---|---|---|
| Test suite result | **661 passed, 1 xfailed** (intentional, `strict=True` — documents a known, characterized residual risk, HAZARD-DSP-005; not a skipped or ignored failure) | `pytest --cov=src --cov-report=term-missing` run today, this session |
| Line coverage | **95%** (2,302 statements, 124 missed) | Same `pytest --cov=src` run, this session |
| Lint status | `ruff check src tests` — clean, zero findings | `ruff check src tests` run today, this session |
| ISO 14971 hazard entries tracked | **40** populated rows in the live risk register (39 assigned `HAZARD-*` IDs + 1 row awaiting ID assignment) | Independently counted today via direct read of `ICU_Edge_Gateway_Risk_Register_2.xlsx` ("Risk Register" sheet, populated `Risk ID` column), cross-checked against [docs/RMF-001_Risk_Management_File.md](RMF-001_Risk_Management_File.md)'s own 2026-08-10 row-by-row correction (also 40) |
| Hazard entries closed vs. open | 22 "Closed - Mitigated"; 1 "Open - Accepted Residual Risk" (HAZARD-DSP-005 — engineering-decided only, not clinically ratified); 17 Open (various: Requires Action / Awaiting Decision / PROPOSED pending sign-off / INTERIM engineering sign-off / Deferred by Scope Decision / awaiting Risk ID assignment) | [docs/RMF-001_Risk_Management_File.md § 4](RMF-001_Risk_Management_File.md) |
| Interim (non-clinical) sign-off scope | Limited to exactly 2 hazards — HAZARD-DSP-007 and HAZARD-STREAM-012 — by a project-owner-level engineering appointment; does **not** extend to any other hazard in the register | [docs/RMF-001_Risk_Management_File.md § 5](RMF-001_Risk_Management_File.md); [docs/CSO_Role_Appointment_Brief.md](CSO_Role_Appointment_Brief.md) |

**Note on prior numbers:** README.md's Test Suite section currently states "332 passed,
91% coverage" — that figure predates this branch's additions (many new/modified test
files present in this session's working tree) and is stale relative to the 661/95%
figures above, which were measured directly, not carried over. This one-pager uses only
the number measured today.

---

## Architecture Differentiators

- **Edge-first deployment.** The full ingest → DSP → NEWS2 → FHIR pipeline runs on the
  appliance itself — a multi-stage, Alpine 3.19-based container image, non-root,
  targeting under 150 MB — not as a thin client dependent on a cloud service for its
  core clinical output. *Source: [Dockerfile](../Dockerfile) header comment; edge
  deployment manifest at [deploy/k3s/edge-appliance.yaml](../deploy/k3s/edge-appliance.yaml).*
- **Zero-touch mTLS device provisioning.** Edge appliances enroll against a control
  plane using a bootstrap handshake that establishes a device-specific mTLS identity
  (ECDSA keypair + CSR, CA-pinned) without manual per-device certificate handling, and
  periodically re-attest that identity. *Source:
  [src/infrastructure/provisioning/](../src/infrastructure/provisioning/)
  (`enrollment_client.py`, `device_identity.py`, `reattestation.py`);
  [docs/SAD-001_Software_Architecture_Description.md](SAD-001_Software_Architecture_Description.md)
  ("zero-touch device provisioning/enrollment").*
- **Standards-based FHIR R4 output.** Every response is a real FHIR R4 `Bundle`
  (type `collection`) built to the HL7 FHIR R4 specification — not a proprietary JSON
  shape — with NEWS2 expressed as a scored `Observation` with per-component
  sub-observations. *Source:
  [src/infrastructure/fhir/bundle_assembler.py](../src/infrastructure/fhir/bundle_assembler.py)
  module docstring (cites `http://hl7.org/fhir/R4/bundle.html`).*
- **Clean Architecture / hexagonal layering.** Clinical domain logic (DSP, NEWS2) has
  no I/O or framework dependency, is independently unit-tested, and is architecturally
  guarded from waveform data ever feeding the score
  (`TestWaveformNeverFeedsNews2Score`). *Source:
  [README.md § Architecture](../README.md#architecture).*

---

## Regulatory Status

> **This is a software component intended for integration under a licensee's own
> regulatory pathway. It has not been independently FDA-cleared or Health
> Canada-licensed. Device classification is pending formal regulatory determination.
> No credentialed Clinical Safety Officer has yet reviewed this system; current hazard
> sign-offs are interim, project-owner-level engineering decisions, not clinical
> validation.**

*This section must render as prominent body content in the finished one-pager — not a
footnote, not reduced-size type, not below the fold.*

---

## Explicitly Excluded From This Content

Per the brief for this document: **no pricing figures**, **no "compliance-backed" or
"verified safe" language**, and **no liability or exemption claims of any kind** appear
anywhere above. Any regulatory-adjacent phrasing in source code comments (e.g., "FDA CDS
Non-Device Exemption") is explicitly *not* repeated here as a claim — see
[docs/RMF-001_Risk_Management_File.md](RMF-001_Risk_Management_File.md)'s own banner:
those source-comment citations are "engineering design-intent markers... not a completed
regulatory submission."
