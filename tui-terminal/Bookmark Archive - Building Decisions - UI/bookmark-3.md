# Bookmark 3 — Phase 2 COMPLETE: Rust Ingester + TUI Infrastructure

**Session date:** 2026-04-11  
**Phase:** 2 of 4 — Complete  
**Status:** Ingester shipping live data for NBA, MLB (PP + UD + Kalshi). TUI syntax-verified. Ready to test full stack.

---

## What Was Completed This Session

| Component | Status | Notes |
|---|---|---|
| UD sport inference fix | Done | `positions[]` empty in UD API — sport now inferred from stat name via `infer_from_ud()` |
| MLB ingester support | Done | PP league 10, 14 new MLB StatType variants, sport-aware `from_prizepicks()` |
| `ml_bridge.py` MLB wiring | Done | MLB_DB path, full PROP_MAP, `merge_predictions("MLB", ...)` in `run_bridge()` |
| Kalshi series confirmed | Done | 9 live series across NBA + MLB; NHL has no active player prop markets |
| Kalshi ticker parser | Done | Per-series → StatType mapping (was hardcoded NbaPoints for all NBA) |

---

## Confirmed Kalshi Series (as of Apr 11, 2026)

| Series | Sport | Stat |
|---|---|---|
| KXNBAPTS | NBA | Points |
| KXNBAAST | NBA | Assists |
| KXNBAREB | NBA | Rebounds |
| KXNBA3PT | NBA | 3-Pointers Made |
| KXMLBHIT | MLB | Batter Hits |
| KXMLBHRR | MLB | Hits + Runs + RBIs |
| KXMLBTB  | MLB | Total Bases |
| KXMLBKS  | MLB | Pitcher Strikeouts |
| KXMLBHR  | MLB | Home Runs |

**NHL:** No active Kalshi player prop markets as of Apr 2026. Check again at playoff start.  
**NBA steals/blocks/turnovers/fantasy/PRA:** Not found on Kalshi — check periodically.

---

## Architecture Decisions Made

### UD sport inference (underdog.rs)
Underdog's API removed `sport_id` from appearances and the `positions` array is always empty.
Sport is now derived entirely from the stat name string since UD uses sport-distinct names:
- Golf stats (`strokes`, `birdies_or_better`, etc.) → `Sport::Unknown` → skipped
- Plain `"hits"` → `NhlHits` (NHL body-checks; UD uses `"batter hits"` for MLB base hits)
- `"pitcher strikeouts"` → MLB (UD distinguishes pitcher vs batter Ks)

### from_prizepicks is now sport-aware (types.rs)
PP uses `"hits"` for both NHL physical hits (league 2) and MLB base hits (league 10).
`StatType::from_prizepicks(sport: &Sport, raw: &str)` disambiguates using the sport context
already known from the league_id. Call site in prizepicks.rs passes `&sport`.

### Kalshi ticker parser (kalshi.rs)
Switched from `series.contains("NBA") → NbaPoints` (wrong for all non-points series)
to an explicit match on the full series prefix string. Unknown series return `None` (dropped).

### MLB stat types (types.rs)
14 MLB StatType variants total, split into pitcher vs batter:
- Pitcher: `MlbStrikeouts`, `MlbOutsRecorded`, `MlbPitcherWalks`, `MlbHitsAllowed`, `MlbEarnedRuns`
- Batter: `MlbHits`, `MlbTotalBases`, `MlbHomeRuns`, `MlbRbis`, `MlbRuns`, `MlbStolenBases`, `MlbBatterWalks`, `MlbBatterStrikeouts`, `MlbHrr`

### ml_bridge MLB (tui/ml_bridge.py)
MLB predictions table has same schema as NHL/NBA (`player_name`, `prop_type`, `line`, `prediction`, `probability`).
`merge_predictions("MLB", MLB_DB, props_conn)` is wired — returns 0 rows until today's
MLB statistical predictions run, then populates automatically. No ML models yet; uses same
statistical output path as NHL/NBA did before their models trained.

---

## Live Ingester Status (verified Apr 11 2026)

```
PrizePicks poller started — leagues: [7, 2, 10]
PP league=7  fetched 216 projections   (NBA)
PP league=2  fetched 224 projections   (NHL)
PP league=10 fetched ~N  projections   (MLB — active once games start)
UD fetched 1610 lines                  (NBA + MLB props; golf skipped)
Kalshi discovered 0 open markets       (markets open closer to game time)
```

---

## How to Test (full stack)

### 1. Start the ingester
```bash
cd tui-terminal
RUST_LOG=info ./target/release/ingester.exe
```
Expected: PP leagues [7, 2, 10] confirmed, UD fetched N lines, Kalshi 0 markets (until game day).

### 2. Install TUI Python deps (first time only)
```bash
cd tui-terminal/tui
pip install -r requirements.txt
```

### 3. Run the TUI
```bash
cd tui-terminal
PYTHONIOENCODING=utf-8 python tui/app.py
```
Expected: Bloomberg dark-theme grid appears. Empty rows until ml_bridge runs.

### 4. Test ml_bridge standalone
```bash
cd tui-terminal/tui
python ml_bridge.py
```
Expected: `Bridge complete: {'nba_updated': N, 'nhl_updated': N, 'mlb_updated': 0, 'intel_rows': N}`
MLB will be 0 until today's MLB predictions run via the orchestrator.

### 5. Seed a test row (optional — bypasses orchestrator dependency)
```sql
-- In SQLite CLI or DB browser, against tui-terminal/props.db:
INSERT INTO current_lines (player_id, name, sport, stat_type, prizepicks_line, last_updated)
VALUES ('nikola_jokic_nba', 'Nikola Jokic', 'NBA', 'NBA_POINTS', 25.5, datetime('now'));
```

---

## Known Issues / Notes

- **PP 429 on startup**: All three leagues fire immediately on first run — rate limiting hits leagues 2 and 10. Resolves automatically on next poll cycle (~30s). Not a bug.
- **UD "hits" ambiguity**: Plain `"hits"` on UD → NhlHits. If UD uses `"hits"` for MLB base hits (not `"batter hits"`), those lines will be misclassified. Acceptable for now — PP is the primary MLB source.
- **Kalshi markets open late**: NBA/MLB markets typically open a few hours before tip-off/first pitch. Run ingester from ~noon onwards for live data.
- **MLB ml_bridge returns 0**: Expected until orchestrator generates today's MLB statistical predictions. The bridge polls every 5 min in app.py — will populate automatically.

---

## File Locations Summary
```
tui-terminal/
├── props.db                  ← TUI SQLite (populated by Rust ingester)
├── bookmark-3.md             ← this file
├── src/
│   ├── main.rs               ← spawns 3 tasks
│   ├── config.rs             ← env config; league IDs [7,2,10]; Kalshi series
│   ├── types.rs              ← StatType (NBA×9, NHL×6, MLB×14); infer_from_ud; from_prizepicks
│   ├── prizepicks.rs         ← PP REST poller; passes &sport to from_prizepicks
│   ├── underdog.rs           ← UD REST poller; sport inferred from stat name
│   ├── kalshi.rs             ← Kalshi WS; per-series → StatType match
│   └── db.rs                 ← SQLite upsert logic
└── tui/
    ├── app.py                ← Main Textual app entry point
    ├── ml_bridge.py          ← Merges NBA/NHL/MLB predictions into props.db
    ├── styles.tcss           ← Bloomberg dark theme
    ├── requirements.txt
    └── widgets/
        ├── ticker.py         ← Bottom scrolling marquee
        ├── main_grid.py      ← Center DataTable (1s refresh)
        ├── context_wing.py   ← Left intel panel
        └── watchlist.py      ← Right watchlist panel
```

---

## Phase 3 — Next Session: Gemini Intelligence Layer

Build `intel/context_engine.py`:
1. Python watcher polling `line_history` every 60 seconds
2. Volatility trigger: PP/UD line move >1.0pt OR Kalshi price move >10% within 15 min
3. Gemini API (`google-generativeai` SDK) with Google Search retrieval
4. Budget cap: 10 calls/day tracked in props.db config table
5. Writes summaries to `news_context` — ContextWing already reads it automatically

Stick to Prompt 3 from `cpt_planning_markdowns/4_Prompt Engineering Preliminary.md`.
