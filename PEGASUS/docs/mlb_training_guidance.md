# MLB ML Training Guidance — Do This Right From Day One
**Written: 2026-04-15 | Author: PEGASUS Session 5**

---

## Context: Why This Document Exists

The NHL ML models (v20260325_003) failed spectacularly despite showing +12.6% test improvement before deployment. The full failure analysis is in `PEGASUS/docs/nhl_ml_post_mortem.md`. This document extracts every lesson from that disaster and applies it to MLB — which starts from a cleaner position (statistical model behaving correctly, no circular feature dependencies) but faces the same structural traps.

**Read the NHL post-mortem first.** This document assumes you have.

---

## 1. Current MLB Status (as of April 15, 2026)

| Item | Status |
|------|--------|
| Statistical model | Working correctly. No flip bug detected. |
| XGBoost models | Exist in `mlb_feature_store/data/mlb.duckdb`, trained on `xgboost_v1` |
| ML predictions | Generated daily by mlb_feature_store pipeline |
| PEGASUS blend | 60/40 ML/stat via `mlb_ml_reader.py` — hits, total_bases, strikeouts, walks, outs_recorded |
| home_runs | EXCLUDED from blend (Rule 5: model worse than naive) |
| LEARNING_MODE | True — not yet blending in production orchestrator |
| Graded data | ~18,835 rows total in `mlb_predictions.db` calibration sample |

The current XGBoost models in `mlb.duckdb` are regression models (output = expected count). They were trained as part of the mlb_feature_store pipeline. **Before activating the full 60/40 blend in production, every item in the Pre-Training Checklist (Section 5) must be satisfied.**

---

## 2. Lessons From NHL — Applied to MLB

### Lesson 1: Never Use the Statistical Model's Own Probability as an ML Feature

**What killed NHL:** The primary ML feature was `f_prob_over` — the statistical model's own probability output. When the stat model broke (outputting 100% UNDER for shots when OVER was winning 57%), the ML model inherited the breakage. The feedback loop made the problem invisible in training metrics because the test set was drawn from the same broken period.

**MLB protection:**
- The XGBoost models in `mlb_feature_store` were trained on raw player features, NOT on statistical model output. Verify this before any retrain.
- Run `PRAGMA table_info` on the features table in mlb.duckdb to audit what columns were used.
- If ANY column from `mlb/scripts/statistical_predictions.py` output (probability, confidence_tier, expected_value) appears in the training features: **remove it before retraining.**
- Acceptable ML features: rolling stats (L3/L5/L10 averages), park factors, weather, opponent context, platoon splits, days rest, batting order. NOT the stat model's probability.

### Lesson 2: Always Measure Against Majority-Class Baseline, Not Against the Stat Model

**What killed NHL:** Baseline = statistical model prediction. When the stat model was broken (45.4% accuracy), beating it by 12.6% was trivial. The ML model actually barely beat always-UNDER (+0.9%), which is not actionable.

**MLB implementation:**
```python
# WRONG — this is what NHL did:
improvement = ml_accuracy - stat_model_accuracy  # 12.6% when stat is broken = noise

# RIGHT — this is the correct baseline:
under_rate = sum(1 for y in y_test if y == 0) / len(y_test)  # fraction UNDER in test
majority_class_accuracy = max(under_rate, 1 - under_rate)
real_improvement = ml_accuracy - majority_class_accuracy

# Gate: if real_improvement < 0.05 (5%), do NOT deploy. No exceptions.
if real_improvement < 0.05:
    raise ValueError(f"Model does not clear 5% improvement gate: {real_improvement:.1%}")
```

### Lesson 3: Walk-Forward Validation — Never a Single Test Split

**What killed NHL:** Test split = last 15% of the 90-day window. A model can memorize a single time window's characteristics. The shots_1_5 "improvement" was specific to March 12-25 test data.

**MLB implementation (required, non-negotiable):**
```python
# Walk-forward validation across multiple windows
def walk_forward_validate(df, n_windows=3, train_months=4, test_months=1):
    """
    For each window i:
      - Train on months 0..train_months+i
      - Test on month train_months+i+1
    Report AVERAGE improvement across all windows.
    """
    improvements = []
    for i in range(n_windows):
        # define cutoffs
        train_cutoff = train_start + (train_months + i) * 30
        test_start   = train_cutoff
        test_cutoff  = test_start + test_months * 30
        
        X_train, y_train = df[df.date < train_cutoff]
        X_test,  y_test  = df[(df.date >= test_start) & (df.date < test_cutoff)]
        
        model.fit(X_train, y_train)
        ml_acc  = (model.predict(X_test) == y_test).mean()
        maj_acc = max(y_test.mean(), 1 - y_test.mean())
        improvements.append(ml_acc - maj_acc)
    
    avg_improvement = sum(improvements) / len(improvements)
    return avg_improvement, improvements

# Gate: average improvement across ALL windows must be > 5%
# Any single window may dip below 5% — but the average must hold
avg_imp, windows = walk_forward_validate(df)
if avg_imp < 0.05:
    print(f"FAIL: avg improvement {avg_imp:.1%} across {len(windows)} windows")
    print(f"Per-window: {[f'{x:.1%}' for x in windows]}")
    # Do NOT deploy
```

**Minimum requirement for MLB:** 3 forward windows, each using 3+ months of training data. With MLB's 162-game season (April–September), aim for:
- Window 1: Train Apr–Jun, Test Jul
- Window 2: Train Apr–Jul, Test Aug
- Window 3: Train Apr–Aug, Test Sep

### Lesson 4: Skip Degenerate Lines — They Cannot Be Modeled

**What happened in NHL:** points_1_5 (87.8% UNDER) and shots_3_5 (86.8% UNDER) — always-UNDER beats any model here by definition. Models trained on degenerate lines waste parameters and produce overfit metrics.

**MLB degenerate line thresholds (skip ML training if majority class > 80%):**

| Prop/Line | UNDER% | Assessment |
|-----------|--------|------------|
| hits 2.5 | ~85% | DEGENERATE — skip ML, use stat-only |
| hits 1.5 | ~70% | BORDERLINE — train but gate strictly |
| total_bases 2.5 | ~65% | Modelable |
| total_bases 1.5 | ~55% | Modelable — competitive |
| strikeouts (varies by line) | Check empirically | Most competitive at O4.5–O6.5 |
| home_runs 0.5 | Rule 5 EXCLUDED | Worse than naive regardless of split |
| outs_recorded 16.5 | ~58% | Modelable |
| walks 0.5 | ~55% | Modelable |

**Implementation guard:**
```python
DEGENERATE_THRESHOLD = 0.80

for prop, line in prop_line_combos:
    under_rate = compute_under_rate(df, prop, line)
    if max(under_rate, 1 - under_rate) >= DEGENERATE_THRESHOLD:
        print(f"Skipping {prop}_{line}: {max(under_rate, 1-under_rate):.1%} majority class — degenerate")
        metadata[f"{prop}_{line}"]["model_type"] = "statistical_skipped_degenerate"
        continue  # no model trained; stat-only
```

### Lesson 5: Feature Deduplication — One Naming Convention

**What killed NHL:** 38-39 features included both `success_rate_season` (old) and `f_season_success_rate` (new) for the same underlying values. Near-duplicate columns cause coefficient instability in linear models and inflate apparent feature count.

**MLB implementation:**
- Every feature must use the `f_` prefix: `f_l5_avg_hits`, `f_season_k9`, `f_park_hr_factor`
- Context features use `ctx_` prefix: `ctx_temperature`, `ctx_wind_speed`
- Opponent features use `opp_` prefix: `opp_team_k_pct`, `opp_starter_era`
- Before training: run deduplication check that removes any column appearing twice under different names
- After training: print feature importance table. If any two features rank 1st and 2nd with near-identical importance (within 2%), they are probably duplicates — investigate

### Lesson 6: Calibration Split — Never Calibrate on the Validation Set

**What went wrong in early NBA:** The isotonic calibration was fit on the same validation set used for model selection. This overfits calibration to the val set, giving falsely confident probabilities on new data.

**MLB protocol (already implemented in train_models.py via the calibration fix):**
```
60% train / 15% val (model selection) / 10% cal (calibration ONLY) / 15% test (final evaluation)
```
Do not touch this. The 4-way temporal split is mandatory. **Never fit calibration on train or val data.**

### Lesson 7: Feature Importance Sanity Check — Single Feature Dominance = Overfit

**NHL finding:** shots_1_5 model had `success_rate_season` at 31.3% importance. Not terrible, but a useful canary.

**MLB gate:** If ANY single feature has importance > 50%, the model has overfit to that signal. Reject and investigate. Common causes:
- Leakage: a feature derived from the target (e.g., actual hit rate for THIS game, not historical)
- Degenerate data: some lines are trivially predicted by one stat
- Target encoding contamination

**Check:**
```python
feature_importances = dict(zip(feature_names, model.feature_importances_))
max_feat = max(feature_importances, key=feature_importances.get)
max_imp  = feature_importances[max_feat]

if max_imp > 0.50:
    raise ValueError(f"Single feature dominance: {max_feat} = {max_imp:.1%}. Check for leakage.")
```

---

## 3. MLB-Specific Traps to Avoid

### Trap 1: Starting Pitcher Data Leakage

MLB pitching props (strikeouts, outs_recorded, walks) depend heavily on the OPPOSING starting pitcher. The confirmed starter for TODAY's game is known in advance and is a legitimate feature. But DO NOT include:
- Actual strikeout outcome for today's game (obvious leakage)
- Confirmed lineup changes that happen after the model makes its prediction
- Today's game score or in-game context

Safe pitcher features: `ctx_opposing_starter_era`, `ctx_opposing_starter_k9`, pre-game park factor.

### Trap 2: Early-Season vs. Late-Season Distribution Shift

April stats are noisy. A player who hit .350 in April may regress to .270 by August. ML models trained on April–June data will overfit to early-season volatility.

**Mitigation:**
- Include season-to-date stats normalized by games played: `f_normalized_hits_per_PA` instead of raw `f_total_hits`
- Use 3-year rolling player baselines alongside current season stats
- Add `f_games_played` as a feature — the model can learn to discount early-season single-season metrics

### Trap 3: The "This Player Is Hot" Signal — It's Already Priced In

PrizePicks adjusts lines based on recent performance. A player who went 3-for-3 in his last 3 games will see his hits line move from 0.5 to 1.5. If your ML model's strongest feature is "L5 average hits," you're predicting the same thing PP already priced.

**Feature to prefer:** `f_hits_vs_line_L10` = how many of last 10 games did player exceed THIS SPECIFIC line. Not his raw average — his hit rate on this exact line. PP may not adjust the line as quickly as the player's rolling hit rate on it.

### Trap 4: Weather and Ballpark Collinearity

Wind speed, temperature, humidity, and park HR factor are highly correlated for outdoor stadiums. This creates collinearity issues for linear models.

**Options:**
1. Use XGBoost (handles collinearity naturally via tree splitting)
2. Create a single `f_scoring_environment_index` that combines park factor + weather into one composite score
3. Use PCA to reduce weather/park features to 2-3 orthogonal components

### Trap 5: Using Team-Level Stats for Individual Player Props

`opp_team_k_pct` (opponent team strikeout rate) is useful for pitcher props. But individual hitter matchups (platoon splits, vs-this-pitcher history) are more predictive than team averages for individual props. Team stats are the floor, not the ceiling.

**Priority order for batter props:**
1. Player vs. THIS specific starting pitcher (if ≥10 PA sample)
2. Player vs. LHP/RHP split (platoon)
3. Player's recent form vs. team's overall pitching quality
4. Team-level opponent stats

---

## 4. Minimum Data Requirements Before ML Training

| Prop | Minimum Graded Rows | Reason |
|------|---------------------|--------|
| hits (all lines) | 2,000 per line | High variance prop — need large sample |
| total_bases | 2,000 per line | Wide range (0-12) requires more data |
| strikeouts (pitcher) | 1,500 per line | Lower variance, pitcher-specific |
| outs_recorded | 1,500 per line | Relatively consistent per starter |
| walks | 2,000 per line | Rare events need larger sample |
| home_runs | DO NOT TRAIN | Rule 5 — model excluded permanently unless 5-year audit shows otherwise |

**Minimum for walk-forward validation:**
- At least 5 months of clean data (May–September of 2026 season)
- No data contamination (no stat model bugs affecting the prediction period)
- 100% opponent feature coverage (no null `opp_*` columns)

**Earliest realistic MLB ML training date: October 2026** (after full 2026 season data is collected and graded).

---

## 5. Pre-Training Checklist (Required Before Any Retrain)

**Run this checklist in order. Do not skip steps.**

### Data Quality
- [ ] Query `prediction_outcomes` for null `actual_value` rows — must be 0% null for last 30 days
- [ ] Verify stat model is behaving correctly: OVER% by prop matches historical rates (±10%)
  - hits 0.5: expect ~50-55% OVER
  - strikeouts (line-dependent): check vs. prior season
  - Do NOT train if any prop shows >80% one-direction for 3+ consecutive weeks without a structural reason
- [ ] Confirm `f_prob_over` or any stat model output is NOT in the feature set
- [ ] Check opponent feature coverage: `opp_*` columns must be non-null in ≥95% of rows
- [ ] Run feature deduplication check — no column appearing twice under different names

### Baseline & Evaluation Setup
- [ ] Baseline = always-majority-class (NOT stat model accuracy)
- [ ] Walk-forward validation configured: minimum 3 windows
- [ ] Degenerate line guard active: auto-skip if majority class ≥ 80%
- [ ] Calibration split is 60/15/10/15 (train/val/cal/test) — NOT a 3-way split

### Training Run
- [ ] Training script logs: per-prop baseline, ML accuracy, improvement, feature importances
- [ ] Feature importance gate: no single feature > 50%
- [ ] Walk-forward gate: average improvement > 5% across all windows
- [ ] Degenerate lines logged as `statistical_skipped_degenerate` in metadata
- [ ] Model saved with full metadata (feature_names, training_date, gate_results, walk_forward_windows)

### Post-Training Validation
- [ ] Run PEGASUS shadow audit on last 30 days of graded data
- [ ] Shadow audit must confirm: ML beats majority-class by >3% on ≥1 competitive prop/line
- [ ] Calibration buckets: mid-range predictions (40-60%) within ±10% of actual hit rates
- [ ] Do NOT activate blend until shadow audit clears on LIVE data (not just test set)

---

## 6. The Correct Frame: What We're Actually Solving

Statistical model: "Given this player's history, what is P(hits > 0.5)?"
PrizePicks: "Given this player's history, what is a fair line that balances our action?"

These are nearly the same question. Building an ML model to reproduce the same calculation PrizePicks already did adds no value.

**The correct frame for MLB ML:**
"Where does PrizePicks set a line that is inconsistent with the true distribution of outcomes, given situational context they don't fully price?"

Feature ideas that encode PP mispricing:
- `f_hit_rate_vs_this_exact_line_L20`: PP may not adjust line fast enough for a consistent performer
- `f_k_rate_when_team_trailing_L10`: pitcher behavior changes in comeback situations — PP averages ignore this
- `f_hits_allowed_vs_lefty_heavy_lineup_L10`: matchup-specific, not in team averages
- `f_days_since_last_start`: pitcher fatigue effect distinct from simple days_rest
- `f_altitude_adjusted_k_rate`: Coors Field pitching props are systematically mispriced by average K rates

These features answer "what does PP not know that we do?" That's where edge lives.

---

## 7. Summary Table — NHL Failures vs. MLB Safeguards

| NHL Failure | Severity | MLB Safeguard |
|-------------|----------|---------------|
| f_prob_over as primary feature (feedback loop) | CRITICAL | Verify no stat model output in features |
| Baseline = broken stat model (inflated improvement) | HIGH | Baseline = majority-class always |
| Single test split (memorization) | HIGH | Walk-forward: 3+ windows, avg > 5% |
| No forward validation on live data | HIGH | PEGASUS shadow audit required pre-activation |
| Degenerate lines modeled (87% one-direction) | MEDIUM | Auto-skip gate: majority class ≥ 80% |
| Feature duplicates (38 features = 18 signals) | MEDIUM | Deduplication check before training |
| Calibration overfit to val set | MEDIUM | 4-way split: train/val/cal/test |
| No feature importance gate | LOW | Max single-feature importance < 50% |
| home_runs model (worse than naive) | MEDIUM | Rule 5: permanently excluded from blend |

---

*Maintained in PEGASUS/docs/ — update this document when new failure modes are discovered.*
