@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------------------
REM  stop_demo.bat - clean teardown of the ICU Edge Gateway demonstration stack.
REM  Frees the three demo ports so run_demo.bat can start cleanly. Safe to run
REM  repeatedly. Only touches processes LISTENING on the demo ports.
REM ---------------------------------------------------------------------------

if not defined GATEWAY_PORT   set "GATEWAY_PORT=8000"
if not defined DASHBOARD_PORT set "DASHBOARD_PORT=8501"
if not defined MLLP_PORT      set "MLLP_PORT=2575"

echo.
echo   ICU Edge Gateway - stopping demonstration stack
echo   ===============================================
echo.

call :freeport %GATEWAY_PORT%   gateway
call :freeport %DASHBOARD_PORT% dashboard
call :freeport %MLLP_PORT%      mllp

echo.
echo   Done. All three demo ports are free.
echo   You can now run:  run_demo.bat
echo.
endlocal
exit /b 0

:freeport
set "PORTPID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"LISTENING" ^| findstr /c:":%~1 "') do set "PORTPID=%%p"
if not defined PORTPID (
    echo     port %~1 ^(%~2^) already free
    exit /b 0
)
echo     port %~1 ^(%~2^) held by PID !PORTPID! - stopping
taskkill /f /pid !PORTPID! >nul 2>&1
if errorlevel 1 (
    echo       WARNING: could not stop PID !PORTPID!. Try an elevated prompt.
    exit /b 0
)
exit /b 0
