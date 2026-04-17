# PEGASUS Bookmark — Session 8
**Date: 2026-04-15**

---

## Completed This Session

- [x] `PEGASUS/sync/turso_sync.py` — Step 8 complete (PEGASUS Turso sync)
- [x] `PEGASUS/run_daily.py` — Step 6 wired (Turso sync after JSON write)
- [x] Version string bumped from `step7` → `step8` in `run_daily.py`
- [x] `PEGASUS/bookmarks/bookmark-08.md` (this file)
- [x] `PEGASUS/bookmarks/comprehensive_summary.md` — updated with Step 8

No production files modified. Rule 2 intact.

---

## Files Created / Modified This Session

```
PEGASUS/sync/turso_sync.py    (NEW — Step 8)
PEGASUS/run_daily.py          (MODIFIED — Step 6 Turso sync block + step8 version)
PEGASUS/bookmarks/bookmark-08.md          (NEW — this)
PEGASUS/bookmarks/comprehensive_summary.md (UPDATED)
```

---

## turso_sync.py Architecture

### Design decisions
- Writes to `pegasus_picks` table — **separate from existing `predictions` table** to avoid
  any conflict with the production Turso sync layer.
- Uses `INSERT OR REPLACE` (not `INSERT OR IGNORE`) so re-runs update stale data when
  calibrated_probability or situation_flags change.
- `UNIQUE(player_name, prop, game_date, sport)` — same upsert key as specified in PLAN.md.
- Each sport writes to its own Turso DB: NHL → `TURSO_NHL_URL/TOKEN`,
  NBA → `TURSO_NBA_URL/TOKEN`, MLB → `TURSO_MLB_URL/TOKEN`.
- Table DDL (`CREATE TABLE IF NOT EXISTS`) runs before every sync — idempotent.

### Public API
```python
from PEGASUS.sync.turso_sync import sync_to_turso

results = sync_to_turso(
    picks=picks,          # List[PEGASUSPick] or List[dict]
    game_date="2026-04-15",
    sports=["nhl","nba","mlb"],  # optional — inferred from picks if omitted
)
# returns {"nhl": 44, "nba": 130, "mlb": 168}
```

### `pegasus_picks` table columns
```
id, game_date, player_name, team, sport, prop, line, direction, odds_type,
raw_stat_probability, ml_probability, blended_probability, calibrated_probability,
break_even, ai_edge, vs_naive_edge, tier,
situation_flag, situation_modifier, situation_notes,
model_version, source_prediction_id, usage_boost,
pegasus_version, synced_at
```

### Standalone CLI
```bash
python PEGASUS/sync/turso_sync.py --date 2026-04-15
python PEGASUS/sync/turso_sync.py --date 2026-04-15 --sport nba
```
Reads from the existing JSON snapshot (`PEGASUS/data/picks/picks_{date}.json`).

### Non-fatal wiring in run_daily.py
```
Step 5: _write_json()   → PEGASUS/data/picks/picks_{date}.json
Step 6: sync_to_turso() → Turso pegasus_picks (non-fatal, logs on failure)
Step 7: _print_summary() → terminal output
```

---

## Known Issues (carried forward)

1. `no such column: minutes_played` — USAGE_BOOST in NBA situational intel. Pre-existing.
2. Unicode `→` renders as `?` on Windows cp1252 — cosmetic only. JSON output is clean UTF-8.
3. MLB Turso smart-picks silent failure noted in Apr 6 handoff — not investigated yet.
   PEGASUS writes to `pegasus_picks` table (not `predictions`), so this does NOT affect
   PEGASUS sync. Carry to Step 9 investigation.

---

## Exact Next Step (start of Session 9)

**Step 9: Odds Integration (Phase 1a + 1b)**

```
1a. PrizePicks MLB extension
    - Existing shared/prizepicks_client.py handles NHL/NBA
    - Create PEGASUS/pipeline/prizepicks_client.py as copy + extension for league_id=2
    - Do NOT modify shared/prizepicks_client.py

1b. The Odds API integration (free tier — 500 req/month)
    - Wire implied_probability into PEGASUS picks
    - Target display: "Model: 72% | Sportsbook: 54% | Edge: +18%"
    - When wired: implied_probability and true_ev stop being NULL in daily_props
```

Read first in Session 9:
1. `PEGASUS/bookmarks/bookmark-08.md` (this file)
2. `PEGASUS/bookmarks/comprehensive_summary.md`
3. `PEGASUS/PLAN.md` Step 9 section
4. `shared/prizepicks_client.py` — existing client to copy + extend

---

## Prompt for Session 9 Agent

```
I'm continuing work on PEGASUS — a parallel read-only prediction system built on top
of the existing SportsPredictor orchestrator. PEGASUS lives entirely in PEGASUS/ and
never modifies existing files outside that directory (Rule 2).

Start by reading:
1. PEGASUS/bookmarks/bookmark-08.md — session 8 results + exact next steps
2. PEGASUS/bookmarks/comprehensive_summary.md — full project context
3. PEGASUS/PLAN.md Step 9 section
4. shared/prizepicks_client.py — existing PP client to copy + extend for MLB

Steps 1-8 complete. Today's task is Step 9: Odds Integration.

Build PEGASUS/pipeline/prizepicks_client.py (copy of shared/ version + MLB league_id=2 support).
Then research The Odds API free tier and design the odds integration module.

Do NOT touch: orchestrator.py, sync/turso_sync.py, shared/prizepicks_client.py,
or any file outside PEGASUS/.
```
