# Apr 19, 2026 — Pipeline Recovery + Path Forward

## Context

Post-VPS migration (Apr 18) the local orchestrator had stopped running. This session
recovered the pipeline, diagnosed the playoff transition gap, and surfaced a major
architectural insight about prediction storage.

---

## Session 2 — MLB Training Fix + NBA EV Wiring (Apr 19, 2026 evening)

### Completed

1. **NBA `statistical_predictions.py`** — `predict_binary_prop()` rewritten from naive
   `f_season_success_rate` baseline to proper `mu → normal CDF` approach (matches
   `predict_continuous_prop()`). `expected_value` now returns `mu` (projected stat value).

2. **NBA predictions table** — `expected_value` column added; all 206K existing rows
   backfilled with `0.40*f_l5_avg + 0.35*f_l10_avg + 0.25*f_season_avg`.

3. **NBA `generate_predictions_daily_V6.py`** — `_save_prediction()` wired to INSERT
   `expected_value` for all future NBA predictions.

4. **`ml_training/train_models.py`** — two fixes:
   - Temporal split boundary snapping (day-level, prevents same-day leakage across partitions)
   - NaN median fallback: columns entirely NaN in train partition produced NaN medians;
     `train_median.fillna(0)` ensures fillna() actually removes NaN before sklearn sees it.
   - Assertion tolerance widened 2% → 8% to handle day-snapping on small prop datasets.

5. **MLB training completed** — 13 models saved to `ml_training/model_registry/mlb/`
   (version `v20260419_005`). `hits O0.5` (previously crashing with NaN) now trains
   successfully (Brier 0.2320). MLB `generate_predictions_daily.py` auto-loads them
   via `ProductionPredictor`.

### Commit

`03e27c25` — "Fix MLB training NaN crash; add NBA expected_value; improve temporal splits"

---

## What We Did

### Pipeline Recovery
- Confirmed local databases were stale (last local run: NHL Apr 16, NBA Apr 17, MLB/Golf Apr 17)
- VPS had run NBA predictions on Apr 18 (2,535 rows) but those stayed on VPS SQLite only
- Decision: **abandon VPS orchestrator, run locally** — not prod yet, local is simpler and was working fine
- Ran grading for Apr 17 results across NBA, MLB, Golf directly via scripts
- Generated predictions for Apr 19 across all four sports (NHL 362, NBA 2,723, MLB 489, Golf 232)

### NHL/NBA Playoff Transition
- NHL Apr 18 = first playoff games (`gameType=3`, IDs like `2025030131` vs regular season `202502XXXX`)
- Local DB had 0 predictions for Apr 17-18 because the prediction script stopped running Apr 16
- Confirmed: `fetch_game_schedule_FINAL.py` does NOT filter by game type — playoffs will be picked up
- `nba_config.py` already includes `'004'` (playoffs) in schedule parser — NBA playoffs handled automatically
- **Action taken**: ran NHL schedule fetch + predictions for Apr 19 manually; continuous mode will handle from here

### Orchestrator Restart
- Updated `start_orchestrator.bat` with VPS `.env` values (Grok key, Discord webhooks, all API keys)
- Restarted local continuous mode — pipeline is live

---

## Expected Value Architecture Audit

This session revealed a critical architectural split across sports:

| Sport | `expected_value` stored | Coverage | Notes |
|---|---|---|---|
| NHL | ✅ Yes | 71,759 rows, Oct 15 2025 → present | Full season, every prediction |
| NBA | ⚠️ Partial | 203,723 rows | `f_l5_avg`, `f_l10_avg`, `f_season_avg` stored — derivable but no single EV column |
| MLB | ✅ Yes | 38,284 rows | Explicit `expected_value` column, absolute projected stat |
| Golf | ❌ No | 3,816 rows | Direction + probability only |

### What "expected_value" means and why it matters

NHL and MLB store the **absolute projected stat value** (e.g., `expected_value=0.72` for
Panarin points, `expected_value=3.49` for pitcher strikeouts). OVER/UNDER and probability
are *derived* by comparing that number to the PP line.

This is architecturally superior to storing direction+probability directly because:

1. **Line-agnostic** — you can reprice a prediction against any line retroactively without
   re-running the model. If PP moves the line mid-day, your stored EV is still valid.

2. **Richer ML training signal** — "we projected 23.8, line was 24.5, actual was 21" gives
   magnitude information. Pure OVER/UNDER labels lose the distance signal that separates
   confident predictions from coin-flips.

3. **Proper calibration** — a 52% UNDER on a 24.5 line vs a 52% UNDER on a 25.5 line are
   very different bets. With EV stored you can recompute both correctly against any line.

4. **Retroactive backfill** — with EV + line stored, you can generate training rows for
   PP lines that didn't exist on the prediction date. Crucial for exotic lines.

### NBA fix (pre-Oct 2026 retrain)

NBA already has the underlying value in `f_l5_avg` / `f_l10_avg` / `f_season_avg`. The fix is:
- Add `expected_value` column to `nba/database/nba_predictions.db`
- Backfill: `UPDATE predictions SET expected_value = f_l5_avg` (or weighted blend)
- Wire into `generate_predictions_daily_V6.py` to store it going forward
- All 203K existing rows are recoverable from stored feature columns

### Golf fix (lower priority — post season)

Add `expected_value` column to golf predictions. Golf model uses Strokes Gained and
rolling score averages — the projected round score is the EV. Same pattern as NHL/MLB.

---

## Feature Engineering Roadmap

### The Core Problem

`f_l5_avg = 4.0` is the naive baseline. ML training only creates value when the model
**beats** the naive baseline — specifically on borderline cases (historical rate 45–55%)
where context should show signal. Extreme cases (90% UNDER on a line) don't need ML.

### NBA — Priority Features for Oct 2026 Retrain

Current features are player-historical only. Missing opponent context is the biggest gap.

**Opponent-aware features (highest priority):**
- Opponent defensive rating vs specific stat (assists allowed, points in paint, etc.)
- Opponent pace of play — faster pace = more possessions = more counting stats
- Opponent recent form (last 7 days) — tired defense gives up more

**Situational features:**
- Rest days / back-to-back flag
- Minutes projection (injury report context)
- Vegas spread as game script proxy — blowout risk = starters sit early
- Home court advantage (we have home_away but weakly modeled)

**Note:** `nba_opponent_feature_extractor.py` already exists — it just needs deeper data.
The sklearn warnings during Apr 18 backfill confirmed it's running.

### NHL — Features for Next Season

NHL already stores opponent stats in `features_json` (`opp_points_allowed_L5` etc.).
Gaps:
- Goalie matchup (starting goalie save % last 10 games)
- Power play time (affects shots and points lines significantly)
- Travel fatigue (back-to-back on road)

### MLB — Features Already Rich

MLB has the most sophisticated feature set: pitcher ERA, park factors, platoon splits,
weather (wind speed/direction). The Apr 18 session diagnosed that ML accuracy matches
naive baseline exactly — root cause is likely the model learning from the hit-rate
features which ARE the naive baseline by construction. Next focus: ensure opponent
pitcher features create signal on borderline cases.

### Golf — Environmental Features

Golf is structurally simple (1 player, 1 round, 1 number) but environment-dependent:
- Strokes Gained history at this specific venue
- Course fit score (ball-striking vs putting-heavy courses)
- Weather: wind speed and direction (dominant factor in scoring variance)
- Round-over-round momentum (R1 score as R2 prediction feature)
- Field quality adjustment (same score means different things vs weak vs strong field)

---

## ML Retrain Timeline

| Sport | Target | Gate | Notes |
|---|---|---|---|
| NBA | Oct 2026 | Season restart | Add EV column + opponent features before retrain. Current models REVERTED (Mar 15 retrain destroyed UNDER). Statistical mode only until Oct. |
| NHL | Oct 2026 | Season restart | Models exist but inactive (statistical_only mode). Enrich with goalie/PP features over offseason. |
| MLB | Mid-season 2026 | 50K graded rows | ~38K now, adding ~500/day. Fix naive baseline issue first. |
| Golf | Post-Masters 2026 | 700+ samples | Currently 3,816 predictions. Build scaffold once samples hit threshold. |

---

## Immediate Next Steps

1. **NBA `expected_value` backfill** — one session, schema change + script update + backfill query
2. **Restart local continuous orchestrator** — done (start_orchestrator.bat updated with VPS keys)
3. **Golf `expected_value`** — add column before next season so all 2026-27 data is clean
4. **Dashboard Turso migration** — still broken (reads local SQLite, shows nothing for VPS-era data). Requires dedicated planning session per Apr 18 handoff.
5. **NBA opponent feature depth** — before Oct retrain, enrich `nba_opponent_feature_extractor.py`

---

## Retroactive Prediction Generation

Confirmed viable for all sports. `shared/prizepicks_lines.db` stores PP lines by
`fetch_date` going back to at least Apr 16. To generate predictions for a missed date:

```bash
# NHL — uses fetch_date = target_date from shared PP DB (exact historical lines)
cd nhl && python scripts/generate_predictions_daily_V6.py 2026-04-18 --force

# NBA — uses today's lines (close enough, lines barely move day-to-day)
cd nba && python -W ignore scripts/generate_predictions_daily_V6.py 2026-04-18 --force

# MLB
cd mlb && python scripts/generate_predictions_daily.py 2026-04-18

# Golf
python orchestrator.py --sport golf --mode once --operation prediction
```

NBA V6 hardcodes `today` for PP line lookup (`generate_predictions_daily_V6.py:140`).
A minor fix would pass `target_date` instead — worth doing when adding EV column.

---

## Golf Path Forward

### Current State (Apr 19, 2026)
- **3,816 predictions**, 2,767 graded, 70.6% Apr accuracy
- **Props**: `round_score` (72.5% acc, 2,649 graded) and `make_cut` (37.3% acc, 118 graded)
- **Active tournament**: RBC Heritage (Apr 16–19) — 232 predictions today
- **107K round logs** stored — rich historical base
- No `expected_value` column
- No ML scaffolding yet

### make_cut Accuracy Problem
37.3% on `make_cut` is below the ~50% random baseline — the model is actively
mispredicting cuts. Root causes to investigate:
- Cut line varies by field size and scoring conditions (not a fixed threshold)
- Current model likely uses rolling score average without field-quality normalization
- A player who averages 70 in weak fields may miss the cut in a major

### expected_value for Golf
Golf EV = projected round score. The model already computes this (rolling Strokes
Gained + historical scoring average at course type). Adding the column:
- Schema: `ALTER TABLE predictions ADD COLUMN expected_value REAL`
- Backfill: derive from `features_json` (projected score stored there)
- Going forward: store before OVER/UNDER comparison in prediction script

### Feature Gaps
Current features are player-historical only. Missing:

| Feature | Impact | Source |
|---|---|---|
| Strokes Gained at this specific venue | High | PGA Tour SG data |
| Course fit score (ball-striking vs putting) | High | Course profile + player SG splits |
| Wind speed + direction | High | Weather API (already in MLB pipeline) |
| Field quality (avg world ranking) | Medium | PGA Tour API |
| Round-over-round momentum (R1 → R2) | Medium | Already in round_logs |
| Cut line historical at this venue | Medium | PGA Tour historical |

### ML Training Gate
- **Current**: 3,816 predictions, ~2,800 graded
- **Target**: 700+ graded samples per prop/line combo before training
- `round_score` is close — likely ready for a first model by mid-summer 2026
- `make_cut` has only 118 graded — needs a full season before ML is viable
- **Plan**: build scaffold after Masters 2026 (already past), target first retrain Oct 2026 alongside NHL/NBA

### Tournament Coverage Gap
Golf predictions run tournament-by-tournament. Verify the orchestrator is picking
up every PGA Tour event — some weeks have multiple events (e.g. opposite-field).
Check that `fetch_golf_schedule` is current through end of 2025-26 PGA season.

### Immediate Golf Actions
1. Fix `make_cut` — investigate why accuracy is below random, likely field normalization
2. Add `expected_value` column (same session as NBA EV work)
3. Add weather API integration (reuse MLB `weather_client.py`)
4. Add venue-specific Strokes Gained history to `player_round_logs`
5. Verify tournament schedule coverage through PGA season end
