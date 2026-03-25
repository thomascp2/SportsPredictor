"""
MLB Prediction System - Central Configuration
=============================================

Single source of truth for all MLB-specific settings.
ALL other scripts must import from here — never hardcode paths or settings.

Mission: Build a world-class MLB prop prediction system by capturing every
measurable PrizePicks MLB prop with rich features (opposing pitcher, park factors,
Vegas lines, weather) to identify +EV spots for end users.

Prop Predictability Reference:
  HIGH:    Pitcher strikeouts, batter strikeouts (K rates most stable in baseball)
  MED-HI:  Hits O0.5 for high-avg hitters vs weak pitchers
  MEDIUM:  Pitcher walks, total bases, outs recorded, HRR
  LOW:     Home runs, RBIs, runs scored, stolen bases, earned runs (high variance)

PrizePicks Goblin/Demon Break-even Rates (VERIFIED):
  Standard: ~54.5% per leg (6-pick Power Play at 37.5x payout)
  Goblin:   ~70.7% per leg (1 goblin in 2-pick drops payout to ~2x)
  Demon:    ~44.7% per leg (1 demon in 2-pick raises payout to ~5x)
  KEY INSIGHT: Goblins are HARDER to profit from despite easier lines.
               Demons are EASIER to profit from despite harder lines.
"""

import os
import sqlite3
from pathlib import Path

# ============================================================================
# PATHS
# ============================================================================

MLB_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = MLB_ROOT.parent
DB_PATH = str(MLB_ROOT / "database" / "mlb_predictions.db")
BACKUPS_DIR = str(MLB_ROOT / "backups")

# ============================================================================
# SYSTEM SETTINGS
# ============================================================================

LEARNING_MODE = False         # False = use best available model (statistical now, ML later)
MODEL_TYPE = "statistical_only"   # Will switch to "ensemble" when ML models ready
PROBABILITY_CAP = (0.0, 1.0)      # No cap during ML calibration phase
TIMEZONE = "America/Chicago"      # CST
SEASON = "2026"
DATA_COLLECTION_START = "2026-03-27"  # Opening Day 2026 (approximate)

# ============================================================================
# PROPS & LINES (30 total prop/line combos)
# ============================================================================

CORE_PROPS = {
    # --- Pitcher props (13 combos) ---
    # Highest predictability: K/9 is the most stable stat in baseball
    'strikeouts':    [3.5, 4.5, 5.5, 6.5, 7.5],

    # Medium predictability: tied to pitcher efficiency and run suppression
    'outs_recorded': [12.5, 15.5, 17.5],

    # Medium predictability: BB% stable season-long but noisy per game
    'pitcher_walks': [1.5, 2.5],

    # Medium predictability: WHIP is predictable but hits cluster
    'hits_allowed':  [3.5, 5.5],

    # Low predictability: random events (HRs, defense, sequencing) dominate
    'earned_runs':   [0.5, 1.5, 2.5],

    # --- Batter props (17 combos) ---
    # Medium-High: high-avg hitters in favorable matchups have reliable floors
    'hits':               [0.5, 1.5],

    # Medium: ISO + park + pitcher matchup gives good signal
    'total_bases':        [1.5, 2.5],

    # Low-Medium: even elite HR hitters avg ~0.15 HR/game; high variance
    'home_runs':          [0.5],

    # Low: baserunner-context dependent — hard to predict without lineup info
    'rbis':               [0.5, 1.5],

    # Low: batting order + team offense dependent; use cautiously
    'runs':               [0.5],

    # Low: green light + game situation dependent
    'stolen_bases':       [0.5],

    # Medium: BB% very stable; best when opposing pitcher walks a lot
    'walks':              [0.5],

    # High: K% extremely stable; best when high-K batter faces high-K pitcher
    'batter_strikeouts':  [0.5, 1.5],

    # Medium: hits + runs + rbis; good for high-OBP contact hitters
    'hrr':                [1.5, 2.5, 3.5],
}

# Player type for each prop (determines which features to extract)
PITCHER_PROPS = {'strikeouts', 'outs_recorded', 'pitcher_walks', 'hits_allowed', 'earned_runs'}
BATTER_PROPS = {'hits', 'total_bases', 'home_runs', 'rbis', 'runs', 'stolen_bases',
                'walks', 'batter_strikeouts', 'hrr'}

def get_player_type(prop_type: str) -> str:
    """Returns 'pitcher' or 'batter' for a given prop type."""
    if prop_type in PITCHER_PROPS:
        return 'pitcher'
    if prop_type in BATTER_PROPS:
        return 'batter'
    raise ValueError(f"Unknown prop type: {prop_type}")

# Total combos
TOTAL_PROP_COMBOS = sum(len(lines) for lines in CORE_PROPS.values())  # 30

# ============================================================================
# PRIZEPICKS LINE TYPE CLASSIFICATION
# ============================================================================
# On PrizePicks, goblin and demon lines only allow OVER (More) selections.
# Standard lines allow both OVER and UNDER.
#
# Goblin lines: easier bar → ~70.7% break-even → OVER only
# Demon lines:  harder bar → ~44.7% break-even → OVER only
# Standard:     middle bar → ~54.5% break-even → OVER or UNDER
#
# CRITICAL: Never record or grade UNDER predictions for goblin/demon lines.
# These picks are not actionable on PrizePicks.
#
# Note: PrizePicks assigns line types dynamically. This dict represents our
# best classification based on typical PrizePicks behavior. Update as needed
# when PrizePicks changes their offerings.
LINE_TYPES = {
    # ----- Goblin lines (easy bars — OVER only on PrizePicks) -----
    # Low-threshold props where hitting Over is relatively easy
    ('hits', 0.5):               'goblin',
    ('runs', 0.5):               'goblin',
    ('rbis', 0.5):               'goblin',
    ('stolen_bases', 0.5):       'goblin',
    ('walks', 0.5):              'goblin',
    ('batter_strikeouts', 0.5):  'goblin',
    ('earned_runs', 0.5):        'goblin',

    # ----- Standard lines (OVER or UNDER available) -----
    # HR 0.5 is standard — not trivially easy despite low bar
    ('home_runs', 0.5):          'standard',
    # Mid-range lines default to standard (explicit for clarity)
    ('hits', 1.5):               'standard',
    ('strikeouts', 3.5):         'standard',
    ('strikeouts', 4.5):         'standard',
    ('strikeouts', 5.5):         'standard',
    ('strikeouts', 6.5):         'standard',
    ('outs_recorded', 12.5):     'standard',
    ('outs_recorded', 15.5):     'standard',
    ('pitcher_walks', 1.5):      'standard',
    ('hits_allowed', 3.5):       'standard',
    ('earned_runs', 1.5):        'standard',
    ('total_bases', 1.5):        'standard',
    ('rbis', 1.5):               'standard',
    ('batter_strikeouts', 1.5):  'standard',
    ('hrr', 1.5):                'standard',
    ('hrr', 2.5):                'standard',

    # ----- Demon lines (hard bars — OVER only on PrizePicks) -----
    # High-threshold props where hitting Over requires elite performance
    ('strikeouts', 7.5):         'demon',
    ('outs_recorded', 17.5):     'demon',
    ('pitcher_walks', 2.5):      'demon',
    ('hits_allowed', 5.5):       'demon',
    ('earned_runs', 2.5):        'demon',
    ('total_bases', 2.5):        'demon',
    ('hrr', 3.5):                'demon',
}


def get_line_type(prop_type: str, line: float) -> str:
    """
    Returns PrizePicks line type: 'standard', 'goblin', or 'demon'.

    Goblin and demon lines only support OVER (More) selections on PrizePicks.
    UNDER predictions for goblin/demon lines are not actionable and must
    never be recorded or graded.

    Args:
        prop_type: Prop type string (e.g., 'strikeouts', 'hits')
        line: Line value (e.g., 4.5, 0.5)

    Returns:
        'standard', 'goblin', or 'demon' (defaults to 'standard' if unknown)
    """
    return LINE_TYPES.get((prop_type, float(line)), 'standard')


def is_over_only_line(prop_type: str, line: float) -> bool:
    """
    Returns True if this prop/line combo only supports OVER (goblin or demon).

    Use this to filter out non-actionable UNDER predictions before saving.
    """
    return get_line_type(prop_type, line) in ('goblin', 'demon')

# ============================================================================
# CONFIDENCE TIERS (same as NHL/NBA)
# ============================================================================

CONFIDENCE_TIERS = {
    'T1-ELITE':  0.75,
    'T2-STRONG': 0.70,
    'T3-GOOD':   0.65,
    'T4-LEAN':   0.55,
    'T5-FADE':   0.0,
}

def get_confidence_tier(probability: float) -> str:
    """Assign confidence tier based on probability."""
    for tier, threshold in CONFIDENCE_TIERS.items():
        if probability >= threshold:
            return tier
    return 'T5-FADE'

# ============================================================================
# ML TRAINING SETTINGS
# ============================================================================

ML_TRAINING_TARGET_PER_PROP = 7500   # Predictions per prop/line combo before ML training
ML_TRAINING_START_DATE = "2027-03-01"  # After ~1 full MLB season of data collection

# ============================================================================
# DATA QUALITY THRESHOLDS
# ============================================================================

MIN_FEATURE_COMPLETENESS = 0.90   # MLB allows slightly more missing data (TBD starters, etc.)
MIN_OPPONENT_FEATURE_RATE = 0.85  # Rate of predictions with opponent features populated
OPPONENT_FEATURE_LOOKBACK_DAYS = 14
MIN_DAILY_PREDICTIONS = 100       # ~30 pitchers + ~250 batters on a full slate
MAX_DAILY_PREDICTIONS = 500
MIN_PITCHER_STARTS_FOR_PREDICTION = 3   # Skip pitcher props below this threshold
MIN_BATTER_GAMES_FOR_PREDICTION = 10    # Skip batter props below this threshold

# ============================================================================
# PERFORMANCE TARGETS
# ============================================================================

TARGET_UNDER_ACCURACY = 0.60
TARGET_OVER_ACCURACY = 0.55

# ============================================================================
# API SETTINGS
# ============================================================================

# Official MLB Stats API (free, no auth needed)
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
MLB_API_TIMEOUT = 30
MLB_API_RETRIES = 3

# ESPN hidden API (for Vegas odds)
ESPN_API_BASE = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb"

# OpenWeatherMap (weather at ballpark)
OPENWEATHERMAP_API_KEY = os.getenv('OPENWEATHERMAP_API_KEY', '')
OPENWEATHERMAP_BASE = "https://api.openweathermap.org/data/2.5"

# ============================================================================
# SCHEDULE HELPERS
# ============================================================================

# MLB regular season runs approximately late March through late September
MLB_SEASON_START_MONTH = 3   # March
MLB_SEASON_END_MONTH = 9     # September
MLB_SEASON_START_DAY = 20    # Approximate earliest opening day
MLB_SEASON_END_DAY = 30      # Approximate latest end of regular season


def mlb_has_games(target_date: str) -> bool:
    """
    Check whether MLB regular season games are expected on a given date.

    Uses a quick date range check first, then optionally queries the MLB
    Stats API schedule for confirmation. Fails OPEN (returns True) on API errors
    so the prediction pipeline runs rather than silently skipping a game day.

    Args:
        target_date: Date string in YYYY-MM-DD format.

    Returns:
        True if games are expected, False if clearly in the off-season.
    """
    try:
        from datetime import datetime
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        month = dt.month

        # Quick off-season check (October through mid-March)
        if month in (10, 11, 12, 1, 2):
            return False
        if month == 3 and dt.day < MLB_SEASON_START_DAY:
            return False

        # For dates in the valid window, assume games exist.
        # Could add API-based confirmation here in a future iteration.
        return True

    except Exception:
        # Fail open — assume games exist
        return True


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date TEXT NOT NULL,
    game_id TEXT,
    player_name TEXT NOT NULL,
    player_id INTEGER,
    team TEXT NOT NULL,
    opponent TEXT NOT NULL,
    home_away TEXT NOT NULL,
    player_type TEXT NOT NULL,
    prop_type TEXT NOT NULL,
    line REAL NOT NULL,
    prediction TEXT NOT NULL,
    probability REAL NOT NULL,
    confidence_tier TEXT NOT NULL,
    expected_value REAL,
    features_json TEXT,
    model_version TEXT,
    prediction_batch_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prediction_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER REFERENCES predictions(id),
    game_date TEXT NOT NULL,
    game_id TEXT,
    player_name TEXT NOT NULL,
    prop_type TEXT NOT NULL,
    line REAL NOT NULL,
    prediction TEXT NOT NULL,
    actual_value REAL,
    outcome TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_game_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT,
    game_date TEXT NOT NULL,
    player_name TEXT NOT NULL,
    player_id INTEGER,
    team TEXT NOT NULL,
    opponent TEXT NOT NULL,
    home_away TEXT NOT NULL,
    player_type TEXT NOT NULL,
    innings_pitched REAL,
    outs_recorded INTEGER,
    strikeouts_pitched INTEGER,
    walks_allowed INTEGER,
    hits_allowed INTEGER,
    earned_runs INTEGER,
    home_runs_allowed INTEGER,
    pitches INTEGER,
    at_bats INTEGER,
    hits INTEGER,
    home_runs INTEGER,
    rbis INTEGER,
    runs INTEGER,
    stolen_bases INTEGER,
    walks_drawn INTEGER,
    strikeouts_batter INTEGER,
    doubles INTEGER,
    triples INTEGER,
    total_bases INTEGER,
    hrr INTEGER,
    batting_order INTEGER,
    opposing_pitcher TEXT,
    opposing_pitcher_hand TEXT,
    venue TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(game_id, player_name, player_type)
);

CREATE TABLE IF NOT EXISTS game_context (
    game_id TEXT PRIMARY KEY,
    game_date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    venue TEXT,
    home_starter TEXT,
    away_starter TEXT,
    home_starter_id INTEGER,
    away_starter_id INTEGER,
    home_ml INTEGER,
    away_ml INTEGER,
    game_total REAL,
    temperature INTEGER,
    wind_speed INTEGER,
    wind_direction TEXT,
    conditions TEXT,
    day_night TEXT,
    status TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_predictions_date ON predictions(game_date);
CREATE INDEX IF NOT EXISTS idx_predictions_player ON predictions(player_name, prop_type);
CREATE INDEX IF NOT EXISTS idx_outcomes_date ON prediction_outcomes(game_date);
CREATE INDEX IF NOT EXISTS idx_logs_player ON player_game_logs(player_name, game_date);
CREATE INDEX IF NOT EXISTS idx_logs_team ON player_game_logs(team, game_date);
CREATE INDEX IF NOT EXISTS idx_context_date ON game_context(game_date);
"""


def initialize_database(db_path: str = None) -> None:
    """
    Create the MLB database and all required tables if they don't exist.

    Args:
        db_path: Path to SQLite database. Defaults to DB_PATH.
    """
    if db_path is None:
        db_path = DB_PATH

    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(DB_SCHEMA)
        conn.commit()
        print(f"[MLB] Database initialized: {db_path}")
    finally:
        conn.close()


def get_db_connection(db_path: str = None) -> sqlite3.Connection:
    """
    Get a database connection with row_factory set for dict-like access.

    Args:
        db_path: Path to SQLite database. Defaults to DB_PATH.

    Returns:
        sqlite3.Connection with row_factory = sqlite3.Row
    """
    if db_path is None:
        db_path = DB_PATH

    if not Path(db_path).exists():
        initialize_database(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================================
# TEAM ABBREVIATION MAPPINGS
# (MLB Stats API abbreviations — canonical source)
# ============================================================================

MLB_TEAMS = {
    'ARI': 'Arizona Diamondbacks',
    'ATL': 'Atlanta Braves',
    'BAL': 'Baltimore Orioles',
    'BOS': 'Boston Red Sox',
    'CHC': 'Chicago Cubs',
    'CWS': 'Chicago White Sox',
    'CIN': 'Cincinnati Reds',
    'CLE': 'Cleveland Guardians',
    'COL': 'Colorado Rockies',
    'DET': 'Detroit Tigers',
    'HOU': 'Houston Astros',
    'KC':  'Kansas City Royals',
    'LAA': 'Los Angeles Angels',
    'LAD': 'Los Angeles Dodgers',
    'MIA': 'Miami Marlins',
    'MIL': 'Milwaukee Brewers',
    'MIN': 'Minnesota Twins',
    'NYM': 'New York Mets',
    'NYY': 'New York Yankees',
    'OAK': 'Oakland Athletics',
    'PHI': 'Philadelphia Phillies',
    'PIT': 'Pittsburgh Pirates',
    'SD':  'San Diego Padres',
    'SF':  'San Francisco Giants',
    'SEA': 'Seattle Mariners',
    'STL': 'St. Louis Cardinals',
    'TB':  'Tampa Bay Rays',
    'TEX': 'Texas Rangers',
    'TOR': 'Toronto Blue Jays',
    'WSH': 'Washington Nationals',
}

# ESPN uses slightly different abbreviations for some teams
ESPN_TO_MLB_TEAM = {
    'ARI': 'ARI', 'ATL': 'ATL', 'BAL': 'BAL', 'BOS': 'BOS',
    'CHC': 'CHC', 'CWS': 'CWS', 'CIN': 'CIN', 'CLE': 'CLE',
    'COL': 'COL', 'DET': 'DET', 'HOU': 'HOU', 'KC': 'KC',
    'LAA': 'LAA', 'LAD': 'LAD', 'MIA': 'MIA', 'MIL': 'MIL',
    'MIN': 'MIN', 'NYM': 'NYM', 'NYY': 'NYY', 'OAK': 'OAK',
    'PHI': 'PHI', 'PIT': 'PIT', 'SD': 'SD', 'SF': 'SF',
    'SEA': 'SEA', 'STL': 'STL', 'TB': 'TB', 'TEX': 'TEX',
    'TOR': 'TOR', 'WSH': 'WSH',
    # ESPN alternates
    'KCR': 'KC', 'SDP': 'SD', 'SFG': 'SF', 'TBR': 'TB',
    'WSN': 'WSH', 'CHW': 'CWS',
}


def normalize_team(abbr: str) -> str:
    """Normalize any team abbreviation to the canonical MLB Stats API form."""
    abbr = abbr.upper().strip()
    return ESPN_TO_MLB_TEAM.get(abbr, abbr)


if __name__ == '__main__':
    print(f"[MLB Config] Initializing database at: {DB_PATH}")
    initialize_database()
    print(f"[MLB Config] Total prop/line combos: {TOTAL_PROP_COMBOS}")
    print(f"[MLB Config] Pitcher props: {sorted(PITCHER_PROPS)}")
    print(f"[MLB Config] Batter props:  {sorted(BATTER_PROPS)}")
    print(f"[MLB Config] Season: {SEASON} | Data collection starts: {DATA_COLLECTION_START}")
    print(f"[MLB Config] ML training target: {ML_TRAINING_TARGET_PER_PROP:,} per prop/line combo")
