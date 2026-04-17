"""
PEGASUS Configuration
Paths to existing databases + constants. Read-only contract — PEGASUS never writes to these DBs.
"""
from pathlib import Path

# Project root (SportsPredictor/)
ROOT = Path(__file__).parent.parent

# ── Existing SQLite databases (READ-ONLY from PEGASUS) ──────────────────────
NHL_DB = ROOT / "nhl" / "database" / "nhl_predictions_v2.db"
NBA_DB = ROOT / "nba" / "database" / "nba_predictions.db"
MLB_DB = ROOT / "mlb" / "database" / "mlb_predictions.db"

# MLB XGBoost feature store (DuckDB)
MLB_DUCKDB = ROOT / "mlb_feature_store" / "data" / "mlb.duckdb"

# NHL ML model registry
NHL_MODEL_REGISTRY = ROOT / "ml_training" / "model_registry" / "nhl"

# ── PEGASUS local output dirs ────────────────────────────────────────────────
PEGASUS_ROOT = Path(__file__).parent
CALIBRATION_TABLES_DIR = PEGASUS_ROOT / "data" / "calibration_tables"
REPORTS_DIR = PEGASUS_ROOT / "data" / "reports"

# ── Break-even constants (must match smart_pick_selector.py exactly) ─────────
# Standard (-110): risk 110 to win 100 → break-even = 110/210 = 0.5238
# Goblin  (-320): risk 320 to win 100 → break-even = 320/420 = 0.7619
# Demon   (+100 payout, -220 risk): break-even = 100/220 = 0.4545
BREAK_EVEN = {
    "standard": 0.5238,
    "goblin":   0.7619,
    "demon":    0.4545,
}

# ── Tier thresholds (edge above break-even, in percentage points) ────────────
TIER_THRESHOLDS = {
    "T1-ELITE":  19.0,
    "T2-STRONG": 14.0,
    "T3-GOOD":    9.0,
    "T4-LEAN":    0.0,
    # T5-FADE: edge < 0 (suppressed from output by default)
}

# ── Calibration audit gate ───────────────────────────────────────────────────
# real_edge = our_accuracy - always_under_accuracy
# Must exceed this threshold (with n > MIN_SAMPLE_N) for sport to pass
MIN_REAL_EDGE = 0.03   # 3 percentage points
MIN_SAMPLE_N  = 1000

# Minimum sample per calibration bucket to include in reliability diagram
MIN_BUCKET_N = 30

# ── Supported sports ─────────────────────────────────────────────────────────
SPORTS = ["nhl", "nba", "mlb"]
