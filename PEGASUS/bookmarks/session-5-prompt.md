# Session 5 Prompt — PEGASUS Continuation
**Use this to start the next session. Copy the block you want.**

---

## Context (read regardless of which option you pick)

I'm continuing work on **PEGASUS** — a parallel read-only prediction system built on top
of the existing SportsPredictor orchestrator. PEGASUS lives entirely in `PEGASUS/` and
never modifies any existing files outside that directory.

**Most recent bookmark**: `PEGASUS/bookmarks/bookmark-04.md`

**PEGASUS root**: `C:\Users\thoma\SportsPredictor\PEGASUS\`

**Steps completed so far:**
- Step 1: Calibration audit — all 3 sports PASS
- Step 2: Calibration tables written (part of Step 1)
- Step 3: Situational intelligence engine (`flags.py` + `intel.py`) + 2027 Layer 2 edition
- Step 4: NHL ML audit ran — **VERDICT: FAIL**. Models caused 100% UNDER bias in production.
  Root cause fully diagnosed and fixed. See `PEGASUS/docs/nhl_ml_post_mortem.md` and
  `PEGASUS/2027/NHL_RETRAIN_MASTERPLAN.md` for the full picture.

**Production fixes already applied (outside PEGASUS):**
- `USE_ML = False` in `nhl/scripts/generate_predictions_daily_V6.py`
- `_prepare_features` now handles `f_*` naming convention fallback in `production_predictor.py`
- `_is_model_degenerate` updated with 4 failure modes
- `train_models.py`: f_prob_over excluded, always-majority-class baseline, degenerate line guard,
  feature deduplication

**All SQLite/DuckDB access from PEGASUS is READ-ONLY. Never INSERT/UPDATE/DELETE.**

---

## OPTION A — Full Session (Recommended)
**Build both self-monitoring pieces + document the retrain process end-to-end.**

This session covers two deliverables:

### Deliverable 1: Direction Sanity Check (production code)

Add `check_prediction_direction_sanity()` to `orchestrator.py`. It runs automatically
after every NHL/NBA prediction batch and fires a Discord alert if any competitive
prop/line is >85% in one direction (flags stat model bugs the same night they happen,
not 30 days later). The function signature and full implementation are already specified
in `PEGASUS/2027/NHL_RETRAIN_MASTERPLAN.md` Part 4 Piece 1.

Wire it into the orchestrator where the prediction count Discord post happens
(approximately line 664 area based on prior investigation).

### Deliverable 2: Weekly ML Shadow Audit (automated cron)

Wire `audit_nhl_models()` from `PEGASUS/pipeline/nhl_ml_reader.py` into a weekly
Sunday cron in `orchestrator.py`. Posts verdict + per-prop results to Discord.
Auto-sets `USE_ML = False` if audit FAILS during active season.
Implementation spec is in `PEGASUS/2027/NHL_RETRAIN_MASTERPLAN.md` Part 4 Piece 2.

After both pieces are built:
- Run the direction sanity check manually against the last 7 days to verify it's clean
- Verify the weekly audit cron is scheduled

### Then continue PEGASUS Step 5: MLB XGBoost Integration

Read `PEGASUS/PLAN.md` Step 5 section. Build `PEGASUS/pipeline/mlb_ml_reader.py`:
```python
def get_today_mlb_ml_predictions(game_date: str) -> dict:
    """Read ml_predictions from mlb_feature_store DuckDB (read-only)."""
```
Blend: hits/total_bases/strikeouts/walks/outs_recorded = 60/40 ML/stat.
All other MLB props (including home_runs — model excluded per PLAN.md) = stat only.
If DuckDB unavailable or player missing: fall back to stat_prob silently.

---

### Build in this order:

1. **Direction sanity check** — wire into `orchestrator.py` post-prediction hook
   - Implementation spec: `PEGASUS/2027/NHL_RETRAIN_MASTERPLAN.md` Part 4 Piece 1
   - Apply to both NHL and NBA prediction pipelines
   - Test by running it against last 7 days of predictions

2. **Weekly ML shadow audit** — wire into Sunday grading cron
   - Implementation spec: `PEGASUS/2027/NHL_RETRAIN_MASTERPLAN.md` Part 4 Piece 2
   - NHL only for now (NBA ML is off, NBA uses pure statistical)
   - Verify it posts to Discord correctly

3. Run both manually to confirm output is clean before ending session.

Do not start Step 5 (MLB) in this session — stop after monitoring is verified working.

---

## Files to Read at Session Start

1. `PEGASUS/bookmarks/bookmark-04.md` — full session 4 results
2. `PEGASUS/docs/nhl_ml_post_mortem.md` — root cause analysis
3. `PEGASUS/2027/NHL_RETRAIN_MASTERPLAN.md` — retrain plan + monitoring specs
4. `PEGASUS/PLAN.md` lines ~290-320 — Step 5 spec (if doing Option A)
