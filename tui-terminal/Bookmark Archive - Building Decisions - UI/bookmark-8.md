# TUI Bookmark 8 -- Apr 11 2026

## STATUS: Intel + injury feed fixed. Game lines + scoreboard planned for next session.

## Fixes applied this session
1. **Intel `i` not working** -- DataTable wasn't auto-focused. Fixed: 0.3s timer calls `table.focus()` on mount. Row 0 also fires selection callback immediately so header shows a player from launch.
2. **ESPN injury feed wrong structure** -- ESPN groups injuries by team (`injuries[i].injuries[j]`). Fixed parser in `app.py _injury_feed_tick()`. Writes 10 players per sport to news_context.
3. **Injury feed timing** -- fires 60s after TUI launch, then every 6000s. No manual trigger needed.

## Answers to your questions
- **Ingester not running**: Not a problem for viewing smart picks -- ml_bridge already populated smart_picks table (156 rows). Ingester only needed for real-time PP line updates from the Rust poller.
- **Context engine not open**: Not needed for manual intel (`i` key). Context engine only auto-triggers Gemini on line volatility, which is broken (quota exhausted). Manual Grok via `i` key works fine without it.

## Next session: Game Lines + Scoreboard

### Game line picks
- Live scripts: `nhl/scripts/generate_game_predictions.py`, `nba/scripts/generate_game_predictions.py`, `mlb/scripts/generate_game_predictions.py`
- These write to each sport's SQLite DB (nhl_predictions_v2.db, nba_predictions.db, mlb DB)
- Plan: add a `game_picks` tab (press `g`) that shows game-level picks (spread/total/ML) separate from player props
- Query from the existing sport DBs -- look at the game_predictions table schema in each

### Scoreboard integration
- `scoreboard/live_data.py` -- already has `all_games()`, `nhl_games()`, `nba_games()`, `mlb_games()` functions
- `scoreboard/scoreboard.py` -- rich terminal scoreboard with live scores + bet tracking
- Plan: Add a `ScoreboardPanel` widget that calls `all_games(today)` every 60s and displays scores in right panel (replace or add to watchlist)
- OR: make it a 4th tab/view toggled with `s` key
- The scoreboard's `live_data.py` is clean and importable -- just call `all_games(date)` directly

### Recommended layout for game lines + scoreboard
```
Option A: Tab views (g=game lines, s=scoreboard, default=props)
  - keeps current 3-column layout intact
  - `g` swaps main grid content to game picks
  - `s` swaps to scoreboard view

Option B: 4-column ultra-wide
  - Add ScoreboardPanel as 4th column (15%)
  - Shrink other cols: 18/47/20/15
  - Always visible, auto-refreshes scores
```
Option A is simpler and less risky. Recommend starting there.

## Ticker: Replace line changes with live game scores
- Current ticker scrolls PP line changes -- no longer useful (UD disabled, lines stable)
- Replace with live game scores scrolling across bottom bar
- Source: `scoreboard/live_data.py` `all_games(today)` -- already fetches NHL/NBA/MLB scores
- Format: `NHL: EDM 3 VAN 1 (P2)  |  MLB: NYY 4 BOS 2 (B7)  |  NBA: LAL 108 GSW 102 (FINAL)`
- Refresh every 60s (not 1s -- scores don't change that fast)
- File to edit: `tui-terminal/tui/widgets/ticker.py` -- swap the line-change scroll for score scroll
- Key constraint: `scoreboard/` is in SportsPredictor root, so import path needs `sys.path` insert

## Launch
```bash
cd /c/Users/thoma/SportsPredictor/tui-terminal
PYTHONIOENCODING=utf-8 python tui/app.py
```
