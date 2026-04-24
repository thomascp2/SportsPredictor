---
# apex-arb Session 1 — Handoff Prompt
**Date: 2026-04-24 | Paste this cold into the next session.**

---

```
We are building MLB V2 inside the apex-arb repo (C:\Users\thoma\apex-arb).
Read MLB_V2_MASTER_PLAN.md and docs/sessions/2026-04-24-mlb-v2-session-0.md
in SportsPredictor before anything else.

Context:
- Session 0 complete. apex-arb repo is live at https://github.com/thomascp2/apex-arb
- SportsPredictor is read-only archive. Orchestrator stopped (intentional).
- Replaced by Windows Task Scheduler:
    8:00 AM  → run_v2_grader.bat  → auto_grade_daily.py
    10:00 AM → run_v2_predictor.bat → generate_v2_predictions.py
- mlb_v2.db: fresh DB at apex-arb/mlb/database/mlb_v2.db
    - 81,722 player_game_logs copied from V1 (clean box score data)
    - ml_v2_predictions table created and ready
    - Data boundary: ml_v2_predictions starts 2026-04-25, zero V1 rows
- mlb.duckdb: 45MB Statcast history at apex-arb/feature_store/data/mlb.duckdb
- ACTIVE_MODELS = ['stat', 'xgb'] — phantom arms fixed in Session 0
- Secrets live in env.bat (gitignored) — never hardcode keys in any file
- All bat files call env.bat before running Python

Pick up at Phase A2. Work in order — do not skip ahead:

A2 — Extend feature_store/ml/train.py
  - Add RandomForestRegressor (sklearn) for each prop → saves {prop}_rf.pkl
  - Add Ridge regression for each prop → saves {prop}_lr.pkl
  - Same feature matrix and 70/15/15 temporal split as existing XGBoost
  - Add RF and LR metrics (MAE, RMSE) to metadata.json alongside XGBoost
  - Only runs if ≥500 clean rows (same guard as XGBoost — do not lower this)

A3 — Build feature_store/ml/retrain.py
  - Train XGBoost + RF + LR → validate → deploy only if val_mae improves ≥0.005 vs current
  - KS drift flag overrides the improvement gate (allow retrain even if marginal)
  - Writes deploy log to metadata.json with version history

A4 — Extend feature_store/ml/predict_to_db.py
  - Add RF and LR inference alongside XGBoost
  - Schema migration: add rf_predicted_value, lr_predicted_value columns to ml_predictions
  - generate_v2_predictions.py loads all 3 when available

B1 — Build mlb/scripts/mlb_ks_drift.py
  - KS test on actual_value from ml_v2_outcomes (real outcomes, not model probs)
  - Reference distribution: DuckDB pitcher_labels + hitter_labels (full historical)
  - Logs to mlb_drift_log table in mlb_v2.db
  - Wire into auto_grade_daily.py after _grade_v2_predictions()
  - On drift: call retrain.py for affected props (non-fatal)

B2 — Build mlb/scripts/mlb_v2_calibration.py
  - 7 reports: row counts, BMA vs stat-only hit rate, calibration by tier,
    individual arm accuracy, MAB weight trajectory, drift log summary, Phase 2 gate status
  - Early stopping rule (LAW): if BMA > 5pp below stat-only after 200 rows → print STOP banner
  - Usage: python mlb_v2_calibration.py [--date YYYY-MM-DD]

run_daily_v2.py — Simple 4-script daily runner at repo root
  - Replaces individual TS entries once built
  - Sequence: grade (8am) → predict (10am) → feature store ingest (10:30am) → predict_to_db (10:45am)
  - Simple subprocess calls, no orchestrator complexity

Push back hard if scope creeps. MLB V2 only.
No dashboard. No Discord. No Supabase. No FreePicks.
Early stopping rule is law, not a suggestion — the NHL/NBA debacle of 2026 is why.
```
