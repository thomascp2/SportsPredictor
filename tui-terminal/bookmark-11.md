# TUI Bookmark 11 — Apr 12 2026

## STATUS: Mid-implementation of game-line edge fix. Context ran out. Resume below.

## What was done this session
1. **MLB syntax crash fixed** — orphan `"""` at EOF of `mlb/features/opponent_feature_extractor.py`. Predictions re-ran: 86 MLB picks for 2026-04-12.
2. **Turso schema drift fixed** — added `--fix-schema` to `sync/turso_migrate.py`. Applied 17 missing columns (`odds_type`, `game_time`, `closing_line`, etc.) across NHL/NBA/MLB Turso DBs. All sports syncing clean.
3. **TUI crash fixed** — duplicate row key in DataTable (`NBA_franz_wagner|NBA_PRA|23.5`). Dedup added in `refresh_data()` in `tui/widgets/main_grid.py`.
4. **View nomenclature agreed**: THE GRID, LEFT WING, RIGHT WING, INJ, BOARD, LINES, TICKER.
5. **Game-line edge fix — PARTIALLY DONE** (see below).

## Game-Line Edge Fix — In Progress

### The Bug
`shared/game_prediction_engine.py` lines 308-321 uses hardcoded break-evens:
- Spreads: flat `0.5238` (assumes -110 always)
- Totals: flat `0.50` (WRONG — should be at least 0.5238, use real odds when available)
- Moneylines: correct (uses actual `gf_home_implied_prob`)

### ESPN Has The Data
Live test confirmed ESPN pickcenter returns `overOdds`, `underOdds`, `homeTeamOdds.spreadOdds`, `awayTeamOdds.spreadOdds` for all sports.

### What's Already Fixed
- `shared/fetch_game_odds.py` — extracts + stores `over_odds`, `under_odds`, `home_spread_odds`, `away_spread_odds`
- `nhl/scripts/espn_nhl_api.py` — extracts all 4 new fields
- `nhl/scripts/generate_predictions_daily_V6.py` — schema + INSERT updated with 4 new cols
- `nhl/features/game_features.py` — 4 new `gf_*` defaults added (but `_add_odds_features` NOT yet updated to read them)

### Still To Do (in order)
1. `nhl/features/game_features.py` `_add_odds_features` (line ~320) — read `over_odds`, `under_odds`, `home_spread_odds`, `away_spread_odds` from `game_lines` table into `gf_*` features
2. `nba/features/game_features.py` `_add_odds_features` (line ~321) — same pattern
3. `mlb/features/game_features.py` `_add_odds_features` (line ~366) — same pattern
4. `nba/features/game_features.py` DEFAULT_FEATURES (line ~100) — add 4 new `gf_*` defaults
5. `mlb/features/game_features.py` DEFAULT_FEATURES (line ~102) — same
6. `nba/scripts/generate_predictions_daily.py` game_lines schema + INSERT (lines ~192-287) — add 4 new cols (NBA uses its own INSERT, not shared/fetch_game_odds.py)
7. **`shared/game_prediction_engine.py` lines 308-321** — THE MAIN FIX

### The Engine Fix (item 7)
Replace the hardcoded break-evens with this pattern:

```python
def _american_to_break_even(odds: Optional[int], default: float = 0.5238) -> float:
    """Convert American odds to break-even probability."""
    if odds is None:
        return default
    try:
        o = int(odds)
        if o < 0:
            return abs(o) / (abs(o) + 100)
        else:
            return 100 / (o + 100)
    except (ValueError, TypeError):
        return default

# In predict_and_save(), replace lines 308-321:
if sp.bet_type == "spread":
    if sp.bet_side == "home":
        implied = _american_to_break_even(features.get("gf_home_spread_odds_american"))
    else:
        implied = _american_to_break_even(features.get("gf_away_spread_odds_american"))
elif sp.bet_side in ["over", "under"]:
    if sp.bet_side == "over":
        implied = _american_to_break_even(features.get("gf_over_odds_american"))
    else:
        implied = _american_to_break_even(features.get("gf_under_odds_american"))
else:  # moneyline
    implied = features.get("gf_home_implied_prob", 0.50)
    if sp.bet_side == "away":
        implied = 1.0 - implied
```

### The _add_odds_features Pattern (same for all 3 sports)
```python
def _add_odds_features(self, conn, features, home, away, game_date):
    row = conn.execute("""
        SELECT spread, over_under, home_moneyline, away_moneyline,
               over_odds, under_odds, home_spread_odds, away_spread_odds
        FROM game_lines
        WHERE home_team = ? AND away_team = ? AND game_date = ?
        LIMIT 1
    """, (home, away, game_date)).fetchone()

    if row:
        if row["spread"] is not None:
            features["gf_spread"] = row["spread"]
        if row["over_under"] is not None:
            features["gf_total_line"] = row["over_under"]
        if row["home_moneyline"] is not None:
            ml = row["home_moneyline"]
            features["gf_home_implied_prob"] = round(
                abs(ml) / (abs(ml) + 100) if ml < 0 else 100 / (ml + 100), 4)
        if row["over_odds"] is not None:
            features["gf_over_odds_american"] = row["over_odds"]
        if row["under_odds"] is not None:
            features["gf_under_odds_american"] = row["under_odds"]
        if row["home_spread_odds"] is not None:
            features["gf_home_spread_odds_american"] = row["home_spread_odds"]
        if row["away_spread_odds"] is not None:
            features["gf_away_spread_odds_american"] = row["away_spread_odds"]
```

## After This Is Done
- Run `python sync/turso_migrate.py --fix-schema` to propagate the 4 new `game_lines` cols to Turso
- Optionally re-run today's game predictions to get recalculated edges

## TUI Outstanding (minor, resume after engine fix)
- INJ scroll doesn't work
- Prop stat abbreviations unclear (UTS, UNS, DED, RECORD, ALLOWE, STRIKE)
- Blank real estate in BOARD center view
