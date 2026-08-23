# Verified Claims Sheet — ICU Edge Gateway

**Purpose.** Every commercial artifact — pitch deck, Loom script, cold email, one-pager, Zulip post —
draws its factual claims from this sheet and nowhere else. If a statement is not in the CAN SAY
table with evidence beside it, it does not go in front of a buyer.

**Why this exists.** A US healthcare enterprise buyer's technical due diligence will check these
claims. One overstatement discovered discredits the twenty accurate ones next to it. The asset's real
strength is the evidence discipline behind it — the marketing must not undercut the thing it sells.

**Status:** **MERGED TO `main` 2026-08-23** via merge commit `c143037` (PR #1, a true merge commit with two
parents — the 43 individually-evidenced commits are preserved on `main`, deliberately not squashed, because that
granular history is the IEC 62304 traceability trail). `main` now carries 53 commits; the remote feature branch
`phase5/streaming-mllp-listener` has been deleted. Verified on `main` after the merge: **816 passed / 1 xfailed**,
**95% coverage** (2302 statements, 124 missed; CI reports the same measurement as 94.61%), `ruff check .` clean,
`mypy src` clean across 46 files. CI on `main`: Quality Gate **green** (Ruff, Mypy, Bandit, pip-audit, pytest all
pass), Docker Verify **green**, Docker Build **fails on image size only** — the known, tracked GAP-DOCKER-SIZE-001,
not a regression from the merge. Four items remain open: **GAP-DOCKER-SIZE-001** (372 MB vs the 150 MB edge budget),
**REG-CITATION-001** beyond site E1, **HAZARD-DSP-007** awaiting sign-off, and **FLAKE-MQTT-001**. Commit counts in
this sheet have gone stale three times — re-measure with `git rev-list --count HEAD` rather than quoting.

---

## 1. CAN SAY — verified, with the evidence

| Claim | Evidence | Verified how |
|---|---|---|
| **816 automated tests passing, 1 xfailed** | Full suite | Local (`pytest --cov=src`, venv311 / Python 3.11.9) **and CI-CONFIRMED 2026-08-23** on commit `fa0c61e` — [run](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32634489719): `816 passed, 1 xfailed` in 30.01s on a clean ubuntu-latest runner, coverage gate of 90% met. This is the first CI run in which the pytest step completed green; the three before it either skipped it or failed it |
| **95% statement coverage of `src/`** | 2302 statements, 124 missed | `pytest --cov` locally and **CI-confirmed 2026-08-23** — [run](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32634489719) reports **94.61%**, which is the same measurement: 124/2302 missed is 94.61%, which pytest-cov's terminal summary rounds to 95%. Quote either, but do not quote 95% as if it were a separate, higher figure |
| **Zero-regression discipline across six phases** | 667 → 709 → 744 → 816, baseline held at every gate | Recorded per phase |
| **Static analysis clean** | `ruff check .` clean repo-wide; `mypy src` success across 46 files; Bandit clean at severity floor `low` | Local run **and CI-confirmed 2026-08-23** on commit `74a6a02` — [run](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32631860663): Ruff, Mypy and Bandit steps all green on a clean ubuntu-latest runner |
| Real-time **HL7 v2.5.1 ORU^R01** ingestion over **MLLP** (VT/FS/CR framing, 1 MiB cap, AA/AE ACK, malformed message NAKs without dropping the connection) | `mllp_listener.py` + integration tests | Driven live with real framed messages |
| **Multi-vendor normalization** — Philips proprietary OBX codes, GE with LOINC, Dräger — three beds concurrently, no per-vendor configuration | 3-bed streamer through the live listener | Observed live on the bed wall |
| **Deterministic RCP 2017 NEWS2**, all seven parameters, every scoring boundary tested at the exact threshold — including the non-monotonic 41–50 bpm band and both SpO2 scales | `test_news2_calculator.py`, `test_news2_safety.py` | Parametrized boundary tests |
| **FHIR R4 Bundle** output with a NEWS2 Observation coded **SNOMED CT 1239842005**, seven `component[]` sub-scores with dual LOINC + SNOMED coding and UCUM units | `news2_builder.py`, conformance tests | Captured from a running gateway |
| **100 messages through MLLP: 100/100 ACKs, 100/100 Bundles carrying a NEWS2 Observation, 100/100 WebSocket frames, zero drops** | End-to-end smoke test | **Re-run 2026-08-22T20:23:31Z and retained: [`docs/demo/evidence/mllp_smoke_100.txt`](../docs/demo/evidence/mllp_smoke_100.txt)** (run tag SMOKE1787430202, venv311 / Python 3.11.9). 100 sent · 100/100 ACKs, all `MSA\|AA` · 100/100 Bundles with a NEWS2 Observation · 100 WS deltas, 100/100 matched to this run · 0 drops. The same artifact records the emitted `Observation.note[].text` and an explicit `'880.3780' present: False` check, evidencing REG-CITATION-001 E1. **Round-trip timings in this artifact are p50 63 ms / p95 156 ms — a loaded-machine run, not the idle-laptop figures in the row below. Do not mix the two.** |
| **Pipeline processing time 0.22–0.70 ms** (`X-Pipeline-Duration-Ms`); **MLLP round-trip p50 46 ms / p95 65 ms on an idle developer laptop**, p50 ~150 ms / p95 ~390 ms under concurrent load | Instrumented measurement | Measured live — **always quote with the conditions** |
| **Deterioration detection demonstrated end-to-end**: NEWS2 0 NORMAL → 3 LOW → 6 MEDIUM → 7 HIGH → 17 HIGH | Sepsis scenario through the real pipeline | Observed live, screenshotted |
| **The single-parameter rule made visible**: two beds at an identical total of 3 render differently — one `LOW-MEDIUM` (amber, "minimum 1-hourly observations", driven by RR 8 scoring 3) and one `LOW` (green, "minimum 12-hourly"). Same number, different escalation | Purpose-built scenario | Observed live, screenshot 07 |
| **Risk bands are distinguishable without relying on hue** — shape markers (▲ / ▲▲ / ●●) accompany colour | Dashboard | Observed live |
| **SpO2 Scale 1 vs Scale 2 materially changes the score**: identical data scored **2 LOW** on Scale 2 vs **5 MEDIUM** on Scale 1 — a 3-point swing crossing a risk band | Both figures returned by the gateway's own calculator | Verified live over HTTP |
| **Artifact rejection suppresses the score rather than faking one**: an out-of-bounds heart rate is marked REJECTED and NEWS2 shows **NO SCORE**, not a reassuring zero | Bounds checker + orchestrator | Driven live |
| **Non-finite value rejection (NaN / ±Inf)** with 42 dedicated evidence tests — **18 of which fail against the pre-fix code**, proving the tests are load-bearing rather than decorative | `test_hazard_dsp_007_nan.py` | Verified by reverting the fix and re-running |
| **Advisory-only posture enforced in the transport itself**, not only in documentation: `X-CDS-Advisory-Only: true` response header, a FHIR extension, and a Bundle note on every response | API + FHIR layer, asserted by tests | Integration tests |
| **Resilience**: disconnect detected, cards dimmed with true data age, automatic reconnect without restart; bounded per-client queue (200, drop-oldest, logged); store-and-forward ring buffer (10,000) for WAN outage | Live kill-and-recover test | Observed live, screenshotted |
| **API contract stability**: 0 paths added, 0 removed; `/health`, `/api/v1/ingest`, `/api/v1/vitals` byte-identical to the committed spec across all demo-layer work | OpenAPI diff | Automated comparison |
| **Demonstration layer is architecturally excluded from the medical device — machine-enforced, now EXECUTED**: inside the built image `/app/demo` is absent, as are `/app/requirements-demo.txt`, `/app/run_demo.sh`, `/app/run_demo.bat`, `/app/scripts`, `/app/tests`; and `streamlit`, `plotly`, `pandas`, `altair`, `pydeck` are all non-importable | `docker-verify.yml`, step "Assert the demonstration layer is ABSENT from the image" | **CI-confirmed 2026-08-23 on commit `74a6a02`** — [run](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32631860667) (pull_request) and [run](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32631858092) (push), both green |
| **The production image runs as non-root**: `uid=1001 gid=1001` | `docker-verify.yml`, step "Assert the container runs as UID 1001" | **CI-confirmed 2026-08-23** — [run](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32631860667). Quote the UID, not a security posture |
| **The image boots and self-reports healthy**: container accepting connections after **5 s**, Docker `HEALTHCHECK` reaching `healthy` after **2 s**; `GET /health` returns 200 with all four components healthy, and `POST /api/v1/ingest` returns 200 with `X-CDS-Advisory-Only: true`, media type `application/fhir+json`, and a **9-entry Bundle** containing the NEWS2 Observation | `docker-verify.yml` runtime assertions | **CI-confirmed 2026-08-23** — [run](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32631860667). These are ubuntu-latest GitHub-runner timings; quote them with that condition |

**Numbers to quote exactly:** 816 tests / 1 xfailed · 95% coverage · NEWS2 0→3→6→7→17 · Scale 2 = 2 LOW
vs Scale 1 = 5 MEDIUM (+3) · 100/100 zero drops · pipeline 0.22–0.70 ms · SNOMED CT 1239842005 ·
HL7 v2.5.1 · FHIR R4.

---

## 2. CANNOT SAY YET — and what would make each sayable

| Do not claim | Why not | What would earn it |
|---|---|---|
| "ISO 14971 risk register entry HAZARD-DSP-007" | The entry is now **drafted as a proposal awaiting human sign-off**. It is not signed | A qualified person reviews and signs it |
| "IEC 62304 compliant" / "certified" | Code is *engineered to* Class B practices and cites them throughout, but there is no audited QMS, no assembled Design History File, no independent assessment. Nobody certifies IEC 62304 for a component in isolation | Assemble the DHF; commission a gap assessment |
| "FDA CDS Non-Device Exemption applies" | A **self-assessment**. FDA issues no exemption letters for CDS — the developer determines it and carries the risk | Say "designed against the non-device CDS criteria"; commission a regulatory opinion |
| **"21 CFR §880.3780"** as the CDS authority | Very likely the wrong authority, and it is **emitted inside `Observation.note[].text` in every Bundle** — REST, WebSocket, MQTT, Subscription — so it can persist into a clinical record. The carve-out is statutory: **FD&C Act §520(o)(1)(E) / 21 U.S.C. §360j(o)**, interpreted by FDA's CDS guidance (**updated 15 January 2026**). A second, inconsistent citation ("21 CFR Part 880.3") also appears in `vital_sign.py` | Counsel confirms the correct authority; corrected repo-wide as a documented change. Tracked as REG-CITATION-001 |
| "Health Canada Class II" | Self-classification. No licence, no submission | A Medical Device Licence application |
| "Clinically validated" | **Zero real patient data. Zero traffic from a real monitor.** Every message so far is synthetic. The regulatory tests prove conformance to the RCP 2017 *specification* — a different and lesser claim | A pilot on real HL7 traffic, then a retrospective accuracy study |
| "Production-ready" | No deployment has happened. TLS/mTLS, authn/z, CORS lock-down (currently `allow_origins=["*"]`), persistence and audit-log retention are all absent | Deploy it somewhere real under those controls |
| **"Edge-optimized" / "lightweight footprint"** — and any favourable image-size claim | **GAP-DOCKER-SIZE-001.** The image measures **372 MB against the project's own 150 MB edge-deployment limit** — `docker-build (size-limited)` **FAILS** in CI ([run](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32634489719)), while `docker-verify` (behaviour) **PASSES** on the same image. Not yet re-architected. The size had never been measured before 2026-08-23 because that job was skipped in every earlier run; it is a first measurement, not a regression. Layer count still unread | A multi-stage build or the `Dockerfile.slim` rework on `python:3.11-slim`, **or** a deliberate re-baseline of the edge budget with written rationale. Changing the base image alters the SOUP inventory, so it needs sign-off. See `regulatory/findings/GAP-DOCKER-SIZE-001.md` |
| Throughput at ICU density | Never load-tested beyond a single laptop | A load test with published methodology |
| Cloud deployment | Terraform is committed but **never applied**; no AWS credentials, no `terraform plan` | `terraform apply` against a real account |
| "`run_demo.bat` works" | Only its guard logic was exercised. The success path is untested on Windows | Run it end to end once |
| "299" / "311" / "744" tests | All stale. The number is **816** | — |

---

## 3. Approved regulatory phrasing

Use this wording. It is defensible, and it signals competence rather than bravado.

> The gateway is engineered under IEC 62304 Class B software life-cycle practices with ISO 14971 risk
> analysis applied to each hazard, and is designed against the non-device clinical decision support
> criteria in FD&C Act §520(o)(1)(E) as interpreted by FDA's Clinical Decision Support Software
> guidance. Output is advisory only and requires independent clinician review; the software triggers
> no automated treatment. These are the developer's own determinations and have not been reviewed by
> FDA or any notified body.

**On the January 2026 guidance update.** FDA's revised CDS guidance relaxed Criterion 3 for
single-recommendation outputs — relevant here, since NEWS2 produces one score — while adding an
explicit expectation that developers hold evidence of clinical validity for exactly such outputs.
NEWS2's clinical validity rests on the published RCP 2017 literature, not on this implementation.
State that distinction plainly: *the algorithm is externally validated; this implementation is
verified against it.* Accurate, and a strength.

**Never use:** FDA-approved · FDA-cleared · certified · compliant (unqualified) · validated
(unqualified — say "verified against") · production-ready · HIPAA-compliant · game-changing ·
revolutionary · seamless · cutting-edge.

---

## 4. Disclose these proactively

Volunteering a gap before the buyer finds it converts a weakness into evidence of rigour. Technical
buyers in this market are unusually receptive to it.

1. No real patient data yet — synthetic only, deliberately labelled as such on every screen.
2. Regulatory posture is self-assessed and awaits counsel review; REG-CITATION-001 is open.
3. The security layer (TLS, authn/z, CORS) is deployment work, not yet done.
4. The container image is verified by CI, not by hand. **CI has now run** (2026-08-23, `74a6a02`): `docker-verify.yml` passed every assertion, so non-root operation, the HEALTHCHECK and the
   demo-layer exclusion are in §1. Image size and layer count remain unread — that workflow writes
   them only to the job summary, never to stdout.
5. One timing-sensitive async test (`test_failed_item_is_requeued_not_dropped`, FLAKE-MQTT-001) failed
   once under CPU contention and passed on every subsequent run. Recorded and left unexplained rather
   than silenced by loosening the assertion.
7. **The production image is 372 MB against our own 150 MB edge budget (GAP-DOCKER-SIZE-001).** It builds, runs
   non-root, and passes every behavioural assertion in CI — and it is 2.5× the footprint the "edge-optimized"
   positioning implies. Volunteer the number with the behavioural evidence; quoting one without the other is
   exactly the selective disclosure this sheet exists to prevent.
6. **`pytest==7.4.4` carries `PYSEC-2026-1845` (fixed in 9.0.3), and the test toolchain still runs it.**
   On 2026-08-23 the pin was removed from `requirements.txt`, where it never belonged — pytest is a
   test-only tool, it is absent from the production image (CI confirms `/app/tests` is not in the
   image and the Dockerfile copies only `src/`), so it is not production SOUP. That unblocks
   `pip-audit --requirement requirements.txt`. **It does not remediate the advisory:**
   `requirements-dev.txt` still pins `pytest==7.4.4`, CI installs that file, and the vulnerable
   version is therefore still what runs the suite — it is simply no longer *scanned*, because the
   scan is scoped to production requirements. Do not present the green pip-audit as "the CVE is
   fixed". The honest statement is that it was moved out of production scope and remains open in the
   development toolchain. Upgrading to pytest 9.x is a separate change that would need the full suite
   re-verified against it.

---

## 5. The honest positioning

Not "a production-ready SaMD". It is **a verified reference implementation and IP asset**: the HL7 →
artifact rejection → NEWS2 → FHIR R4 pipeline, built to medical-software engineering discipline, with
the evidence trail a regulatory reviewer would ask for, ready for a partner to take through clinical
validation and submission.

That framing survives due diligence. The stronger-sounding one does not — and the difference shows up
in the first technical call, not the last.
