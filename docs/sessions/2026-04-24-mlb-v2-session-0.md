# MLB V2 — Session 0 Handoff
**Date: 2026-04-24 | Status: Foundation laid. Build continues next session.**
**"Day 0. We're going to the moon."**

---

## What This Session Was

A complete pivot and rearchitecture. We stopped building V1 features, diagnosed what was actually wrong, read the MASTER_PLAN as gospel, and designed a clean MLB V2 system from scratch. No NHL. No NBA. No dashboard. No Discord. Pure intelligence layer — BMA engine, closed-loop validation, path to Phase 2.

---

## Decisions Made (treat these as locked)

### Scope
- **MLB V2 only** until Phase 1 gate is met. NHL/NBA are read-only archive until next season.
- **No Supabase, Discord, FreePicks, dashboard** — pure data + models + closed-loop validation.
- **SportsPredictor → read-only V1 archive.** Nothing new added there.
- **New repo: `apex-arb`** — the Apex Arb system. hlss becomes this. MLB V2 scripts are Phase 1 of this system.

### Architecture
- **4-arm BMA**: XGBoost + RF + LR (regression, same Statcast features) + Stat model
- **MAB** (Thompson Sampling) tracks each arm's win rate. Weights only sampled from `ACTIVE_MODELS` — starts `['stat', 'xgb']`, expands to all 4 when RF/LR are built.
- **KS drift** detects scoring environment changes → triggers retrain pipeline
- **Closed-loop retrain**: train → validate → deploy only if new model beats current on val set
- **Weekly calibration script** runs every Sunday from day 1 — early stopping if BMA underperforms stat-only by >5pp after 200 rows

### Data Boundary
- `ml_v2_predictions` and `ml_v2_outcomes` start at **2026-04-25**. Zero V1 rows.
- `player_game_logs` copied from V1 (factual box score data — clean).
- `mlb.duckdb` Statcast history copied (irreplaceable training data — clean).
- MAB state starts from cold-start priors. No V1 grading history imported.

### Phase 2 Gate (DO NOT skip this)
CSA trigger goes live only when ALL are true:
1. BMA True Probability within 5% of actual outcomes over 500 graded trials per covered prop
2. HIGH confidence rows outperform LOW by ≥5pp
3. No active KS drift flags on traded props
4. Retrain pipeline has completed at least one successful deploy cycle

---

## What Was Built This Session

### Files created/modified in SportsPredictor (all move to apex-arb):

| File | Status | What it does |
|------|--------|--------------|
| `mlb/scripts/generate_v2_predictions.py` | Done | BMA generator. Writes `predictions` + `ml_v2_predictions`. Honest CI (Beta calibration uncertainty for stat-only — no zero-width CIs). Coverage tracking. `ACTIVE_MODELS` constant guards phantom arms. |
| `mlb/scripts/auto_grade_daily.py` | Done | Grades `predictions` → `prediction_outcomes`. Grades `ml_v2_predictions` → `ml_v2_outcomes` (bma_correct flag). MAB updates. |
| `orchestrator.py:296` | Done | MLB prediction_script swapped to `generate_v2_predictions.py` |
| `MLB_V2_MASTER_PLAN.md` | Done | Governing document. Read before every session. |

### Commits this session (SportsPredictor/master):
```
40847133  A1: Fix phantom MAB arms + add V2 data boundary marker
f479aa06  Wire MLB V2 pipeline end-to-end: generator + grader + orchestrator
ad10761e  Add MLB_V2_PLAN.md — V2 BMA build order of operations
bbd8918f  Wire BMA data accumulation for MLB: ml_prob_over + MAB updates
```

---

## What's NOT Built Yet (next session picks up here)

### Phase A — Fix the Foundation

**A1 ✅ DONE** — Phantom MAB arms fixed. `ACTIVE_MODELS = ['stat', 'xgb']`.

**A2 — RF + LR Training** ← START HERE NEXT SESSION
- Extend `mlb_feature_store/ml/train.py`
- Add `RandomForestRegressor` (sklearn) for each prop → saves `{prop}_rf.pkl`
- Add `Ridge` regression for each prop → saves `{prop}_lr.pkl`
- Same feature matrix and 70/15/15 temporal split as XGBoost
- RF and LR metrics added to `metadata.json`
- Only runs if ≥500 clean rows (same guard as XGBoost)

**A3 — Retrain Pipeline**
- New `mlb_feature_store/ml/retrain.py`
- Train XGBoost + RF + LR → validate → deploy only if val_mae improves by ≥0.005 vs current
- KS drift flag overrides the improvement gate (allow retrain even if marginal)
- Writes deploy log to `metadata.json` with version history

**A4 — Extend predict_to_db.py**
- Add RF and LR inference alongside XGBoost
- Schema migration: add `rf_predicted_value`, `lr_predicted_value` columns to `ml_predictions`
- `generate_v2_predictions.py` loads all 3 when available

### Phase B — Feedback Loop

**B1 — KS Drift Hook**
- New `mlb/scripts/mlb_ks_drift.py` — MLB-specific KS test
  - Uses `actual_value` from `ml_v2_outcomes` (real outcomes, not model probs)
  - Reference distribution: DuckDB `pitcher_labels` + `hitter_labels` (full historical)
  - Logs to `mlb_drift_log` table in `mlb_v2.db`
  - No Discord (out of scope)
- Wire into `auto_grade_daily.py` after `_grade_v2_predictions()`
- On drift: call `retrain.py` for affected props (non-fatal)

**B2 — Weekly Calibration Script**
- New `mlb/scripts/mlb_v2_calibration.py`
- Reads from `mlb_v2.db`
- 7 reports:
  1. Row counts by prop type (how much data do we have)
  2. BMA hit rate vs stat-only hit rate
  3. Calibration by confidence tier (HIGH/MEDIUM/LOW)
  4. Individual arm accuracy (xgb vs rf vs lr vs stat)
  5. MAB weight trajectory over time
  6. Drift log summary (any KS flags last 30 days)
  7. Phase 2 gate status per prop
- Early stopping rule: if BMA > 5pp below stat-only after 200 rows → print STOP banner
- Usage: `python mlb_v2_calibration.py` or `python mlb_v2_calibration.py --date 2026-05-15`

### Daily Runner
- New `run_daily_v2.py` at repo root
- Replaces orchestrator for MLB V2
- Sequence: grade (8am) → predict (10am) → feature store ingest (10:30am) → predict_to_db (10:45am)
- Simple subprocess calls, no orchestrator complexity

---

## When You Get Home — Exact Checklist

```
1.  Stop start_orchestrator.bat (close the window / kill process)
2.  mkdir C:\Users\thoma\apex-arb
3.  cd C:\Users\thoma\apex-arb && git init
4.  Copy files per apex-arb structure below
5.  Copy mlb_feature_store/data/mlb.duckdb → apex-arb/feature_store/data/mlb.duckdb
6.  Copy player_game_logs from mlb_predictions.db into fresh mlb_v2.db:
      sqlite3 mlb_v2.db
      ATTACH 'path/to/mlb_predictions.db' AS v1;
      CREATE TABLE player_game_logs AS SELECT * FROM v1.player_game_logs;
7.  Create empty apex-arb/intelligence/mab_state/ directory
8.  Update path constants in mlb_config.py to point to apex-arb paths
9.  python intelligence/setup_ml_v2_schema.py --sport mlb (creates fresh V2 tables)
10. git remote add origin https://github.com/thomascp2/apex-arb
11. git push -u origin main
12. Set up two Task Scheduler entries:
      8:00 AM  → python mlb/scripts/auto_grade_daily.py
      10:00 AM → python mlb/scripts/generate_v2_predictions.py
    (run_daily_v2.py handles all 4 once built next session)
```

---

## apex-arb Repo Structure

```
apex-arb/
├── MASTER_PLAN.md                     ← copy from hlss (the gospel)
├── MLB_V2_MASTER_PLAN.md              ← copy from SportsPredictor
├── run_daily_v2.py                    ← BUILD next session
│
├── mlb/
│   ├── config/mlb_config.py           ← copy + update paths
│   ├── features/                      ← copy from SportsPredictor/mlb/features/
│   ├── scripts/
│   │   ├── generate_v2_predictions.py ← DONE (copy)
│   │   ├── auto_grade_daily.py        ← DONE (copy)
│   │   ├── fetch_game_schedule.py     ← copy
│   │   ├── statistical_predictions.py ← copy
│   │   ├── mlb_stats_api.py           ← copy
│   │   ├── mlb_ks_drift.py            ← BUILD next session (B1)
│   │   └── mlb_v2_calibration.py      ← BUILD next session (B2)
│   └── database/
│       └── mlb_v2.db                  ← FRESH (player_game_logs only from V1)
│
├── feature_store/                     ← copy entire mlb_feature_store/
│   ├── ml/
│   │   ├── train.py                   ← EXTEND next session (A2: RF + LR)
│   │   ├── retrain.py                 ← BUILD next session (A3)
│   │   ├── predict_to_db.py           ← EXTEND next session (A4: RF + LR)
│   │   └── models/                    ← existing XGBoost pkl files
│   └── data/mlb.duckdb                ← COPY (Statcast history — irreplaceable)
│
├── intelligence/                      ← cherry-picked from hlss
│   ├── mab_weighting.py               ← copy (code only, no state)
│   ├── drift_detector.py              ← copy (reference; mlb_ks_drift.py is MLB-specific)
│   ├── market_odds_client.py          ← copy
│   ├── setup_ml_v2_schema.py          ← copy
│   └── mab_state/                     ← FRESH EMPTY (cold-start priors on first run)
│
└── execution/                         ← Phase 2-4, dormant
    └── csa_state_machine.py           ← copy from hlss
```

---

## Key Design Decisions To Remember

**Why RF as regression, not classification:**
Same feature matrix as XGBoost → predicted_value → Poisson CDF. Keeps the pipeline identical, no separate feature engineering needed.

**Why LR as Ridge regression:**
Ridge is more numerically stable than OLS with 5 features and adds regularization. Same pipeline as XGBoost/RF — predicted_value → Poisson CDF. Consistent architecture for all 3 ML models.

**Why KS test on actual_value (not model probs):**
We're detecting scoring environment changes (rule changes, June adjustments, weather patterns). Testing real outcomes directly is a cleaner signal than testing model output distributions.

**Why no Discord/Supabase/FreePicks:**
Out of scope until Phase 2 gate is met. We are in data accumulation + validation mode. Nothing to show until BMA is validated.

**Early stopping rule (law, not suggestion):**
If BMA hit rate is >5pp below stat-only after 200 graded rows → STOP and diagnose. Do not wait for more data to "balance out." This is the NHL/NBA lesson applied directly.

---

## Paste-Ready Prompt For Next Session

```
We are building MLB V2 inside the apex-arb repo (formerly hlss, now the Apex Arb system).
Read MLB_V2_MASTER_PLAN.md and docs/sessions/2026-04-24-mlb-v2-session-0.md before anything else.

Context:
- Session 0 complete. Foundation is laid. apex-arb repo set up locally.
- SportsPredictor is now read-only archive. Orchestrator stopped.
- ACTIVE_MODELS = ['stat', 'xgb'] — phantom arms fixed.
- ml_v2_predictions and ml_v2_outcomes start fresh from 2026-04-25.

Pick up at Phase A2:
- Extend mlb_feature_store/ml/train.py to add RF (RandomForestRegressor) and
  Ridge regression alongside XGBoost. Same feature matrix, same 70/15/15 split.
  Save as {prop}_rf.pkl and {prop}_lr.pkl. Add metrics to metadata.json.
- Then A3: build mlb_feature_store/ml/retrain.py (closed-loop retrain pipeline).
- Then A4: extend predict_to_db.py to write rf_predicted_value + lr_predicted_value.
- Then B1: mlb_ks_drift.py + wire into auto_grade_daily.py.
- Then B2: mlb_v2_calibration.py (weekly calibration, 7 reports, early stopping banner).
- Then: run_daily_v2.py (simple 4-script daily runner, replaces orchestrator for MLB).

Push back hard if scope creeps. MLB V2 only. No dashboard. No Discord. No Supabase.
```

---

*Session 0. Day 0. The data accumulates from here.*
