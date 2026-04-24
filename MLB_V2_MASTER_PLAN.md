# MLB V2 Master Plan
**Created: 2026-04-24 | Status: PRE-ACCUMULATION — do not start collecting calibration data until blockers are resolved**

This is the governing document for MLB V2. All implementation decisions trace back here.
The target is MASTER_PLAN.md Phase 1 complete: a validated BMA engine producing True Probability + 95% CI,
ready to gate Phase 2 (CSA trigger). NHL and NBA are out of scope until this is done.

---

## What We Are Building

A closed-loop, self-improving Bayesian probability engine for MLB player props.

```
Daily Input                  BMA Core                      Daily Output
-----------                  --------                      ------------
Stat model                   XGBoost  ─┐
  P(OVER) per prop           RF       ─┤─ MAB weights ──> prob_over + 95% CI
                             LR       ─┘                    ml_v2_predictions
XGBoost (DuckDB)             Stat ────┘
  predicted_value → Poisson CDF

                             ↓ next morning
                        Auto-grader
                        ml_v2_outcomes (bma_correct per row)
                             ↓
                        MAB updates (who was right)
                             ↓
                        KS drift check (env shifted?)
                             ↓
                        Weekly calibration report (Sunday)
                             ↓ (when gate criteria met)
                        Retrain trigger → validate → deploy
```

---

## Honest Current State

| Component | Status | Notes |
|-----------|--------|-------|
| `generate_v2_predictions.py` | Built | Writes `predictions` + `ml_v2_predictions`. CI is honest. |
| `auto_grade_daily.py` + `ml_v2_outcomes` | Built | Grades V2 rows, writes `bma_correct` daily. |
| Orchestrator wired to V2 generator | Done | MLB now runs `generate_v2_predictions.py`. |
| XGBoost models (6 props) | Exists | In `mlb_feature_store/ml/models/`. Regression → Poisson CDF → P(OVER). |
| Stat model | Exists | Full prop coverage (~15 prop types). Solid baseline. |
| MAB (Thompson Sampling) | Exists | 4 arms: xgb, rf, lr, stat. Cold-start priors set. |
| RF model | **MISSING** | Arm exists in MAB with phantom weight. No predictions generated. |
| LR model | **MISSING** | Same — phantom arm. |
| Retrain pipeline (train/validate/deploy) | **MISSING** | mlb_feature_store can train XGBoost but no closed-loop validation/deploy cycle. |
| KS drift detector | Exists (hlss) | Not wired into daily MLB pipeline. |
| Weekly calibration script | **MISSING** | The primary lesson from NHL/NBA — must build this. |

---

## Blockers — Must Fix Before Accumulating Calibration Data

### Blocker 1: Phantom MAB Arms (CRITICAL)

**The problem:** `sample_weights()` currently returns weights for all 4 arms (xgb, rf, lr, stat).
But RF and LR produce no predictions. The BMA math in `_save_v2_prediction` uses `stat` and `xgb` only.
The `mab_weights` JSON recorded in `ml_v2_predictions` shows non-zero rf/lr weights that were never applied.

**The consequence:** Every calibration row is recorded with false metadata. When we retrospectively
analyze "did the MAB weights correlate with accuracy?" the answer will be garbage because the
recorded weights don't reflect what the BMA actually computed.

**The fix:** Until RF and LR models are built and generating predictions, `generate_v2_predictions.py`
must only sample from `['stat', 'xgb']`. Add a `ACTIVE_MODELS` config constant. Once RF/LR are
deployed, add them to this list. The recorded `mab_weights` will then honestly reflect BMA composition.

### Blocker 2: XGBoost Only Covers 6 Props

**The problem:** The feature store trains XGBoost on: hits, total_bases, home_runs, strikeouts,
walks, outs_recorded. The full MLB prop suite has ~15 prop types. Props outside those 6 are
permanently stat-only regardless of what we build.

**This is acceptable** — the stat model is solid for those props. But we must be explicit:
- ML coverage props (6): hits, total_bases, home_runs, strikeouts, walks, outs_recorded
- Stat-only props (~9): singles, doubles, rbis, runs, stolen_bases, batter_strikeouts, hrr, hits_allowed, earned_runs

The calibration report must segment by covered vs. stat-only props. Phase 2 gate
criteria apply to covered props only.

### Blocker 3: No Train/Validate/Deploy Loop

**The problem:** KS drift says "environment shifted, retrain." But retrain to what? We have
`mlb_feature_store/ml/train.py` which trains XGBoost, but there is no:
- Holdout validation gate (new model must beat current model to deploy)
- Model registry with versioning
- Automated deploy step

Without this, "automated retraining" from KS drift is a promise we cannot keep.

---

## Architecture Decision: RF and LR

**Recommendation: Yes, build both. Here is the rationale and the architecture.**

RF and LR add genuine diversity because they fail differently from XGBoost:
- XGBoost: powerful but prone to overfit on noisy recent features
- RF: tree ensemble, more resistant to overfitting, slower to react to sharp changes
- LR: linear baseline; if RF and XGBoost diverge significantly from LR, that is a drift signal

**Architecture choice:**
- RF: regression model (same as XGBoost — predict actual value → Poisson CDF). Same feature matrix,
  different estimator. Low additional complexity.
- LR: classification model (logistic regression with line as an input feature → outputs P(OVER)
  directly, no Poisson CDF needed). This is actually cleaner — LR is the one model that
  natively outputs calibrated probabilities.

**Training data source:** Both use the existing DuckDB feature store. Same features as XGBoost.
Same 70/15/15 temporal train/val/test split. Add as new pkl files alongside XGBoost models.

**Scope of RF/LR:** Same 6 props as XGBoost. No point adding them for stat-only props.

---

## Build Order (Sequenced — Do Not Reorder)

### Phase A: Fix the Foundation (before any calibration data accumulates)

**A1. Fix phantom MAB arms**
- Add `ACTIVE_MODELS = ['stat', 'xgb']` to `generate_v2_predictions.py`
- Only sample weights from active models
- Update `mab_weights` JSON to only record contributing models
- Expand `ACTIVE_MODELS` to `['stat', 'xgb', 'rf', 'lr']` when Phase B is done

**A2. Add RF + LR to mlb_feature_store training**
- Extend `mlb_feature_store/ml/train.py` to train RF regressor and LR classifier alongside XGBoost
- RF: `sklearn.ensemble.RandomForestRegressor` → predicted value → Poisson CDF
- LR: `sklearn.linear_model.LogisticRegression` with line as a feature → direct P(OVER) output
- Save as `ml/models/{prop}_rf.pkl` and `ml/models/{prop}_lr.pkl` alongside XGBoost
- Evaluate against holdout: RF and LR only deploy if they beat the naive stat baseline on test set

**A3. Extend `predict_to_db.py` to write RF and LR predictions**
- Current: writes XGBoost `predicted_value` per player/prop/date
- New: also write RF and LR outputs to DuckDB (`ml_predictions` gains `rf_predicted_value`,
  `lr_prob_over` columns, or separate rows keyed by model name)
- `generate_v2_predictions.py` loads all 3 ML model outputs when available

**A4. Build the retrain pipeline (train/validate/deploy closed loop)**
- `mlb_feature_store/ml/retrain.py`:
  - Pulls latest features + labels from DuckDB
  - Trains XGBoost, RF, LR on 70% train split
  - Validates on 15% val split: must beat current deployed model's val score to proceed
  - If passes: writes new pkl to models/, updates `models/metadata.json` with version + metrics
  - If fails: logs failure, keeps current model, sends no-deploy signal
- Gates: Brier score must improve by ≥ 0.005 OR KS drift flag is set (allow retrain even if improvement is marginal)
- Minimum data requirement: 500 labeled rows per prop after dropna (same as existing `train.py` guard)

### Phase B: Wire the Feedback Loop

**B1. Wire KS drift into daily pipeline**
- After grading in `auto_grade_daily.py`, call `drift_detector.detect()` with last 30 days of
  `actual_value` per prop from `ml_v2_outcomes`
- If KS p-value < 0.05: set `drift_flagged=1` on today's `ml_v2_predictions` rows for that prop
- Log to `mlb_drift_log` table (game_date, prop_type, ks_stat, p_value)
- If drift flagged: trigger retrain pipeline for affected props (via `retrain.py`)

**B2. Build weekly calibration script (`mlb_v2_calibration.py`)**
- Standalone script. Run manually anytime. Also runs automatically every Sunday.
- Segments output by prop coverage (ML-covered vs stat-only) and model version
- Reports at whatever sample size is available — always honest about small N

**Reports at every run:**
1. Row counts by prop type (how much data do we actually have)
2. BMA hit rate vs stat-only hit rate (is the ensemble adding value)
3. Calibration by confidence tier: HIGH / MEDIUM / LOW — are these meaningfully different
4. XGBoost/RF/LR individual arm accuracy (which model is pulling weight)
5. MAB weight trajectory — what direction are weights drifting
6. Prop-level drift log (any KS flags in the last 30 days)
7. Phase 2 gate status: how many props have hit 500 graded trials

**Checkpoint schedule:**
| Milestone | Approx date | What we expect to learn |
|-----------|-------------|-------------------------|
| 50 rows | Day 1-2 | Catch catastrophic failures (zero hits, all VOIDs, broken imports) |
| 200 rows | Week 1 | Directional signal: is BMA performing better than stat alone? |
| 500 rows total | Week 2 | Enough to see tier separation (HIGH > MEDIUM > LOW?) |
| 500 rows per prop | ~July 2026 | Phase 2 gate: per-prop calibration within 5% of actual outcomes |

**Early stopping criteria (NHL/NBA lesson applied):**
- If BMA hit rate is MORE THAN 5 percentage points BELOW stat-only after 200 rows: STOP.
  Diagnose before accumulating more bad data. Do not "wait for more data to balance out."
- If any individual ML arm (xgb, rf, lr) is performing below 45% after 200 rows on its covered props:
  that arm's retrain is triggered immediately, not deferred.

---

## Phase 2 Gate Criteria (from MASTER_PLAN)

The CSA trigger (Phase 2) does NOT go live until ALL of the following are true:

1. BMA `True Probability` aligns with real-world outcomes within **5% margin of error**
   measured across **500 graded trials per covered prop type**
2. Calibration tiers are meaningful: HIGH rows must hit at ≥ 5 percentage points above MEDIUM,
   MEDIUM above LOW
3. No active KS drift flags on the props being traded
4. Retrain pipeline has successfully completed at least one deploy cycle (proves the loop works)

Until these gates are met, no capital is committed. The system is in data accumulation + validation mode only.

---

## Daily Pipeline (once Phase A complete)

| Time (CST) | Script | Output |
|------------|--------|--------|
| ~8:00 AM | `auto_grade_daily.py` | Grades yesterday → `prediction_outcomes` + `ml_v2_outcomes` + MAB update + KS check |
| ~10:00 AM | `generate_v2_predictions.py` | Today's BMA predictions → `predictions` + `ml_v2_predictions` |
| ~10:30 AM | `mlb_feature_store/run_daily.py` | Ingests yesterday's Statcast data into DuckDB |
| ~10:45 AM | `mlb_feature_store/ml/predict_to_db.py` | Writes XGBoost + RF + LR predictions for today |
| Sunday AM | `mlb_v2_calibration.py` | Weekly calibration report — print output only, no DB writes |
| On KS flag | `mlb_feature_store/ml/retrain.py` | Retrains affected props, validates, deploys if gate passed |

---

## Scope Boundaries (hard stops)

The following are explicitly OUT OF SCOPE until Phase 2 gate is met:

- Supabase sync
- Discord posts / webhooks
- FreePicks app / dashboard
- NHL or NBA V2 work
- DraftKings market implied probability (NULL until paid API tier)
- Golf
- Any CSA / Kalshi / Polymarket execution logic
- Capital commitment of any kind

---

## What "Done" Looks Like for Phase 1

Phase 1 is complete when:
1. All 4 model arms (xgb, rf, lr, stat) are producing real predictions daily
2. Retrain pipeline has completed at least one successful train/validate/deploy cycle
3. KS drift is wired and has logged at least one detection event (proves it works)
4. Weekly calibration has run for 4+ consecutive Sundays without early stopping criteria triggered
5. Phase 2 gate criteria above are met for at least 3 of the 6 ML-covered props

At that point we have something to show for the season — not a vague hit rate number,
but a validated probability engine with a documented track record.
