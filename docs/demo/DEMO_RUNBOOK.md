# Demo Runbook

Operational guide for running the ICU Edge Gateway demonstration. The failure
modes listed here are ones that **actually occurred during development**, not
hypothetical ones — each is followed by what it looked like and what fixed it.

---

## 1. Pre-flight checklist

Do this before the meeting, not in it.

### ☐ 1. TWO Python environments exist — this is item one for a reason

This is the single most likely way the demo breaks in someone else's hands.

| Environment | Runs | websockets |
|---|---|---|
| `venv311` | gateway + streamer + tests | **17.0.1** |
| `venv-demo` | Streamlit dashboard **only** | **16.1.1** |

**They cannot be merged.** `streamlit` requires `websockets<17`;
`requirements.txt` pins `websockets==17.0.1` as a production runtime
dependency of the FHIR Subscription dispatcher and the live channel. Installing
Streamlit into `venv311` **silently downgrades** websockets and leaves the
validated test environment no longer matching its own pin file — exactly the
drift HAZARD-STREAM-013 was raised for.

Create them:

```bash
python -m venv venv311
venv311/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt

python -m venv venv-demo
venv-demo/Scripts/python -m pip install -r requirements-demo.txt
```

Verify:

```bash
venv311/Scripts/python   -c "import websockets; print('app :', websockets.__version__)"   # 17.x
venv-demo/Scripts/python -c "import websockets; print('demo:', websockets.__version__)"   # 16.x
venv311/Scripts/python   -c "import streamlit" && echo "CONTAMINATED"                     # must FAIL
```

The launchers check all of this and refuse to start with a named error. Do not
bypass that check.

### ☐ 2. Ports 8000, 8501, 2575 are free

```bash
netstat -ano | findstr "LISTENING" | findstr ":8000 :8501 :2575"    # Windows
lsof -iTCP:8000 -iTCP:8501 -iTCP:2575 -sTCP:LISTEN                  # macOS/Linux
```

### ☐ 3. The suite passes

```bash
venv311/Scripts/python -m pytest -q
```

Expect **816 passed, 1 xfailed**.

### ☐ 4. One full rehearsal

Run the demo end to end once and watch a complete Bed 3 cycle
(NORMAL → LOW → MEDIUM → HIGH → loop, about 90 seconds). If you have not
watched the loop restart, you will think it has frozen when it does.

### ☐ 5. Screenshots are on disk

`docs/demo/screenshots/` — seven files. They are your fallback if the live
stack fails.

---

## 2. Starting and stopping

```
run_demo.bat        # Windows
./run_demo.sh       # macOS / Linux
```

Start order is enforced: gateway → health gate → dashboard → streamer. The
dashboard starts **before** the streamer on purpose, so you can see the
AWAITING FIRST MESSAGE state.

Stop: press a key in the launcher window (Windows) or Ctrl+C (POSIX). Both
terminate every child.

---

## 3. Failure modes actually encountered

### 3.1 A bed card is stale while the others update

**Looked like:** ICU-BED-03 sat at its baseline vitals showing NORMAL while
the gateway was broadcasting HIGH. Beds 1 and 2 updated normally.

**Cause:** the dashboard called `st.rerun()` on a 1-second cadence. A full
render — three bed cards plus Plotly charts — took longer than that, so
Streamlit tore the script down before the **last-rendered** card repainted.

**Diagnosis that found it:** connecting to the WebSocket directly and
comparing the wire against the screen. The socket said `total 7, HR 110`; the
card said `0 / NORMAL`. Trusting the page would have hidden this indefinitely.

**Fixed by:** matching the refresh interval to the data rate (2 s) and
replacing three per-bed Plotly component charts with plain HTML bars.

**If it recurs:** raise `REFRESH_SECONDS` in `demo/dashboard.py`. A card
showing an age stamp is honest; a card silently frozen is not.

### 3.2 Vitals numerals wrapped across three lines

**Looked like:** `121.4 mmHg` rendering as `121.4` / `mm` / `Hg` stacked
vertically — unreadable across a room.

**Fixed by:** moving the unit into the small caption and giving the numeral
`white-space: nowrap`.

### 3.3 Streamlit console flooded with deprecation warnings

**Looked like:** 22,000+ log lines of `use_container_width will be removed`,
which would bury a real error mid-demo.

**Fixed by:** `use_container_width=True` → `width="stretch"`.

### 3.4 `device_vendor=auto` returns HTTP 422

**Looked like:** every HTTP-transport send failing with
`422 Unprocessable Entity`.

**Cause:** `device_vendor` is a `MonitorVendor` enum. There is no `auto`
member — **omitting the parameter** is what triggers MSH-3 auto-detection.

**Fixed by:** not sending the parameter.

### 3.5 `X-NEWS2-Total` always missing

**Looked like:** the streamer logging `NEWS2=(awaiting delta)` on the HTTP
transport even though the gateway returned the header.

**Cause:** uvicorn emits response header names **lower-cased**. Looking up the
documented `X-NEWS2-Total` spelling case-sensitively silently misses.

**Fixed by:** case-insensitive header lookup. Any integrator will hit this.

### 3.6 Test flake under load

`test_mqtt_publisher.py::...::test_failed_item_is_requeued_not_dropped` failed
once while the gateway, streamer, dashboard and browser were all running. It
passed 14/14 isolated and 3/3 full-suite afterwards. Tracked in
`regulatory/findings/FLAKE-MQTT-001.md`; **deliberately not "fixed"** by
loosening the assertion.

If you see it during a rehearsal, re-run. If you see it on an idle machine,
that is new information — read the finding.

---

## 4. Port conflicts

The launchers name the conflicting port and refuse to start. Override:

```bash
GATEWAY_PORT=8010 DASHBOARD_PORT=8511 MLLP_PORT=2585 ./run_demo.sh
```

```bat
set GATEWAY_PORT=8010
set DASHBOARD_PORT=8511
set MLLP_PORT=2585
run_demo.bat
```

Find the offender: `netstat -ano | findstr :8000` then `tasklist /FI "PID eq <pid>"`.

---

## 5. Resetting mid-meeting

**Bed 3 is at the wrong point in its story.** Do not restart anything. The loop
is 90 seconds; say "it cycles — watch it climb again" and use the time for the
FHIR panel.

**Dashboard looks wrong.** Refresh the browser (F5). Session state rebuilds
from the next delta within ~2 seconds. Do not restart the stack.

**Feed shows DISCONNECTED.** Wait. It reconnects with backoff on its own,
un-dims the cards, and returns to LIVE — verified by killing the gateway
mid-run and restarting it. Cards show their true age while stale, so nothing
misleading is on screen.

**Total reset.** Stop the launcher, re-run it. About 15 seconds.

**One-shot scenarios** (run in a second terminal; the streamer keeps running):

```
venv311\Scripts\python scripts\demo_inject.py --scenario low-medium --transport http
venv311\Scripts\python scripts\demo_inject.py --scenario artifact   --transport http
```

Both target ICU-BED-01 and are overwritten by the streamer within ~2 seconds —
have the screen showing that bed before you run them.

---

## 6. Offline operation

The whole stack is local: no internet, no cloud, no external service. Verified
by running with the machine's network in use only for localhost.

- Synthetic data is generated in-process — no fixtures to download.
- Streamlit telemetry is disabled by the launchers
  (`--browser.gatherUsageStats false`).
- The one hard requirement is that both venvs are **already installed**. There
  is no offline package cache; do the install before you travel.

---

## 7. Known limitations — say these before you are asked

- **Terraform is committed but never applied.** No AWS credentials were
  available; `terraform plan` has not been run against a real account.
- **The container image has never been built.** Docker is not installed on the
  development host. `.github/workflows/docker-verify.yml` performs the build
  and every assertion in CI, but it has **not yet executed**. Any image size
  or boot-time figure would be fabricated — there are none in these documents.
- **No real patient data, ever.** Every patient is synthetic and labelled
  `PT-DEMO-*`. The banner is permanent and not dismissible.
- **The dashboard is not part of the medical device.** It lives outside `src/`
  precisely so the container build cannot pick it up, and CI asserts its
  absence from the image.
- **No authentication anywhere.** No authn, no authz, `allow_origins=["*"]`.
  Fine on a laptop; not a deployment posture.
- **No TLS on MLLP.** Plaintext TCP.
- **Per-patient SpO2 scale is not implemented.** MLLP applies one process-wide
  scale. See the roadmap in `COMMERCIAL_ONE_PAGER.md`.
- **REG-CITATION-001 is open.** The FDA CDS citation embedded in emitted
  output appears incorrect and is under review. Do not present it as settled.
- **Clinical-validity evidence has no owner** under the January 2026 CDS
  guidance update. The regulatory tests show RCP 2017 *specification*
  conformance, which is not the same claim.
- **`LOW_MEDIUM` is now verified live** via the `low-medium` scenario
  (screenshot 07) — but no continuous bed produces it naturally, so it only
  appears when you run that scenario.

---

## 8. URLs

| What | Where |
|---|---|
| Dashboard | <http://localhost:8501> |
| Swagger UI | <http://localhost:8000/docs> |
| ReDoc | <http://localhost:8000/redoc> |
| OpenAPI JSON | <http://localhost:8000/openapi.json> |
| Health | <http://localhost:8000/health> |
| WebSocket | `ws://localhost:8000/api/v1/live/vitals` |
| MLLP | `localhost:2575` (TCP) |
