@echo off
title FreePicks Mission Control

cd /d C:\Users\thoma\SportsPredictor

:LOOP
python mission_control.py
echo.
echo [WARN] Mission Control exited. Restarting in 5 seconds...
echo        Press Ctrl+C to cancel.
timeout /t 5 /nobreak
goto LOOP
