# TUI Bookmark 9 -- Apr 11 2026

## STATUS: Bobby McMann bug fixed. Scoreboard + picks overlay done. Intel cleaned up.

## What was done this session
1. **Ticker live scores** -- replaces dead line_history scroll. Pulls all_games() every 60s via bg thread. Color: green=FINAL, amber=live, orange=scheduled. Speed: 130ms/char.
2. **Bobby McMann intel bug FIXED** -- Root cause: DataTable row keys are 3-part ("pid|stat|pp_line") but `_row_data` dict used 2-part keys ("pid|stat"). `_row_highlighted` always returned None -> arrow-key navigation never updated `_selected_row`. Fix: extract 2-part key in `_row_highlighted` and `_row_selected` via `"|".join(key.split("|")[:2])`.
3. **Stale intel FIXED** -- Added `summary NOT LIKE 'No real%'` filter to intel query in context_wing.py. Old Gemini noise ("No real Gemini call -- Desmond Bane") gone.
4. **Injury display** -- LIMIT 6 -> 25, compact 1-line format in left panel. Center panel (`n` key) shows 2-line format (name+status / comment) with comment up to 100 chars.
5. **`n` key -- Injury Report center panel** -- toggles center column. Shows grouped by sport with status color-coding. `n` again returns to props.
6. **`s` key -- Scoreboard + Picks Overlay** -- new ScoreboardView widget. Shows LIVE/FINAL/TONIGHT sections. Under each game: our smart picks for players in that game (matched by team column). Picks show player, stat, line, tier badge, edge%. Auto-refreshes every 30s via bg thread.

## Current key bindings
| Key     | Action                                     |
|---------|--------------------------------------------|
| /       | Open player search filter                  |
| ESC     | Close filter                               |
| 1       | Filter to NHL only                         |
| 2       | Filter to MLB only                         |
| 3       | Filter to NBA only                         |
| 0       | Show all sports                            |
| t       | Cycle tier filter                          |
| n       | Toggle injury report (center column)       |
| s       | Toggle scoreboard + picks (center column)  |
| SPACE   | Mark/unmark row for parlay (max 6)         |
| p       | Open parlay builder modal                  |
| i       | Force Grok intel for selected player       |
| ENTER   | Add/remove from watchlist                  |
| r       | Refresh ML bridge manually                 |
| ctrl+x  | Clear entire watchlist                     |
| q       | Quit                                       |

## Architecture
```
tui/app.py                  -- main app; _center_view state: "props"|"injuries"|"scoreboard"
tui/widgets/main_grid.py    -- props DataTable (Bobby McMann bug fixed in _row_highlighted)
tui/widgets/context_wing.py -- left panel; intel date+content filtered; injuries show 25 max
tui/widgets/injury_view.py  -- center column injury report (n key)
tui/widgets/scoreboard_view.py -- center column scoreboard + picks overlay (s key)
tui/widgets/ticker.py       -- bottom bar live scores from scoreboard/live_data.py
tui/widgets/watchlist.py    -- right panel watchlist
```

## Center column view system
`_set_center_view(view)` is the single method to swap: sets display=True/False on all 3 widgets.
- `_center_view = "props"`:      MainGrid visible
- `_center_view = "injuries"`:   InjuryView visible
- `_center_view = "scoreboard"`: ScoreboardView visible
Header shows `[INJURIES]` or `[SCOREBOARD]` when not on props.
`n` and `s` both toggle (press again to return to props).

## Key implementation notes
- **Bg thread pattern**: `_kick_fetch()` starts threading.Thread, worker sets `_pending_data` attr, `_drain_pending()` runs on 1s interval on main thread and consumes it. GIL makes single-attr assignment safe.
- **Team matching for picks overlay**: `smart_picks.team` column matched against `away_team`/`home_team` from scoreboard. Works when abbreviations match (NHL/MLB mostly good; NBA may have some misses due to ESPN vs NBA Stats API abbrev differences).
- **Injury cap**: ESPN API returns ~10 per sport. InjuryView dedupes by pid (keeps most recent).
- **Intel filter**: `date(created_at) = date('now') AND summary NOT LIKE 'No real%'` -- kills both stale old-session entries and broken Gemini entries.

## Known issues / next ideas
- NBA picks team matching may miss some players (ESPN abbrevs: GSW not GS, etc.)
  Fix: add TEAM_ALIASES dict in scoreboard_view.py if this becomes a problem
- Scoreboard `g` key for game-level ML predictions (spread/total/ML) not yet built
  Source: `nhl/scripts/generate_game_predictions.py` / `nba/scripts/generate_game_predictions.py`
  These write to `game_predictions` table in each sport DB -- schema TBD
- CBB games show in scoreboard (tournament) but no picks for CBB (not in our system)
- NBA LEARNING_MODE=True -- 0 NBA smart picks until Oct 2026 retrain
- MLB unmatched rate 76% -- stat_type normalization gap, low priority

## Launch
```bash
cd /c/Users/thoma/SportsPredictor/tui-terminal
PYTHONIOENCODING=utf-8 python tui/app.py
```
