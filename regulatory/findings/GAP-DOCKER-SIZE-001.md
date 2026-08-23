# GAP-DOCKER-SIZE-001 — Production Image Is 2.5× the Declared Edge Size Budget

**Status:** 🔍 **OPEN — TRACKED, ACCEPTED AT MERGE**
**Raised:** 2026-08-23
**Priority:** Medium. Not a safety issue. It is a **claims** issue: it contradicts
the "edge-optimized" positioning until either the image or the budget changes.

## What fails

```
.github/workflows/ci.yml
  job: Docker Build — Alpine 3.19, Edge-Optimized (size-limited)
  step: Verify image size < 150 MB
```

```
Size limit : 150 MB
ERROR: Image (372 MB) exceeds the 150 MB edge limit.
```

**372 MB measured against a 150 MB limit — 2.48×.**

## Why it surfaced only on 2026-08-23

This job has **never succeeded on this branch**. In every prior CI run it was
`skipped`, because the `quality-gate` job failed ahead of it and it depends on
that job:

| Run | Commit | quality-gate | docker-build |
|---|---|---|---|
| 31752800014 | `89b0227` | failed at Bandit | skipped |
| 31757233522 | `94cbe08` | failed at pytest | skipped |
| 32631860663 | `74a6a02` | failed at pip-audit | skipped |
| 32634177687 | `29ec3eb` | failed at pip-audit | skipped |
| 32634489719 | `fa0c61e` | **passed** | **failed — 372 MB** |

Fixing the pip-audit trigger (commit `29ec3eb`, the `pytest` pin removal) let
`quality-gate` go green for the first time, which let `docker-build` run for the
first time, which measured the image for the first time.

**The image was almost certainly always this size.** This is a measurement that
had never been taken, not a regression introduced by any commit on this branch.
Do not attribute it to the Phase 5–9 work.

## What is NOT wrong with the image

`docker-verify.yml` — a separate workflow — **passes every assertion** on the
same image, and did so on this exact commit:

- builds cleanly on Alpine (no musllinux wheel fallback)
- runs as **non-root**, `uid=1001 gid=1001`
- accepts connections after **5 s**; `HEALTHCHECK` healthy after **2 s**
- `GET /health` → 200, all four components healthy
- `POST /api/v1/ingest` → 200, `X-CDS-Advisory-Only: true`,
  `application/fhir+json`, 9-entry Bundle with the NEWS2 Observation
- the demonstration layer is **absent**: `/app/demo`, `/app/requirements-demo.txt`,
  `/app/run_demo.sh`, `/app/run_demo.bat`, `/app/scripts`, `/app/tests` all gone;
  `streamlit`, `plotly`, `pandas`, `altair`, `pydeck` all non-importable

So the image is **functionally correct and regulatorily well-scoped**. It is
simply far larger than the footprint the project claims for itself.

## Likely cause

The numeric stack dominates. From the CI build log, wheel download sizes alone:

| Package | Wheel |
|---|---|
| `scipy==1.17.1` | 37.7 MB |
| `numpy==2.4.6` | 18.7 MB |
| `cryptography==50.0.0` | 5.0 MB |

Unpacked, plus the Alpine base and the build toolchain retained in a
single-stage image, 372 MB is unsurprising. **This is a hypothesis from the
build log, not a measured layer breakdown** — nobody has run
`docker history` against the image.

## What would close this

Either of the following, deliberately chosen — not whichever is easier:

1. **Re-architect the image.** A multi-stage build that discards the compiler
   toolchain, or the `Dockerfile.slim` on `python:3.11-slim` already contemplated
   in `docker-verify.yml`'s own failure guidance. Note that changing the base
   image alters the SOUP inventory and the attack surface, so it needs sign-off
   — it is explicitly *not* a CI-side substitution.
2. **Re-baseline the budget with a written rationale.** 150 MB was chosen as an
   edge-deployment constraint. Raising it is a product decision about whether the
   "edge-optimized" story still holds, not a config tweak. If the budget moves,
   the commercial copy must move with it.

## Claims impact — the reason this is tracked, not shrugged off

Until this closes, **"edge-optimized" / "lightweight footprint" is not a sayable
claim.** It sits in §2 CANNOT SAY YET of `claude/verified_claims_sheet.md`.

The honest formulation available today is: *the image builds, runs non-root,
passes every behavioural assertion in CI, and is 372 MB — against our own 150 MB
edge target, which it does not currently meet.*

Quoting the behavioural evidence while omitting the size would be exactly the
kind of selective disclosure this repository's evidence discipline exists to
prevent.
