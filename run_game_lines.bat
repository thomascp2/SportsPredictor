@echo off
:: MLB Game Lines — Daily Runner
:: Task Scheduler points here instead of calling Python directly.
:: Captures output to a dated log file for debugging.

cd /d C:\Users\thoma\SportsPredictor
call env.bat
cd mlb\scripts

SET LOGFILE=C:\Users\thoma\SportsPredictor\logs\game_lines_%DATE:~-4,4%%DATE:~-10,2%%DATE:~-7,2%.log

C:\Users\thoma\AppData\Local\Programs\Python\Python313\python.exe generate_game_predictions.py >> "%LOGFILE%" 2>&1

echo [%DATE% %TIME%] game_lines run complete >> "%LOGFILE%"
