"""
V2 Auto-Grade Yesterday's Predictions - V3 RELIABLE
===================================================

RELIABILITY ENHANCEMENTS:
✅ Automated database backups before any writes
✅ API retry logic with exponential backoff
✅ Comprehensive error handling and logging
✅ Discord alerts for failures
✅ Result verification after grading

This script:
1. Backs up database before any operations
2. Finds all predictions for target date
3. Fetches actual results from NHL API (with retries)
4. Grades predictions (HIT/MISS) with fuzzy matching
5. Stores results in prediction_outcomes table
6. Updates player_game_logs (V3 continuous learning)
7. Reports accuracy and sends Discord notification
8. Logs all errors for debugging
"""

import sqlite3
import unicodedata
import requests
import sys
import shutil
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from v2_config import DB_PATH, LEARNING_MODE
from v2_discord_notifications import send_discord_notification

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))
from shared.pp_rules_validator import validate_prediction, correct_outcome


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
    backup_path = backup_dir / f"nhl_predictions_v2_grade_{timestamp}.db"
    
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
    
    log_file = log_dir / f"grading_errors_{datetime.now().strftime('%Y%m%d')}.log"
    
    with open(log_file, 'a') as f:
        f.write(f"\n{'='*80}\n")
        f.write(f"[{error_type}] {datetime.now().isoformat()}\n")
        f.write(error_text)
        f.write(f"\n{'='*80}\n")


def fetch_with_retry(url: str, max_retries: int = 3, backoff: int = 30) -> requests.Response:
    """
    Fetch URL with exponential backoff retry logic
    
    Args:
        url: URL to fetch
        max_retries: Maximum number of retry attempts
        backoff: Initial backoff time in seconds
        
    Returns:
        Response object
        
    Raises:
        Exception if all retries fail
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                return response
            elif response.status_code >= 500:
                # Server error - retry with backoff
                if attempt < max_retries - 1:
                    wait_time = backoff * (2 ** attempt)
                    print(f'[RETRY] API error {response.status_code}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})')
                    time.sleep(wait_time)
                    continue
            else:
                # Client error (4xx) - don't retry
                return response
                
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = backoff * (2 ** attempt)
                print(f'[RETRY] Request failed: {e}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})')
                time.sleep(wait_time)
                continue
            raise
    
    raise Exception(f"Failed to fetch {url} after {max_retries} attempts")


# ============================================================================
# CORE GRADING FUNCTIONS (from original script)
# ============================================================================

def _normalize_name(name: str) -> str:
    """Strip diacritics so DB stores ASCII-only player names."""
    return ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')


def save_player_game_logs_to_db(conn, game_id: str, game_date: str, player_stats_by_team: dict):
    """
    Save player stats to player_game_logs table
    
    V3 FEATURE: This function ensures feature extractors get fresh data every day.
    Without this, predictions are based on stale data and model can't improve.
    
    Args:
        conn: Database connection
        game_id: NHL game ID
        game_date: Game date YYYY-MM-DD
        player_stats_by_team: Dict with 'away' and 'home' keys
    """
    cursor = conn.cursor()
    saved_count = 0
    
    for team_type in ['away', 'home']:
        is_home = 1 if team_type == 'home' else 0
        team_stats = player_stats_by_team.get(team_type, {})
        
        for _raw_name, stats in team_stats.items():
            player_name = _normalize_name(_raw_name)
            try:
                # Calculate binary outcomes for feature extraction
                points = stats.get('points', 0)
                shots = stats.get('shots', 0)
                
                scored_1plus_points = 1 if points >= 1 else 0
                scored_2plus_shots = 1 if shots >= 2 else 0
                scored_3plus_shots = 1 if shots >= 3 else 0  
                scored_4plus_shots = 1 if shots >= 4 else 0
                
                cursor.execute("""
                    INSERT OR REPLACE INTO player_game_logs
                    (game_id, game_date, player_name, team, opponent, is_home,
                     goals, assists, points, shots_on_goal, toi_seconds, plus_minus, pim,
                     hits, blocked_shots, assists_total,
                     scored_1plus_points, scored_2plus_shots, scored_3plus_shots, scored_4plus_shots,
                     created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    game_id,
                    game_date,
                    player_name,
                    stats.get('team'),
                    stats.get('opponent'),
                    is_home,
                    stats.get('goals', 0),
                    stats.get('assists', 0),
                    points,
                    shots,
                    stats.get('toi_seconds', 0),
                    stats.get('plus_minus', 0),
                    stats.get('pim', 0),
                    stats.get('hits', 0),
                    stats.get('blocked_shots', 0),
                    stats.get('assists', 0),  # assists_total mirrors assists
                    scored_1plus_points,
                    scored_2plus_shots,
                    scored_3plus_shots,
                    scored_4plus_shots,
                    datetime.now().isoformat()
                ))
                saved_count += 1
            except Exception as e:
                print(f'[WARN] Could not save {player_name} to player_game_logs: {e}')
    
    conn.commit()
    return saved_count


def fetch_actual_results(game_date: str) -> Dict[str, Dict]:
    """
    Fetch actual player stats from NHL API for all games on given date
    
    RELIABILITY: Now uses retry logic for API calls
    
    Args:
        game_date: Date in YYYY-MM-DD format
        
    Returns:
        Dict mapping player_name -> {points, shots, goals, assists, team, opponent, toi_seconds, plus_minus, pim}
    """
    print(f'Fetching actual results for {game_date}...')
    
    player_stats = {}
    
    try:
        # Get schedule for the date (WITH RETRY)
        schedule_url = f'https://api-web.nhle.com/v1/schedule/{game_date}'
        response = fetch_with_retry(schedule_url)
        
        if response.status_code != 200:
            print(f'[ERROR] Schedule API returned status {response.status_code}')
            return player_stats
            
        schedule_data = response.json()
        
        # Find games for the target date
        games = []
        for day in schedule_data.get('gameWeek', []):
            if day.get('date') == game_date:
                games = day.get('games', [])
                break
        
        if not games:
            print(f'No games found for {game_date}')
            return player_stats
        
        print(f'Found {len(games)} games')
        
        # Fetch boxscore for each game
        for game in games:
            game_id = game.get('id')
            if not game_id:
                continue
            
            away_abbrev = game.get('awayTeam', {}).get('abbrev', 'UNK')
            home_abbrev = game.get('homeTeam', {}).get('abbrev', 'UNK')
            game_state = game.get('gameState', 'UNKNOWN')
            
            print(f'  Fetching: {away_abbrev} @ {home_abbrev} (ID: {game_id}, State: {game_state})')
            
            # Only process finished games
            if game_state not in ['OFF', 'FINAL']:
                print(f'    [WARN] Game not finished yet (state: {game_state})')
                continue
            
            try:
                # Get boxscore (WITH RETRY)
                boxscore_url = f'https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore'
                box_response = fetch_with_retry(boxscore_url)
                
                if box_response.status_code != 200:
                    print(f'    [ERROR] Boxscore API returned status {box_response.status_code}')
                    continue
                
                boxscore = box_response.json()
                
                # Extract player stats from boxscore
                if 'playerByGameStats' not in boxscore:
                    print(f'    [WARN] No player stats in boxscore')
                    continue
                
                player_by_game = boxscore['playerByGameStats']
                away_stats = player_by_game.get('awayTeam', {})
                home_stats = player_by_game.get('homeTeam', {})
                
                # Process away team
                away_players = {}
                for position in ['forwards', 'defense']:
                    for player in away_stats.get(position, []):
                        name_data = player.get('name', {})
                        player_name = name_data.get('default', '')
                        
                        if player_name:
                            points = player.get('points', 0)
                            shots = player.get('sog', 0)
                            goals = player.get('goals', 0)
                            assists = player.get('assists', 0)
                            hits = player.get('hits', 0)
                            blocked_shots = player.get('blockedShots', 0)
                            toi = player.get('toi', '0:00')
                            plus_minus = player.get('plusMinus', 0)
                            pim = player.get('pim', 0)

                            # Convert TOI to seconds
                            toi_seconds = 0
                            if toi and ':' in toi:
                                try:
                                    parts = toi.split(':')
                                    if len(parts) == 2:
                                        toi_seconds = int(parts[0]) * 60 + int(parts[1])
                                except:
                                    toi_seconds = 0

                            player_stats[player_name] = {
                                'points': points,
                                'shots': shots,
                                'goals': goals,
                                'assists': assists,
                                'hits': hits,
                                'blocked_shots': blocked_shots,
                                'team': away_abbrev,
                                'opponent': home_abbrev,
                                'toi_seconds': toi_seconds,
                                'plus_minus': plus_minus,
                                'pim': pim
                            }

                            away_players[player_name] = player_stats[player_name]

                # Process home team
                home_players = {}
                for position in ['forwards', 'defense']:
                    for player in home_stats.get(position, []):
                        name_data = player.get('name', {})
                        player_name = name_data.get('default', '')

                        if player_name:
                            points = player.get('points', 0)
                            shots = player.get('sog', 0)
                            goals = player.get('goals', 0)
                            assists = player.get('assists', 0)
                            hits = player.get('hits', 0)
                            blocked_shots = player.get('blockedShots', 0)
                            toi = player.get('toi', '0:00')
                            plus_minus = player.get('plusMinus', 0)
                            pim = player.get('pim', 0)

                            # Convert TOI to seconds
                            toi_seconds = 0
                            if toi and ':' in toi:
                                try:
                                    parts = toi.split(':')
                                    if len(parts) == 2:
                                        toi_seconds = int(parts[0]) * 60 + int(parts[1])
                                except:
                                    toi_seconds = 0

                            player_stats[player_name] = {
                                'points': points,
                                'shots': shots,
                                'goals': goals,
                                'assists': assists,
                                'hits': hits,
                                'blocked_shots': blocked_shots,
                                'team': home_abbrev,
                                'opponent': away_abbrev,
                                'toi_seconds': toi_seconds,
                                'plus_minus': plus_minus,
                                'pim': pim
                            }

                            home_players[player_name] = player_stats[player_name]
                
                # V3 FEATURE: Save player stats to player_game_logs table
                conn = sqlite3.connect(DB_PATH)
                saved = save_player_game_logs_to_db(
                    conn,
                    game_id=str(game_id),
                    game_date=game_date,
                    player_stats_by_team={'away': away_players, 'home': home_players}
                )
                conn.close()
                
                player_count = len(away_players) + len(home_players)
                print(f'    [OK] Fetched stats for {player_count} players (saved {saved} to player_game_logs)')
                
            except Exception as e:
                print(f'    [ERROR] Error fetching game {game_id}: {e}')
                log_error(traceback.format_exc(), "GAME_FETCH_ERROR")
                continue
        
        print(f'Found stats for {len(player_stats)} players total')
        
    except Exception as e:
        print(f'[ERROR] Error fetching results: {e}')
        log_error(traceback.format_exc(), "API_ERROR")
    
    return player_stats


def find_player_stats(player_name: str, actual_stats: Dict) -> Optional[tuple]:
    """
    Find player stats with fuzzy matching to handle name variations
    
    Handles:
    - Exact match
    - Case-insensitive
    - Spacing differences (J.Kulich vs J. Kulich)
    - Dot variations (E.Lindholm vs E. Lindholm)
    - Nickname variations
    
    Args:
        player_name: Player name from prediction
        actual_stats: Dict of {player_name: stats}
        
    Returns:
        (player stats dict, match_type) or (None, None) if not found
    """
    # Strategy 1: Exact match
    if player_name in actual_stats:
        return actual_stats[player_name], 'exact'
    
    # Strategy 2: Case-insensitive exact match
    for name, stats in actual_stats.items():
        if name.lower() == player_name.lower():
            return stats, 'case_insensitive'
    
    # Strategy 3: Normalize spacing around dots and compare
    def normalize_name(name):
        import re
        name = re.sub(r'\.(?=[A-Z])', '. ', name)
        name = ' '.join(name.split())
        return name.lower()
    
    normalized_search = normalize_name(player_name)
    
    for name, stats in actual_stats.items():
        if normalize_name(name) == normalized_search:
            return stats, 'normalized'
    
    # Strategy 4: Remove all spaces/dots and compare
    def strip_all(name):
        return name.replace('.', '').replace(' ', '').replace('-', '').lower()
    
    stripped_search = strip_all(player_name)
    
    for name, stats in actual_stats.items():
        if strip_all(name) == stripped_search:
            return stats, 'stripped'
    
    # Strategy 5: Fuzzy matching (similar names)
    try:
        from difflib import SequenceMatcher
        
        best_match = None
        best_match_name = None
        best_ratio = 0.85  # 85% similarity threshold
        
        for name, stats in actual_stats.items():
            ratio = SequenceMatcher(None, player_name.lower(), name.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = stats
                best_match_name = name
        
        if best_match:
            return best_match, f'fuzzy_{best_ratio:.0%}'
            
    except ImportError:
        pass
    
    # Not found
    return None, None


def grade_predictions(game_date: str) -> Dict:
    """
    Grade all predictions for given date
    
    Args:
        game_date: Date in YYYY-MM-DD format
        
    Returns:
        Dict with grading results and stats
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Idempotent migrations — run once, safe to repeat
    for migration in [
        "ALTER TABLE prediction_outcomes ADD COLUMN profit REAL",
        "ALTER TABLE prediction_outcomes ADD COLUMN is_smart_pick INTEGER DEFAULT 0",
        "ALTER TABLE prediction_outcomes ADD COLUMN odds_type TEXT DEFAULT 'standard'",
        "ALTER TABLE prediction_outcomes RENAME COLUMN predicted_outcome TO prediction",
        "ALTER TABLE prediction_outcomes RENAME COLUMN actual_stat_value TO actual_value",
    ]:
        try:
            cursor.execute(migration)
            conn.commit()
        except Exception:
            pass  # Column already exists or was already renamed

    # Get predictions for date
    cursor.execute('''
        SELECT id, player_name, team, opponent, prop_type, line,
               prediction, probability, confidence_tier, is_smart_pick, odds_type
        FROM predictions
        WHERE game_date = ?
    ''', (game_date,))
    
    predictions = cursor.fetchall()
    
    if not predictions:
        print(f'No predictions found for {game_date}')
        conn.close()
        return {}
    
    print(f'Found {len(predictions)} predictions to grade')
    
    # Fetch actual results
    actual_stats = fetch_actual_results(game_date)
    
    if not actual_stats:
        print('[WARN] Could not fetch actual results - cannot grade')
        conn.close()
        return {}
    
    # Grade each prediction
    results = {
        'total': 0,
        'hits': 0,
        'misses': 0,
        'by_tier': {},
        'by_prop': {},
        'graded': [],
        'match_stats': {
            'exact': 0,
            'case_insensitive': 0,
            'normalized': 0,
            'stripped': 0,
            'fuzzy': 0,
            'not_found': 0
        }
    }
    
    print()
    print('Grading predictions...')
    print()
    
    not_found_count = 0
    not_found_examples = []
    
    for pred in predictions:
        pred_id, player_name, team, opponent, prop_type, line, prediction, probability, tier = pred
        is_smart_pick = pred[9]
        odds_type     = pred[10] or 'standard'

        # Block impossible combos (demon/goblin + UNDER)
        combo_check = validate_prediction(odds_type, prediction)
        if not combo_check:
            print(f'[BLOCKED] {player_name} {prop_type}: {combo_check.reason}')
            continue

        # Find player's actual stats using fuzzy matching
        actual, match_type = find_player_stats(player_name, actual_stats)

        if not actual:
            results['match_stats']['not_found'] += 1
            not_found_count += 1
            if len(not_found_examples) < 5:
                not_found_examples.append(f'{player_name} ({team})')
            continue

        # Track match type
        if match_type.startswith('fuzzy_'):
            results['match_stats']['fuzzy'] += 1
        elif match_type in results['match_stats']:
            results['match_stats'][match_type] += 1

        # Get actual stat value
        if prop_type == 'points':
            actual_value = actual['points']
        elif prop_type == 'shots':
            actual_value = actual['shots']
        elif prop_type == 'goals':
            actual_value = actual['goals']
        elif prop_type == 'assists':
            actual_value = actual['assists']
        elif prop_type == 'hits':
            actual_value = actual.get('hits', 0)
        elif prop_type == 'blocked_shots':
            actual_value = actual.get('blocked_shots', 0)
        else:
            print(f'[WARN] Unknown prop type: {prop_type}')
            continue

        # Use validator — handles DNP (actual=0 → VOID), push, logic errors
        outcome = correct_outcome(odds_type, prediction, actual_value, line)
        actual_outcome = 'OVER' if actual_value > line else 'UNDER'

        if outcome == 'HIT':
            profit = 120.0 if odds_type == 'demon' else (31.25 if odds_type == 'goblin' else 90.91)
        elif outcome == 'MISS':
            profit = -100.0
        else:
            profit = 0.0  # VOID / PUSH

        cursor.execute('''
            INSERT INTO prediction_outcomes
            (prediction_id, game_date, player_name, prop_type, line,
             prediction, predicted_probability,
             actual_value, actual_outcome, outcome, graded_at, profit,
             is_smart_pick, odds_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (pred_id, game_date, player_name, prop_type, line,
              prediction, probability, actual_value, actual_outcome, outcome,
              datetime.now().isoformat(), profit,
              is_smart_pick, odds_type))

        hit = (outcome == 'HIT')
        # Update stats
        results['total'] += 1
        if hit:
            results['hits'] += 1
        else:
            results['misses'] += 1
        
        # By tier
        if tier not in results['by_tier']:
            results['by_tier'][tier] = {'total': 0, 'hits': 0}
        results['by_tier'][tier]['total'] += 1
        if hit:
            results['by_tier'][tier]['hits'] += 1
        
        # By prop type
        if prop_type not in results['by_prop']:
            results['by_prop'][prop_type] = {'total': 0, 'hits': 0}
        results['by_prop'][prop_type]['total'] += 1
        if hit:
            results['by_prop'][prop_type]['hits'] += 1
        
        results['graded'].append({
            'player': player_name,
            'team': team,
            'prop': f'{prop_type} {prediction} {line}',
            'predicted': probability,
            'actual': actual_value,
            'outcome': outcome
        })

    # Backfill profit for any existing rows that are missing it
    cursor.execute("""
        UPDATE prediction_outcomes
        SET profit = CASE outcome 
            WHEN 'HIT' THEN 
                CASE odds_type
                    WHEN 'goblin' THEN 31.25
                    WHEN 'demon' THEN 120.0
                    ELSE 90.91
                END
            ELSE -100.0 
        END
        WHERE profit IS NULL AND outcome IN ('HIT', 'MISS')
    """)

    conn.commit()
    conn.close()
    
    # Show not found examples if any
    if not_found_count > 0:
        print()
        print(f'[WARN] {not_found_count} predictions could not be matched to player stats')
        if not_found_examples:
            print(f'Examples: {", ".join(not_found_examples[:5])}')
            if not_found_count > 5:
                print(f'... and {not_found_count - 5} more')
    
    return results


def print_grading_report(results: Dict, game_date: str):
    """Print detailed grading report"""
    
    if not results or results['total'] == 0:
        print('No predictions graded')
        return
    
    print('='*80)
    print(f'GRADING RESULTS - {game_date}')
    print('='*80)
    print()
    
    # Overall accuracy
    accuracy = results['hits'] / results['total']
    print(f'Overall: {results["hits"]}/{results["total"]} ({accuracy:.1%})')
    print()
    
    # Name matching stats
    if results.get('match_stats'):
        match_stats = results['match_stats']
        total_checked = sum(match_stats.values())
        matched = total_checked - match_stats['not_found']
        
        print('Name Matching:')
        print(f'  Total predictions: {total_checked}')
        print(f'  Successfully matched: {matched} ({matched/total_checked:.1%})')
        print(f'  Not found: {match_stats["not_found"]} ({match_stats["not_found"]/total_checked:.1%})')
        print()
        print('  Match types:')
        if match_stats['exact'] > 0:
            print(f'    Exact: {match_stats["exact"]}')
        if match_stats['case_insensitive'] > 0:
            print(f'    Case-insensitive: {match_stats["case_insensitive"]}')
        if match_stats['normalized'] > 0:
            print(f'    Normalized (spacing): {match_stats["normalized"]}')
        if match_stats['stripped'] > 0:
            print(f'    Stripped (dots/spaces): {match_stats["stripped"]}')
        if match_stats['fuzzy'] > 0:
            print(f'    Fuzzy (similarity): {match_stats["fuzzy"]}')
        print()
    
    # By tier
    if results['by_tier']:
        print('By Confidence Tier:')
        for tier in sorted(results['by_tier'].keys()):
            stats = results['by_tier'][tier]
            tier_acc = stats['hits'] / stats['total'] if stats['total'] > 0 else 0
            print(f'  {tier}: {stats["hits"]}/{stats["total"]} ({tier_acc:.1%})')
        print()
    
    # By prop type
    if results['by_prop']:
        print('By Prop Type:')
        for prop in sorted(results['by_prop'].keys()):
            stats = results['by_prop'][prop]
            prop_acc = stats['hits'] / stats['total'] if stats['total'] > 0 else 0
            print(f'  {prop}: {stats["hits"]}/{stats["total"]} ({prop_acc:.1%})')
        print()
    
    # Sample of results
    print('Sample Results (first 10):')
    for result in results['graded'][:10]:
        emoji = '[OK]' if result['outcome'] == 'HIT' else '[MISS]'
        print(f'  {emoji} {result["player"]} ({result["team"]}): {result["prop"]} - '
              f'Predicted {result["predicted"]:.1%}, Actual {result["actual"]} - {result["outcome"]}')
    
    if len(results['graded']) > 10:
        print(f'  ... and {len(results["graded"]) - 10} more')
    
    print()
    print('='*80)


def verify_grading_results(game_date: str, expected_graded: int) -> bool:
    """
    Verify grading actually worked
    
    Args:
        game_date: Date that was graded
        expected_graded: Number of predictions we expected to grade
        
    Returns:
        True if verification passed
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check outcomes were saved
    cursor.execute('''
        SELECT COUNT(*) FROM prediction_outcomes 
        WHERE game_date = ? AND graded_at >= ?
    ''', (game_date, datetime.now().strftime('%Y-%m-%d 00:00:00')))
    
    actual_graded = cursor.fetchone()[0]
    
    # Check player_game_logs were updated (V3 feature)
    cursor.execute('''
        SELECT COUNT(*) FROM player_game_logs 
        WHERE game_date = ? AND created_at >= ?
    ''', (game_date, datetime.now().strftime('%Y-%m-%d 00:00:00')))
    
    logs_saved = cursor.fetchone()[0]
    
    conn.close()
    
    print()
    print('[VERIFY] Verification Results:')
    print(f'  Outcomes saved: {actual_graded}/{expected_graded}')
    print(f'  Player logs updated: {logs_saved}')
    
    if actual_graded == 0:
        print('[ERROR] CRITICAL: No outcomes were saved!')
        return False
    
    if logs_saved == 0 and actual_graded > 0:
        print('[ERROR] CRITICAL: Outcomes saved but player_game_logs not updated!')
        print('         V3 continuous learning is broken!')
        return False
    
    print('[OK] Verification passed')
    return True


# ============================================================================
# MAIN WITH RELIABILITY WRAPPER
# ============================================================================

def safe_main():
    """
    Main function wrapped with comprehensive error handling
    
    RELIABILITY: Catches all errors, logs them, and sends Discord alerts
    """
    backup_path = None
    target_date = None
    
    try:
        print()
        print('='*80)
        print('AUTO-GRADING PREDICTIONS - V3 RELIABLE')
        print('='*80)
        print()
        
        # Create database backup FIRST
        backup_path = backup_database()
        print()
        
        # Determine target date
        if len(sys.argv) > 1:
            target_date = sys.argv[1]
        else:
            # Default to yesterday
            target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        print(f'Grading target: {target_date}')
        print()
        
        # Grade predictions
        results = grade_predictions(target_date)
        
        if results and results['total'] > 0:
            # Print report
            print_grading_report(results, target_date)
            
            # VERIFY results were actually saved
            verification_passed = verify_grading_results(target_date, results['total'])
            
            if not verification_passed:
                raise Exception("Verification failed - data may not have been saved correctly")
            
            # Send success Discord notification
            try:
                accuracy = results['hits'] / results['total']
                
                # Match stats
                match_stats = results.get('match_stats', {})
                total_checked = sum(match_stats.values())
                matched = total_checked - match_stats.get('not_found', 0)
                match_rate = matched / total_checked if total_checked > 0 else 0
                
                message = f"""**[OK] GRADING COMPLETE - {target_date}**

Overall: {results['hits']}/{results['total']} ({accuracy:.1%})
Name matching: {matched}/{total_checked} ({match_rate:.1%})

By Prop Type:
"""
                for prop in sorted(results['by_prop'].keys()):
                    stats = results['by_prop'][prop]
                    prop_acc = stats['hits'] / stats['total'] if stats['total'] > 0 else 0
                    message += f"• {prop}: {stats['hits']}/{stats['total']} ({prop_acc:.1%})\n"
                
                send_discord_notification("NHL Grading Complete", message, color="green")

            except Exception as e:
                print(f'[WARN] Could not send Discord notification: {e}')
            
            print()
            print('[OK] SUCCESS - Grading completed and verified')
            return 0
            
        else:
            # No predictions for this date - could be an off day or break
            print(f'[OK] No predictions to grade for {target_date} (off day, break, or no games)')
            return 0
    
    except requests.exceptions.RequestException as e:
        # API errors
        error_msg = f"❌ NHL API ERROR - {target_date}\n{str(e)}\n\nBackup at: {backup_path}\nRetry in 30 minutes"
        print()
        print('[ERROR] ' + error_msg)
        log_error(traceback.format_exc(), "API_ERROR")
        try:
            send_discord_notification("NHL API Error", error_msg, color="red")
        except:
            pass
        return 1

    except sqlite3.Error as e:
        # Database errors
        error_msg = f"DATABASE ERROR - {target_date}\n{str(e)}\n\nBackup at: {backup_path}"
        print()
        print('[ERROR] ' + error_msg)
        log_error(traceback.format_exc(), "DATABASE_ERROR")
        try:
            send_discord_notification("NHL Database Error", error_msg, color="red")
        except:
            pass
        return 1

    except Exception as e:
        # Unknown errors
        error_msg = f"UNEXPECTED ERROR - {target_date}\n{str(e)}\n\nBackup at: {backup_path}\nCheck logs for details"
        print()
        print('[ERROR] ' + error_msg)
        log_error(traceback.format_exc(), "UNKNOWN_ERROR")
        try:
            send_discord_notification("NHL Grading Error", error_msg, color="red")
        except:
            pass
        return 1


if __name__ == '__main__':
    sys.exit(safe_main())
