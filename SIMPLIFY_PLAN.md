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

### 3B — Fill Turso Gaps ✅ COMPLETE (commit 6f032dd1)

- [x] Step 1: ALTER TABLE run on all 4 SQLite DBs — added ai_edge, ai_ev_2/3/4leg, game_time.
  Golf also got odds_type (was missing). Applied directly to local .db files.
- [x] Step 2: supabase_sync.py SQLite write-back now also persists ai_edge + ai_ev_* so Turso
  picks them up on next smart-picks sync. (The write-back to SQLite stays even after Supabase
  is fully removed — it's how Turso gets these values.)
- [x] Step 3: sync_game_times() added to turso_sync.py — reads prizepicks_lines.db, UPDATEs
  predictions.game_time in Turso. Wired into run_sync 'all' + new 'game-times' operation.
- [x] Step 4: sync_game_scores() + GAME_SCORES_DDL added to turso_sync.py — game_scores table
  mirrors Supabase daily_games schema exactly.
- [x] Step 5: game_sync.py fully rewritten — Turso HTTP pipeline replaces Supabase client.
  Removed _lock_started_games (was locking daily_props, a Supabase-only concept).
- [x] Step 6: Backfill historical ai_edge — complete (f82ec62a):
  - Ran turso_migrate --fix-schema to add ai_edge/ai_ev_*/game_time to all 4 Turso DBs
  - Computed ai_edge directly from probability + breakeven formula for 131,559 SQLite rows
  - Synced to Turso: NBA 52,458 rows (32 dates), NHL 18,606 (32 dates), MLB 25,285 (15 dates)
  - Fixed pp-sync: added SmartPickSelector write-back as step 2 so future runs populate ai_edge in SQLite before Turso reads it

### 3C — Remove Supabase from Dashboard ✅ COMPLETE (4fb6a81d)

- [x] Remove 4 remaining get_supabase() call sites (all `if not db_path.exists():` guards → early return)
- [x] Replace "Supabase Sync" System tab section with Turso row count query (4 sports)
- [x] Remove get_supabase() stub
- [x] Clean up Supabase references in docstrings

### 3D — Remove Supabase from Orchestrator Write Path ✅ COMPLETE (4fb6a81d)

- [x] `SUPABASE_SYNC_AVAILABLE = False` (removed import block)
- [x] Prediction sync: replaced Supabase block with Turso-only call
- [x] Grading sync: extracted Turso from inside Supabase block, removed Supabase block
- [x] pp-sync: removed early-return check + full Supabase block; Turso-only now
- [x] supabase_local_sync imports removed from H+B and SZLN operations

### 3E — Archive Supabase Sync Code ✅ COMPLETE (4fb6a81d)
- [x] sync/supabase_sync.py → _archive/supabase_sync.py
- [x] sync/backfill_smart_picks.py → _archive/
- [x] sync/backfill_supabase.py → _archive/
- [x] sync/purge_stale_rows.py → _archive/
- [x] sync/config.py: removed SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
- [ ] Supabase account: leave dormant for 2 weeks before deleting

---

## Phase 4 — Remote Access via Streamlit Cloud (TODO)

1. Finish Phase 3 first (dashboard reads Turso, no Supabase)
2. Set TURSO_*_URL and TURSO_*_TOKEN env vars in Streamlit Cloud secrets UI
3. Deploy dashboards/cloud_dashboard.py to share.streamlit.io
4. Dashboard becomes accessible from any browser, no local machine needed
5. Orchestrator (predictions, grading) still runs locally on desktop

---

## Phase 5 — Remaining File Cleanup (PARTIAL)

**Deleted:**
- [x] mlb/database/mlb_game_predictions.db (0 bytes)
- [x] nhl/database/nhl_predictions.db (0 bytes, deprecated)

**Still TODO:**
- [ ] nhl/database/hits_blocks.db (experimental, no sync plan — delete when NHL season confirmed over)

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
| game-times | ✅ working | predictions (UPDATE game_time) |
| game-scores | ✅ working | game_scores (new table) |
| smart-picks edge | ✅ working | predictions (UPDATE ai_edge, ai_ev_*) |

---

## Handoff Prompt (paste at start of next session)

```
We are finishing the simplification of SportsPredictor to SQLite local + Turso cloud only.
VPS is killed. Supabase is fully removed from code. FreePicks mobile app is dead.

CURRENT STATE (all committed, pushed to master):
- Phase 1 ✅ Git cleanup (4b5bc02b)
- Phase 2 ✅ VPS archived (ac6eb42b)
- Phase 3A ✅ Turso gap audit complete
- Phase 3B ✅ Turso gaps filled (6f032dd1)
- Phase 3C ✅ Dashboard: all Supabase call sites removed, System tab replaced (4fb6a81d)
- Phase 3D ✅ Orchestrator: SUPABASE_SYNC_AVAILABLE=False, all sync paths → Turso (4fb6a81d)
- Phase 3E ✅ Archived: supabase_sync.py, backfill_*.py, purge_stale_rows.py, config.py cleaned (4fb6a81d)
- Phase 5 PARTIAL: deleted mlb_game_predictions.db, nhl_predictions.db (0-byte files)

REMAINING TASKS:

1. Phase 4 — Streamlit Cloud deploy for remote access:
   Dashboard already reads Turso. Set TURSO_*_URL + TURSO_*_TOKEN in Streamlit Cloud secrets.
   Deploy dashboards/cloud_dashboard.py to share.streamlit.io → permanent public URL.

3. Phase 5 remaining:
   - Delete nhl/database/hits_blocks.db when NHL season confirmed over

Key files:
- SIMPLIFY_PLAN.md — this plan
- dashboards/cloud_dashboard.py — Turso-only, no Supabase
- orchestrator.py — SUPABASE_SYNC_AVAILABLE=False, all writes go to Turso
- sync/turso_sync.py — the only cloud sync layer
```
