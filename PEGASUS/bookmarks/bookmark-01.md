# PEGASUS Bookmark — Session 1
**Date: 2026-04-15**
**Context used: ~65% at close**

---

## Completed This Session

- [x] Read and absorbed all `mlb_feature_store` docs (ARCHITECTURE.md, CLAUDE.md, HANDOFF.md, PROJECT_STATUS.md, metadata.json)
- [x] Created `SportsPredictor/PEGASUS/` directory
- [x] Audited actual ML model registry state — found 3 major errors in original PEGASUS.md
- [x] Wrote addendum to `PEGASUS/PEGASUS.md` with corrections (bottom of that file)
- [x] Wrote `PEGASUS/PLAN.md` — full 11-step execution plan, integrated with user Q&A
- [x] Created `PEGASUS/bookmarks/` protocol
- [x] Saved persistent memory to `~/.claude/projects/.../memory/project_pegasus.md`
- [x] Corrected stale NHL ML status in MEMORY.md

## Files Created
- `SportsPredictor/PEGASUS/PEGASUS.md` — addendum appended at bottom
- `SportsPredictor/PEGASUS/PLAN.md` — master execution plan (START HERE)
- `SportsPredictor/PEGASUS/bookmarks/bookmark-01.md` — this file

## Key Facts Established (do not re-derive)

**NHL**: Models exist in `ml_training/model_registry/nhl/` — 13 prop/lines, LogisticRegression, latest v20260325_003. NEVER activated. `v2_config.py` = MODEL_TYPE="statistical_only". User believed ML was running — it was not. Must audit before activating.

**NBA**: 471 model dirs exist (v20260315_001), all LogisticRegression. REVERTED after catastrophic Mar 15 accuracy collapse (84%→47% UNDER). Config = statistical-only. Correct behavior — leave alone.

**MLB**: Two ML layers:
  - `mlb_feature_store/ml/models/` — 6 XGBoost regressors, wired to orchestrator, feeds dashboard+TUI ONLY. NOT in Supabase/mobile.
  - `mlb/scripts/` (main pipeline) — statistical-only, LEARNING_MODE=True.
  - Gap: XGBoost picks exist but never reach users. Phase 4a closes this.

**PEGASUS architecture**: Parallel system. Reads existing SQLite/DuckDB (read-only). Builds calibrated pick layer. Eventual target: flip Supabase sync from old to PEGASUS when validated.

## Exact Next Step (start of Session 2)

**Read**: `SportsPredictor/PEGASUS/PLAN.md` — Steps 1 and 2

**Do Step 1**: Scaffold PEGASUS directory structure per PLAN.md. Create:
```
PEGASUS/calibration/__init__.py  (empty)
PEGASUS/situational/__init__.py  (empty)
PEGASUS/pipeline/__init__.py     (empty)
PEGASUS/sync/__init__.py         (empty)
PEGASUS/api/__init__.py          (empty)
PEGASUS/data/calibration_tables/ (empty dir)
PEGASUS/data/reports/            (empty dir)
PEGASUS/config.py                (paths to existing DBs + Supabase key + break-even constants)
PEGASUS/requirements.txt         (based on root requirements.txt)
PEGASUS/README.md                (how to run)
```

**Then do Step 2**: Calibration audit. Read the NHL + NBA SQLite schemas first (check column names — they differ). Build `PEGASUS/calibration/audit.py`.

## Turso Context (confirmed 2026-04-15)

Turso is the PRIMARY operational database target — not Supabase. All references to "Supabase sync" in PLAN.md Step 8 have been updated.

Key facts:
- `sync/turso_sync.py` exists — handles predictions, smart-picks, grading per sport
- Per-sport Turso DBs: env vars `TURSO_{NHL|NBA|MLB|GOLF}_{URL|TOKEN}`
- Orchestrator already calls Turso sync (wired at predictions + pp-sync + grading hooks)
- 772k rows migrated to Turso as of Apr 6, 2026
- **Known bug**: MLB Turso smart-picks has a silent failure — investigate before trusting MLB Turso output
- Supabase: holds user-facing data (daily_props, user_picks, profiles) — mobile reads from here
- Mobile Turso integration was "next" as of Apr 6 — unresolved; Step 8 decision depends on this

PEGASUS sync (`PEGASUS/sync/turso_sync.py`) mirrors pattern from `sync/turso_sync.py` using `libsql_client`.

## Open Questions for Next Session

Before starting Step 2, clarify:
1. NHL `predictions` table: is the probability column named `probability` or `confidence` or something else? Check with `sqlite3 nhl/database/nhl_predictions_v2.db ".schema predictions"`
2. Are there enough graded predictions in the MLB database to run a meaningful calibration? Check count.
3. Does user want calibration output as a Streamlit page or just terminal + JSON?
4. MLB Turso smart-picks silent failure — should we investigate this at the top of the next session or defer?
