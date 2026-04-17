# PEGASUS Bookmark — Session 10 (Start-of-Session)
**Date: 2026-04-15 | Steps 1–9 COMPLETE | Starting Step 10**

---

## What Was Done Before This Session (Steps 1–9)

| Step | File(s) | Summary |
|---|---|---|
| 1 | config.py, scaffold | Directory structure, paths, break-evens, tier thresholds |
| 2 | calibration/audit.py + tables | 6-check calibration audit; tables saved to data/calibration_tables/ |
| 3 | situational/flags.py + intel.py | HIGH_STAKES/DEAD_RUBBER/ELIMINATED/USAGE_BOOST flags; NBA playoffs live |
| 4 | pipeline/nhl_ml_reader.py | NHL ML audit — FAIL verdict; stat-only confirmed |
| 5 | pipeline/mlb_ml_reader.py | MLB XGBoost reader; 60/40 blend for 5 props |
| 6 | pipeline/pick_selector.py | Core pick builder; PEGASUSPick dataclass |
| 7 | run_daily.py | Daily runner; JSON snapshot output |
| 8 | sync/turso_sync.py | Turso upsert to pegasus_picks table |
| 9a | pipeline/prizepicks_client.py | In-memory live PP line fetcher; line movement detection |
| 9b | pipeline/odds_client.py | Odds API client; math utils; implied_probability stub |

**Validation (2026-04-15):** 342 picks, T1:112 T2:99 T3:13 T4:118, 11 MLB ML-blended, situational flags firing.

---

## PEGASUS Architecture (Step 9 baseline)

```
  ORCHESTRATOR (existing — runs first, PEGASUS never touches it)
  ├── Predictions → NHL/NBA/MLB SQLite  (nhl/nba/mlb predictions tables)
  ├── pp-sync     → marks is_smart_pick=1 on PP-matched rows
  └── Turso sync  → mirrors predictions/ smart_picks/ grading to per-sport Turso DBs

  PEGASUS/run_daily.py  (standalone — runs AFTER orchestrator finishes)
  │
  ├── 1. _check_readiness()          reads SQLite prediction counts
  ├── 2. pick_selector.get_picks()
  │       ├── reads SQLite (is_smart_pick=1 filter, READ-ONLY)
  │       ├── MLB: blends with mlb_feature_store DuckDB (XGBoost)
  │       ├── applies calibration tables → calibrated_probability
  │       ├── computes ai_edge, true_ev, tier
  │       └── attaches situational flags (advisory, display-only)
  ├── 3. _write_json()               → PEGASUS/data/picks/picks_{date}.json
  ├── 4. sync_to_turso()             → Turso pegasus_picks table (per-sport)
  └── 5. _print_summary()            → terminal
```

---

## Current Coverage (Player Props Only)

### NHL — Stat-only (LR models trained but FAIL audit)
| Prop | Lines | ML |
|---|---|---|
| points | O0.5, O1.5 | None |
| shots | O1.5, O2.5, O3.5 | None |
| hits* | O0.5-O3.5 | None |
| blocked_shots* | O0.5, O1.5 | None |
*V6 prediction script generates points/shots only; hits/blocked_shots predictions not yet in DB.

### NBA — Stat-only (LEARNING_MODE=True; reverted after Mar 15 disaster)
| Prop | Notes |
|---|---|
| points, rebounds, assists | Core props |
| pts_rebs, pts_asts, rebs_asts, pra | Combo props |
| threes | OVER suppressed (guard in smart_pick_selector.py) |
| steals, blocks, stocks, turnovers, fantasy | Low-volume |

### MLB — 60/40 XGBoost blend for BLEND_PROPS; stat-only for rest
| Prop | ML Model | Notes |
|---|---|---|
| hits | XGBoost (Poisson CDF) | BLEND — 60% ML + 40% stat |
| total_bases | XGBoost (Poisson CDF) | BLEND |
| strikeouts | XGBoost (Normal CDF, σ=1.8) | BLEND |
| walks | XGBoost (Poisson CDF) | BLEND |
| outs_recorded | XGBoost (Normal CDF, σ=2.5) | BLEND |
| home_runs | Stat-only | EXCLUDED from ML permanently (low-n, high variance) |
| pitcher props | Stat-only | strikeouts, outs_recorded, walks_allowed, hits_allowed |

### No Coverage (not in scope)
- Game lines (moneyline / spread / total) — Step 11 (future)
- Golf — separate system, no PEGASUS integration
- NFL — not in PEGASUS scope

---

## Credentials (all in root `.env`)

```
TURSO_NHL_URL / TURSO_NHL_TOKEN
TURSO_NBA_URL / TURSO_NBA_TOKEN
TURSO_MLB_URL / TURSO_MLB_TOKEN
ODDS_API_KEY   (free tier — game totals only until paid plan)
```

PEGASUS does NOT use `start_orchestrator.bat`. Nothing PEGASUS touches belongs in any `.bat` file.

---

## Open Issues Coming Into Step 10

1. `no such column: minutes_played` — USAGE_BOOST detection in NBA intel, non-fatal
2. `pegasus_picks` Turso table: if Step 8 already created it before Step 9 added columns,
   run on Turso console: `ALTER TABLE pegasus_picks ADD COLUMN implied_probability REAL;`
   and: `ALTER TABLE pegasus_picks ADD COLUMN true_ev REAL;`
3. MLB Turso smart-picks silent failure (production, not PEGASUS) — low priority
4. NHL hits/blocked_shots predictions not generating — V6 script scope issue

---

## Step 10: FastAPI + Mobile + DraftKings Odds

### 10a — DraftKings Player Prop Odds (FREE — do this first)

**Background:** The Odds API requires $30/month for player props. DraftKings has an
unofficial but extremely stable JSON API — no key, no registration, `pip install draft-kings`.
This gives us American odds (e.g. -115 UNDER) for player props across NBA/NHL/MLB, which
we convert to implied probability using our existing `american_to_implied()` function in
`PEGASUS/pipeline/odds_client.py`.

**Implementation:**
```python
# pip install draft-kings
from draft_kings import Sport, get_contests, get_available_players
# or use the sportsbook endpoint directly — research the current API shape first
```

**What to build:** `PEGASUS/pipeline/draftkings_odds.py`
- Fetch player prop lines + American odds for a sport/date from DraftKings
- Return `dict[(player_name_norm, prop): {"over_odds": int, "under_odds": int, "line": float}]`
- Use existing `american_to_implied()` + `remove_vig()` from `odds_client.py` to get fair prob
- Cache per (sport, date) per session — same pattern as prizepicks_client.py
- Non-fatal: return empty dict on any failure
- Wire into `pick_selector.get_picks()` as optional enrichment:
  DK odds → `remove_vig(over_odds, under_odds)` → `implied_probability` on PEGASUSPick

**BALLDONTLIE** as free official fallback if DK proves unstable:
- Register at balldontlie.io (free key)
- Add `BALLDONTLIE_API_KEY` to root `.env`
- Returns multi-book consensus implied probability — better signal than single-book

**ESPN note:** ESPN's existing API (already in use) has game-level totals only — no
player prop odds. Do NOT attempt to use ESPN for player prop implied probability.

**Note on ToS:** DraftKings unofficial is for personal research only — never
re-distribute the data or use it commercially.

---

### 10b — Mobile Data Source: Turso (NOT Supabase)

PEGASUS writes to **Turso** (`pegasus_picks` table). Mobile reads from Turso via FastAPI.
Supabase is the legacy backend for the old orchestrator data — PEGASUS does not touch it.

**Path: FastAPI reads Turso → mobile hits FastAPI**
- No Supabase bridge. No mixing backends.
- FastAPI (`PEGASUS/api/main.py`) queries Turso `pegasus_picks` and serves JSON
- Mobile update: point the picks screen at the PEGASUS FastAPI endpoint instead of Supabase `daily_props`
- This is a clean separation — PEGASUS data comes from PEGASUS infrastructure end-to-end

---

### 10c — FastAPI Skeleton

**What to build:** `PEGASUS/api/main.py`
- FastAPI app serving enriched pick data from JSON snapshots (no DB dependency for MVP)
- `GET /picks/{date}` — returns all picks for a date, optional `?sport=nba&min_tier=T2-STRONG`
- `GET /picks/{date}/{player_name}` — single player lookup
- `GET /health` — returns last snapshot date + pick counts per sport
- Read from `PEGASUS/data/picks/picks_{date}.json` for now; swap to Turso query later
- Install: `pip install fastapi uvicorn`
- Run: `uvicorn PEGASUS.api.main:app --port 8600`

---

### 10d — Mobile Pick Card Design Doc

**What to build:** `PEGASUS/docs/mobile-step10.md`
- Design spec for pick card update in `mobile/src/` (React Native / Expo)
- Tier badge: color-coded (T1=gold, T2=silver, T3=bronze, T4=gray)
- Edge bar: visual bar showing ai_edge from 0-30%
- Prob display: "Model: {calibrated_probability:.0%}" (replace raw probability)
- Situation badge: HIGH_STAKES / DEAD_RUBBER / ELIMINATED shown as pill
- When implied_probability is available: "Book: {implied_prob:.0%} | Edge: {ai_edge:+.1f}%"
- All new fields nullable — card renders normally if missing

---

### Files to Read Before Starting Session 10

1. `PEGASUS/bookmarks/bookmark-10.md` — this file
2. `PEGASUS/bookmarks/comprehensive_summary.md` — full context
3. `PEGASUS/pipeline/odds_client.py` — `american_to_implied()` + `remove_vig()` already built
4. `PEGASUS/pipeline/prizepicks_client.py` — pattern to follow for DK client
5. `sync/supabase_sync.py` — Supabase upsert pattern (READ-ONLY reference)
6. `supabase/migrations/001_initial_schema.sql` — daily_props schema
7. `PEGASUS/PLAN.md` Step 10 section (~lines 448-453)

---

## Prompt for Session 10 Agent

```
I'm continuing work on PEGASUS — a parallel read-only prediction system built on top
of the existing SportsPredictor orchestrator. PEGASUS lives entirely in PEGASUS/ and
never modifies existing files outside that directory (Rule 2).

PEGASUS is a STANDALONE system — NOT wired into start_orchestrator.bat.
All credentials go in the root .env only.

Start by reading:
1. PEGASUS/bookmarks/bookmark-10.md — current state + full Step 10 plan
2. PEGASUS/bookmarks/comprehensive_summary.md — full project context
3. PEGASUS/pipeline/odds_client.py — math utils already built (american_to_implied, remove_vig)
4. PEGASUS/pipeline/prizepicks_client.py — pattern to follow for the DK client
5. sync/supabase_sync.py — Supabase pattern (READ-ONLY reference, do not modify)
6. supabase/migrations/001_initial_schema.sql — daily_props schema

Steps 1-9 complete. Step 10 has four sub-tasks — do them in order:

10a. PEGASUS/pipeline/draftkings_odds.py
     Free DraftKings unofficial API for player prop American odds.
     pip install draft-kings — research current API shape first (it may have changed).
     Return dict[(norm_player_name, prop): {over_odds, under_odds, line}].
     Use american_to_implied() + remove_vig() from odds_client.py.
     Wire implied_probability into PEGASUSPick via pick_selector.get_picks().
     Non-fatal. Cache per (sport, date).

10b. PEGASUS/api/main.py (FastAPI — Turso as backend)
     FastAPI reads directly from Turso pegasus_picks (NOT Supabase).
     Supabase is legacy — PEGASUS does not write to or read from Supabase.
     Mobile points picks screen at this endpoint instead of Supabase daily_props.

10c. PEGASUS/api/main.py
     FastAPI skeleton. GET /picks/{date}, GET /picks/{date}/{player_name}, GET /health.
     Read from JSON snapshots for now. Port 8600.

10d. PEGASUS/docs/mobile-step10.md
     Pick card design doc: tier badge (T1=gold), edge bar, calibrated prob display,
     situation pill, implied prob when available. All new fields nullable.

Do NOT touch: orchestrator.py, sync/supabase_sync.py, sync/turso_sync.py, shared/*,
or any production file outside PEGASUS/.
```
