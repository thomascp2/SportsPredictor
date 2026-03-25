@echo off
:: FreePicks Orchestrator - Windows Startup Script
:: Run this to start NBA, NHL, and MLB in continuous mode.
:: Double-click, or add to Windows Task Scheduler for auto-start on login.

title FreePicks Orchestrator

cd /d C:\Users\thoma\SportsPredictor

:: Discord webhooks
SET DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1477417873252159619/RXcF9y2d2hqGAzpjkLjlcsZZT_8_xFEv71sIKUOeL8KyoqrAFmOPwnT8wLeCiKmkv96h
SET NHL_DISCORD_WEBHOOK=https://discord.com/api/webhooks/1477417873252159619/RXcF9y2d2hqGAzpjkLjlcsZZT_8_xFEv71sIKUOeL8KyoqrAFmOPwnT8wLeCiKmkv96h
SET NBA_DISCORD_WEBHOOK=https://discord.com/api/webhooks/1477417873252159619/RXcF9y2d2hqGAzpjkLjlcsZZT_8_xFEv71sIKUOeL8KyoqrAFmOPwnT8wLeCiKmkv96h
SET MLB_DISCORD_WEBHOOK=https://discord.com/api/webhooks/1477417873252159619/RXcF9y2d2hqGAzpjkLjlcsZZT_8_xFEv71sIKUOeL8KyoqrAFmOPwnT8wLeCiKmkv96h
:: NHL Hits & Blocks — dedicated channel webhook
SET NHL_HITS_BLOCKS_WEBHOOK=https://discord.com/api/webhooks/1486458242526740501/zMAu9G7M5ADTyaZpOYc_ZeMAieXkD6EhPf0L2NuasJdymqKatD9u9NWJCtrAWwFcruiJ

:: Discord bot token
SET DISCORD_BOT_TOKEN=MTQ3NzQxOTg4OTY2Nzg2NjcyNw.Go4-N9.Evkr19VpztQb69etFOPwjrIY5MjXHtQsQ9SCSo

:: AI API keys
SET XAI_API_KEY=xai-ATIDuNLiU7ETx2djYH0Q1Va88ux6nBH6IjkG7dvPMZRRqQzs6LTL9B99hmZCdPKydtys0K4SzQ0LJ1F6
SET ODDS_API_KEY=c02e47a4bcf4c5edb0211c129595b0bb
:: SET ANTHROPIC_API_KEY=sk-ant-...   <- add your key here when ready

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
