# Plan: SportsPredictor → Rithmm-Caliber App

## Context

The SportsPredictor codebase is a mature, three-sport (NHL, NBA, MLB) prediction system in **data collection phase** with strong hit rates (NBA 79.1%, NHL 68.6%). The goal is to evolve it into a polished, user-facing product like Rithmm that shows **model confidence vs. implied sportsbook odds** across MLB/NBA/NHL game lines, player props, and over/unders.

The user is concerned about:
1. Whether headline accuracy numbers are overstated (UNDER bias risk)
2. Whether the math is trustworthy before showing users
3. How to produce the clean, coherent look of a professional app

---

## Key Risks & Findings (from codebase analysis)

### Risk 1: UNDER Bias Inflates Accuracy (CRITICAL)
- NBA system predicts UNDER **81.2%** of the time → 84.2% UNDER accuracy
- NHL predicts UNDER **67.3%** of the time → 74.4% UNDER accuracy
- If the model learned "always bet UNDER," it could achieve ~60-70% accuracy trivially because sportsbooks tend to set props slightly high
- **Must-do before launch**: Run always-UNDER baseline test. Real edge = (our accuracy) − (always-UNDER accuracy)

### Risk 2: No Trained ML Models Yet
- System is running **statistical-only** (Poisson/Normal distribution)
- ML training infrastructure is built (`ml_training/train_models.py`) but no `.joblib` models exist
- NBA ML retrain attempt (Mar 15) caused catastrophic collapse: 84% → 47% UNDER accuracy
- **Do not train ML until calibration audit validates statistical model is sound**

### Risk 3: EV Calculated Against Wrong Baseline
- Current: edge = model_prob − 0.545 (PrizePicks break-even), assumes flat -110
- Real sportsbooks have variable juice (+110, -125, etc.) per line
- Need to fetch actual book odds and compute true EV per pick

### Risk 4: Calibration Untested Empirically
- Isotonic calibration code exists for future ML models
- Statistical model uses hard caps (18%-77% NHL) — not empirically validated
- No reliability diagram (calibration plot) has ever been generated
- When model says 70% probability, does it actually hit ~70% of the time?

### Risk 5: MLB Disconnected from App
- MLB pipelines, database, feature extractors, and grading scripts are **fully built**
- 71,532 historical game logs backfilled
- MLB is **not wired** into `api/picks.py` or the mobile app

---

## Implementation Plan

### Phase 0: Calibration Audit — "Are Our Numbers Real?" (do first)
**File to create**: `shared/calibration_audit.py`

Goal: Generate an honest scorecard before showing users anything.

Steps:
1. **Reliability diagram per sport**: Bin predictions into 10% probability buckets (0-10%, 10-20%, … 90-100%). For each bucket, calculate actual hit rate. A calibrated model's dots fall on the diagonal.
2. **Always-UNDER baseline test**: Calculate what accuracy would be if we predicted UNDER on every pick. Compare to our actual accuracy.
   - Formula: `real_edge = our_accuracy - always_under_accuracy`
   - If real_edge < 3%, our "edge" is mostly just UNDER bias
3. **Tier performance validation**: For each tier (T1-ELITE through T5-FADE), calculate hit rate with 95% confidence interval. T1-ELITE must hit meaningfully better than T4-LEAN.
4. **Brier score**: Lower = better calibrated. Compare our statistical model Brier score vs. the always-UNDER naive model.
5. Output: Print calibration report to terminal + save JSON to `data/calibration_report_{sport}_{date}.json`

**SQL queries needed** (both databases):
- Group predictions + outcomes by probability bucket → hit rate
- Group by confidence_tier → hit rate + count
- Always-UNDER accuracy: `COUNT(outcome='HIT' AND prediction='UNDER') / COUNT(*)`

**Acceptance criteria**: Real edge > 3% above always-UNDER baseline for both sports before proceeding to user-facing features.

---

### Phase 1: Odds Integration (both PrizePicks + sportsbooks)

#### 1a. PrizePicks (already working — extend to MLB)
- `shared/prizepicks_client.py` handles NHL and NBA
- Add MLB league_id=2 to the client
- Wire MLB picks into `shared/smart_pick_selector.py`

#### 1b. Sportsbook Odds via The Odds API
- **Cheaper alternatives to evaluate first**:
  - ESPN API (free, already in `shared/fetch_game_odds.py`): covers game-level moneyline/spread/total but **not player props**
  - PrizePicks API (free, working): covers props but is DFS-specific
  - The Odds API **Developer tier ($49/month)**: most reliable for player props from DraftKings/FanDuel/BetMGM. Only charge once per request, ~1,500-3,000 calls/month needed
  - Recommended: start with The Odds API free tier (500 req/month) to validate, then upgrade
- Extend `shared/fetch_game_odds.py`:
  - Add `fetch_player_prop_odds(sport, game_date)` function
  - Markets to fetch: `player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_shots_on_target`
  - Store: `implied_probability` (convert American odds → probability), `book_line`, `book_odds`, `book_name`
- **True EV formula**: `ev = (model_prob × (1 + decimal_odds)) - 1`
- Add `implied_probability` and `true_ev` columns to predictions tables (migration needed for NHL/NBA/MLB DBs)

**Key file**: `shared/fetch_game_odds.py` (17KB, already exists — extend it)

---

### Phase 2: Backend Wiring (FastAPI)

**Files to modify**: `api/picks.py` (14KB), `api/performance.py` (14KB)

1. **Add MLB to picks endpoint** (`api/picks.py`):
   - Currently queries NHL and NBA databases only
   - Add third database query path for `mlb/database/mlb_predictions.db`
   - MLB prop types: pitcher strikeouts, batter hits, home runs, RBIs, etc.

2. **Enrich pick response schema** with new fields:
   ```python
   # Add to pick response:
   implied_probability: float     # from sportsbook
   true_ev: float                 # (model_prob × decimal_odds) - 1
   pp_edge: float                 # vs PrizePicks break-even (existing)
   tier_hit_rate: float           # historical hit rate for this tier
   tier_sample_size: int          # how many graded predictions in this tier
   always_under_baseline: float   # naive baseline for this sport
   ```

3. **New endpoint**: `GET /api/performance/tier-breakdown`
   - Returns tier hit rates with confidence intervals
   - Powers the "How often does T1-ELITE hit?" display in the app

---

### Phase 3: Mobile App Polish (React Native/Expo)

**React Native + Expo is the right choice.** Used by Shopify, Discord, Tesla. The existing app is well-structured. The issue is design execution, not technology.

**What makes Rithmm look good (and what to build):**

#### 3a. Design System File
Create `mobile/src/theme/index.ts`:
```typescript
// Colors
ELITE_GOLD = '#F5A623'      // T1-ELITE badge
STRONG_GREEN = '#27AE60'    // T2-STRONG
GOOD_BLUE = '#2980B9'       // T3-GOOD
LEAN_GRAY = '#7F8C8D'       // T4-LEAN
FADE_RED = '#E74C3C'        // T5-FADE
BG_DARK = '#0F1117'         // Background
CARD_BG = '#1A1D2E'         // Card surface
TEXT_PRIMARY = '#FFFFFF'
TEXT_SECONDARY = '#A0AEC0'

// Typography scale, spacing constants, border radius
```

#### 3b. Pick Card Redesign
Rebuild `mobile/src/components/PickCard.tsx` (create if not exists) with:
- Player name + team + prop type header
- Large OVER/UNDER chip with tier color
- **Two-bar comparison**: "Model 72%" vs "Implied 54%" (horizontal bars, side by side)
- Edge badge: "+18% edge" in tier color
- Tier badge: "T1-ELITE" with appropriate color
- Small footer: "T1-ELITE historically hits 71% (n=847)"

#### 3c. SmartPicksScreen Enhancement
`mobile/src/screens/SmartPicksScreen.tsx`:
- Sport filter tabs (ALL / NHL / NBA / MLB) at top
- Sort options: By Edge, By Tier, By Sport
- Section headers: "Today's Elite Plays" / "Strong Plays" / "Leans"
- Pull-to-refresh with skeleton loading states

#### 3d. Performance Screen Enhancement
`mobile/src/screens/PerformanceScreen.tsx`:
- Calibration chart: Model Probability vs Actual Hit Rate (line chart using react-native-chart-kit)
- Tier breakdown table: T1 | T2 | T3 | T4 with hit rate + sample size
- "Always-UNDER baseline" vs "Our model" comparison bar
- 30-day rolling accuracy trend

#### 3e. Animations & Polish
- Add `react-native-reanimated` for card entrance animations
- Skeleton loading screens (avoid blank states)
- Haptic feedback on pick selection (`expo-haptics`)
- Consistent 8px spacing grid throughout

---

### Phase 3.5: Situational Intelligence Layer (URGENT — playoff timing)

**Spec already exists**: `docs/plans/situational_intelligence_layer.md` (665 lines, detailed handoff doc)

**The Problem**: The model treats every game identically. Kawhi Leonard in a win-or-go-home playoff game gets the same prediction as a regular season game in January. This is wrong in both directions:
- **Star players in elimination games**: More minutes, full effort, coaches don't rest them → stats likely OVER regular season averages
- **Eliminated teams / locked seeding**: Starters benched early, minutes reduced, coaches rest players for next season → stats likely UNDER normal
- **Playoff intensity generally**: Home/away splits change, defensive intensity increases, pace slows

**Design (from existing spec)**: Advisory overlay — does NOT modify database predictions or probabilities. Instead adds 3 advisory fields to each pick output:
- `situation_flag`: `HIGH_STAKES` | `DEAD_RUBBER` | `REDUCED_STAKES` | `USAGE_BOOST` | `NORMAL`
- `situation_modifier`: float (-0.15 to +0.05) — displayed as a warning/boost, never written to DB
- `situation_notes`: human-readable (e.g., "LAL fighting for 4-seed, 2 games left — Kawhi expected full minutes")

**Motivation Score Gradient (0.0–1.0)**:
- Eliminated → 0.05–0.15 (DEAD_RUBBER, high fade risk)
- Exact seed locked, playoffs clinched → 0.10–0.25 (REDUCED_STAKES)
- Clinched playoffs, seed moveable → 0.40–0.60 (MEDIUM stakes)
- Bubble team, fighting for seeding → 0.65–1.00 (HIGH_STAKES, usage boost candidates)
- Win-or-go-home playoff game → 1.00 (maximum flag, applies USAGE_BOOST to stars)

**Files to modify** (per existing spec):
1. `shared/pregame_intel.py`: Add `fetch_season_context()`, `get_situation_flag()`, `get_usage_beneficiaries()`, `get_situation_notes()`
2. `shared/smart_pick_selector.py`: Add 3 situational fields to `SmartPick` dataclass, populate them
3. `api/picks.py`: Include situational fields in API response
4. `mobile/src/screens/SmartPicksScreen.tsx`: Show situational warning/boost badge on pick cards (e.g., yellow "PLAYOFF INTENSITY" banner or red "DEAD RUBBER" warning)

**Why urgent**: It's April 15, 2026. NBA playoffs are active. Win-or-go-home games are happening right now. Without this layer, the model will confidently predict UNDER on players who are about to go off in elimination games.

---

### Phase 4: ML Model Training (gated on Phase 0 results)

**CONFIRMED: No NHL ML models exist locally.** `ml_training/model_registry/` directory does not exist. `nhl/scripts/v2_config.py` shows `MODEL_TYPE = "statistical_only"`. The HybridPredictionEngine code was written to support 60/40 blend but never activated — no `.joblib` files ever created. The user's memory of a 60/40 blend likely refers to the code being written, not models being trained. Probable cause: training work done on a different machine/branch that was never committed to GitHub.

**Immediate action before training**: Check other machines/branches for `model_registry/` contents. If found, commit them. If not, train from scratch.

**Training plan** (gated on Phase 0 calibration audit passing):
1. Run `ml_training/train_models.py --sport nhl --prop points_0.5` (most data, best starting point)
2. **Shadow mode**: Run ML predictions alongside statistical for 2 weeks. Log both, surface statistical in app. Compare accuracy.
3. Cutover only if: held-out test accuracy (last 30 days) > statistical accuracy by >2 percentage points
4. Auto-revert guard: if post-cutover accuracy drops >5% from pre-cutover baseline → set `MODEL_TYPE = "statistical_only"` immediately
5. **NBA**: Do NOT attempt ML training until NHL validates. The Mar 15 disaster (84% → 47%) is a hard warning. When NBA training resumes, use `LogisticRegression(C=0.1)` only — no XGBoost/gradient boosting.
6. **MLB**: Trained LR models exist locally (not in GitHub). Priority: commit them to `ml_training/model_registry/mlb/` using `model_manager.py`, then wire into prediction pipeline. Only ship STRONG models (+8% vs naive). Exclude Home Runs (-30.1% vs naive).

**Configuration**: Set `MODEL_TYPE = "hybrid"` in sport config only after shadow mode validates.

---

## Critical Files Reference

| Purpose | Path |
|--------|------|
| Calibration audit (NEW) | `shared/calibration_audit.py` |
| Odds fetching (extend) | `shared/fetch_game_odds.py` |
| PrizePicks client (extend to MLB) | `shared/prizepicks_client.py` |
| Smart pick selector (extend to MLB) | `shared/smart_pick_selector.py` |
| Edge calculator | `shared/edge_calculator.py` |
| FastAPI picks router (extend) | `api/picks.py` |
| FastAPI performance router (extend) | `api/performance.py` |
| Mobile picks screen (redesign) | `mobile/src/screens/SmartPicksScreen.tsx` |
| Mobile performance screen (extend) | `mobile/src/screens/PerformanceScreen.tsx` |
| Design system (NEW) | `mobile/src/theme/index.ts` |
| Pick card component (NEW/rebuild) | `mobile/src/components/PickCard.tsx` |
| NHL config | `nhl/scripts/v2_config.py` |
| NBA config | `nba/scripts/nba_config.py` |
| MLB config | `mlb/scripts/mlb_config.py` |
| ML training | `ml_training/train_models.py` |
| Orchestrator | `orchestrator.py` |

---

## Execution Order

```
URGENT (do first — playoffs happening now):
  Phase 3.5: Situational Intelligence Layer
    → NBA playoff flags, Kawhi-type adjustments, DEAD_RUBBER warnings

Phase 0a: Calibration audit
    → Are our numbers real? vs naive baseline for NHL/NBA/MLB
    → Includes confidence inflation filter (see below)
    → Gate everything else on this

Phase 0b: Codebase scrub (parallel with Phase 0a — can be done independently)
    → Inventory, deduplicate, standardize naming, archive dead code

Phase 1a: Extend PrizePicks to MLB
Phase 1b: Wire The Odds API for sportsbook prop lines  (parallel)
    ↓
Phase 2: FastAPI — add MLB + implied_probability + tier stats + situational fields
    ↓
Phase 3: Mobile app — design system + pick card redesign + situational badges
    ↓
Phase 4a: Commit MLB LR models from local machine → model_registry/mlb/
Phase 4b: Train NHL models (shadow mode first)
Phase 4c: NBA LR training (only after NHL validates)
Phase 4d: Full game lines ML (separate pipeline — see Phase 5 below)
```

**Note on GitHub sync**: Before any new development, run `git status` and `git fetch` to determine how far local is ahead of remote. Any ML-related work (models, training scripts, config changes) that exists locally but not in GitHub must be committed to `claude/sports-prediction-planning-MxoBU` before new work begins.

---

---

### Phase 0b: Codebase Scrub

The repo has accumulated multiple versions of the same scripts (`v2_auto_grade_yesterday_v3_RELIABLE.py`, `generate_predictions_daily_V5.py`, etc.) plus dead code, old experiments, and inconsistent naming. This makes it hard to know which script is authoritative.

**Step 1: Inventory** — run `find . -name "*.py" | sort > /tmp/file_inventory.txt` and categorize every file as:
- CANONICAL: the one true active script for each function
- ARCHIVE: an old version superseded by a newer one
- DEAD: never called by orchestrator or any other script

**Step 2: Standardize naming conventions**
- Prediction scripts: `generate_predictions_{sport}.py` (one per sport, no version suffix)
- Grading scripts: `auto_grade_{sport}.py` (one per sport)
- Config: `{sport}_config.py` (already correct)
- Data fetchers: `fetch_{sport}_{data_type}.py`

**Step 3: Archive or delete**
- Move archived scripts to `{sport}/archive/` with a `README.md` inside explaining what each was and why it was superseded
- Delete truly dead files (nothing imports or calls them, no data they created is used)

**Step 4: Update CLAUDE.md** to list the one canonical script for each function per sport. This becomes the source of truth.

**Goal**: Open the `scripts/` directory and immediately know which file to edit. No more `_v2_v3_RELIABLE_FIXED` suffixes.

---

### Phase 0c: Confidence Inflation Filter

**The problem**: When the model says 78% confidence, does it actually hit 78% of the time? Probably not — the probability caps and tier assignments may be poorly calibrated, especially in the extreme buckets.

**Query to run** (both databases):
```sql
-- NHL version
SELECT
  ROUND(probability / 0.1) * 0.1 AS prob_bucket,
  COUNT(*) AS n,
  1.0 * SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) / COUNT(*) AS actual_hit_rate
FROM predictions p
JOIN prediction_outcomes o ON p.id = o.prediction_id
WHERE p.probability IS NOT NULL
GROUP BY prob_bucket
HAVING n >= 30
ORDER BY prob_bucket;
```

**What to do with the results**:
- If a probability bucket hits < its stated probability by > 5 percentage points → those picks are overconfident
- Most likely to see: model says 70-80% probability, actual hit rate is 60-65% → those high confidence picks are inflated
- **Fix (no model retraining required)**: Add a `calibration_discount` column to the display — show the "adjusted confidence" (the empirical hit rate for that bucket) alongside the raw model probability
- **Filter option**: Only surface picks where `empirical_hit_rate_for_this_bucket > 0.58` (above the PrizePicks break-even) — suppresses picks that look confident but historically don't perform

**Where to apply this**:
- `shared/edge_calculator.py`: Add `get_calibrated_probability(raw_prob, sport)` that looks up the empirical hit rate for that bucket from a precomputed JSON file
- `shared/smart_pick_selector.py`: Use calibrated probability when computing edge, not raw model probability
- `api/picks.py`: Return both `raw_probability` and `calibrated_probability` so the app can show both
- Precompute the calibration table: `python shared/calibration_audit.py --export-table` → saves `data/calibration_tables/{sport}.json`

---

### Phase 5: Full Game Lines ML (Separate Pipeline)

This is a genuinely new capability — separate from player props. The models, features, and grading logic are all different.

**Scope**:
- **NHL**: Moneyline (home win / away win) + puck line (-1.5/+1.5 goals) + game total (O/U 5.5 goals)
- **NBA**: Moneyline + point spread + game total (O/U)
- **MLB**: Moneyline + run line (-1.5/+1.5) + game total (O/U)

**Feature engineering (team-level, not player-level)**:
- NHL: team CF% (Corsi), PDO, power play %, penalty kill %, goalie SV%, recent form (last 5-10 games)
- NBA: offensive rating, defensive rating, pace, net rating, home/away splits, rest days
- MLB: starting pitcher ERA/FIP/xFIP/WHIP/K%, opposing lineup OPS vs starter hand, ballpark factor, weather

**Data sources already available**:
- `shared/fetch_game_odds.py` fetches moneylines and totals from ESPN API (already working for game lines)
- NHL: `api-web.nhle.com` provides team stats and goalie data (already integrated in grading)
- NBA: ESPN box scores (already integrated)
- MLB: will need Baseball Reference or Stats API for pitcher stats

**Architecture**:
- Store game-level predictions in separate tables: `game_predictions` and `game_outcomes` (don't mix with player props)
- One model per market per sport: `nhl_moneyline`, `nhl_puck_line`, `nhl_total`, etc. (9 models total)
- Model type: Logistic Regression (moneyline/total → binary), ordinal regression or LR with spread bucket for lines
- **Do not start this until** player prop pipeline is stable and calibrated

**Suggested project structure**:
```
shared/
  game_lines/
    feature_engineering.py   # team-level feature extraction per sport
    grading.py               # compare prediction vs actual game result
    model_training.py        # train game line models
    predictor.py             # generate game line picks
```

**This is Phase 5 because**: Building it right takes longer than it looks (game result data needs its own grading pipeline, team features need their own data fetcher, etc.). Don't rush this. Get the player prop system clean and validated first.

---

## Verification Steps

1. **Calibration audit**: Run `python shared/calibration_audit.py --sport nba` → reliability diagram should show dots near diagonal, real edge > 3% above always-UNDER baseline
2. **Odds integration**: Run `python shared/fetch_game_odds.py --sport nba --date 2026-04-15` → should return player prop lines with implied probabilities
3. **API**: `curl http://localhost:8000/api/picks/smart?sport=mlb` → should return MLB picks with `implied_probability`, `true_ev`, `tier_hit_rate`
4. **Mobile app**: Launch Expo dev server, open app → verify pick cards show model % vs implied %, tier badges correct color, MLB picks appear in ALL tab
5. **End-to-end**: For a T1-ELITE pick, verify: model_prob − implied_prob > 0.19 (≥19% edge for ELITE tier), true_ev > 0 (positive expected value)

---

## Notes on Cheaper Odds API Alternatives

For game-level lines (moneyline, spread, total):
- ESPN API is free and already integrated → use it

For player prop lines from traditional sportsbooks:
- No free reliable source exists for player props
- The Odds API Developer tier ($49/month) is the pragmatic choice
- Start with the free tier (500 req/month) to validate integration, then upgrade
- PrizePicks API (free, already working) covers the DFS prop market and is sufficient for the initial launch
- Can launch with PrizePicks-only and add sportsbook lines as a v2 upgrade

---

## Addendum: MLB Trained Models, NHL ML Status, NBA Model Architecture

### MLB Trained Models (Local, Not in GitHub)

MLB Linear Regression models exist on the local machine with strong backtested results on 2024-25 data (n_test=14,764). Key findings:

**Strong models (ship these):**
- Hits O0.5: 72.2% accuracy, **+14.8% vs naive** → genuine edge, xwOBA dominates (53.5%)
- Strikeouts K4.5: 68.1% accuracy, **+16.9% vs naive** → excellent pitcher model
- Strikeouts K3.5: 75.6%, +7.1% vs naive; K5.5: 71.6%, +8.6% vs naive
- Walks W1.5: 61.4%, **+11.3% vs naive** → real edge

**Weak models (use with caution):**
- Hits O1.5: 81.4% but only +0.6% vs naive → almost all naive-baseline effect
- Total Bases O2.5/O3.5: <3.1% vs naive → marginal
- Outs Recorded: <6% vs naive → thin edge

**Negative model (do NOT ship):**
- Home Runs: -30.1% improvement over baseline (model hurts you here) → exclude from picks

**Action items:**
1. Commit MLB model files to `ml_training/model_registry/mlb/` using existing `model_manager.py`
2. Add `model_quality_tier` metadata to each model: "STRONG" (+8% vs naive), "MODERATE" (+3-8%), "WEAK" (<3%), "NEGATIVE" (worse than naive)
3. Only surface STRONG/MODERATE models in the app
4. Track live 2026 accuracy vs backtested 2024-25 accuracy daily (they are currently doing this — add this comparison to the PerformanceScreen)

### NHL ML Status

Current state: `MODEL_TYPE = "statistical_only"` in `nhl/scripts/v2_config.py`. ML infrastructure exists (`HybridPredictionEngine` supports 60/40 ensemble) but no `.joblib` files exist. NHL needs to go through the same training process.

**To enable NHL ML:**
1. Run `ml_training/train_models.py` for NHL props (points_0.5, shots_2.5 — most data volume)
2. Shadow mode: run alongside statistical model for 2 weeks, compare
3. Only flip `MODEL_TYPE = "hybrid"` in config after shadow validation
4. This is gated on Phase 0 calibration audit passing

### NBA Model Architecture: Statistical vs. Linear Regression

Recommendation: **Yes, switch NBA to logistic regression** (LR for classification, not linear regression). Rationale:
- The previous NBA ML catastrophe (84% → 47%) strongly suggests the prior model overfit (likely XGBoost/gradient boosting with too many features and too little data)
- LR is far less prone to overfitting on 30,000-sample datasets
- LR is interpretable: you can see which features drive each prediction
- LR with proper regularization (L2/Ridge) handles correlated features (stats are correlated with each other)
- LR calibration is well-understood and reliable
- Sklearn `LogisticRegression(C=0.1, max_iter=1000)` as a starting point
- Features: the canonical `f_*` columns already extracted per canonical_schema.py

**NBA LR training plan:**
1. Use the same `train_models.py` pipeline (it already supports LogisticRegression)
2. Set `MLConfig.model_types = ['logistic_regression']` only (not XGBoost/RF) initially
3. Shadow mode: run LR alongside statistical for 2 weeks
4. Guard: if accuracy drops >5% vs statistical baseline, auto-revert

---

## The Math/Confidence Framework ("Warm and Fuzzy" Checklist)

The concern about overstating results is 100% legitimate. Here is the complete framework for determining when a model is trustworthy:

### The Three-Check System

A model is only "validated" when ALL three pass:

**Check 1: Beat the Naive Baseline (statistical validity)**
- Calculate naive baseline accuracy = accuracy if you always predict the majority class (usually UNDER)
- Real edge = our accuracy − naive baseline accuracy
- Threshold: real_edge > 3% on n > 1,000 test samples
- Example: NBA 84.2% UNDER accuracy looks great but if always-UNDER hits 80%, real edge is only 4.2%

**Check 2: Temporal Validation (no data leakage)**
- Train on season N (e.g., 2024-25), test on season N+1 (2025-26) with ZERO data from N+1 in training
- If live 2026 results track within 5 percentage points of backtested 2024-25 results → model generalizes
- If live results collapse vs backtest → overfitting or regime change
- The MLB team is already doing this comparison daily — this is exactly right

**Check 3: Profit Simulation (financial validation)**
- Simulate flat $100 bets on all picks for a full season at -110
- Break-even: 52.38% hit rate
- Any model with >55% real hit rate at sufficient volume generates positive ROI
- Kelly criterion check: `kelly = (p × 1.909 − 1) / 0.909` where p = hit rate. Positive kelly = mathematical edge.
- `backtest_game_strategies.py` already implements this — run it.

### Red Flags (model is not trustworthy)
- High accuracy that disappears when compared to always-UNDER baseline
- Model trained and tested on same season (data leakage)
- Accuracy that varies wildly week-to-week (unstable model)
- Feature importances dominated by one feature >70% (overfit to one signal)
- Live results >10% lower than backtest

### Green Flags (model can be trusted)
- Real edge (vs naive) consistently >5% across multiple prop types
- Live season results within 5% of backtest
- Feature importances spread across 3+ meaningful features
- Positive Kelly fraction on most picks
- Calibrated probabilities: when model says 65%, it actually hits ~65%

### For MLB specifically (from the backtested results provided)
- Hits O0.5 (xwOBA model): ✓ Strong real edge (+14.8%), ✓ xwOBA + xwOBA_14d coherent features → **VALIDATE against 2026 live data first, then ship**
- Strikeouts: ✓ Real edges across multiple lines, pitcher features (whiff rate, velocity) make intuitive sense → **VALIDATE then ship**
- Home Runs: ✗ Negative improvement → **do not ship**
- Everything else: run Three-Check system before shipping

### Adding "vs Naive Baseline" to the App

This is the single most important display change for building user trust. Every pick in the app should show:
```
Model: 72%  |  Implied: 54%  |  vs Naive: +14.8%
```

The "vs Naive" number answers "is this model actually adding value or just predicting what everyone predicts?" Users who see +14.8% vs naive will trust the system more than if they just see 72%.

Add `naive_baseline_rate` and `vs_naive_edge` to:
- `api/picks.py` response schema
- `mobile/src/screens/SmartPicksScreen.tsx` pick cards
- `mobile/src/screens/PerformanceScreen.tsx` tier breakdown table

---

---

## ADDENDUM: Ground-Truth Corrections After Local Codebase Inspection
**Written: 2026-04-15 — supersedes any conflicting claims in the original document above**

The original PEGASUS.md was written without access to local files, `mlb_feature_store/`, or the model registry (all gitignored). This addendum corrects three significant errors and maps the real system architecture.

---

### Correction 1: NHL Models DO Exist (PEGASUS.md was wrong)

**Original claim**: "no `.joblib` files exist" for NHL. ML infrastructure built but never activated.

**Reality**: `ml_training/model_registry/nhl/` contains trained LogisticRegression models across **13 prop/line combinations**:
- `points_0.5`, `points_1.5`, `points_2.5`, `points_3.5`
- `shots_0.5` through `shots_7.5` (8 lines)
- `fantasy_points_99.5`

Latest version: `v20260325_003` (March 25, 2026). These are `.joblib` files with accompanying `metadata.json` (training_samples: ~11,751 per prop) and `scaler.joblib`.

**Status today**: Models exist but are **intentionally deactivated**. `nhl/scripts/v2_config.py` reads:
```python
LEARNING_MODE = False
MODEL_TYPE = "statistical_only"  # No ML until Week 10
```

The HybridPredictionEngine code supports a 60/40 ML/stat blend but it has not been switched on. This was a deliberate decision — models were trained as a test but not activated in production. The config comment "Week 10" suggests they were held back pending a data-volume gate that may now be met.

**What this means for PEGASUS Phase 4**: We do not need to train NHL models from scratch. We need to:
1. Audit the existing v20260325_003 models against the Three-Check System
2. Confirm the 60/40 blend logic in `HybridPredictionEngine` is correct
3. Run shadow mode before switching `MODEL_TYPE = "hybrid"`

---

### Correction 2: NBA Models Also Exist — But Were Deliberately Reverted

**Original claim**: "NBA ML retrain attempt (Mar 15) caused catastrophic collapse: 84% → 47% UNDER accuracy" — accurate. But the framing implies no models exist.

**Reality**: `ml_training/model_registry/nba/` contains **471 model directories** across all prop/line combos (assists, blocked_shots, fantasy, points, rebounds, steals, threes, turnovers — each at 10-20 line thresholds). Latest version in all directories: `v20260315_001` (the disastrous March 15 retrain).

**Status today**: `nba/scripts/nba_config.py`:
```python
LEARNING_MODE = True
MODEL_TYPE = "statistical_only"  # No ML until Week 8+
```

The system was deliberately reverted to pure statistical after the March 15 collapse. The models sitting in the registry are the bad ones — do not activate them. The recommendation for LogisticRegression re-training in the original addendum stands and is correct.

---

### Correction 3: The MLB ML System — Two Layers, One Gap

**Original claim**: "MLB pipelines, database, feature extractors, and grading scripts are fully built" and "MLB LR models exist locally — commit to `ml_training/model_registry/mlb/`."

**Reality**: There are two distinct MLB ML layers that the original document conflates:

#### Layer A: `mlb_feature_store/` (XGBoost regression — LIVE, orchestrator-wired)

This is the **production MLB ML system**, built April 13, 2026. It is:
- Self-contained in `mlb_feature_store/` with its own DuckDB (`data/mlb.duckdb`)
- Trained on 2024-2025 Statcast data (~94k hitter rows, ~9.9k starter pitcher rows)
- Uses **XGBoost regression**, not LR — predicts raw expected value (e.g., "1.3 hits") then converts to P(OVER line) via Poisson CDF
- **6 trained models**: `hits`, `total_bases`, `home_runs`, `strikeouts`, `walks`, `outs_recorded`
- Accuracy on 2026 test set: hits 72.8%, total_bases 74.5%, strikeouts 71.0%, outs_recorded 68.7%, walks 61.1%
- Home runs model is worse than naive baseline — **excluded from picks** (this is documented and enforced)
- **Already wired into `orchestrator.py`** via `_run_feature_store_cmd()`. Runs daily at 10:20 AM, non-fatal
- Predictions written to DuckDB `ml_predictions` table and surfaced in:
  - Cloud dashboard MLB tab (`_render_mlb_ml_comparison()` widget)
  - TUI terminal `ML Exp` and `ML +/-` columns via `tui/ml_bridge.py`

**Feature importances (as-trained, no FanGraphs):**
| Prop | Top feature | Share |
|---|---|---|
| hits | xwoba | 53.5% |
| total_bases | xwoba | 53.9% |
| strikeouts | whiff_rate | 35.1% |
| walks | xwoba_allowed | 38.6% |

Note: FanGraphs (wrc+, wpa, opp_strength) is permanently blocked (403). Models use Statcast-only features. This is documented and accepted.

#### Layer B: `mlb/scripts/` (statistical-only player props — the main pick pipeline)

This is the pipeline that flows to **users via Supabase and the mobile app**:
```
mlb/scripts/generate_predictions_daily.py
  → shared/smart_pick_selector.py
  → sync/supabase_sync.py
  → Supabase daily_props table
  → Mobile app FreePicks
```

`mlb/scripts/mlb_config.py` shows `LEARNING_MODE = True` — purely statistical. The ProductionPredictor ML blend is not enabled.

#### THE GAP (critical for PEGASUS work):

**mlb_feature_store ML predictions are NOT flowing into the user-facing pick pipeline.** They exist in DuckDB and are visible in the dashboard/TUI, but the mobile app and Supabase see only the statistical predictions.

Closing this gap is a concrete PEGASUS deliverable: wire `mlb_feature_store` ML predictions into `mlb/scripts/generate_predictions_daily.py` as a blend, then through `smart_pick_selector.py` → Supabase. This is analogous to the 60/40 blend that NHL's `HybridPredictionEngine` supports but hasn't activated.

---

### The Full ML Architecture Map (as of 2026-04-15)

| Sport | Models exist? | Model type | In production? | Gap |
|---|---|---|---|---|
| NHL | YES — 13 prop/line combos, v20260325_003 | LogisticRegression (.joblib) | NO — MODEL_TYPE="statistical_only" | Audit models, run shadow mode, then flip config |
| NBA | YES — 471 dirs, v20260315_001 | LogisticRegression (.joblib) | NO — REVERTED (catastrophic collapse) | Retrain with LR only; shadow mode; hard accuracy gate |
| MLB (feature store) | YES — 6 XGBoost .pkl models | XGBoost regression + Poisson CDF | PARTIAL — dashboard+TUI only | Wire into main pick pipeline + Supabase sync |
| MLB (stat-only) | N/A | Poisson/statistical | YES — LEARNING_MODE=True | This IS production; needs MLB blend layer to consume XGBoost output |

---

### Revised Phase 4 Execution Plan (replaces original Phase 4 section)

Given the above, the ML activation sequence is:

**4a — MLB: Close the gap between mlb_feature_store and the pick pipeline**
- Create a blend layer in `mlb/scripts/generate_predictions_daily.py` that reads `ml_predictions` from DuckDB and merges with statistical probabilities (e.g., 60/40 or best-model-wins)
- Only blend for: hits, total_bases, strikeouts, walks, outs_recorded (exclude home_runs)
- Validate on 2026 live results before surfacing in mobile app
- Set `LEARNING_MODE = False` in `mlb_config.py` only after validation

**4b — NHL: Activate existing models via shadow mode**
- Models already exist (v20260325_003). No training needed to start.
- Read existing metadata to confirm accuracy before enabling
- Set `MODEL_TYPE = "hybrid"` in `v2_config.py` with 60/40 blend (infrastructure already supports this)
- Two-week shadow mode: log both stat and hybrid predictions, surface stat in app, compare accuracy daily
- Full cutover only if hybrid outperforms stat by >2pp on last 30 days

**4c — NBA: Retrain with LogisticRegression, strict gate**
- Delete or archive all v20260315_001 models (the bad ones) from registry
- Retrain using `train_models.py` with `model_types=['logistic_regression']` only
- Hard accuracy gate: new LR must beat stat model by >2pp AND not regress >5pp vs prior stat baseline
- Shadow mode mandatory before any production activation

**4d — Full Game Lines (Phase 5 from original doc)**
- Separate pipeline, separate tables — do not start until props are stable
- See original Phase 5 section — that content stands as written

---

### Notes on PEGASUS Scope vs. mlb_feature_store Isolation

`mlb_feature_store/` has its own `CLAUDE.md` that says "Do not cross-import with nhl/, nba/, or shared/." This isolation is **intentional and should be preserved**. The gap closure in Phase 4a should happen at the orchestrator/pipeline level — not by having `mlb_feature_store` import from `shared/` or vice versa.

Pattern: `generate_predictions_daily.py` calls a thin reader function that queries DuckDB for today's `ml_predictions` rows and returns a DataFrame. All the blending logic lives in the MLB script, not in `mlb_feature_store`. This keeps the feature store self-contained while feeding its outputs into the main pipeline.

---

*Addendum written after direct inspection of local codebase on 2026-04-15. Verified by reading: `mlb_feature_store/ARCHITECTURE.md`, `mlb_feature_store/CLAUDE.md`, `mlb_feature_store/HANDOFF.md`, `mlb_feature_store/ml/models/metadata.json`, `ml_training/model_registry/nhl/` directory tree, `ml_training/model_registry/nba/` directory tree, `nhl/scripts/v2_config.py`, `nba/scripts/nba_config.py`, `mlb/scripts/mlb_config.py`, `orchestrator.py` feature_store hooks.*