# PEGASUS Bookmark — Session 2
**Date: 2026-04-15**

---

## Completed This Session

- [x] Step 1: Scaffold — all directories + `__init__.py` files created
- [x] Step 1: `PEGASUS/config.py` — DB paths, break-even constants, tier thresholds, audit gates
- [x] Step 1: `PEGASUS/requirements.txt`
- [x] Step 1: `PEGASUS/README.md`
- [x] Step 2: `PEGASUS/calibration/audit.py` — full 6-check calibration audit (final version)
- [x] Step 2: `PEGASUS/calibration/report.py` — report loader helper
- [x] Step 2: Ran audit against all 3 sports — ALL PASS with correct gate

## Files Created This Session

```
PEGASUS/calibration/__init__.py
PEGASUS/situational/__init__.py
PEGASUS/pipeline/__init__.py
PEGASUS/sync/__init__.py
PEGASUS/api/__init__.py
PEGASUS/data/calibration_tables/  (populated — nhl.json, nba.json, mlb.json)
PEGASUS/data/reports/             (populated — calibration_{sport}_2026-04-15.json x3)
PEGASUS/config.py
PEGASUS/requirements.txt
PEGASUS/README.md
PEGASUS/calibration/audit.py
PEGASUS/calibration/report.py
```

---

## Calibration Audit Final Results (ALL PASS)

### The gate that matters: Check F — Per (direction × odds_type), T1-T3 picks only

All three sports have at least 2 approved combos. Goblin/demon show NO_DATA (not enough
historical picks labeled as goblin/demon yet — will populate over time).

**NHL** (n=61,976 graded)
| Combo | n T1-T3 | Hit Rate | Break-Even | Edge | Status |
|---|---|---|---|---|---|
| OVER/standard | 8,372 | 64.8% | 52.4% | +12.5pp | APPROVED |
| UNDER/standard | 29,027 | 78.6% | 52.4% | +26.2pp | APPROVED |
- T1-ELITE OVER: 71.9% (+19.5pp) ✓ | T2 OVER: 66.4% (+14.0pp) ✓ | T3 OVER: 61.2% (+8.8pp) ✓
- T4-LEAN OVER: 54.1% (+1.8pp) → SUPPRESS | T5-FADE OVER: 48.6% → SUPPRESS
- [A] always-UNDER baseline: -1.79pp (was wrong gate — informational only)

**NBA** (n=147,163 graded)
| Combo | n T1-T3 | Hit Rate | Break-Even | Edge | Status |
|---|---|---|---|---|---|
| OVER/standard | 18,132 | 60.4% | 52.4% | +8.0pp | APPROVED |
| UNDER/standard | 39,498 | 82.8% | 52.4% | +30.4pp | APPROVED |
- T1-ELITE UNDER: 87.1% (+34.7pp) — best single number in the audit
- T3-GOOD OVER: 54.1% (+1.8pp) — borderline; monitor closely
- MACE=28.71pp warning: raw probabilities are miscalibrated. Edge/tier system still
  works correctly for pick selection. Display must use calibrated_probability from table.

**MLB** (n=18,835 graded)
| Combo | n T1-T3 | Hit Rate | Break-Even | Edge | Status |
|---|---|---|---|---|---|
| OVER/standard | 3,623 | 65.7% | 52.4% | +13.3pp | APPROVED |
| UNDER/standard | 9,035 | 76.0% | 52.4% | +23.6pp | APPROVED |
- T4-LEAN OVER: 50.4% (-1.9pp) → BLOCKED — do not surface
- All T1-T3 clear break-even cleanly

### Key architectural decision locked in
`approved_combos` is embedded in each sport's `data/calibration_tables/{sport}.json`.
`pick_selector.py` (Step 6) reads this list and suppresses any pick whose
(direction, odds_type) is not in approved_combos. This is the seal of approval.

### Break-even note
Config uses standard=52.38% (-110 equivalent). User mentioned -119 (54.3%) as a
possible correct figure for PrizePicks. Verify before Step 6 — if 54.3% is correct,
update `BREAK_EVEN["standard"]` in `config.py` and re-run audit. The T3-GOOD OVER
combos are most sensitive to this (edge shrinks from +8.8pp to +7.4pp at 54.3%).

---

## Exact Next Step (start of Session 3)

**Step 3: Situational Intelligence Engine**

Read FIRST (do not skip):
- `PEGASUS/PLAN.md` Step 3 section (lines ~146–220) — implementation spec
- `docs/plans/situational_intelligence_layer.md` — 665-line detailed spec

Build:
1. `PEGASUS/situational/flags.py` — SituationFlag enum + modifier table
2. `PEGASUS/situational/intel.py` — standings fetch (ESPN + NHL API), stakes scoring

APIs already used elsewhere in the codebase (use these, don't reinvent):
- ESPN standings: `shared/fetch_game_odds.py` — ESPN already called here for odds
- NHL standings: `api-web.nhle.com/v1/standings/now` — already used in grading scripts
  See `nhl/scripts/v2_auto_grade_yesterday_v3_RELIABLE.py` for NHL API usage patterns

Key rules for Step 3:
- Advisory ONLY. Never modifies `probability`, `ai_edge`, or `tier` stored anywhere.
- Output adds 3 fields: `situation_flag`, `situation_modifier`, `situation_notes`
- MLB gets a no-op placeholder (April = no stakes yet, build placeholder only)
- Default when API unavailable: `situation_flag = "NORMAL"`, modifier = 0.0
- star player USAGE_BOOST: query `player_game_logs` for top-2 minute leaders on team,
  flag if `game_stakes_score >= 0.75`

After Step 3 is complete:
→ Step 4: NHL ML Audit (`PEGASUS/pipeline/nhl_ml_reader.py`)
→ Step 5: MLB XGBoost gap closure (`PEGASUS/pipeline/mlb_ml_reader.py`)
→ Step 6: PEGASUS Pick Selector (`PEGASUS/pipeline/pick_selector.py`)
→ Step 7: Daily Runner (`PEGASUS/run_daily.py`)
→ Step 8: Turso Sync (`PEGASUS/sync/turso_sync.py`)
