# Full-Game Prediction System — Implementation Plan

## The Vision

Turn SportsPredictor into the **one-stop shop for sharp sports bettors**. Right now we have player props (PrizePicks). This adds the other half — full game lines: **moneylines, spreads, and totals** across NHL, NBA, and MLB. A sharp bettor opens the dashboard and sees everything they need for the day.

---

## Architecture: Standalone But Connected

This system runs **independently** from the props pipeline — separate scripts, separate tables, separate models. But it's **informed by** the player-level data we've been collecting:

- `player_game_logs` tables (thousands of rows per sport) feed team-level aggregations
- Existing ESPN/NHL/NBA API clients get reused for schedule + odds fetching
- `ml_training/train_models.py` pipeline gets extended (not replaced)
- Same orchestrator, same dashboard, same Discord — new tabs and commands

```
Existing Props Pipeline          New Game Lines Pipeline
─────────────────────            ──────────────────────
player stats → prop picks        team stats → game picks
  (unchanged)                      (standalone)
       │                                │
       └──── both feed ────→ Dashboard / Discord / API
                              "One-Stop Shop"
```

---

## Phase 1: Data Foundation (Weeks 1-3)

### 1A. New Database Tables

Each sport gets `game_predictions` and `game_prediction_outcomes` tables — completely separate from existing `predictions` tables.

```sql
game_predictions:
    id, game_date, game_id, home_team, away_team, venue,
    bet_type TEXT,        -- 'moneyline' | 'spread' | 'total'
    bet_side TEXT,        -- 'home' | 'away' | 'over' | 'under'
    line REAL,            -- spread value or total line
    prediction TEXT,      -- 'WIN'/'LOSE' or 'OVER'/'UNDER'
    probability REAL,
    edge REAL,            -- predicted prob minus implied prob
    confidence_tier TEXT, -- SHARP / LEAN / PASS
    features_json TEXT,
    model_version TEXT,
    created_at TEXT

game_prediction_outcomes:
    id, prediction_id, game_date, game_id,
    bet_type, bet_side, line,
    prediction TEXT,
    home_score INT, away_score INT,
    outcome TEXT,         -- HIT / MISS / PUSH
    created_at TEXT
```

### 1B. Team Stats Collectors

One per sport — nightly scheduled jobs that build rolling team profiles:

| Script | Source API | Key Stats |
|--------|-----------|-----------|
| `nhl/scripts/team_stats_collector.py` | `api-web.nhle.com` | GF/GA per game, PP%, PK%, save%, home/away splits |
| `nba/scripts/team_stats_collector.py` | `cdn.nba.com/stats` | Pace, off/def rating, eFG%, TOV%, rebound rate |
| `mlb/scripts/team_stats_collector.py` | `statsapi.mlb.com` | Team ERA, WHIP, OPS, bullpen ERA, run differential |

Player data from existing `player_game_logs` tables can be aggregated into team-level stats where possible.

### 1C. Venue & Arena Data

MLB already has `park_factors.py` with lat/lon, altitude, roof type. Create equivalents:
- `nhl/scripts/arena_data.py` — 32 NHL arenas (lat/lon, timezone, altitude)
- `nba/scripts/arena_data.py` — 30 NBA arenas (lat/lon, timezone, altitude)

These enable travel distance and timezone-crossing features.

### 1D. Elo Rating Engine

`shared/elo_engine.py` — simple, powerful, sport-agnostic:
- All teams start at 1500 each season (carry 75% from prior year)
- Update after each game with margin-of-victory multiplier
- Sport-specific home advantage baked in (NHL: +60, NBA: +100, MLB: +24)
- Elo difference alone is ~55-60% accurate — strong baseline feature

---

## Phase 2: Feature Engineering (Weeks 3-5)

### The Feature Set (~40-50 features per game)

#### Universal Features (All Sports)

| Category | Features | Count |
|----------|----------|-------|
| **Team Strength** | Win %, L10 win %, scoring avg, defense avg, net rating, Elo diff | ~10 |
| **Rest/Rotation** | Days rest, back-to-back flag, 3-in-4 flag, travel miles, rest advantage | ~8 |
| **Streaks** | Win/loss streak, ATS streak, O/U streak (home + away) | ~6 |
| **Odds-Derived** | Spread, total line, implied prob, line movement (open to close) | ~6 |
| **Matchup** | Divisional flag, conference flag, H2H record this season | ~4 |

#### Sport-Specific Features

**NHL** (~8 extra):
- Starting goalie save %, GAA (from existing goalie data)
- PP% vs opponent PK%, and vice versa
- Shots for/against differential

**NBA** (~10 extra):
- Pace of play (both teams — predicts total)
- Offensive/defensive efficiency ratings
- 3PT shooting rate, free throw rate
- Player impact: Use `player_game_logs` to detect if stars are out (biggest edge in NBA)

**MLB** (~12 extra):
- Starting pitcher ERA, WHIP, K/9 (from existing pitcher data)
- Bullpen ERA, closer save %
- Park factor (HR, runs — already in `park_factors.py`)
- Weather: temp, wind, humidity (already have `weather_client.py`)
- Altitude adjustment (already in `park_factors.py`)

#### Leveraging Existing Player Data

```python
# Example: derive team scoring from player_game_logs already collected
def get_team_scoring_avg(team, last_n_games=10):
    query = """
        SELECT game_date, SUM(points) as team_points
        FROM player_game_logs
        WHERE team = ? AND game_date >= ?
        GROUP BY game_date
        ORDER BY game_date DESC LIMIT ?
    """
```

---

## Phase 3: Models (Weeks 5-8)

### ML Algorithms (Priority Order)

| Model | Why | Library |
|-------|-----|---------|
| **XGBoost** | Best default for tabular sports data. Already in pipeline. | `xgboost` |
| **LightGBM** | Faster training, handles categoricals natively | `lightgbm` |
| **CatBoost** | Excellent with categoricals, less tuning needed | `catboost` |
| **Logistic Regression** | Mandatory baseline — ML must beat this or don't deploy | `sklearn` |
| **Stacking Ensemble** | Meta-learner combining XGB + LGBM + LR outputs | `sklearn` |

Neural networks not prioritized — dataset too small for deep learning to outperform gradient boosting.

### Three Models Per Sport

1. **Moneyline model** — binary classification (home win = 1)
2. **Spread model** — binary classification (home covers = 1)
3. **Totals model** — binary classification (over = 1)

### Training Approach

- Time-series cross-validation (never train on future data)
- Isotonic or sigmoid calibration
- Feature selection by importance threshold
- Minimum 500 training samples before deployment

### Backfill for Instant Training

Existing `games` tables have **1,100+ NHL** and **1,350+ NBA** games with final scores. Backfill scripts reconstruct features for historical games, enabling immediate ML training.

### Confidence Tiers

| Tier | Criteria | Action |
|------|----------|--------|
| **SHARP** | Edge >= 5%, model agreement >= 3/4, probability >= 60% | **BET** — highlighted |
| **LEAN** | Edge >= 2%, probability >= 55% | Shown but not highlighted |
| **PASS** | Edge < 2% or low confidence | Hidden by default |

---

## Phase 4: Pipeline Integration (Weeks 8-10)

### Orchestrator Scheduling

```python
game_prediction_time = "12:00"   # After props, after odds settle
game_grading_time = "09:00"      # Morning after

# New operations:
--operation game-prediction
--operation game-grading
--operation game-all
```

### Daily Flow

```
6:00 AM   Team stats collector runs (all sports)
8:00 AM   Prop predictions run (existing, unchanged)
9:00 AM   Game grading runs (yesterday's games)
12:00 PM  Game predictions run (today's games)
           -> Fetch schedule + odds
           -> Extract features
           -> Run models (statistical + ML)
           -> Save to game_predictions
           -> Post SHARP picks to Discord
           -> Sync to Supabase
```

---

## Phase 5: Dashboard & Delivery (Weeks 10-12)

### New Dashboard Tab: "Game Lines"

- Today's game predictions (moneyline, spread, total) with confidence tiers
- Filter by sport, bet type, SHARP-only toggle
- Historical accuracy by bet type and sport
- ROI tracking (simulated flat-unit betting)
- Model confidence distribution

### Discord Delivery

```
--- SHARP GAME PICKS — March 25, 2026 ---

NHL (3 plays)
  NYR -1.5 (+155) vs BOS | Edge: 7.2% | 62%
  COL/VGK UNDER 6.0 (-110) | Edge: 5.8% | 59%
  TOR ML (-130) vs DET | Edge: 5.1% | 64%

NBA (2 plays)
  MIL -4.5 (-110) vs CHA | Edge: 6.1% | 61%
  GSW/PHX OVER 228.5 (-105) | Edge: 4.9% | 58%

L30 Record: 58% (250/432) | +27.5 units
```

---

## Phase 6: Advanced Features (Ongoing)

| Feature | Impact | Difficulty | Priority |
|---------|--------|------------|----------|
| **Injury impact scoring** | HIGH (esp NBA) | Medium | 1st |
| **Line movement tracking** | HIGH | Low (Odds API) | 2nd |
| **Referee/umpire tendencies** | MEDIUM | Medium | 3rd |
| **Public betting %** | MEDIUM | Needs paid API | 4th |
| **Coach tendencies** | LOW-MED | Hard (manual data) | 5th |
| **Live in-game model** | HIGH | Very hard | Future |

---

## Data Sources (All Free to Start)

| Source | Already Have? | Data |
|--------|:---:|------|
| ESPN hidden API | Yes | Odds, scores, schedule |
| NHL API (`api-web.nhle.com`) | Yes | Team/goalie stats, schedule |
| NBA Stats API | Yes | Advanced stats, pace, ratings |
| MLB Stats API | Yes | Pitcher stats, boxscores |
| Open-Meteo (weather) | Yes | MLB weather (free, no key) |
| Park Factors | Yes | MLB venue effects |
| Player Game Logs | Yes | Feed into team aggregations |
| The Odds API | Yes (free tier) | Multi-book odds, line movement |

---

## New File Map

```
shared/
    elo_engine.py                    -- Elo ratings (all sports)

nhl/
    scripts/
        arena_data.py                -- 32 arenas with coordinates
        team_stats_collector.py      -- Nightly team stats
        generate_game_predictions.py -- Daily game picks
        grade_game_predictions.py    -- Grade game outcomes
        backfill_game_features.py    -- Historical feature backfill
    features/
        game_features.py             -- NHL game feature extractor

nba/
    scripts/
        arena_data.py                -- 30 arenas with coordinates
        team_stats_collector.py      -- Nightly team stats
        generate_game_predictions.py -- Daily game picks
        grade_game_predictions.py    -- Grade game outcomes
        backfill_game_features.py    -- Historical feature backfill
    features/
        game_features.py             -- NBA game feature extractor

mlb/
    scripts/
        team_stats_collector.py      -- Nightly team stats
        generate_game_predictions.py -- Daily game picks
        grade_game_predictions.py    -- Grade game outcomes
        backfill_game_features.py    -- Historical feature backfill
    features/
        game_features.py             -- MLB game feature extractor

ml_training/
    train_models.py                  -- EXTEND: game prediction support

dashboards/
    cloud_dashboard.py               -- EXTEND: Game Lines tab

orchestrator.py                      -- EXTEND: game ops + scheduling
```

---

## Bottom Line

- **Standalone pipeline** — doesn't touch the props system
- **Leverages existing player data** where it gives an edge
- **Reuses infrastructure** — same orchestrator, dashboard, Discord, APIs
- **Sharp-bettor focused** — only surfaces high-edge plays
- **Buildable incrementally** — statistical baseline Day 1, ML layers on as data accumulates
