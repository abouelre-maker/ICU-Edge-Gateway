# Deployment Runbook — ICU Edge-to-FHIR Interoperability Gateway

**Status:** Current, verified against this repository as of commit `b166b17` and the
Phase 7 documentation additions in this session.

> **Scope note:** This runbook covers *software* installation, verification, and release
> tagging — a configuration-management milestone under IEC 62304 §8. It is **not** a
> regulatory release gate. Tagging `v1.0.0` in git does not constitute, imply, or require
> that REG-001 (classification) or QMS-002 (CSO risk ratification) be resolved first — those
> are independent, currently-open workstreams (see
> [README.md § Regulatory & QMS Package](../README.md#regulatory--qms-package)). Do not
> conflate a software version tag with a market-authorization claim.

---

## 1. Prerequisites

| Requirement | Verified version (this environment) |
|---|---|
| Python | ≥3.10 per `pyproject.toml`; verified working on 3.13.1 |
| pip | Any recent version |
| Docker (containerized path only) | Any version supporting multi-stage builds |
| git | Any recent version |

## 2. Local Installation

```bash
git clone <repository-url>
cd ICU-Edge-Gateway
python -m pip install -r requirements.txt -r requirements-dev.txt
```

**Note on `requirements.txt`:** as of this session, `fastapi` and `uvicorn` were added to
`requirements.txt` — they were previously missing despite being hard runtime dependencies
of `src/main.py` and the Dockerfile's `CMD`. If you're running against an older checkout,
confirm `requirements.txt` includes both before proceeding; installation will otherwise
appear to succeed but the server will fail at import time.

## 3. Environment Configuration

| Variable | Required? | Behavior |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | **Required for any non-local deployment** | Comma-separated explicit origin allow-list. Unset → falls back to `http://localhost:3000` (dev only). Set to `*` or left empty-string → the app **refuses to start** (`ValueError`, HAZARD-CORS-001 mitigation, [src/config.py](../src/config.py)). |

```bash
export CORS_ALLOWED_ORIGINS="https://your-ehr-frontend.example.org"
```

## 4. Verification — run this before every deployment, no exceptions

```bash
# Lint
ruff check src tests

# Full test suite with coverage
pytest --cov=src --cov-report=term-missing
```

**Expected result** (as of this repository state):

```
332 passed, 1 xfailed, 91% total coverage
ruff check: clean
```

**Do not deploy if:**
- Any test fails (other than the single documented `xfail(strict=True)` for
  HAZARD-DSP-005 — if that one unexpectedly *passes*, `strict=True` will fail the suite
  automatically, which is itself a signal requiring investigation before deploying, not a
  green light).
- Coverage drops below the current 91% baseline without an explicitly reviewed reason.
- `ruff check` reports any error.

## 5. Local Run (non-containerized)

```bash
python -m uvicorn main:app --app-dir src --host 0.0.0.0 --port 8000
```

Smoke test:

```bash
curl http://localhost:8000/health
# Expect: HTTP 200, JSON body with status information

curl http://localhost:8000/docs
# Expect: HTTP 200, Swagger UI HTML
```

## 6. Containerized Deployment

```bash
docker build -t icu-edge-gateway:v1.0.0 .
docker run -d \
  --name icu-edge-gateway \
  -p 8000:8000 \
  -e CORS_ALLOWED_ORIGINS="https://your-ehr-frontend.example.org" \
  icu-edge-gateway:v1.0.0
```

The image's built-in `HEALTHCHECK` polls `GET /health` every 30s (10s timeout, 15s start
period, 3 retries) — confirm `docker ps` reports `healthy` before considering the deployment
complete:

```bash
docker ps --filter "name=icu-edge-gateway" --format "{{.Status}}"
```

**Container security properties already built in** (verify, don't just trust the comment):
non-root user (`gateway`, uid 1001), Alpine-based minimal image, no dev/test files copied
into the runtime stage (`src/` only).

## 7. Pre-Release Checklist (run through before tagging)

- [ ] Section 4 verification passed with the expected results.
- [ ] `CORS_ALLOWED_ORIGINS` documented for the target deployment environment (not left as
      the localhost dev default).
- [ ] **Version metadata reconciled — currently inconsistent, not yet fixed:**
      `pyproject.toml` declares `version = "0.1.0"`
      ([pyproject.toml:7](../pyproject.toml)), while `src/main.py`'s FastAPI app declares
      `version="1.0.0"` ([src/main.py:60](../src/main.py)) and the Dockerfile's OCI label
      also says `1.0.0` ([Dockerfile:42](../Dockerfile)). **Decide which is authoritative
      and update the other(s) before tagging** — I have not changed this myself since it's a
      release-versioning decision, not a bug fix. If `1.0.0` is correct (matches the
      Dockerfile and app metadata, and this runbook's own examples), the fix is:
      ```diff
      - version = "0.1.0"
      + version = "1.0.0"
      ```
      in `pyproject.toml`.
- [ ] Regulatory/QMS docs reviewed for currency — if REG-001's decision has been made since
      this runbook was written, update [README.md](../README.md)'s status table accordingly
      before release (don't let a "draft, pending decision" label go stale once a decision
      exists).
- [ ] `git status` clean — no uncommitted changes.
- [ ] `CHANGELOG.md` — **does not currently exist in this repository.** Recommend creating
      one before the first tagged release if your organization's process expects it; not
      created as part of this runbook since its content (what counts as "released" scope)
      is a product decision, not something inferable from the code alone.

## 8. Tagging the Release

```bash
git tag -a v1.0.0 -m "v1.0.0: Phase 6 engineering complete (CORS/DSP-006/DSP-004 hazards
resolved, HL7 NA/ED waveform parsing), Phase 7 regulatory/QMS drafts (REG-001, QMS-001,
QMS-002, CSO appointment brief) delivered pending human sign-off."
git push origin v1.0.0
```

Do not include marketing or regulatory-clearance language in the tag message — it should
describe software state only, consistent with this runbook's scope note above.

## 9. Rollback

```bash
docker stop icu-edge-gateway && docker rm icu-edge-gateway
docker run -d --name icu-edge-gateway -p 8000:8000 \
  -e CORS_ALLOWED_ORIGINS="..." \
  icu-edge-gateway:<previous-tag>
```

No database or persistent state exists in this service (stateless request/response
middleware) — rollback is simply running the previous image tag. Confirm this remains true
if future work adds any persistence layer.

## 10. Post-Deployment Verification

Re-run the Section 5/6 smoke tests against the deployed endpoint, plus one functional check:

```bash
curl -X POST https://<deployed-host>/api/v1/vitals \
  -H "Content-Type: application/json" \
  -d '{"patient_id": "SMOKE-TEST", "samples": [...]}'
# Confirm: HTTP 200, FHIR Bundle response, X-CDS-Advisory-Only: true header present
```

(Construct a valid minimal payload from `tests/integration/test_api_vitals.py` fixtures if
you need a concrete example.)
