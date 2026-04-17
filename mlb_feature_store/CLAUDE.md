# mlb_feature_store — Module Guide for Claude

This module is a **self-contained MLB data pipeline + ML layer** that runs alongside the main SportsPredictor orchestrator. It has its own DuckDB database, its own training loop, and its own daily run script. Do not cross-import with `nhl/`, `nba/`, or `shared/`.

## Directory layout

```
mlb_feature_store/
  config/settings.py        Central config — paths + env-override settings
  ingest/                   Raw data fetchers (Statcast, FanGraphs, schedule)
  transform/                Aggregation + rolling features + gold layer
  labels/                   Prop outcome labels derived from raw data
  feature_store/            DuckDB schema + upsert helpers (build_duckdb.py)
  ml/                       XGBoost training, evaluation, prediction, grading
  data/mlb.duckdb           Live DuckDB file — single-writer, do NOT open from two processes
  run_daily.py              Full daily ingest → labels → DuckDB pipeline
  backfill.py               Historical backfill (--resume flag for safe reruns)
```

## Common commands

```bash
# Always run from mlb_feature_store/ directory
cd /c/Users/thoma/SportsPredictor/mlb_feature_store

# Daily pipeline (defaults to yesterday)
python run_daily.py
python run_daily.py --date 2026-04-12

# ML training (all 6 props, or one at a time)
python -m ml.train
python -m ml.train --prop hits

# Accuracy report vs stat model
python -m ml.evaluate

# Write today's ML predictions to DuckDB
python -m ml.predict_to_db --date 2026-04-13

# Grade yesterday's ML predictions
python -m ml.grade --date 2026-04-12

# Rebuild player name lookup (after new season data loads)
python -m ml.build_players

# Safe historical backfill (skips already-ingested dates)
python backfill.py --resume
python backfill.py --start 2026-03-27
```

## DuckDB schema — 10 tables

| Table | Key columns | Updated by |
|---|---|---|
| `ingestion_metadata` | data_type, last_ingested_date | run_daily.py |
| `hitters_daily` | player_id, date, avg_ev, avg_la, xwoba, pa | run_daily.py |
| `pitchers_daily` | pitcher_id, date, avg_velocity, whiff_rate | run_daily.py |
| `player_features` | player_id, date (gold-layer hitter features) | run_daily.py |
| `pitcher_features` | pitcher_id, date (gold-layer pitcher features) | run_daily.py |
| `hitter_labels` | player_id, game_date, hits, total_bases, home_runs | run_daily.py |
| `pitcher_labels` | player_id, game_date, strikeouts, walks, outs_recorded | run_daily.py |
| `players` | player_id, player_name, player_type | ml/build_players.py |
| `ml_predictions` | player_id, game_date, prop, predicted_value | ml/predict_to_db.py |
| `ml_grading_log` | game_date, rows_graded | ml/grade.py |

## ML models — 6 props

| Prop | Type | Features | Filter | 2026 accuracy |
|---|---|---|---|---|
| hits | hitter | avg_ev, avg_la, xwoba, ev_7d, xwoba_14d | none | 72.8% |
| total_bases | hitter | same | none | 74.5% |
| home_runs | hitter | same | none | worse than naive — do NOT swap |
| strikeouts | pitcher | avg_velocity, whiff_rate, xwoba_allowed, velocity_trend_7d, park_adjusted_xwoba | outs_recorded >= 9 | 71.0% |
| walks | pitcher | same | starters only | 61.1% |
| outs_recorded | pitcher | same | starters only | 68.7% |

Models live in `ml/models/*.pkl`. Metadata (accuracy, feature importance, date ranges) in `ml/models/metadata.json`.

## Orchestrator integration

The main `orchestrator.py` hooks into this module **automatically** — do not run manually if the orchestrator is alive:

- **After MLB stat predictions**: runs `run_daily.py --date <today>` then `ml.predict_to_db --date <today>`
- **After MLB grading**: re-runs `run_daily.py --date <yesterday>` then `ml.grade --date <yesterday>`

Both hooks are non-fatal — a failure here does NOT abort the main MLB pipeline.

## Known gotchas

- **Single-writer DuckDB**: Only one process can write at a time. `backfill.py` holds a write lock — don't run `run_daily.py` or `predict_to_db` while backfill is running.
- **Statcast lag**: Statcast data lands ~24 hours after games. `predict_to_db.py` auto-falls back to the latest available features if today's data hasn't arrived yet.
- **FanGraphs 403**: FanGraphs blocks scraping — `wrc_plus`, `wpa`, `opp_strength` are NULL. Models are Statcast-only; do not add FanGraphs features back without testing first.
- **Home runs model**: MAE is worse than the naive "predict league mean" baseline. Do not replace the stat model for HR — leave it alone.
- **Pitcher ID mismatch**: `pitcher_features` uses `pitcher_id` column; `pitcher_labels` uses `player_id`. Both store the same values; joins work as-is.
- **TUI enrichment**: `tui/ml_bridge.py` joins smart_picks MLB rows with DuckDB ml_predictions. On light game days (< 10 MLB picks) or when today's Statcast hasn't landed, `ML Exp` and `ML +/-` columns show `--`. That is correct.

## Configuration

All paths come from `config/settings.py`. Override via environment variables with `MLB_` prefix:

```bash
MLB_STATCAST_COLUMNS='["launch_speed","launch_angle"]'  # override Statcast cols
```

Never hardcode `data/mlb.duckdb` — always use `config.settings.PATHS.duckdb`.

## What NOT to do

- Do not import from `nhl/`, `nba/`, or `shared/` — this module is intentionally isolated
- Do not open DuckDB in write mode from two processes simultaneously
- Do not retrain models unless you have at least 500 rows per prop after `dropna`
- Do not add the home_runs ML model to smart pick selection (it underperforms the stat model)
- Do not run `backfill.py` while the orchestrator's MLB pipeline hook is active
