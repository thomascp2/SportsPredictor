# MLB Feature Store — Project Status
**Last updated:** 2026-04-13  
**Working directory:** `C:\Users\thoma\SportsPredictor\mlb_feature_store\`  
**Python:** Global Python 3.13 (NOT a venv — runs in global env alongside main SportsPredictor)

---

## Objective

Build a standalone MLB prop prediction system using Statcast data and regression-based ML models. This is **separate from the main SportsPredictor orchestrator** and will not be wired into `start_orchestrator.bat` until explicitly decided. The end goal is daily MLB prop predictions (pitcher strikeouts, hitter hits, total bases, home runs) that can eventually feed into the FreePicks platform.

---

## Architecture

```
mlb_feature_store/
├── config/settings.py          # All paths and constants — edit here first
├── ingest/
│   ├── statcast_hitting.py     # Fetches pitch-level Statcast data (hitting + events)
│   ├── statcast_pitching.py    # Fetches Statcast pitching metrics
│   ├── fangraphs_hitting.py    # Season FanGraphs stats — 403s gracefully (non-fatal)
│   └── fangraphs_pitching.py   # Season FanGraphs stats — 403s gracefully (non-fatal)
├── transform/
│   ├── aggregate_hitters.py    # Silver: daily per-player contact quality metrics
│   ├── aggregate_pitchers.py   # Silver: daily per-pitcher velocity/stuff metrics
│   ├── rolling_features.py     # 7d/14d rolling windows on silver
│   ├── opponent_strength.py    # Team-level opponent quality (skips if FanGraphs missing)
│   └── merge_features.py       # Gold: joins rolling + opponent into model-ready features
├── labels/
│   └── compute_labels.py       # Derives actual prop values from raw Statcast events
├── feature_store/
│   ├── schema.sql              # DuckDB table definitions
│   └── build_duckdb.py         # Upsert helpers for all tables
├── run_daily.py                # Full daily pipeline (ingest → silver → gold → labels)
├── backfill.py                 # Historical backfill with --force and --resume flags
└── backfill_labels.py          # Standalone label backfill from existing parquets
```

**Data lake:** `data/`
```
data/
├── mlb.duckdb                  # Single DuckDB file — all tables
├── raw/statcast/               # One parquet per day (hitting, includes pitcher col)
├── raw/statcast/*_pitching.parquet  # Pitcher velocity/movement parquets
├── silver/hitters/             # Daily aggregated hitter metrics
├── silver/pitchers/            # Daily aggregated pitcher metrics
└── gold/features/              # Model-ready feature tables per day
```

---

## Current State (as of 2026-04-13)

### Data Ingested
| Dataset | Status | Coverage |
|---|---|---|
| Statcast hitting (2024) | COMPLETE | 2024-04-01 to 2024-10-01 |
| Statcast pitching (2024) | COMPLETE | 2024-04-01 to 2024-10-01 |
| Statcast hitting (2025) | IN PROGRESS | Running now — 2025-03-27 to 2025-09-28 |
| Statcast pitching (2025) | IN PROGRESS | Running alongside 2025 hitting |
| FanGraphs (any year) | BLOCKED | fangraphs.com returning 403 — non-fatal, pipeline continues without it |

### DuckDB Tables (2024 data only — 2025 will double these)
| Table | Rows | Notes |
|---|---|---|
| hitter_labels | 47,326 | Per-player per-game actual stat values |
| pitcher_labels | 20,199 | Includes starters AND relievers |
| hitters_daily | 47,328 | Silver contact-quality aggregates |
| pitchers_daily | 20,205 | Silver velocity/stuff aggregates |
| player_features | 47,328 | Gold hitter features (model-ready) |
| pitcher_features | 20,205 | Gold pitcher features (model-ready) |

### Prop Labels Schema

**hitter_labels:** `player_id, game_date, hits, total_bases, home_runs`  
**pitcher_labels:** `player_id, game_date, strikeouts, walks, outs_recorded`

Labels store **actual values** (not binary HIT/MISS). Apply any line at query time:
```sql
-- OVER 1.5 hits: actual hits > 1.5
SELECT player_id, game_date, hits > 1.5 AS over FROM hitter_labels
```

---

## Prop Lines and Models Planned

### Pitcher Props (regression — predict actual value, threshold any line)
| Prop | Lines | Notes |
|---|---|---|
| strikeouts | 3.5, 4.5, 5.5, 6.5, 7.5 | **Starters only** — filter: `outs_recorded >= 9` |
| walks | 1.5, 2.5 | Starters only |
| outs_recorded | 14.5, 17.5 | = innings × 3 |

### Hitter Props (regression — predict actual value, threshold any line)
| Prop | Lines | Notes |
|---|---|---|
| hits | 0.5, 1.5, 2.5 | All batters |
| total_bases | 1.5, 2.5, 3.5 | All batters |
| home_runs | 0.5, 1.5 | All batters |

**NOT YET IMPLEMENTED (requires box score data, not in Statcast):**
- RBIs, Runs Scored, HRR (Hits+Runs+RBIs) — future work

### Model Architecture
- **One regression model per prop** (9 models total, NOT one per line)
- Predict actual value → apply any line threshold at runtime
- More data-efficient than binary per-line models
- Consistent with plan to eventually apply same approach to NBA

---

## Completed Steps

- [x] Requirements fixed for Python 3.13 compatibility
- [x] Statcast hitting + pitching ingest pipeline
- [x] FanGraphs ingest — made non-fatal (403 graceful degradation)
- [x] Silver layer (daily aggregates)
- [x] Gold layer (rolling features + opponent strength)
- [x] DuckDB schema + upsert helpers
- [x] `backfill.py` with `--resume` and `--force` flags
- [x] Label layer (`labels/compute_labels.py`)
- [x] `hitter_labels` and `pitcher_labels` DuckDB tables
- [x] `backfill_labels.py` standalone label backfiller
- [x] 2024 full season data + labels ingested and verified
- [x] 2025 season backfill IN PROGRESS (running now)

---

## Next Steps (in order)

### Step 1 — Finish 2025 backfill + labels (running now)
Once the `backfill.py` command finishes:
```bash
python backfill_labels.py --start 2025-03-27 --end 2025-09-28
```
Then verify:
```bash
python -c "
import duckdb
conn = duckdb.connect('data/mlb.duckdb')
for t in ['hitter_labels','pitcher_labels']:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    r = conn.execute(f'SELECT MIN(game_date), MAX(game_date) FROM {t}').fetchone()
    print(f'{t}: {n:,} rows | {r[0]} -> {r[1]}')
conn.close()
"
```
**Expected:** ~95k hitter_labels, ~40k pitcher_labels, coverage 2024-04-01 to 2025-09-28.

### Step 2 — Build Standalone Streamlit Dashboard
- File: `mlb_feature_store/dashboard.py`
- Port: **8503** (doesn't conflict with existing dashboards on 8501/8502)
- Run: `streamlit run dashboard.py --server.port 8503`
- This is **local only** — NOT connected to Supabase or the main cloud dashboard
- Tabs to build:
  1. **Data Explorer** — query DuckDB, filter by player/date/prop, view raw labels
  2. **Player Profile** — rolling feature trends for a specific player
  3. **Label Distribution** — hit rate by prop/line (sanity checking)
  4. **Model Performance** (placeholder until ML module built)

### Step 3 — Build ML Training Module
- Directory: `ml/`
- Files:
  - `ml/train.py` — trains one regression model per prop
  - `ml/evaluate.py` — calibration curves, MAE, probability accuracy per line
  - `ml/predict.py` — given today's starters/batters, output predictions per prop
- Model: **XGBoost regressor** (same library already used in main SportsPredictor)
- Training data: join `player_features` + `hitter_labels` on (player_id, date)
- **Starter filter for pitcher models:** `WHERE outs_recorded >= 9`
- Save models to `ml/models/{prop_name}.pkl`

### Step 4 — Daily Prediction Output (future)
- Run `ml/predict.py` each morning to generate today's prop predictions
- Output CSV or DuckDB table with player, prop, predicted_value, line, edge
- Eventually wire into orchestrator and Supabase sync

---

## Key Commands

```bash
# All commands from: C:\Users\thoma\SportsPredictor\mlb_feature_store\

# Run daily pipeline for a specific date
python run_daily.py --date 2025-09-01

# Backfill a date range
python backfill.py --start 2025-03-27 --end 2025-09-28

# Resume from last DuckDB checkpoint
python backfill.py --resume

# Re-fetch hitting parquets (e.g. after schema column changes)
python backfill.py --start 2024-04-01 --end 2024-10-01 --force

# Backfill labels only (reads existing parquets, no API calls)
python backfill_labels.py --start 2025-03-27 --end 2025-09-28

# Launch analysis dashboard (once built)
streamlit run dashboard.py --server.port 8503
```

---

## Important Gotchas

1. **FanGraphs 403** — Non-fatal. Pipeline continues without season-level wRC+/WAR. Opponent strength features will be empty (NULLs in player_features). This is acceptable — Statcast features alone are sufficient for ML.

2. **Pitcher labels include relievers** — `pitcher_labels` stores ALL pitchers. For PrizePicks K/outs models, always filter: `WHERE outs_recorded >= 9` to isolate starters.

3. **`pitcher` column was added mid-project** — Parquets fetched before 2026-04-13 may lack the `pitcher` column and produce empty pitcher_labels. Re-fetch with `--force` if pitcher_labels come back empty for a date range.

4. **DuckDB single-writer** — Only one process can write to `mlb.duckdb` at a time. If backfill is running, don't run dashboard or other scripts that write to DuckDB simultaneously.

5. **Global Python env** — This project uses `requirements.txt` with `>=` pins. Do NOT pin exact versions — it will downgrade Supabase/NBA packages in the shared global environment.

6. **Separate from orchestrator** — Do NOT add mlb_feature_store to `start_orchestrator.bat` yet. It runs manually or via its own bat file when ready.
