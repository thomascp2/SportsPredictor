# Simplification Plan — Kill VPS + Supabase, SQLite → Turso Only

**Goal:** One pipeline. SQLite local → Turso cloud. No VPS. No Supabase. Dashboard runs from Turso.
**Rule:** NOTHING gets removed from a provider until its data exists in Turso first.

---

## Status Summary (as of 2026-04-21)

| Phase | Status | Commit |
|-------|--------|--------|
| 1 — Git cleanup | ✅ COMPLETE | 4b5bc02b |
| 2 — Kill VPS | ✅ COMPLETE | ac6eb42b |
| 3A — Turso gap audit | ✅ COMPLETE | — |
| 3B — Fill Turso gaps | ✅ COMPLETE | 6f032dd1 + f82ec62a |
| 3C — Dashboard cleanup | ✅ COMPLETE | 4fb6a81d |
| 3D — Orchestrator cleanup | ✅ COMPLETE | 4fb6a81d |
| 3E — Archive Supabase code | ✅ COMPLETE | 4fb6a81d |
| 3F — ai_edge backfill | ✅ COMPLETE | f82ec62a |
| 4 — Streamlit Cloud deploy | 🔲 NEXT | — |
| 5 — File cleanup | 🔲 PARTIAL | — |

**The codebase is now Supabase-free.** All cloud writes go through Turso. Dashboard reads Turso with SQLite fallback.

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

## Phase 3 — Supabase → Turso Migration ✅ COMPLETE

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

### 3B — Fill Turso Gaps ✅ COMPLETE (6f032dd1)

- [x] Step 1: ALTER TABLE run on all 4 SQLite DBs — added ai_edge, ai_ev_2/3/4leg, game_time.
  Golf also got odds_type (was missing). Applied directly to local .db files.
- [x] Step 2: supabase_sync.py SQLite write-back now also persists ai_edge + ai_ev_* so Turso
  picks them up on next smart-picks sync.
- [x] Step 3: sync_game_times() added to turso_sync.py — reads prizepicks_lines.db, UPDATEs
  predictions.game_time in Turso. Wired into run_sync 'all' + new 'game-times' operation.
- [x] Step 4: sync_game_scores() + GAME_SCORES_DDL added to turso_sync.py — game_scores table
  mirrors Supabase daily_games schema exactly.
- [x] Step 5: game_sync.py fully rewritten — Turso HTTP pipeline replaces Supabase client.
  Removed _lock_started_games (was locking daily_props, a Supabase-only concept).

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
- [ ] Supabase account: leave dormant until ~May 5 then delete

### 3F — ai_edge Backfill + pp-sync Fix ✅ COMPLETE (f82ec62a)

- [x] Ran `turso_migrate --fix-schema` — added ai_edge, ai_ev_2/3/4leg, game_time, odds_type to
  all 4 Turso DBs (game_lines over/under_odds also added as bonus)
- [x] Computed ai_edge directly from `(probability - breakeven) * 100` for 131,559 SQLite smart-pick rows
- [x] Synced to Turso: NBA 52,458 rows (32 dates), NHL 18,606 (32 dates), MLB 25,285 (15 dates)
- [x] Fixed orchestrator pp-sync: added SmartPickSelector write-back as step 2 (was only in
  archived supabase_sync.py). Going forward, every pp-sync run populates ai_edge in SQLite
  before Turso reads it.

---

## Phase 4 — Remote Access via Streamlit Cloud 🔲 NEXT

**Goal:** Dashboard accessible from any browser without the local machine running.

### Pre-deploy checklist
- [x] Dashboard reads Turso (no Supabase dependencies remaining)
- [x] All Turso credentials read via `os.getenv()` — compatible with st.secrets
- [ ] requirements.txt updated: remove `supabase`, add `libsql-client`
- [ ] `.streamlit/secrets.toml` template committed (values redacted)
- [ ] Shared module imports wrapped in try/except (shared/ won't exist on Cloud)

### Deploy steps
1. Fix requirements.txt and add `.streamlit/secrets.toml` template → commit + push
2. Go to share.streamlit.io → New app
3. Repo: thomascp2/SportsPredictor, Branch: master, File: dashboards/cloud_dashboard.py
4. In app settings → Secrets, add all TURSO_*_URL and TURSO_*_TOKEN values
5. Deploy → get permanent URL
6. Test: Top Plays tab, NHL/NBA/MLB tabs, System tab Turso row counts

### Streamlit Cloud limitations to know
- No local SQLite files — dashboard falls back gracefully (local-only features disabled)
- No SmartPickSelector path — Turso primary path is what Cloud sees
- No prizepicks_lines.db — game_time shown from Turso (populated by pp-sync)
- shared/ modules unavailable — project_config import already wrapped in try/except

---

## Phase 5 — Remaining File Cleanup 🔲 PARTIAL

**Deleted:**
- [x] mlb/database/mlb_game_predictions.db (0 bytes, unused)
- [x] nhl/database/nhl_predictions.db (0 bytes, deprecated)

**Still TODO:**
- [ ] nhl/database/hits_blocks.db — delete when NHL season confirmed fully over (playoffs TBD)

**Do NOT touch:**
- PEGASUS — leave entirely as-is
- ML flags — no retrain review = no changes
- mlb_feature_store/ — working, leave it
- parlay_lottery/ — out of scope

---

## Turso Sync Operations (all working)

| Operation | Status | Tables |
|-----------|--------|--------|
| predictions | ✅ working | predictions |
| smart-picks | ✅ working | predictions (UPDATE is_smart_pick, ai_tier, odds_type, ai_edge, ai_ev_*) |
| grading | ✅ working | prediction_outcomes |
| game-predictions | ✅ working | game_predictions |
| game-outcomes | ✅ working | game_prediction_outcomes |
| game-times | ✅ working | predictions (UPDATE game_time) |
| game-scores | ✅ working | game_scores |

---

## Handoff Prompt (paste at start of next session)

```
We are finishing the simplification of SportsPredictor to SQLite local + Turso cloud only.
VPS is killed. Supabase is fully removed from code. FreePicks mobile app is dead.

CURRENT STATE (all committed, pushed to master at 54f54aef / f82ec62a):
- Phase 1 ✅ Git cleanup
- Phase 2 ✅ VPS archived
- Phase 3 ✅ FULLY COMPLETE — Supabase removed from dashboard, orchestrator, and sync layer.
  All ai_edge/ev values backfilled into Turso (NBA 52K, NHL 18K, MLB 25K rows, last 35 days).
  pp-sync now includes SmartPickSelector write-back step so ai_edge stays current going forward.
- Phase 5 PARTIAL: deleted 0-byte dead DBs; hits_blocks.db pending (NHL season TBD)

NEXT: Phase 4 — Streamlit Cloud deploy.

Pre-deploy work needed:
1. requirements.txt: remove supabase>=2.0.0 line, add libsql-client
2. Create .streamlit/secrets.toml template with redacted values (commit it)
3. Verify shared/ module imports are try/except safe for Cloud (project_config already is)
4. Commit + push, then deploy to share.streamlit.io

Deploy: share.streamlit.io → New app → thomascp2/SportsPredictor → dashboards/cloud_dashboard.py
Secrets to add in Cloud UI: TURSO_NHL_URL, TURSO_NHL_TOKEN, TURSO_NBA_URL, TURSO_NBA_TOKEN,
                              TURSO_MLB_URL, TURSO_MLB_TOKEN, TURSO_GOLF_URL, TURSO_GOLF_TOKEN

Key files:
- SIMPLIFY_PLAN.md — this plan
- dashboards/cloud_dashboard.py — Turso-only, no Supabase, Cloud-ready
- requirements.txt — needs libsql-client, remove supabase
- orchestrator.py — SUPABASE_SYNC_AVAILABLE=False, all writes → Turso
- sync/turso_sync.py — the only cloud sync layer
```
