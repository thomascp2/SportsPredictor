@echo off
:: FreePicks Orchestrator - Windows Startup Script
:: Run this to start both NBA + NHL in continuous mode.
:: Double-click, or add to Windows Task Scheduler for auto-start on login.

title FreePicks Orchestrator

cd /d C:\Users\thoma\SportsPredictor

echo.
echo =====================================================
echo   FreePicks Orchestrator
echo   Starting NBA + NHL in continuous mode...
echo   Keep this window open. Close it to stop.
echo =====================================================
echo.

:LOOP
python orchestrator.py --sport all --mode continuous
echo.
echo [WARN] Orchestrator exited (crash or stop). Restarting in 30 seconds...
echo        Press Ctrl+C twice to cancel restart.
timeout /t 30 /nobreak
goto LOOP
