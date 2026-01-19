"""
Players Router
==============
Endpoints for player search and prediction history.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Query, HTTPException

from api.config import DB_PATHS

router = APIRouter()


def get_db_connection(sport: str):
    """Get database connection for a sport."""
    db_path = DB_PATHS.get(sport.lower())
    if not db_path or not db_path.exists():
        raise HTTPException(status_code=404, detail=f"Database not found for {sport}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/search")
async def search_players(
    query: str = Query(..., min_length=2, description="Search query (min 2 chars)"),
    sport: Optional[str] = Query(None, description="Filter by sport: 'nba' or 'nhl'"),
    limit: int = Query(20, description="Max results to return"),
):
    """
    Search players by name across NBA and NHL.

    Returns player name, team, prediction count, and accuracy.
    """
    results = []

    sports_to_search = [sport.lower()] if sport else ['nba', 'nhl']

    for sp in sports_to_search:
        if sp not in ['nba', 'nhl']:
            continue

        try:
            conn = get_db_connection(sp)
            cursor = conn.cursor()

            # Search in prediction_outcomes for players with results
            cursor.execute("""
                SELECT
                    player_name,
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits,
                    MAX(game_date) as last_game
                FROM prediction_outcomes
                WHERE LOWER(player_name) LIKE LOWER(?)
                GROUP BY player_name
                ORDER BY total DESC
                LIMIT ?
            """, (f'%{query}%', limit))

            for row in cursor.fetchall():
                total = row['total']
                hits = row['hits']
                results.append({
                    'player_name': row['player_name'],
                    'sport': sp.upper(),
                    'total_predictions': total,
                    'accuracy': round(hits / total * 100, 2) if total > 0 else 0,
                    'last_game_date': row['last_game'],
                })

            conn.close()
        except Exception as e:
            print(f"Error searching {sp}: {e}")

    # Sort by total predictions
    results.sort(key=lambda x: x['total_predictions'], reverse=True)

    return {
        "success": True,
        "query": query,
        "total_results": len(results[:limit]),
        "players": results[:limit],
    }


def find_player_name(cursor, player_name: str, sport: str) -> Optional[str]:
    """
    Find the actual player name in the database.
    Handles mismatches like 'Cale Makar' vs 'C. Makar'.
    """
    # First try exact match
    cursor.execute("""
        SELECT DISTINCT player_name FROM prediction_outcomes
        WHERE LOWER(player_name) = LOWER(?)
    """, (player_name,))
    row = cursor.fetchone()
    if row:
        return row[0]

    # For NHL, try matching by last name (PrizePicks uses full names, NHL API uses abbreviated)
    if sport == 'nhl':
        # Extract last name from the full name
        parts = player_name.split()
        if len(parts) >= 2:
            last_name = parts[-1]
            first_initial = parts[0][0] + '.'

            # Try "F. Lastname" format
            cursor.execute("""
                SELECT DISTINCT player_name FROM prediction_outcomes
                WHERE LOWER(player_name) = LOWER(?)
            """, (f"{first_initial} {last_name}",))
            row = cursor.fetchone()
            if row:
                return row[0]

            # Try just matching by last name if unique
            cursor.execute("""
                SELECT player_name, COUNT(*) as cnt FROM prediction_outcomes
                WHERE LOWER(player_name) LIKE LOWER(?)
                GROUP BY player_name
            """, (f"%. {last_name}",))
            rows = cursor.fetchall()
            if len(rows) == 1:
                return rows[0][0]

    # Also check predictions table (player may not have outcomes yet)
    cursor.execute("""
        SELECT DISTINCT player_name FROM predictions
        WHERE LOWER(player_name) = LOWER(?)
    """, (player_name,))
    row = cursor.fetchone()
    if row:
        return row[0]

    return None


@router.get("/{player_name}/history")
async def player_history(
    player_name: str,
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    prop_type: Optional[str] = Query(None, description="Filter by prop type"),
    limit: int = Query(50, description="Max predictions to return"),
):
    """
    Get prediction history for a specific player.

    Returns all predictions with outcomes, grouped by prop type.
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    conn = get_db_connection(sport)
    cursor = conn.cursor()

    try:
        # Find the actual player name in the database (handles name format mismatches)
        actual_name = find_player_name(cursor, player_name, sport)
        if not actual_name:
            raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

        # Get player's overall stats
        cursor.execute("""
            SELECT
                player_name,
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
            FROM prediction_outcomes
            WHERE LOWER(player_name) = LOWER(?)
            GROUP BY player_name
        """, (actual_name,))

        row = cursor.fetchone()
        if not row:
            # Player exists in predictions but has no graded outcomes yet
            return {
                "success": True,
                "player_name": player_name,
                "sport": sport.upper(),
                "overall": {
                    'total_predictions': 0,
                    'accuracy': 0,
                    'hits': 0,
                },
                "by_prop_type": {},
                "predictions": [],
                "message": "No graded predictions yet for this player"
            }

        total = row['total']
        hits = row['hits']

        # Get breakdown by prop type
        cursor.execute("""
            SELECT
                prop_type,
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
            FROM prediction_outcomes
            WHERE LOWER(player_name) = LOWER(?)
            GROUP BY prop_type
            ORDER BY total DESC
        """, (actual_name,))

        by_prop_type = {}
        for r in cursor.fetchall():
            prop = r['prop_type']
            prop_total = r['total']
            prop_hits = r['hits']
            by_prop_type[prop] = {
                'accuracy': round(prop_hits / prop_total * 100, 2) if prop_total > 0 else 0,
                'total': prop_total,
                'hits': prop_hits,
            }

        # Get recent predictions (column names differ between NHL and NBA)
        if sport == 'nhl':
            # NHL uses: predicted_outcome, actual_stat_value
            query = """
                SELECT
                    game_date,
                    prop_type,
                    line,
                    predicted_outcome as prediction,
                    actual_stat_value as actual_value,
                    outcome
                FROM prediction_outcomes
                WHERE LOWER(player_name) = LOWER(?)
            """
        else:
            # NBA uses: prediction, actual_value
            query = """
                SELECT
                    game_date,
                    prop_type,
                    line,
                    prediction,
                    actual_value,
                    outcome
                FROM prediction_outcomes
                WHERE LOWER(player_name) = LOWER(?)
            """
        params = [actual_name]

        if prop_type:
            query += " AND LOWER(prop_type) = LOWER(?)"
            params.append(prop_type)

        query += " ORDER BY game_date DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)

        predictions = []
        for r in cursor.fetchall():
            predictions.append({
                'date': r['game_date'],
                'prop_type': r['prop_type'],
                'line': r['line'],
                'prediction': r['prediction'],
                'actual_value': r['actual_value'],
                'outcome': r['outcome'],
            })

        return {
            "success": True,
            "player_name": row['player_name'],
            "sport": sport.upper(),
            "overall": {
                'total_predictions': total,
                'accuracy': round(hits / total * 100, 2) if total > 0 else 0,
                'hits': hits,
            },
            "by_prop_type": by_prop_type,
            "predictions": predictions,
        }

    finally:
        conn.close()


@router.get("/{player_name}/stats")
async def player_stats(
    player_name: str,
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    games: int = Query(10, description="Number of recent games"),
):
    """
    Get player's recent game stats.

    Returns stats from player_game_logs table.
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    conn = get_db_connection(sport)
    cursor = conn.cursor()

    try:
        if sport == 'nba':
            cursor.execute("""
                SELECT
                    game_date, team, opponent, home_away,
                    minutes, points, rebounds, assists,
                    steals, blocks, turnovers, threes_made,
                    pra, stocks
                FROM player_game_logs
                WHERE LOWER(player_name) = LOWER(?)
                ORDER BY game_date DESC
                LIMIT ?
            """, (player_name, games))
        else:
            cursor.execute("""
                SELECT
                    game_date, team, opponent, home_away,
                    goals, assists, points, shots_on_goal,
                    toi_seconds, plus_minus
                FROM player_game_logs
                WHERE LOWER(player_name) = LOWER(?)
                ORDER BY game_date DESC
                LIMIT ?
            """, (player_name, games))

        logs = []
        for row in cursor.fetchall():
            log = dict(row)
            logs.append(log)

        if not logs:
            raise HTTPException(status_code=404, detail=f"No game logs found for '{player_name}'")

        # Calculate averages
        if sport == 'nba':
            avg_points = sum(l.get('points', 0) or 0 for l in logs) / len(logs)
            avg_rebounds = sum(l.get('rebounds', 0) or 0 for l in logs) / len(logs)
            avg_assists = sum(l.get('assists', 0) or 0 for l in logs) / len(logs)
            averages = {
                'points': round(avg_points, 1),
                'rebounds': round(avg_rebounds, 1),
                'assists': round(avg_assists, 1),
            }
        else:
            avg_points = sum(l.get('points', 0) or 0 for l in logs) / len(logs)
            avg_shots = sum(l.get('shots_on_goal', 0) or 0 for l in logs) / len(logs)
            averages = {
                'points': round(avg_points, 2),
                'shots': round(avg_shots, 1),
            }

        return {
            "success": True,
            "player_name": player_name,
            "sport": sport.upper(),
            "games_returned": len(logs),
            "averages": averages,
            "game_logs": logs,
        }

    finally:
        conn.close()
