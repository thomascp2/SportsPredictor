"""
Performance Router
==================
Endpoints for accuracy metrics, trends, and system health.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Query, HTTPException

from api.config import DB_PATHS, BREAK_EVEN_RATES

router = APIRouter()


def get_db_connection(sport: str):
    """Get database connection for a sport."""
    db_path = DB_PATHS.get(sport.lower())
    if not db_path or not db_path.exists():
        raise HTTPException(status_code=404, detail=f"Database not found for {sport}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/overview")
async def performance_overview(
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    days: int = Query(14, description="Days of history for trending"),
):
    """
    Get comprehensive performance metrics.

    Returns overall accuracy, prop-type breakdown, tier breakdown, and daily trend.
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    conn = get_db_connection(sport)
    cursor = conn.cursor()

    try:
        # Column name differs between sports: NBA uses 'prediction', NHL uses 'predicted_outcome'
        pred_col = 'predicted_outcome' if sport == 'nhl' else 'prediction'

        # Overall metrics
        cursor.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits,
                SUM(CASE WHEN {pred_col} = 'OVER' THEN 1 ELSE 0 END) as over_count,
                SUM(CASE WHEN {pred_col} = 'OVER' AND outcome = 'HIT' THEN 1 ELSE 0 END) as over_hits,
                SUM(CASE WHEN {pred_col} = 'UNDER' THEN 1 ELSE 0 END) as under_count,
                SUM(CASE WHEN {pred_col} = 'UNDER' AND outcome = 'HIT' THEN 1 ELSE 0 END) as under_hits
            FROM prediction_outcomes
        """)
        row = cursor.fetchone()

        total = row['total'] or 0
        hits = row['hits'] or 0
        over_count = row['over_count'] or 0
        over_hits = row['over_hits'] or 0
        under_count = row['under_count'] or 0
        under_hits = row['under_hits'] or 0

        overall = {
            'total_predictions': total,
            'total_graded': total,
            'accuracy': round(hits / total * 100, 2) if total > 0 else 0,
            'hit_count': hits,
            'over_accuracy': round(over_hits / over_count * 100, 2) if over_count > 0 else 0,
            'over_total': over_count,
            'under_accuracy': round(under_hits / under_count * 100, 2) if under_count > 0 else 0,
            'under_total': under_count,
        }

        # By prop type
        cursor.execute("""
            SELECT
                prop_type,
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
            FROM prediction_outcomes
            GROUP BY prop_type
            ORDER BY total DESC
        """)
        by_prop_type = {}
        for row in cursor.fetchall():
            prop = row['prop_type']
            total_prop = row['total']
            hits_prop = row['hits']
            by_prop_type[prop] = {
                'accuracy': round(hits_prop / total_prop * 100, 2) if total_prop > 0 else 0,
                'total': total_prop,
                'hits': hits_prop,
            }

        # By confidence tier (NHL has tiers, NBA may not)
        by_tier = {}
        if sport == 'nhl':
            cursor.execute("""
                SELECT
                    confidence_tier,
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
                FROM prediction_outcomes
                WHERE confidence_tier IS NOT NULL
                GROUP BY confidence_tier
                ORDER BY confidence_tier
            """)
            for row in cursor.fetchall():
                tier = row['confidence_tier']
                total_tier = row['total']
                hits_tier = row['hits']
                by_tier[tier] = {
                    'accuracy': round(hits_tier / total_tier * 100, 2) if total_tier > 0 else 0,
                    'total': total_tier,
                    'hits': hits_tier,
                }

        # Daily trend
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        cursor.execute("""
            SELECT
                game_date,
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
            FROM prediction_outcomes
            WHERE game_date >= ?
            GROUP BY game_date
            ORDER BY game_date DESC
        """, (start_date,))

        trending = []
        for row in cursor.fetchall():
            date = row['game_date']
            total_day = row['total']
            hits_day = row['hits']
            trending.append({
                'date': date,
                'accuracy': round(hits_day / total_day * 100, 2) if total_day > 0 else 0,
                'total': total_day,
                'hits': hits_day,
            })

        return {
            "success": True,
            "sport": sport.upper(),
            "overall": overall,
            "by_prop_type": by_prop_type,
            "by_tier": by_tier,
            "trending": trending,
        }

    finally:
        conn.close()


@router.get("/health")
async def system_health(sport: str = Query(...)):
    """Get system health metrics."""
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    conn = get_db_connection(sport)
    cursor = conn.cursor()

    try:
        # Total predictions
        cursor.execute("SELECT COUNT(*) FROM predictions")
        total_predictions = cursor.fetchone()[0]

        # Total graded
        cursor.execute("SELECT COUNT(*) FROM prediction_outcomes")
        total_graded = cursor.fetchone()[0]

        # Latest dates
        cursor.execute("SELECT MAX(game_date) FROM predictions")
        latest_prediction = cursor.fetchone()[0]

        cursor.execute("SELECT MAX(game_date) FROM prediction_outcomes")
        latest_graded = cursor.fetchone()[0]

        # Unique players
        cursor.execute("SELECT COUNT(DISTINCT player_name) FROM predictions")
        unique_players = cursor.fetchone()[0]

        return {
            "success": True,
            "sport": sport.upper(),
            "status": "HEALTHY",
            "metrics": {
                "total_predictions": total_predictions,
                "total_graded": total_graded,
                "grading_rate": round(total_graded / total_predictions * 100, 2) if total_predictions > 0 else 0,
                "unique_players": unique_players,
                "latest_prediction_date": latest_prediction,
                "latest_graded_date": latest_graded,
            }
        }

    finally:
        conn.close()


@router.get("/calibration")
async def calibration_check(sport: str = Query(...)):
    """
    Check prediction calibration.

    Compares predicted probabilities to actual hit rates.
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    conn = get_db_connection(sport)
    cursor = conn.cursor()

    try:
        # Get probability column name based on sport
        if sport == 'nhl':
            prob_col = 'predicted_probability'
        else:
            # NBA uses predictions table joined
            prob_col = 'p.probability'

        # Bucket predictions by probability range
        if sport == 'nhl':
            cursor.execute("""
                SELECT
                    CASE
                        WHEN predicted_probability < 0.55 THEN '50-55'
                        WHEN predicted_probability < 0.60 THEN '55-60'
                        WHEN predicted_probability < 0.65 THEN '60-65'
                        WHEN predicted_probability < 0.70 THEN '65-70'
                        ELSE '70+'
                    END as bucket,
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits,
                    AVG(predicted_probability) as avg_predicted
                FROM prediction_outcomes
                WHERE predicted_probability IS NOT NULL
                GROUP BY bucket
                ORDER BY bucket
            """)
        else:
            # NBA: join with predictions table
            cursor.execute("""
                SELECT
                    CASE
                        WHEN p.probability < 0.55 THEN '50-55'
                        WHEN p.probability < 0.60 THEN '55-60'
                        WHEN p.probability < 0.65 THEN '60-65'
                        WHEN p.probability < 0.70 THEN '65-70'
                        ELSE '70+'
                    END as bucket,
                    COUNT(*) as total,
                    SUM(CASE WHEN o.outcome = 'HIT' THEN 1 ELSE 0 END) as hits,
                    AVG(p.probability) as avg_predicted
                FROM prediction_outcomes o
                JOIN predictions p ON o.prediction_id = p.id
                WHERE p.probability IS NOT NULL
                GROUP BY bucket
                ORDER BY bucket
            """)

        calibration = []
        for row in cursor.fetchall():
            bucket = row['bucket'] if isinstance(row['bucket'], str) else row[0]
            total = row['total'] if isinstance(row['total'], int) else row[1]
            hits = row['hits'] if isinstance(row['hits'], int) else row[2]
            avg_pred = row['avg_predicted'] if 'avg_predicted' in row.keys() else row[3]

            actual_rate = hits / total if total > 0 else 0
            calibration.append({
                'bucket': bucket,
                'predicted': round(avg_pred * 100, 1) if avg_pred else 0,
                'actual': round(actual_rate * 100, 1),
                'count': total,
                'difference': round((actual_rate - (avg_pred or 0)) * 100, 1),
            })

        return {
            "success": True,
            "sport": sport.upper(),
            "calibration_curve": calibration,
        }

    finally:
        conn.close()


@router.get("/realized-edge")
async def realized_edge(
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    days: int = Query(30, description="Days of history to analyze"),
):
    """
    Compare predicted edge to realized (actual) edge per prop type.

    realized_edge = (hit_rate - break_even) * 100
    edge_ratio    = realized_edge / predicted_edge  (>1 = model underestimates, <1 = overestimates)

    Break-even values: standard=56.2%, goblin=76.0%, demon=44.7%
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    conn = get_db_connection(sport)
    cursor = conn.cursor()

    # Break-even per odds_type — imported from api.config (single source of truth).
    # Do NOT hardcode these values here; they must match smart_pick_selector and supabase_sync.
    BREAK_EVEN = BREAK_EVEN_RATES

    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        if sport == 'nba':
            # NBA: join prediction_outcomes ↔ predictions on player_name+prop_type+game_date
            # (no FK id link guaranteed in schema, so match on natural key)
            cursor.execute("""
                SELECT
                    o.prop_type,
                    COALESCE(p.odds_type, 'standard') AS odds_type,
                    COUNT(*) AS total,
                    SUM(CASE WHEN o.outcome = 'HIT' THEN 1 ELSE 0 END) AS hits,
                    AVG(p.probability) AS avg_predicted_prob
                FROM prediction_outcomes o
                LEFT JOIN predictions p
                    ON LOWER(o.player_name) = LOWER(p.player_name)
                    AND LOWER(o.prop_type) = LOWER(p.prop_type)
                    AND o.game_date = p.game_date
                WHERE o.game_date >= ?
                GROUP BY o.prop_type, odds_type
                HAVING total >= 10
                ORDER BY o.prop_type
            """, (cutoff,))
        else:
            # NHL: probability stored in prediction_outcomes.predicted_probability
            cursor.execute("""
                SELECT
                    prop_type,
                    'standard' AS odds_type,
                    COUNT(*) AS total,
                    SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) AS hits,
                    AVG(predicted_probability) AS avg_predicted_prob
                FROM prediction_outcomes
                WHERE game_date >= ?
                GROUP BY prop_type
                HAVING total >= 10
                ORDER BY prop_type
            """, (cutoff,))

        results = []
        for row in cursor.fetchall():
            prop_type = row[0]
            odds_type = row[1] or 'standard'
            total = row[2]
            hits = row[3] or 0
            avg_pred = row[4] or 0.5  # neutral midpoint fallback — not a break-even proxy

            hit_rate = hits / total if total > 0 else 0
            break_even = BREAK_EVEN.get(odds_type, BREAK_EVEN_RATES['standard'])
            predicted_edge = (avg_pred - break_even) * 100
            realized_edge_val = (hit_rate - break_even) * 100

            edge_ratio = (
                round(realized_edge_val / predicted_edge, 3)
                if abs(predicted_edge) > 0.5 else None
            )

            results.append({
                'prop_type': prop_type,
                'odds_type': odds_type,
                'total_graded': total,
                'hit_rate': round(hit_rate * 100, 1),
                'avg_predicted_prob': round(avg_pred * 100, 1),
                'break_even': round(break_even * 100, 1),
                'predicted_edge': round(predicted_edge, 2),
                'realized_edge': round(realized_edge_val, 2),
                'edge_ratio': edge_ratio,
            })

        # Sort by edge_ratio descending (best-calibrated markets first)
        results.sort(key=lambda x: (x['edge_ratio'] or 0), reverse=True)

        return {
            "success": True,
            "sport": sport.upper(),
            "days": days,
            "results": results,
        }

    finally:
        conn.close()
