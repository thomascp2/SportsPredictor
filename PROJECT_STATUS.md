# FreePicks / SportsPredictor — Project Status

> Last updated: 2026-04-01  
> Branch: `claude/add-golf-module-UybTP`

---

## What This Is

A dual-sport (NHL + NBA) player prop prediction engine expanding into MLB and Golf.
Predictions are generated daily by ML models (19 trained, live since Feb 23 2026),
graded automatically, and surfaced to users via a Streamlit cloud dashboard and
a React Native mobile app (FreePicks). A game lines module (moneyline/spread/totals)
is running in statistical baseline mode for NHL, NBA, and MLB.

**Revenue model:** FreePicks Plus subscription + sportsbook affiliates. Currently
in data-collection / pre-launch phase.

---

## System Architecture

```
Orchestrator (orchestrator.py)
  ├── NHL  → grade 3AM → predict 4AM → pp-sync 1PM → game-lines 9AM
  ├── NBA  → grade 5AM → predict 6AM → pp-sync 12:30PM → game-lines 9:30AM
  ├── MLB  → grade 8AM → predict 12PM → pp-sync 3PM → game-lines 9:45AM
  └── GOLF → grade 8AM → predict 10AM → pp-sync 12PM

Prediction pipeline:
  PrizePicks lines → feature engineering → ML models (60%) + statistical (40%)
  → smart pick selector → SQLite → Supabase sync → dashboard / mobile app

Databases (local SQLite):
  nhl/database/nhl_predictions_v2.db
  nba/database/nba_predictions.db
  mlb/database/mlb_predictions.db
  golf/database/golf_predictions.db

Cloud: Supabase (txleohtoesmanorqcurt, us-east-1)
  Tables: daily_props, user_picks, user_bets, profiles, watchlist, daily_games
```

---

## ML Model Status

| Sport | Models | Last Trained | Avg Accuracy | Prediction Count |
|-------|--------|-------------|--------------|-----------------|
| NBA | 14 | 2026-03-15 | ~80% | 180,016 |
| NHL | 5 | 2026-03-15 | ~68% | 62,183 |
| MLB | 0 | — | — | 6,859 (data collection) |
| GOLF | 0 | — | — | 212 (data collection) |

- **Learning mode:** OFF for NHL + NBA. ON for MLB + Golf.
- **ML target:** 7,500 graded samples per prop/line combo before training
- **Auto-retrain:** Every Sunday — NHL 3:30AM, NBA 5:30AM, MLB 8:30AM CST

---

## Session History — What Was Built

### Apr 1, 2026
- Fixed home-team bias in game lines (`game_statistical_baseline.py`) — was triple-counting home advantage
- Moved game prediction schedule before 10AM (NHL 9:00, NBA 9:30, MLB 9:45)
- Added new ML features to all sport extractors: raw Elo ratings, momentum (L5 vs season), L5 scoring
- Added prop/player/team checkbox filters to Today's Picks dashboard tab
- Added live orchestrator health monitor to System tab (terminal-style, auto-refreshes 60s)
- Redesigned Game Lines tab with HTML game cards (inline styles, probability bars, tier badges)
- Fixed badge rendering bug — Streamlit strips CSS class names with uppercase letters
- Created this PROJECT_STATUS.md and todo list

### Mar 29, 2026
- Wired Golf into live pipeline, added Golf dashboard tab
- Fixed partial in-progress round score grading bug (ESPN API)

### Mar 15, 2026
- Trained v20260315_001 models — all 19 models improved
- Added NBA threes OVER guard (model degenerate — always picks UNDER)
- Extended backfill to include full 2025 PGA Tour season

### Mar 8–9, 2026
- Goblin/Demon tier fix — tier now based on edge above break-even not raw probability
- Calibration architecture fix — 4-way temporal split (train/val/cal/test)
- Added NHL hits + blocked shots props
- Fixed Unicode print encoding (Windows cp1252 kills sync mid-run)

### Mar 3–6, 2026
- Fixed team assignment bug (traded players appearing on old team)
- Fixed ai_edge break-even bug (312 NHL + 1,179 NBA rows corrected)
- MLB branch added, season started Mar 27

---

## Open Todo List

| # | Task | Priority | Depends On |
|---|------|----------|-----------|
| 2 | `daily_audit.py` — automated DB health + Discord report | HIGH | — |
| 3 | Add `profit` column to all grading scripts (ROI foundation) | **HIGHEST** | — |
| 4 | Grok live-web intel — line movement, injury news before predictions | HIGH | — |
| 5 | Unify NHL/NBA/MLB `prediction_outcomes` column names | HIGH | — |
| 6 | Investor P&L dashboard section (unit P&L chart, Kelly sim) | HIGH | Task 3 |
| 7 | Consolidate 12+ duplicate config variable definitions | MEDIUM | — |
| 8 | Delete dead V5 scripts + `_old` feature extractor files | LOW | — |
| 9 | Consistent theme tokens across all dashboard tabs | LOW | — |

**Start with Task 3.** Once `profit` is written by grading scripts, Tasks 2, 4, and 6
all become straightforward reads from that data. It's the one dependency that unlocks everything.

---

## Known Issues / Tech Debt

### Critical
- **No profit tracking in grading** — NHL/NBA/MLB `prediction_outcomes` have no `profit` column.
  Can't compute ROI, can't prove profitability to investors.
- **Schema column name mismatch** — NHL uses `predicted_outcome` + `actual_stat_value`;
  NBA/MLB use `prediction` + `actual_value`. Every cross-sport query needs conditionals.
  Lives in `shared/canonical_schema.py` as a mapping but it's a maintenance burden.

### Medium
- **12+ duplicate DB_PATH/config definitions** — DB_PATH defined independently in every sport
  config, sync config, API config, and some scripts. One source of truth needed.
- **`performance_dashboard.py` has hardcoded paths to old projects** —
  `C:\Users\thoma\NHL-Model-Rebuild-V2` doesn't exist. Dashboard is broken.
- **Golf + MLB consecutive_failures = 3** in orchestrator_state.json —
  need to investigate what's failing.

### Low
- Dead files: `nhl/scripts/generate_predictions_daily_V5.py`, `nhl/features/*_old.py` (3 files)
- `SELECT *` in 68 files — fragile against schema changes
- Path mixing: some files use `Path()`, others use `os.path.join()`

---

## Investor Readiness Checklist

- [ ] **Profit column in grading** — prerequisite for all ROI metrics
- [ ] **Cumulative unit P&L chart** — show growth from day 1 to today
- [ ] **Win rate by tier** — PRIME/SHARP/LEAN/PASS breakdown with sample sizes
- [ ] **Kelly bankroll growth simulation** — what $1000 becomes with our picks
- [ ] **Comparison vs coin-flip baseline** — prove we beat random
- [ ] **Model calibration proof** — predicted prob vs actual hit rate (calibration curve)
- [ ] **Out-of-sample backtest** — results on data the model never trained on
- [ ] **Mobile app demo** — TestFlight build for investor demo
- [ ] **OAuth configured** — blocks device testing (Google + Apple + Discord OAuth needed)

---

## How to Run

```bash
# Start orchestrator (continuous mode, all sports)
start_orchestrator.bat

# Start dashboard (port 8502 via Cloudflare tunnel)
streamlit run dashboards/cloud_dashboard.py --server.port 8502

# Manual operations
python orchestrator.py --sport nhl --mode once --operation prediction
python orchestrator.py --sport nba --mode once --operation grading
python orchestrator.py --sport all --mode once --operation game-prediction

# Discord bot
start_bot.bat
```

---

## Key File Map

```
orchestrator.py              — master scheduler, all sports
shared/
  game_prediction_engine.py  — moneyline/spread/total predictions
  game_statistical_baseline.py — statistical model (home bias fixed Apr 1)
  smart_pick_selector.py     — filters picks by edge, tier, odds_type
  pregame_intel.py           — Grok API for injury/goalie context
  elo_engine.py              — Elo ratings for all sports
nhl/scripts/
  generate_predictions_daily_V6.py  — ACTIVE prediction script
  v2_auto_grade_yesterday_v3_RELIABLE.py — ACTIVE grading script
nba/scripts/
  generate_predictions_daily_V6.py  — ACTIVE
  auto_grade_multi_api_FIXED.py     — ACTIVE
sync/
  supabase_sync.py           — SQLite → Supabase bridge
dashboards/
  cloud_dashboard.py         — main dashboard (Streamlit, port 8502)
ml_training/
  train_models.py            — prop model training
  train_game_models.py       — game lines model training
```
