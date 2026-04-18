# Session Handoff — Apr 18, 2026: Display Architecture + MLB ML Audit

## Resume Prompt (paste this after /clear)

```
We just completed a major dashboard architecture session. Key commits:
- 60d0fc15: Dashboard Supabase gate removed, all reads migrated to Turso/SQLite, pick quality framework added

Context files to read first:
- docs/sessions/2026-04-18-display-architecture-mlb-ml.md  ← this file
- C:\Users\thoma\.claude\projects\C--Users-thoma-SportsPredictor\memory\MEMORY.md

Session goals we left mid-stream:
1. Verify dashboard renders correctly (picks tab, quality columns, performance tab)
2. Diagnose WHY MLB accuracy matches naive baseline exactly — we have rich features (pitcher ERA, park factors, platoon splits, weather), so it's NOT a features gap. Something in the training pipeline is wrong.
3. Implement MLB matchup-aware path forward
4. Answer: why is NBA so much more predictable than MLB?
```

---

## What We Built This Session

### Dashboard Architecture Overhaul (commit 60d0fc15)

**Root cause diagnosed and fixed:**
- Line 1666 in `cloud_dashboard.py` had `sb = get_supabase(); if sb is None: return` — this BLOCKED the entire dashboard from rendering if Supabase was unavailable.
- All tabs were silently dead. No picks, no performance, no system tab.

**Full source migration map:**

| Function | Was | Now |
|---|---|---|
| Main gate | Supabase (blocked everything) | **Removed** |
| `fetch_picks()` | Turso (already) | Turso + quality columns added |
| `fetch_all_lines_for_players()` | Supabase `daily_props` | Turso `predictions` |
| `fetch_recent_results()` | Supabase `daily_props` | Local SQLite JOIN |
| `fetch_performance()` | Supabase `model_performance` | Local SQLite computed |
| MLB/NHL local-first fallbacks | Supabase (unreachable locally) | Unchanged (local-first was already working) |

**New pick quality framework (5 values per pick):**

| Column | Source | Meaning |
|---|---|---|
| Model prob | Turso `predictions.probability` | Our statistical/ML confidence |
| PP BE% | `break_even[odds_type]` | Min probability needed to profit |
| Edge | `model_prob − break_even` | Profit margin |
| Naive% | Turso `prediction_outcomes` historical UNDER rate for this prop/line | What always-same-direction would hit |
| vs Naive | `model_prob − naive_rate` | Does our model add value over a coin-flip baseline? |

**New module-level helpers:**
- `_turso_request(sport_key, sql, args)` — synchronous Turso HTTP query
- `_turso_cell(cell)` — unwrap Turso response cell
- `fetch_under_baselines(sport)` — @st.cache_data(ttl=1800), queries Turso `prediction_outcomes` for historical UNDER rates

**Bug fixed during testing:** `game_time` column does not exist in Turso predictions table (was never synced). Removed from SQL, `game_time=None` hardcoded for now.

---

## Paolo Banchero Row-by-Row Breakdown (April 17, 2026)

These are real picks from yesterday's smart picks to illustrate the full pipeline.

### How predictions are generated

1. **VPS runs orchestrator** each morning → calls `generate_predictions_daily.py`
2. **For each player on today's PP board**, fetch their `player_game_logs` from local SQLite
3. **Compute feature vector**: success rates at each line (season, L20, L10, L5, L3), seasonal averages, home/away splits, consistency score, avg minutes
4. **Statistical model** (`statistical_v1`) blends these into a probability: "what fraction of this player's recent games exceeded this line?"
5. **SmartPickSelector** applies edge filter, odds_type break-even, suppression rules → marks `is_smart_pick=1`
6. **VPS runs `turso_sync`** → syncs predictions + smart picks to Turso
7. **Dashboard reads Turso** → applies quality framework

### Row 1: Paolo Banchero OVER assists 4.5 (standard, -110)

**Raw data:**
- `probability` in DB = 0.6470 (raw OVER probability)
- prediction = OVER → confidence = 64.7%

**Features:**
- `f_season_success_rate` = 57.6% (all season, 57.6% of games had >4.5 assists)
- `f_l20_success_rate` = 75.0% (last 20: 15/20 games over)
- `f_l10_success_rate` = 60.0%
- `f_l5_success_rate` = 60.0%
- `f_season_avg` = 5.37, `f_l10_avg` = 5.60, `f_l5_avg` = 6.20
- Trending UP — recent 5-game average (6.20) well above season average (5.37)

**Quality framework:**
| Metric | Value |
|---|---|
| Model confidence | 64.7% OVER |
| PP break-even | 52.4% |
| Edge | +12.3% |
| Naive (always-OVER 4.5 assists) | 59.2% historically |
| vs Naive | +5.5% |

**Verdict:** Legitimate edge. Recent trend is accelerating. We beat the naive baseline by 5.5pp. Strong pick.

---

### Row 2: Paolo Banchero UNDER pra 36.0 (standard)

**Raw data:**
- `probability` in DB = 0.1492 (14.9% OVER → 85.1% UNDER confidence)
- prediction = UNDER

**Features:**
- `f_season_success_rate` = 0.0 — literally 0 times all season went OVER 36.0 pra
- `f_l20_success_rate` = 0.0 — 0/20 last 20 games
- `f_l10_success_rate` = 0.0 — 0/10 last 10 games
- `f_l5_success_rate` = 0.0
- `f_season_avg` = 36.44 (barely above the line), `f_l10_avg` = 31.60, `f_l5_avg` = 34.80
- Recent form clearly trending DOWN from season average

**Quality framework:**
| Metric | Value |
|---|---|
| Model confidence | 85.1% UNDER |
| PP break-even | 52.4% |
| Edge | +32.7% |
| Naive (always-UNDER pra 36.0) | 54.2% historically |
| vs Naive | +30.9% |

**Verdict:** Maximum model conviction. The line (36.0) is set where PRA almost never goes that high for this player. The model correctly reads 0/20 historical hits as near-certainty UNDER. Strong pick AND adds massive value vs naive.

---

### Row 3: Paolo Banchero UNDER assists 5.5 (standard) — THE BAD PICK

**Raw data:**
- `probability` in DB = 0.6195 (61.9% OVER → only 38.0% UNDER confidence)
- prediction = UNDER

**Features:**
- `f_l20_success_rate` = 55.0% (more often OVER 5.5 than UNDER recently)
- `f_l5_avg` = 6.20 — recent form clearly above 5.5 line

**Quality framework:**
| Metric | Value |
|---|---|
| Model confidence | 38.0% UNDER |
| PP break-even | 52.4% |
| Edge | **−14.4% (LOSING BET)** |
| Naive (always-UNDER 5.5 assists) | 40.5% |
| vs Naive | −2.5% |

**Verdict:** This should NOT be a smart pick. Edge is −14.4% — below break-even. The model actually thinks OVER is more likely. This is the tier inconsistency: `ai_tier=T4-LEAN` was stamped during pp-sync but edge is negative. The quality framework exposes this immediately — any pick with negative edge or negative vs_naive should be filtered out.

**This reveals a pipeline bug:** SmartPickSelector is letting through picks with negative edge. The `vs Naive` column is the stamp-of-approval — if it's negative for an UNDER pick in a high-OVER-rate environment, it shouldn't surface.

---

## MLB ML Audit — Why We Match the Naive Baseline

### The finding

**21,334 graded MLB picks, 66.5% overall accuracy.** But:

| Prop/Line | Our acc | Naive always-same-dir | We add |
|---|---|---|---|
| rbis UNDER 1.5 | 90% | 90% | **0%** |
| hits UNDER 1.5 | 81% | 81% | **0%** |
| home_runs UNDER 0.5 | 90% | 90% | **0%** |
| batter_strikeouts UNDER 1.5 | 78% | 77% | +1% |
| earned_runs OVER 0.5 | 82% | 82% | **0%** |
| hits OVER 0.5 | 60% | 60% | **0%** |

### MLB ALREADY HAS the right features

This was confirmed. MLB `features_json` includes:

**Batter features:**
- `f_vs_rhp_avg`, `f_vs_lhp_avg`, `f_platoon_advantage` — platoon splits
- `f_l5_hits_avg`, `f_l10_hits_avg`, `f_streak` — recent form
- `ctx_park_hr_factor`, `ctx_park_hits_factor`, `ctx_park_k_factor` — park factors
- `ctx_temperature`, `ctx_wind_speed`, `ctx_wind_direction_encoded` — weather
- `ctx_game_total`, `ctx_implied_home_runs`, `ctx_implied_away_runs` — Vegas lines
- `opp_pitcher_era`, `opp_pitcher_whip`, `opp_pitcher_k9`, `opp_pitcher_l3_k_avg` — pitcher matchup
- `opp_pitcher_difficulty` — composite pitcher strength score

**So WHY do we match the naive baseline?**

**The real diagnosis (to verify):**

1. **Dominant signal overwhelms context**: For "easy" lines (rbis > 1.5 → 90% UNDER), the historical success rate IS the naive baseline. The ML model learns "historical_rate ≈ prediction" because it's the dominant feature. Context features (park, weather, pitcher) have smaller signal than "this player has gone UNDER 90% of all time."

2. **Training data concentration**: Most picks cluster at lines where the naive rate is extreme (70-90%). The model trains mostly on these easy cases where context doesn't matter much, so it never learns to use context on borderline cases.

3. **Success rate features ARE the naive baseline**: `f_l10_hits_rate`, `f_l5_hits_rate` etc. compute "how often did this player exceed this line recently" — which, averaged across all players for a prop/line, IS the naive baseline. The model learns these features = reliable → outputs ≈ naive baseline.

4. **No cross-player normalization**: If player A has 80% UNDER rate and player B has 40% UNDER rate for the same line, the model sees two different success rates. But the naive baseline (averaged) is ~60%. The model's marginal value comes from discriminating between these players. But if SmartPickSelector only shows high-confidence picks, it's selecting the 80% cases, which the naive baseline also gets right.

### Questions to answer next session

1. **Why is NBA so much more predictable than MLB?**
   - NBA: 80%+ hit rate on UNDER picks. MLB: 66% overall (mostly riding naive baseline).
   - Hypothesis: NBA stats are more stable. A player's points/assists are heavily constrained by role, playing time, team system. MLB outcomes are much more stochastic — a single AB result (hit/no-hit) has massive variance. NBA you're predicting a sum of 35+ possessions; MLB you're predicting 3-5 discrete events.
   - Also: NBA player roles are very sticky (starters/bench clear). MLB batters face different pitchers every game.
   - Needs verification with data.

2. **Is the naive match a training artifact or a fundamental limit?**
   - If we retrain excluding success-rate features and only use context features, does performance drop (proving historical rate is needed) or stay the same (proving context adds nothing)?
   - This experiment would isolate feature contributions.

3. **Does the model add value on BORDERLINE cases?**
   - Filter to picks where naive rate is 45-55% (genuinely uncertain). Does our model outperform 50% coin flip on those?

---

## TO DISCUSS Next Session

### MLB Path Forward

**Option A — Feature importance audit (quick, 1 session)**
- Train with / without success-rate features
- Measure: does context (pitcher, park, weather) add >3% accuracy on borderline picks?
- Expected finding: success rate features dominate; context adds ~2-5% on borderline cases

**Option B — Reframe the prediction target (medium, 2-3 sessions)**
- Current: predict "will player exceed historical rate?"
- New: predict "given today's specific context, what is the expected deviation from historical rate?"
- This makes context the signal, not the noise

**Option C — Segment the model (medium)**
- Train separate model for "easy" picks (>70% naive rate) vs "borderline" picks (45-55% naive)
- Only surface borderline picks where model adds ≥5% vs naive
- Easy picks handled by naive rule alone (they don't need ML)

**Option D — The stamp-of-approval filter (immediate, 1 hour)**
- Implement in `smart_pick_selector.py`: skip any pick where `model_prob - naive_rate < +5%`
- This would zero out most current MLB smart picks
- Honest, immediate improvement to displayed quality
- Dashboard `vs Naive` column already shows this data — just need to filter

**Recommended path: D → A → B**
1. Implement the filter immediately (D) so we stop surfacing picks that don't add value
2. Run feature importance audit (A) to understand the data
3. Reframe prediction target (B) if context features prove meaningful

---

## Remaining TODO Items (updated Apr 18)

### Completed this session ✅
- [x] Dashboard Supabase gate removed — dashboard now renders without Supabase
- [x] `fetch_picks` → Turso primary (already was), fixed game_time column bug
- [x] `fetch_all_lines_for_players` → Turso (was Supabase daily_props)
- [x] `fetch_recent_results` → local SQLite JOIN (was Supabase)
- [x] `fetch_performance` → local SQLite computed accuracy (was Supabase model_performance table)
- [x] Pick quality framework: PP BE%, Naive%, vs Naive, Src columns in All Picks display
- [x] `fetch_under_baselines` — new function, historical UNDER rate per prop/line from Turso
- [x] MLB ML audit — 21k picks graded, diagnosed naive baseline match, confirmed features are NOT the gap

### Active / Next
- [ ] **Verify dashboard picks actually render** — reload at localhost:8502, check NBA/NHL tabs show picks with quality columns
- [ ] **Diagnose Paolo UNDER assists 5.5 bug** — SmartPickSelector is passing through picks with negative edge. Check edge filter in `shared/smart_pick_selector.py`
- [ ] **Implement vs_naive filter in SmartPickSelector** — skip picks where model adds <+3% vs naive baseline (stamps out rides)
- [ ] **MLB feature importance audit** — retrain with context-only features, measure borderline case accuracy
- [ ] **NBA vs MLB predictability analysis** — quantify why NBA is so much more stable (role stability, sample size per game, etc.)

### VPS Cleanup (6 items still pending from migration)
- [ ] NBA Turso uncapped — verify NBA Turso rows don't have capped probabilities
- [ ] Golf column fix
- [ ] MLB feature store
- [ ] NHL hits guard
- [ ] pp-sync local job
- [ ] Grok key

### PEGASUS
- [ ] Step 11: Game Lines ML (gated until Oct 2026)

---

## Key Technical Details to Carry Forward

### Turso picks query (working, no game_time)
```sql
SELECT player_name, team, opponent, prop_type, line, odds_type,
       prediction, probability, ai_tier, model_version
FROM predictions
WHERE game_date = ? AND is_smart_pick = 1
```

### Always-UNDER baseline query
```sql
SELECT prop_type, line,
  SUM(CASE WHEN (outcome='HIT' AND prediction='UNDER') OR
           (outcome='MISS' AND prediction='OVER') THEN 1.0 ELSE 0 END) /
  NULLIF(CAST(COUNT(*) AS REAL), 0) AS under_rate,
  COUNT(*) AS n
FROM prediction_outcomes
WHERE outcome IN ('HIT','MISS')
GROUP BY prop_type, line
```

### Probability convention (NBA/MLB/NHL)
- `predictions.probability` = **raw OVER probability** always
- For OVER picks: `confidence = probability`
- For UNDER picks: `confidence = 1 - probability`
- Dashboard `fetch_picks` already handles this correctly

### MLB features confirmed present
Batter: platoon splits, recent form, park factors, weather, Vegas implied runs, opp pitcher ERA/WHIP/K9/difficulty
Pitcher: K/9, BB/9, WHIP, H/9, ER/9, L3/L5 averages, park factors, game total
→ Features are NOT the gap. The issue is how the model uses them.
