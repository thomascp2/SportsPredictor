"""
Smart Picks Router
==================
Endpoints for today's predictions with PrizePicks lines.
Includes game times and filters out started games.
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'shared'))

from api.services.schedule import get_schedule
from api.services.cache import cache

router = APIRouter()


def get_smart_picks(sport: str, date: str = None, min_edge: float = 5.0, min_prob: float = 0.55):
    """Fetch smart picks using SmartPickSelector."""
    try:
        from smart_pick_selector import SmartPickSelector

        selector = SmartPickSelector(sport)
        picks = selector.get_smart_picks(
            game_date=date,
            min_edge=min_edge,
            min_prob=min_prob,
            refresh_lines=False  # Don't refresh on every request
        )

        # Convert to dicts
        result = []
        for pick in picks:
            result.append({
                'player_name': pick.player_name,
                'team': pick.team,
                'opponent': pick.opponent,
                'prop_type': pick.prop_type,
                'pp_line': pick.pp_line,
                'pp_probability': round(pick.pp_probability, 4),
                'prediction': pick.prediction,
                'edge': round(pick.edge, 2),
                'tier': pick.tier,
                'pp_odds_type': pick.pp_odds_type,
                'leg_value': pick.leg_value,
                'our_line': pick.our_line,
                'our_probability': round(pick.our_probability, 4),
                'ev_2leg': round(pick.ev_2leg, 4) if pick.ev_2leg else 0,
                'ev_3leg': round(pick.ev_3leg, 4) if pick.ev_3leg else 0,
                'ev_4leg': round(pick.ev_4leg, 4) if pick.ev_4leg else 0,
                'ev_5leg': round(pick.ev_5leg, 4) if pick.ev_5leg else 0,
                'ev_6leg': round(pick.ev_6leg, 4) if pick.ev_6leg else 0,
            })

        return result
    except Exception as e:
        print(f"Error getting smart picks: {e}")
        import traceback
        traceback.print_exc()
        return []


def enrich_with_game_times(picks: list, sport: str, date: str) -> list:
    """Add game time information to picks and filter out started games."""
    schedule = get_schedule(sport, date)

    enriched = []
    for pick in picks:
        team = pick.get('team', '')

        # Look up game info for this team
        game_info = schedule.get(team, {})

        if game_info:
            pick['game_time'] = game_info.get('start_time_local', '')
            pick['game_time_utc'] = game_info.get('start_time', '')
            pick['has_started'] = game_info.get('has_started', False)
            pick['game_state'] = game_info.get('game_state', 'FUT')
            pick['venue'] = game_info.get('venue', '')
            pick['matchup'] = f"{game_info.get('away_team', '')} @ {game_info.get('home_team', '')}"
        else:
            pick['game_time'] = ''
            pick['game_time_utc'] = ''
            pick['has_started'] = False
            pick['game_state'] = 'UNKNOWN'
            pick['venue'] = ''
            pick['matchup'] = f"{pick.get('team', '')} vs {pick.get('opponent', '')}"

        enriched.append(pick)

    return enriched


def sort_picks(picks: list, sort_by: str) -> list:
    """Sort picks by various criteria."""
    if sort_by == 'edge':
        return sorted(picks, key=lambda x: x.get('edge', 0), reverse=True)
    elif sort_by == 'probability':
        return sorted(picks, key=lambda x: x.get('pp_probability', 0), reverse=True)
    elif sort_by == 'game_time':
        return sorted(picks, key=lambda x: x.get('game_time_utc', '') or 'ZZZ')
    elif sort_by == 'team':
        return sorted(picks, key=lambda x: x.get('team', ''))
    elif sort_by == 'player':
        return sorted(picks, key=lambda x: x.get('player_name', ''))
    elif sort_by == 'tier':
        tier_order = {'T1-ELITE': 0, 'T2-STRONG': 1, 'T3-GOOD': 2, 'T4-LEAN': 3, 'T5-FADE': 4}
        return sorted(picks, key=lambda x: tier_order.get(x.get('tier', 'T5-FADE'), 5))
    else:
        return picks


def group_picks_by_game(picks: list) -> dict:
    """Group picks by game/matchup."""
    games = {}
    for pick in picks:
        matchup = pick.get('matchup', 'Unknown')
        if matchup not in games:
            games[matchup] = {
                'matchup': matchup,
                'game_time': pick.get('game_time', ''),
                'has_started': pick.get('has_started', False),
                'picks': []
            }
        games[matchup]['picks'].append(pick)

    return list(games.values())


@router.get("/smart")
async def smart_picks(
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    date: Optional[str] = Query(None, description="Date YYYY-MM-DD (default: today)"),
    min_edge: float = Query(5.0, description="Minimum edge percentage"),
    min_prob: float = Query(0.55, description="Minimum probability"),
    tier: Optional[str] = Query(None, description="Filter by tier (e.g., 'T1-ELITE,T2-STRONG')"),
    odds_type: Optional[str] = Query(None, description="Filter by odds type (e.g., 'standard,goblin')"),
    prediction: Optional[str] = Query(None, description="Filter by prediction ('OVER' or 'UNDER')"),
    team: Optional[str] = Query(None, description="Filter by team abbreviation"),
    hide_started: bool = Query(True, description="Hide picks from games that have started"),
    sort_by: str = Query('edge', description="Sort by: edge, probability, game_time, team, player, tier"),
    group_by_game: bool = Query(False, description="Group picks by game"),
):
    """
    Get today's smart picks with PrizePicks lines.

    Returns predictions that exist on PrizePicks with calculated edge and EV.
    Includes game times and filters out started games by default.
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    # Default to today
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')

    # Check cache first
    cache_key = f"picks:{sport}:{date}:{min_edge}:{min_prob}"
    cached_picks = cache.get(cache_key)

    if cached_picks:
        picks = cached_picks
    else:
        picks = get_smart_picks(sport, date, min_edge, min_prob)
        cache.set(cache_key, picks, 300)  # Cache for 5 minutes

    # Enrich with game times
    picks = enrich_with_game_times(picks, sport, date)

    # Filter out started games if requested
    if hide_started:
        picks = [p for p in picks if not p.get('has_started', False)]

    # Apply filters
    if tier:
        allowed_tiers = [t.strip().upper() for t in tier.split(',')]
        picks = [p for p in picks if p['tier'] in allowed_tiers]

    if odds_type:
        allowed_types = [t.strip().lower() for t in odds_type.split(',')]
        picks = [p for p in picks if p['pp_odds_type'] in allowed_types]

    if prediction:
        picks = [p for p in picks if p['prediction'].upper() == prediction.upper()]

    if team:
        team = team.upper()
        picks = [p for p in picks if p.get('team', '').upper() == team or p.get('opponent', '').upper() == team]

    # Sort
    picks = sort_picks(picks, sort_by)

    # Calculate summary
    if picks:
        avg_prob = sum(p['pp_probability'] for p in picks) / len(picks)
        avg_edge = sum(p['edge'] for p in picks) / len(picks)
        tier_counts = {}
        for p in picks:
            tier_counts[p['tier']] = tier_counts.get(p['tier'], 0) + 1

        # Get unique games
        games = set(p.get('matchup', '') for p in picks)
    else:
        avg_prob = 0
        avg_edge = 0
        tier_counts = {}
        games = set()

    # Group by game if requested
    if group_by_game:
        grouped = group_picks_by_game(picks)
        return {
            "success": True,
            "date": date,
            "sport": sport.upper(),
            "total_picks": len(picks),
            "total_games": len(games),
            "games": grouped,
            "summary": {
                "avg_probability": round(avg_prob, 4),
                "avg_edge": round(avg_edge, 2),
                "by_tier": tier_counts
            }
        }

    return {
        "success": True,
        "date": date,
        "sport": sport.upper(),
        "total_picks": len(picks),
        "total_games": len(games),
        "picks": picks,
        "summary": {
            "avg_probability": round(avg_prob, 4),
            "avg_edge": round(avg_edge, 2),
            "by_tier": tier_counts
        }
    }


@router.get("/today")
async def today_picks(
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    hide_started: bool = Query(True, description="Hide picks from games that have started"),
    sort_by: str = Query('edge', description="Sort by: edge, probability, game_time, team, player, tier"),
):
    """Shortcut for today's picks with default filters. Only shows upcoming games."""
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    date = datetime.now().strftime('%Y-%m-%d')

    # Check cache
    cache_key = f"today:{sport}:{date}"
    cached_picks = cache.get(cache_key)

    if cached_picks:
        picks = cached_picks
    else:
        picks = get_smart_picks(sport, date, min_edge=0, min_prob=0.5)
        cache.set(cache_key, picks, 300)

    # Enrich with game times
    picks = enrich_with_game_times(picks, sport, date)

    # Filter out started games
    if hide_started:
        picks = [p for p in picks if not p.get('has_started', False)]

    # Sort
    picks = sort_picks(picks, sort_by)

    # Calculate summary
    if picks:
        avg_prob = sum(p['pp_probability'] for p in picks) / len(picks)
        avg_edge = sum(p['edge'] for p in picks) / len(picks)
        tier_counts = {}
        for p in picks:
            tier_counts[p['tier']] = tier_counts.get(p['tier'], 0) + 1
        games = set(p.get('matchup', '') for p in picks)
    else:
        avg_prob = 0
        avg_edge = 0
        tier_counts = {}
        games = set()

    return {
        "success": True,
        "date": date,
        "sport": sport.upper(),
        "total_picks": len(picks),
        "total_games": len(games),
        "picks": picks,
        "summary": {
            "avg_probability": round(avg_prob, 4),
            "avg_edge": round(avg_edge, 2),
            "by_tier": tier_counts
        }
    }


@router.get("/games")
async def picks_by_game(
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    hide_started: bool = Query(True, description="Hide games that have started"),
):
    """Get picks grouped by game. Great for viewing one game at a time."""
    date = datetime.now().strftime('%Y-%m-%d')

    # Reuse smart_picks with grouping
    return await smart_picks(
        sport=sport,
        date=date,
        min_edge=0,
        min_prob=0.5,
        hide_started=hide_started,
        sort_by='game_time',
        group_by_game=True,
    )


@router.get("/game/{matchup}")
async def picks_for_game(
    matchup: str,
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
):
    """Get all picks for a specific game matchup (e.g., 'BOS @ NYR')."""
    date = datetime.now().strftime('%Y-%m-%d')
    sport = sport.lower()

    picks = get_smart_picks(sport, date, min_edge=0, min_prob=0.5)
    picks = enrich_with_game_times(picks, sport, date)

    # Filter to this matchup
    matchup = matchup.upper().replace(' ', '')
    filtered = [p for p in picks if p.get('matchup', '').upper().replace(' ', '') == matchup]

    # Sort by edge
    filtered = sort_picks(filtered, 'edge')

    return {
        "success": True,
        "matchup": matchup,
        "sport": sport.upper(),
        "total_picks": len(filtered),
        "picks": filtered,
    }
