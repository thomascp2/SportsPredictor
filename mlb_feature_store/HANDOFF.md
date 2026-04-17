# MLB Feature Store — Session Handoff (2026-04-13)

## What was built this session

### 1. ML Training Module (`mlb_feature_store/ml/`)
Six XGBoost regression models trained on 2024-2025 Statcast data (95k hitter rows, 41k pitcher rows).

**Props:** hits, total_bases, home_runs, strikeouts, walks, outs_recorded  
**Hitter features:** avg_ev, avg_la, xwoba, ev_7d, xwoba_14d  
**Pitcher features:** avg_velocity, whiff_rate, xwoba_allowed, velocity_trend_7d, park_adjusted_xwoba  
**Pitcher models filter:** outs_recorded >= 9 (starters only)  

**Test-set accuracy vs current stat model (2026 season):**
| Prop | ML test acc | Stat model 2026 |
|---|---|---|
| hits O0.5 | 72.8% | 70.1% |
| total_bases O1.5 | 74.5% | 55.8% |
| strikeouts O4.5 | 71.0% | 62.0% |
| outs_recorded O14.5 | 68.7% | 59.3% |
| walks O1.5 | 61.1% | 40.8% |

Models saved to `mlb_feature_store/ml/models/*.pkl` + `metadata.json`.

### 2. New files
- `ml/train.py` — XGBoost regressor training, temporal 70/15/15 split
- `ml/evaluate.py` — terminal accuracy report per prop + per line
- `ml/predict.py` — terminal predictions for a date with Poisson P(OVER)
- `ml/predict_to_db.py` — writes predictions to DuckDB `ml_predictions` table; falls back to latest features if today's Statcast not yet available
- `ml/grade.py` — grades ML predictions vs hitter_labels/pitcher_labels; writes actual_value back to ml_predictions
- `ml/build_players.py` — seeds `players` table from main MLB SQLite DB + pybaseball chadwick fallback (98.1% coverage, 1,804 players)

### 3. DuckDB schema additions (`feature_store/schema.sql`)
- `players` table — player_id → player_name, player_type
- `ml_predictions` table — player_id, player_name, game_date, prop, predicted_value, actual_value, graded_at, model_version
- `ml_grading_log` table — tracks which dates have been graded

### 4. 2026 season backfill
- Ran `backfill.py --start 2026-03-27` → 17 days ingested, 0 errors
- ML predictions written for Apr 10, 11, 12, 13

### 5. Orchestrator integration (`orchestrator.py`)
- Added `_run_feature_store_cmd()` helper method (runs from mlb_feature_store/ dir, non-fatal, logs to daily pipeline log)
- **Prediction hook** (MLB only): after stat model → runs `run_daily.py --date <today>` then `ml.predict_to_db --date <today>`
- **Grading hook** (MLB only): after stat grading → re-runs `run_daily.py --date <yesterday>` then `ml.grade --date <yesterday>`

### 6. Cloud dashboard (`dashboards/cloud_dashboard.py`)
- Added `_render_mlb_ml_comparison()` function in MLB tab (between Player Props and Season Props)
- Shows: Player | Prop | Line | ML Expected | ML P(Over)% | ML Pred | Stat Prob% | Stat Pred | Agree
- Green/red Agree column; filters by prop, player, disagreements-only

### 7. TUI Terminal (`tui-terminal/`)
- `props.db` migrated: added `ml_predicted_value REAL` column to smart_picks
- `tui/ml_bridge.py` — added `_enrich_mlb_ml()` that joins smart_picks MLB rows with DuckDB ml_predictions after every sync
- `tui/widgets/main_grid.py` — two new columns:
  - **ML Exp** (width 7) — raw predicted value, color: green if > line, red if below, amber if within 0.2
  - **ML +/-** (width 7) — predicted_value minus pp_line signed delta, same color scheme

## What still needs to be done (next session)
1. **Write `mlb_feature_store/CLAUDE.md`** — module-specific instructions for future Claude sessions
2. **Write `mlb_feature_store/ARCHITECTURE.md`** — full technical reference doc
3. **Verify tomorrow morning** — check orchestrator ran the feature store hooks cleanly in the pipeline log (`logs/pipeline_mlb_YYYYMMDD.log`)
4. **Validate enrichment on a full game day** — today was a light Monday (15 picks, all pitchers, 0 matched). Full enrichment confirmed working on Apr 11 (50/50 stat picks matched).
5. **Consider: swap stat model for ML on strikeouts/total_bases/walks** — these are the clear wins. Needs 2-3 weeks of live 2026 accuracy comparison first.

## Key paths
```
mlb_feature_store/
  data/mlb.duckdb               main DuckDB file
  ml/models/*.pkl               trained models
  ml/models/metadata.json       training metadata + accuracy
  ml/train.py                   retrain: python -m ml.train
  ml/evaluate.py                report: python -m ml.evaluate
  ml/predict_to_db.py           daily: python -m ml.predict_to_db
  ml/grade.py                   grade: python -m ml.grade
  ml/build_players.py           player names: python -m ml.build_players
  backfill.py                   backfill: python backfill.py --resume
  run_daily.py                  daily pipeline: python run_daily.py --date YYYY-MM-DD
```

## Known gotchas
- Statcast data lands ~24hrs after games — `predict_to_db.py` auto-falls back to latest available features
- DuckDB single-writer — only one process at a time; backfill locks it
- `ml_predicted_value` in TUI will show `--` for NHL/NBA rows (correct — ML only covers MLB)
- Home runs model MAE is WORSE than naive baseline (rare event problem) — don't swap stat model for HR
- `pitcher_features` uses `pitcher_id` col; `pitcher_labels` uses `player_id` — same values, different names; join works
- FanGraphs 403 is permanent for now — wrc_plus, wpa, opp_strength are all NULL; models use Statcast-only features
