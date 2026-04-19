# Next Session Handoff — Apr 19, 2026

## State of the World

All four sports are running locally in continuous mode. Local orchestrator restarted
Apr 19 with updated `start_orchestrator.bat` (VPS keys, Discord webhooks).

VPS orchestrator is NOT running — decision made Apr 19 to run locally until prod is
declared. VPS SQLite is stale (last run Apr 18).

---

## What Was Completed This Session (Apr 19)

### Session 1 — Pipeline Recovery
- Graded Apr 17 results for NBA, MLB, Golf
- Generated Apr 19 predictions: NHL 362, NBA 2,723, MLB 489, Golf 232
- Confirmed NHL/NBA playoff game types handled automatically (gameType=3 / `'004'`)
- Restarted local continuous orchestrator

### Session 2 — ML Fixes
1. **NBA `statistical_predictions.py`** — `predict_binary_prop()` rewritten to use
   `mu → normal CDF` (matches continuous prop approach). `expected_value` now returns mu.

2. **NBA `expected_value` column** — added to predictions table; 206K rows backfilled
   with `0.40*f_l5_avg + 0.35*f_l10_avg + 0.25*f_season_avg`.

3. **NBA `generate_predictions_daily_V6.py`** — `expected_value` wired into INSERT.

4. **`ml_training/train_models.py`** — two fixes:
   - `train_median.fillna(0)` after `X_train.median()` — prevents NaN columns from
     surviving the imputation step and crashing sklearn
   - Split-ratio assertion tolerance widened 2% → 8% for day-boundary snapping

5. **MLB models trained** — 13 models in `ml_training/model_registry/mlb/v20260419_005/`.
   Training completes cleanly including `hits O0.5` (previously crashing on NaN).

6. **MLB blend guard** — `generate_predictions_daily.py` now checks
   `MODEL_TYPE != "statistical_only"` before enabling `ProductionPredictor`. MLB stays
   pure statistical until explicitly flipped in `mlb_config.py`. This was a silent bug:
   models were loading and blending despite `LEARNING_MODE = True` in the config.

### Commits (newest → oldest)
```
6aaf1401  Guard MLB ML blend behind MODEL_TYPE config flag
db21ad1a  Update Apr 19 session doc: MLB fix + NBA EV wiring results
03e27c25  Fix MLB training NaN crash; add NBA expected_value; improve temporal splits
37dc3b7c  Update Apr 19 session doc: add Golf path forward, final health check results
caf78a8c  Add Apr 19 session: pipeline recovery, expected_value audit, ML path forward
```

---

## Remaining Work (Priority Order)

### 1. Dashboard Turso Migration (HIGH)
Cloud dashboard still reads local SQLite — shows nothing for VPS-era data (Apr 18+).
Needs a dedicated planning session. See Apr 18 handoff for details.

### 2. Golf `expected_value` Column (MEDIUM)
Add `ALTER TABLE predictions ADD COLUMN expected_value REAL` to golf DB.
Backfill from `features_json` (projected score is already computed there).
Wire into prediction script going forward. Same pattern as NHL/MLB.

### 3. NBA Opponent Feature Depth (MEDIUM — before Oct retrain)
`nba_opponent_feature_extractor.py` exists but is shallow. Add before Oct 2026 retrain:
- Opponent defensive rating vs specific stat
- Opponent pace of play
- Rest days / back-to-back flag
- Vegas spread as blowout-risk proxy

### 4. MLB Model Blend Enablement (MEDIUM — mid-season gate)
When ready (target: ~50K graded rows, currently ~38K + ~500/day):
1. Verify feature quality / Brier scores are beating naive baseline
2. Flip `mlb_config.py`: `MODEL_TYPE = "ensemble"`, `LEARNING_MODE = False`
3. Monitor hit rates for 2 weeks before trusting

### 5. make_cut Accuracy Investigation (MEDIUM)
Golf `make_cut` accuracy: 37.3% — below random baseline (~50%). Root cause is likely
missing field-quality normalization (a 70 avg in weak fields ≠ cut in a major).
Fix before next season.

### 6. VPS Cleanup Items (LOW — 6 remaining)
From Apr 18 migration: NBA Turso uncapped prob, Golf EV col (overlaps #2 above),
MLB feature store, NHL hits guard, pp-sync local job removal, Grok key rotation.

---

## Key Config Switches (don't flip without review)

| Sport | File | Flag | Current | Flip when |
|---|---|---|---|---|
| NBA | `nba/scripts/nba_config.py` | `LEARNING_MODE` | `True` | Oct 2026 + clean retrain |
| NHL | `nhl/scripts/v2_config.py` | `MODEL_TYPE` | `statistical_only` | Oct 2026 + clean retrain |
| MLB | `mlb/scripts/mlb_config.py` | `MODEL_TYPE` | `statistical_only` | ~50K graded rows, mid-season |
| Golf | N/A | N/A | No ML scaffolding | Post-season, 700+ samples/prop |

---

## Architecture Notes

### MLB ML is trained but gated
Models exist in `ml_training/model_registry/mlb/` and are valid. The prediction script
will not use them until `MODEL_TYPE = "ensemble"` in `mlb_config.py`. Training runs
every Sunday auto-retrain alongside NHL/NBA — models will continue improving silently.

### expected_value semantics
NHL, MLB, NBA: stores the **projected stat value** (e.g. 23.8 points). OVER/UNDER and
probability are derived by comparing to the PP line. This is architecturally superior to
storing direction+probability — you can reprice against any line retroactively.
Golf: still missing this column — add before next tournament season.

### NaN imputation in train_models.py
`train_median.fillna(0)` is the correct fallback. Columns entirely absent from a sport's
training split (sparse props) produce NaN medians; filling with 0 is safe because sparse
features contribute near-zero signal anyway.
