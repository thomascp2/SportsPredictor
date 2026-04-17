# Bookmark 4 — Phase 3 IN PROGRESS: Gemini Intelligence Layer (mid-install reboot)

**Session date:** 2026-04-10  
**Phase:** 3 of 4 — Code complete, dependency blocked by Windows Defender  
**Status:** context_engine.py written and syntax-verified. Blocked on `google-generativeai` pip install (Defender hang). Rebooting to fix.

---

## What Was Completed This Session

| Component | Status | Notes |
|---|---|---|
| config.rs poll intervals | Done | PP: 30s → 120s, UD: 30s → 90s. Kalshi unchanged (WebSocket). |
| Ingester rebuild | Done | `cargo build --release` clean, 10 pre-existing warnings, no errors |
| `intel/context_engine.py` | Done | Written, syntax-verified, .env auto-load added |
| `google-generativeai` install | BLOCKED | Windows Defender scanning .pyd files — froze pip. Reboot + re-add exclusions needed. |

---

## Exact Resume Steps After Reboot

### Step 1 — Re-add Windows Defender exclusions (DO THIS FIRST)

Defender removes these exclusions on updates — this is a recurring issue (happened Jan + Mar 2026).

1. Open **Windows Security** → **Virus & threat protection** → **Manage settings**
2. **Exclusions** → **Add or remove exclusions** → **Add a folder** for each:
   ```
   C:\Users\thoma\AppData\Local\Programs\Python\Python313\Lib\site-packages
   C:\Users\thoma\AppData\Local\Programs\Python\Python313\Scripts
   ```

### Step 2 — Install the dependency

```bash
pip install google-generativeai
```
Should complete in seconds once exclusions are in place. Confirm:
```bash
python -c "import google.generativeai; print('OK:', google.generativeai.__version__)"
```

### Step 3 — Dry-run the context engine

```bash
python tui-terminal/intel/context_engine.py --dry-run
```
Expected:
```
[context_engine] Starting. DB=...props.db  dry_run=True  budget=10/day
```
Polls every 60s. If a volatile line is detected you'll see a `[DRY RUN]` log line. Nothing is written to DB. Hit Ctrl+C to stop.

### Step 4 — Live mode

```bash
python tui-terminal/intel/context_engine.py
```
Leave running in its own Git Bash tab alongside the ingester.

### Step 5 — Verify Context Wing populates

After a trigger fires, check the DB:
```bash
sqlite3 tui-terminal/props.db "SELECT player_id, summary, trigger, created_at FROM news_context ORDER BY created_at DESC LIMIT 5;"
```
The TUI Context Wing (left panel) auto-refreshes every 5s and will show intel entries automatically.

---

## context_engine.py — Design Summary

| Concern | Decision |
|---|---|
| Poll interval | 60 seconds |
| Volatility window | 15 minutes |
| PP/UD threshold | ≥ 1.0pt move |
| Kalshi threshold | ≥ 10% price move |
| Debounce | Skips player if processed within last 30 min |
| Gemini model | `gemini-2.0-flash` with `google_search_retrieval` |
| Prompt | "Search for latest news on [Name]. Why is their line moving? Injuries, rest, coach comments. 15 words or less." |
| Budget cap | 10 Gemini calls/day, tracked in `gemini_budget` table (auto-created) |
| .env loading | Auto-loads `tui-terminal/.env` via python-dotenv |
| DB writes | `news_context` table — `player_id, stat_type, summary, source_api='gemini', trigger, created_at` |
| ContextWing | Already reads `news_context` automatically — no changes needed to widget |

---

## File Locations Summary

```
tui-terminal/
├── props.db                        ← TUI SQLite (populated by Rust ingester)
├── bookmark-4.md                   ← this file
├── .env                            ← GEMINI_API_KEY=AIzaSy... (already set)
├── src/
│   ├── config.rs                   ← PP=120s, UD=90s defaults (CHANGED this session)
│   └── ...
├── tui/
│   ├── requirements.txt            ← google-generativeai>=0.7.0 already listed
│   └── widgets/
│       └── context_wing.py         ← reads news_context, no changes needed
└── intel/
    └── context_engine.py           ← NEW this session — Phase 3 core
```

---

## Phase 4 — Next Up: Heatmap / Secondary Display

Build the secondary lightweight Textual app for the top-mounted monitor:
- Sport-tile grid (NBA / NHL / MLB) colored by ML model confidence vs Kalshi discrepancy
- Flashes green on high-confidence cross-platform edge
- Large text only — readable from 5 feet
- Reads same `props.db` (no new ingester work needed)

Stick to Prompt 4 from `cpt_planning_markdowns/4_Prompt Engineering Preliminary.md`.
