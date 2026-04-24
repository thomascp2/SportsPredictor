# Session Handoff — Apr 24 2026 (Game Lines Fix)

## What We Did

Fixed the MLB game line prediction pipeline end-to-end. Four commits pushed to master.

### Commits (in order)
1. `77e86a35` — Fix MLB Elo ratings: alias normalization, initial build, grader hook
2. `d2711eb2` — Wire SP data and refresh team stats into pipeline
3. `c9c6dc98` — Incorporate SP ERA into predicted total formula
4. `8641e249` — Add SP_WEIGHT calibration, error guards, calibration notes

---

## Root Causes Fixed

### 1. Elo stuck at 0.535 for every team
- `elo_ratings_mlb.json` never existed — `load()` returned False silently
- **Fix**: Added `TEAM_ALIASES` dict to `elo_engine.py` (AZ→ARI, SD→SDP, SF→SFG, TB→TBR, KC→KCR, CWS→CHW, ATH→OAK), ran initial build from 289 scored games, hooked `update_elo_ratings()` into grader

### 2. team_rolling_stats stale since Apr 5 (2-3 games per team)
- MIL `rapg=7.5` from 2 games was the direct cause of 90% OVER predictions
- **Fix**: Ran `--rebuild`, wired `team_stats_collector --rebuild` into `grade_game_predictions.py` Step 1c. Orchestrator also calls `run_team_stats_update()` at 7:30 AM daily — was already wired, just needed to be running.

### 3. SP ERA not wired to feature extractor
- `game_context` has starters. `fetch_todays_games()` was dropping them. `_add_pitcher_stats()` received `None` for both starters every time.
- **Fix**: `MLBGameFeatureExtractor.extract()` now auto-looks up starters from `game_context` when not provided.

### 4. SP ERA not affecting predicted total
- `gf_predicted_total` formula was pure team RPG/RAPG average — SP ERA was stored in features_json but never used in the calculation.
- **Fix**: When SP data available, adjusts each team's expected runs by their opponent's SP quality relative to league average (ERA/4.00), with SP_WEIGHT=0.50.

---

## Current State of Today's Picks (Apr 24)

MIL/PIT OVER 7.0 journey:
- Before any fixes: 90.0% (stale 2-game rapg=7.5, no Elo, no SP)
- After team stats + Elo: 81.8% (fresh rapg=4.94, Skenes ERA=2.09 in features but not used)
- After SP formula fix: 71.3% (predicted total 8.8 vs market 7.0)

Model still disagrees with market by 1.8 runs. Skenes is legitimately elite (2.09 ERA, K/9=10.5 over 51.7 IP) but market prices him even higher. The SP_WEIGHT=0.50 may underweight elite aces — calibrate when we have 500+ graded totals with SP data (~Aug 2026).

---

## Known Limitation / Next Action

**SP_WEIGHT calibration**: `python mlb/features/game_features.py --calibrate`
- Currently returns `NOT READY` (0 graded total rows with SP data)
- Check again ~Aug 2026
- If improvement >= 0.10 RMSE vs baseline, update `SP_WEIGHT` in `game_features.py`
- Elite ace tier (ERA < 2.50, K/9 > 11) may warrant weight 0.60–0.65 — add K/9 tier logic then

**Orchestrator stability**: As long as orchestrator runs continuously, the loop is closed:
- 3:15 AM: `grade_game_predictions.py` → grades + updates Elo + rebuilds team stats
- 7:30 AM: `run_team_stats_update()` — incremental team stats + Elo (belt-and-suspenders)
- 9:45 AM: `generate_game_predictions.py` — fresh predictions with current SP, stats, Elo

---

## Files Changed This Session
- `shared/elo_engine.py` — TEAM_ALIASES, alias normalization in process_games_from_db
- `mlb/database/elo_ratings_mlb.json` — initial build (289 games, all 30 teams)
- `mlb/scripts/grade_game_predictions.py` — Elo update + team stats rebuild hooks
- `mlb/features/game_features.py` — starter auto-lookup, SP ERA in total formula, calibration method

---

## Evening Session — Task Scheduler + Data Integrity (Apr 24)

### What Was Added

**1. Starter context always refreshed on every run**
`generate_game_predictions.py` now calls `GameScheduleFetcher.fetch_and_save()` unconditionally before the `already_predicted` guard. `game_context` is always current regardless of whether predictions are regenerated. Rule: clean data, always, non-negotiable (the NHL/NBA lesson applied).

**2. Pre-game odds locked once a game goes live**
`shared/fetch_game_odds.py` reads ESPN's `status.type.state` per game:
- `pre` → `INSERT OR REPLACE` (lines update freely)
- `in` / `post` → `INSERT OR IGNORE` (pre-game line locked in place)

`mlb/scripts/fetch_game_schedule.py` applies the same gate to `game_context` — skips context refresh for any game ESPN reports as live or final.

Why: a re-run later in the day (e.g. west coast schedule) would otherwise pull volatile in-game odds for noon games that have already started. Live odds are meaningless for pre-game predictions.

**3. Task Scheduler wired up**
Game lines pipeline now runs daily at **9:30 AM CST** via Windows Task Scheduler. Runs as user `thoma` (not SYSTEM — needed for correct Python paths and Defender exclusions).

Entry point is a wrapper bat, not the Python script directly:
- **Wrapper:** `C:\Users\thoma\SportsPredictor\run_game_lines.bat`
- **Log:** `C:\Users\thoma\SportsPredictor\logs\game_lines_YYYYMMDD.log`

TS task config:
- Program: `C:\Users\thoma\SportsPredictor\run_game_lines.bat`
- Arguments: *(empty)*
- Start in: `C:\Users\thoma\SportsPredictor\mlb\scripts`

### Verified Working (18:24 CST)
Log confirmed full run. Odds lock fired correctly — 6 games already started were skipped on context refresh, 8 evening games updated. `already_predicted` guard exited cleanly (no --force).

### Files Added/Changed
- `mlb/scripts/generate_game_predictions.py` — schedule refresh moved above already_predicted guard
- `shared/fetch_game_odds.py` — game_started flag + INSERT OR IGNORE for live/final games
- `mlb/scripts/fetch_game_schedule.py` — skip context update for live/final games
- `run_game_lines.bat` — TS wrapper (env vars, log redirect)
- `logs/` — daily execution logs directory

### Architecture Note
Game lines is **standalone** — not part of apex-arb, not part of run_daily_v2.py. Intentional. Different data source, different timing, different purpose. Blast radius isolation: if props break, game lines still runs, and vice versa.
