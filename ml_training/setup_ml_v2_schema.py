"""
ml_training/setup_ml_v2_schema.py

Creates the ml_v2_predictions table in each sport's SQLite database.

Run once before starting the ML v2 pipeline:
    python ml_training/setup_ml_v2_schema.py

Safe to re-run — uses CREATE TABLE IF NOT EXISTS.
"""

import sqlite3
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_SPORT_DBS = {
    "nhl": _REPO_ROOT / "nhl" / "database" / "nhl_predictions_v2.db",
    "nba": _REPO_ROOT / "nba" / "database" / "nba_predictions.db",
    "mlb": _REPO_ROOT / "mlb" / "database" / "mlb_predictions.db",
}

_CREATE_ML_V2 = """
CREATE TABLE IF NOT EXISTS ml_v2_predictions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date        DATE    NOT NULL,
    player_name      TEXT    NOT NULL,
    team             TEXT,
    prop_type        TEXT    NOT NULL,
    line             REAL    NOT NULL,
    prediction       TEXT,           -- 'OVER' or 'UNDER'
    model_prob       REAL,           -- BMA mean P(predicted direction)
    prob_over        REAL,           -- BMA mean P(OVER) regardless of direction
    prob_std         REAL,           -- uncertainty (lower = more confident)
    ci_lower         REAL,           -- 2.5th percentile bootstrap
    ci_upper         REAL,           -- 97.5th percentile bootstrap
    model_confidence TEXT,           -- 'HIGH' / 'MEDIUM' / 'LOW'
    component_probs  TEXT,           -- JSON: {model_name: prob_over}
    mab_weights      TEXT,           -- JSON: weights used for this prediction
    market_implied   REAL,           -- DK implied prob (NULL = no paid plan yet)
    true_edge        REAL,           -- model_prob - market_implied (NULL if no market)
    pp_edge          REAL,           -- model_prob - PP break-even (always present)
    pp_break_even    REAL,           -- break-even used for pp_edge
    odds_type        TEXT,           -- 'standard' / 'goblin' / 'demon'
    drift_flagged    INTEGER DEFAULT 0,  -- 1 if KS drift detected for this prop today
    created_at       TEXT,
    UNIQUE(game_date, player_name, prop_type, line)
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ml_v2_date_sport
    ON ml_v2_predictions (game_date)
"""


def setup_schema(sport: str = None):
    targets = {sport: _SPORT_DBS[sport]} if sport and sport in _SPORT_DBS else _SPORT_DBS

    for sp, db_path in targets.items():
        if not db_path.exists():
            print(f"  [{sp.upper()}] DB not found at {db_path} — skipping")
            continue

        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.execute(_CREATE_ML_V2)
        conn.execute(_CREATE_INDEX)
        conn.commit()
        conn.close()
        print(f"  [{sp.upper()}] ml_v2_predictions table ready at {db_path.name}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Set up ml_v2_predictions schema")
    parser.add_argument("--sport", choices=["nhl", "nba", "mlb"], default=None,
                        help="Sport to set up (default: all)")
    args = parser.parse_args()

    print("\nSetting up ML v2 schema...")
    setup_schema(args.sport)
    print("Done.\n")
