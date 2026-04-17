# TUI Bookmark 10 -- Apr 12 2026

## STATUS: Scoreboard scroll fixed. GamePredView wired (g key). Team IDs + ELO on game preds. Phase 4 (Heatmap) not started.

## What was done this session
1. **Scoreboard scroll fix (completed mid-impl from last session)** -- `_render_content` now consistently returns a list of Rich markup strings (the "no games" path was still returning a bare string -- fixed). `ScoreboardView` now carries `_all_lines` + `_scroll_offset`. New `_redraw_body()` slices `_all_lines[offset:]`, joins, and updates the Static. `on_key` rewritten to use offset arithmetic (j/k = 3 lines, PgDn/PgUp = 20) -- old `body.scroll_down()` calls removed. `_drain_pending` stores into `_all_lines`, resets offset, calls `_redraw_body()`.
2. **GamePredView fully wired** -- `game_pred_view.py` existed but had a `SyntaxError` (generator expression in `min()` with `key=` arg needs parens -- fixed). Was not connected to `app.py` at all. Now: import added, `Binding("g")` added, widget composed + hidden on mount, `_set_center_view("gamepreds")` as 4th center view, `action_game_preds()` toggles in/out like scoreboard/injuries, `_apply_sport_filter()` pushes sport filter to GamePredView, hints bar updated.
3. **GamePredView -- team identification** -- replaced ambiguous WIN/LOSE labels with actual team abbreviations. Convention used: MONEYLINE WIN = home team wins (shows home abbrev), MONEYLINE LOSE = away team wins (shows away abbrev). SPREAD positive line (+1.5) = away team's spread (shows away), negative line (-1.5) = home team's spread (shows home). TOTAL rows unchanged (OVER/UNDER clear). Game header now annotates ELO win % for both teams, bold yellow highlight on the ELO favorite:
   ```
   VAN @ SJS   VAN 40%   SJS 60%*
     TOTAL      6.5    ^ OVER   58%   +7.6%   L    60%
     SPREAD     1.5    ^ VAN    56%   +3.6%   L    60%
     SPREAD    -1.5    v SJS    44%   -8.4%   -    60%
     MONEYLINE   --   ^ SJS    62%   -6.1%   ?    60%
     MONEYLINE   --   v VAN    38%   +6.1%   -    60%
   ```

## Current key bindings
| Key      | Action                                              |
|----------|-----------------------------------------------------|
| /        | Open player search filter                           |
| ESC      | Close filter                                        |
| 1        | Filter to NHL only                                  |
| 2        | Filter to MLB only                                  |
| 3        | Filter to NBA only                                  |
| 0        | Show all sports                                     |
| t        | Cycle tier filter                                   |
| n        | Toggle injury report (center column)                |
| s        | Toggle scoreboard + picks overlay (center column)   |
| g        | Toggle game-line predictions (center column) -- NEW |
| w        | Toggle right sidebar: watchlist ↔ live score sidebar|
| SPACE    | Mark/unmark row for parlay (max 6)                  |
| p        | Open parlay builder modal                           |
| i        | Force Grok intel for selected player                |
| ENTER    | Add/remove from watchlist                           |
| r        | Refresh ML bridge manually                          |
| ctrl+x   | Clear entire watchlist                              |
| q        | Quit                                                |

**While in scoreboard (s) or gamepreds (g) view:**
| j / k      | Scroll down / up 3 lines   |
| PgDn/PgUp  | Scroll down / up 20 lines  |
| 1 / 2 / 3  | Filter by sport            |

## Architecture
```
tui/app.py                   -- main app; _center_view state: "props"|"injuries"|"scoreboard"|"gamepreds"
tui/widgets/main_grid.py     -- props DataTable
tui/widgets/context_wing.py  -- left panel; intel + injuries (25 max, date-filtered)
tui/widgets/injury_view.py   -- center column injury report (n key)
tui/widgets/scoreboard_view.py -- center column scoreboard + picks overlay (s key)
                                  also ScoreSidebar -- compact right panel (w key)
tui/widgets/game_pred_view.py  -- center column game-line predictions (g key)
tui/widgets/ticker.py        -- bottom bar live scores
tui/widgets/watchlist.py     -- right panel watchlist
```

## Center column view system
`_set_center_view(view)` is the single method to swap: sets `display=True/False` on all 4 widgets.
- `_center_view = "props"`:      MainGrid visible
- `_center_view = "injuries"`:   InjuryView visible
- `_center_view = "scoreboard"`: ScoreboardView visible (s key -- j/k scroll)
- `_center_view = "gamepreds"`:  GamePredView visible (g key -- j/k scroll)

Header shows `[INJURIES]`, `[SCOREBOARD]`, or `[GAMEPREDS]` when not on props.
All four toggle: press the key again to return to props.

## Key implementation notes
- **Scroll pattern (scoreboard + gamepreds)**: `_all_lines: list` stores all rendered Rich markup lines. `_scroll_offset: int` tracks position. `_redraw_body()` slices and joins. `on_key` adjusts offset. ScoreSidebar still uses Textual's built-in `overflow-y: auto` (compact sidebar, doesn't need manual pagination).
- **GamePredView data source**: reads `game_predictions` table directly from each sport DB (`nhl_predictions_v2.db`, `nba_predictions.db`, `mlb_predictions.db`). Refreshes every 5 min + on `on_show`. Groups by (away, home) matchup, sorts by confidence_tier then edge.
- **ELO convention**: `elo_win_prob` stored per-row but is game-level -- home team's ELO win probability. `>= 0.50` = home team is ELO favorite. Used for header annotation only; does not affect pick rendering.
- **Team label convention (MONEYLINE/SPREAD)**: WIN=home wins, LOSE=away wins (moneyline). Positive spread line = away team's line, negative = home team's line. If DB stores `prediction` as HOME/AWAY instead of WIN/LOSE -- both are handled in the same branch, no change needed.
- **Bg thread pattern**: `_kick_fetch()` starts `threading.Thread`, worker sets `_pending_data` attr, `_drain_pending()` runs on 1s interval on main thread and consumes it. GIL makes single-attr assignment safe.

## Outstanding from PreWork Bookmark 9 (still to do)
- [ ] **Prop stat abbreviations unclear** -- in scoreboard picks overlay AND main grid. Examples: `UTS` (Hitter Outs?), `UNS`, `DED`, `RECORD` (Recorded Outs), `ALLOWE` (Hits Allowed), `STRIKE` (Hitter K), `HIT` → `HITS`. Fix: expand `STAT_ABBREV` dict in `scoreboard_view.py` and column display in `main_grid.py`.
- [ ] **[??] two missing chars** at top of scroll bar in main props grid -- cosmetic, low priority.
- [ ] **Blank real estate in scoreboard center view** -- picks only occupy ~40% of screen. Ideas: show more picks per game (currently capped at 10), add a "Today's Stats Leaders" section, or show league standings snippet.

## Phase 4 -- Heatmap Secondary Monitor (NOT STARTED)
Per `BLUEPRINT.md` Section 7 Phase 4:
- **File**: `heatmap/app.py` (separate Textual app, not part of main TUI process)
- **Goal**: heads-up macro view for second monitor -- readable from 5 feet
- **Three tiles**: NBA / NHL / MLB -- one big colored tile per league
- **Tile color logic**:
  - GREEN = T1-ELITE picks available, no negative intel
  - AMBER = T2/T3 picks or Grok flags a caution
  - RED = active negative intel (injury, rest) overriding model
  - GRAY = no plays of value
  - FLASHING border = `is_volatile = 1` row exists for that sport (Kalshi move >10% or PP/UD discrepancy >1.0pt)
- **Content per tile**: sport name (large), T1 count, top player name + tier
- **Refresh**: every 2 seconds from `props.db`
- **Launch**: separate terminal, `python heatmap/app.py`
- **Dependency**: reads `current_lines` table -- needs Rust ingester + ML bridge populated (both working)
- **Note**: Blueprint says "stick to Prompt 4 verbatim" -- see `cpt_planning_markdowns/4_Prompt Engineering Preliminary.md` for the exact build prompt.

## Known issues
- NBA picks team matching may miss some players (ESPN abbrevs: GSW not GS, etc.). TEAM_ALIASES dict in `scoreboard_view.py` can fix if it surfaces.
- NBA `LEARNING_MODE=True` -- 0 NBA smart picks until Oct 2026 retrain. Scoreboard NBA picks section will be empty.
- MLB unmatched rate ~76% -- stat_type normalization gap between ML bridge and PP lines. Low priority.
- CBB games show in scoreboard but no CBB picks (not in our system).

## Launch
```bash
cd /c/Users/thoma/SportsPredictor/tui-terminal
PYTHONIOENCODING=utf-8 python tui/app.py

# Phase 4 heatmap (once built):
PYTHONIOENCODING=utf-8 python heatmap/app.py
```
