# Session: Game Lines Inflated Probabilities — Root Cause & Fix
**Date:** 2026-04-05  
**Status:** NBA/NHL fixed. MLB game lines pipeline needs audit before use.

---

## Problem
Game Lines dashboard showed 99.8%, 98.2%, 92.6% probabilities against the spread for NBA games. For context, spread bets are priced at -110 (~52.4% implied), so valid model probabilities should sit in the 45–80% range for most games.

---

## Root Causes (Three Compounding Bugs)

### Bug 1 — Corrupted ELO Ratings (PRIMARY)
- **File:** `nba/database/elo_ratings_nba.json`
- **Problem:** ELO was built from early 2024-25 season data (511 games, last updated 2025-01-06). That game data had wrong/inverted scores. OKC showed ELO=1200 (worst tier), UTA showed ELO=1622 (top tier). Completely backwards.
- **Effect:** `gf_elo_home_prob` for OKC vs UTA = 0.1357 (13.6%). The model thought OKC would lose.
- **Fix:** Rebuilt ELO from 2025-26 games only (`elo.ratings = {}` then `process_games_from_db(db, season='2025-26')`). OKC now 1557, UTA now 1435.

### Bug 2 — No Season Filter in Team Stats Collector (PRIMARY)
- **File:** `nba/scripts/team_stats_collector.py`
- **Problem:** `get_team_games()` and `get_opponent_scoring()` had no season date filter. The `games` table has a 14-month gap (Jan 2025 – Feb 2026) with only Oct-Dec 2024 old data + Mar-Apr 2026. The "season" window mixed old corrupted data with new. OKC showed win_pct=0.1714, point_diff=-11.57. UTA showed win_pct=0.7273, point_diff=+6.7. Completely inverted.
- **Fix:** Added `SEASON_START_DATE = "2025-10-01"` constant and `season_start` parameter to both query functions. `update_team()` now passes it. Rebuilt with `--rebuild`.

### Bug 3 — Sign Error in Spread→Probability Approximation
- **File:** `shared/fetch_game_odds.py` (line ~188)
- **Problem:** When no moneyline is available, ESPN spread is used to estimate `home_implied_prob`. Convention: negative spread = home is favored. The formula was `0.50 + spread * 0.03` — so OKC home at -24.5 gave 0.50 + (-24.5)*0.03 = -0.235 → clamped to 0.15. Should be the opposite.
- **Fix:** Changed to `0.50 - spread * 0.03`. Same fix applied for NHL.
- **Note:** This column wasn't actually used by the feature extractor (only `home_moneyline` was), so this bug's impact was limited to the stored `game_lines.home_implied_prob` column. But it's corrected for future use.

### Bonus Fix — NBA Moneylines Never Fetched
- **File:** `shared/fetch_game_odds.py`
- **Problem:** ESPN summary endpoint (which has moneylines) was only fetched for NBA when `over_under is None`. ESPN scoreboard gives over/under but not moneylines. So moneylines were never fetched for NBA, and `gf_home_implied_prob` always defaulted to 0.5.
- **Fix:** Changed condition to `odds_data.get("home_ml") is None` — now always fetches summary when moneyline is missing.

### Bonus Fix — Duplicate Rows on Re-run
- **File:** `shared/game_prediction_engine.py`
- **Problem:** `save_predictions()` used `INSERT OR REPLACE` but the table PK is auto-increment `id`. The UNIQUE constraint on `(game_date, home_team, away_team, bet_type, bet_side, line, model_version)` was added to the schema file but never applied to the existing table (SQLite `CREATE TABLE IF NOT EXISTS` doesn't alter). Result: every `--force` run appended new rows instead of replacing.
- **Fix:** Added explicit `DELETE FROM game_predictions WHERE game_date=? AND home_team=? AND away_team=?` before inserting, inside `save_predictions()`.

---

## Results After Fix
| Game | Bet | Before | After |
|------|-----|--------|-------|
| UTA @ OKC | spread away +24.5 | 99.8% | 46.0% |
| IND @ CLE | spread away +16.5 | 98.2% | 42.8% |
| TOR @ BOS | spread away +9.5 | 96.4% | ~55% |

Probabilities now in realistic range. Large-spread games correctly show ~50% (efficient market).

---

## Files Changed
1. `shared/fetch_game_odds.py` — sign fix + always fetch moneylines
2. `shared/game_prediction_engine.py` — delete-before-insert in save_predictions
3. `nba/scripts/team_stats_collector.py` — SEASON_START_DATE constant + season_start param

---

## What Still Needs Work (MLB Priority)

### MLB Game Lines Pipeline Audit Needed
MLB is starting data collection now (April 2026). Before running game predictions:

1. **Create `mlb/scripts/team_stats_collector.py`** (or equivalent) with season filter baked in from day 1. Use `SEASON_START_DATE = "2026-03-01"`.
2. **Verify `mlb/features/game_features.py`** has the correct feature keys (`gf_home_run_diff`, not `gf_home_point_diff` or `gf_home_goal_diff`). The statistical baseline in `shared/game_statistical_baseline.py` checks `gf_home_goal_diff → gf_home_point_diff → gf_home_run_diff` in fallback order.
3. **MLB ELO**: Start fresh. After 2+ weeks of games run `python shared/elo_engine.py --sport mlb --db mlb/database/mlb_predictions.db` to build ratings.
4. **MLB moneylines**: ESPN run-line spread for MLB is almost always 1.5 (not a point spread). The moneyline is the real signal for MLB. Verify `fetch_game_odds.py` fetches MLB moneylines correctly from the summary endpoint.
5. **`generate_game_predictions.py`** for MLB exists at `mlb/scripts/generate_game_predictions.py`. Audit it mirrors the NBA version's fixes above.
6. **`game_lines` table**: May not exist yet in `mlb/database/mlb_predictions.db`. Run `python shared/game_prediction_schema.py` to initialize.

### NHL (end of season — low priority)
Same data gap issue exists for NHL. Not worth fixing for the last ~2 weeks of the season. Revisit October 2026 when next season starts.

---

## How to Rebuild After Data Gaps
Whenever the `games` table has a gap (system offline, vacation, etc.):
```bash
# 1. Rebuild team stats (NBA example)
python nba/scripts/team_stats_collector.py --rebuild

# 2. Rebuild ELO
python -c "
import sys; sys.path.insert(0,'shared')
from elo_engine import EloEngine
elo = EloEngine(sport='nba')
elo.ratings = {}
elo.process_games_from_db('nba/database/nba_predictions.db', season='2025-26')
elo.save()
"

# 3. Re-run game predictions
python nba/scripts/generate_game_predictions.py --force
```
