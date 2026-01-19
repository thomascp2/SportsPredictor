"""
Admin Router
============
Endpoints for running predictions, grading, and system management.
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Query, HTTPException, BackgroundTasks

PROJECT_ROOT = Path(__file__).parent.parent.parent

router = APIRouter()

# Track running tasks
running_tasks = {}


def run_prediction_pipeline(sport: str, date: str = None):
    """Run the prediction pipeline for a sport."""
    sport = sport.lower()

    if sport == 'nhl':
        script = PROJECT_ROOT / 'nhl' / 'scripts' / 'generate_predictions_daily_V5.py'
    else:
        script = PROJECT_ROOT / 'nba' / 'scripts' / 'generate_predictions_daily.py'

    cmd = [sys.executable, str(script)]
    if date:
        cmd.append(date)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=str(PROJECT_ROOT)
        )

        return {
            'success': result.returncode == 0,
            'stdout': result.stdout[-2000:] if result.stdout else '',  # Last 2000 chars
            'stderr': result.stderr[-1000:] if result.stderr else '',
            'return_code': result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Prediction pipeline timed out after 5 minutes',
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
        }


def run_grading_pipeline(sport: str, date: str = None):
    """Run the grading pipeline for a sport."""
    sport = sport.lower()

    if sport == 'nhl':
        script = PROJECT_ROOT / 'nhl' / 'scripts' / 'v2_auto_grade_yesterday_v3_RELIABLE.py'
    else:
        script = PROJECT_ROOT / 'nba' / 'scripts' / 'auto_grade_multi_api_FIXED.py'

    cmd = [sys.executable, str(script)]
    if date:
        cmd.append(date)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT)
        )

        return {
            'success': result.returncode == 0,
            'stdout': result.stdout[-2000:] if result.stdout else '',
            'stderr': result.stderr[-1000:] if result.stderr else '',
            'return_code': result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Grading pipeline timed out after 5 minutes',
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
        }


def refresh_prizepicks_lines(sport: str = 'all'):
    """Fetch fresh lines from PrizePicks."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / 'shared'))
        from prizepicks_client import PrizePicksIngestion

        ingestion = PrizePicksIngestion()

        if sport.lower() == 'all':
            result = ingestion.run_ingestion(['NHL', 'NBA'])
        else:
            result = ingestion.run_ingestion([sport.upper()])

        return {
            'success': True,
            'total_lines': result.get('total_lines', 0),
            'details': result,
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
        }


@router.post("/run-predictions")
async def run_predictions(
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    date: Optional[str] = Query(None, description="Date YYYY-MM-DD (default: today)"),
    background_tasks: BackgroundTasks = None,
):
    """
    Run the prediction pipeline for a sport.

    This generates new predictions for today's games.
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    if not date:
        date = datetime.now().strftime('%Y-%m-%d')

    # Run synchronously for now (could make async with background_tasks)
    result = run_prediction_pipeline(sport, date)

    return {
        "success": result['success'],
        "sport": sport.upper(),
        "date": date,
        "message": "Predictions generated successfully" if result['success'] else "Prediction pipeline failed",
        "details": result,
    }


@router.post("/run-grading")
async def run_grading(
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    date: Optional[str] = Query(None, description="Date YYYY-MM-DD (default: yesterday)"),
):
    """
    Run the grading pipeline for a sport.

    This grades yesterday's predictions against actual results.
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    result = run_grading_pipeline(sport, date)

    return {
        "success": result['success'],
        "sport": sport.upper(),
        "date": date or "yesterday",
        "message": "Grading completed successfully" if result['success'] else "Grading pipeline failed",
        "details": result,
    }


@router.post("/refresh-lines")
async def refresh_lines(
    sport: str = Query('all', description="Sport: 'nba', 'nhl', or 'all'"),
):
    """
    Fetch fresh PrizePicks lines.

    This updates the local database with current lines from PrizePicks.
    """
    result = refresh_prizepicks_lines(sport)

    return {
        "success": result['success'],
        "sport": sport.upper(),
        "message": f"Fetched {result.get('total_lines', 0)} lines" if result['success'] else "Failed to fetch lines",
        "details": result,
    }


@router.get("/status")
async def system_status():
    """Get overall system status."""
    import sqlite3

    status = {
        'api': 'online',
        'timestamp': datetime.now().isoformat(),
        'databases': {},
        'predictions': {},
    }

    # Check databases
    for sport in ['nba', 'nhl']:
        try:
            if sport == 'nhl':
                db_path = PROJECT_ROOT / 'nhl' / 'database' / 'nhl_predictions_v2.db'
            else:
                db_path = PROJECT_ROOT / 'nba' / 'database' / 'nba_predictions.db'

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Get counts
            cursor.execute("SELECT COUNT(*) FROM predictions")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT MAX(game_date) FROM predictions")
            latest = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM prediction_outcomes")
            graded = cursor.fetchone()[0]

            conn.close()

            status['databases'][sport] = 'connected'
            status['predictions'][sport] = {
                'total': total,
                'graded': graded,
                'latest_date': latest,
            }
        except Exception as e:
            status['databases'][sport] = f'error: {str(e)}'
            status['predictions'][sport] = None

    return status


@router.post("/clear-cache")
async def clear_cache():
    """Clear the API cache."""
    from api.services.cache import cache

    count = cache.clear()
    return {
        "success": True,
        "message": f"Cleared {count} cache entries",
    }


@router.get("/cache-stats")
async def cache_stats():
    """Get cache statistics."""
    from api.services.cache import cache

    return {
        "success": True,
        "stats": cache.stats(),
    }
