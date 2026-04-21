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
- [ ] Step 6: Backfill historical ai_edge — run next session:
  `python -m sync.turso_sync --sport all --operation smart-picks --date YYYY-MM-DD`
  for the last ~30 days of active prediction dates.

### 3C — Remove Supabase from Dashboard (PARTIAL)

**Done:**
- [x] Replaced fetch_pipeline_status() with Turso version
- [x] Removed Supabase fallback from fetch_season_projections()
- [x] get_supabase() stub → returns None (safe — all remaining callers check `if sb is None`)
- [x] Changed dashboard docstring to reference Turso

**Still TODO (3B is done — safe to finish now):**
- [ ] Remove 4 remaining get_supabase() call sites:
  - ~line 1454: fetch_ml_szln_picks() if-not-local-ok fallback
  - ~line 1541: fetch_player_projection() if-not-local-ok fallback
  - ~line 1647: fetch_hb_picks() if-not-local-ok fallback
  - ~line 1703: fetch_hb_history() if-not-local-ok fallback
  - ALL are `if not db_path.exists():` guards → just change to `return pd.DataFrame()` / `return {}` / `return []`
- [ ] Remove "Supabase Sync" section from System tab (~line 3585-3611) → replace with Turso row count query
- [ ] Remove get_supabase() stub once all call sites gone

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
We are mid-execution on simplifying SportsPredictor to SQLite local + Turso cloud only.
VPS is killed. Supabase is being deprecated. FreePicks mobile app is intentionally dead.

CURRENT STATE (all committed, pushed to master):
- Phase 1 ✅ Git cleanup (4b5bc02b)
- Phase 2 ✅ VPS archived (ac6eb42b)
- Phase 3A ✅ Turso gap audit complete
- Phase 3B ✅ Turso gaps filled (6f032dd1):
    - All 4 SQLite DBs: added ai_edge, ai_ev_2/3/4leg, game_time, golf+odds_type
    - supabase_sync.py write-back now persists ai_edge + ai_ev_* to SQLite
    - turso_sync.py: sync_smart_picks now syncs ai_edge + ai_ev_*
    - turso_sync.py: added sync_game_times() and sync_game_scores()
    - game_sync.py: fully rewritten to Turso, Supabase entirely removed from it
- Phase 3C PARTIAL (0bfe63ab): dashboard get_supabase() stubbed to return None (safe)

RULE: SQLite write-back in supabase_sync.py must STAY even after Supabase is removed.
It is now the mechanism that writes ai_edge/ai_ev_* from SmartPickSelector into SQLite
so Turso can pick them up. Do NOT delete that block.

NEXT TASKS in order:

1. Backfill ai_edge into Turso for recent dates (last 30 days of active picks):
   python -m sync.turso_sync --sport nba --operation smart-picks --date 2026-04-21
   (repeat for each date with predictions; can loop over date range)

2. Finish Phase 3C — dashboard cleanup (dashboards/cloud_dashboard.py):
   Remove 4 remaining get_supabase() call sites — all are `if not db_path.exists():` guards:
   - ~line 1454: fetch_ml_szln_picks() → replace fallback block with `return pd.DataFrame()`
   - ~line 1541: fetch_player_projection() → replace fallback block with `return None`
   - ~line 1647: fetch_hb_picks() → replace fallback block with `return {}`
   - ~line 1703: fetch_hb_history() → replace fallback block with `return []`
   Then remove the `def get_supabase(): return None` stub.
   Then replace "Supabase Sync" System tab section (~line 3585-3611) with Turso row count query.

3. Phase 3D — remove Supabase from orchestrator write path (orchestrator.py):
   - Lines ~123-126: remove supabase_sync import, hardcode SUPABASE_SYNC_AVAILABLE = False
   - Lines ~760, 933: supabase_sync calls already guarded — will auto-skip with flag=False
   - Lines ~2601: supabase check in pp-sync → just remove the early-return check
   - Lines ~3514, 3556: supabase_local_sync imports → delete (wrap in try/except or delete)
   Also: remove sync_odds_types() and sync_game_times() calls from orchestrator since Supabase
   is where those wrote to; turso_sync now handles game_times via 'all' operation.

4. Phase 3E — archive supabase code:
   Move sync/supabase_sync.py → _archive/supabase_sync.py
   sync/config.py: remove SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY lines

5. Phase 4 — Streamlit Cloud deploy for remote access:
   Dashboard already reads Turso. Set TURSO_*_URL + TURSO_*_TOKEN in Streamlit Cloud secrets.
   Deploy dashboards/cloud_dashboard.py to share.streamlit.io → permanent public URL.

6. Phase 5 — delete dead files:
   mlb/database/mlb_game_predictions.db (0 bytes)
   nhl/database/nhl_predictions.db (0 bytes, deprecated)

Key files:
- SIMPLIFY_PLAN.md — this plan (update as you go)
- dashboards/cloud_dashboard.py — 4 get_supabase() call sites + System tab section
- orchestrator.py — supabase_sync calls at ~760, 933, 2601, 3514, 3556
- sync/supabase_sync.py — archive after orchestrator is clean; keep SQLite write-back logic
- sync/turso_sync.py — new sync_game_times + sync_game_scores already added
- sync/config.py — remove Supabase vars after orchestrator cleaned
```
