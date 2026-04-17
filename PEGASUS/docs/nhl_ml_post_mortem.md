# NHL ML Post-Mortem: Why the Models Failed and How to Fix It Right
**Date: 2026-04-15 | PEGASUS Session 4**

---

## TL;DR

The NHL ML models (v20260325_003) failed for two independent reasons that compounded each other. First: the statistical prediction engine developed a hard bug around March 16 that caused it to output 100% UNDER for shots and points props, despite OVER being the actual majority outcome. Second: the ML training code had systematic methodology flaws — wrong baseline, duplicated features, a stat model feedback loop, and no real forward validation — that meant the impressive-looking test metrics (shots_1_5: +12.6% improvement) were measuring the ML model's ability to partially fix the stat model's bugs on one specific test window, not its ability to predict hockey outcomes.

Retraining in October with "fresh data" **will not fix this** if the same methodology is used. The stat model bug will still corrupt training data if it isn't fixed first. The evaluation framework will still overstate performance. The dependency on `f_prob_over` will still create a circular reference. We will get the same result.

This document is the specification for doing it correctly.

---

## 1. What Actually Happened — Timeline

```
Jan–Feb 2026    Statistical model working correctly:
                shots_1_5: predicts OVER ~75% | actual OVER: 57% (directionally right)
                points_0_5: predicts OVER ~55% | actual OVER: 50% (directionally right)

Week 12         STATISTICAL MODEL BUGS OUT (~March 16, 2026):
(Mar 16-22)     shots_1_5: flips to 100% UNDER | actual OVER still 57%
                points_0_5: flips to 0-2% OVER  | actual OVER still 50-55%
                shots_2_5: similar pattern
                [This is a script bug — see Section 2, Root Cause #1]

Week 12-15      Last 3 weeks of training window contain corrupted stat model output.
(Mar 16-25)     f_prob_over feature is now 0.36 for shots (should be ~0.64).
                ML model is being "trained" on a broken signal.

Mar 25, 2026    ML retrain v20260325_003 runs.
                Test set = last 15% of 90-day window = ~Mar 12–25.
                Stat model already broken for last 3 weeks of test period.
                Stat baseline gets 45.4% on test set (broken, easy to beat).
                ML model gets 57.9% by learning to partially override the bug.
                Reported improvement: +12.6%. This is noise, not signal.

Mar 25–today    Models deployed, stat model still broken.
                SHADOW AUDIT: ML gets 44.2% on shots_1_5, barely above always-UNDER (43.4%).
                The correction it learned on the test set doesn't generalize.
```

---

## 2. Root Cause Analysis — Five Layers

### Root Cause #1 (CRITICAL): The Statistical Model Has a Hard Bug Right Now

This is the most urgent finding and it is independent of ML.

**Current state of the V6 stat model (as of April 15, 2026):**

| Prop/Line     | Stat UNDER% | Actual OVER% | Assessment           |
|---------------|------------|-------------|----------------------|
| shots 1.5     | 100%       | 57%         | Systematic wrong direction |
| shots 2.5     | 100%       | 36%         | Over-confident UNDER |
| shots 3.5     | 100%       | 13%         | Extreme line, acceptable |
| points 0.5    | 100%       | 51%         | Systematic wrong direction |
| points 1.5    | 100%       | 12%         | Extreme line, acceptable |
| shots 0.5     | 0%         | 74%         | Correct — OVER is right |

The statistical model is telling users to pick UNDER on shots_1_5 when OVER wins 57% of the time. **Smart picks flowing out of this engine for shots_1_5 and points_0.5 are currently wrong at above-chance rates.**

This flip happened at Week 12 (March 16-22) and has been in production ever since. The likely cause: a change in how Poisson lambda is estimated in `nhl/scripts/generate_predictions_daily_V6.py` — possibly the season-window cutoff was tightened, pulling lambda from a small recent sample that happens to show low scoring, or the comparison direction was inverted for certain lines.

**This is a P0 production bug. It must be fixed before any ML retraining discussion is relevant.**

### Root Cause #2 (HIGH): ML Training Used the Broken Stat Model as Its Primary Feature

Every ML model in v20260325_003 lists `f_prob_over` in its feature set — the statistical model's own probability output. This creates a dependency loop:

```
stat_model → f_prob_over (feature) → ML model → ML probability
```

When the stat model is correct, `f_prob_over` provides useful signal. When it breaks, ML inherits the breakage. The stat model's last 3 weeks of training data (March 2-25) were transitioning from correct to fully broken, which means the ML model was trained on a mixture of good and garbage `f_prob_over` values.

More fundamentally: using the stat model's probability as an ML feature means the ML model cannot generate independent alpha. It is estimating "how confident is the stat model" rather than "what does the raw player data say about outcomes." These are very different questions. We want the second one.

### Root Cause #3 (HIGH): The Baseline Was Wrong — The Model Looks Better Than It Is

The train_models.py code computes improvement as:
```python
improvement = ml_accuracy - baseline_accuracy
where baseline = statistical_model.predict(test_set)
```

When the stat model was broken during the test period (45.4% on shots_1_5), beating it by 12.6% is a very low bar. The correct baseline is `max(always-OVER, always-UNDER)` — whichever direction wins more in the test period.

For shots_1_5 in the test period (March 12-25): OVER was winning ~57%. So:
- Always-OVER baseline: ~57%
- Stat model baseline: 45.4% (broken)
- ML model: 57.9%
- Reported improvement vs stat model: **+12.6%** (looks great)
- Real improvement vs always-OVER: **+0.9%** (trivially above random)

The ML model was essentially learning to partially fix the stat model's bugs on the test window. That's not a useful skill.

### Root Cause #4 (MEDIUM): Feature Set Has 18 Signals Masquerading as 38

Each v20260325_003 model has 38-39 features, but they include both the old naming convention (`success_rate_season`) and the new `f_` prefix convention (`f_season_success_rate`) for the same underlying values. The DB's `features_json` evolved from unprefixed to `f_`-prefixed keys over time. When the training loader joined both, it created near-duplicate columns.

For logistic regression specifically, duplicated features cause coefficient instability — the model distributes weight across both versions instead of one clean signal, reducing interpretability and slightly degrading predictive accuracy. The feature importance numbers in the metadata are partially an artifact of this.

### Root Cause #5 (MEDIUM): No Real Forward Validation

The test split is a single temporal slice at the end of the 90-day training window. This tests generalization within the current season's regime, not across different regimes. A model that learned the last 13 days of March will look good on a test set taken from those same 13 days.

Walk-forward validation (train on months 1-6, test on 7, then train on 1-7, test on 8, etc.) would have shown that the "12.6% improvement" was specific to the test window, collapsing to <1% on subsequent windows. We would have known before deploying.

---

## 3. Current State: What Smart Picks Are Actually Receiving

The smart_pick_selector.py (`shared/smart_pick_selector.py`) recalculates probability using a Poisson model based on recent player form. This is somewhat insulated from the stat model bug because it uses `our_lambda` (derived from recent game logs) rather than the stored DB probability. However:

1. The PP-matched recalculation still uses the **same underlying Poisson** assumptions that are broken in V6
2. The stat model bias feeds into what gets flagged as a smart pick in the first place — if V6 says 100% UNDER for shots_1_5, those predictions don't get paired with OVER PP lines, so OVER edges are invisible to the system
3. The `ml_adjustment` field in SmartPick shows "ML vs naive baseline difference" — this number is meaningless when both baseline and ML are broken

In short: **users are receiving UNDER picks on shots_1_5 when OVER is the correct directional call.** The magnitude of this error is significant — 57% vs 43% is a 14-point directional gap.

---

## 4. The Bigger Picture: Why Statistical-On-Top-Of-Statistical Won't Beat The Market

The user's question is the right one: anyone can build a statistical model. To build something genuinely better than what every punter on Twitter has, you need to answer a different question than "will this player go OVER 1.5 shots?"

**The question that generates edge is:** "Where is PrizePicks pricing a line at a different expected value than the true probability?"

PrizePicks is not setting lines at the true probability. They are setting lines to balance action, maximize hold percentage, and minimize sharp liability. Sometimes they are conservative (underestimating OVER probability to attract OVER bets). Sometimes they shade against player narratives. These pricing errors are the actual edge.

A statistical model that predicts "player A averages 2.3 shots per game, so OVER 1.5 shots" is doing exactly what PrizePicks already did when they set the line at 1.5. You are not adding information — you are reproducing their calculus.

**What adds information:**
1. **Situational deviations from expectation**: The player averages 2.3 shots but plays back-to-back with 1 day rest, on the road, against a team allowing 3.1 shots per game to that position. Does PP adjust their 1.5 line for this? Often no.
2. **Player-specific game-script sensitivity**: Does this player's shot count correlate with score differential? If his team goes down early, does he shoot more or less? PP sets lines based on averages; these tendencies are not always in the price.
3. **Opponent quality adjusted by situation**: Not just "opponent allows X shots per game" but "opponent in the 3rd period of a blowout allows Y shots" — the situation changes what opponent stats mean.
4. **Line-setting inefficiency detection**: If a line looks out of position relative to recent player performance AND opponent context AND situational factors, that's where the edge is. This requires comparing your model's probability against the implied probability of the PP line odds (break-even), not just whether you predict OVER.

The PEGASUS architecture is already aligned with this philosophy (calibration layer, situational intelligence, edge calculation). The gap is in the ML training methodology — which needs to be rebuilt to search for PrizePicks pricing inefficiencies, not to reproduce the same predictions PrizePicks already made.

---

## 5. Recommendations for Next Season — Ordered by Priority

### Priority 1 (Do now, before any ML work): Fix the Statistical Model Bug

Investigate `nhl/scripts/generate_predictions_daily_V6.py`. The flip to 100% UNDER for shots_1_5 and points_0_5 started Week 12 (March 16-22). Check:
- Was the Poisson lambda computation changed? (e.g., smaller rolling window, different stat column)
- Was the comparison direction changed? (e.g., `prob_over` vs `prob_under` inversion)
- Did a column rename change which value is being fetched from `player_game_logs`?

Until this is fixed, the smart picks for shots_1_5 and points_0_5 are systematically biased in the wrong direction.

### Priority 2 (Pre-training data work): Clean the Training Dataset

Before retraining, run a data audit:
1. Tag all predictions generated after Week 12 (March 16, 2026) as "corrupted_stat_model" — flag these rows so they can be excluded from training or down-weighted
2. Verify that the stat model bug affected the `f_prob_over` feature in those rows (it did — avg 0.638 in shadow period represents P(UNDER), not P(OVER))
3. Keep the historical data from before the bug — it's clean and represents 3+ months of valid training signal

### Priority 3 (Training methodology): Remove `f_prob_over` from ML Features

The ML model cannot generate alpha if its primary feature is the stat model's own probability. Remove `f_prob_over` from the feature set. The ML model should learn from raw player and opponent features independently.

What to use instead:
- Rolling performance vs line (not vs stat model prediction): `pct_games_exceeded_1_5_shots_L10`
- Opponent shots-against rates from actual game logs, not as derived by stat model
- Game context: back-to-back, days rest, home/away, travel (cross-timezone)
- Situational: PEGASUS situational intel score (already built in Step 3)
- Season trend: is the player's rolling average rising or falling?

### Priority 4 (Training methodology): Fix the Baseline

Replace `baseline = statistical_model.predict(test_set)` with:
```python
majority_class = 1 if y_test.mean() > 0.5 else 0
baseline_accuracy = max(y_test.mean(), 1 - y_test.mean())
# i.e., always-predict-the-majority-class accuracy
```

If your ML model doesn't beat always-OVER or always-UNDER with a meaningful margin (we suggest >5%), it is not adding value. There is no edge in reproducing what PrizePicks already knows.

### Priority 5 (Training methodology): Deduplicate Features

Choose one naming convention for features. The `f_*` prefix system is canonical (it's what current predictions generate). Remove the non-prefixed duplicates:
- Remove: `success_rate_season`, `sog_season`, `opp_points_allowed_l10`, etc.
- Keep: `f_season_success_rate`, `f_season_avg`, `f_opp_allowed_l10`, etc.

This reduces the feature space by ~50% with no information loss and eliminates multicollinearity for logistic regression.

### Priority 6 (Training methodology): Walk-Forward Validation

Replace the single test split with walk-forward validation:
```
Train: Nov–Feb → Test: Mar
Train: Dec–Mar → Test: Apr
Train: Jan–Apr → Test: May (not possible for NHL, but apply this to NBA/MLB)
```
Report the AVERAGE test accuracy across all forward windows. A model that consistently delivers +3-5% improvement across multiple forward windows is real. A model that delivers +12.6% on one window and +0.9% on the next has learned noise.

### Priority 7 (Scope): Skip Degenerate Lines for ML

Lines where >75% of outcomes fall one direction are not modelable. Logistic regression cannot beat always-majority-class on these — the signal-to-noise ratio is too low:

| Line         | UNDER% | Assessment |
|-------------|--------|------------|
| points 1.5  | 87.8%  | Degenerate — skip ML |
| shots 3.5   | 86.8%  | Degenerate — skip ML |
| shots 4.5+  | 88%+   | Degenerate — skip ML |

For these lines, the statistical model's prediction is essentially "always UNDER," which is correct 87% of the time. ML can't improve on this because there is no predictable variation to learn. Save the model capacity for the competitive lines.

**Lines worth modeling (40-65% majority):**
- shots_1_5 (43% UNDER, 57% OVER — near even, most actionable)
- shots_2_5 (64% UNDER — moderate, modelable)
- points_0_5 (49% UNDER, 51% OVER — essentially coin flip on averages, situational edge possible)

### Priority 8 (Architecture): Build Toward PP Line Targeting

Medium-term, the training target should change from:
```
Does player exceed our fixed line (e.g., 1.5)?
```
to:
```
Does player exceed the PrizePicks line that exists on a given day?
```

PP adjusts lines. A player might be at shots_2.5 one week and shots_1.5 the next. Training on fixed lines means the model learns "does this player get 1.5+ shots" but PrizePicks might be asking you a different question on any given day. Aligning the training target to the actual PP line improves both training relevance and evaluation.

This requires storing PP lines in the DB alongside predictions (which is partially done already via `odds_type` and `pp_line` columns in smart_pick_selector output).

---

## 6. Retrain Specification for October 2026

When the NHL season resumes, here is the retrain protocol that should be followed:

**Pre-training checklist:**
- [ ] Stat model bug is confirmed fixed — shots_1_5 predicts OVER for players with lambda > 1.5
- [ ] Training data excludes rows from March 16 – (fix date) where `f_prob_over` was corrupted
- [ ] `f_prob_over` is removed from feature_names in train_models.py
- [ ] Baseline computation updated to always-majority-class
- [ ] Feature deduplication applied (no non-prefixed + f_-prefixed duplicates)

**Minimum data requirements:**
- At least 60 calendar days of clean post-fix predictions per prop/line
- Minimum 2,000 graded rows for competitive lines (shots_1_5, shots_2_5, points_0_5)
- All rows must have full opponent feature coverage (f_opp_allowed_l10, f_opp_allowed_l5, etc.)

**Validation gate (no model ships without clearing all three):**
1. Walk-forward accuracy improvement over always-majority-class: **>5%** averaged across at least 2 forward windows
2. No single feature with importance >50% (single-feature dominance = overfit)
3. Calibration: predicted probability buckets (40-50%, 50-60%, 60-70%) must be within ±10% of actual hit rates in the hold-out set

**Degenerate line handling:**
- Auto-skip training for any prop/line where majority-class accuracy >80%
- These lines continue to use statistical model output only
- Flag them in metadata as `model_type: "statistical_skipped_degenerate"`

---

## 7. What "Doing It Right" Looks Like

The difference between a system that just produces picks and one that actually generates edge comes down to one thing: **the model must encode information that PrizePicks doesn't already have.**

PrizePicks has:
- Player season averages
- Recent form (their analysts watch games)
- General home/away splits
- Obvious injury information

We can beat them on:
- **Situational granularity at scale**: Processing back-to-back schedules, exact rest days, cross-timezone travel, opponent defensive context, and playoff/seeding stakes simultaneously across all players — things their analysts can't manually assess for 100 players a night
- **Player-specific game-script tendencies**: Does Player X shoot more when his team is trailing? Does he take fewer shots in blowout wins? These correlations exist and PP lines don't always reflect them
- **End-of-season motivation signals**: Already built in PEGASUS Step 3. A team locked into a playoff seed plays differently than a team fighting for it. This is highly predictable and PP lines often lag
- **Calibrated edge vs break-even**: Our system distinguishes between standard/goblin/demon lines with different break-even thresholds. A 55% confident pick is a good play at demon odds, a losing play at goblin. PP doesn't show you this — we do

None of that requires a neural network. It requires clean features, honest evaluation, and the discipline to only show picks where the model's probability genuinely clears the break-even of the odds type being offered.

The goal for the October retrain is not "ML beats stat model." It is: **"the ML model's probability estimate, when above the odds break-even, produces a positive expected return over 300+ predictions."** That is the bar. Everything above is in service of clearing that bar.

---

---

## 8. Hits and Blocked Shots: Include From Day One

These props were added March 8, 2026. By end of this season (~April 18) we'll have ~800-900 graded rows per line. That's below the 2,000-row minimum for reliable training, but the data is clean and the stat model for these props behaves correctly (no evidence of the flip bug affecting hits/blocked_shots).

**Current data and profile:**

| Prop/Line            | n (to date) | OVER% | Majority% | ML Viable? |
|---------------------|-------------|-------|-----------|------------|
| hits 0.5            | ~800        | 55%   | 55%       | Yes — competitive line, near even split |
| hits 1.5            | ~800        | 27%   | 73%       | Borderline — skewed but some signal possible |
| hits 2.5            | ~800        | 15%   | 85%       | Skip — degenerate |
| blocked_shots 0.5   | ~800        | 41%   | 59%       | Yes — competitive, UNDER edge |
| blocked_shots 1.5   | ~800        | 19%   | 81%       | Skip — degenerate |

**Why hits and blocked_shots are valuable:**
These are physical/role-based props. A fourth-liner who logs 15 minutes and fights for pucks has very consistent hit counts. A defensive defenseman blocks shots every game. PrizePicks doesn't always price these well because their model likely leans heavily on season averages — it doesn't distinguish between a physical winger on a defensive team (consistent 3-4 hits) and a skill winger who gets similar ice time but never hits. Situational context (road games, back-to-backs, high-stakes games where defensive structure tightens) also affects these in detectable ways.

**Plan for next season:**
- Begin collecting hits and blocked_shots from **game 1 of the 2026-27 season** — same priority as points and shots
- The ~800 rows from this season provide warm start data for feature engineering and exploratory analysis
- Target first ML training for hits_0.5 and blocked_shots_0.5 after **January 2027** if 2,000+ rows are available
- Until then: use statistical model (it's behaving correctly for these props — no flip bug observed)
- Do not train hits_2.5 or blocked_shots_1.5 — too skewed. Use always-UNDER for these with no model.

**Feature additions needed for hits/blocked_shots:**
- `f_avg_hits_L5`, `f_avg_hits_L10`, `f_season_hits_avg` (already being stored in player_game_logs)
- `f_opp_hits_allowed_L10` — opponent defensive aggression rating
- `f_physical_player_flag` — binary: player averages >2.5 hits/game season (identifies hitters)
- `f_avg_toi` — ice time directly affects both hits and blocked shots opportunity count
- For blocked_shots specifically: `f_is_defenseman` and `f_opp_shot_volume` (high-shot teams create more block opportunities)

---

## Appendix: Data Used in This Analysis

| Query | Finding |
|-------|---------|
| OVER rate by month, shots_1_5 | Consistent 56-59% — no distribution shift |
| Stat model UNDER% by week, shots_1_5 | Flipped from 24% → 100% at Week 12 (Mar 16) |
| Stat model UNDER% by week, points_0_5 | Flipped from 34% → 100% at Week 12 (Mar 16) |
| Current V6 output by prop (last 7d) | points_0_5, shots_1_5, shots_2_5 all 100% UNDER |
| Shadow audit, 30 days graded data | shots_1_5 ML: +0.9% vs baseline (not +12.6%) |
| Calibration buckets, shots_1_5 | <40% bucket has 50.7% OVER hit rate — random |
| Feature completeness check | 100% opp feature coverage in last 30 days |
| Training window vs shadow period | Stat model predicts_UNDER: 28.5% in train, 100% in shadow |
