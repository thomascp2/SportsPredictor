"""
Game Prediction Schema — Shared database table definitions for full-game predictions.

Creates game_predictions and game_prediction_outcomes tables in each sport's database.
These are completely separate from the existing player prop predictions tables.

Usage:
    from shared.game_prediction_schema import ensure_game_tables
    ensure_game_tables(conn)  # Creates tables if they don't exist
"""

# ── Game Predictions Table ────────────────────────────────────────────────────

GAME_PREDICTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date TEXT NOT NULL,
    game_id TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    venue TEXT,

    -- Bet details
    bet_type TEXT NOT NULL,       -- 'moneyline', 'spread', 'total'
    bet_side TEXT NOT NULL,       -- 'home', 'away', 'over', 'under'
    line REAL,                    -- spread value or total line (NULL for moneyline)

    -- Prediction
    prediction TEXT NOT NULL,     -- 'WIN'/'LOSE' or 'OVER'/'UNDER'
    probability REAL,             -- calibrated probability
    edge REAL,                    -- predicted prob minus implied prob from odds
    confidence_tier TEXT,         -- 'SHARP', 'LEAN', 'PASS'

    -- Odds at time of prediction
    odds_american INTEGER,        -- e.g., -110, +150
    implied_probability REAL,     -- from the odds

    -- Model info
    model_version TEXT,
    model_type TEXT,              -- 'statistical', 'xgboost', 'lgbm', 'ensemble'
    features_json TEXT,           -- JSON blob of all features used

    -- Elo snapshot
    home_elo REAL,
    away_elo REAL,
    elo_diff REAL,
    elo_win_prob REAL,            -- Elo-predicted home win probability

    -- Metadata
    prediction_batch_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(game_date, home_team, away_team, bet_type, bet_side, line, model_version)
)
"""

GAME_PREDICTIONS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_gp_date ON game_predictions(game_date)",
    "CREATE INDEX IF NOT EXISTS idx_gp_teams ON game_predictions(home_team, away_team)",
    "CREATE INDEX IF NOT EXISTS idx_gp_bet_type ON game_predictions(bet_type)",
    "CREATE INDEX IF NOT EXISTS idx_gp_tier ON game_predictions(confidence_tier)",
    "CREATE INDEX IF NOT EXISTS idx_gp_batch ON game_predictions(prediction_batch_id)",
]

# ── Game Prediction Outcomes Table ────────────────────────────────────────────

GAME_PREDICTION_OUTCOMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_prediction_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER NOT NULL,
    game_date TEXT NOT NULL,
    game_id TEXT,

    -- Bet details (denormalized for easy querying)
    bet_type TEXT NOT NULL,
    bet_side TEXT NOT NULL,
    line REAL,
    prediction TEXT NOT NULL,

    -- Actual result
    home_score INTEGER,
    away_score INTEGER,
    actual_margin INTEGER,        -- home_score - away_score (positive = home win)
    actual_total INTEGER,         -- home_score + away_score

    -- Grading
    outcome TEXT NOT NULL,        -- 'HIT', 'MISS', 'PUSH'
    model_version TEXT,
    confidence_tier TEXT,

    -- P&L tracking (flat $100 unit)
    odds_american INTEGER,
    profit REAL,                  -- +90 (win), -100 (loss), 0 (push)

    graded_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(prediction_id),
    FOREIGN KEY (prediction_id) REFERENCES game_predictions(id)
)
"""

GAME_PREDICTION_OUTCOMES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_gpo_date ON game_prediction_outcomes(game_date)",
    "CREATE INDEX IF NOT EXISTS idx_gpo_outcome ON game_prediction_outcomes(outcome)",
    "CREATE INDEX IF NOT EXISTS idx_gpo_bet_type ON game_prediction_outcomes(bet_type)",
    "CREATE INDEX IF NOT EXISTS idx_gpo_tier ON game_prediction_outcomes(confidence_tier)",
]

# ── Bot Arena Tables (for competitive model tracking) ─────────────────────────

BOT_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_name TEXT NOT NULL UNIQUE,
    strategy TEXT,                -- Description of the bot's approach
    feature_set TEXT,             -- JSON list of feature categories used
    model_type TEXT,              -- 'xgboost', 'lgbm', 'ensemble', etc.
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1
)
"""

BOT_PREDICTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_name TEXT NOT NULL,
    game_date TEXT NOT NULL,
    game_id TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    bet_type TEXT NOT NULL,
    bet_side TEXT NOT NULL,
    line REAL,
    prediction TEXT NOT NULL,
    probability REAL,
    confidence REAL,              -- Bot's self-assessed confidence
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(bot_name, game_date, home_team, away_team, bet_type, line),
    FOREIGN KEY (bot_name) REFERENCES bot_registry(bot_name)
)
"""

BOT_PERFORMANCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_name TEXT NOT NULL,
    game_date TEXT NOT NULL,
    prediction_id INTEGER,

    outcome TEXT,                 -- 'HIT', 'MISS', 'PUSH'
    profit REAL,

    -- Running totals (updated after each grading)
    season_wins INTEGER,
    season_losses INTEGER,
    season_pushes INTEGER,
    season_roi REAL,
    current_streak INTEGER,       -- positive = win streak, negative = loss streak

    graded_at TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (bot_name) REFERENCES bot_registry(bot_name)
)
"""

BOT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_bp_bot ON bot_predictions(bot_name)",
    "CREATE INDEX IF NOT EXISTS idx_bp_date ON bot_predictions(game_date)",
    "CREATE INDEX IF NOT EXISTS idx_bperf_bot ON bot_performance(bot_name)",
]


def ensure_game_tables(conn):
    """Create all game prediction tables if they don't exist."""
    conn.execute(GAME_PREDICTIONS_SCHEMA)
    conn.execute(GAME_PREDICTION_OUTCOMES_SCHEMA)
    for idx in GAME_PREDICTIONS_INDEXES + GAME_PREDICTION_OUTCOMES_INDEXES:
        conn.execute(idx)

    # Bot Arena tables
    conn.execute(BOT_REGISTRY_SCHEMA)
    conn.execute(BOT_PREDICTIONS_SCHEMA)
    conn.execute(BOT_PERFORMANCE_SCHEMA)
    for idx in BOT_INDEXES:
        conn.execute(idx)

    conn.commit()


def ensure_default_bots(conn):
    """Register the default bot personas."""
    default_bots = [
        ("The Quant", "Pure numbers — traditional stats + Elo + market data", "standard_stats,elo,odds"),
        ("The Situationist", "Rest, travel, schedule spots, revenge games, emotional factors", "rest,travel,schedule,situational"),
        ("The Contrarian", "CLV, reverse line movement, public %, fade the public", "line_movement,public_pct,clv"),
        ("The Matchup Nerd", "Lineup-specific data, goalie/pitcher matchups, pace differentials", "matchups,pace,lineup,four_factors"),
        ("The Weather Witch", "Weather, barometric pressure, altitude, wind, park factors", "weather,park_factors,altitude,environment"),
        ("The Kitchen Sink", "Everything combined — let the ML feature-select", "all"),
        ("The Ensemble", "Meta-learner combining predictions from all other bots", "meta,convergence"),
    ]

    for name, strategy, features in default_bots:
        conn.execute("""
            INSERT OR IGNORE INTO bot_registry (bot_name, strategy, feature_set)
            VALUES (?, ?, ?)
        """, (name, strategy, features))

    conn.commit()


# ── CLI: Initialize tables in all sport databases ─────────────────────────────

if __name__ == "__main__":
    import os

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dbs = {
        "NHL": os.path.join(base, "nhl", "database", "nhl_predictions_v2.db"),
        "NBA": os.path.join(base, "nba", "database", "nba_predictions.db"),
        "MLB": os.path.join(base, "mlb", "database", "mlb_predictions.db"),
    }

    import sqlite3
    for sport, db_path in dbs.items():
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            ensure_game_tables(conn)
            ensure_default_bots(conn)

            # Verify
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'game_%' OR name LIKE 'bot_%'"
            ).fetchall()]
            bots = conn.execute("SELECT COUNT(*) FROM bot_registry").fetchone()[0]
            conn.close()
            print(f"[{sport}] Game tables created: {tables} | {bots} bots registered")
        else:
            print(f"[{sport}] Database not found: {db_path}")
