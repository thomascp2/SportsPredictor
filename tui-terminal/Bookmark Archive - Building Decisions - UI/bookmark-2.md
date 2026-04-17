# Bookmark 2 — Phase 2 Python Textual TUI: ~80% COMPLETE

**Session date:** 2026-04-10  
**Phase:** 2 of 4 — Python Textual TUI  
**Status:** Core architecture built and syntax-verified. Remaining: install deps + runtime test.

---

## What Was Built

| File | Status | What It Does |
|---|---|---|
| `tui/requirements.txt` | Done | textual, rich, fuzzywuzzy, python-Levenshtein |
| `tui/styles.tcss` | Done | Bloomberg dark theme — black bg, green value, red drop, amber volatile |
| `tui/ml_bridge.py` | Done | Reads nba/nhl prediction DBs, merges ml_* into props.db; loads pregame intel cache |
| `tui/widgets/__init__.py` | Done | Package marker |
| `tui/widgets/ticker.py` | Done | Scrolling bottom marquee from line_history (15min window, sorted by abs(delta)) |
| `tui/widgets/main_grid.py` | Done | Center DataTable — Player/Prop/Sport/PP/UD/Kalshi%/Tier/Edge/Disc, 1s refresh |
| `tui/widgets/context_wing.py` | Done | Left panel — reads news_context, shows selected player intel + global feed |
| `tui/widgets/watchlist.py` | Done | Right panel — reads/writes watchlist table, toggle play with ENTER |
| `tui/app.py` | Done | Main Textual app, 3-column layout, keyboard bindings, ML bridge async worker |

All files pass `python -m py_compile` (syntax verified).

---

## Architecture Decisions Made

### Player ID matching (ml_bridge.py)
The Rust ingester builds player_id as `{full_name_tokenized}_{sport_lower}` (e.g., `nikola_jokic_nba`).
The prediction DBs may store abbreviated names like "N. Jokic". The `_fuzzy_id_match()` function
handles this with:
1. Direct make_player_id match
2. Abbreviated name pattern (single char + last name → suffix match in current_lines)
3. Token subset check

### Tier computation in ml_bridge
The predictions table stores `probability` and `prediction` (OVER/UNDER) but not tier directly.
ml_bridge computes tier fresh: `edge = probability - break_even[odds_type]`, then `_tier_from_edge()`.
Break-evens match smart_pick_selector.py exactly (standard: 0.5238, goblin: 0.7619, demon: 0.4545).

### DataTable refresh strategy
`MainGrid.refresh_data()` calls `table.clear()` then re-adds all rows every 1 second.
Row ordering: T1→T5 first, then by sport, then by edge descending.
Row key format: `"{player_id}|{stat_type}"` — used by `get_selected_row()`.

### ENTER key routing
Textual's DataTable captures ENTER as `DataTable.RowSelected`. But adding to watchlist needs
to be triggered from the App's `on_key()` (not a binding) because ENTER also navigates.
Current implementation: `on_key()` checks `event.key == "enter"`, calls `grid.get_selected_row()`,
then calls `panel.toggle_play()`.

### Ticker scroll
Ticker uses 80ms interval advancing 1 char/tick (~12 chars/sec). Content reloads from DB every 30s.
Doubles the padded string for seamless looping: `doubled = padded * 2`, slice `[offset:offset+width]`.

---

## What Needs to Happen Next (to finish Phase 2)

### 1. Install dependencies
```bash
cd tui-terminal/tui
pip install -r requirements.txt
```

### 2. First run test (with mock/empty DB)
```bash
cd tui-terminal
PYTHONIOENCODING=utf-8 python tui/app.py
```
Expected: Empty grid (no rows in current_lines), empty context wing, ticker showing "No recent line moves".
App should launch without errors.

### 3. Known issue to fix — `get_selected_row()` in main_grid.py
The current implementation of `get_selected_row()` uses `coordinate_to_cell_key()` which may not
exist in all Textual versions. If it throws AttributeError, replace with:
```python
def get_selected_row(self) -> Optional[dict]:
    table: DataTable = self.query_one("#main-table", DataTable)
    # Textual 0.52+ exposes cursor_row as index
    try:
        # Build ordered key list from current table rows
        keys = list(self._row_data.keys())
        if 0 <= table.cursor_row < len(keys):
            return self._row_data[keys[table.cursor_row]]
    except Exception:
        pass
    return None
```

### 4. Wire `DataTable.RowSelected` → context wing update
The `MainGrid` has `on_row_select` callback but `DataTable.RowSelected` fires when ENTER is
pressed AND when cursor moves (in Textual 0.52+). Verify behavior: context wing should update
on UP/DOWN navigation, not just ENTER. If not working, add `on_data_table_row_highlighted` handler.

### 5. Run ingester first to populate props.db
Without the Rust ingester running, current_lines is empty and the grid shows nothing.
For testing, can seed props.db manually:
```sql
INSERT INTO current_lines (player_id, name, sport, stat_type, prizepicks_line, last_updated)
VALUES ('nikola_jokic_nba', 'Nikola Jokic', 'NBA', 'NBA_POINTS', 25.5, datetime('now'));
```

### 6. Test ml_bridge standalone
```bash
cd tui-terminal/tui
python ml_bridge.py
```
Expected output: `Bridge complete: {'nba_updated': N, 'nhl_updated': N, 'intel_rows': N}`
If 0 rows updated, run the orchestrator predictions first.

---

## Phase 3 Hooks (already in app.py)

- `action_force_intel()` is a stub that prints a status message. Phase 3 wires it to Gemini.
- `news_context` table is already being read by `ContextWing` — Phase 3 just needs to write to it.
- The `trigger` column in `news_context` is used to style entries differently (line moves show `[!]`).

---

## File Locations Summary
```
tui-terminal/
├── props.db              ← TUI SQLite (populated by Rust ingester)
├── bookmark-2.md         ← this file
├── tui/
│   ├── app.py            ← Main entry point
│   ├── ml_bridge.py      ← ML data merge
│   ├── styles.tcss       ← Bloomberg theme
│   ├── requirements.txt
│   └── widgets/
│       ├── __init__.py
│       ├── ticker.py     ← Bottom scrolling marquee
│       ├── main_grid.py  ← Center DataTable
│       ├── context_wing.py ← Left intel panel
│       └── watchlist.py  ← Right watchlist panel
```

---

## Next Session — Phase 3: Gemini Intelligence Layer
Build `intel/context_engine.py`:
1. Python watcher polling `line_history` every 60 seconds
2. Volatility trigger: Kalshi move >10% OR PP/UD line move >1.0pt within 15 min
3. Gemini API (`google-generativeai` SDK) with Google Search retrieval
4. Budget cap: 10 calls/day tracked in props.db (add `gemini_calls` column to a config table)
5. Writes to `news_context` — TUI already reads it automatically

Stick to Prompt 3 from `cpt_planning_markdowns/4_Prompt Engineering Preliminary.md`.
