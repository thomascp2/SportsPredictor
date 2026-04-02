"""
Golf Module Configuration
=========================

Central configuration for the golf prediction system.
All golf scripts must import paths and settings from here — never hardcode.

Architecture notes:
- Golf is individual/tournament-based (no teams, no daily schedule)
- Tournaments run Thursday–Sunday, ~46 PGA Tour events per year
- The "opponent" is the course + field, not another team
- Cut eliminates ~50% of the field after Round 2
- We predict OVER/UNDER on round scores (e.g., will player shoot under 70.5?)

Data strategy (free-first):
- ESPN Golf API for tournament schedule and round scores
- PGA Tour traditional stats as Strokes Gained proxies
- Upgrade path: DataGolf API (~$40/mo) for true SG data when ready

ML readiness target: 7,500 predictions per prop/line combo.
With ~46 tournaments x ~100 players x 4 rounds = ~18,400 data points/season,
a 5-season backfill (2020-2024) should push us past ML readiness quickly.
"""

import os
from pathlib import Path

# ============================================================================
# PATHS
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent  # golf/
REPO_ROOT = PROJECT_ROOT.parent   # SportsPredictor/

DB_PATH = str(PROJECT_ROOT / "database" / "golf_predictions.db")
BACKUP_DIR = str(PROJECT_ROOT / "backups")

# ============================================================================
# LEARNING MODE
# ============================================================================

LEARNING_MODE = True          # Data collection phase — no real-money decisions
PROBABILITY_CAP = 0.72        # Cap predictions to prevent overconfidence
MODEL_TYPE = "statistical"    # 'statistical' until ML training threshold reached

# ============================================================================
# PROP TYPES AND LINES
# ============================================================================

# These mirror the format used by NBA/MLB configs.
# round_score: OVER/UNDER on a player's gross score for one round
#   68.5 = elite rounds (birdie-heavy rounds)
#   70.5 = around-par rounds (most common betting line)
#   72.5 = bogey-leaning rounds
# make_cut: binary — does the player survive the 36-hole cut?
CORE_PROPS = {
    'round_score': [68.5, 70.5, 72.5],  # 3 combos
    'make_cut':    [0.5],               # 1 combo
}

# Total prop/line combos (used for ML readiness tracking)
TOTAL_PROP_COMBOS = sum(len(lines) for lines in CORE_PROPS.values())  # 4

# ============================================================================
# ML TRAINING SETTINGS
# ============================================================================

ML_TRAINING_TARGET_PER_PROP = 7500   # Predictions per prop/line combo before training
ML_TRAINING_MIN_SAMPLES = 500        # Minimum before any ML evaluation
ML_TRAINING_MIN_NEW_PREDICTIONS = 200  # New preds needed to trigger weekly retrain
DATA_COLLECTION_START = "2020-01-01"   # Backfill start (2019-20 PGA season)
DATA_COLLECTION_END = None             # Open-ended (ongoing)

# ============================================================================
# PERFORMANCE TARGETS
# ============================================================================

# Round score UNDER tends to be easier to predict than OVER:
# - Players are more consistent at avoiding blow-up rounds than going low
TARGET_UNDER_ACCURACY = 0.60
TARGET_OVER_ACCURACY  = 0.55

# Minimum confidence to include in output
MIN_PREDICTION_CONFIDENCE = 0.52

# ============================================================================
# PGA TOUR SCHEDULE / CALENDAR
# ============================================================================

# PGA Tour season runs roughly January–August (regular season),
# then FedEx Cup playoffs in August–September.
# Off-season: late October through December.
PGA_SEASON_START_MONTH = 1   # January
PGA_SEASON_END_MONTH = 9     # September

# Known major championship names (used to set f_is_major = 1)
MAJOR_NAMES = [
    "Masters Tournament",
    "The Masters",
    "U.S. Open",
    "US Open",
    "The Open Championship",
    "British Open",
    "PGA Championship",
]

# Typical round par (standard 72-par course).
# Individual courses vary (70–72 is common); use this as fallback.
DEFAULT_COURSE_PAR = 72

# ============================================================================
# DATA QUALITY THRESHOLDS
# ============================================================================

MIN_ROUNDS_FOR_PREDICTION = 10   # Minimum career rounds before generating predictions
MIN_COURSE_HISTORY_ROUNDS = 2    # Min rounds at this specific course to use course features
MIN_FEATURE_COMPLETENESS = 0.80  # Golf has more missing data than NBA (not all stats tracked)

# ============================================================================
# ESPN GOLF API SETTINGS
# ============================================================================

ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/leaderboard"
ESPN_PGA_TOUR_ID = "pga"
ESPN_REQUEST_TIMEOUT = 30   # seconds
ESPN_RETRY_ATTEMPTS = 3

# ============================================================================
# PGA TOUR STATS SETTINGS
# ============================================================================

# Unofficial PGA Tour stats feed (used for traditional stats as SG proxies)
PGA_STATS_BASE_URL = "https://www.pgatour.com/stats"
PGA_STATS_TIMEOUT = 30

# Stat categories we scrape (maps to f_ feature names)
PGA_STAT_CATEGORIES = {
    "driving_distance":  "driving_distance",   # Avg yards off the tee
    "driving_accuracy":  "driving_accuracy",   # % fairways hit
    "gir":               "gir_pct",            # Greens in regulation %
    "scrambling":        "scrambling_pct",     # Up-and-down % when missing GIR
    "putting_avg":       "putting_avg",        # Putts per GIR
    "birdie_avg":        "birdie_avg",         # Birdies per round
}

# ============================================================================
# WORLD RANKING
# ============================================================================

# Players ranked outside this cutoff have very low win probability
# (used to filter for make_cut prop predictions)
OWGR_ACTIVE_THRESHOLD = 500   # Include all players ranked inside world top 500

# ============================================================================
# DISCORD / NOTIFICATIONS
# ============================================================================

DISCORD_WEBHOOK = os.getenv("GOLF_DISCORD_WEBHOOK", "")

# ============================================================================
# DATABASE INITIALIZATION HELPERS
# ============================================================================

SCHEMA_SQL = """
-- Historical round-by-round data (backfill + ongoing)
CREATE TABLE IF NOT EXISTS player_round_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    player_name      TEXT    NOT NULL,
    tournament_name  TEXT    NOT NULL,
    tournament_id    TEXT    NOT NULL,
    course_name      TEXT    NOT NULL,
    round_number     INTEGER NOT NULL,   -- 1, 2, 3, or 4
    round_score      INTEGER,            -- Gross score (e.g., 68, 71)
    score_vs_par     INTEGER,            -- Score relative to par (e.g., -3, +1)
    game_date        TEXT    NOT NULL,   -- Date of this round (YYYY-MM-DD)
    season           INTEGER NOT NULL,   -- PGA Tour season year (e.g., 2024)
    made_cut         INTEGER,            -- 1 = made cut, 0 = missed, NULL = not yet determined
    finish_position  INTEGER,            -- Final tournament finish (NULL during event)
    world_ranking    INTEGER,            -- OWGR at time of event
    driving_distance REAL,               -- Seasonal stat (SG:OTT proxy)
    driving_accuracy REAL,               -- Seasonal stat (SG:OTT proxy)
    gir_pct          REAL,               -- Seasonal stat (SG:APP proxy)
    scrambling_pct   REAL,               -- Seasonal stat (SG:ARG proxy)
    putting_avg      REAL,               -- Seasonal stat (SG:PUTT proxy)
    created_at       TEXT    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(player_name, tournament_id, round_number)
);

CREATE INDEX IF NOT EXISTS idx_prl_player_date
    ON player_round_logs(player_name, game_date);
CREATE INDEX IF NOT EXISTS idx_prl_tournament
    ON player_round_logs(tournament_id, round_number);
CREATE INDEX IF NOT EXISTS idx_prl_season
    ON player_round_logs(season, game_date);

-- Generated predictions
CREATE TABLE IF NOT EXISTS predictions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date        TEXT    NOT NULL,   -- Date of the round being predicted
    player_name      TEXT    NOT NULL,
    tournament_name  TEXT    NOT NULL,
    prop_type        TEXT    NOT NULL,   -- 'round_score' or 'make_cut'
    line             REAL    NOT NULL,   -- e.g., 70.5 or 0.5
    prediction       TEXT    NOT NULL,   -- 'OVER' or 'UNDER'
    probability      REAL    NOT NULL,   -- Model confidence [0,1]
    features_json    TEXT,               -- JSON blob of f_ features used
    round_number     INTEGER,            -- 1–4 (NULL for make_cut)
    model_version    TEXT    DEFAULT 'statistical',
    created_at       TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pred_date
    ON predictions(game_date);
CREATE INDEX IF NOT EXISTS idx_pred_player_prop
    ON predictions(player_name, prop_type, line);

-- Graded outcomes
CREATE TABLE IF NOT EXISTS prediction_outcomes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id  INTEGER REFERENCES predictions(id),
    game_date      TEXT    NOT NULL,
    player_name    TEXT    NOT NULL,
    prop_type      TEXT    NOT NULL,
    line           REAL    NOT NULL,
    actual_value   REAL,               -- Actual round score or 1/0 for make_cut
    prediction     TEXT    NOT NULL,   -- 'OVER' or 'UNDER'
    outcome        TEXT,               -- 'HIT' or 'MISS'
    graded_at      TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outcomes_date
    ON prediction_outcomes(game_date);
"""


def init_database(db_path=None):
    """Initialize the golf database with all required tables."""
    import sqlite3
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    return path


def has_active_tournament(target_date=None):
    """
    Returns True if there is likely an active PGA Tour tournament on the target date.
    Uses a simple heuristic: Thu–Sun during PGA season months.
    The ESPN API is the authoritative source; this is a fast pre-check.
    """
    from datetime import date
    d = date.fromisoformat(target_date) if target_date else date.today()
    # Thu=3, Fri=4, Sat=5, Sun=6
    is_tournament_day = d.weekday() in (3, 4, 5, 6)
    in_season = PGA_SEASON_START_MONTH <= d.month <= PGA_SEASON_END_MONTH
    return is_tournament_day and in_season
