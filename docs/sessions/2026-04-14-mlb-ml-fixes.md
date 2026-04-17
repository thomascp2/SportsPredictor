# MLB ML Pipeline — Bug Fixes & Hardening (2026-04-14)

## What broke and why

### 1. NBA Play-In games silently skipped (NBA 0 picks today)
**File:** `nba/scripts/nba_config.py` — `_fetch_and_cache_schedule()`  
**Bug:** `nba_has_games()` only counted game IDs starting with `002` (regular season). Play-In Tournament game IDs start with `005`. Cache was built on Apr 9 and contained no Play-In dates.  
**Symptom:** NBA prediction pipeline returned `(False, 0)` for Apr 13–16, skipping the entire pipeline. 829/829 PP lines unmatched because no predictions existed.  
**Fix:** Added `or game_id.startswith('005')` to the ID filter. Force-refreshed cache.  
**Also applies to:** Playoffs (`004`) if we ever want to predict those — add then.

### 2. NBA grading script corrupted (IndentationError every run)
**File:** `nba/scripts/auto_grade_multi_api_FIXED.py` lines 371–378  
**Bug:** Duplicate `if __name__ == '__main__':` block appended with broken indentation (`rader =` instead of `grader =`). Every grading run since the last edit failed at import.  
**Fix:** Deleted the duplicate block. Confirmed syntax with `ast.parse`.

### 3. MLB stat model: 4471 AttributeErrors per run
**File:** `mlb/features/batter_feature_extractor.py` line 133  
**Bug:** `self._compute_fatigue_features(games, target_date)` was called but the method was never implemented. Every batter × prop × line combination threw `AttributeError` silently caught in the caller, generating thousands of error lines in the pipeline log.  
**Symptom:** Stat model ran very slowly, consuming most of the subprocess timeout budget, leaving no time for the feature store hooks.  
**Fix:** Implemented `_compute_fatigue_features()` — returns `f_days_rest` (0–7) and `f_played_yesterday` (0/1) from game log dates.

### 4. MLB feature store hooks coupled inside prediction pipeline (root cause of missing ML output)
**Root cause:** `run_daily.py` and `ml.predict_to_db` were chained inline after the stat model inside `run_daily_prediction_pipeline()`. When the stat model consumed close to the 5-min subprocess timeout (due to bug #3), the feature store subprocesses had no budget left and silently timed out — no log entry is written on `TimeoutExpired`.  
**Fix:** Removed both inline hooks entirely. Added `run_mlb_feature_store()` as a **standalone scheduled method** at 10:20 AM — its own time slot, own 600s timeout, own Discord alert on failure. Wired into `schedule_tasks()` for MLB only via `feature_store_time` config key.  
**Orchestrator changes:** `orchestrator.py` — removed Step 2b from `run_daily_prediction_pipeline` and Step 1b from `run_daily_grading`. Added `run_mlb_feature_store()` method and scheduler registration.

### 5. ML predictions: relievers getting starter-model predictions
**File:** `mlb_feature_store/ml/predict_to_db.py`  
**Bug:** `_run_models()` had no `starter_only` filter. The pitcher model for `outs_recorded`, `strikeouts`, `walks` was trained on starters only (outs >= 9 in training labels) but was applied to all 333 pitchers in `pitcher_features`, including relievers.  
**Symptom:** Taylor Clarke (avg 3.1 outs/app historically) predicted 18.9 outs. Wandy Peralta (avg 2.8 outs) predicted 17.7 outs. Jeff Hoffman (avg 2.9 outs) predicted 9+ strikeouts.  
**Note:** Relievers never appear on PrizePicks for these props anyway — these rows were pure noise.  
**Fix:** `_get_starter_pitcher_ids()` — queries `pitcher_labels`, returns pitcher IDs with avg `outs_recorded >= 12.0` AND `>= 5 appearances`. Applied in `_run_models()` for all `starter_only=True` props. **97 relievers removed** per run. Predictions: 1,257 → 966 rows.

### 6. ML predictions: extreme feature extrapolation on small 2026 samples
**File:** `mlb_feature_store/ml/predict_to_db.py`  
**Bug:** No feature clipping before inference. Brice Turang had `xwoba = 1.035` on ~8 PA of 2026 data (a 3-hit, multi-XBH game inflating a tiny sample). Training distribution p99 = 0.895; 1.035 is outside even that. Model extrapolated to 6.15 expected total bases.  
**Fix:** `HITTER_CLIP` and `PITCHER_CLIP` dicts applied in `_clip_features()` before every model call:
- `xwoba`, `xwoba_14d`: capped at 0.600 (elite but realistic ceiling)
- `ev_7d`, `avg_ev`: capped at 105 mph
- `avg_la`: clipped to [-20, 50] degrees
- `whiff_rate`: capped at 0.65
- `avg_velocity`, `velocity_trend_7d`: clipped to [78, 101] mph
- `xwoba_allowed`, `park_adjusted_xwoba`: capped at 0.750

### 7. Unknown player names (~4% of rows)
**Status:** Pre-existing 1.9% lookup gap. `ml.build_players` seeds from main MLB SQLite + pybaseball (98.1% coverage). ~34 player IDs have no match in either source. Non-fatal — rows appear with `player_name = NULL` in the dashboard (shown as blank).  
**Not fixed** — would require manual MLBAM ID mapping for fringe roster players.

---

## Daily schedule after fixes (MLB orchestrator)

| Time (CST) | Operation |
|---|---|
| 08:00 AM | MLB grading (yesterday) |
| 08:30 AM | PrizePicks line fetch |
| 10:00 AM | MLB stat model predictions |
| **10:20 AM** | **MLB feature store + ML predictions (decoupled)** |
| 03:00 PM | PP afternoon re-sync |
| 04:00 PM | Top picks Discord post |

## Validation after fixes
- Apr 15 top hits: Altuve 1.806 (84% OVER 0.5) — reasonable  
- Apr 15 top total_bases: Altuve 3.482 (86% OVER 1.5) — reasonable  
- Apr 15 top strikeouts: deGrom 6.960, Gilbert 6.810 — reasonable for starters  
- Apr 15 top outs_recorded: deGrom 18.4, Gilbert 17.2 — reasonable for elite starters  
- Turang total_bases: no longer 6.155 (xwoba clipped, prediction now realistic)  
- Taylor Clarke outs_recorded: removed (reliever filter)  

## Files changed
- `nba/scripts/nba_config.py` — Play-In game ID fix
- `nba/scripts/auto_grade_multi_api_FIXED.py` — duplicate block removed
- `mlb/features/batter_feature_extractor.py` — `_compute_fatigue_features()` implemented
- `orchestrator.py` — inline hooks removed; `run_mlb_feature_store()` + `feature_store_time` added
- `mlb_feature_store/ml/predict_to_db.py` — starter filter + feature clipping
