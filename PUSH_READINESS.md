# Push Readiness — `phase5/streaming-mllp-listener`

**Prepared:** 2026-08-23 · **Branch:** `phase5/streaming-mllp-listener` → `main`
**Scope:** Phase 5 (streaming MLLP listener) through Phase 9 (commercial demo package).
**Nothing has been pushed.** This document is the pre-push record.

Claims here are bounded by [`claude/verified_claims_sheet.md`](claude/verified_claims_sheet.md).
Where that sheet's §2 says a thing cannot be claimed yet, this document does not claim it —
including after CI goes green.

---

## 1. Local verification gate — run 2026-08-23 on an idle machine

Run on `venv311` (Python 3.11.9), which matches the CI pin. The demo stack was stopped
first: `FLAKE-MQTT-001` is a timing-sensitive async test that failed once under CPU
contention, so the gate is not run while the gateway, dashboard and streamer are up.

| Gate | Command | Result |
|---|---|---|
| Test suite | `pytest --cov=src` | **816 passed, 1 xfailed** — matches the regression contract in `CLAUDE.md` |
| Coverage | (same run) | **95%** of `src/` — 2302 statements, 124 missed |
| Lint | `ruff check .` | clean, exit 0, repo-wide |
| Types | `mypy src` | **Success: no issues found in 46 source files** |
| API contract | live `app.openapi()` vs `docs/demo/openapi.json` | **whole-spec identical**; 5 paths, 0 added, 0 removed; `/health`, `/api/v1/ingest`, `/api/v1/vitals` byte-identical |

The OpenAPI comparison is whole-spec, not paths-only. It is clean because the offline copy
was regenerated in this session — see §4.

---

## 1a. UPDATE — CI has now run (2026-08-23, commit `74a6a02`)

This document was written before the first push. Both workflows have since executed.
This section supersedes the forward-looking language below where the two disagree.

| Workflow | Result |
|---|---|
| [Docker Verify — pull_request](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32631860667) | **success** |
| [Docker Verify — push](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32631858092) | **success** |
| [CI — Quality Gate](https://github.com/abouelre-maker/ICU-Edge-Gateway/actions/runs/32631860663) | **failure at `pip-audit`** |

**Now verified, and moved into §1 of the claims sheet:** the demonstration layer is absent
from the built image (`/app/demo` plus five further paths, and `streamlit` / `plotly` /
`pandas` / `altair` / `pydeck` all non-importable); the container runs as `uid=1001
gid=1001`; it accepts connections after 5 s with `HEALTHCHECK` healthy after 2 s;
`GET /health` returns 200 with all four components healthy; `POST /api/v1/ingest` returns
200 with `X-CDS-Advisory-Only: true`, `application/fhir+json`, and a 9-entry Bundle
carrying the NEWS2 Observation. Ruff, Mypy and Bandit are green on a clean runner.

**Still NOT verified.** *Image size and layer count* remain unquotable: `docker-verify.yml`
writes them only to `$GITHUB_STEP_SUMMARY`, never to stdout, so they are not in the log.
`ci.yml`'s `docker-build` job does echo the size to stdout, but it was **skipped** because
the quality gate failed ahead of it.

**The CI failure is not a regression from this branch.** All three runs to date failed at a
*different* step — `89b0227` at Bandit, `94cbe08` at pytest (the since-fixed HAZARD-DSP-007
NaN defects), and `74a6a02` at pip-audit. pip-audit *passed* on `94cbe08` nine days earlier
against the same unchanged `pytest==7.4.4` pin; `PYSEC-2026-1845` was published in between.

**`pytest` was skipped in every CI run so far**, so the 816 / 1 xfailed figure remains
**local-only** and must not be described as CI-confirmed until a run actually executes it.

---

## 2. What CI will verify once this is pushed

Two workflows fire. Neither has ever executed on this branch.

### `ci.yml` — Quality Gate (Ruff → Mypy → Bandit → pip-audit → pytest)

Re-runs the §1 gate on clean Ubuntu runners, plus two checks with no local equivalent:

- **Bandit** — static application security testing across `src/`, severity floor `low`.
- **pip-audit** — CVE scan of `requirements.txt`.

Value added over §1: it proves the results are not artefacts of one Windows developer
machine, and it runs the two security scanners that are not part of the local loop.

### `docker-verify.yml` — Production image verification

This is the workflow that converts the **largest** block of §2 "cannot say" items into
evidence, because **the image has never been built** — Docker is absent from the
development host. On push it will:

1. **Build** the Alpine image. Failure is reported with its log rather than silently
   swapping the base image — a base-image change affects the SOUP inventory and needs
   sign-off, not a CI-side substitution.
2. **Assert the regulatory scope guard** — that the demonstration layer is absent from
   the image: `/app/demo`, `/app/requirements-demo.txt`, `/app/run_demo.sh`,
   `/app/run_demo.bat`, `/app/scripts`, `/app/tests` all absent, and `streamlit`,
   `plotly`, `pandas`, `altair`, `pydeck` all non-importable inside the image.
3. **Assert non-root operation** — `id -u` is exactly `1001`.
4. **Start the container** and assert `GET /health` is 200 with all four components
   (`hl7v2_adapter`, `dsp_pipeline`, `news2_calculator`, `fhir_builder`) healthy.
5. **Assert `POST /api/v1/ingest`** returns 200, media type `application/fhir+json`,
   header `X-CDS-Advisory-Only: true` (matched case-insensitively — uvicorn lower-cases
   header names), and a Bundle containing the NEWS2 Observation (SNOMED `1239842005`).
6. **Assert the `HEALTHCHECK`** reaches `healthy`.
7. **Record image evidence** to the job summary — size in MB, layer count, and the OCI
   `samd.*` / `org.opencontainers.*` labels.

After a green run, these become quotable with their conditions stated: image size, layer
count, non-root UID, HEALTHCHECK behaviour, and the machine-enforced absence of the
demonstration layer from the device image.

---

## 3. What stays UNVERIFIED even after CI passes

Drawn from §2 of the claims sheet. A green CI run does **not** retire any of these, and
none may be claimed on the strength of it.

| Still not sayable after CI | Why CI cannot settle it |
|---|---|
| **"Clinically validated"** | Zero real patient data, zero traffic from a real monitor. Every message is synthetic. CI runs synthetic messages too. Needs a pilot on real HL7 traffic, then a retrospective accuracy study. |
| **"IEC 62304 compliant" / "certified"** | No audited QMS, no assembled Design History File, no independent assessment. Nobody certifies IEC 62304 for a component in isolation. CI runs tests; it does not assemble a DHF. |
| **"FDA CDS Non-Device Exemption applies"** | A self-assessment. FDA issues no exemption letters for CDS. Say "designed against the non-device CDS criteria". Needs a regulatory opinion. |
| **The correct CDS authority (REG-CITATION-001)** | Open. The statutory carve-out is FD&C Act §520(o)(1)(E) / 21 U.S.C. §360j(o), interpreted by FDA's CDS guidance (updated 15 January 2026). E1 (removing the citation from emitted output) is done and evidenced; the remaining source-comment citations in `news2_calculator.py` and `vital_sign.py` still await counsel. CI does not review citations. |
| **"Health Canada Class II"** | Self-classification. No licence, no submission. |
| **"ISO 14971 risk register entry HAZARD-DSP-007"** | Drafted as a proposal awaiting human sign-off. Not signed. A CI run is not a signature. |
| **"Production-ready"** | No deployment has happened. TLS/mTLS, authn/z, CORS lock-down (currently `allow_origins=["*"]`), persistence and audit-log retention are all absent. CI does not deploy. |
| **Throughput at ICU density** | Never load-tested beyond a single laptop. CI asserts correctness, not capacity, and a shared runner is not a sizing reference. |
| **Cloud deployment** | Terraform is committed but never applied. No AWS credentials, no `terraform plan`. Outside both workflows. |
| **"`run_demo.bat` works"** | Only its guard logic was exercised; the success path is untested on Windows. CI runners are `ubuntu-latest` and never execute it. |

One further item that CI *will* exercise but which should still be stated carefully:

- **FLAKE-MQTT-001** — `test_failed_item_is_requeued_not_dropped` failed once under CPU
  contention and passed on every subsequent run. Recorded in
  `regulatory/findings/FLAKE-MQTT-001.md` and deliberately not "fixed" by loosening the
  assertion. A green CI run is consistent with the flake still existing; it is not
  evidence that it is gone.

---

## 4. Changes made in this session

### 4.1 Regulatory copy reconciled against the claims sheet (Phase 9, Task 1)

Verified **as rendered**, with the stack restarted in the enforced order
(gateway → health gate → dashboard → streamer), not by reading source alone.

- `demo/dashboard.py` — the on-screen advisory banner no longer cites
  **`21 CFR §880.3780`**. It now carries the §3 approved posture wording, condensed for
  the banner without altering its meaning.
- `demo/dashboard.py` — **the sidebar "Regulatory" badge panel**, which a source-only
  scan missed and the rendered check caught. It asserted `FDA CDS Non-Device Exemption`
  and `Health Canada — Class II`, both forbidden by §2. The first is now stated as
  *designed against* the criteria; the second was **deleted outright** — it is pure
  self-classification with no defensible substitute wording. A caption now states these
  are the developer's own determinations, with no submission, clearance or licence.
- `src/main.py` — **scope note: this is outside `docs/demo/` and `demo/`.** The FastAPI
  `description` asserted the same two forbidden claims and is *served to integrators* via
  `/openapi.json`, ReDoc and Swagger UI, making it buyer-facing published copy rather
  than an internal comment. It now carries the §3 approved wording. No clinical logic was
  touched, so there is no ISO 14971 risk impact.
- `docs/demo/openapi.json` — regenerated from the corrected app. This also cleared
  **12 mojibake escape sequences** still present in the committed copy
  as raw `â€”` and `Â·` escapes — the UTF-8 bytes of the em-dash (`E2 80 94`) and the middle dot (`C2 B7`) each re-read as cp1252, the classic
  double-decode. Codepoints are now correct: U+2014, U+00B7, U+00A7, U+2192.
- `docs/demo/API_QUICKSTART.md`, `COMMERCIAL_ONE_PAGER.md` — both carried a stale note
  saying the claims sheet "does not exist in this repository". It does; both now cite it
  as the source of truth.
- `docs/demo/API_QUICKSTART.md` — the regulatory note claimed the emitted advisory text
  "currently includes a CFR citation". That became false when REG-CITATION-001 E1 landed;
  it now records the removal and cites the evidence artifact.
- `docs/demo/DEMO_SCRIPT_3MIN.md` — the "is it FDA approved?" answer now gives the §3
  paragraph verbatim as the only approved posture statement.
- `docs/demo/DEMO_RUNBOOK.md`, `demo/dashboard.py` — "validated test environment" →
  "verified", per the §3 never-use list.

Confirmed zero occurrences of the forbidden-word list across `docs/demo/` and `demo/`.
The only surviving matches are prohibition context (the script listing what *not* to say)
and negative checks (`'880.3780' present: False`). Every test-count and coverage mention
reads **816 / 1 xfailed / 95%**; no stale 299 / 311 / 667 / 709 / 744 figure remains.

### 4.2 MLLP smoke row reconciled

The claims sheet row for the 100-message MLLP smoke test previously read *"the evidence
artifact was not retained in the repo"*. Its "Verified how" cell now cites
[`docs/demo/evidence/mllp_smoke_100.txt`](docs/demo/evidence/mllp_smoke_100.txt) —
run tag `SMOKE1787430202`, 2026-08-22T20:23:31Z, venv311 — recording 100/100 ACKs all
`MSA|AA`, 100/100 Bundles with a NEWS2 Observation, 100 WebSocket deltas all matched to
that run, zero drops, plus the emitted note text and the `'880.3780' present: False`
check.

> **Flagged, not silently reconciled.** That artifact's round-trip timings are
> **p50 63 ms / p95 156 ms**, which are *not* the "p50 46 ms / p95 65 ms on an idle
> developer laptop" in the adjacent timing row — it was a loaded-machine run. Both
> figures are real under their own conditions. The sheet now warns against mixing them.
> The one-pager continues to quote the idle figures with the conditions stated, which is
> correct, but a buyer comparing the two documents will notice, so quote conditions.

### 4.3 Claims-sheet commit count corrected

The Status line read "33 commits on the working branch / 43 total". Measured 2026-08-23:
**37 on the branch, 47 total**. The 33/43 figure predates the four 2026-08-22 recovery
commits (`435d004`, `2650130`, `672e1f1`, `c61c367`). This figure has now gone stale
three times (19 → 33/43 → 37/47); it should be re-measured, not quoted.

---

## 5. Environment findings — documented and closed, not open risks

Both were found today. Neither is a live exposure, because the launcher fix already
closes the path by which a wrong interpreter could be used.

### 5.1 `venv/` — Python **3.13.1**, git-ignored, now rejected by the launcher guard

| | |
|---|---|
| Interpreter | 3.13.1 — **not** the 3.11.9 CI pin |
| Git status | ignored via `.gitignore:18` (`venv/`). Never committed, will not be pushed |
| Packages | 96, including `uvicorn==0.52.1` (vs `0.52.3` in the verified environments) |
| Live exposure | **Closed.** `435d004` pinned the POSIX launcher to `venv311`/`venv-demo` explicitly and removed the unpinned interpreter probe that could previously have selected this environment |

`run_demo.sh` now resolves `VENV_APP=venv311` and `VENV_DEMO=venv-demo` as fixed paths and
verifies each interpreter before doing any work — checking the `websockets` major version
on each side of 17, which is the actual constraint boundary, rather than mere package
presence. There is no code path by which `venv/` is selected.

**Status: resolved.** The directory is inert. Deleting it is optional housekeeping, not a
prerequisite for push.

> Note for anyone driving this repo: activating `venv` in a shell — e.g.
> `& venv\Scripts\Activate.ps1` — does **not** change which interpreter the launchers or
> the verification gate use, since both pin their interpreters by absolute path. It would,
> however, silently give an interactive `pytest` the wrong Python. Run the gate as
> `venv311/Scripts/python.exe -m pytest`.

### 5.2 `venv313_clean/` — Python **3.13.1**, inventoried

| | |
|---|---|
| Interpreter | 3.13.1 |
| Git status | ignored via `.gitignore:26` (`venv3*/`). Never committed |
| Packages | **87**, manifest at `venv313_clean_versions.txt` |
| Relation to `venv311` (88 packages) | Differs in **3** entries only: `numpy` 2.4.6 → **2.5.2**, `scipy` 1.17.1 → **1.18.0**, and `setuptools==65.5.0` present in `venv311`, absent here |
| Relation to `venv/` (the dirty 3.13) | **35** differing lines — `venv313_clean` is the tidy counterpart, `venv/` the drifted one |
| Shared with `venv311` | `fastapi==0.141.1`, `pytest==7.4.4`, `websockets==17.0.1` |

Its purpose is forward-compatibility scouting on 3.13 — the numpy/scipy delta is exactly
what a 3.13 move would drag in. **It is not the verification environment and must not be
used as one.** The regression contract (816 / 1 xfailed) is defined on venv311 / 3.11.9
because that matches the CI pin.

**Status: tracked, not a risk.** Inert, ignored, not pushed, and unreachable from the
launchers.

---

## 6. Working tree at time of writing

```
 M demo/dashboard.py
 M docs/demo/API_QUICKSTART.md
 M docs/demo/COMMERCIAL_ONE_PAGER.md
 M docs/demo/DEMO_RUNBOOK.md
 M docs/demo/DEMO_SCRIPT_3MIN.md
 M docs/demo/openapi.json
 M src/main.py
?? claude/
```

**These changes are uncommitted.** They must be committed before the push command in §7
carries them. `claude/verified_claims_sheet.md` is currently untracked — decide
deliberately whether the approved-claims sheet belongs in the repository or stays out of
it, since pushing it publishes the sheet along with the honest gap list in its §2.

---

## 7. Push and PR — commands only, NOT executed

Neither command below has been run. Nothing has been pushed.

```bash
git push -u origin phase5/streaming-mllp-listener

gh pr create --base main --head phase5/streaming-mllp-listener \
  --title "Phase 5-9: streaming MLLP listener through commercial demo package" \
  --body-file PUSH_READINESS.md
```

Expect `docker-verify.yml` to run on the push (it triggers on `push` to `**` with
`src/**` among its paths, and `src/main.py` changed) and again on the pull request.
This will be the first execution of that workflow, and therefore the first time any
container claim in the claims sheet has evidence behind it.
