#!/usr/bin/env bash
#
# scripts/demo_run.sh — End-to-end technical demo, built entirely on the
# EXISTING docker-compose.yml stack (mock control plane + gateway +
# hl7-monitor-simulator). No mocked/hardcoded output: every value printed
# below comes from a real running container, over a real MLLP socket, a
# real WebSocket, and real structlog output.
#
# What it does, in order:
#   0. `docker compose up -d` the existing stack; wait for GET /health.
#   1. Inject ONE HL7 v2.x ORU^R01 message over the gateway's real MLLP
#      listener (port 2575) — deliberately containing an out-of-range
#      Heart Rate artifact (450 bpm) alongside a corrected valid reading.
#      See scripts/demo_inject.py's module docstring for the exact clinical
#      rationale.
#   2. Show the real gateway container log lines for that one message
#      (structlog output from vitals_orchestrator.py / mllp_listener.py —
#      DSP rejection is visible via warning_count > 0).
#   3. Show the resulting NEWS2 score (from the live WebSocket delta).
#   4. Show the resulting FHIR R4 Bundle (same delta).
#   5. Show the full live-dashboard delta envelope, proving the WS channel
#      delivered it in real time (no polling).
#
# See README.md § "Technical Demo" for what a viewer is watching at each
# step and why it matters.
#
# Requirements: Docker (with Compose v2), curl, and a Python interpreter
# with the `websockets` package installed (requirements-dev.txt).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

GATEWAY_HTTP_PORT="${GATEWAY_HTTP_PORT:-8000}"
GATEWAY_MLLP_PORT="${GATEWAY_MLLP_PORT:-2575}"
HEALTH_URL="http://localhost:${GATEWAY_HTTP_PORT}/health"
STARTUP_TIMEOUT_S="${STARTUP_TIMEOUT_S:-90}"
PATIENT_ID="PT-DEMO-$(date +%s)"

# ── Preflight ────────────────────────────────────────────────────────────

if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
else
    echo "ERROR: 'docker compose' (or 'docker-compose') not found on PATH." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon is not reachable. Start Docker Desktop (or the" >&2
    echo "Docker service) and re-run this script." >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "ERROR: curl is required (used for the /health readiness check)." >&2
    exit 1
fi

# ── Interpreter selection ────────────────────────────────────────────────
#
# DEFECT FIX (recorded in PUSH_READINESS.md): this block previously PROBED
# for a bare `$REPO_ROOT/venv`, then fell back to whatever `python3` or
# `python` happened to be on PATH. All of those are git-ignored and
# unpinned, so the demo could -- and on the development machine
# demonstrably did -- run against an interpreter that is not the CI-pinned
# one: a 3.13.1 `venv/` had already drifted to uvicorn 0.52.1 against
# venv311's 0.52.3. That is the HAZARD-STREAM-013 silent-pin-drift class.
# There is now no probe and no fallback -- the interpreter is venv311 by
# absolute path, or this script fails loudly.
#
# NOTE on venv-demo: this is the DOCKER demo. The gateway runs in a
# container; the only local interpreter need is the MLLP injector client.
# This script never launches Streamlit, so it does not require venv-demo,
# and hard-failing on its absence would block a working demo for no safety
# gain. venv-demo is therefore verified only if it EXISTS -- which still
# catches drift, without inventing a dependency this script does not have.
# The launcher that does start the dashboard, run_demo.bat, gates it hard.

if [[ -x "$REPO_ROOT/venv311/Scripts/python.exe" ]]; then
    PYTHON_BIN="$REPO_ROOT/venv311/Scripts/python.exe"
elif [[ -x "$REPO_ROOT/venv311/bin/python" ]]; then
    PYTHON_BIN="$REPO_ROOT/venv311/bin/python"
else
    echo "ERROR: venv311 not found at $REPO_ROOT/venv311." >&2
    echo "       This script requires the CI-pinned interpreter and will NOT" >&2
    echo "       fall back to any other Python. Create it with:" >&2
    echo "         python -m venv venv311" >&2
    echo "         venv311/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt" >&2
    exit 1
fi

# ── venv311 pin assertions (parity with run_demo.bat) ────────────────────

if ! "$PYTHON_BIN" -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,11) else 1)" >/dev/null 2>&1; then
    echo "ERROR: venv311 is not Python 3.11.x (found: $("$PYTHON_BIN" --version 2>&1))." >&2
    echo "       CI pins 3.11 (.github/workflows/ci.yml PYTHON_VERSION). A run on" >&2
    echo "       any other interpreter resolves a different dependency graph and" >&2
    echo "       is not comparable to the 816 passed / 1 xfailed baseline." >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c "import websockets" >/dev/null 2>&1; then
    echo "ERROR: venv311 is missing 'websockets'." >&2
    echo "       Install: $PYTHON_BIN -m pip install -r requirements.txt -r requirements-dev.txt" >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c "import sys,websockets; sys.exit(0 if int(websockets.__version__.split('.')[0])>=17 else 1)" >/dev/null 2>&1; then
    echo "ERROR: venv311 has websockets < 17. The production pin is websockets==17.0.1." >&2
    echo "       Installing streamlit into venv311 does exactly this. Recreate it" >&2
    echo "       from requirements.txt." >&2
    exit 1
fi

if "$PYTHON_BIN" -c "import streamlit" >/dev/null 2>&1; then
    echo "ERROR: venv311 unexpectedly contains 'streamlit'." >&2
    echo "       The two environments have been cross-contaminated. streamlit" >&2
    echo "       requires websockets<17; the gateway pins websockets==17.0.1." >&2
    echo "       See requirements-demo.txt." >&2
    exit 1
fi

# ── venv-demo: not used here; verified only if present (see NOTE above) ──

DEMO_PY=""
if [[ -x "$REPO_ROOT/venv-demo/Scripts/python.exe" ]]; then
    DEMO_PY="$REPO_ROOT/venv-demo/Scripts/python.exe"
elif [[ -x "$REPO_ROOT/venv-demo/bin/python" ]]; then
    DEMO_PY="$REPO_ROOT/venv-demo/bin/python"
fi

if [[ -n "$DEMO_PY" ]]; then
    if ! "$DEMO_PY" -c "import streamlit" >/dev/null 2>&1; then
        echo "ERROR: venv-demo exists but is missing 'streamlit'." >&2
        echo "       Recreate it from requirements-demo.txt." >&2
        exit 1
    fi
    if ! "$DEMO_PY" -c "import sys,websockets; sys.exit(0 if int(websockets.__version__.split('.')[0])<17 else 1)" >/dev/null 2>&1; then
        echo "ERROR: venv-demo does not satisfy websockets<17, which streamlit" >&2
        echo "       requires. Recreate it from requirements-demo.txt." >&2
        exit 1
    fi
fi

echo "Interpreter: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

LOG_CAPTURE_FILE="$(mktemp)"
LOG_PID=""

cleanup() {
    if [[ -n "$LOG_PID" ]] && kill -0 "$LOG_PID" 2>/dev/null; then
        kill "$LOG_PID" 2>/dev/null || true
        wait "$LOG_PID" 2>/dev/null || true
    fi
    rm -f "$LOG_CAPTURE_FILE"
}
trap cleanup EXIT

section() { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

DEMO_START_EPOCH=$(date +%s)

# ── Step 0: bring up the existing compose stack ────────────────────────────

section "STEP 0 — docker compose up -d (mock control plane → CA fetch → gateway → HL7 simulator)"
"${COMPOSE_CMD[@]}" up -d

echo "Waiting for gateway ${HEALTH_URL} ..."
STACK_WAIT_START=$(date +%s)
until curl -sf "$HEALTH_URL" >/dev/null 2>&1; do
    if (( $(date +%s) - STACK_WAIT_START > STARTUP_TIMEOUT_S )); then
        echo "ERROR: gateway did not become healthy within ${STARTUP_TIMEOUT_S}s." >&2
        echo "Check: ${COMPOSE_CMD[*]} logs gateway" >&2
        exit 1
    fi
    sleep 1
done
STACK_READY_ELAPSED=$(( $(date +%s) - STACK_WAIT_START ))
echo "Gateway healthy after ${STACK_READY_ELAPSED}s."

# ── Core demo (this is the part the <2 minute target measures) ─────────────

DEMO_CORE_START=$(date +%s)

section "STEP 1 — Injecting one HL7v2 ORU^R01 message over real MLLP (port ${GATEWAY_MLLP_PORT})"
echo "Deliberate artifact: Heart Rate OBX = 450 bpm (outside the [20, 250] physiological"
echo "bound enforced by domain/services/artifact_rejector.py), immediately followed in the"
echo "same message by a corrected 82 bpm reading one second later. Patient ID: ${PATIENT_ID}"

# Follow the gateway's real stdout from *now*, filtered by this run's unique
# patient_id later — this is genuine container log output, not synthesized.
"${COMPOSE_CMD[@]}" logs -f --no-color --since 1s gateway >"$LOG_CAPTURE_FILE" 2>&1 &
LOG_PID=$!
sleep 1  # let log-follow attach before anything worth capturing happens

set +e
DELTA_JSON="$("$PYTHON_BIN" "$SCRIPT_DIR/demo_inject.py" \
    --patient-id "$PATIENT_ID" \
    --gateway-host localhost \
    --mllp-port "$GATEWAY_MLLP_PORT" \
    --http-port "$GATEWAY_HTTP_PORT")"
INJECT_STATUS=$?
set -e

# Let the last log lines actually flush through `docker compose logs` before
# we stop following and read the capture file back.
sleep 2
if [[ -n "$LOG_PID" ]] && kill -0 "$LOG_PID" 2>/dev/null; then
    kill "$LOG_PID" 2>/dev/null || true
    wait "$LOG_PID" 2>/dev/null || true
fi
LOG_PID=""

if [[ "$INJECT_STATUS" -ne 0 ]]; then
    echo "ERROR: injection failed. Captured gateway log:" >&2
    cat "$LOG_CAPTURE_FILE" >&2
    exit 1
fi

section "STEP 2 — Real gateway log output for this message (DSP rejection + NEWS2)"
echo "(structlog lines from vitals_orchestrator.py and mllp_listener.py, filtered to"
echo "this run's patient_id so the simulator sidecar's own background traffic doesn't"
echo "clutter the view — full unfiltered log: ${COMPOSE_CMD[*]} logs gateway)"
echo
grep "$PATIENT_ID" "$LOG_CAPTURE_FILE" || echo "(no matching log lines captured yet — re-run '${COMPOSE_CMD[*]} logs gateway')"

section "STEP 3 — Resulting NEWS2 score (from the live WebSocket delta)"
echo "$DELTA_JSON" | "$PYTHON_BIN" -c "
import json, sys
d = json.load(sys.stdin)
print(json.dumps(d['news2'], indent=2))
"

section "STEP 4 — Resulting FHIR R4 Bundle (same delta)"
echo "$DELTA_JSON" | "$PYTHON_BIN" -c "
import json, sys
d = json.load(sys.stdin)
print(json.dumps(d['bundle'], indent=2))
"

section "STEP 5 — Full live-dashboard delta envelope (WS /api/v1/live/vitals, real-time — no polling)"
echo "$DELTA_JSON" | "$PYTHON_BIN" -c "
import json, sys
d = json.load(sys.stdin)
d = dict(d)
d['bundle'] = '<see Step 4 — omitted here to avoid printing it twice>'
print(json.dumps(d, indent=2))
"

DEMO_CORE_ELAPSED=$(( $(date +%s) - DEMO_CORE_START ))
DEMO_TOTAL_ELAPSED=$(( $(date +%s) - DEMO_START_EPOCH ))

section "Done"
echo "Core demo (inject → log → NEWS2 → FHIR → WS delta): ${DEMO_CORE_ELAPSED}s"
echo "End-to-end including compose startup / health wait:  ${DEMO_TOTAL_ELAPSED}s"
echo "Stack left running for further exploration — '${COMPOSE_CMD[*]} down' to stop it."
