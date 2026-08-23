# ICU Edge-to-FHIR Interoperability Gateway

**A verified reference implementation and IP asset for HL7 v2 → FHIR R4
interoperability with embedded NEWS2 scoring.**

> **What this is, stated plainly.** A working, tested reference implementation
> and an intellectual-property asset. It is **not** a finished product, **not**
> a cleared or approved medical device, and **not** deployed in any clinical
> setting. Every claim below traces to a repository artefact or an observed
> run; nothing is projected, benchmarked against competitors, or attributed to
> a customer, because there are no customers and no competitive benchmarks.
>
> **Note on sourcing:** every claim below is drawn from
> [`claude/verified_claims_sheet.md`](../../claude/verified_claims_sheet.md),
> the approved-claims source of truth, and cites its own evidence inline.
> Anything that could not be evidenced was left out rather than softened.

---

## The problem

ICU bedside monitors emit HL7 v2.x. Modern EMRs consume FHIR R4. The gap is
bridged today by bespoke integration projects — per vendor, per unit, per
site — that must then be maintained indefinitely by whoever built them.

Two costs follow. The obvious one is integration spend. The less obvious one
is clinical: when normalisation is bespoke, early-warning scoring tends to be
bolted on inconsistently, and alarm burden is managed by whoever wired it up
rather than by design.

---

## What the code actually does

| Capability | Evidence |
|---|---|
| Ingests HL7 v2.x ORU^R01 over **MLLP** (raw TCP) and **HTTP** | `mllp_listener.py`, `api/v1/ingest.py`; exercised end-to-end |
| Normalises **five monitor vendors** — Philips, GE, Dräger, Mindray, Nihon Kohden — from proprietary *and* LOINC OBX-3 codes, detected from MSH-3 | `hl7v2_adapter.py` mapping tables; three dialects driven live |
| Emits **FHIR R4** Bundles: vital-sign Observations plus a NEWS2 Observation (SNOMED CT `1239842005`) with all seven components, each dual-coded LOINC + SNOMED | Observed Bundle: 9 entries, 7 components, 3 extensions |
| Computes **NEWS2** to RCP 2017, including SpO2 Scale 1 / Scale 2 routing and the single-parameter-of-3 escalation rule | `news2_calculator.py`; `tests/regulatory/test_news2_safety.py` |
| Rejects physiologically implausible readings **before** scoring, recording each rejection in the audit trail | `artifact_rejector.py`; observed live as a `REJECTED` marker with score withheld |
| Streams results live over **WebSocket** with per-client bounded queues | `live_dashboard_channel.py`; drives the dashboard |
| **Store-and-forward** buffering for WAN interruption | `ring_buffer.py` (drop-oldest, every drop counted and logged) |
| Delivers to subscribers via **FHIR R4 Subscription** rest-hook, and to cloud via **MQTT** | `subscription_dispatcher.py`, `mqtt_publisher.py` |
| Runs as a **non-root container** (UID 1001) with a HEALTHCHECK and OCI `samd.*` labels | `Dockerfile`; asserted by `.github/workflows/docker-verify.yml` |

**816 automated tests, 1 xfailed** (2026-08-21, Python 3.11.9), 95% statement
coverage of `src/`. These include regulatory tests that lock NEWS2 band
boundaries and pipeline ordering against silent drift — for example, a
structural test that fails if DSP cleaning is ever reordered after scoring.

### Measured throughput — conditions stated

100 messages driven through the real MLLP listener on one developer laptop
(Windows 11, Python 3.11.9), every one producing a FHIR Bundle containing the
NEWS2 Observation and a WebSocket frame, **zero drops**:

| Measure | Value | What it covers |
|---|---|---|
| Domain pipeline (`X-Pipeline-Duration-Ms`) | **0.22 – 0.70 ms** | HL7 parse → DSP → NEWS2 → FHIR assembly |
| MLLP round-trip, idle machine | **p50 46 ms · p95 65 ms** | full socket send → ACK received |
| MLLP round-trip, machine also running the dashboard and a browser | p50 ~150 ms · p95 ~390 ms | same, under contention |

The clinical pipeline itself is sub-millisecond; the round-trip figure is
dominated by transport and by whatever else the host is doing. Both are given
because quoting only the favourable one would misrepresent what a site would
see. **These are laptop numbers, not a sizing guarantee** — no production
hardware has been characterised.

---

## Value by buyer

### Hospital network / health system

- **One normalisation layer instead of one per vendor.** Adding a monitor
  vendor is a mapping-table entry, not an integration project.
- **NEWS2 computed consistently at the edge**, with the seven component
  sub-scores exposed — so a clinician sees *which* physiology drove a score,
  not only the total.
- **Artifact rejection is auditable.** Implausible readings are excluded
  before scoring and recorded in `Bundle.note`. When a NEWS2-mandatory
  parameter is rejected, the system **withholds the score entirely** rather
  than scoring the patient as well — the conservative direction.
- **Deploys at the edge**, one container per ICU node. Scaling is by pod, not
  by tuning worker counts.

### EMR vendor

- **Standards-native output.** Nothing bespoke to map: FHIR R4 resources,
  LOINC, SNOMED CT, UCUM.
- **A documented API surface** — OpenAPI 3.1, Swagger, ReDoc, an offline spec
  export, and a documented WebSocket frame schema.
- **An explicit response-header contract**, including the two traps that bite
  integrators: uvicorn lower-cases header names, and a missing `X-NEWS2-Total`
  means *no score*, never zero.
- **FHIR Subscription rest-hook delivery** already implemented.

### Monitor OEM

- **Your proprietary OBX-3 codes are already mapped** — vendor detected from
  MSH-3, no per-device configuration.
- **MLLP-native.** The protocol your devices already speak, with correct
  framing, ACK/NAK semantics, and a hard guarantee that one malformed message
  never drops the connection.
- **A path to FHIR without changing your firmware.**

---

## Deployment model

Edge container per ICU node. MLLP inward from monitors; HTTP/WebSocket/MQTT
outward. Store-and-forward buffering means a WAN interruption does not block
ingestion. Horizontal scaling is by node, matching how ICUs are physically
organised.

---

## Regulatory posture — stated honestly

The gateway is engineered under IEC 62304 Class B software life-cycle practices with ISO 14971 risk
analysis applied to each hazard, and is designed against the non-device clinical decision support
criteria in FD&C Act §520(o)(1)(E) as interpreted by FDA's Clinical Decision Support Software
guidance. Output is advisory only and requires independent clinician review; the software triggers
no automated treatment. These are the developer's own determinations and have not been reviewed by
FDA or any notified body.

Design-history documents exist in `docs/` (SRS, SAD, RTM, RMF) and hazard
analyses are recorded in source alongside the controls they justify.

**What has not happened:** no regulatory submission, no clearance, no
approval, no notified-body review, no clinical validation study, no
deployment with real patients.

Two open items are tracked in the repository rather than hidden:

- **REG-CITATION-001** — the FDA CDS exemption citation embedded in emitted
  output appears incorrect and is under review. Raised by us, before anyone
  asked.
- **Clinical-validity evidence** under the January 2026 CDS guidance update
  has no owner yet. The existing regulatory tests demonstrate conformance to
  the RCP 2017 *specification*, which is not the same thing and is not offered
  as such.

A buyer's diligence will find both. Better that they find them already
written down.

---

## Roadmap — recorded, not built

**Per-patient SpO2 scale registry.** Today the MLLP listener applies one
process-wide SpO2 scale to every message, because HL7 v2.x has no field to
carry a scale assignment and the gateway deliberately refuses to infer one
from SpO2 values — that is a clinician's decision (ISO 14971
HAZARD-SPO2-001).

The right answer is a **clinician-facing registry** the listener consults per
patient: the assignment is made and attributed by a clinician, recorded with
provenance, and applied automatically to that patient's monitor feed. This is
a meaningful piece of clinical workflow, not a configuration flag, and is
**not implemented**. The HTTP endpoints already carry the scale explicitly per
request, which is how the Scale 1 / Scale 2 comparison is demonstrated today.

Also open: TLS/mTLS on the MLLP listener, authentication and authorisation,
CORS lock-down from `allow_origins=["*"]`, persistence and audit-log
retention, and IEC 62304 documentation for the newer modules.

---

## Licensing hooks

The asset is the **normalisation layer, the NEWS2 scoring engine with its
verification-test evidence, and the regulatory paper trail**
("verified", deliberately, not "validated" — there is verification evidence
against the RCP 2017 specification, and no clinical validation study) — not the dashboard, which is a demonstration
tool deliberately excluded from the device image.

Plausible structures: per-node subscription for health systems; OEM licence
for EMR vendors embedding the normalisation layer; white-label for monitor
manufacturers. Which fits depends on who moves first, and none has been
tested against a real buyer.

---

## What a pilot would need

A real monitor feed, a defined ICU node, and the two hours of integration-team
time it takes to point an interface engine at port 2575. Everything above runs
today from a single command on a laptop — including the failure modes, which
are documented in [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md) rather than hidden.
