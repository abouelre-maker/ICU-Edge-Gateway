@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

REM ============================================================================
REM  run_demo.bat - One-command ICU Edge Gateway demonstration stack (Windows)
REM
REM  TWO ENVIRONMENTS, DELIBERATELY. This is the fragile part of the launcher
REM  and the most likely way the demo breaks in someone else's hands:
REM
REM    venv311    gateway + streamer.  websockets==17.0.1 (production pin)
REM    venv-demo  Streamlit dashboard. websockets<17     (streamlit constraint)
REM
REM  streamlit declares `websockets<17,>=12.0.0` while requirements.txt pins
REM  websockets==17.0.1 as a PRODUCTION runtime dependency. The constraints are
REM  mutually unsatisfiable, so installing Streamlit into venv311 silently
REM  downgrades websockets and leaves the validated environment no longer
REM  matching its own pin file. Each child window below uses ONLY the
REM  interpreter it needs, by absolute path - no venv is ever "activated" into
REM  a shared shell, so neither can shadow the other. Both are verified before
REM  anything starts: a silently-wrong interpreter is worse than a loud failure.
REM
REM  Start order is enforced: gateway -> health gate -> dashboard -> streamer.
REM  The dashboard starts BEFORE the streamer on purpose - that shows the
REM  AWAITING FIRST MESSAGE state, which is a feature to narrate (the live
REM  channel is push-only and sends no snapshot on connect), not a gap to hide.
REM ============================================================================

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
cd /d "%REPO_ROOT%"

if not defined GATEWAY_PORT   set "GATEWAY_PORT=8000"
if not defined DASHBOARD_PORT set "DASHBOARD_PORT=8501"
if not defined MLLP_PORT      set "MLLP_PORT=2575"
if not defined HEALTH_TIMEOUT set "HEALTH_TIMEOUT=60"
if not defined DASHBOARD_TIMEOUT set "DASHBOARD_TIMEOUT=90"

set "PY_APP=%REPO_ROOT%\venv311\Scripts\python.exe"
set "PY_DEMO=%REPO_ROOT%\venv-demo\Scripts\python.exe"

echo.
echo   ICU Edge Gateway - demonstration stack
echo   ======================================
echo.

REM ---------------------------------------------------------------- environments
echo   Verifying environments ^(two, deliberately^)...

if not exist "%PY_APP%" (
    echo.
    echo   ERROR: application interpreter not found:
    echo            %PY_APP%
    echo          Create it first:
    echo            python -m venv venv311
    echo            venv311\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
    echo.
    goto :fail
)
if not exist "%PY_DEMO%" (
    echo.
    echo   ERROR: demo interpreter not found:
    echo            %PY_DEMO%
    echo          Create it first:
    echo            python -m venv venv-demo
    echo            venv-demo\Scripts\python -m pip install -r requirements-demo.txt
    echo.
    goto :fail
)

REM Each interpreter must have what it needs, and must sit on the correct
REM side of the websockets==17 boundary. See the NOTE below on why package
REM presence alone is NOT a valid discriminator here.
"%PY_APP%" -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo   ERROR: venv311 is missing 'uvicorn'. Install requirements.txt.
    goto :fail
)
"%PY_APP%" -c "import streamlit" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo   ERROR: venv311 unexpectedly contains 'streamlit'.
    echo          The two environments have been cross-contaminated.
    echo          streamlit requires websockets^<17; the gateway pins
    echo          websockets==17.0.1. See requirements-demo.txt.
    echo.
    goto :fail
)
"%PY_APP%" -c "import sys,websockets; sys.exit(0 if int(websockets.__version__.split('.')[0])>=17 else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ERROR: venv311 has websockets ^< 17. The production pin is
    echo          websockets==17.0.1. This is exactly what installing
    echo          streamlit into venv311 does. Recreate it from
    echo          requirements.txt.
    echo.
    goto :fail
)

"%PY_DEMO%" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo   ERROR: venv-demo is missing 'streamlit'. Install requirements-demo.txt.
    goto :fail
)
REM NOTE: do NOT assert that venv-demo lacks uvicorn -- streamlit DEPENDS on
REM uvicorn, so a correctly-built demo environment contains it. Package
REM presence is not an exclusive discriminator between these two
REM environments; the websockets VERSION is, because that is the actual
REM conflict. An earlier version of this guard rejected a correct
REM environment for precisely that reason.
"%PY_DEMO%" -c "import sys,websockets; sys.exit(0 if int(websockets.__version__.split('.')[0])<17 else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ERROR: venv-demo has websockets ^>= 17, which streamlit forbids
    echo          ^(it requires websockets^<17^). Recreate venv-demo from
    echo          requirements-demo.txt.
    echo.
    goto :fail
)
echo     app  : %PY_APP%
echo     demo : %PY_DEMO%

REM ----------------------------------------------------------------------- ports
echo   Verifying ports...
call :checkport %GATEWAY_PORT%   gateway   || goto :fail
call :checkport %DASHBOARD_PORT% dashboard || goto :fail
call :checkport %MLLP_PORT%      mllp      || goto :fail
echo     %GATEWAY_PORT%, %DASHBOARD_PORT%, %MLLP_PORT% all free

REM ------------------------------------------------------------------- 1. gateway
echo   Starting gateway ^(uvicorn, MLLP enabled^)...
start "ICU Gateway" cmd /k "cd /d "%REPO_ROOT%" && set MLLP_ENABLED=1&& set MLLP_PORT=%MLLP_PORT%&& set PYTHONPATH=src&& "%PY_APP%" -m uvicorn main:app --host 127.0.0.1 --port %GATEWAY_PORT%"

REM --------------------------------------------------- 2. health gate (blocking)
echo   Waiting for GET /health to report healthy ^(timeout %HEALTH_TIMEOUT%s^)...
set "HEALTHY=0"
for /l %%i in (1,1,%HEALTH_TIMEOUT%) do (
    if "!HEALTHY!"=="0" (
        "%PY_APP%" -c "import sys,json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:%GATEWAY_PORT%/health',timeout=2)); sys.exit(0 if d.get('status')=='healthy' else 1)" >nul 2>&1
        if not errorlevel 1 set "HEALTHY=1"
        if "!HEALTHY!"=="0" ping -n 2 127.0.0.1 >nul
    )
)
if "!HEALTHY!"=="0" (
    echo.
    echo   ERROR: gateway did not become healthy within %HEALTH_TIMEOUT%s.
    echo          Check the "ICU Gateway" window. Common causes:
    echo            - port %GATEWAY_PORT% taken by another process
    echo            - dependencies missing from venv311
    echo.
    goto :fail
)
echo     gateway healthy

REM ------------------------- 3. dashboard BEFORE streamer (shows AWAITING state)
echo   Starting dashboard ^(Streamlit, demo environment^)...
start "Clinical Dashboard" cmd /k "cd /d "%REPO_ROOT%\demo" && "%PY_DEMO%" -m streamlit run dashboard.py --server.port %DASHBOARD_PORT% --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false"

REM ------------------- 3b. dashboard readiness gate (blocking, replaces fixed delay)
echo   Waiting for dashboard to accept connections ^(timeout %DASHBOARD_TIMEOUT%s^)...
set "DASH_UP=0"
for /l %%i in (1,1,%DASHBOARD_TIMEOUT%) do (
    if "!DASH_UP!"=="0" (
        "%PY_DEMO%" -c "import socket; s=socket.create_connection(('127.0.0.1',%DASHBOARD_PORT%),1); s.close()" >nul 2>&1
        if not errorlevel 1 set "DASH_UP=1"
        if "!DASH_UP!"=="0" ping -n 2 127.0.0.1 >nul
    )
)
if "!DASH_UP!"=="0" (
    echo.
    echo   ERROR: dashboard never listened on port %DASHBOARD_PORT% within %DASHBOARD_TIMEOUT%s.
    echo          Check the "Clinical Dashboard" window. Common causes:
    echo            - Windows Defender Firewall blocked the bind on first run
    echo            - streamlit missing from venv-demo
    echo            - port %DASHBOARD_PORT% taken after the pre-flight check
    echo.
    goto :fail
)
echo     dashboard listening

REM ------------------------------------------------------------------ 4. streamer
echo   Starting 3-bed synthetic streamer ^(MLLP^)...
start "Patient Streamer" cmd /k "cd /d "%REPO_ROOT%" && "%PY_APP%" scripts\demo_inject.py --continuous --beds 3 --interval 2.0 --seed 42 --transport mllp --gateway-host 127.0.0.1 --mllp-port %MLLP_PORT% --http-port %GATEWAY_PORT%"

REM --------------------------------------------------------- 5. browser + summary
start "" "http://127.0.0.1:%DASHBOARD_PORT%"

echo.
echo   +------------------------------------------------------------------------+
echo   ^|  ICU EDGE GATEWAY - DEMONSTRATION STACK RUNNING                        ^|
echo   ^|                                                                        ^|
echo   ^|  SYNTHETIC DEMONSTRATION DATA - NOT REAL PATIENT DATA                  ^|
echo   ^|  Clinical decision support, advisory only. Independent clinician       ^|
echo   ^|  review required before any action.                                    ^|
echo   +------------------------------------------------------------------------+
echo     Dashboard    http://127.0.0.1:%DASHBOARD_PORT%
echo     Swagger UI   http://127.0.0.1:%GATEWAY_PORT%/docs
echo     ReDoc        http://127.0.0.1:%GATEWAY_PORT%/redoc
echo     OpenAPI      http://127.0.0.1:%GATEWAY_PORT%/openapi.json
echo     Health       http://127.0.0.1:%GATEWAY_PORT%/health
echo     WebSocket    ws://127.0.0.1:%GATEWAY_PORT%/api/v1/live/vitals
echo     MLLP ^(TCP^)   127.0.0.1:%MLLP_PORT%
echo   +------------------------------------------------------------------------+
echo     TWO ENVIRONMENTS ARE IN USE - this is intentional:
echo       gateway + streamer : venv311    ^(websockets==17.0.1, production pin^)
echo       dashboard          : venv-demo  ^(streamlit needs websockets^<17^)
echo     They are mutually incompatible. Do not merge them.
echo   +------------------------------------------------------------------------+
echo     One-shot scenarios ^(run in another shell; streamer keeps running^):
echo       venv311\Scripts\python scripts\demo_inject.py --scenario low-medium --transport http
echo       venv311\Scripts\python scripts\demo_inject.py --scenario artifact    --transport http
echo   +------------------------------------------------------------------------+
echo.
echo   The dashboard was started BEFORE the streamer so you can see the
echo   AWAITING FIRST MESSAGE state. The live channel is push-only and sends
echo   no snapshot on connect by design; beds appear within a few seconds.
echo.
echo   Press any key in THIS window to STOP the demonstration stack.
pause >nul

echo.
echo   Stopping demonstration stack...
taskkill /FI "WINDOWTITLE eq ICU Gateway*"        /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Clinical Dashboard*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Patient Streamer*"   /T /F >nul 2>&1
echo   Stopped.
endlocal
exit /b 0

REM ------------------------------------------------------------------ subroutines
:checkport
REM  Reports the PID holding a port. With RECLAIM_PORTS=1, reclaims it first.
set "PORTPID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"LISTENING" ^| findstr /c:":%~1 "') do set "PORTPID=%%p"
if not defined PORTPID exit /b 0
if "%RECLAIM_PORTS%"=="1" (
    echo     port %~1 ^(%~2^) held by PID !PORTPID! - reclaiming ^(RECLAIM_PORTS=1^)
    taskkill /f /pid !PORTPID! >nul 2>&1
    ping -n 3 127.0.0.1 >nul
    set "PORTPID="
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"LISTENING" ^| findstr /c:":%~1 "') do set "PORTPID=%%p"
    if not defined PORTPID exit /b 0
)
echo.
echo   ERROR: port %~1 ^(%~2^) is already in use by PID !PORTPID!.
echo          Free that one process:   taskkill /f /pid !PORTPID!
echo          Or free all demo ports:  stop_demo.bat
echo          Or reclaim automatically: set RECLAIM_PORTS=1 ^&^& run_demo.bat
echo.
exit /b 1

:fail
echo   Demonstration stack did NOT start.
endlocal
exit /b 1
