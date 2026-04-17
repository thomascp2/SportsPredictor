# TUI Bookmark 7 -- Apr 11 2026

## STATUS: All 5 features implemented, ready to test

## What was done this session
1. **Grok intel fixed** -- XAI_API_KEY pulled from start_orchestrator.bat, written to tui-terminal/.env. Press `i` on any player for live Grok analysis.
2. **Filter bar** (`/`) -- opens native Input widget in the grid. Type to filter by player name, ESC to clear and close.
3. **Sport hotkeys** -- `1`=NHL, `2`=MLB, `3`=NBA, `0`=all. Active sport shown in header bar.
4. **Tier filter** (`t`) -- cycles ALL -> T1 -> T1+T2 -> T1+T2+T3 -> ALL. Active tier shown in header.
5. **Parlay builder** (`SPACE` + `p`) -- SPACE marks up to 6 picks with `*` prefix. `p` opens a modal with combined EV, break-even, and payout based on PrizePicks Power Play payouts.
6. **Injury feed** -- ESPN API polled 60s after startup, then every 6000s. Results appear in context wing under INJURIES section (separate from intel).

## Key bindings (full list)
| Key     | Action                              |
|---------|-------------------------------------|
| /       | Open player search filter           |
| ESC     | Close filter                        |
| 1       | Filter to NHL only                  |
| 2       | Filter to MLB only                  |
| 3       | Filter to NBA only                  |
| 0       | Show all sports                     |
| t       | Cycle tier filter                   |
| SPACE   | Mark/unmark row for parlay (max 6)  |
| p       | Open parlay builder modal           |
| i       | Force Grok intel for selected player|
| ENTER   | Add/remove from watchlist           |
| r       | Refresh ML bridge manually          |
| ctrl+x  | Clear entire watchlist              |
| q       | Quit                                |

## Parlay EV math (PrizePicks Power Play)
| Legs | Payout | Break-even |
|------|--------|------------|
| 2    | 3x     | 33.3%      |
| 3    | 5x     | 20.0%      |
| 4    | 10x    | 10.0%      |
| 5    | 20x    | 5.0%       |
| 6    | 25x    | 4.0%       |

## Architecture in one line
Rust ingester (PP/Kalshi) -> props.db current_lines -> ml_bridge.py merges SmartPicks -> props.db smart_picks -> Python Textual TUI reads every 1s

## Key file locations
- `tui-terminal/tui/app.py` -- main Textual app, all hotkeys + parlay modal + injury feed
- `tui-terminal/tui/widgets/main_grid.py` -- grid with filter/tier/parlay state
- `tui-terminal/tui/widgets/context_wing.py` -- intel + injury feed display
- `tui-terminal/tui/widgets/watchlist.py` -- watchlist panel
- `tui-terminal/tui/ml_bridge.py` -- bridges SmartPickSelector -> props.db
- `tui-terminal/.env` -- XAI_API_KEY, KALSHI_API_KEY (gitignored)
- `tui-terminal/intel/context_engine.py` -- Gemini/Grok triggered by line volatility

## Known remaining gaps
- UD (Underdog) blocked by geolocation -- skip, not worth pursuing
- NBA in LEARNING_MODE=True -- 0 NBA smart picks until next season
- MLB unmatched rate 76% -- stat_type normalization gap, low priority
- Parlay modal: ESC to close (q also works if focus lands on modal)

## Launch command
```bash
cd /c/Users/thoma/SportsPredictor/tui-terminal
PYTHONIOENCODING=utf-8 python tui/app.py
```
