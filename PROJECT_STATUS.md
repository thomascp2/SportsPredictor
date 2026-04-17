# FreePicks / SportsPredictor — Project Status

> Last updated: 2026-04-11  
> Branch: `main`

---

## What This Is

A multi-sport (NHL, NBA, MLB, Golf) player prop and game line prediction engine.
Prop predictions are driven by an ensemble of ML models (19 trained) and statistical baselines.
Game lines (Moneyline/Spread/Total) currently run on a calibrated statistical baseline (Elo-driven).

**Core Strategy:** Replicating the "High-Volume/Low-Variance" success of the NHL models (68%+ accuracy) across all sports by porting its "Secret Sauce" (usage-weighted features and opponent performance analysis).

---

## Strategic Roadmap (Phase 3+)

### **1. The ROI Foundation (HIGHEST PRIORITY)**
*   [ ] **Profit Column:** Add `profit` to all prop and game grading tables to track actual unit P&L.
*   [ ] **CLV Capture:** Add `closing_line` and `closing_odds` to game predictions to measure Closing Line Value (the gold standard of sharp betting).
*   [ ] **Daily Audit:** Automated Discord report covering DB health, feature completeness, and daily ROI.

### **2. Porting the "NHL Secret Sauce"**
*   [ ] **MLB Matchup Quality:** Implement NHL-style features analyzing how many stats the *opponent lineup* allows to average pitchers.
*   [ ] **MLB Fatigue Signal:** Add "Day After Night" (DAN) features for batters.
*   [ ] **NFL Usage-Weighting:** Focus on high-frequency props (Targets/Receptions) over high-variance events (TDs).

### **3. ML Training Timelines**
*   [ ] **NBA/NHL Retraining Freeze:** Effective April 2026 — lock in current models to avoid late-season "tanking" noise.
*   [ ] **MLB Alpha Training:** Target **July 15, 2026** (Post All-Star Break) for first production ML models.
*   [ ] **NFL Training:** Data collection Weeks 1-4; Initial training **Week 5 (October 2026)**.
*   [ ] **Game Line ML:** Target **October 2026** for NHL/MLB game line models once datasets reach 1,500+ games.

### **4. After Action Reviews (AAR)**
*   [ ] **NBA AAR:** Audit "misleading" hit rates vs actual profitability. Segment performance by prop type to identify "sketchy" vs "solid" predictors.

---

## System Architecture

```
Orchestrator (orchestrator.py)
  ├── NHL  → grade 3AM → predict 4AM → pp-sync 1PM → game-lines 9AM
  ├── NBA  → grade 5AM → predict 6AM → pp-sync 12:30PM → game-lines 9:30AM
  ├── MLB  → grade 8AM → predict 10AM → pp-sync 3PM → game-lines 9:45AM
  └── GOLF → grade 8AM → predict 10AM → pp-sync 12PM

Databases:
  nhl/database/nhl_predictions_v2.db
  nba/database/nba_predictions.db
  mlb/database/mlb_predictions.db
  golf/database/golf_predictions.db
```

---

## ML Model Status

| Sport | Models | Last Trained | Avg Accuracy | Prediction Count | Status |
|-------|--------|-------------|--------------|-----------------|--------|
| NHL | 5 | 2026-03-15 | ~68% | 62,183 | **FROZEN** (Stable) |
| NBA | 14 | 2026-03-15 | ~58% (Recent) | 180,016 | **FROZEN** (High Variance) |
| MLB | 0 | — | — | 6,859 | Data Collection |
| GOLF | 0 | — | — | 212 | Data Collection |

---

## Open Todo List

| # | Task | Priority | Status |
|---|------|----------|--------|
| 1 | Add `profit` column to grading | **HIGHEST** | Pending |
| 2 | Add `closing_line` to game predictions | **HIGHEST** | Pending |
| 3 | `daily_audit.py` Discord report | HIGH | Pending |
| 4 | NBA After Action Review | HIGH | Pending |
| 5 | MLB "NHL-Style" Feature Port | MEDIUM | Pending |

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
