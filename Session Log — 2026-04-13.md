Session Log — 2026-04-13                                                                                              
  Added singles and doubles prop predictions to the MLB engine.

  Files changed:
  - mlb/scripts/mlb_config.py — added to CORE_PROPS, BATTER_PROPS, LINE_TYPES (singles=goblin, doubles=standard). Total
  combos: 30→32
  - mlb/scripts/statistical_predictions.py — added _batter_singles_lambda() (hits λ × singles fraction, ISO-adjusted
  from 68% base) and _batter_doubles_lambda() (PA × ISO × 0.31). Both wired into predict() and _get_expected_value()
  - mlb/scripts/auto_grade_daily.py — added to BATTER_STAT_MAP: singles = hits−2B−3B−HR, doubles = b.doubles

  Also completed this session (mlb_feature_store):
  - Fixed Python 3.13 pip installs (>=pins, pyarrow/pydantic wheels)
  - Made FanGraphs 403 non-fatal
  - Fixed DuckDB column mismatch (explicit INSERT cols)
  - Built labels layer (hitter_labels + pitcher_labels tables)
  - Backfilled full 2024 + 2025 seasons + labels
  - Created mlb_feature_store/PROJECT_STATUS.md

  Pending:
  - mlb_feature_store Step 2: Streamlit dashboard (port 8503)
  - mlb_feature_store Step 3: ML training module (ml/train.py)