#!/usr/bin/env bash
#
# run_demo.sh — One-command ICU Edge Gateway demonstration stack (POSIX).
#
# TWO ENVIRONMENTS, DELIBERATELY. This is the fragile part of the launcher and
# the most likely way the demo breaks in someone else's hands:
#
#   venv311   gateway + streamer.  websockets==17.0.1 (production pin)
#   venv-demo Streamlit dashboard. websockets<17     (streamlit's constraint)
#
# streamlit declares `websockets<17,>=12.0.0` while requirements.txt pins
# websockets==17.0.1 as a PRODUCTION runtime dependency. The constraints are
# mutually unsatisfiable, so installing Streamlit into venv311 silently
# downgrades websockets and leaves the validated environment no longer
# matching its own pin file. Each child below therefore activates ONLY the
# environment it needs, and VERIFIES its interpreter before doing any work --
# a silently-wrong interpreter is far worse than a loud failure.
#
# Start order is enforced: gateway -> health gate -> dashboard -> streamer.
# The dashboard starts BEFORE the streamer on purpose: that shows the
# AWAITING_FIRST_MESSAGE state, which is a feature to narrate (the live
# channel is push-only and sends no snapshot on connect), not a gap to hide.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

GATEWAY_PORT="${GATEWAY_PORT:-8000}"
DASHBOARD_PORT="${DASHBOARD_PORT:-8501}"
MLLP_PORT="${MLLP_PORT:-2575}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-60}"

VENV_APP="$REPO_ROOT/venv311"
VENV_DEMO="$REPO_ROOT/venv-demo"
PY_APP="$VENV_APP/bin/python"
PY_DEMO="$VENV_DEMO/bin/python"
# Windows layout (Git Bash / MSYS) puts executables in Scripts/.
[[ -x "$PY_APP"  ]] || PY_APP="$VENV_APP/Scripts/python.exe"
[[ -x "$PY_DEMO" ]] || PY_DEMO="$VENV_DEMO/Scripts/python.exe"

PIDS=()

log()  { printf '  %s\n' "$*"; }
fail() { printf '\n  ERROR: %s\n\n' "$*" >&2; exit 1; }

cleanup() {
    printf '\n  Stopping demonstration stack...\n'
    for pid in "${PIDS[@]:-}"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    printf '  Stopped.\n'
}
trap cleanup EXIT INT TERM

# ── Environment verification ────────────────────────────────────────────────

require_interpreter() {
    # $1 = interpreter path, $2 = label ("app" | "demo")
    #
    # The discriminator is the websockets VERSION, not package presence.
    # Presence is not exclusive: venv-demo legitimately contains uvicorn,
    # because streamlit depends on it -- an earlier version of this guard
    # rejected a correctly-built demo environment for exactly that reason.
    # The version boundary IS the conflict (gateway pins websockets==17.0.1,
    # streamlit requires <17), so a merged environment is detected precisely
    # by checking which side of 17 each interpreter landed on.
    local py="$1" label="$2"

    if [[ ! -x "$py" ]]; then
        if [[ "$label" == demo ]]; then
            fail "demo interpreter not found at $py
         python -m venv venv-demo
         venv-demo/Scripts/python -m pip install -r requirements-demo.txt"
        else
            fail "app interpreter not found at $py
         python -m venv venv311
         venv311/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt"
        fi
    fi

    if [[ "$label" == app ]]; then
        "$py" -c "import uvicorn" 2>/dev/null || fail "venv311 is missing 'uvicorn' ($py). Install requirements.txt."
        if "$py" -c "import streamlit" 2>/dev/null; then
            fail "venv311 unexpectedly contains 'streamlit' ($py).
         The environments have been merged. Installing streamlit here
         SILENTLY DOWNGRADES websockets below the production pin.
         Recreate venv311 from requirements.txt."
        fi
        "$py" -c "import sys,websockets; sys.exit(0 if int(websockets.__version__.split('.')[0])>=17 else 1)" 2>/dev/null             || fail "venv311 has websockets < 17 ($py); the production pin is
         websockets==17.0.1. This is exactly what installing streamlit
         here does. Recreate venv311 from requirements.txt."
    else
        "$py" -c "import streamlit" 2>/dev/null || fail "venv-demo is missing 'streamlit' ($py). Install requirements-demo.txt."
        "$py" -c "import sys,websockets; sys.exit(0 if int(websockets.__version__.split('.')[0])<17 else 1)" 2>/dev/null             || fail "venv-demo has websockets >= 17 ($py), which streamlit
         forbids (it requires websockets<17). Recreate venv-demo from
         requirements-demo.txt."
    fi
}

check_port() {
    local port="$1" what="$2"
    if command -v lsof >/dev/null 2>&1; then
        if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
            fail "Port $port ($what) is already in use.
         Free it, or re-run with a different port:
           ${what^^}_PORT=<port> ./run_demo.sh"
        fi
    elif command -v netstat >/dev/null 2>&1; then
        if netstat -an 2>/dev/null | grep -qE "[:.]$port[[:space:]].*LISTEN"; then
            fail "Port $port ($what) is already in use."
        fi
    fi
}

printf '\n  ICU Edge Gateway — demonstration stack\n'
printf '  ======================================\n\n'

log "Verifying environments (two, deliberately)..."
require_interpreter "$PY_APP"  app
require_interpreter "$PY_DEMO" demo
log "  app  : $PY_APP"
log "  demo : $PY_DEMO"

log "Verifying ports..."
check_port "$GATEWAY_PORT"   gateway
check_port "$DASHBOARD_PORT" dashboard
check_port "$MLLP_PORT"      mllp
log "  $GATEWAY_PORT, $DASHBOARD_PORT, $MLLP_PORT all free"

# ── 1. Gateway ──────────────────────────────────────────────────────────────

log "Starting gateway (uvicorn, MLLP enabled)..."
(
    cd "$REPO_ROOT"
    MLLP_ENABLED=1 MLLP_PORT="$MLLP_PORT" PYTHONPATH=src \
        "$PY_APP" -m uvicorn main:app \
            --host 127.0.0.1 --port "$GATEWAY_PORT" --log-level warning
) &
PIDS+=($!)

# ── 2. Health gate — nothing else starts until this passes ──────────────────

log "Waiting for GET /health to report healthy (timeout ${HEALTH_TIMEOUT}s)..."
healthy=0
for _ in $(seq 1 "$HEALTH_TIMEOUT"); do
    if body="$(curl -fsS --max-time 2 "http://127.0.0.1:$GATEWAY_PORT/health" 2>/dev/null)"; then
        if printf '%s' "$body" | grep -q '"status":"healthy"'; then
            healthy=1
            break
        fi
    fi
    sleep 1
done
[[ "$healthy" -eq 1 ]] || fail "Gateway did not become healthy within ${HEALTH_TIMEOUT}s.
         Check the uvicorn output above. Common causes:
           - port $GATEWAY_PORT taken by another process
           - dependencies missing from venv311"
log "  gateway healthy"

# ── 3. Dashboard (BEFORE the streamer — shows AWAITING, which is a feature) ──

log "Starting dashboard (Streamlit, demo environment)..."
(
    cd "$REPO_ROOT/demo"
    "$PY_DEMO" -m streamlit run dashboard.py \
        --server.port "$DASHBOARD_PORT" \
        --server.headless true \
        --browser.gatherUsageStats false \
        >/dev/null 2>&1
) &
PIDS+=($!)
sleep 3

# ── 4. Streamer ─────────────────────────────────────────────────────────────

log "Starting 3-bed synthetic streamer (MLLP)..."
(
    cd "$REPO_ROOT"
    "$PY_APP" scripts/demo_inject.py \
        --continuous --beds 3 --interval 2.0 --seed 42 \
        --transport mllp --gateway-host 127.0.0.1 \
        --mllp-port "$MLLP_PORT" --http-port "$GATEWAY_PORT" \
        >/dev/null 2>&1
) &
PIDS+=($!)

# ── 5. Browser + summary ────────────────────────────────────────────────────

DASH_URL="http://127.0.0.1:$DASHBOARD_PORT"
if   command -v xdg-open >/dev/null 2>&1; then xdg-open "$DASH_URL" >/dev/null 2>&1 || true
elif command -v open     >/dev/null 2>&1; then open     "$DASH_URL" >/dev/null 2>&1 || true
fi

cat <<BOX

  +------------------------------------------------------------------------+
  |  ICU EDGE GATEWAY - DEMONSTRATION STACK RUNNING                        |
  |                                                                        |
  |  SYNTHETIC DEMONSTRATION DATA - NOT REAL PATIENT DATA                  |
  |  Clinical decision support, advisory only. Independent clinician       |
  |  review required before any action.                                    |
  +------------------------------------------------------------------------+
  |  Dashboard    http://127.0.0.1:$DASHBOARD_PORT
  |  Swagger UI   http://127.0.0.1:$GATEWAY_PORT/docs
  |  ReDoc        http://127.0.0.1:$GATEWAY_PORT/redoc
  |  OpenAPI      http://127.0.0.1:$GATEWAY_PORT/openapi.json
  |  Health       http://127.0.0.1:$GATEWAY_PORT/health
  |  WebSocket    ws://127.0.0.1:$GATEWAY_PORT/api/v1/live/vitals
  |  MLLP (TCP)   127.0.0.1:$MLLP_PORT
  +------------------------------------------------------------------------+
  |  TWO ENVIRONMENTS ARE IN USE - this is intentional:                    |
  |    gateway + streamer : venv311    (websockets==17.0.1, production pin)|
  |    dashboard          : venv-demo  (streamlit needs websockets<17)     |
  |  They are mutually incompatible. Do not merge them.                    |
  +------------------------------------------------------------------------+
  |  One-shot scenarios (run in another shell, streamer keeps running):    |
  |    venv311/bin/python scripts/demo_inject.py --scenario low-medium \\
  |        --transport http                                                |
  |    venv311/bin/python scripts/demo_inject.py --scenario artifact \\
  |        --transport http                                                |
  +------------------------------------------------------------------------+

  The dashboard was started BEFORE the streamer so you can see the
  AWAITING FIRST MESSAGE state. The live channel is push-only and sends no
  snapshot on connect by design; beds appear within a few seconds.

  Press Ctrl+C to stop the demonstration stack.

BOX

wait
