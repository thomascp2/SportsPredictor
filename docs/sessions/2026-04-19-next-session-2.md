# Next Session Handoff — Apr 19, 2026 (Evening)

## State of the World

Local orchestrator running continuously. All four sports active. VPS is NOT running —
local-only until prod is declared. Dashboard restarted after code fixes applied this
session.

---

## What Was Fixed This Session

### 1. `odds_type` Not Propagating to SQLite / Turso (BUG — FIXED)

**Root cause**: `supabase_sync.py` SQLite write-back updated `is_smart_pick` and
`ai_tier` but never wrote `odds_type`. All local predictions stayed `'standard'`
regardless of actual PP classification. Turso inherited the wrong value since it reads
from local SQLite.

**Evidence**: All 2,723 NBA predictions for Apr 19 had `odds_type='standard'` in local
SQLite, even though prizepicks_lines.db had 5,767 demon + 3,609 goblin lines for NBA
that day. Derrick White `assists 5.5` showed as STD — it's actually demon.

**Fix 1 — `sync/supabase_sync.py`** (line ~369):
```python
# Before:
"UPDATE predictions SET is_smart_pick=1, ai_tier=? ..."
# After:
"UPDATE predictions SET is_smart_pick=1, ai_tier=?, odds_type=? ..."
```
Added `pick.pp_odds_type` as the second bind param.

**Fix 2 — `sync/turso_sync.py` `sync_smart_picks()`**:
- SELECT now includes `odds_type` from SQLite
- UPDATE SQL now sets `odds_type = ?` in Turso alongside `is_smart_pick` and `ai_tier`
- Both exact-name and normalized-name pass updated

**Takes effect**: Next pp-sync run (smart picks flagged after this fix get correct
odds_type in both SQLite and Turso).

---

### 2. Game Times Missing in Turso Path (BUG — FIXED)

**Root cause**: The Turso path in `fetch_picks()` set `game_time=None` and returned
immediately — the game_time enrichment from `prizepicks_lines.db` only existed in the
SmartPickSelector fallback path.

**Fix — `dashboards/cloud_dashboard.py`** Turso path (lines ~554-571):
Added same enrichment block that SmartPickSelector path uses:
```python
# Query prizepicks_lines.db for team→start_time mapping keyed by game_date+league
df["game_time"] = df["team"].apply(lambda t: _team_times.get(str(t).upper()))
```
Time column now populates for Turso rows.

---

### 3. "Sort by Prop" Added to All Picks Tab (IMPROVEMENT)

**`dashboards/cloud_dashboard.py`** `_render_picks_section`:
- Sort options: was `["Edge", "Probability", "Tier"]`
- Now: `["Edge", "Probability", "Prop", "Tier"]`
- Prop sort is ascending alphabetical (groups picks by prop type for scanning)

---

## Observations / Non-Issues Noted

### MLB Game Lines PRIME Hit Rate
All but ~2 PRIME-tagged MLB game lines (spread + total) hit today. Noted as a positive
signal for the game lines model — not a bug. Good early-season calibration sign.

### Lawson Cruse Goblin Showing as "Best Play"
Was VPS Apr 18 Turso data. Cruse has no entry in local SQLite (NHL Apr 18 had 0 smart
picks in local DB — orchestrator was being migrated). The edge math for goblin O0.5
is mathematically correct (high prob, real edge above 76.19% break-even). Not a bug —
but a display quirk when goblin floor lines dominate edge rankings. No fix applied.

### ML Model — No Bat File Change Needed
Orchestrator already schedules `run_weekly_ml_retrain()` every Sunday at 08:30 (MLB).
User manually ran it Apr 19 because orchestrator was restarting during VPS migration
and missed the Sunday Apr 13 trigger. If another manual run is needed:
```
python ml_training/train_models.py --sport mlb --all
```

---

## Remaining Work (Priority Order)

### 1. Dashboard Turso Migration — Verify Current Data Flow (HIGH)
The odds_type + game_time fixes above only help going forward. Turso rows for dates
before today still have `odds_type='standard'`. Consider a one-time backfill:
```
python -m sync.turso_sync --sport nba --operation smart-picks --date 2026-04-19
```
Run after next pp-sync to confirm new odds_type values land correctly in Turso.

### 2. Golf `expected_value` Column (MEDIUM)
`ALTER TABLE predictions ADD COLUMN expected_value REAL` in golf DB.
Backfill from `features_json`. Wire into prediction script going forward.

### 3. NBA Opponent Feature Depth (MEDIUM — before Oct retrain)
- Opponent defensive rating vs specific stat
- Opponent pace / rest days / back-to-back flag
- Vegas spread as blowout-risk proxy

### 4. MLB Model Blend Enablement (MEDIUM — mid-season gate)
Target: ~50K graded rows (currently ~38K + ~500/day → roughly Aug 2026).
Flip: `mlb_config.py` → `MODEL_TYPE = "ensemble"`, `LEARNING_MODE = False`.
Monitor 2 weeks before trusting.

### 5. make_cut Accuracy Investigation (MEDIUM)
Golf `make_cut` accuracy: 37.3% — below random baseline. Root cause: missing
field-quality normalization (70 avg in weak field ≠ cut in a major). Fix off-season.

### 6. VPS Cleanup Items (LOW — 6 remaining)
NBA Turso uncapped prob, Golf EV col, MLB feature store, NHL hits guard,
pp-sync local job removal, Grok key rotation.

---

## Key Config Switches (don't flip without review)

| Sport | File | Flag | Current | Flip when |
|---|---|---|---|---|
| NBA | `nba/scripts/nba_config.py` | `LEARNING_MODE` | `True` | Oct 2026 + clean retrain |
| NHL | `nhl/scripts/v2_config.py` | `MODEL_TYPE` | `statistical_only` | Oct 2026 + clean retrain |
| MLB | `mlb/scripts/mlb_config.py` | `MODEL_TYPE` | `statistical_only` | ~50K graded rows |
| Golf | N/A | N/A | No ML scaffolding | Post-season, 700+ samples/prop |

---

## Files Changed This Session

| File | Change |
|---|---|
| `sync/supabase_sync.py` | Write-back now includes `odds_type=pick.pp_odds_type` |
| `sync/turso_sync.py` | `sync_smart_picks` SELECTs + UPDATEs `odds_type` in Turso |
| `dashboards/cloud_dashboard.py` | Turso path: game_time enrichment from prizepicks_lines.db; "Prop" sort option added |
