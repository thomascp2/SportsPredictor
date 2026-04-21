@echo off
:: fetch_and_push_pp.bat
:: Fetches PrizePicks lines locally (residential IP) and pushes to VPS
:: Runs passwordless via SSH key ~/.ssh/vps_key
::
:: Schedule via Windows Task Scheduler at these times (CST):
::   2:00 AM  - before Golf initial fetch (2:15 AM)
::   3:15 AM  - before NHL initial fetch (3:30 AM)
::   5:15 AM  - before NBA initial fetch (5:30 AM)
::   8:15 AM  - before MLB initial fetch (8:30 AM)
::   9:00 AM  - before all mid-morning syncs (9:15/10:15/10:45 AM)
::   12:00 PM - before afternoon syncs (12:30 NBA, 1:00 NHL)
::   2:45 PM  - before MLB afternoon sync (3:00 PM)

set REPO=C:\Users\thoma\SportsPredictor
set VPS_IP=159.203.93.232
set VPS_PATH=/opt/SportsPredictor/shared/prizepicks_lines.db
set LOCAL_DB=%REPO%\shared\prizepicks_lines.db
set PYTHON=C:\Users\thoma\AppData\Local\Programs\Python\Python313\python.exe
set SSH_KEY=C:\Users\thoma\.ssh\vps_key
set SCP="C:\Program Files\Git\usr\bin\scp.exe"

echo [%date% %time%] Starting PP fetch...
cd /d %REPO%

%PYTHON% orchestrator.py --sport nhl --mode once --operation prizepicks
%PYTHON% orchestrator.py --sport nba --mode once --operation prizepicks
%PYTHON% orchestrator.py --sport mlb --mode once --operation prizepicks
%PYTHON% orchestrator.py --sport golf --mode once --operation prizepicks

echo [%date% %time%] Pushing prizepicks_lines.db to VPS...
%SCP% -i %SSH_KEY% -o StrictHostKeyChecking=no %LOCAL_DB% root@%VPS_IP%:%VPS_PATH%

echo [%date% %time%] Done.
