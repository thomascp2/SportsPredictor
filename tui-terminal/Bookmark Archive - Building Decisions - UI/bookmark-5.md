# Bookmark 5 — Phase 3 PARTIAL: Gemini Layer Running (dry-run verified), wiring to TUI pending

**Session date:** 2026-04-11  
**Phase:** 3 of 4 — Context Engine running but not wired into TUI's force-intel keybind  
**Status:** Dry-run confirmed working. NHL_HITS/MLB misclassification fixed. Gemini not yet called live.

---

## What Was Completed This Session

| Component | Status | Notes |
|---|---|---|
| `google-generativeai` install | RESOLVED | Deprecated package — replaced with `google-genai` v1.72.0 |
| `context_engine.py` SDK update | Done | Migrated from old `GenerativeModel` API to `google.genai.Client` |
| `tui/requirements.txt` | Done | `google-generativeai>=0.7.0` → `google-genai>=1.0.0` |
| NHL_HITS/MLB misclassification | Fixed (Python) | `_find_volatile_players()` now guards against non-NHL players on NHL_HITS |
| Dry-run verified | Done | 232 false positives suppressed; context engine polls cleanly |
| Live Gemini call | NOT YET | Need live mode test + wire to TUI keybind |
| `action_force_intel()` wiring | NOT YET | Stub in `tui/app.py:160` — Phase 3 core remaining task |

---

## Bugs Identified

### Bug 1 — UD MLB base hits mapped as NHL_HITS (partially fixed)
- **Cause**: `infer_from_ud()` in `src/types.rs:189` maps plain `"hits"` → `NhlHits`
- **Assumption was wrong**: Bookmark-3 assumed UD uses `"batter hits"` for MLB — they use plain `"hits"` too
- **Python fix applied**: `context_engine.py` `_find_volatile_players()` now joins `current_lines.sport` and skips `NHL_HITS` rows where `sport != 'NHL'` — guard uses `!= 'NHL'` (not `and sport != 'NHL'`) so NULL sport (no current_lines match) also gets filtered. This matters because UD writes these players with `_nhl` suffix player_id, which never matches an MLB row in current_lines.
- **Rust fix still needed**: `types.rs:189` — the `infer_from_ud()` match arm for `"hits"` needs to stay `NhlHits` for NHL but somehow distinguish MLB. Without sport context from UD API, best option is to cross-reference player_id suffix (`_mlb` vs `_nhl`) in `underdog.rs` at write time. **Do not attempt until we can inspect the full UD appearance JSON for a known MLB player.**
- **Impact**: Bad `NHL_HITS` rows still enter `line_history` from UD — harmless for now, won't trigger Gemini

### Bug 2 — PP league=10 (MLB) getting 429'd every poll cycle
- **Symptom**: `PP API returned 429 Too Many Requests` for league=10 every ~120s
- **Cause**: All 3 PP leagues fire nearly simultaneously on startup; rate limit hits leagues 2 and 10 back-to-back
- **Not urgent**: NHL (league=2) data is clean. MLB PP lines arrive eventually once rate limit clears
- **Fix idea**: Stagger PP league polls by adding a per-league jitter offset in `config.rs` (e.g. league 7 at T+0s, league 2 at T+40s, league 10 at T+80s)

### Bug 3 — `action_force_intel()` stub not wired (Phase 3 remaining work)
- **Location**: `tui/app.py:154–161`
- **Current behavior**: Pressing the force-intel keybind shows `"[Phase 3] Intel queued for {name} — Gemini not wired yet"` in the header
- **Fix needed**: Wire to `context_engine._call_gemini()` via async worker, write result to `news_context`, refresh `ContextWing`

---

## Exact Resume Steps

### Step 1 — Launch all terminals (one double-click)
```bash
# From Git Bash or Windows Explorer:
cd C:/Users/thoma/SportsPredictor/tui-terminal
./launch.sh
```
This opens 3 Git Bash windows automatically:
- Tab/Window 1: Rust ingester
- Tab/Window 2: Python TUI
- Tab/Window 3: Context engine (dry-run by default — edit launch.sh to remove --dry-run for live)

### Step 2 — Wire `action_force_intel()` to Gemini

In `tui/app.py`, replace the stub at line 154 with:

```python
def action_force_intel(self) -> None:
    """Manually trigger Gemini intel for the selected player."""
    if not self._selected_row:
        self._status_msg = "Select a player first (use arrow keys)"
        self._refresh_header()
        return
    name     = self._selected_row.get("name", "unknown")
    player_id = self._selected_row.get("player_id", "")
    stat_type = self._selected_row.get("stat_type", "")
    self._status_msg = f"Fetching intel for {name}..."
    self._refresh_header()
    self.run_worker(
        lambda: self._run_force_intel(player_id, name, stat_type),
        exclusive=False,
        name="force_intel"
    )

def _run_force_intel(self, player_id: str, name: str, stat_type: str) -> None:
    """Worker: call Gemini and write to news_context."""
    import sqlite3
    from pathlib import Path
    # Import context_engine helpers
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "intel"))
    from context_engine import _connect, _call_gemini, _write_intel, _budget_remaining

    db_path = Path(__file__).parent.parent / "props.db"
    conn = _connect(db_path)
    if _budget_remaining(conn) <= 0:
        self._status_msg = f"Daily Gemini budget exhausted"
        self._refresh_header()
        return
    summary = _call_gemini(name, stat_type, dry_run=False)
    if summary:
        _write_intel(conn, player_id, stat_type, summary, trigger="manual")
        self._status_msg = f"Intel: {summary[:60]}"
    else:
        self._status_msg = f"Gemini returned nothing for {name}"
    self._refresh_header()
```

### Step 3 — Test live Gemini call (manual trigger)

1. Start the ingester (Tab 1) — wait for PP lines to populate
2. Start the TUI (Tab 2)
3. Navigate to any player with arrow keys
4. Press the force-intel keybind (check `app.py` bindings for the key)
5. Watch ContextWing left panel — should populate within ~3s

### Step 4 — Switch context engine to live mode

Once manual trigger is confirmed:
```bash
python tui-terminal/intel/context_engine.py  # no --dry-run
```
First real Gemini call will fire on the next genuine line move (≥ 1.0pt in 15 min).

---

## Phase 4 — Next Up: Heatmap Display

After Phase 3 wiring is done:
- Secondary lightweight Textual app for top-mounted monitor
- Sport-tile grid (NBA / NHL / MLB) colored by ML model confidence vs Kalshi discrepancy  
- Reads same `props.db` — no new ingester work needed
- Stick to Prompt 4 from `cpt_planning_markdowns/4_Prompt Engineering Preliminary.md`

---

## File Locations Summary

```
tui-terminal/
├── props.db                        ← TUI SQLite (ingester writes here)
├── bookmark-5.md                   ← this file
├── launch.sh                       ← NEW: one-click terminal launcher
├── .env                            ← GEMINI_API_KEY=... (already set)
├── src/
│   ├── types.rs:189                ← infer_from_ud() "hits" → NhlHits (Rust fix pending)
│   └── ...
├── tui/
│   ├── app.py:154                  ← action_force_intel() stub — wire this in Phase 3
│   ├── requirements.txt            ← google-genai>=1.0.0 (updated this session)
│   └── widgets/
│       └── context_wing.py         ← reads news_context; no changes needed
└── intel/
    └── context_engine.py           ← _find_volatile_players() has NHL_HITS sport guard
```
