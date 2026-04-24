# MLB V2 Build Plan
**Started: 2026-04-24**
**Scope: MLB only. NHL/NBA untouched until October.**

---

## What We're Building

A clean dual-model BMA prediction pipeline for MLB that feeds the Apex Arb engine.
Supabase, Discord, and FreePicks are out of scope — this is the intelligence layer only.

**Output:** `ml_v2_predictions` table in `mlb/database/mlb_predictions.db`
Every row has a True Probability (P) + 95% CI. That is the only deliverable that matters.

---

## Signals Available Today

| Signal | Source | Format | Coverage |
|--------|--------|--------|----------|
| Stat model P(OVER) | `mlb/features/statistical_predictions.py` | float [0,1] | ~all scheduled players |
| XGBoost P(OVER) | `mlb_feature_store/data/mlb.duckdb` → Poisson CDF | float [0,1] | ~320 players (Statcast coverage) |
| MAB weights | `hlss/ml_training/mab_state/mlb_*.json` | Beta(α,β) per model | cold-start until ~100 graded rows |
| DK market implied | `hlss/shared/market_odds_client.py` | float or NULL | NULL (free tier) — stored as NULL |

---

## Build Order

### Step 1 — `mlb/scripts/generate_v2_predictions.py` ← START HERE

Replace `generate_predictions_daily.py` as the primary MLB daily script.

For each player/prop line:
1. Run stat model → `stat_prob_over` (float)
2. Read DuckDB `ml_predictions` → `xgb_prob_over` via Poisson CDF (float or None)
3. Sample MAB weights from `mab_weighting.py` → `{stat: w_s, xgb: w_x}`
   - If xgb_prob_over is None: stat gets full weight (1.0), xgb skipped
4. BMA mean: `prob_over = w_s * stat_p + w_x * xgb_p` (normalized)
5. Bootstrap CI (N=500 Monte Carlo samples of Beta weight vectors):
   - Sample N weight pairs from Beta distributions
   - Compute N BMA outcomes
   - `ci_lower` = 2.5th percentile, `ci_upper` = 97.5th percentile
6. Derive direction: `prediction = 'OVER' if prob_over > 0.5 else 'UNDER'`
7. Compute `pp_edge = prob_over - pp_break_even` (using odds_type break-even)
8. Write to `ml_v2_predictions`:
   - `prob_over`, `ci_lower`, `ci_upper`
   - `component_probs` = JSON `{"stat": stat_p, "xgb": xgb_p}`
   - `mab_weights` = JSON `{"stat": w_s, "xgb": w_x}`
   - `market_implied` = NULL (until paid DK tier)
   - `true_edge` = NULL (until market_implied available)
   - `pp_edge`, `pp_break_even`, `odds_type`
   - `drift_flagged` = 0 (Step 3 will set to 1 when triggered)

**Fallback:** If xgb unavailable for a player → stat-only, weights `{stat: 1.0}`, CI from stat model uncertainty alone.

---

### Step 2 — Grader Update: `auto_grade_daily.py`

Add `ml_v2_outcomes` table. After grading `predictions`, also:
1. Match graded player/prop/date to `ml_v2_predictions`
2. Record HIT/MISS/VOID into `ml_v2_outcomes`
3. Update MAB: stat arm and xgb arm (already wired — just point at V2 rows)

`ml_v2_outcomes` schema:
```sql
CREATE TABLE IF NOT EXISTS ml_v2_outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    v2_prediction_id INTEGER REFERENCES ml_v2_predictions(id),
    game_date       DATE,
    player_name     TEXT,
    prop_type       TEXT,
    line            REAL,
    prediction      TEXT,   -- OVER/UNDER
    actual_value    REAL,
    outcome         TEXT,   -- HIT/MISS/VOID
    prob_over       REAL,   -- copied from ml_v2_predictions at grade time
    bma_correct     INTEGER, -- 1 if BMA direction matched actual
    created_at      TEXT
)
```

---

### Step 3 — KS Drift Detector Hook

Wire `hlss/ml_training/drift_detector.py` into the daily pipeline.

After grading each day:
1. Pass last 30 days of `actual_value` per prop to `drift_detector.detect()`
2. If KS p-value < 0.05 → set `drift_flagged=1` on today's `ml_v2_predictions` rows for that prop
3. Log drift events to `mlb_drift_log` table (game_date, prop_type, ks_stat, p_value)

Drift = scoring environment shifted (pitcher era change, weather, rule change). When flagged,
MAB decay runs immediately instead of waiting for the daily window.

---

## Success Metrics (from MASTER_PLAN.md)

| Metric | Target | Check date |
|--------|--------|------------|
| BMA P within 5% of actual outcomes | 500 graded trials | ~Aug 2026 (full season) |
| Net-of-fee arb yield | >3% | When CSA live |
| Snowball capital return | By Level 3 | When snowball live |

---

## Key Files

| File | Role |
|------|------|
| `mlb/scripts/generate_v2_predictions.py` | Step 1 — daily V2 prediction writer |
| `mlb/scripts/auto_grade_daily.py` | Step 2 — grader + ml_v2_outcomes + MAB update |
| `hlss/ml_training/mab_weighting.py` | MAB state (cold-start priors fixed Apr 24) |
| `hlss/ml_training/drift_detector.py` | Step 3 — KS drift detection |
| `mlb_feature_store/data/mlb.duckdb` | XGBoost predictions source |
| `mlb_feature_store/ml/predict_to_db.py` | Writes XGBoost predicted_value to DuckDB daily |
| `hlss/ml_training/setup_ml_v2_schema.py` | Creates ml_v2_predictions table (run once) |
| `hlss/bma_engine.py` | BMA aggregator (regression space — NOT used here; MLB uses probability space) |
| `hlss/shared/market_odds_client.py` | DK implied prob (NULL on free tier — stored cleanly) |
| `hlss/csa_state_machine.py` | Phase 2 Apex Arb — fires after Leg 1 settles |

---

## What is NOT in scope (intentionally)

- Supabase sync
- Discord posts
- FreePicks app
- Dashboard changes
- NHL / NBA (October 2026)
- DraftKings market implied (NULL until paid tier — don't block on it)
- home_runs ML model (stat model only — XGBoost underperforms naive baseline)

---

## Daily Schedule (MLB V2, once live)

| Time (CST) | Action |
|------------|--------|
| ~9:00 AM | `generate_v2_predictions.py` — stat + XGBoost → BMA → `ml_v2_predictions` |
| ~9:15 AM | `predict_to_db.py` — XGBoost feature store refresh (DuckDB) |
| ~3:00 AM next day | `auto_grade_daily.py` — grade → `ml_v2_outcomes` → MAB update → drift check |
