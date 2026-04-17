# PEGASUS Bookmark — Session 11 (Start-of-Session)
**Date: 2026-04-15 | Steps 1–10 COMPLETE | Step 11 Gated (Oct 2026)**

---

## What Was Done in Session 10

| Sub-step | File(s) | Summary |
|---|---|---|
| 10a | `PEGASUS/pipeline/draftkings_odds.py` | DK sportsbook unofficial API; `get_dk_props()` + `get_implied_prob()`; markets/selections parser; 3s rate-limit; session cache; non-fatal |
| 10a wire | `PEGASUS/pipeline/pick_selector.py` | `get_picks()` pre-loads DK per sport; `_build_pick()` sets `implied_probability` via `remove_vig()` |
| 10b/10c | `PEGASUS/api/main.py` | FastAPI port 8600; Turso-first with JSON snapshot fallback; GET /picks/{date}, GET /picks/{date}/{player}, GET /health; CORS open; query params: sport, min_tier, direction, limit |
| 10d | `PEGASUS/docs/mobile-step10.md` | Full pick card design spec: tier badge colors, edge bar, calibrated prob, situation pills, implied prob row, true_ev, TypeScript interface, nullable contract |
| Bookmarks | `bookmark-11.md`, `comprehensive_summary.md` | Both updated. Memory files updated. |

**Validation (2026-04-15):** All imports clean. FastAPI routes: /health, /picks/{date}, /picks/{date}/{player_name}. 342-pick snapshot loads. NBA T2+ filter → 74 picks. DK client imports OK (returns {} — no games today).

---

## Full Architecture (Step 10 baseline)

```
ORCHESTRATOR (existing — runs first, PEGASUS never touches it)
├── Predictions → NHL/NBA/MLB SQLite
├── pp-sync     → marks is_smart_pick=1
└── Turso sync  → production predictions / smart_picks tables

PEGASUS/run_daily.py  (run AFTER orchestrator finishes)
├── pick_selector.get_picks(smart_picks_only=True)
│     ├── SQLite READ-ONLY per sport
│     ├── MLB: mlb_ml_reader → 60/40 XGBoost blend
│     ├── draftkings_odds.get_dk_props() → implied_probability (optional, non-fatal)
│     ├── calibration tables → calibrated_probability
│     ├── tier_from_edge() → T1–T4
│     └── situational.intel → flags (advisory only)
├── _write_json() → PEGASUS/data/picks/picks_{date}.json
└── sync_to_turso() → Turso pegasus_picks table

PEGASUS/api/main.py  (separate process)
uvicorn PEGASUS.api.main:app --port 8600
├── GET /health                          → last snapshot + counts
├── GET /picks/{date}?sport=&min_tier=   → Turso → snapshot fallback
└── GET /picks/{date}/{player_name}      → player filter
    Swagger: http://localhost:8600/docs

Mobile (future):
→ hits PEGASUS FastAPI (port 8600) instead of Supabase daily_props
→ renders PEGASUSPick card per docs/mobile-step10.md
```

---

## Key Implementation Notes for Session 11

### DraftKings API (draftkings_odds.py)
- The `draft-kings` PyPI package is for DFS fantasy — NOT sportsbook odds. We use raw requests.
- Confirmed working endpoint: `sportsbook-nash.draftkings.com/api/sportscontent/dkusoh/v1/leagues/{league_id}/categories/{category_id}`
- League IDs: NBA=42648, NHL=42133, MLB=84240
- Player prop category IDs: NBA=1000074, NHL=1000096, MLB=1000045
- Rate-limit: 2nd consecutive call times out. 3s `_MIN_INTERVAL` mitigates. Non-fatal.
- DK lines not posted until ~1h before tip. Returns `{}` earlier in the day — expected.

### FastAPI (api/main.py)
- Run from repo root: `uvicorn PEGASUS.api.main:app --port 8600 --reload`
- Module path must be `PEGASUS.api.main` (not a relative path)
- Tries Turso first; if Turso returns 0 rows for all sports, falls back to JSON snapshot
- Turso read is per-sport (3 async calls for "all" query)

### pick_selector.py changes (Step 10)
Three additions:
1. Import guard: `try: from PEGASUS.pipeline.draftkings_odds import get_dk_props; _DK_AVAILABLE = True`
2. In `get_picks()` loop: `dk_data_for_sp = get_dk_props(sp, game_date)` (non-fatal)
3. In `_build_pick()`: DK lookup → `remove_vig()` → `implied_prob` → passed as `implied_probability=implied_prob`

---

## Open Issues Coming Into Session 11

| # | Issue | Severity | Fix |
|---|---|---|---|
| 1 | `no such column: minutes_played` in NBA intel USAGE_BOOST | Low | `situational/intel.py` NBA fallback path |
| 2 | `pegasus_picks` Turso may be missing `implied_probability`/`true_ev` columns | Med | Run on Turso console: `ALTER TABLE pegasus_picks ADD COLUMN implied_probability REAL; ALTER TABLE pegasus_picks ADD COLUMN true_ev REAL;` |
| 3 | DK rate-limit: 2nd/3rd sport in same run may timeout | Low | Non-fatal. Already handled. Could add sleep between sports if needed. |
| 4 | NHL hits/blocked_shots not generating (V6 scope) | Low | Next season — season ends ~Apr 18 |
| 5 | Mobile not yet wired to PEGASUS API | Med | Add `PEGASUS_API_URL` env + PEGASUSPick type in `mobile/src/` |
| 6 | MLB Turso smart-picks silent failure (production, not PEGASUS) | Low | Investigate when relevant |

---

## Step 11 — Game Lines ML (GATED — do not start until Oct 2026)

Requires a full 2026 regular season's worth of game-level data (pace, totals, back-to-backs).

Plan when ready:
- XGBoost model for game pace / scoring environment
- Back-to-back / travel fatigue features
- Calibrate with 4-way temporal split (same as MLB)
- Integrate as advisory `game_context_flag` in pick_selector — never modifies probability/edge
- PEGASUS shadow audit required before activating

---

## Recommended Session 11 Work (while Step 11 is gated)

**Option A — Fix minutes_played bug (Issue #1):**
In `PEGASUS/situational/intel.py`, the NBA USAGE_BOOST path queries `minutes_played` which
doesn't exist in the NBA game_logs schema. Fix the column name or add a graceful fallback.
File to read first: `PEGASUS/situational/intel.py` (find the NBA minutes_played query).

**Option B — Wire mobile to PEGASUS API:**
In `mobile/src/`, replace the Supabase `daily_props` fetch with a call to
`http://{PEGASUS_HOST}:8600/picks/{date}`. Add `PEGASUSPick` TypeScript interface
(full spec in `PEGASUS/docs/mobile-step10.md`). Add `PEGASUS_API_URL` to app config.

**Option C — Validate end-to-end DK implied_probability:**
Wait until NBA playoffs have games with active DK lines. Run `run_daily.py` and confirm
`implied_probability` is populating on picks. Check a few picks in the JSON snapshot.

---

## Prompt for Session 11 Agent

```
I'm continuing work on PEGASUS — a parallel read-only prediction system built on top
of the existing SportsPredictor orchestrator. PEGASUS lives entirely in PEGASUS/ and
never modifies existing files outside that directory (Rule 2).

PEGASUS is STANDALONE — NOT wired into start_orchestrator.bat.
All credentials go in root .env only.

Steps 1-10 are COMPLETE. Start by reading:
1. PEGASUS/bookmarks/bookmark-11.md — current state + open issues
2. PEGASUS/bookmarks/comprehensive_summary.md — full project context

Step 11 (Game Lines ML) is GATED until Oct 2026.

Recommended work for this session (pick one):

A. Fix `no such column: minutes_played` bug in PEGASUS/situational/intel.py
   The NBA USAGE_BOOST path references a column that doesn't exist. Fix gracefully.

B. Wire mobile/src/ to PEGASUS FastAPI (port 8600) instead of Supabase daily_props.
   TypeScript interface + API call update. Design spec: PEGASUS/docs/mobile-step10.md.
   This is in mobile/src/ — Rule 2 allows this (mobile is not production backend).

C. Any other maintenance task from the open issues list in bookmark-11.md.

Do NOT touch: orchestrator.py, sync/supabase_sync.py, sync/turso_sync.py, shared/*,
nhl/, nba/, mlb/ scripts, or any production file outside PEGASUS/ (except mobile/src/).
```
