@echo off
title FreePicks Dashboard

cd /d C:\Users\thoma\SportsPredictor

SET SUPABASE_URL=https://***REMOVED***
SET SUPABASE_SERVICE_ROLE_KEY=***REMOVED***

:: ── Permanent URL config ──────────────────────────────────────────────────
:: Option A (active): ngrok static domain — never changes, bookmark this!
::   Setup: ngrok.com → free account → Domains → claim one free static domain
::   Then: ngrok config add-authtoken YOUR_TOKEN
SET NGROK_DOMAIN=benita-wedgelike-healingly.ngrok-free.dev

:: Option B (fallback): Cloudflare quick tunnel — random URL every restart
::   Uncomment the cloudflared line in TUNNEL_LOOP and comment out ngrok if preferred

echo.
echo =====================================================
echo   FreePicks Cloud Dashboard
echo   Local:     http://localhost:8502
echo   Permanent: https://%NGROK_DOMAIN%
echo =====================================================
echo.

:: Start Streamlit on port 8502 in background
start "FreePicks Streamlit" cmd /c "streamlit run dashboards/cloud_dashboard.py --server.port 8502 --server.headless true"

:: Wait for Streamlit to fully start
timeout /t 6 /nobreak >nul

echo [INFO] Starting ngrok tunnel (permanent URL)...
echo [INFO] Permanent URL (bookmark this): https://%NGROK_DOMAIN%
echo.

:TUNNEL_LOOP
"%LOCALAPPDATA%\Microsoft\WindowsApps\ngrok.exe" http 8502 --domain=%NGROK_DOMAIN%
echo.
echo [WARN] Tunnel dropped. Restarting in 10 seconds...
timeout /t 10 /nobreak
goto TUNNEL_LOOP
