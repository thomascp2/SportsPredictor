# Handoff Prompt: MLB Game Lines Pipeline Audit

Use this prompt at the start of the next context window.

---

## PASTE THIS AS YOUR FIRST MESSAGE:

We just fixed the NBA game lines inflated probability bug (session log at `docs/sessions/2026-04-05-game-lines-bug-fix.md`). Three root causes were: corrupted ELO data, no season filter in team stats, and a sign error in the spread→probability approximation. All three are now fixed for NBA.

We need you to audit and fix the MLB game lines pipeline before it produces the same bad numbers. MLB data collection is live as of April 2026.

Here's what needs to happen — work through these in order:

**1. Read the session log first:**
`docs/sessions/2026-04-05-game-lines-bug-fix.md`
This explains exactly what was wrong in NBA so you understand what to look for.

**2. Check if MLB has a team_stats_collector:**
Look in `mlb/scripts/` for anything that builds rolling team stats. If it doesn't exist, create one modeled after `nba/scripts/team_stats_collector.py` with `SEASON_START_DATE = "2026-03-01"` baked in from the start. Key difference for MLB: use `run_diff_avg` not `point_diff_avg`.

**3. Audit `mlb/features/game_features.py`:**
Verify it uses `gf_home_run_diff` and `gf_away_run_diff` (not goal_diff or point_diff). The shared statistical baseline in `shared/game_statistical_baseline.py` falls back through `gf_home_goal_diff → gf_home_point_diff → gf_home_run_diff`. If MLB features use the wrong key name, the team strength signal silently drops to 0.

**4. Check MLB moneyline fetching:**
MLB doesn't use a point spread — it uses a run line (always ±1.5) plus a moneyline. The moneyline IS the MLB probability signal. Verify `shared/fetch_game_odds.py` fetches moneylines from the ESPN summary endpoint for MLB games. Look at the game_lines table: `SELECT * FROM game_lines WHERE game_date >= '2026-04-01' LIMIT 10` in `mlb/database/mlb_predictions.db` — check if `home_moneyline` is populated or NULL.

**5. Initialize MLB game prediction tables if needed:**
Check if `game_predictions` table exists in the MLB DB. If not: `python shared/game_prediction_schema.py`

**6. Check `mlb/scripts/generate_game_predictions.py`:**
Verify it has a feature extractor wired up and calls `fetch_and_save_odds` before generating predictions (same pattern as `nba/scripts/generate_game_predictions.py`).

**7. Run a test prediction for today or yesterday:**
`python mlb/scripts/generate_game_predictions.py --force`
Check the output probabilities. Spread predictions should be 40–65% range. Moneyline predictions can be higher (70–85% for heavy favorites) but nothing should be 95%+.

**8. Build MLB ELO if enough games exist:**
Check how many games are in `mlb/database/mlb_predictions.db` — `SELECT COUNT(*), MIN(game_date), MAX(game_date) FROM games WHERE home_score IS NOT NULL`. If 50+ games, rebuild ELO:
```python
import sys; sys.path.insert(0,'shared')
from elo_engine import EloEngine
elo = EloEngine(sport='mlb')
elo.ratings = {}
elo.process_games_from_db('mlb/database/mlb_predictions.db', season='2025-26')
elo.save()
```

**Goal:** MLB game lines should show realistic probabilities (moneyline 45–80% for most games, no 99%+ numbers) and the data pipeline should have a season filter so it never mixes old-season data.
