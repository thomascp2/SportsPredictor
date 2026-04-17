# PEGASUS Bookmark — Session 6
**Date: 2026-04-15**

---

## Completed This Session

- [x] `PEGASUS/docs/mlb_training_guidance.md` — comprehensive MLB training guide
- [x] `PEGASUS/bookmarks/comprehensive_summary.md` — full Sessions 1–5 reference doc
- [x] `PEGASUS/pipeline/pick_selector.py` — Step 6 complete
- [x] `PEGASUS/bookmarks/bookmark-06.md` (this file)
- [x] `PEGASUS/pipeline/mlb_ml_reader.py` — Step 5 (done in same session, bookmarked separately as bookmark-05.md)

No production files modified. Rule 2 intact.

---

## Files Created / Modified This Session

```
PEGASUS/docs/mlb_training_guidance.md       (NEW)
PEGASUS/bookmarks/comprehensive_summary.md  (NEW — full reference)
PEGASUS/bookmarks/bookmark-05.md            (NEW — Step 5)
PEGASUS/bookmarks/bookmark-06.md            (NEW — this)
PEGASUS/pipeline/mlb_ml_reader.py           (NEW — Step 5)
PEGASUS/pipeline/pick_selector.py           (NEW — Step 6)
```

---

## MLB Training Guidance — Key Rules

Full document at `PEGASUS/docs/mlb_training_guidance.md`. Core rules extracted from NHL post-mortem:

1. **Never use stat model output as a feature** — f_prob_over is what killed NHL. Remove ANY derived stat model column from features before training.
2. **Baseline = majority-class always** — NOT stat model accuracy. If ML doesn't beat always-UNDER/OVER by >5%, don't deploy.
3. **Walk-forward validation: 3+ windows** — single test split = memorization. Average improvement across windows must be >5%.
4. **Auto-skip degenerate lines (majority class ≥ 80%)** — guard in train_models.py before training MLB. Save as `statistical_skipped_degenerate` in metadata.
5. **4-way temporal split**: train/val/cal/test — never fit calibration on val set.
6. **Feature importance gate**: no single feature > 50% — check for leakage.
7. **PEGASUS shadow audit required** before production activation — test set improvement ≠ live improvement.
8. **Earliest realistic MLB retrain: October 2026** — need full 2026 season data.

MLB-specific traps: pitcher data leakage, early-season distribution shift, "hot player" signal already priced by PP, weather/park collinearity.

---

## pick_selector.py — Architecture Notes

### Entry Point
```python
from PEGASUS.pipeline.pick_selector import get_picks, PEGASUSPick

picks = get_picks(
    game_date="2026-04-15",
    sport="all",           # nhl | nba | mlb | all
    include_fades=False,   # T5-FADE suppressed by default
    min_tier=None,         # optional: "T3-GOOD" to restrict
)
# Returns List[PEGASUSPick] sorted by ai_edge descending
```

### Probability Semantics (per sport)
- **NHL**: `probability` = P(direction), always ≥ 0.5. Cal table: buckets 0.55–0.95.
- **NBA**: `probability` = P(OVER), can be < 0.5 for UNDER picks. Cal table: buckets 0.05–0.95.
- **MLB**: `probability` = P(direction), always ≥ 0.5. Cal table: buckets 0.55–0.95.
- Calibration lookup uses raw stored probability (consistent with how cal table was built).

### Blend Logic (MLB only)
```python
# For BLEND_PROPS (hits, total_bases, strikeouts, walks, outs_recorded):
ml_p_over      = compute_ml_p_over(predicted_value, line, prop)
ml_p_direction = ml_p_over if direction == "OVER" else (1.0 - ml_p_over)
blended        = 0.60 * ml_p_direction + 0.40 * stat_prob

# For STAT_ONLY_PROPS (home_runs) and props not in DuckDB:
blended = stat_prob
```

### Calibration Lookup
```python
# Mirrors calibration/audit.py exactly:
bucket_low = round(min(int(prob * 10) / 10, 0.9), 1)
bucket_mid = round(bucket_low + 0.05, 2)
calibrated  = cal_table.get(str(bucket_mid), prob)  # fallback: raw prob
```

### Edge & Tier
```python
ai_edge = (calibrated_prob - break_even) * 100
# T1-ELITE: ≥+19%  T2-STRONG: ≥+14%  T3-GOOD: ≥+9%  T4-LEAN: ≥0%  T5-FADE: <0%
```

### Situational Flag Behavior
- `get_situation()` from PEGASUS/situational/intel.py — called once per (team, sport, date)
- Returns `(flag, modifier, notes)` — advisory ONLY
- Stored in PEGASUSPick.situation_flag / modifier / notes
- NEVER applied to calibrated_probability, ai_edge, or tier
- MLB: always returns NORMAL in April (no stakes logic yet)

### Known Non-Fatal Issues
1. **`no such column: minutes_played`** in NBA situational intel (`get_usage_boost_players`) — pre-existing bug in Step 3 code. USAGE_BOOST detection falls back gracefully. Does not affect pick output.
2. **20 NBA picks skipped** — these have `probability = 0.0` (f_insufficient_data=1 rows). Correct behavior — `not (0.0 < p < 1.0)` guard filters them.
3. **High T1-ELITE count**: calibration table caps at bucket 0.95 → cal=0.793 for any pick with raw prob ≥ 0.90. This is correct — MLB stat model often outputs very high probabilities for extreme lines. Step 7 should add `is_smart_pick=1` filter and PP line matching to reduce to actionable set.

### Validation Output (2026-04-15)
```
NHL: 278 picks built (451 raw rows)
NBA: 389 picks built (1,045 raw rows) — 20 skipped (prob=0)
MLB: 1,410 picks built (2,702 raw rows) — 193 ML-blended
     NBA: HIGH_STAKES correctly detected for NBA playoff teams (PHI, ORL, GSW, LAC)
```

Sample top picks (--tier T2-STRONG):
```
T1-ELITE  VJ Edgecombe   NBA rebs_asts   UNDER 11.5  edge=+32.8%  cal=0.852  [HIGH_STAKES]
T2-STRONG Ryan McMahon   MLB total_bases UNDER 1.5   edge=+18.1%  cal=0.704  (ML=0.643)
```

---

## Exact Next Step (start of Session 7)

**Step 7: PEGASUS Daily Runner**

Build `PEGASUS/run_daily.py`.

Read first:
1. `PEGASUS/PLAN.md` Step 7 section (lines ~380–403)
2. `PEGASUS/pipeline/pick_selector.py` — already built; run_daily calls `get_picks()`
3. `PEGASUS/bookmarks/comprehensive_summary.md` — for full context

Key design points:
- Verify existing orchestrator ran today (check prediction counts in SQLite before proceeding)
- Call `get_picks(game_date=today, sport="all")` — filters to T1-T4 by default
- Add `is_smart_pick=1` filter to SQLite query OR pass a filter param to get_picks
- Write to `PEGASUS/data/picks/picks_{date}.json` (local snapshot only — no DB writes)
- Print terminal summary: tier counts, sport counts, situation flags, top 10 picks
- Flag if any sport returns 0 picks (likely orchestrator didn't run)
- Schedule: run manually at first; later add to start_orchestrator.bat

**Step 7 scope check:** 
- Does NOT write to Supabase (Step 8)
- Does NOT write to Turso (Step 8)
- Does NOT fetch PP lines (Step 9)
- Does NOT send Discord notifications (defer to Step 7b or 8)
- Local snapshot only

**Step 8 prerequisite:** Investigate MLB Turso silent failure before wiring MLB sync.

---

## Prompt for Session 7 Agent

```
I'm continuing work on PEGASUS — a parallel read-only prediction system built on top
of the existing SportsPredictor orchestrator. PEGASUS lives entirely in PEGASUS/ and
never modifies existing files outside that directory.

Start by reading:
1. PEGASUS/bookmarks/bookmark-06.md — session 6 results + exact next steps
2. PEGASUS/bookmarks/comprehensive_summary.md — full project context
3. PEGASUS/PLAN.md Step 7 section (~lines 380-403)

Steps 1-6 complete:
- Step 1-2: Calibration audit + tables (all 3 sports PASS)
- Step 3: Situational intelligence engine (flags.py + intel.py)
- Step 4: NHL ML audit — FAIL. nhl_ml_reader.py built as skeleton.
- Step 5: MLB XGBoost reader (mlb_ml_reader.py) — DuckDB reader + p_over converter
- Step 6: pick_selector.py — full PEGASUS pick builder (builds PEGASUSPick dataclasses)

Today's task: Step 7 — PEGASUS Daily Runner
Build PEGASUS/run_daily.py with these responsibilities:
1. Verify orchestrator ran today (check prediction row counts in each SQLite DB)
2. Call pick_selector.get_picks() for all sports
3. Add is_smart_pick=1 filter (update _read_predictions SQL in pick_selector.py or
   filter at run_daily level — your call on cleanest approach)
4. Write to PEGASUS/data/picks/picks_{date}.json (local only, no DB writes)
5. Print terminal summary
6. Return exit code 1 if orchestrator hasn't run for any sport (safety guard)

Do NOT touch: orchestrator.py, any scripts outside PEGASUS/, any grading/pipeline code.
```
