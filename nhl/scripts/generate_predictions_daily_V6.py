"""
Generate Daily Predictions - V6 PrizePicks Line Driven Edition
================================================================

CHANGES IN V6 (Jan 2026):
- Predictions generated ONLY for actual PrizePicks lines
- Fetches PP lines first, then generates predictions for those exact lines
- No more fixed lines (O1.5, O2.5, etc.) - uses what PP actually offers
- Ensures every prediction is immediately betable

This version:
1. Fetches fresh PrizePicks lines (if not already fetched today)
2. For each player in scheduled games, finds their PP lines
3. Generates predictions only for those available lines
4. Results in cleaner training data for ML

Based on V5 RELIABLE Edition with ML integration.
"""

import sys
import sqlite3
import subprocess
import shutil
import traceback
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add script directory and parent (for features) to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))  # For features module

from v2_config import DB_PATH, BLOWOUT_IMPLIED_PROB_THRESHOLD
from statistical_predictions_v2 import StatisticalPredictionEngine
from v2_discord_notifications import send_discord_notification
from espn_nhl_api import ESPNNHLApi

# ML Integration
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "ml_training"))
try:
    from production_predictor import ProductionPredictor
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("NOTE: ML predictor not available, using statistical only")

# PrizePicks Integration
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "shared"))
try:
    from prizepicks_client import PrizePicksIngestion, PrizePicksDatabase
    PP_AVAILABLE = True
except ImportError:
    PP_AVAILABLE = False
    print("WARNING: PrizePicks client not available")

# Pre-game intel (Grok-powered injury/availability/goalie sweep)
try:
    from pregame_intel import PreGameIntel
    INTEL_AVAILABLE = True
except ImportError:
    INTEL_AVAILABLE = False
    print("NOTE: pregame_intel not available — running without player filter")

# ============================================================================
# CONFIGURATION
# ============================================================================

# ML Configuration
USE_ML = False             # DISABLED 2026-04-15: audit confirmed models cause 100% UNDER bias
                           # Root cause: _prepare_features defaults non-prefixed features to 0.0
                           # because features_for_ml only stores f_* keys. sog_l10=0 -> z huge
                           # positive -> all UNDER. Re-enable after Oct 2026 retrain + audit.
ENSEMBLE_MODE = True       # True = combine ML+statistical, False = ML only when available
ML_WEIGHT = 0.6            # ML weight in ensemble (0.6 = 60% ML, 40% statistical)

# PrizePicks Configuration
PP_DB_PATH = Path(__file__).parent.parent.parent / "shared" / "prizepicks_lines.db"
SUPPORTED_PROPS = ['shots', 'points', 'hits', 'blocked_shots']  # Props we generate predictions for
ODDS_TYPES = ['standard', 'goblin', 'demon']  # Demon BE ~45% — quality-gated by σ<1.5 in selector

# Fallback lines if PP not available (should rarely be needed)
FALLBACK_SHOT_LINES = [1.5, 2.5, 3.5]
FALLBACK_POINTS_LINES = [0.5, 1.5]
FALLBACK_HITS_LINES = [0.5, 1.5, 2.5]
FALLBACK_BLOCKED_SHOTS_LINES = [0.5, 1.5]


# ============================================================================
# HYBRID PREDICTION ENGINE (Same as V5)
# ============================================================================

class HybridPredictionEngine:
    """Wrapper that uses ML when available, falls back to statistical."""

    def __init__(self, use_ml: bool = True, ensemble_mode: bool = True, ml_weight: float = 0.6):
        self.statistical_engine = StatisticalPredictionEngine(db_path=DB_PATH)
        self.use_ml = use_ml and ML_AVAILABLE
        self.ensemble_mode = ensemble_mode
        self.ml_weight = ml_weight

        if self.use_ml:
            registry_dir = Path(__file__).parent.parent.parent / "ml_training" / "model_registry"
            self.ml_predictor = ProductionPredictor(str(registry_dir))

            # Check which models are available
            available = []
            for prop in ['points', 'shots']:
                test_lines = FALLBACK_POINTS_LINES if prop == 'points' else FALLBACK_SHOT_LINES
                for line in test_lines:
                    if self.ml_predictor.is_model_available('nhl', prop, line):
                        available.append(f"{prop} O{line}")

            if available:
                print(f"[ML] Hybrid mode enabled: {len(available)} ML models loaded")
                print(f"     Models: {', '.join(available)}")
                print(f"     Ensemble: {ensemble_mode}, ML weight: {ml_weight:.0%}")
            else:
                print("[ML] No ML models found, using statistical only")
                self.use_ml = False
        else:
            self.ml_predictor = None
            print("[STAT] Using statistical predictions only")

    def predict_points(self, player, team, game_date, opponent, is_home, line):
        """Generate prediction, using ML if available"""
        use_ml_for_this = self.use_ml and self.ml_predictor.is_model_available('nhl', 'points', line)

        stat_pred = self.statistical_engine.predict_points(
            player, team, game_date, opponent, is_home, line,
            save=not use_ml_for_this
        )

        if stat_pred is None:
            return None

        if use_ml_for_this:
            features = stat_pred['features']

            if self.ensemble_mode:
                result = self.ml_predictor.predict_ensemble(
                    'nhl', 'points', line, features, stat_pred, self.ml_weight
                )
            else:
                result = self.ml_predictor.predict(
                    'nhl', 'points', line, features, stat_pred
                )

            result['game_date'] = stat_pred['game_date']
            result['player_name'] = stat_pred['player_name']
            result['team'] = stat_pred['team']
            result['opponent'] = stat_pred['opponent']
            result['prop_type'] = stat_pred['prop_type']
            result['line'] = stat_pred['line']
            result['prediction_batch_id'] = stat_pred['prediction_batch_id']
            result['created_at'] = stat_pred['created_at']

            self.statistical_engine._save_prediction(result)
            return result

        return stat_pred

    def predict_hits(self, player, team, game_date, opponent, is_home, lines):
        """Generate hits predictions (statistical only — no ML models yet). Returns list of dicts."""
        results = self.statistical_engine.predict_hits(
            player, team, game_date, opponent, is_home, lines=lines, save=True
        )
        return results or []

    def predict_blocked_shots(self, player, team, game_date, opponent, is_home, lines):
        """Generate blocked_shots predictions (statistical only — no ML models yet). Returns list of dicts."""
        results = self.statistical_engine.predict_blocked_shots(
            player, team, game_date, opponent, is_home, lines=lines, save=True
        )
        return results or []

    def predict_shots(self, player, team, game_date, opponent, is_home, line):
        """Generate prediction, using ML if available"""
        use_ml_for_this = self.use_ml and self.ml_predictor.is_model_available('nhl', 'shots', line)

        stat_pred = self.statistical_engine.predict_shots(
            player, team, game_date, opponent, is_home, line,
            save=not use_ml_for_this
        )

        if stat_pred is None:
            return None

        if use_ml_for_this:
            features = stat_pred['features']

            if self.ensemble_mode:
                result = self.ml_predictor.predict_ensemble(
                    'nhl', 'shots', line, features, stat_pred, self.ml_weight
                )
            else:
                result = self.ml_predictor.predict(
                    'nhl', 'shots', line, features, stat_pred
                )

            result['game_date'] = stat_pred['game_date']
            result['player_name'] = stat_pred['player_name']
            result['team'] = stat_pred['team']
            result['opponent'] = stat_pred['opponent']
            result['prop_type'] = stat_pred['prop_type']
            result['line'] = stat_pred['line']
            result['prediction_batch_id'] = stat_pred['prediction_batch_id']
            result['created_at'] = stat_pred['created_at']

            self.statistical_engine._save_prediction(result)
            return result

        return stat_pred


# ============================================================================
# PRIZEPICKS LINE FUNCTIONS
# ============================================================================

def ensure_pp_lines_fetched(target_date: str) -> bool:
    """
    Ensure PrizePicks lines are fetched for today.

    Returns:
        True if lines are available, False otherwise
    """
    if not PP_AVAILABLE:
        print("[WARN] PrizePicks client not available")
        return False

    conn = sqlite3.connect(PP_DB_PATH)
    cursor = conn.cursor()

    # Check if we have lines for today
    cursor.execute('''
        SELECT COUNT(*) FROM prizepicks_lines
        WHERE fetch_date = ? AND league = 'NHL'
    ''', (target_date,))
    count = cursor.fetchone()[0]
    conn.close()

    if count > 0:
        print(f"[PP] Found {count} existing NHL lines for {target_date}")
        return True

    # Fetch fresh lines
    print(f"[PP] No lines found for {target_date}, fetching fresh...")
    try:
        ingestion = PrizePicksIngestion()
        result = ingestion.run_ingestion(['NHL'])

        lines_fetched = result.get('sports', {}).get('NHL', {}).get('lines_fetched', 0)
        print(f"[PP] Fetched {lines_fetched} NHL lines")
        return lines_fetched > 0
    except Exception as e:
        print(f"[PP] Error fetching lines: {e}")
        return False


def get_pp_lines_for_player(player_name: str, prop_type: str, target_date: str) -> list[float]:
    """
    Get PrizePicks lines available for a specific player and prop.

    Uses fuzzy matching on last name to handle name format differences.

    Args:
        player_name: Player name (our format, e.g., "K. Kaprizov")
        prop_type: 'points' or 'shots'
        target_date: Date in YYYY-MM-DD format

    Returns:
        List of available lines (e.g., [1.5, 2.5, 3.5])
    """
    if not PP_AVAILABLE:
        return []

    conn = sqlite3.connect(PP_DB_PATH)
    cursor = conn.cursor()

    # Extract last name for fuzzy matching
    last_name = player_name.split()[-1]

    # Query for lines matching this player/prop
    placeholders = ','.join(['?' for _ in ODDS_TYPES])
    cursor.execute(f'''
        SELECT DISTINCT line
        FROM prizepicks_lines
        WHERE fetch_date = ?
        AND league = 'NHL'
        AND player_name LIKE ?
        AND prop_type = ?
        AND odds_type IN ({placeholders})
        ORDER BY line
    ''', (target_date, f'%{last_name}%', prop_type, *ODDS_TYPES))

    lines = [row[0] for row in cursor.fetchall()]
    conn.close()

    return lines


def get_all_pp_player_lines(target_date: str) -> dict:
    """
    Get all PrizePicks lines for NHL, organized by player.

    Returns:
        Dict: {player_name: {'points': [0.5, 1.5], 'shots': [2.5, 3.5]}}
    """
    if not PP_AVAILABLE:
        return {}

    conn = sqlite3.connect(PP_DB_PATH)
    cursor = conn.cursor()

    placeholders = ','.join(['?' for _ in ODDS_TYPES])
    cursor.execute(f'''
        SELECT player_name, prop_type, line
        FROM prizepicks_lines
        WHERE fetch_date = ?
        AND league = 'NHL'
        AND prop_type IN ('points', 'shots', 'hits', 'blocked_shots')
        AND odds_type IN ({placeholders})
        ORDER BY player_name, prop_type, line
    ''', (target_date, *ODDS_TYPES))

    # Organize by player
    player_lines = {}
    for row in cursor.fetchall():
        player, prop, line = row
        if player not in player_lines:
            player_lines[player] = {'points': [], 'shots': [], 'hits': [], 'blocked_shots': []}
        if prop in player_lines[player]:
            player_lines[player][prop].append(line)

    conn.close()
    return player_lines


# ============================================================================
# RELIABILITY UTILITIES (Same as V5)
# ============================================================================

def backup_database() -> Path:
    """Create timestamped backup of database before any writes"""
    db_path = Path(DB_PATH)
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"nhl_predictions_v2_predict_{timestamp}.db"

    shutil.copy2(db_path, backup_path)
    print(f'[BACKUP] Database backed up: {backup_path}')

    # Keep last 30 days only
    for old_backup in sorted(backup_dir.glob("*.db"))[:-30]:
        old_backup.unlink()

    return backup_path


def log_error(error_text: str, error_type: str = "ERROR"):
    """Log errors to file for debugging"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / f"prediction_errors_{datetime.now().strftime('%Y%m%d')}.log"

    with open(log_file, 'a') as f:
        f.write(f"\n{'='*80}\n")
        f.write(f"[{error_type}] {datetime.now().isoformat()}\n")
        f.write(error_text)
        f.write(f"\n{'='*80}\n")


# ============================================================================
# DATABASE HELPERS
# ============================================================================

def check_predictions_exist(target_date: str) -> tuple[bool, int]:
    """Check if predictions already exist for target date"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM predictions WHERE game_date = ?', (target_date,))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0, count


def delete_existing_predictions(target_date: str) -> int:
    """Delete existing predictions for target date"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM predictions WHERE game_date = ?', (target_date,))
    count = cursor.fetchone()[0]
    cursor.execute('DELETE FROM predictions WHERE game_date = ?', (target_date,))
    conn.commit()
    conn.close()
    return count


def check_games_exist(target_date: str) -> tuple[bool, int]:
    """Check if games exist in database for target date"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM games WHERE game_date = ?', (target_date,))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0, count


def fetch_game_schedule(target_date: str) -> bool:
    """Call fetch_game_schedule_FINAL.py to populate games"""
    print()
    print("=" * 80)
    print(f"AUTO-FETCHING GAME SCHEDULE FOR {target_date}")
    print("=" * 80)
    print()

    max_retries = 2

    for attempt in range(max_retries):
        try:
            schedule_script = SCRIPT_DIR / 'fetch_game_schedule_FINAL.py'
            result = subprocess.run(
                [sys.executable, str(schedule_script), target_date],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(SCRIPT_DIR)
            )

            if result.returncode == 0:
                print("[OK] Game schedule fetched successfully!")
                print()
                return True
            else:
                print(f"[WARN] Attempt {attempt+1} failed: {result.stderr[:200]}")
                if attempt < max_retries - 1:
                    time.sleep(2)

        except subprocess.TimeoutExpired:
            print(f"[WARN] Attempt {attempt+1} timed out")
            if attempt < max_retries - 1:
                time.sleep(2)

        except Exception as e:
            print(f"[ERROR] Error fetching game schedule: {e}")
            log_error(traceback.format_exc(), "SCHEDULE_FETCH_ERROR")
            print()
            return False

    return False


def get_players_with_history_for_team(team: str, game_date: str, min_games: int = 5, top_n: int = 12) -> list[str]:
    """
    Get players who have game log history for a team.

    Only includes players whose MOST RECENT game (before game_date) was for this team.
    This filters out traded players who still have historical logs for old teams.
    (e.g. Q. Hughes traded VAN→MIN — won't appear in VAN queries after trade date)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        WITH current_teams AS (
            SELECT player_name, team AS current_team
            FROM (
                SELECT player_name, team,
                       ROW_NUMBER() OVER (PARTITION BY player_name ORDER BY game_date DESC) AS rn
                FROM player_game_logs
                WHERE game_date < ?
            ) ranked
            WHERE rn = 1
        )
        SELECT pgl.player_name, COUNT(*) AS games,
               SUM(pgl.points) * 1.0 / COUNT(*) AS ppg
        FROM player_game_logs pgl
        JOIN current_teams ct ON pgl.player_name = ct.player_name
            AND ct.current_team = ?
        WHERE pgl.team = ?
          AND pgl.game_date < ?
        GROUP BY pgl.player_name
        HAVING games >= ?
        ORDER BY ppg DESC
        LIMIT ?
    ''', (game_date, team, team, game_date, min_games, top_n))

    players = [row[0] for row in cursor.fetchall()]
    conn.close()

    return players


def determine_phase(current_date: str) -> tuple[str, int]:
    """Determine which collection phase we're in"""
    exploration_end = datetime(2025, 11, 19)
    current = datetime.strptime(current_date, '%Y-%m-%d')

    if current <= exploration_end:
        return "EXPLORATION", 12
    else:
        return "EXPLOITATION", 8


def match_player_to_pp(player_name: str, pp_player_lines: dict) -> str | None:
    """
    Match our player name to PrizePicks player name using fuzzy matching.

    Args:
        player_name: Our format (e.g., "K. Kaprizov")
        pp_player_lines: Dict from get_all_pp_player_lines

    Returns:
        PP player name if found, None otherwise
    """
    # Extract last name
    last_name = player_name.split()[-1].lower()

    for pp_name in pp_player_lines.keys():
        if last_name in pp_name.lower():
            return pp_name

    return None


# ============================================================================
# NHL ODDS FETCH (ESPN)
# ============================================================================

# ESPN uses different abbreviations than the NHL API in some cases
_ESPN_NHL_ALIASES = {
    'TB': 'TBL', 'TBL': 'TB',
    'SJ': 'SJS', 'SJS': 'SJ',
    'NJ': 'NJD', 'NJD': 'NJ',
    'LA': 'LAK', 'LAK': 'LA',
    'CBJ': 'CBJ',
}


def _fetch_and_save_nhl_game_lines(conn, game_date: str, games: list) -> dict:
    """
    Fetch betting lines from ESPN NHL scoreboard and save to game_lines table.

    Args:
        conn: Open SQLite connection to nhl_predictions_v2.db
        game_date: 'YYYY-MM-DD'
        games: list of (game_date, away_team, home_team, game_id) tuples from DB

    Returns:
        {game_id: {'max_implied_prob': float, 'spread': float, ...}}
        Only entries where odds were available are included.
    """
    result = {}
    try:
        espn = ESPNNHLApi()
        espn_games = espn.get_scoreboard(game_date)
    except Exception as e:
        print(f"   [ODDS] ESPN NHL fetch failed: {e} — skipping lines")
        return result

    if not espn_games:
        print("   [ODDS] No ESPN NHL games returned — lines unavailable")
        return result

    # Build lookup: (home_abbr, away_abbr) -> game_id from DB
    db_lookup = {}
    for _, away, home, gid in games:
        db_lookup[(home.upper(), away.upper())] = gid

    cursor = conn.cursor()
    lines_saved = 0

    for eg in espn_games:
        espn_home = eg['home_team']
        espn_away = eg['away_team']

        # Try direct match, then alias resolution
        game_id = db_lookup.get((espn_home, espn_away))
        if not game_id:
            h = _ESPN_NHL_ALIASES.get(espn_home, espn_home)
            a = _ESPN_NHL_ALIASES.get(espn_away, espn_away)
            game_id = (db_lookup.get((h, a)) or db_lookup.get((espn_home, a))
                       or db_lookup.get((h, espn_away)))

        if not game_id:
            continue

        cursor.execute("""
            INSERT OR REPLACE INTO game_lines
            (game_id, game_date, home_team, away_team,
             spread, over_under, home_moneyline, away_moneyline,
             home_implied_prob, away_implied_prob, max_implied_prob,
             over_odds, under_odds, home_spread_odds, away_spread_odds,
             odds_details, odds_provider, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            game_id, game_date, espn_home, espn_away,
            eg.get('spread'), eg.get('over_under'),
            eg.get('home_moneyline'), eg.get('away_moneyline'),
            eg.get('home_implied_prob'), eg.get('away_implied_prob'),
            eg.get('max_implied_prob'),
            eg.get('over_odds'), eg.get('under_odds'),
            eg.get('home_spread_odds'), eg.get('away_spread_odds'),
            eg.get('odds_details', ''), eg.get('odds_provider', ''),
            datetime.now().isoformat()
        ))

        if eg.get('max_implied_prob') is not None:
            result[game_id] = {
                'max_implied_prob': eg['max_implied_prob'],
                'spread': eg.get('spread'),
                'over_under': eg.get('over_under'),
                'home_moneyline': eg.get('home_moneyline'),
                'away_moneyline': eg.get('away_moneyline'),
            }
            lines_saved += 1

    conn.commit()
    unmatched = len(espn_games) - lines_saved
    print(f"   [ODDS] Saved NHL lines for {lines_saved}/{len(espn_games)} games"
          + (f" ({unmatched} unmatched)" if unmatched else ""))
    return result


# ============================================================================
# MAIN PREDICTION GENERATION
# ============================================================================

def generate_predictions_for_date(target_date: str, force: bool = False) -> int:
    """
    Generate predictions for all games on target date using PrizePicks lines.

    V6: Now generates predictions ONLY for actual PrizePicks lines.

    Args:
        target_date: Date in YYYY-MM-DD format
        force: If True, delete existing predictions and regenerate

    Returns:
        Number of predictions generated
    """
    # Determine phase
    phase, players_per_team = determine_phase(target_date)

    print('=' * 80)
    print(f'V6: GENERATING PREDICTIONS FOR {target_date}')
    print(f'Phase: {phase} (Top {players_per_team} players per team)')
    print('=' * 80)
    print()

    print('MODE: PrizePicks Line Driven')
    print('Only generating predictions for ACTUAL PrizePicks lines')
    print()

    # Check if predictions already exist
    preds_exist, pred_count = check_predictions_exist(target_date)

    if preds_exist and not force:
        print(f'[SKIP] Predictions already exist for {target_date} ({pred_count} predictions)')
        print('       Use --force flag to regenerate')
        print()
        return 0

    if preds_exist and force:
        deleted = delete_existing_predictions(target_date)
        print(f'[DELETE] Deleted {deleted} existing predictions (--force flag used)')
        print()

    # STEP 1: Ensure PrizePicks lines are fetched
    print("STEP 1: Checking PrizePicks lines...")
    pp_available = ensure_pp_lines_fetched(target_date)

    if not pp_available:
        print("[WARN] PrizePicks lines not available, falling back to fixed lines")
        use_pp_lines = False
    else:
        use_pp_lines = True
        # Get all PP lines organized by player
        pp_player_lines = get_all_pp_player_lines(target_date)
        print(f"[PP] Found lines for {len(pp_player_lines)} NHL players")
    print()

    # STEP 2: Check if games exist in database
    print("STEP 2: Checking game schedule...")
    games_exist, game_count = check_games_exist(target_date)

    if not games_exist:
        print(f'[INFO] No games found in database for {target_date}')
        print('       Attempting to fetch game schedule...')

        if fetch_game_schedule(target_date):
            games_exist, game_count = check_games_exist(target_date)

            if not games_exist:
                print(f'[WARN] Still no games found after fetching schedule')
                print(f'       NHL may not have any games scheduled for {target_date}')
                print()
                return 0
        else:
            print('[ERROR] Failed to fetch game schedule')
            print()
            return 0

    print(f'Found {game_count} games scheduled for {target_date}')
    print()

    # Get games from database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Ensure game_lines table exists (created once, safe to repeat)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_lines (
            game_id          TEXT NOT NULL,
            game_date        TEXT NOT NULL,
            home_team        TEXT,
            away_team        TEXT,
            spread           REAL,          -- puck line (typically +/-1.5)
            over_under       REAL,          -- game total
            home_moneyline   INTEGER,
            away_moneyline   INTEGER,
            home_implied_prob REAL,         -- implied win probability (0.0-1.0)
            away_implied_prob REAL,
            max_implied_prob  REAL,         -- max(home, away) — used for blowout filter
            over_odds        INTEGER,       -- over price (e.g. -142)
            under_odds       INTEGER,       -- under price (e.g. 120)
            home_spread_odds INTEGER,       -- home covering spread price
            away_spread_odds INTEGER,       -- away covering spread price
            odds_details     TEXT,
            odds_provider    TEXT,
            fetched_at       TEXT,
            PRIMARY KEY (game_id)
        )
    """)
    # Add new columns for existing databases
    for col, typ in [("over_odds", "INTEGER"), ("under_odds", "INTEGER"),
                     ("home_spread_odds", "INTEGER"), ("away_spread_odds", "INTEGER")]:
        try:
            cursor.execute(f"ALTER TABLE game_lines ADD COLUMN {col} {typ}")
        except Exception:
            pass  # Column already exists
    conn.commit()

    cursor.execute('''
        SELECT game_date, away_team, home_team, game_id
        FROM games
        WHERE game_date = ?
    ''', (target_date,))
    games = cursor.fetchall()

    # Fetch ESPN odds and save to game_lines
    game_lines = _fetch_and_save_nhl_game_lines(conn, target_date, games)

    conn.close()

    # Initialize prediction engine
    engine = HybridPredictionEngine(
        use_ml=USE_ML,
        ensemble_mode=ENSEMBLE_MODE,
        ml_weight=ML_WEIGHT
    )

    # Pre-game intel: fetch injury/availability/goalie confirmations from Grok
    intel = PreGameIntel() if INTEL_AVAILABLE else None
    if intel:
        matchups = [f'{away} vs {home}' for _, away, home, _ in games]
        intel.fetch('nhl', target_date, matchups)

    # Track predictions
    total_predictions = 0
    pp_matched_players = 0
    pp_unmatched_players = 0
    predictions_by_prop = {'points': 0, 'shots': 0, 'hits': 0, 'blocked_shots': 0}
    predictions_by_line = {}
    skipped_blowouts = 0
    skipped_intel = 0

    print('STEP 3: Generating predictions...')
    print()

    for game_date, away_team, home_team, game_id in games:
        # Blowout filter: skip if favorite's implied win probability is too high.
        # Uses moneyline-based implied probability (not spread — puck line doesn't vary).
        max_prob = game_lines.get(game_id, {}).get('max_implied_prob')
        if max_prob is not None and max_prob >= BLOWOUT_IMPLIED_PROB_THRESHOLD:
            print(f"[SKIP] {away_team} @ {home_team} — blowout risk "
                  f"(implied prob {max_prob:.0%} >= {BLOWOUT_IMPLIED_PROB_THRESHOLD:.0%}). Skipping.")
            skipped_blowouts += 1
            continue
        for team, opponent, is_home in [(away_team, home_team, False), (home_team, away_team, True)]:
            players = get_players_with_history_for_team(team, game_date, min_games=5, top_n=players_per_team)

            if not players:
                print(f"{team}: No players with sufficient history (skipping)")
                continue

            print(f"{team}: {len(players)} players with history")

            for player in players:
                # Intel filter: skip confirmed OUT / scratched players
                if intel and intel.is_player_out(player, 'nhl', game_date):
                    print(f'  [INTEL] {player} — OUT / scratched (skipping)')
                    skipped_intel += 1
                    continue

                # Find PP lines for this player
                if use_pp_lines:
                    pp_name = match_player_to_pp(player, pp_player_lines)

                    if pp_name:
                        pp_matched_players += 1
                        player_pp_lines = pp_player_lines[pp_name]
                    else:
                        pp_unmatched_players += 1
                        # Fall back to standard lines for unmatched players
                        player_pp_lines = {
                            'points': FALLBACK_POINTS_LINES,
                            'shots': FALLBACK_SHOT_LINES,
                            'hits': FALLBACK_HITS_LINES,
                            'blocked_shots': FALLBACK_BLOCKED_SHOTS_LINES,
                        }
                else:
                    player_pp_lines = {
                        'points': FALLBACK_POINTS_LINES,
                        'shots': FALLBACK_SHOT_LINES,
                        'hits': FALLBACK_HITS_LINES,
                        'blocked_shots': FALLBACK_BLOCKED_SHOTS_LINES,
                    }

                # Generate predictions for POINTS
                for line in player_pp_lines.get('points', []):
                    pred = engine.predict_points(
                        player, team, game_date, opponent,
                        is_home=is_home,
                        line=line
                    )
                    if pred:
                        total_predictions += 1
                        predictions_by_prop['points'] += 1
                        key = f"points_O{line}"
                        predictions_by_line[key] = predictions_by_line.get(key, 0) + 1

                # Generate predictions for SHOTS
                for line in player_pp_lines.get('shots', []):
                    pred = engine.predict_shots(
                        player, team, game_date, opponent,
                        is_home=is_home,
                        line=line
                    )
                    if pred:
                        total_predictions += 1
                        predictions_by_prop['shots'] += 1
                        key = f"shots_O{line}"
                        predictions_by_line[key] = predictions_by_line.get(key, 0) + 1

                # Generate predictions for HITS (returns list)
                hits_lines = player_pp_lines.get('hits', [])
                if hits_lines:
                    preds = engine.predict_hits(
                        player, team, game_date, opponent,
                        is_home=is_home,
                        lines=hits_lines
                    )
                    for pred in preds:
                        if pred:
                            total_predictions += 1
                            predictions_by_prop['hits'] += 1
                            key = f"hits_O{pred.get('line', '?')}"
                            predictions_by_line[key] = predictions_by_line.get(key, 0) + 1

                # Generate predictions for BLOCKED SHOTS (returns list)
                blocked_lines = player_pp_lines.get('blocked_shots', [])
                if blocked_lines:
                    preds = engine.predict_blocked_shots(
                        player, team, game_date, opponent,
                        is_home=is_home,
                        lines=blocked_lines
                    )
                    for pred in preds:
                        if pred:
                            total_predictions += 1
                            predictions_by_prop['blocked_shots'] += 1
                            key = f"blocked_shots_O{pred.get('line', '?')}"
                            predictions_by_line[key] = predictions_by_line.get(key, 0) + 1

        print()

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print()
    print('=' * 80)
    print(f'V6: GENERATED {total_predictions} PREDICTIONS')
    print('=' * 80)
    print()

    if skipped_blowouts:
        print(f'[SKIP] Blowout games skipped: {skipped_blowouts} '
              f'(implied prob >= {BLOWOUT_IMPLIED_PROB_THRESHOLD:.0%})')
        print()
    if skipped_intel:
        print(f'[INTEL] Players skipped (OUT/scratched): {skipped_intel}')
        print()

    if use_pp_lines:
        print('PRIZEPICKS MATCHING:')
        print(f'  Players matched to PP: {pp_matched_players}')
        print(f'  Players unmatched (fallback): {pp_unmatched_players}')
        print()

    print('BREAKDOWN BY PROP:')
    for prop, count in predictions_by_prop.items():
        print(f'  {prop.title()}: {count}')
    print()

    print('BREAKDOWN BY LINE:')
    for line_key in sorted(predictions_by_line.keys()):
        print(f'  {line_key}: {predictions_by_line[line_key]}')
    print()

    return total_predictions


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point with argument handling"""
    import argparse

    parser = argparse.ArgumentParser(
        description='V6: Generate NHL predictions from PrizePicks lines'
    )
    parser.add_argument(
        'date',
        nargs='?',
        default=datetime.now().strftime('%Y-%m-%d'),
        help='Target date (YYYY-MM-DD). Default: today'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force regeneration even if predictions exist'
    )

    args = parser.parse_args()

    print()
    print('=' * 80)
    print('NHL PREDICTION GENERATOR V6 - PrizePicks Line Driven')
    print('=' * 80)
    print()

    # Create backup before any writes
    try:
        backup_database()
    except Exception as e:
        print(f"[WARN] Could not create backup: {e}")

    # Generate predictions
    try:
        count = generate_predictions_for_date(args.date, force=args.force)

        if count > 0:
            print(f'[SUCCESS] Generated {count} predictions for {args.date}')
            sys.exit(0)
        else:
            # Distinguish legitimate skips from real failures
            preds_exist, _ = check_predictions_exist(args.date)
            games_exist, _ = check_games_exist(args.date)
            if preds_exist or not games_exist:
                # Off day or already existed — legitimate skip
                print(f'[INFO] No new predictions generated for {args.date} (off day or already exists)')
                sys.exit(0)
            else:
                # Games exist but 0 predictions — something went wrong
                print(f'[ERROR] 0 predictions generated despite {args.date} having games', file=sys.stderr)
                sys.exit(1)

    except Exception as e:
        print(f'[ERROR] Fatal error: {e}')
        log_error(traceback.format_exc(), "FATAL_ERROR")

        # Send Discord alert
        try:
            send_discord_notification(
                f"NHL V6 Prediction Generation FAILED for {args.date}: {str(e)[:200]}",
                "error"
            )
        except:
            pass

        sys.exit(1)


if __name__ == '__main__':
    main()
