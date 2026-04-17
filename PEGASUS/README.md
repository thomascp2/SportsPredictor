# PEGASUS

Rithmm-caliber sports prediction layer built on top of SportsPredictor's existing data collection pipeline.

## Architecture

PEGASUS is a **parallel, read-only consumer** of the existing SQLite databases. It never writes to them.

```
SportsPredictor (existing, running — DO NOT TOUCH)
  → nhl/database/nhl_predictions_v2.db
  → nba/database/nba_predictions.db
  → mlb/database/mlb_predictions.db
  → mlb_feature_store/data/mlb.duckdb

PEGASUS/ (this directory)
  → calibration/  — reliability diagrams, Brier score, always-UNDER baseline
  → situational/  — playoff stakes, star usage flags
  → pipeline/     — calibrated pick selector, ML blend, edge calculator
  → sync/         — Turso + Supabase upsert
  → api/          — FastAPI endpoints (Phase 7+)
  → run_daily.py  — daily runner (run AFTER existing orchestrator has run)
```

## Running

### Step 1: Calibration audit (run once, then weekly)
```bash
cd SportsPredictor
python PEGASUS/calibration/audit.py
```
Output: `PEGASUS/data/reports/calibration_{sport}_{date}.json` + terminal scorecard.

### Step 2: Daily picks (run manually after orchestrator completes)
```bash
python PEGASUS/run_daily.py
```

## Non-negotiable rules

1. Never write to existing SQLite databases — read-only.
2. Never modify `orchestrator.py`, `nhl/`, `nba/`, `mlb/`, `shared/`, or `sync/`.
3. Every probability shown to users must be calibration-backed.
4. Situational modifiers are display-only — never touch stored probabilities.
5. No NBA ML until clean LR retrain (October 2026 or later).
6. Home runs ML model excluded — XGBoost HR model is worse than naive.
