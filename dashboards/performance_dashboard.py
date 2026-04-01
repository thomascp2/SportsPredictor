#!/usr/bin/env python3
"""
Multi-Sport Prediction System - Dashboard Application
======================================================

Flask web dashboard for monitoring and managing NBA & NHL prediction systems.

Features:
- Multi-sport monitoring (NBA & NHL)
- System health for both sports
- Command center (run predictions, grading, data collection)
- Prediction browser with search/filters
- Performance analytics (accuracy, calibration)
- Feature extraction monitoring
- ESPN scoreboards for both sports
- Probability distribution analysis

Usage:
    python dashboard_app.py

    Then open browser to: http://localhost:5000
"""

import os
import sys
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request
import json
import requests

# ============================================================================
# CONFIGURATION
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.parent  # repo root

# Sport-specific configurations
SPORTS_CONFIG = {
    'nba': {
        'name': 'NBA',
        'db_path': PROJECT_ROOT / 'nba' / 'database' / 'nba_predictions.db',
        'project_root': PROJECT_ROOT / 'nba',
        'prop_types': ['points', 'rebounds', 'assists', 'threes', 'stocks', 'pra', 'minutes'],
        'scoreboard_url': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
        'scripts': [
            'generate_predictions_daily_V6.py',
            'auto_grade_multi_api_FIXED.py',
        ],
        'color': '#FDB927',
        'icon': 'basketball'
    },
    'nhl': {
        'name': 'NHL',
        'db_path': PROJECT_ROOT / 'nhl' / 'database' / 'nhl_predictions_v2.db',
        'project_root': PROJECT_ROOT / 'nhl',
        'prop_types': ['points', 'shots', 'goals', 'assists', 'saves', 'hits', 'blocked_shots'],
        'scoreboard_url': 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard',
        'scripts': [
            'generate_predictions_daily_V6.py',
            'v2_auto_grade_yesterday_v3_RELIABLE.py',
        ],
        'color': '#C8102E',
        'icon': 'hockey-puck'
    }
}

app = Flask(__name__)
app.config['SECRET_KEY'] = 'multi-sport-prediction-dashboard-2025'
app.config['TEMPLATES_AUTO_RELOAD'] = True


# ============================================================================
# DATABASE QUERIES
# ============================================================================

def get_db_connection(sport):
    """Get SQLite database connection for a sport."""
    db_path = SPORTS_CONFIG[sport]['db_path']
    if not db_path.exists():
        raise FileNotFoundError(f"{sport.upper()} database not found at {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_system_health(sport):
    """Get system health metrics for a sport."""
    conn = get_db_connection(sport)
    cursor = conn.cursor()

    # Total predictions
    cursor.execute("SELECT COUNT(*) as count FROM predictions")
    total_predictions = cursor.fetchone()['count']

    # Graded predictions
    cursor.execute("SELECT COUNT(*) as count FROM prediction_outcomes")
    graded_predictions = cursor.fetchone()['count']

    # Player game logs
    cursor.execute("SELECT COUNT(*) as count FROM player_game_logs")
    player_logs = cursor.fetchone()['count']

    # Unique players tracked
    cursor.execute("SELECT COUNT(DISTINCT player_name) as count FROM player_game_logs")
    unique_players = cursor.fetchone()['count']

    # Unique probability values (feature variety)
    cursor.execute("""
        SELECT COUNT(DISTINCT ROUND(probability, 2)) as count
        FROM predictions
        WHERE probability IS NOT NULL
    """)
    probability_variety = cursor.fetchone()['count']

    # Predictions with features
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM predictions
        WHERE features_json IS NOT NULL
          AND features_json != ''
    """)
    predictions_with_features = cursor.fetchone()['count']

    # Predictions with opponent features
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM predictions
        WHERE features_json IS NOT NULL
          AND features_json LIKE '%opp_%'
    """)
    predictions_with_opponent_features = cursor.fetchone()['count']

    # Recent prediction date
    cursor.execute("SELECT MAX(game_date) as latest_date FROM predictions")
    latest_prediction_date = cursor.fetchone()['latest_date']

    # Recent grading date
    cursor.execute("SELECT MAX(game_date) as latest_date FROM prediction_outcomes")
    latest_graded_date = cursor.fetchone()['latest_date']

    # Database size
    db_path = SPORTS_CONFIG[sport]['db_path']
    db_size_mb = os.path.getsize(db_path) / (1024 * 1024) if db_path.exists() else 0

    conn.close()

    grading_rate = (graded_predictions / total_predictions * 100) if total_predictions > 0 else 0
    feature_capture_rate = (predictions_with_features / total_predictions * 100) if total_predictions > 0 else 0
    opponent_feature_rate = (predictions_with_opponent_features / total_predictions * 100) if total_predictions > 0 else 0

    return {
        'sport': sport.upper(),
        'total_predictions': total_predictions,
        'graded_predictions': graded_predictions,
        'grading_rate': round(grading_rate, 1),
        'player_logs': player_logs,
        'unique_players': unique_players,
        'probability_variety': probability_variety,
        'predictions_with_features': predictions_with_features,
        'feature_capture_rate': round(feature_capture_rate, 1),
        'predictions_with_opponent_features': predictions_with_opponent_features,
        'opponent_feature_rate': round(opponent_feature_rate, 1),
        'latest_prediction_date': latest_prediction_date,
        'latest_graded_date': latest_graded_date,
        'db_size_mb': round(db_size_mb, 2)
    }


def get_performance_metrics(sport):
    """Get accuracy and performance metrics for a sport."""
    conn = get_db_connection(sport)
    cursor = conn.cursor()

    # Overall accuracy
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
        FROM prediction_outcomes
    """)
    result = cursor.fetchone()
    total = result['total'] or 0
    hits = result['hits'] or 0
    overall_accuracy = (hits / total * 100) if total > 0 else 0

    # Accuracy by prop type
    prop_accuracies = {}
    for prop_type in SPORTS_CONFIG[sport]['prop_types']:
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
            FROM prediction_outcomes
            WHERE prop_type = ?
        """, (prop_type,))
        result = cursor.fetchone()
        prop_total = result['total'] or 0
        prop_hits = result['hits'] or 0
        prop_accuracies[prop_type] = {
            'accuracy': round((prop_hits / prop_total * 100), 1) if prop_total > 0 else 0,
            'total': prop_total,
            'hits': prop_hits or 0
        }

    # Brier score (calibration metric) - join with predictions table to get probability
    cursor.execute("""
        SELECT p.probability, po.outcome
        FROM prediction_outcomes po
        JOIN predictions p ON po.prediction_id = p.id
        WHERE p.probability IS NOT NULL
          AND po.outcome IS NOT NULL
    """)
    results = cursor.fetchall()

    if results and len(results) > 0:
        brier_sum = 0
        for row in results:
            prob = row['probability']
            actual = 1 if row['outcome'] == 'HIT' else 0
            brier_sum += (prob - actual) ** 2
        brier_score = brier_sum / len(results)
    else:
        brier_score = None

    conn.close()

    return {
        'sport': sport.upper(),
        'overall_accuracy': round(overall_accuracy, 1) if total > 0 else None,
        'total_graded': total,
        'total_hits': hits,
        'brier_score': round(brier_score, 3) if brier_score is not None else None,
        'prop_accuracies': prop_accuracies
    }


def get_probability_distribution(sport):
    """Get probability distribution for recent predictions."""
    conn = get_db_connection(sport)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ROUND(probability, 2) as prob_bucket,
            COUNT(*) as count
        FROM predictions
        WHERE probability IS NOT NULL
          AND created_at >= datetime('now', '-7 days')
        GROUP BY ROUND(probability, 2)
        ORDER BY prob_bucket
    """)

    distribution = [{'probability': row['prob_bucket'], 'count': row['count']} for row in cursor.fetchall()]
    conn.close()

    return distribution


def get_recent_predictions(sport, limit=50):
    """Get recent predictions with outcomes for a sport."""
    conn = get_db_connection(sport)
    cursor = conn.cursor()

    # Check which columns exist in prediction_outcomes
    cursor.execute("PRAGMA table_info(prediction_outcomes)")
    columns = [col[1] for col in cursor.fetchall()]

    # Use appropriate column name for actual value
    actual_col = 'actual_stat_value' if 'actual_stat_value' in columns else 'actual_value'

    query = f"""
        SELECT
            p.id,
            p.game_date,
            p.player_name,
            p.team,
            p.opponent,
            p.prop_type,
            p.line,
            p.prediction,
            p.probability,
            p.created_at,
            po.outcome,
            po.{actual_col} as actual_value
        FROM predictions p
        LEFT JOIN prediction_outcomes po ON p.id = po.prediction_id
        ORDER BY p.created_at DESC
        LIMIT ?
    """

    cursor.execute(query, (limit,))
    predictions = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return predictions


def get_accuracy_trend(sport, days=14):
    """Get daily accuracy trend for a sport."""
    conn = get_db_connection(sport)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            game_date,
            COUNT(*) as total,
            SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits,
            ROUND(SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as accuracy
        FROM prediction_outcomes
        WHERE game_date >= date('now', '-' || ? || ' days')
        GROUP BY game_date
        ORDER BY game_date ASC
    """, (days,))

    trend = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return trend


def get_feature_stats(sport):
    """Get statistics about features being extracted for a sport."""
    conn = get_db_connection(sport)
    cursor = conn.cursor()

    # Get recent features_json to analyze
    cursor.execute("""
        SELECT features_json
        FROM predictions
        WHERE features_json IS NOT NULL
          AND features_json != ''
          AND created_at >= datetime('now', '-3 days')
        ORDER BY created_at DESC
        LIMIT 500
    """)

    feature_counts = {}
    feature_values = {}

    for row in cursor.fetchall():
        try:
            features = json.loads(row['features_json'])
            for key, value in features.items():
                if key not in feature_counts:
                    feature_counts[key] = 0
                    feature_values[key] = []
                feature_counts[key] += 1
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    feature_values[key].append(value)
        except:
            continue

    # Calculate stats
    feature_stats = []
    for feature_name, count in feature_counts.items():
        values = feature_values.get(feature_name, [])
        stat = {
            'name': feature_name,
            'count': count,
            'type': 'opponent' if 'opp_' in feature_name else 'player'
        }

        if values:
            stat['min'] = round(min(values), 3)
            stat['max'] = round(max(values), 3)
            stat['mean'] = round(sum(values) / len(values), 3)
            if len(values) > 1:
                mean = sum(values) / len(values)
                variance = sum((x - mean)**2 for x in values) / len(values)
                stat['std'] = round(variance**0.5, 3)
            else:
                stat['std'] = 0
        else:
            stat['min'] = stat['max'] = stat['mean'] = stat['std'] = 0

        feature_stats.append(stat)

    # Sort: opponent features first, then by count
    feature_stats.sort(key=lambda x: (0 if x['type'] == 'opponent' else 1, -x['count']))
    conn.close()

    return feature_stats


# ============================================================================
# ESPN SCOREBOARD API
# ============================================================================

def get_espn_scoreboard(sport):
    """Fetch ESPN scoreboard data for a sport."""
    try:
        url = SPORTS_CONFIG[sport]['scoreboard_url']
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        # Enhance with period/clock info
        if 'events' in data:
            for event in data.get('events', []):
                try:
                    competition = event.get('competitions', [{}])[0]
                    status = competition.get('status', {})

                    # Extract period/quarter info
                    period = status.get('period')
                    if period and sport == 'nba':
                        if period <= 4:
                            period_display = f"Q{period}"
                        else:
                            period_display = f"OT{period - 4}"
                    elif period and sport == 'nhl':
                        if period == 1:
                            period_display = "1st"
                        elif period == 2:
                            period_display = "2nd"
                        elif period == 3:
                            period_display = "3rd"
                        elif period == 4:
                            period_display = "OT"
                        else:
                            period_display = "SO"
                    else:
                        period_display = None

                    # Extract clock
                    clock = status.get('displayClock', '')

                    # Add enhanced data
                    competition['enhanced_period'] = period_display
                    competition['enhanced_clock'] = clock
                except:
                    continue

        return data
    except Exception as e:
        return {'error': str(e)}


# ============================================================================
# SCRIPT EXECUTION
# ============================================================================

def run_script(sport, script_name):
    """Run a Python script for a specific sport and return output."""
    project_root = SPORTS_CONFIG[sport]['project_root']
    script_path = project_root / script_name

    print(f"\n{'='*70}")
    print(f"SCRIPT EXECUTION REQUEST - {sport.upper()}")
    print(f"{'='*70}")
    print(f"Script: {script_name}")
    print(f"Full path: {script_path}")
    print(f"Path exists: {script_path.exists()}")
    print(f"{'='*70}\n")

    if not script_path.exists():
        error_msg = f'Script not found: {script_name}\nExpected location: {script_path}'
        print(f"ERROR: {error_msg}")
        return {'success': False, 'error': error_msg}

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )

        print(f"Script completed with return code: {result.returncode}")
        if result.returncode != 0:
            print(f"STDERR: {result.stderr}")

        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        error_msg = 'Script timeout (10 minutes)'
        print(f"ERROR: {error_msg}")
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f'{type(e).__name__}: {str(e)}'
        print(f"ERROR: {error_msg}")
        return {'success': False, 'error': error_msg}


# ============================================================================
# ROUTES - Pages
# ============================================================================

@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('index.html', sports=SPORTS_CONFIG)


# ============================================================================
# ROUTES - API Endpoints
# ============================================================================

@app.route('/api/<sport>/system-health')
def api_system_health(sport):
    """Get system health metrics for a sport."""
    if sport not in SPORTS_CONFIG:
        return jsonify({'error': 'Invalid sport'}), 400
    try:
        return jsonify(get_system_health(sport))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/<sport>/performance-metrics')
def api_performance_metrics(sport):
    """Get performance metrics for a sport."""
    if sport not in SPORTS_CONFIG:
        return jsonify({'error': 'Invalid sport'}), 400
    try:
        return jsonify(get_performance_metrics(sport))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/<sport>/probability-distribution')
def api_probability_distribution(sport):
    """Get probability distribution for a sport."""
    if sport not in SPORTS_CONFIG:
        return jsonify({'error': 'Invalid sport'}), 400
    try:
        return jsonify(get_probability_distribution(sport))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/<sport>/recent-predictions')
def api_recent_predictions(sport):
    """Get recent predictions for a sport."""
    if sport not in SPORTS_CONFIG:
        return jsonify({'error': 'Invalid sport'}), 400
    limit = request.args.get('limit', 50, type=int)
    try:
        return jsonify(get_recent_predictions(sport, limit))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/<sport>/accuracy-trend')
def api_accuracy_trend(sport):
    """Get accuracy trend for a sport."""
    if sport not in SPORTS_CONFIG:
        return jsonify({'error': 'Invalid sport'}), 400
    days = request.args.get('days', 14, type=int)
    try:
        return jsonify(get_accuracy_trend(sport, days))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/<sport>/feature-stats')
def api_feature_stats(sport):
    """Get feature statistics for a sport."""
    if sport not in SPORTS_CONFIG:
        return jsonify({'error': 'Invalid sport'}), 400
    try:
        return jsonify(get_feature_stats(sport))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/<sport>/scoreboard')
def api_scoreboard(sport):
    """Get ESPN scoreboard for a sport."""
    if sport not in SPORTS_CONFIG:
        return jsonify({'error': 'Invalid sport'}), 400
    try:
        return jsonify(get_espn_scoreboard(sport))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/<sport>/run-script', methods=['POST'])
def api_run_script(sport):
    """Execute a script for a specific sport."""
    if sport not in SPORTS_CONFIG:
        return jsonify({'success': False, 'error': 'Invalid sport'}), 400

    data = request.get_json()
    script_name = data.get('script')

    if not script_name:
        return jsonify({'success': False, 'error': 'No script specified'}), 400

    # Check if script is allowed for this sport
    if script_name not in SPORTS_CONFIG[sport]['scripts']:
        return jsonify({'success': False, 'error': 'Script not allowed for this sport'}), 403

    try:
        result = run_script(sport, script_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/<sport>/predictions/search')
def api_predictions_search(sport):
    """Search and filter predictions for a sport."""
    if sport not in SPORTS_CONFIG:
        return jsonify({'error': 'Invalid sport'}), 400

    player = request.args.get('player', '')
    prop_type = request.args.get('prop_type', '')
    outcome = request.args.get('outcome', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    limit = request.args.get('limit', 100, type=int)

    try:
        conn = get_db_connection(sport)
        cursor = conn.cursor()

        # Check which columns exist
        cursor.execute("PRAGMA table_info(prediction_outcomes)")
        columns = [col[1] for col in cursor.fetchall()]
        actual_col = 'actual_stat_value' if 'actual_stat_value' in columns else 'actual_value'

        query = f"""
            SELECT
                p.id,
                p.game_date,
                p.player_name,
                p.team,
                p.opponent,
                p.prop_type,
                p.line,
                p.prediction,
                p.probability,
                p.created_at,
                po.outcome,
                po.{actual_col} as actual_value
            FROM predictions p
            LEFT JOIN prediction_outcomes po ON p.id = po.prediction_id
            WHERE 1=1
        """
        params = []

        if player:
            query += " AND LOWER(p.player_name) LIKE ?"
            params.append(f'%{player.lower()}%')

        if prop_type:
            query += " AND p.prop_type = ?"
            params.append(prop_type)

        if outcome:
            query += " AND po.outcome = ?"
            params.append(outcome)

        if date_from:
            query += " AND p.game_date >= ?"
            params.append(date_from)

        if date_to:
            query += " AND p.game_date <= ?"
            params.append(date_to)

        query += " ORDER BY p.created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        predictions = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify(predictions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("=" * 70)
    print("MULTI-SPORT PREDICTION SYSTEM - DASHBOARD")
    print("=" * 70)
    print("\nConfigured Sports:")
    for sport_key, sport_config in SPORTS_CONFIG.items():
        print(f"\n  {sport_config['name']}:")
        print(f"    Database: {sport_config['db_path']}")
        print(f"    DB exists: {sport_config['db_path'].exists()}")
        print(f"    Project: {sport_config['project_root']}")
    print("\n" + "=" * 70)
    print(f"Dashboard starting at: http://localhost:5000")
    print("=" * 70)
    print()

    app.run(debug=True, host='0.0.0.0', port=5000)
