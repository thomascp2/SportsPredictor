@echo off
title FreePicks Parlay Builder

cd /d C:\Users\thoma\SportsPredictor

:: ─── Environment vars (copy from start_orchestrator.bat) ───────────────────
SET SUPABASE_URL=https://txleohtoesmanorqcurt.supabase.co
SET SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR4bGVvaHRvZXNtYW5vcnFjdXJ0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzEwODQxMDMsImV4cCI6MjA4NjY2MDEwM30.33GFL5ZFM8X9W5_wVW7xNzzHZ32x42qlQMPfqFA9nUQ
SET ODDS_API_KEY=c02e47a4bcf4c5edb0211c129595b0bb
:: SET ANTHROPIC_API_KEY=sk-ant-...   <- uncomment and add key if self-healing needed

echo.
echo =====================================================
echo   FreePicks Parlay Builder UI
echo.
echo   API:    http://localhost:8000
echo   Docs:   http://localhost:8000/docs
echo   Expo:   Scan QR code in the mobile window
echo =====================================================
echo.

:: ─── 1. FastAPI backend ────────────────────────────────────────────────────
echo [1/2] Starting FastAPI backend on port 8000...
start "FreePicks API" cmd /k "cd /d C:\Users\thoma\SportsPredictor && python -m uvicorn api.main:app --reload --port 8000 --host 0.0.0.0"

:: Wait for FastAPI to be ready before launching Expo
echo [INFO] Waiting for API to come up...
timeout /t 5 /nobreak >nul

:: ─── 2. Expo mobile app ────────────────────────────────────────────────────
echo [2/2] Starting Expo dev server (scan QR code with Expo Go)...
start "FreePicks Expo" cmd /k "cd /d C:\Users\thoma\SportsPredictor\mobile && npx expo start"

echo.
echo =====================================================
echo   Both services are starting in separate windows.
echo.
echo   API ready at:  http://localhost:8000/docs
echo   Mobile:        Scan the QR code in the Expo window
echo                  with the Expo Go app on your phone.
echo.
echo   To stop: close the API and Expo windows.
echo =====================================================
echo.
pause
