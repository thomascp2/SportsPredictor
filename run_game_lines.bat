@echo off
:: MLB Game Lines — Daily Runner
:: Task Scheduler points here instead of calling Python directly.
:: Captures output to a dated log file for debugging.

cd /d C:\Users\thoma\SportsPredictor\mlb\scripts

SET ODDS_API_KEY=9689a1d90aa336e596623e5efe9870f3
SET MLB_DISCORD_WEBHOOK=https://discord.com/api/webhooks/1491584147154800792/kU-nmAKpQAAT-9KRyPidY61OHX5-P5JcT6A98_glW3Bkg53h2MXnurbTOipb56hKhUTK

SET LOGFILE=C:\Users\thoma\SportsPredictor\logs\game_lines_%DATE:~-4,4%%DATE:~-10,2%%DATE:~-7,2%.log

C:\Users\thoma\AppData\Local\Programs\Python\Python313\python.exe generate_game_predictions.py >> "%LOGFILE%" 2>&1

echo [%DATE% %TIME%] game_lines run complete >> "%LOGFILE%"
