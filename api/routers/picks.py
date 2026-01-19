"""
Smart Picks Router
==================
Endpoints for today's predictions with PrizePicks lines.
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Query, HTTPException

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'shared'))

router = APIRouter()


def get_smart_picks(sport: str, date: str = None, min_edge: float = 5.0, min_prob: float = 0.55):
    """Fetch smart picks using SmartPickSelector."""
    try:
        from smart_pick_selector import SmartPickSelector

        selector = SmartPickSelector(sport)
        picks = selector.get_smart_picks(
            game_date=date,
            min_edge=min_edge,
            min_prob=min_prob
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
        return []


@router.get("/smart")
async def smart_picks(
    sport: str = Query(..., description="Sport: 'nba' or 'nhl'"),
    date: Optional[str] = Query(None, description="Date YYYY-MM-DD (default: today)"),
    min_edge: float = Query(5.0, description="Minimum edge percentage"),
    min_prob: float = Query(0.55, description="Minimum probability"),
    tier: Optional[str] = Query(None, description="Filter by tier (e.g., 'T1-ELITE,T2-STRONG')"),
    odds_type: Optional[str] = Query(None, description="Filter by odds type (e.g., 'standard,goblin')"),
    prediction: Optional[str] = Query(None, description="Filter by prediction ('OVER' or 'UNDER')"),
):
    """
    Get today's smart picks with PrizePicks lines.

    Returns predictions that exist on PrizePicks with calculated edge and EV.
    """
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    # Default to today
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')

    # Get picks
    picks = get_smart_picks(sport, date, min_edge, min_prob)

    # Apply filters
    if tier:
        allowed_tiers = [t.strip().upper() for t in tier.split(',')]
        picks = [p for p in picks if p['tier'] in allowed_tiers]

    if odds_type:
        allowed_types = [t.strip().lower() for t in odds_type.split(',')]
        picks = [p for p in picks if p['pp_odds_type'] in allowed_types]

    if prediction:
        picks = [p for p in picks if p['prediction'].upper() == prediction.upper()]

    # Calculate summary
    if picks:
        avg_prob = sum(p['pp_probability'] for p in picks) / len(picks)
        avg_edge = sum(p['edge'] for p in picks) / len(picks)
        tier_counts = {}
        for p in picks:
            tier_counts[p['tier']] = tier_counts.get(p['tier'], 0) + 1
    else:
        avg_prob = 0
        avg_edge = 0
        tier_counts = {}

    return {
        "success": True,
        "date": date,
        "sport": sport.upper(),
        "total_picks": len(picks),
        "picks": picks,
        "summary": {
            "avg_probability": round(avg_prob, 4),
            "avg_edge": round(avg_edge, 2),
            "by_tier": tier_counts
        }
    }


@router.get("/today")
async def today_picks(sport: str = Query(..., description="Sport: 'nba' or 'nhl'")):
    """Shortcut for today's picks with default filters."""
    sport = sport.lower()
    if sport not in ['nba', 'nhl']:
        raise HTTPException(status_code=400, detail="Sport must be 'nba' or 'nhl'")

    date = datetime.now().strftime('%Y-%m-%d')
    picks = get_smart_picks(sport, date, min_edge=0, min_prob=0.5)

    # Calculate summary
    if picks:
        avg_prob = sum(p['pp_probability'] for p in picks) / len(picks)
        avg_edge = sum(p['edge'] for p in picks) / len(picks)
        tier_counts = {}
        for p in picks:
            tier_counts[p['tier']] = tier_counts.get(p['tier'], 0) + 1
    else:
        avg_prob = 0
        avg_edge = 0
        tier_counts = {}

    return {
        "success": True,
        "date": date,
        "sport": sport.upper(),
        "total_picks": len(picks),
        "picks": picks,
        "summary": {
            "avg_probability": round(avg_prob, 4),
            "avg_edge": round(avg_edge, 2),
            "by_tier": tier_counts
        }
    }
