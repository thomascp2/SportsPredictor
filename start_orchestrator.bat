@echo off
:: FreePicks Orchestrator - Windows Startup Script
:: Run this to start NBA, NHL, and MLB in continuous mode.
:: Double-click, or add to Windows Task Scheduler for auto-start on login.

title FreePicks Orchestrator

cd /d C:\Users\thoma\SportsPredictor

:: Discord webhooks
SET DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1477417873252159619/***REDACTED_DISCORD_WEBHOOK_1***
SET NHL_DISCORD_WEBHOOK=https://discord.com/api/webhooks/1486934114069250168/***REDACTED_DISCORD_WEBHOOK_4***
SET NBA_DISCORD_WEBHOOK=https://discord.com/api/webhooks/1486934228300992534/***REDACTED_DISCORD_WEBHOOK_3***
SET MLB_DISCORD_WEBHOOK=https://discord.com/api/webhooks/1486934321557274695/***REDACTED_DISCORD_WEBHOOK_2***
:: NHL Hits & Blocks — dedicated channel webhook
SET NHL_HITS_BLOCKS_WEBHOOK=https://discord.com/api/webhooks/1486458242526740501/***REDACTED_DISCORD_WEBHOOK_5***

:: Discord bot token
SET DISCORD_BOT_TOKEN=***REDACTED_DISCORD_BOT_TOKEN***

:: AI API keys
SET XAI_API_KEY=***REDACTED_XAI_KEY***
SET ODDS_API_KEY=***REDACTED_ODDS_API_KEY***
SET ANTHROPIC_API_KEY=***REDACTED_ANTHROPIC_KEY***

echo.
echo =====================================================
echo   FreePicks Orchestrator
echo   Starting NBA + NHL + MLB in continuous mode...
echo   Keep this window open. Close it to stop.
echo =====================================================
echo.

:: Start Discord bot in its own window (inherits env vars set above)
start "FreePicks Discord Bot" start_bot.bat

:: Start dashboard only if not already running (avoids duplicate windows on restart)
tasklist /FI "WINDOWTITLE eq FreePicks Dashboard" 2>NUL | find /I "cmd.exe" >NUL
if errorlevel 1 (
    start "FreePicks Dashboard" start_dashboard.bat
) else (
    echo [INFO] Dashboard already running - skipping...
)

:LOOP
python orchestrator.py --sport all --mode continuous
echo.
echo [WARN] Orchestrator exited (crash or stop). Restarting in 30 seconds...
echo        Press Ctrl+C twice to cancel restart.
timeout /t 30 /nobreak
goto LOOP
