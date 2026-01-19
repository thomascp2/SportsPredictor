"""
Game Schedule Service
=====================
Fetches game schedules and times from NHL/NBA APIs.
"""

import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional
from .cache import cache

# NBA team abbreviation mapping (ESPN -> Standard)
NBA_TEAM_MAP = {
    'WSH': 'WAS',
    'NY': 'NYK',
    'SA': 'SAS',
    'UTAH': 'UTA',
    'GS': 'GSW',
    'NO': 'NOP',
    'PHX': 'PHO',
}

# Reverse mapping (Standard -> ESPN)
NBA_TEAM_MAP_REVERSE = {v: k for k, v in NBA_TEAM_MAP.items()}


def get_nhl_schedule(date: str) -> Dict[str, dict]:
    """
    Get NHL game schedule for a date.
    Returns dict mapping team abbreviation to game info.
    """
    cache_key = f"nhl_schedule:{date}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        url = f"https://api-web.nhle.com/v1/schedule/{date}"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return {}

        data = response.json()
        games = {}

        for day in data.get('gameWeek', []):
            if day.get('date') != date:
                continue

            for game in day.get('games', []):
                game_state = game.get('gameState', 'FUT')
                start_time = game.get('startTimeUTC', '')

                away_team = game.get('awayTeam', {}).get('abbrev', '')
                home_team = game.get('homeTeam', {}).get('abbrev', '')

                # Determine if game has started
                has_started = game_state in ['LIVE', 'CRIT', 'FINAL', 'OFF']

                game_info = {
                    'game_id': game.get('id'),
                    'start_time': start_time,
                    'start_time_local': _utc_to_local(start_time),
                    'has_started': has_started,
                    'game_state': game_state,
                    'home_team': home_team,
                    'away_team': away_team,
                    'venue': game.get('venue', {}).get('default', ''),
                }

                # Map both teams to this game
                games[away_team] = game_info
                games[home_team] = game_info

        cache.set(cache_key, games, 300)  # Cache for 5 minutes
        return games

    except Exception as e:
        print(f"Error fetching NHL schedule: {e}")
        return {}


def get_nba_schedule(date: str) -> Dict[str, dict]:
    """
    Get NBA game schedule for a date.
    Returns dict mapping team abbreviation to game info.
    """
    cache_key = f"nba_schedule:{date}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        # Use ESPN API for NBA schedule
        from pathlib import Path
        import sys

        PROJECT_ROOT = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(PROJECT_ROOT / 'nba' / 'scripts'))

        from espn_nba_api import ESPNNBAApi

        api = ESPNNBAApi()
        scoreboard = api.get_scoreboard(date)

        games = {}

        for game in scoreboard:
            start_time = game.get('start_date', '')
            status = game.get('status', '').lower()

            # Determine if game has started
            has_started = status in ['in_progress', 'in progress', 'final', 'halftime']

            away_team_raw = game.get('away_team', '')
            home_team_raw = game.get('home_team', '')

            # Normalize team abbreviations
            away_team = NBA_TEAM_MAP.get(away_team_raw, away_team_raw)
            home_team = NBA_TEAM_MAP.get(home_team_raw, home_team_raw)

            game_info = {
                'game_id': game.get('espn_game_id'),
                'start_time': start_time,
                'start_time_local': _format_espn_time(start_time),
                'has_started': has_started,
                'game_state': status,
                'home_team': home_team,
                'away_team': away_team,
                'venue': game.get('venue_name', ''),
            }

            # Map both teams to this game (using normalized abbreviations)
            if away_team:
                games[away_team] = game_info
                # Also map raw abbreviation if different
                if away_team_raw != away_team:
                    games[away_team_raw] = game_info
            if home_team:
                games[home_team] = game_info
                # Also map raw abbreviation if different
                if home_team_raw != home_team:
                    games[home_team_raw] = game_info

        cache.set(cache_key, games, 300)  # Cache for 5 minutes
        return games

    except Exception as e:
        print(f"Error fetching NBA schedule: {e}")
        return {}


def _utc_to_local(utc_str: str) -> str:
    """Convert UTC time string to local time display."""
    if not utc_str:
        return ''

    try:
        # Parse ISO format: 2025-01-19T19:00:00Z
        dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
        # Convert to local time
        local_dt = dt.astimezone()
        # Format for display
        return local_dt.strftime('%I:%M %p')
    except:
        return utc_str


def _format_espn_time(time_str: str) -> str:
    """Format ESPN time string for display."""
    if not time_str:
        return ''

    try:
        # ESPN format: 2025-01-19T19:00Z
        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        local_dt = dt.astimezone()
        return local_dt.strftime('%I:%M %p')
    except:
        return time_str


def get_schedule(sport: str, date: str) -> Dict[str, dict]:
    """Get game schedule for a sport."""
    if sport.lower() == 'nhl':
        return get_nhl_schedule(date)
    else:
        return get_nba_schedule(date)
