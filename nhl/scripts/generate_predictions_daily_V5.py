"""
Generate Daily Predictions - V5 RELIABLE Edition with Multi-Line Points
========================================================================

RELIABILITY ENHANCEMENTS:
✅ Automated database backups before any writes
✅ Better error handling with Discord alerts
✅ Comprehensive error logging
✅ Result verification after generation
✅ Retry logic for subprocess calls

CHANGES IN V5 (Nov 19, 2025):
- Added support for multiple points lines: O0.5, O1.5
- Shots remain: O1.5, O2.5, O3.5 (unchanged from V4)
- Same features used for all points lines (binary classification)
- Enhanced for Underdog Fantasy platform (UNDERs available)

CHANGES IN V4 (Nov 10, 2025):
- Added support for multiple shot lines: O1.5, O2.5, O3.5
- Points were at O0.5 only
- Same features used for all shot lines (distribution-based approach)

This version generates:
- 2 predictions per player for points (O0.5, O1.5)
- 3 predictions per player for shots (O1.5, O2.5, O3.5)
- Total: 5 predictions per player (up from 4)
"""

import sys
import sqlite3
import subprocess
import shutil
import traceback
import time
from datetime import datetime, timedelta
from pathlib import Path
from v2_config import DB_PATH
from statistical_predictions_v2 import StatisticalPredictionEngine
from v2_discord_notifications import send_discord_notification

# ML Integration
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "ml_training"))
try:
    from production_predictor import ProductionPredictor
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("NOTE: ML predictor not available, using statistical only")

# ============================================================================
# CONFIGURATION
# ============================================================================

# Shot lines to predict (V4)
SHOT_LINES = [1.5, 2.5, 3.5]

# Points lines to predict (V5 - added O1.5 for Underdog platform)
POINTS_LINES = [0.5, 1.5]

# ML Configuration
USE_ML = True              # Set to False to disable ML predictions
ENSEMBLE_MODE = True       # True = combine ML+statistical, False = ML only when available
ML_WEIGHT = 0.6            # ML weight in ensemble (0.6 = 60% ML, 40% statistical)


# ============================================================================
# HYBRID PREDICTION ENGINE
# ============================================================================

class HybridPredictionEngine:
    """
    Wrapper that uses ML when available, falls back to statistical.

    Modes:
    - ensemble_mode=True: Combine ML (60%) + Statistical (40%)
    - ensemble_mode=False: Use ML only when available, else statistical
    """

    def __init__(self, use_ml: bool = True, ensemble_mode: bool = True, ml_weight: float = 0.6):
        self.statistical_engine = StatisticalPredictionEngine()
        self.use_ml = use_ml and ML_AVAILABLE
        self.ensemble_mode = ensemble_mode
        self.ml_weight = ml_weight

        if self.use_ml:
            registry_dir = Path(__file__).parent.parent.parent / "ml_training" / "model_registry"
            self.ml_predictor = ProductionPredictor(str(registry_dir))

            # Check which models are available
            available = []
            for prop in ['points', 'shots']:
                lines = POINTS_LINES if prop == 'points' else SHOT_LINES
                for line in lines:
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
        # Check if ML is available for this prop/line
        use_ml_for_this = self.use_ml and self.ml_predictor.is_model_available('nhl', 'points', line)

        # Get statistical prediction (don't save if we'll use ML)
        stat_pred = self.statistical_engine.predict_points(
            player, team, game_date, opponent, is_home, line,
            save=not use_ml_for_this  # Only save if not using ML
        )

        if stat_pred is None:
            return None

        # Apply ML if available
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

            # Copy required fields from stat_pred for database save
            result['game_date'] = stat_pred['game_date']
            result['player_name'] = stat_pred['player_name']
            result['team'] = stat_pred['team']
            result['opponent'] = stat_pred['opponent']
            result['prop_type'] = stat_pred['prop_type']
            result['line'] = stat_pred['line']
            result['prediction_batch_id'] = stat_pred['prediction_batch_id']
            result['created_at'] = stat_pred['created_at']

            # Save ML/ensemble prediction to database
            self.statistical_engine._save_prediction(result)
            return result

        return stat_pred

    def predict_shots(self, player, team, game_date, opponent, is_home, line):
        """Generate prediction, using ML if available"""
        # Check if ML is available for this prop/line
        use_ml_for_this = self.use_ml and self.ml_predictor.is_model_available('nhl', 'shots', line)

        # Get statistical prediction (don't save if we'll use ML)
        stat_pred = self.statistical_engine.predict_shots(
            player, team, game_date, opponent, is_home, line,
            save=not use_ml_for_this  # Only save if not using ML
        )

        if stat_pred is None:
            return None

        # Apply ML if available
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

            # Copy required fields from stat_pred for database save
            result['game_date'] = stat_pred['game_date']
            result['player_name'] = stat_pred['player_name']
            result['team'] = stat_pred['team']
            result['opponent'] = stat_pred['opponent']
            result['prop_type'] = stat_pred['prop_type']
            result['line'] = stat_pred['line']
            result['prediction_batch_id'] = stat_pred['prediction_batch_id']
            result['created_at'] = stat_pred['created_at']

            # Save ML/ensemble prediction to database
            self.statistical_engine._save_prediction(result)
            return result

        return stat_pred


# ============================================================================
# RELIABILITY UTILITIES
# ============================================================================

def backup_database() -> Path:
    """
    Create timestamped backup of database before any writes
    
    Returns:
        Path to backup file
    """
    db_path = Path(DB_PATH)
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"nhl_predictions_v2_predict_{timestamp}.db"
    
    shutil.copy2(db_path, backup_path)
    print(f'[BACKUP] Database backed up: {backup_path}')
    
    # Keep last 30 days only (cleanup old backups)
    for old_backup in sorted(backup_dir.glob("*.db"))[:-30]:
        old_backup.unlink()
    
    return backup_path


def log_error(error_text: str, error_type: str = "ERROR"):
    """
    Log errors to file for debugging
    
    Args:
        error_text: Full error traceback
        error_type: Type of error (ERROR, WARNING, etc.)
    """
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
    """
    Check if predictions already exist for target date
    
    Args:
        target_date: Date in YYYY-MM-DD format
        
    Returns:
        Tuple of (predictions_exist, prediction_count)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM predictions WHERE game_date = ?', (target_date,))
    count = cursor.fetchone()[0]
    conn.close()
    
    return count > 0, count


def delete_existing_predictions(target_date: str) -> int:
    """
    Delete existing predictions for target date
    
    Args:
        target_date: Date in YYYY-MM-DD format
        
    Returns:
        Number of predictions deleted
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Count before deleting
    cursor.execute('SELECT COUNT(*) FROM predictions WHERE game_date = ?', (target_date,))
    count = cursor.fetchone()[0]
    
    # Delete
    cursor.execute('DELETE FROM predictions WHERE game_date = ?', (target_date,))
    conn.commit()
    conn.close()
    
    return count


def check_games_exist(target_date: str) -> tuple[bool, int]:
    """
    Check if games exist in database for target date
    
    Args:
        target_date: Date in YYYY-MM-DD format
        
    Returns:
        Tuple of (games_exist, game_count)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM games WHERE game_date = ?', (target_date,))
    count = cursor.fetchone()[0]
    conn.close()
    
    return count > 0, count


def fetch_game_schedule(target_date: str) -> bool:
    """
    Call fetch_game_schedule_FINAL.py to populate games
    
    RELIABILITY: Now includes retry logic
    
    Args:
        target_date: Date in YYYY-MM-DD format
        
    Returns:
        True if successful, False otherwise
    """
    print()
    print("=" * 80)
    print(f"AUTO-FETCHING GAME SCHEDULE FOR {target_date}")
    print("=" * 80)
    print()
    
    max_retries = 2
    
    for attempt in range(max_retries):
        try:
            # Run fetch_game_schedule_FINAL.py
            result = subprocess.run(
                [sys.executable, 'fetch_game_schedule_FINAL.py', target_date],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                print("[OK] Game schedule fetched successfully!")
                print()
                return True
            else:
                if attempt < max_retries - 1:
                    print(f"[RETRY] Warning: Game schedule fetch returned code {result.returncode}, retrying...")
                    time.sleep(10)
                    continue
                else:
                    print(f"[WARN] Warning: Game schedule fetch returned code {result.returncode}")
                    if result.stdout:
                        print("Output:", result.stdout[-500:])
                    if result.stderr:
                        print("Errors:", result.stderr[-500:])
                    print()
                    return False
                
        except subprocess.TimeoutExpired:
            if attempt < max_retries - 1:
                print(f"[RETRY] Timeout, retrying...")
                continue
            else:
                print("[ERROR] Error: Game schedule fetch timed out")
                print()
                return False
                
        except FileNotFoundError:
            print("[ERROR] Error: fetch_game_schedule_FINAL.py not found")
            print("   Make sure it's in the same directory")
            print()
            return False
            
        except Exception as e:
            print(f"[ERROR] Error fetching game schedule: {e}")
            log_error(traceback.format_exc(), "SCHEDULE_FETCH_ERROR")
            print()
            return False
    
    return False


def get_players_with_history_for_team(team: str, min_games: int = 5, top_n: int = 12) -> list[str]:
    """
    Get players who have game log history for a team
    
    Args:
        team: Team abbreviation
        min_games: Minimum games required in history
        top_n: Number of top players to return (12 for exploration, 8 for exploitation)
        
    Returns:
        List of player names with sufficient history
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT player_name, COUNT(*) as games, 
               SUM(points) * 1.0 / COUNT(*) as ppg
        FROM player_game_logs
        WHERE team = ?
        GROUP BY player_name
        HAVING games >= ?
        ORDER BY ppg DESC
        LIMIT ?
    ''', (team, min_games, top_n))
    
    players = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    return players


def determine_phase(current_date: str) -> tuple[str, int]:
    """
    Determine which collection phase we're in
    
    Args:
        current_date: Current date string YYYY-MM-DD
        
    Returns:
        Tuple of (phase_name, players_per_team)
    """
    # Exploration: Nov 7 - Nov 19 (top 12 players per team)
    # Exploitation: Nov 20 - Jan 5 (top 8 players per team)
    
    exploration_end = datetime(2025, 11, 19)
    current = datetime.strptime(current_date, '%Y-%m-%d')
    
    if current <= exploration_end:
        return "EXPLORATION", 12
    else:
        return "EXPLOITATION", 8


# ============================================================================
# MAIN PREDICTION GENERATION
# ============================================================================

def generate_predictions_for_date(target_date: str, force: bool = False) -> int:
    """
    Generate predictions for all games on target date
    
    UPDATED IN V4: Now generates multiple shot lines per player
    
    Args:
        target_date: Date in YYYY-MM-DD format
        force: If True, delete existing predictions and regenerate
        
    Returns:
        Number of predictions generated
    """
    # Determine phase
    phase, players_per_team = determine_phase(target_date)
    
    print('=' * 80)
    print(f'GENERATING PREDICTIONS FOR {target_date}')
    print(f'Phase: {phase} (Top {players_per_team} players per team)') 
    print('=' * 80)
    print()
    
    # NEW IN V5: Show what lines we're predicting
    print('PREDICTION LINES:')
    print(f'  Points: O{", O".join(map(str, POINTS_LINES))}')
    print(f'  Shots: O{", O".join(map(str, SHOT_LINES))}')
    print(f'  Total: {len(POINTS_LINES) + len(SHOT_LINES)} predictions per player')
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
    
    # Check if games exist in database
    games_exist, game_count = check_games_exist(target_date)
    
    if not games_exist:
        print(f'[INFO] No games found in database for {target_date}')
        print('       Attempting to fetch game schedule...')
        
        # Try to fetch game schedule
        if fetch_game_schedule(target_date):
            # Recheck after fetch
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
    cursor.execute('''
        SELECT game_date, away_team, home_team
        FROM games
        WHERE game_date = ?
    ''', (target_date,))
    games = cursor.fetchall()
    conn.close()
    
    # Initialize prediction engine (uses ML when available)
    engine = HybridPredictionEngine(
        use_ml=USE_ML,
        ensemble_mode=ENSEMBLE_MODE,
        ml_weight=ML_WEIGHT
    )
    
    # Track predictions
    total_predictions = 0
    points_predictions = {line: 0 for line in POINTS_LINES}
    shots_predictions = {line: 0 for line in SHOT_LINES}
    total_players_found = 0
    total_players_skipped = 0
    
    print('Generating predictions...')
    print()
    
    for game_date, away_team, home_team in games:
        # ====================================================================
        # AWAY TEAM PLAYERS
        # ====================================================================
        away_players = get_players_with_history_for_team(away_team, min_games=5, top_n=players_per_team)
        
        if away_players:
            print(f"{away_team}: {len(away_players)} players with history")
            total_players_found += len(away_players)
            
            for player in away_players:
                # 1. Points - MULTIPLE LINES (NEW IN V5)
                for line in POINTS_LINES:
                    pred = engine.predict_points(
                        player, away_team, game_date, home_team, 
                        is_home=False,
                        line=line
                    )
                    if pred:
                        total_predictions += 1
                        points_predictions[line] += 1
                
                # 2. Shots - MULTIPLE LINES (V4)
                for line in SHOT_LINES:
                    pred = engine.predict_shots(
                        player, away_team, game_date, home_team, 
                        is_home=False,
                        line=line
                    )
                    if pred:
                        total_predictions += 1
                        shots_predictions[line] += 1
        else:
            print(f"{away_team}: No players with sufficient history (skipping)")
            total_players_skipped += 1
        
        # ====================================================================
        # HOME TEAM PLAYERS
        # ====================================================================
        home_players = get_players_with_history_for_team(home_team, min_games=5, top_n=players_per_team)
        
        if home_players:
            print(f"{home_team}: {len(home_players)} players with history")
            total_players_found += len(home_players)
            
            for player in home_players:
                # 1. Points - MULTIPLE LINES (NEW IN V5)
                for line in POINTS_LINES:
                    pred = engine.predict_points(
                        player, home_team, game_date, away_team,
                        is_home=True,
                        line=line
                    )
                    if pred:
                        total_predictions += 1
                        points_predictions[line] += 1
                
                # 2. Shots - MULTIPLE LINES (V4)
                for line in SHOT_LINES:
                    pred = engine.predict_shots(
                        player, home_team, game_date, away_team,
                        is_home=True,
                        line=line
                    )
                    if pred:
                        total_predictions += 1
                        shots_predictions[line] += 1
        else:
            print(f"{home_team}: No players with sufficient history (skipping)")
            total_players_skipped += 1
        
        print()
    
    # ========================================================================
    # SUMMARY
    # ========================================================================
    print()
    print('=' * 80)
    print(f'GENERATED {total_predictions} PREDICTIONS')
    print('=' * 80)
    print()
    print(f'Players found: {total_players_found}')
    print(f'Teams skipped: {total_players_skipped}')
    print(f'Phase: {phase}')
    print()
    
    # NEW IN V5: Detailed breakdown by line
    print('BREAKDOWN BY LINE:')
    for line in POINTS_LINES:
        print(f'  Points O{line}: {points_predictions[line]}')
    for line in SHOT_LINES:
        print(f'  Shots O{line}: {shots_predictions[line]}')
    print()
    
    # Sanity check (UPDATED IN V5)
    expected = total_players_found * (len(POINTS_LINES) + len(SHOT_LINES))
    if total_predictions != expected:
        print(f'[WARN] Expected {expected} predictions but generated {total_predictions}')
        print('       Some predictions may have been skipped due to insufficient data')
        print()
    
    return total_predictions


# ============================================================================
# VERIFICATION
# ============================================================================

def verify_predictions(target_date: str) -> dict:
    """
    Verify predictions were saved correctly
    
    UPDATED IN V4: Now shows breakdown by prop_type and line
    
    Args:
        target_date: Date in YYYY-MM-DD format
        
    Returns:
        Dictionary with verification results
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Count predictions
    cursor.execute('SELECT COUNT(*) FROM predictions WHERE game_date = ?', (target_date,))
    count = cursor.fetchone()[0]
    
    # Get variety stats
    cursor.execute('''
        SELECT 
            COUNT(DISTINCT player_name) as unique_players,
            COUNT(DISTINCT ROUND(probability, 2)) as unique_probs,
            AVG(probability) as avg_prob,
            MIN(probability) as min_prob,
            MAX(probability) as max_prob,
            SUM(CASE WHEN prediction = 'OVER' THEN 1 ELSE 0 END) as over_count,
            SUM(CASE WHEN prediction = 'UNDER' THEN 1 ELSE 0 END) as under_count
        FROM predictions 
        WHERE game_date = ?
    ''', (target_date,))
    
    stats = cursor.fetchone()
    
    # NEW IN V4: Breakdown by prop_type and line
    cursor.execute('''
        SELECT prop_type, line, COUNT(*) as count
        FROM predictions
        WHERE game_date = ?
        GROUP BY prop_type, line
        ORDER BY prop_type, line
    ''', (target_date,))
    
    breakdown = cursor.fetchall()
    
    # Check for features_json (ML readiness)
    cursor.execute('''
        SELECT COUNT(*) FROM predictions
        WHERE game_date = ? AND features_json IS NOT NULL
    ''', (target_date,))
    
    with_features = cursor.fetchone()[0]
    
    conn.close()
    
    if stats:
        result = {
            'count': count,
            'unique_players': stats[0],
            'unique_probs': stats[1],
            'avg_prob': stats[2],
            'min_prob': stats[3],
            'max_prob': stats[4],
            'over_count': stats[5],
            'under_count': stats[6],
            'breakdown': breakdown,
            'with_features': with_features
        }
        return result
    else:
        return {'count': 0}


# ============================================================================
# MAIN WITH RELIABILITY WRAPPER
# ============================================================================

def safe_main():
    """
    Main execution wrapped with comprehensive error handling
    
    RELIABILITY: Catches all errors, logs them, and sends Discord alerts
    """
    backup_path = None
    target_date = None
    
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            target_date = sys.argv[1]
            print(f"Using provided date: {target_date}")
        else:
            # Auto-detect tomorrow
            target_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            print(f"Auto-detected tomorrow: {target_date}")
        
        # Check for force flag
        force = '--force' in sys.argv or '-f' in sys.argv
        
        print()
        
        # Create database backup FIRST
        backup_path = backup_database()
        print()
        
        # Generate predictions
        count = generate_predictions_for_date(target_date, force=force)
        
        if count == 0:
            # Check if predictions exist (skipped) vs error
            preds_exist, pred_count = check_predictions_exist(target_date)
            if preds_exist:
                print("[INFO] Predictions already exist - use --force to regenerate")
                return 0  # Success - predictions exist
            else:
                # Check if it's a "no games" situation
                games_exist, _ = check_games_exist(target_date)
                if not games_exist:
                    print("[INFO] No games scheduled for this date")
                    return 0  # Not an error
                else:
                    error_msg = f"No predictions generated for {target_date} despite games existing"
                    print(f"[WARN] {error_msg}")
                    print("   Check if:")
                    print("   1. Players have sufficient game history (5+ games)")
                    print("   2. Feature extraction is working")
                    print()
                    send_discord_notification(f"⚠️ PREDICTION WARNING\n{error_msg}")
                    return 1  # Potential error
        
        # Verify predictions
        print()
        print('=' * 80)
        print('VERIFICATION RESULTS')
        print('=' * 80)
        print()
        
        results = verify_predictions(target_date)
        
        print(f"Predictions in database: {results['count']}")
        
        if results['count'] > 0:
            print(f"Unique players: {results['unique_players']}")
            print(f"Unique probabilities: {results['unique_probs']}")
            print(f"Avg probability: {results['avg_prob']:.1%}")
            print(f"Range: {results['min_prob']:.1%} to {results['max_prob']:.1%}")
            print(f"OVER: {results['over_count']}, UNDER: {results['under_count']}")
            print(f"With features: {results['with_features']}/{results['count']}")
            print()
            
            # NEW IN V4: Show breakdown by line
            if 'breakdown' in results and results['breakdown']:
                print('BREAKDOWN BY PROP & LINE:')
                for prop_type, line, pred_count in results['breakdown']:
                    print(f'  {prop_type} O{line}: {pred_count}')
                print()
            
            # Check for issues
            issues = []
            
            if results['unique_probs'] <= 10:
                issues.append("Low probability variety (may be using defaults)")
            
            if results['with_features'] < results['count']:
                issues.append(f"Some predictions missing features ({results['with_features']}/{results['count']})")
            
            if issues:
                print('[WARN] POTENTIAL ISSUES:')
                for issue in issues:
                    print(f'  • {issue}')
                print()
            else:
                print('[OK] All checks passed!')
                print()
            
            # Send success Discord notification
            try:
                message = f"""**✅ PREDICTIONS GENERATED - {target_date}**

Total: {results['count']} predictions
Players: {results['unique_players']}
Probability variety: {results['unique_probs']} unique values
Range: {results['min_prob']:.1%} to {results['max_prob']:.1%}
"""
                if 'breakdown' in results and results['breakdown']:
                    message += "\nBreakdown:\n"
                    for prop_type, line, pred_count in results['breakdown']:
                        message += f"• {prop_type} O{line}: {pred_count}\n"
                
                if issues:
                    message += "\n⚠️ Warnings:\n"
                    for issue in issues:
                        message += f"• {issue}\n"
                
                send_discord_notification(message)
                
            except Exception as e:
                print(f'[WARN] Could not send Discord notification: {e}')
            
            print('[OK] SUCCESS - Predictions generated and verified!')
            return 0
            
        else:
            error_msg = f"Predictions generated but not found in database for {target_date}"
            print(f"[ERROR] {error_msg}")
            send_discord_notification(f"❌ PREDICTION ERROR\n{error_msg}")
            return 1
    
    except sqlite3.Error as e:
        # Database errors
        error_msg = f"❌ DATABASE ERROR - {target_date}\n{str(e)}\n\nBackup at: {backup_path}"
        print()
        print('[ERROR] ' + error_msg)
        log_error(traceback.format_exc(), "DATABASE_ERROR")
        try:
            send_discord_notification(error_msg)
        except:
            pass
        return 1
        
    except Exception as e:
        # Unknown errors
        error_msg = f"❌ UNEXPECTED ERROR - {target_date}\n{str(e)}\n\nBackup at: {backup_path}\nCheck logs for details"
        print()
        print('[ERROR] ' + error_msg)
        log_error(traceback.format_exc(), "UNKNOWN_ERROR")
        try:
            send_discord_notification(error_msg)
        except:
            pass
        return 1


if __name__ == '__main__':
    sys.exit(safe_main())
