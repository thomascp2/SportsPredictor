# Simplification Plan — Kill VPS + Supabase, SQLite → Turso Only

**Goal:** One pipeline. SQLite local → Turso cloud. No VPS. No Supabase. Dashboard runs from Turso.
**Rule:** NOTHING gets removed from a provider until its data exists in Turso first.

---

## Phase 1 — Git Cleanup ✅ COMPLETE
- [x] Added parlay_lottery/, gsd_module/, *.duckdb, mlb_feature_store/.venv+data/, session log patterns to .gitignore
- [x] Untracked start_orchestrator.bat (had API keys — was incorrectly committed)
- [x] Deleted vpslog*.txt and Next Session*.txt junk files
- [x] Committed and pushed to GitHub (commit 4b5bc02b)

**What NOT to commit:** start_orchestrator.bat always stays gitignored (has API keys).

---

## Phase 2 — Kill VPS Connection ✅ COMPLETE
- [x] Confirmed no Windows Task Scheduler tasks pointing at VPS
- [x] Archived entire deploy/ folder → _archive/deploy_vps_migration/ (commit ac6eb42b)
  - fetch_and_push_pp.bat (SCP'd prizepicks_lines.db to 159.203.93.232)
  - systemd/*.service files
  - vps_setup.sh, transfer.sh, migration docs
- [x] Committed and pushed to GitHub

**Remaining manual step (user does this):** Log into DigitalOcean dashboard → Destroy Droplet 159.203.93.232. Stop paying.

---

## Phase 3 — Supabase → Turso Migration (IN PROGRESS)

### Rule: Fill Turso gaps FIRST, then cut Supabase write path, then clean code.

### 3A — Audit: What Supabase has that Turso doesn't ✅ AUDITED

**Gap table — fields written to Supabase daily_props but NOT in Turso predictions:**

| Field | Where computed | In SQLite? | In Turso? | Fix needed |
|-------|---------------|-----------|----------|-----------|
| ai_edge | supabase_sync (from probability - breakeven) | NO | NO | Add ALTER TABLE + write-back |
| ai_ev_2leg/3leg/4leg | supabase_sync (EV calc) | NO | NO | Add ALTER TABLE + write-back |
| game_time | sync_game_times() from PP start_time | NO | NO | New turso_sync operation |
| status ('open'/'graded') | supabase_sync | NO | NO | Skip — can derive from prediction_outcomes |
| actual_value | supabase_sync grading | In prediction_outcomes | In Turso prediction_outcomes | OK — join needed |
| result / graded_at | supabase_sync grading | In prediction_outcomes | In Turso prediction_outcomes | OK — join needed |

**Gap table — tables in Supabase NOT in Turso:**

| Table | Purpose | Fix needed |
|-------|---------|-----------|
| daily_games | Live game scores (NBA/NHL) | Add game_scores table to Turso; redirect game_sync.py |
| model_performance | Daily aggregate hit rates | Compute from Turso prediction_outcomes on demand; skip sync |

### 3B — Fill Turso Gaps (TODO — do this next session)

**Step 1: Add missing columns to SQLite predictions (all 4 sport DBs)**
```sql
ALTER TABLE predictions ADD COLUMN ai_edge REAL;
ALTER TABLE predictions ADD COLUMN ai_ev_2leg REAL;
ALTER TABLE predictions ADD COLUMN ai_ev_3leg REAL;
ALTER TABLE predictions ADD COLUMN ai_ev_4leg REAL;
ALTER TABLE predictions ADD COLUMN game_time TEXT;
```
Run for: nhl_predictions_v2.db, nba_predictions.db, mlb_predictions.db, golf_predictions.db

**Step 2: Update SQLite write-back in supabase_sync.py**
In sync_smart_picks() SQLite write-back block (~line 357-376), also write:
- ai_edge = pick.edge
- ai_ev_2leg = pick.ev_2leg
- ai_ev_3leg = pick.ev_3leg
- ai_ev_4leg = pick.ev_4leg

**Step 3: Add sync_game_times to turso_sync.py**
New operation: query prizepicks_lines.db for start_time by team, UPDATE predictions.game_time in Turso.
Mirror the logic from supabase_sync.sync_game_times().

**Step 4: Add game_scores table to Turso**
Create in turso_sync.py:
```sql
CREATE TABLE IF NOT EXISTS game_scores (
  game_date TEXT, sport TEXT, game_id TEXT,
  home_team TEXT, away_team TEXT,
  home_score INTEGER, away_score INTEGER,
  status TEXT, period TEXT, clock TEXT, start_time TEXT,
  PRIMARY KEY (game_date, sport, game_id)
)
```

**Step 5: Redirect game_sync.py → Turso instead of Supabase**
Replace Supabase upsert with Turso HTTP pipeline INSERT OR REPLACE.
One turso_request() call per sport (NBA = nba Turso DB, NHL = nhl Turso DB).

**Step 6: Backfill historical ai_edge data**
Run supabase_sync sync_smart_picks() once more so it writes back ai_edge to SQLite.
Then run turso_sync --operation smart-picks --date <range> to push to Turso.

### 3C — Remove Supabase from Dashboard (PARTIAL — needs finishing)

**Already done (safe — all were local SQLite primary, Supabase was fallback only):**
- [x] Replaced fetch_pipeline_status() with Turso version
- [x] Removed Supabase fallback from fetch_season_projections()
- [x] Added get_supabase() stub → returns None (safe, all fallback branches check `if sb is None`)
- [x] Changed dashboard docstring to reference Turso

**Still TODO (finish after 3B is complete):**
- [ ] Remove 4 remaining get_supabase() call sites (lines ~1456, 1543, 1649, 1706) — safe to remove now (all local-DB-missing fallbacks) but leaving until after Turso parity confirmed
- [ ] Remove "Supabase Sync" section from System tab (lines ~3585-3611) — replace with Turso row counts
- [ ] Remove get_supabase() stub entirely once all call sites are gone

### 3D — Remove Supabase from Orchestrator Write Path (TODO — do AFTER 3B+3C)

In orchestrator.py:
- Line 123: `from sync.supabase_sync import SupabaseSync` → delete
- Line 124: `SUPABASE_SYNC_AVAILABLE = True` → hardcode False
- Lines 760, 933: supabase_sync calls after predictions/grading → delete (guarded by flag, so just set flag False)
- Line 2601: supabase check in pp-sync → delete
- Lines 3514, 3556: supabase_local_sync imports → delete

Move game_time sync and odds_type sync logic (currently in supabase_sync) into turso_sync as standalone operations.

### 3E — Archive Supabase Sync Code (TODO — after 3D confirmed working)
- Move sync/supabase_sync.py → _archive/supabase_sync.py
- Move sync/game_sync.py → update in place (Turso version) 
- Supabase account: leave dormant for 2 weeks before deleting

---

## Phase 4 — Remote Access via Streamlit Cloud (TODO)

1. Finish Phase 3 first (dashboard reads Turso, no Supabase)
2. Set TURSO_*_URL and TURSO_*_TOKEN env vars in Streamlit Cloud secrets UI
3. Deploy dashboards/cloud_dashboard.py to share.streamlit.io
4. Dashboard becomes accessible from any browser, no local machine needed
5. Orchestrator (predictions, grading) still runs locally on desktop

---

## Phase 5 — Remaining File Cleanup (TODO — after Phase 3)

**Delete these files:**
- mlb/database/mlb_game_predictions.db (0 bytes, unused)
- nhl/database/nhl_predictions.db (0 bytes, deprecated)
- nhl/database/hits_blocks.db (experimental, no sync plan)

**Archive these files (to _archive/):**
- sync/supabase_sync.py (after orchestrator write path removed in 3D)
- shared/supabase_local_sync.py (if it exists in main tree)

**Do NOT touch:**
- PEGASUS — leave entirely as-is
- ML flags — no retrain review = no changes
- mlb_feature_store/ — working, leave it
- parlay_lottery/ — out of scope

---

## Turso Sync Operations (current + planned)

| Operation | Status | Tables |
|-----------|--------|--------|
| predictions | ✅ working | predictions |
| smart-picks | ✅ working | predictions (UPDATE is_smart_pick, ai_tier, odds_type) |
| grading | ✅ working | prediction_outcomes |
| game-predictions | ✅ working | game_predictions |
| game-outcomes | ✅ working | game_prediction_outcomes |
| game-times | ❌ TODO | predictions (UPDATE game_time) |
| game-scores | ❌ TODO | game_scores (new table) |
| smart-picks edge | ❌ TODO | predictions (UPDATE ai_edge, ai_ev_*) |

---

## Handoff Prompt (paste at start of next session)

```
We are in the middle of simplifying our SportsPredictor system:
- Kill VPS ✅ — deploy/ archived, no scheduled tasks found
- Kill Supabase — migrating everything to Turso instead
- Local SQLite → Turso as the only cloud db provider

CURRENT STATE: Git is clean and pushed. Plan is at SIMPLIFY_PLAN.md in repo root.

RULE: Nothing gets removed from Supabase until Turso has the data first.

NEXT TASK: Phase 3B — Fill Turso gaps:
1. ALTER TABLE to add ai_edge, ai_ev_2leg/3leg/4leg, game_time to all 4 SQLite prediction DBs
2. Update supabase_sync.py SQLite write-back to also write ai_edge + ai_ev_* (even though we're removing Supabase, the write-back code that persists to SQLite must remain and go to turso_sync)
3. Add sync_game_times() to turso_sync.py (read from prizepicks_lines.db, UPDATE predictions.game_time in Turso)
4. Add game_scores table to Turso via turso_sync.py
5. Redirect game_sync.py to write game scores to Turso instead of Supabase
6. Backfill: run turso_sync --operation smart-picks for recent dates to push ai_edge to Turso

After 3B is done, finish 3C (remove remaining 4 get_supabase() call sites from dashboard) and 3D (remove supabase_sync from orchestrator write path).

Key files:
- sync/turso_sync.py — add new operations here
- sync/supabase_sync.py — SQLite write-back section around line 357-376
- sync/game_sync.py — redirect to Turso
- dashboards/cloud_dashboard.py — 4 remaining get_supabase() calls at lines ~1456, 1543, 1649, 1706
- orchestrator.py — supabase_sync calls at lines 760, 933, 2601, 3514, 3556
```
