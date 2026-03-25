# Session Notes - March 24, 2026

## Issue: Predictions Did Not Populate

### What Happened
Today's predictions (NHL + NBA) failed to generate due to a CPU/system crash overnight.

The orchestrator (`start_orchestrator.bat`) runs 4 windows:
- Discord bot
- Orchestrator (continuous mode - grading, predictions, health checks)
- FreePicks Dashboard
- Streamlit

The system crashed during the early morning pipeline. The orchestrator got as far as the **NHL schedule fetch at 04:00** before the process was killed. Since the `schedule` library does not re-run missed jobs on restart, both sports' prediction pipelines were skipped entirely.

### Evidence
- `logs/pipeline_nhl_20260324.log` — ends abruptly after schedule fetch, no prediction generation entry
- `logs/pipeline_nba_20260324.log` — ends after grading, no prediction generation entry
- Both DBs confirmed 0 predictions for 2026-03-24

### Root Cause
System/CPU crash killed the orchestrator process. The `start_orchestrator.bat` restart loop (30s delay) restarted it, but the 04:00 NHL and 06:00 NBA prediction jobs were already past their scheduled times and were not re-run.

### Fix Applied
Ran predictions manually and synced to Supabase:

```bash
cd /c/Users/thoma/SportsPredictor/nhl
python scripts/generate_predictions_daily_V6.py 2026-03-24 --force

cd /c/Users/thoma/SportsPredictor/nba
python scripts/generate_predictions_daily_V6.py 2026-03-24
```

Then synced via Python:
```python
from sync.supabase_sync import SupabaseSync
syncer = SupabaseSync()
for sport in ['nhl', 'nba']:
    syncer.sync_predictions(sport, '2026-03-24')
    syncer.sync_smart_picks(sport, '2026-03-24')
    syncer.sync_odds_types(sport, '2026-03-24')
    syncer.sync_game_times(sport, '2026-03-24')
```

### Results
| Sport | Predictions | Smart Picks | Odds Fixed | Game Times |
|-------|-------------|-------------|------------|------------|
| NHL   | 1,007       | 68          | 356        | 896 rows   |
| NBA   | 1,136       | 176         | 902        | 1,140 rows |

### Quick Recovery Command (for future crashes)
If predictions are missing after a crash, run:
```bash
cd /c/Users/thoma/SportsPredictor
python orchestrator.py --sport nhl --mode once --operation prediction
python orchestrator.py --sport nba --mode once --operation prediction
```

This re-runs the full pipeline (generate + verify + Supabase sync) for both sports.

### Notes
- The orchestrator's `_run_script` timeout is 5 minutes — NHL V6 with 15 games takes ~34 seconds, well under the limit
- The `schedule` library is single-threaded; missed jobs are not replayed on restart
- No code changes were made; this was an operational recovery
