# CLAUDE.md

## What This Is

**4-sport prop prediction system** (NHL, NBA, MLB, Golf) feeding FreePicks — a consumer-facing picks app backed by Supabase + Expo React Native. The prediction engine runs locally on Windows (Git Bash), syncs to Supabase + Turso (cloud), and serves picks via a Streamlit dashboard and Discord bot.

---

## Sports Status (as of Apr 20, 2026)

| Sport | Mode | ML Active? | Notes |
|-------|------|-----------|-------|
| NHL | Statistical only | No | `MODEL_TYPE="statistical_only"` in `v2_config.py`. Season ~ended Apr 18. |
| NBA | Statistical only | No | `LEARNING_MODE=True` in `nba_config.py`. Reverted Apr 5 — Mar 15 retrain wrecked UNDER (83%→47%). Retrain Oct 2026. |
| MLB | Statistical only | No | `MODEL_TYPE="statistical_only"` in `mlb_config.py`. XGBoost feature store runs daily (mlb_feature_store/) but is not wired into live picks. Flip to ensemble at ~50K graded rows (~Aug 2026). |
| Golf | Statistical only | No | No ML scaffolding. Scaffold post-season when samples hit 700+/prop. |

**Do NOT flip any of these ML flags without a full retrain review.**

---

## Core Architecture

### Databases (SQLite, local)
- `nhl/database/nhl_predictions_v2.db`
- `nba/database/nba_predictions.db`
- `mlb/database/mlb_predictions.db`
- `golf/database/golf_predictions.db`

Each has: `predictions`, `prediction_outcomes`, `player_game_logs`. NHL/NBA/MLB also have `game_predictions`, `game_prediction_outcomes`.

**Critical column differences:**
- NHL features: JSON blob in `features_json`
- NBA features: individual `f_*` columns (50+)
- Both sports: outcomes use `prediction` column (not `predicted_outcome` — that's wrong in old docs)

### Turso (cloud SQLite)
Each sport has its own Turso DB. Synced via `sync/turso_sync.py`. Dashboard reads Turso first, falls back to local SQLite.

Operations: `predictions`, `smart-picks`, `grading`, `game-predictions`, `game-outcomes`

```bash
python -m sync.turso_sync --sport mlb --operation all --date 2026-04-20
```

### Supabase (PostgreSQL, cloud)
Consumer-facing. Key table: `daily_props` (bridges prediction engine → FreePicks users).
- Ref: `txleohtoesmanorqcurt` | Region: us-east-1
- `sport` column stores UPPERCASE: `'NBA'`, `'NHL'`, `'MLB'`
- Default query cap: 1000 rows — use `.range(offset, offset+999)` loop for batch ops
- Sync: `sync/supabase_sync.py` (one-directional SQLite → Supabase)

### Orchestrator (`orchestrator.py`)
Master controller. Launched via `start_orchestrator.bat` in continuous mode.

```bash
python orchestrator.py --sport all --mode continuous   # production
python orchestrator.py --sport nba --mode once --operation prediction
python orchestrator.py --sport nba --mode once --operation grading
python orchestrator.py --sport nba --mode once --operation pp-sync
```

**DO NOT manually run** `sync_odds_types` or `sync_game_times` — both wired into orchestrator.

**pp-sync** = re-fetch PP lines, re-match smart picks, update Supabase. Writes NO new SQLite rows. Safe to repeat anytime. Discord: `!refresh [nba|nhl|both]`

### Daily Schedule (approximate CST)
- **3–5 AM**: Grade yesterday (NHL/NBA)
- **4–6 AM**: Generate today's predictions (NHL/NBA)
- **9–10 AM**: MLB predictions + feature store + game predictions
- **12:30–1 PM**: pp-sync (NBA/NHL) — re-fetch PP lines, update Supabase
- **2 PM**: Top-20 Discord post (NHL + NBA)
- **Sunday 3:30/5:30/8:30 AM**: Auto-retrain NHL/NBA/MLB (skips if <500 new predictions)

---

## Key Scripts (current, use these)

```bash
# NHL
nhl/scripts/generate_predictions_daily_V6.py
nhl/scripts/v2_auto_grade_yesterday_v3_RELIABLE.py

# NBA
nba/scripts/generate_predictions_daily_V6.py
nba/scripts/auto_grade_multi_api_FIXED.py

# MLB
mlb/scripts/generate_predictions_daily.py
mlb/scripts/auto_grade_yesterday.py
mlb/scripts/generate_game_predictions.py

# Golf
golf/scripts/generate_predictions_daily.py
```

For a specific date (orchestrator defaults to yesterday for grading):
```bash
cd nhl && python scripts/generate_predictions_daily_V6.py 2026-04-20 --force
cd nba && python scripts/auto_grade_multi_api_FIXED.py 2026-04-19
```

---

## Dashboard (`dashboards/cloud_dashboard.py`)

- Port **8502** via Cloudflare tunnel (`C:\Users\thoma\cloudflared.exe`) — URL changes on restart
- Tabs: **Top Plays | NHL | NBA | MLB | Golf | StatBot | Performance | System**
- Reads Turso first, falls back to local SQLite for all data
- MLB StatBot section: reads XGBoost ML predictions from `mlb_feature_store/data/mlb.duckdb` (populated daily at 10:30 AM by `ml.predict_to_db`)

---

## Sync Architecture (data flow)

```
PP Lines → SmartPickSelector → SQLite (predictions.odds_type updated)
                             → Supabase (daily_props)
                             → Turso (predictions + smart-picks)
```

Break-even values (keep in sync across `smart_pick_selector.py` and `supabase_sync.py`):
- standard: 0.5238 | goblin: 0.7619 | demon: 0.4545

Tier thresholds (edge above break-even):
- T1-ELITE ≥ +19% | T2-STRONG ≥ +14% | T3-GOOD ≥ +9% | T4-LEAN ≥ 0% | T5-FADE < 0%

---

## Critical Gotchas

**Windows Defender hang**: If sklearn/scipy imports hang (processes stuck at ~193 MB, 0 output), re-add Python paths to Defender exclusions:
- `C:\Users\thoma\AppData\Local\Programs\Python\Python313\Lib\site-packages`
- `C:\Users\thoma\AppData\Local\Programs\Python\Python313\Scripts`

**Unicode in print statements**: Use ASCII only in runtime strings. `→` causes cp1252 crash. Accented player names: `.encode('ascii', 'replace').decode('ascii')` before printing.

**NHL name matching**: DB may store `A. Fox`; PP uses `Adam Fox`. `_is_initial_match()` in smart_pick_selector handles it.

**NBA threes OVER guard**: `shared/smart_pick_selector.py` skips `threes OVER` — model is degenerate (0% hit rate), guard is permanent.

**MLB feature store**: `mlb_feature_store/` is a separate DuckDB-based XGBoost system. It is NOT the same as `ml_training/`. The `ml_predictions` table covers ~320 players/pitchers — not exhaustive. Gaps (e.g. Aaron Nola missing) are data coverage issues, not bugs.

**Supabase pagination**: 1000-row cap. Always paginate with `.range()` for batch reads.

---

## Config Files (always import from these — never hardcode)

```python
from v2_config import DB_PATH, LEARNING_MODE          # NHL scripts
from nba_config import DB_PATH, LEARNING_MODE          # NBA scripts
from mlb_config import DB_PATH, MODEL_TYPE             # MLB scripts
from golf_config import DB_PATH                        # Golf scripts
```

---

## Environment Variables (set in `start_orchestrator.bat`)

- `ANTHROPIC_API_KEY` — Claude self-healing + StatBot
- `DISCORD_WEBHOOK_URL`, `NHL/NBA/MLB/GOLF_DISCORD_WEBHOOK` — sport channels
- `XAI_API_KEY` — Grok for StatBot natural language queries
- `ODDS_API_KEY` — live odds feed

---

## What NOT To Do

- Don't flip `LEARNING_MODE` or `MODEL_TYPE` without a full retrain review
- Don't manually run `sync_odds_types` or `sync_game_times` — orchestrator owns these
- Don't hardcode paths — always import from `*_config.py`
- Don't run grading before games finish
- Don't cross NHL/NBA code paths — sports are intentionally isolated
- Don't manually edit databases — use scripts
- Don't add lines to `KNOWN_EXTREME` without explicit confirmation from user
- Don't touch `parlay_lottery/` — out of scope
