# MLB Feature Store — Architecture Reference

## Overview

The MLB feature store is a medallion-architecture data pipeline that transforms raw Statcast + FanGraphs data into ML-ready feature vectors, trains XGBoost regression models per prop, and writes daily predictions back to DuckDB for consumption by the dashboard and TUI.

```
Statcast API (pybaseball)
    │
    ▼
[ingest/]          Raw parquet files → data/raw/
    │
    ▼
[transform/]       Aggregation, rolling windows, opponent strength → data/silver/ + data/gold/
    │
    ▼
[feature_store/]   DuckDB upserts (player_features, pitcher_features, *_labels)
    │
    ▼
[ml/]              XGBoost training → ml/models/*.pkl + Poisson predictions
    │
    ├── DuckDB ml_predictions (via predict_to_db.py)
    ├── Cloud dashboard MLB tab (ml_comparison widget)
    └── TUI ML Exp / ML +/- columns (via ml_bridge.py)
```

## Data layers

### Bronze (skipped — no raw DB)
Raw Statcast pulls are stored as **parquet files** in `data/raw/statcast/` and `data/raw/fangraphs/`. These are the source of truth. If DuckDB is corrupted, re-ingest from these files.

### Silver (daily aggregates)
`transform/aggregate_hitters.py` and `transform/aggregate_pitchers.py` produce one row per (player, date):
- Hitters: `avg_ev`, `avg_la`, `xwoba`, `pa`, `hard_hit_rate`
- Pitchers: `avg_velocity`, `avg_break_x/z`, `xwoba_allowed`, `whiff_rate`, `pitches_thrown`

Saved to `data/silver/hitters/` and `data/silver/pitchers/` as parquet, and upserted into DuckDB `hitters_daily` / `pitchers_daily`.

### Gold (feature-engineered)
`transform/merge_features.py` combines silver + rolling + opponent data:

**Hitter features** (`player_features` table):
| Feature | Source | Description |
|---|---|---|
| avg_ev | Statcast | Average exit velocity (game-level) |
| avg_la | Statcast | Average launch angle (game-level) |
| xwoba | Statcast | Expected wOBA on contact |
| ev_7d | rolling | 7-day rolling avg exit velocity |
| xwoba_14d | rolling | 14-day rolling xwoba |
| opp_strength_7d | opponent | Opponent pitcher quality last 7d |
| park_adjusted_woba | park factors | wOBA adjusted for ballpark |
| wrc_plus, wpa, re24 | FanGraphs | **Always NULL** (FanGraphs 403 — Statcast-only models) |

**Pitcher features** (`pitcher_features` table):
| Feature | Source | Description |
|---|---|---|
| avg_velocity | Statcast | Mean fastball velocity |
| whiff_rate | Statcast | Swinging-strike rate |
| xwoba_allowed | Statcast | Expected wOBA allowed |
| velocity_trend_7d | rolling | Velocity change over last 7 days |
| opponent_strength | FanGraphs | Opposing lineup quality (NULL if FG blocked) |
| park_adjusted_xwoba | park factors | xwoba_allowed normalized for park |

### Labels
`labels/compute_labels.py` computes prop outcome values per (player, game_date):
- `hitter_labels`: hits, total_bases, home_runs
- `pitcher_labels`: strikeouts, walks, outs_recorded

These are the training targets. Apply any line threshold at query time: `actual_value > line => OVER`.

## ML pipeline

### Training (`ml/train.py`)

**Temporal split**: 70% train / 15% val (early stopping) / 15% test (evaluation only). No random shuffle — rows are ordered by date to prevent leakage.

**Model**: `XGBRegressor` with MAE eval metric. Early stopping at 30 rounds on val set.

**XGBoost params**:
- `n_estimators=500`, `learning_rate=0.05`, `max_depth=5`
- `subsample=0.8`, `colsample_bytree=0.8`
- `reg_alpha=0.1`, `reg_lambda=1.0`

**Pitcher filter**: Strikeouts, walks, and outs_recorded models filter `outs_recorded >= 9` to starters only. Relief pitchers have far too much variance for regression to be useful.

**Skips**: Any prop with < 500 clean rows after `dropna` is skipped.

### Prediction (`ml/predict_to_db.py`)

1. Load feature vector for each player with a game today
2. Run `model.predict(features)` → raw expected count (`predicted_value`)
3. Convert to `P(OVER line)` via Poisson CDF: `1 - poisson.cdf(floor(line), mu=predicted_value)`
4. Write to `ml_predictions` table (upsert on player_id, game_date, prop)

**Fallback**: If today's Statcast hasn't landed yet, uses the most recent available feature row for each player.

### Evaluation (`ml/evaluate.py`)

Loads the test split (last 15% by date), computes per-prop and per-line accuracy:
- **Directional accuracy**: `round(predicted_value) > line` vs `actual_value > line`
- Reports vs. the statistical model's 2026 season accuracy for direct comparison

**Key results (trained on 2024-2025 Statcast, tested on 2026)**:
| Prop | ML test acc | Stat model 2026 | Delta |
|---|---|---|---|
| hits O0.5 | 72.8% | 70.1% | +2.7pp |
| total_bases O1.5 | 74.5% | 55.8% | +18.7pp |
| strikeouts O4.5 | 71.0% | 62.0% | +9.0pp |
| outs_recorded O14.5 | 68.7% | 59.3% | +9.4pp |
| walks O1.5 | 61.1% | 40.8% | +20.3pp |
| home_runs | — | — | worse than naive — excluded |

### Grading (`ml/grade.py`)

Joins `ml_predictions` with `hitter_labels`/`pitcher_labels` on (player_id, game_date). Writes `actual_value` back to `ml_predictions`. Tracks graded dates in `ml_grading_log` to prevent double-grading.

## DuckDB notes

- **Single-writer**: DuckDB supports one write connection at a time. Backfill holds the lock while running. The orchestrator hooks and `predict_to_db.py` must not run concurrently with `backfill.py`.
- **Connection pattern**: `duckdb.connect(str(DB_PATH))` — always pass a string path, not a Path object, for compatibility.
- **Schema init**: `feature_store/build_duckdb.py::initialize_schema()` runs `CREATE TABLE IF NOT EXISTS` for all 10 tables. Safe to call on every startup.
- **Upsert pattern**: DuckDB uses `INSERT OR REPLACE` semantics via `conn.executemany()` with `ON CONFLICT DO UPDATE`.

## Orchestrator integration

`orchestrator.py` calls `_run_feature_store_cmd()` which:
1. Sets CWD to `mlb_feature_store/`
2. Runs command as a subprocess
3. Appends stdout/stderr to `logs/pipeline_mlb_YYYYMMDD.log`
4. Returns success/failure without raising (non-fatal to main pipeline)

**Prediction hook** (MLB, after stat predictions):
```
python run_daily.py --date <today>
python -m ml.predict_to_db --date <today>
```

**Grading hook** (MLB, after stat grading):
```
python run_daily.py --date <yesterday>
python -m ml.grade --date <yesterday>
```

## Dashboard integration

`dashboards/cloud_dashboard.py` — MLB tab — calls `_render_mlb_ml_comparison()`:
- Reads `ml_predictions` from DuckDB
- Reads stat-model smart picks from main MLB SQLite DB
- Joins on (player_name, game_date, prop)
- Renders: Player | Prop | Line | ML Expected | ML P(Over)% | ML Pred | Stat Prob% | Stat Pred | Agree

## TUI integration

`tui-terminal/tui/ml_bridge.py::_enrich_mlb_ml()`:
- Runs after every smart_picks sync
- Joins TUI `props.db` smart_picks (MLB rows) with DuckDB `ml_predictions`
- Writes `ml_predicted_value` back to the TUI smart_picks row
- `main_grid.py` renders two extra columns: **ML Exp** (width 7) and **ML +/-** (width 7)

NHL/NBA rows show `--` in these columns — that is correct behavior.

## Config system

`config/settings.py` uses **Pydantic BaseSettings** with `env_prefix = "MLB_"`. All paths resolve relative to the module root. Never hardcode paths — always import `PATHS` and `SETTINGS`.

```python
from config.settings import PATHS, SETTINGS

db_path = PATHS.duckdb          # data/mlb.duckdb
raw_dir = PATHS.raw_statcast    # data/raw/statcast/
windows  = SETTINGS.rolling_windows  # {"ev_7d": 7, "xwoba_14d": 14, ...}
```

## Retrain cadence (recommended)

- **Next retrain**: October 2026 (after full 2026 season)
- **Training data**: 2024 + 2025 + 2026 Statcast (~150k hitter rows, ~65k pitcher rows projected)
- **Trigger**: `python -m ml.train` from `mlb_feature_store/` directory
- **Do not retrain mid-season** unless accuracy drops > 5pp from baseline on 30-day rolling window

## Known limitations

1. **FanGraphs 403**: `wrc_plus`, `wpa`, `opp_strength` always NULL. Do not attempt to re-add FanGraphs features without a working scraping layer.
2. **Home runs model**: Rare-event regression underperforms naive baseline. Excluded from smart pick selection.
3. **Statcast lag**: Data lands ~24h after games. `predict_to_db` falls back to prior-day features automatically.
4. **Pitcher starters only**: Relief pitchers are excluded from strikeouts/walks/outs_recorded models. If a starter is pulled early (< 9 outs), that game row is also excluded from training.
5. **Player ID coverage**: `ml/build_players.py` achieves 98.1% coverage (1,804 players) using MLB SQLite + pybaseball chadwick. ~35 players have no name mapping — they get `player_id` as display name in the dashboard.
