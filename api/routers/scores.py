"""
Live Scores Router
==================
Endpoints for real-time NBA and NHL scores.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Query, HTTPException

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'nba' / 'scripts'))
sys.path.insert(0, str(PROJECT_ROOT / 'nhl' / 'scripts'))

router = APIRouter()


def _format_time_local(time_str: str) -> str:
    """Format UTC time string to local time for display."""
    if not time_str:
        return ''
    try:
        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        local_dt = dt.astimezone()
        return local_dt.strftime('%I:%M %p')
    except:
        return time_str


def _determine_game_status(espn_status: str, start_time: str) -> str:
    """
    Determine actual game status by checking ESPN status AND start time.
    ESPN sometimes returns 'in_progress' for games that haven't started.
    """
    status = espn_status.lower().replace(' ', '_')

    # Final games are definitely final
    if status == 'final':
        return 'final'

    # For 'in_progress' status, verify by checking start time
    if status in ['in_progress', 'halftime']:
        if start_time:
            try:
                now = datetime.now(timezone.utc)
                game_start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                if now >= game_start:
                    return 'in_progress' if status == 'in_progress' else 'halftime'
                else:
                    return 'scheduled'  # Game hasn't actually started
            except:
                return status  # Can't parse time, trust ESPN
        return status

    # Otherwise it's scheduled
    return 'scheduled'


def get_nba_scores(date: str):
    """Fetch NBA scores from ESPN API."""
    try:
        from espn_nba_api import ESPNNBAApi

        api = ESPNNBAApi()
        games = api.get_scoreboard(date)

        result = []
        for game in games:
            start_time = game.get('start_date', '')
            espn_status = game.get('status', 'Scheduled')

            # Determine actual status (ESPN sometimes lies about in_progress)
            actual_status = _determine_game_status(espn_status, start_time)

            result.append({
                'game_id': game.get('espn_game_id', game.get('game_id')),
                'sport': 'NBA',
                'status': actual_status,
                'period': game.get('period', ''),
                'clock': game.get('clock', ''),
                'home_team': {
                    'abbreviation': game.get('home_team', ''),
                    'name': game.get('home_team_name', game.get('home_team', '')),
                    'score': game.get('home_score'),
                },
                'away_team': {
                    'abbreviation': game.get('away_team', ''),
                    'name': game.get('away_team_name', game.get('away_team', '')),
                    'score': game.get('away_score'),
                },
                'start_time': start_time,
                'start_time_local': _format_time_local(start_time),
                'broadcast': game.get('broadcasts', [''])[0] if game.get('broadcasts') else '',
                'venue': game.get('venue_name', ''),
            })
        return result
    except Exception as e:
        print(f"Error fetching NBA scores: {e}")
        return []


def get_nhl_scores(date: str):
    """Fetch NHL scores from NHL API."""
    try:
        import requests

        # NHL API endpoint
        url = f"https://api-web.nhle.com/v1/schedule/{date}"
        response = requests.get(url, timeout=30)

        if response.status_code != 200:
            return []

        data = response.json()
        result = []

        # Parse gameWeek structure
        for day in data.get('gameWeek', []):
            if day.get('date') != date:
                continue

            for game in day.get('games', []):
                # Determine status
                game_state = game.get('gameState', 'FUT')
                if game_state == 'FINAL' or game_state == 'OFF':
                    status = 'final'
                elif game_state == 'LIVE' or game_state == 'CRIT':
                    status = 'in_progress'
                else:
                    status = 'scheduled'

                # Get period info
                period_descriptor = game.get('periodDescriptor', {})
                period = period_descriptor.get('periodType', '')
                if period_descriptor.get('number'):
                    period = f"P{period_descriptor['number']}"

                clock = game.get('clock', {}).get('timeRemaining', '')

                away_team = game.get('awayTeam', {})
                home_team = game.get('homeTeam', {})

                start_time = game.get('startTimeUTC', '')

                result.append({
                    'game_id': str(game.get('id', '')),
                    'sport': 'NHL',
                    'status': status,
                    'period': period,
                    'clock': clock,
                    'home_team': {
                        'abbreviation': home_team.get('abbrev', ''),
                        'name': home_team.get('placeName', {}).get('default', ''),
                        'score': home_team.get('score'),
                    },
                    'away_team': {
                        'abbreviation': away_team.get('abbrev', ''),
                        'name': away_team.get('placeName', {}).get('default', ''),
                        'score': away_team.get('score'),
                    },
                    'start_time': start_time,
                    'start_time_local': _format_time_local(start_time),
                    'broadcast': '',
                    'venue': game.get('venue', {}).get('default', ''),
                })

        return result
    except Exception as e:
        print(f"Error fetching NHL scores: {e}")
        return []


@router.get("/live")
async def live_scores(
    sport: str = Query('all', description="Sport: 'nba', 'nhl', or 'all'"),
    date: Optional[str] = Query(None, description="Date YYYY-MM-DD (default: today)"),
):
    """
    Get live scores for NBA and/or NHL games.

    Returns game status, scores, period/clock for in-progress games.
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl', 'all']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba', 'nhl', or 'all'")

    # Default to today
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')

    games = []

    if sport in ['nba', 'all']:
        games.extend(get_nba_scores(date))

    if sport in ['nhl', 'all']:
        games.extend(get_nhl_scores(date))

    # Sort by status (in_progress first, then scheduled, then final)
    status_order = {'in_progress': 0, 'scheduled': 1, 'final': 2}
    games.sort(key=lambda g: status_order.get(g['status'], 3))

    return {
        "success": True,
        "timestamp": datetime.now().isoformat(),
        "date": date,
        "sport": sport.upper(),
        "total_games": len(games),
        "games": games,
        "summary": {
            "live": sum(1 for g in games if g['status'] == 'in_progress'),
            "scheduled": sum(1 for g in games if g['status'] == 'scheduled'),
            "final": sum(1 for g in games if g['status'] == 'final'),
        }
    }


@router.get("/game/{game_id}")
async def game_detail(game_id: str, sport: str = Query(...)):
    """Get detailed info for a specific game."""
    # For now, just return from the live scores
    scores = await live_scores(sport=sport)
    for game in scores['games']:
        if game['game_id'] == game_id:
            return {"success": True, "game": game}

    raise HTTPException(status_code=404, detail="Game not found")
