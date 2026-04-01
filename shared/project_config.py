"""
shared/project_config.py — Single source of truth for cross-sport constants.

Import from here instead of redefining in individual scripts:

    from project_config import BREAK_EVEN, DB_PATHS, SPORT_KEYS

Authoritative values. If you change something here it takes effect everywhere.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Repository root
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# SQLite database paths
# ---------------------------------------------------------------------------
DB_PATHS = {
    "NHL":  ROOT / "nhl"  / "database" / "nhl_predictions_v2.db",
    "NBA":  ROOT / "nba"  / "database" / "nba_predictions.db",
    "MLB":  ROOT / "mlb"  / "database" / "mlb_predictions.db",
    "GOLF": ROOT / "golf" / "database" / "golf_predictions.db",
}

# String form (for sqlite3.connect which doesn't accept Path on older Python)
DB_PATH_STR = {k: str(v) for k, v in DB_PATHS.items()}

# ---------------------------------------------------------------------------
# PrizePicks break-even probabilities (single-pick, flat -110 equivalent)
#
# These must stay in sync with smart_pick_selector.py.  The values represent
# the minimum hit-rate required for each odds type to produce a positive EV.
#
#   standard : -110 odds (2x payout at 52.4% break-even, PP net ≈ 56%)
#   goblin   : reduced payout (power play goblin — 76% break-even)
#   demon    : boosted payout (power play demon — 45% break-even)
# ---------------------------------------------------------------------------
BREAK_EVEN = {
    "standard": 0.56,
    "goblin":   0.76,
    "demon":    0.45,
}

# ---------------------------------------------------------------------------
# Profit per $100 risked at standard -110 odds (used in grading scripts)
# ---------------------------------------------------------------------------
FLAT_BET_PROFIT = {
    "HIT":  90.91,
    "MISS": -100.0,
    "PUSH": 0.0,
    "VOID": 0.0,
}

# ---------------------------------------------------------------------------
# Smart-pick tier thresholds (edge above break-even, in percentage points)
# ---------------------------------------------------------------------------
TIER_THRESHOLDS = {
    "T1-ELITE":  19,
    "T2-STRONG": 14,
    "T3-GOOD":    9,
    "T4-LEAN":    0,
}

# ---------------------------------------------------------------------------
# Sport keys (canonical uppercase)
# ---------------------------------------------------------------------------
SPORT_KEYS = ["NHL", "NBA", "MLB", "GOLF"]
