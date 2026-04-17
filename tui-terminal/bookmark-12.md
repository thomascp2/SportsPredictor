# TUI Bookmark 12 — Apr 12 2026

## STATUS: Game-line edge fix COMPLETE. All 7 items done.

## What was done this session
1. **Game-line edge fix** — all 7 items from bookmark-11 implemented:
   - `nhl/features/game_features.py` `_add_odds_features` — reads 4 new cols from game_lines
   - `nba/features/game_features.py` DEFAULT_FEATURES — 4 new `gf_*` entries added
   - `nba/features/game_features.py` `_add_odds_features` — reads 4 new cols (+ fallback query updated)
   - `mlb/features/game_features.py` DEFAULT_FEATURES — 4 new `gf_*` entries added
   - `mlb/features/game_features.py` `_add_odds_features` — reads 4 new cols from game_lines primary
   - `nba/scripts/espn_nba_api.py` — extracts `over_odds`, `under_odds`, `home_spread_odds`, `away_spread_odds` from ESPN pickcenter
   - `nba/scripts/generate_predictions_daily.py` — game_lines CREATE TABLE + INSERT updated with 4 new cols + ALTER TABLE migration for existing DBs
   - `shared/game_prediction_engine.py` — `_american_to_break_even()` helper added; lines 308-321 replaced with market-priced break-evens

## What's still outstanding from bookmark-11
- Run `python sync/turso_migrate.py --fix-schema` to propagate the 4 new `game_lines` cols to Turso
- Optionally re-run today's game predictions to get recalculated edges

## TUI Outstanding (minor)
- INJ scroll doesn't work
- Prop stat abbreviations unclear (UTS, UNS, DED, RECORD, ALLOWE, STRIKE)
- Blank real estate in BOARD center view
