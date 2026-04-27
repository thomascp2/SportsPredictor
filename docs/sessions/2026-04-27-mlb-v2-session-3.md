# MLB V2 — Session 3 Handoff
**Date: 2026-04-27 | Status: Pipeline partially working. CRITICAL architectural decision made. Session 4 = full silo.**

---

## What Was Done

### NHL/NBA Playoff Backfills — COMPLETE
- NHL: 1,008 rows written (Apr 19–26), 8 days × 4 games × 36 players
- NBA: 583 rows written (Apr 19–26), variable games per day
- Both scripts work cleanly with `--backfill YYYY-MM-DD`

### New bat files created
- `apex-arb/run_v2_ingest.bat` — runs `python -m feature_store.run_daily` at 10:30 AM
- `apex-arb/run_v2_feature_predict.bat` — runs `python -m feature_store.ml.predict_to_db` at 10:45 AM

### Task Scheduler Registration — PENDING (needs admin elevation)
All 4 tasks need to be registered. Run in Admin CMD:
```bat
schtasks /create /tn "MLB_V2_Daily_Grading" /tr "C:\Users\thoma\apex-arb\run_v2_grader.bat" /sc DAILY /st 08:00 /rl HIGHEST /f
schtasks /create /tn "MLB_V2_Daily_Predictions" /tr "C:\Users\thoma\apex-arb\run_v2_predictor.bat" /sc DAILY /st 10:00 /rl HIGHEST /f
schtasks /create /tn "MLB_V2_Feature_Ingest" /tr "C:\Users\thoma\apex-arb\run_v2_ingest.bat" /sc DAILY /st 10:30 /rl HIGHEST /f
schtasks /create /tn "MLB_V2_Feature_Predict" /tr "C:\Users\thoma\apex-arb\run_v2_feature_predict.bat" /sc DAILY /st 10:45 /rl HIGHEST /f
```

### Bugs Fixed in generate_v2_predictions.py
| Bug | Fix |
|-----|-----|
| `pd` not imported | Added `import pandas as pd` |
| Statcast lag: BMA always stat-only | Load latest-per-player from DuckDB (QUALIFY ROW_NUMBER) instead of exact date match |
| Coverage tracking: overwritten by last prop | Sticky: once 'bma', don't downgrade |
| RF/LR NULL in DuckDB (predict_to_db run before training) | Forced rerun with `--force` — now 993 rows: xgb=993 rf=993 lr=993 |

### BMA Now Working
After fixes: **71% BMA coverage** (24/34 players) on Apr 27 predictions.
- XGB: 1,464 player-prop pairs loaded
- RF: 960 player-prop pairs loaded
- LR: 960 player-prop pairs loaded

### Bugs Fixed in auto_grade_daily.py
| Bug | Fix |
|-----|-----|
| `from generate_predictions_daily import backup_database` | Inlined backup_database() — removes SP dependency |
| `from shared.pp_rules_validator import ...` | Added `_SP_ROOT` sys.path hack — **FLAGGED AS DANGEROUS, remove in Session 4** |
| `is_smart_pick` column missing on predictions table | Added to schema in mlb_config.py + idempotent ALTER TABLE in grader |

### Schema Updates (mlb_config.py + mlb_v2.db)
- `predictions` table: added `odds_type TEXT DEFAULT 'standard'`
- `predictions` table: added `is_smart_pick INTEGER DEFAULT 0`
- Both columns added via ALTER TABLE on existing DB

### Grading NOT yet verified
Grader was fixed but not confirmed working — session stopped before the `auto_grade_daily.py 2026-04-26` run completed. `ml_v2_outcomes` table does not exist yet. Calibration cannot run until grading succeeds at least once.

### Retroactive Predictions Generated
- 2026-04-25: 288 rows, 14% BMA coverage
- 2026-04-26: 330 rows, 44% BMA coverage
- 2026-04-27: 360 rows, 71% BMA coverage (latest, after all fixes)

---

## CRITICAL ARCHITECTURAL DECISION

### The Silo Problem
During session 3, three SP dependencies were added to apex-arb via sys.path hacks:
1. `espn_mlb_api.py` — schedule + ESPN odds fetching (in `fetch_game_schedule.py`)
2. `weather_client.py` — weather data (in `fetch_game_schedule.py`)
3. `shared/pp_rules_validator.py` — outcome grading logic (in `auto_grade_daily.py`)

**#3 is the critical one.** `pp_rules_validator` determines what counts as HIT/MISS/VOID in grading. That feeds `ml_v2_outcomes`. That is the training label source for all future retrains. If SP's validator changes silently, training labels change. This is the exact mechanism that wrecked NBA UNDER accuracy (83% → 47%).

### Decision: Full Silo — Session 4 Priority 0
**Before any more grading or calibration data accumulates**, Session 4 must:
1. Copy `espn_mlb_api.py` into `apex-arb/mlb/scripts/` and own it
2. Copy `weather_client.py` into `apex-arb/mlb/scripts/` and own it
3. Rewrite the grading logic (HIT/MISS/VOID rules) inline in `auto_grade_daily.py` — do NOT copy pp_rules_validator, rewrite it fresh and explicitly
4. Remove ALL sys.path references to SportsPredictor from apex-arb scripts
5. Verify: `python generate_v2_predictions.py` and `python auto_grade_daily.py` both work with SportsPredictor directory REMOVED from sys.path (test with a dummy import guard)

**Why rewrite pp_rules_validator rather than copy it?**
Copying is still coupling — apex-arb would have a copy of SP's logic that could drift in either direction. The grading rules (OVER/UNDER on demon/goblin/standard lines) are simple enough to own directly in 20 lines of code.

---

## What's NOT Done Yet

| Task | Status | Notes |
|------|--------|-------|
| TS registration (4 tasks) | PENDING | Needs admin CMD |
| NHL/NBA playoff TS entries | PENDING | Not yet registered |
| Grading verified end-to-end | PENDING | `auto_grade_daily.py 2026-04-26` not run |
| `ml_v2_outcomes` table exists | PENDING | Created on first successful grade |
| First calibration run | PENDING | Needs ml_v2_outcomes |
| Full silo (remove SP deps) | PENDING | SESSION 4 PRIORITY 0 |
| feature_store/run_daily.py live test (full, not skip-ingest) | PENDING | |

---

## Session 4 — Full Prompt

```
We are building MLB V2 inside the apex-arb repo (C:\Users\thoma\apex-arb).
Read MLB_V2_MASTER_PLAN.md and docs/sessions/2026-04-27-mlb-v2-session-3.md
in SportsPredictor before anything else.

Context:
- Session 3 complete. BMA working at 71% coverage. Multiple bugs fixed.
- CRITICAL: apex-arb has SP dependencies via sys.path hacks that MUST be removed before
  any more grading data accumulates. See "CRITICAL ARCHITECTURAL DECISION" in session 3 doc.
- Retroactive predictions exist for Apr 25, 26, 27. Grading not yet verified.
- `ml_v2_outcomes` table does not exist yet — calibration cannot run until grading works.
- Task Scheduler registration PENDING (needs admin elevation — 4 schtasks commands in session doc).

Session 4 Priority Order (do not reorder):
1. SILO FIRST: Remove all SportsPredictor sys.path dependencies from apex-arb
   a. Copy espn_mlb_api.py into apex-arb/mlb/scripts/ (own it, no SP link)
   b. Copy weather_client.py into apex-arb/mlb/scripts/ (own it, no SP link)
   c. Rewrite HIT/MISS/VOID grading rules directly in auto_grade_daily.py
      (rules are simple: demon/goblin = OVER only; standard = OVER or UNDER;
       actual_value None or DNP = VOID; push = PUSH)
   d. Remove all sys.path.insert(...SP...) lines from apex-arb scripts
   e. Verify with: cd apex-arb && python mlb/scripts/generate_v2_predictions.py
      and python mlb/scripts/auto_grade_daily.py — both must work with zero SP imports

2. Run auto_grade_daily.py 2026-04-25 and 2026-04-26 to create ml_v2_outcomes
3. Verify ml_v2_outcomes has rows, then run mlb_v2_calibration.py (first report)
4. Register Task Scheduler tasks (4 schtasks commands — in session 3 doc)
5. Commit everything to apex-arb/master

Push back hard if scope creeps. MLB V2 + silo work only.
No dashboard. No Discord. No Supabase. No FreePicks.
Early stopping rule is law — NHL/NBA debacle is why.
```
