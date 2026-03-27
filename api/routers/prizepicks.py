"""
PrizePicks Router
=================
Endpoints for PrizePicks cache status and line management.
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Query

from api.config import DB_PATHS

router = APIRouter()


@router.get("/status")
async def prizepicks_status(
    sport: str = Query(None, description="Filter by sport (e.g. 'nba')")
):
    """
    Check PrizePicks cache status.

    Returns last ingestion time, line count, staleness flag, and breakdown by sport/prop.
    """
    db_path = DB_PATHS.get('prizepicks')

    if not db_path or not db_path.exists():
        return {
            "success": False,
            "cached": False,
            "message": "PrizePicks database not found. Run /api/admin/refresh-lines first.",
            "lines_count": 0,
        }

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        today = datetime.now().strftime('%Y-%m-%d')

        sport_filter = ""
        params: list = [today]
        if sport:
            sport_filter = "AND LOWER(sport) = LOWER(?)"
            params.append(sport)

        # Total lines and fetch timestamps for today
        cursor.execute(f"""
            SELECT
                COUNT(*) as total,
                MAX(fetched_at) as last_fetched
            FROM prizepicks_lines
            WHERE DATE(fetched_at) = ? {sport_filter}
        """, params)
        row = cursor.fetchone()

        total = row['total'] if row else 0
        last_fetched = row['last_fetched'] if row else None

        # By sport
        cursor.execute(f"""
            SELECT sport, COUNT(*) as count
            FROM prizepicks_lines
            WHERE DATE(fetched_at) = ? {sport_filter}
            GROUP BY sport
            ORDER BY count DESC
        """, params)
        by_sport = {r['sport']: r['count'] for r in cursor.fetchall()}

        # By prop type
        cursor.execute(f"""
            SELECT prop_type, COUNT(*) as count
            FROM prizepicks_lines
            WHERE DATE(fetched_at) = ? {sport_filter}
            GROUP BY prop_type
            ORDER BY count DESC
        """, params)
        by_prop = {r['prop_type']: r['count'] for r in cursor.fetchall()}

        conn.close()

        # Determine staleness
        is_stale = True
        minutes_old = None
        if last_fetched:
            try:
                fetched_dt = datetime.fromisoformat(last_fetched.replace('Z', '+00:00').split('+')[0])
                minutes_old = (datetime.now() - fetched_dt).total_seconds() / 60
                is_stale = minutes_old > 30
            except Exception:
                pass

        return {
            "success": True,
            "cached": total > 0,
            "date": today,
            "lines_count": total,
            "last_fetched_at": last_fetched,
            "minutes_old": round(minutes_old, 1) if minutes_old is not None else None,
            "is_stale": is_stale,
            "by_sport": by_sport,
            "by_prop_type": by_prop,
        }

    except Exception as e:
        return {
            "success": False,
            "cached": False,
            "message": str(e),
            "lines_count": 0,
        }
