"""
MLB Park Factors Database
=========================

Static park factor database for all 30 MLB ballparks.
Source: FanGraphs 3-year rolling park factors (2023-2025 seasons).

Park factors represent how much a park inflates or deflates each stat
relative to a neutral environment (1.0 = average, 1.10 = 10% above average).

Ballpark orientations are stored for wind direction calculations:
  orientation_deg = compass direction the batter faces when at the plate
  (wind FROM this direction = 'In' to CF, wind TO this direction = 'Out' to CF)

Usage:
    from park_factors import get_park_factor, get_park_factor_by_team
    hr_factor = get_park_factor('Coors Field', 'hr')   # 1.40
    hr_factor = get_park_factor_by_team('COL', 'hr')   # 1.40
"""

from typing import Dict, Optional

# ============================================================================
# PARK FACTOR DATABASE (all 30 MLB parks)
# Factors from FanGraphs 3-year rolling data (2023-2025)
# 1.0 = neutral, >1.0 = inflated stat, <1.0 = deflated stat
# ============================================================================

PARK_FACTORS: Dict[str, Dict] = {
    'Coors Field': {
        'team': 'COL',
        'hr': 1.40,     # Thin air = massive HR boost
        'hits': 1.15,
        'runs': 1.28,
        'k': 0.93,      # Thin air slightly reduces K rate
        '2b': 1.12,
        '3b': 1.55,     # Large outfield, fast turf
        'bb': 1.02,
        'lat': 39.7561, 'lon': -104.9942,
        'altitude': 5200,
        'roof': 'open',
        'orientation_deg': 45,  # NE — wind from NE = In, from SW = Out
    },
    'Fenway Park': {
        'team': 'BOS',
        'hr': 0.93,     # Green Monster suppresses some HRs
        'hits': 1.05,   # Monster doubles become hits
        'runs': 1.04,
        'k': 0.97,
        '2b': 1.10,
        '3b': 0.78,
        'bb': 0.98,
        'lat': 42.3467, 'lon': -71.0972,
        'altitude': 20,
        'roof': 'open',
        'orientation_deg': 53,
    },
    'Wrigley Field': {
        'team': 'CHC',
        'hr': 1.08,
        'hits': 1.02,
        'runs': 1.05,
        'k': 0.96,      # Ivy background slightly hurts K rate
        '2b': 1.00,
        '3b': 0.92,
        'bb': 0.99,
        'lat': 41.9484, 'lon': -87.6553,
        'altitude': 595,
        'roof': 'open',
        'orientation_deg': 36,   # NE — Lake Michigan wind dominant
    },
    'Oracle Park': {
        'team': 'SF',
        'hr': 0.74,     # Cold, windy — notorious HR suppressor
        'hits': 0.96,
        'runs': 0.87,
        'k': 1.03,
        '2b': 0.98,
        '3b': 1.10,
        'bb': 0.99,
        'lat': 37.7786, 'lon': -122.3893,
        'altitude': 10,
        'roof': 'open',
        'orientation_deg': 5,    # North — cold Bay winds off McCovey Cove
    },
    'Petco Park': {
        'team': 'SD',
        'hr': 0.78,     # Marine layer suppresses offense
        'hits': 0.94,
        'runs': 0.88,
        'k': 1.02,
        '2b': 0.92,
        '3b': 0.85,
        'bb': 0.98,
        'lat': 32.7073, 'lon': -117.1566,
        'altitude': 62,
        'roof': 'open',
        'orientation_deg': 0,
    },
    'Great American Ball Park': {
        'team': 'CIN',
        'hr': 1.25,     # Hitter-friendly
        'hits': 1.05,
        'runs': 1.15,
        'k': 0.98,
        '2b': 1.05,
        '3b': 0.90,
        'bb': 1.01,
        'lat': 39.0979, 'lon': -84.5088,
        'altitude': 488,
        'roof': 'open',
        'orientation_deg': 90,
    },
    'Camden Yards': {
        'team': 'BAL',
        'hr': 1.08,
        'hits': 1.03,
        'runs': 1.05,
        'k': 0.99,
        '2b': 1.03,
        '3b': 0.90,
        'bb': 0.99,
        'lat': 39.2839, 'lon': -76.6222,
        'altitude': 10,
        'roof': 'open',
        'orientation_deg': 20,
    },
    'Fenway Park': {
        'team': 'BOS',
        'hr': 0.93,
        'hits': 1.05,
        'runs': 1.04,
        'k': 0.97,
        '2b': 1.10,
        '3b': 0.78,
        'bb': 0.98,
        'lat': 42.3467, 'lon': -71.0972,
        'altitude': 20,
        'roof': 'open',
        'orientation_deg': 53,
    },
    'Guaranteed Rate Field': {
        'team': 'CWS',
        'hr': 1.12,
        'hits': 1.02,
        'runs': 1.05,
        'k': 0.99,
        '2b': 1.01,
        '3b': 0.88,
        'bb': 1.00,
        'lat': 41.8300, 'lon': -87.6339,
        'altitude': 595,
        'roof': 'open',
        'orientation_deg': 180,
    },
    'Progressive Field': {
        'team': 'CLE',
        'hr': 0.90,
        'hits': 0.98,
        'runs': 0.96,
        'k': 1.01,
        '2b': 0.97,
        '3b': 0.88,
        'bb': 0.99,
        'lat': 41.4962, 'lon': -81.6852,
        'altitude': 653,
        'roof': 'open',
        'orientation_deg': 67,
    },
    'Comerica Park': {
        'team': 'DET',
        'hr': 0.88,
        'hits': 0.99,
        'runs': 0.96,
        'k': 0.99,
        '2b': 1.00,
        '3b': 0.90,
        'bb': 1.00,
        'lat': 42.3390, 'lon': -83.0485,
        'altitude': 600,
        'roof': 'open',
        'orientation_deg': 340,
    },
    'Minute Maid Park': {
        'team': 'HOU',
        'hr': 1.05,
        'hits': 1.02,
        'runs': 1.02,
        'k': 0.99,
        '2b': 1.05,     # Tal's Hill removed but still good doubles park
        '3b': 1.00,
        'bb': 1.00,
        'lat': 29.7573, 'lon': -95.3555,
        'altitude': 22,
        'roof': 'retractable',
        'orientation_deg': 0,
    },
    'Kauffman Stadium': {
        'team': 'KC',
        'hr': 0.94,
        'hits': 1.02,
        'runs': 0.98,
        'k': 0.98,
        '2b': 1.00,
        '3b': 0.92,
        'bb': 0.99,
        'lat': 39.0518, 'lon': -94.4803,
        'altitude': 978,
        'roof': 'open',
        'orientation_deg': 70,
    },
    'Angel Stadium': {
        'team': 'LAA',
        'hr': 0.92,
        'hits': 0.99,
        'runs': 0.97,
        'k': 1.01,
        '2b': 0.97,
        '3b': 0.85,
        'bb': 0.99,
        'lat': 33.8003, 'lon': -117.8827,
        'altitude': 160,
        'roof': 'open',
        'orientation_deg': 0,
    },
    'Dodger Stadium': {
        'team': 'LAD',
        'hr': 1.00,
        'hits': 0.98,
        'runs': 0.98,
        'k': 1.01,
        '2b': 0.96,
        '3b': 0.88,
        'bb': 0.99,
        'lat': 34.0739, 'lon': -118.2400,
        'altitude': 511,
        'roof': 'open',
        'orientation_deg': 330,
    },
    'loanDepot Park': {
        'team': 'MIA',
        'hr': 0.87,
        'hits': 0.97,
        'runs': 0.94,
        'k': 1.02,
        '2b': 0.95,
        '3b': 0.88,
        'bb': 0.99,
        'lat': 25.7781, 'lon': -80.2196,
        'altitude': 8,
        'roof': 'retractable',
        'orientation_deg': 0,
    },
    'American Family Field': {
        'team': 'MIL',
        'hr': 1.12,
        'hits': 1.03,
        'runs': 1.06,
        'k': 0.99,
        '2b': 1.02,
        '3b': 0.88,
        'bb': 1.00,
        'lat': 43.0280, 'lon': -87.9712,
        'altitude': 634,
        'roof': 'retractable',
        'orientation_deg': 0,
    },
    'Target Field': {
        'team': 'MIN',
        'hr': 0.96,
        'hits': 1.00,
        'runs': 0.99,
        'k': 0.99,
        '2b': 1.00,
        '3b': 0.88,
        'bb': 1.00,
        'lat': 44.9818, 'lon': -93.2776,
        'altitude': 830,
        'roof': 'open',
        'orientation_deg': 355,
    },
    'Citi Field': {
        'team': 'NYM',
        'hr': 0.92,
        'hits': 0.97,
        'runs': 0.95,
        'k': 1.02,
        '2b': 0.96,
        '3b': 0.88,
        'bb': 1.00,
        'lat': 40.7571, 'lon': -73.8458,
        'altitude': 23,
        'roof': 'open',
        'orientation_deg': 5,
    },
    'Yankee Stadium': {
        'team': 'NYY',
        'hr': 1.20,     # Short porch in right
        'hits': 1.03,
        'runs': 1.08,
        'k': 0.99,
        '2b': 1.00,
        '3b': 0.85,
        'bb': 1.01,
        'lat': 40.8296, 'lon': -73.9262,
        'altitude': 55,
        'roof': 'open',
        'orientation_deg': 340,
    },
    'Oakland Coliseum': {
        'team': 'OAK',
        'hr': 0.83,     # Marine layer + vast foul territory
        'hits': 0.94,
        'runs': 0.89,
        'k': 1.01,
        '2b': 0.92,
        '3b': 0.92,
        'bb': 0.99,
        'lat': 37.7516, 'lon': -122.2005,
        'altitude': 25,
        'roof': 'open',
        'orientation_deg': 0,
    },
    'Citizens Bank Park': {
        'team': 'PHI',
        'hr': 1.12,
        'hits': 1.03,
        'runs': 1.06,
        'k': 0.99,
        '2b': 1.02,
        '3b': 0.88,
        'bb': 1.00,
        'lat': 39.9057, 'lon': -75.1665,
        'altitude': 20,
        'roof': 'open',
        'orientation_deg': 336,
    },
    'PNC Park': {
        'team': 'PIT',
        'hr': 0.93,
        'hits': 1.00,
        'runs': 0.97,
        'k': 1.00,
        '2b': 0.98,
        '3b': 0.90,
        'bb': 1.00,
        'lat': 40.4469, 'lon': -80.0058,
        'altitude': 730,
        'roof': 'open',
        'orientation_deg': 35,
    },
    'Busch Stadium': {
        'team': 'STL',
        'hr': 0.94,
        'hits': 1.00,
        'runs': 0.98,
        'k': 0.99,
        '2b': 1.00,
        '3b': 1.00,
        'bb': 1.00,
        'lat': 38.6226, 'lon': -90.1928,
        'altitude': 466,
        'roof': 'open',
        'orientation_deg': 75,
    },
    'Petco Park': {
        'team': 'SD',
        'hr': 0.78,
        'hits': 0.94,
        'runs': 0.88,
        'k': 1.02,
        '2b': 0.92,
        '3b': 0.85,
        'bb': 0.98,
        'lat': 32.7073, 'lon': -117.1566,
        'altitude': 62,
        'roof': 'open',
        'orientation_deg': 0,
    },
    'T-Mobile Park': {
        'team': 'SEA',
        'hr': 0.90,
        'hits': 0.98,
        'runs': 0.95,
        'k': 1.01,
        '2b': 0.98,
        '3b': 0.88,
        'bb': 1.00,
        'lat': 47.5914, 'lon': -122.3325,
        'altitude': 0,
        'roof': 'retractable',
        'orientation_deg': 335,
    },
    'Tropicana Field': {
        'team': 'TB',
        'hr': 0.96,
        'hits': 0.97,
        'runs': 0.97,
        'k': 1.00,
        '2b': 0.97,
        '3b': 1.05,
        'bb': 1.00,
        'lat': 27.7682, 'lon': -82.6534,
        'altitude': 28,
        'roof': 'dome',         # Always domed — fully climate controlled
        'orientation_deg': 0,
    },
    'Globe Life Field': {
        'team': 'TEX',
        'hr': 1.10,
        'hits': 1.02,
        'runs': 1.04,
        'k': 0.99,
        '2b': 1.02,
        '3b': 0.88,
        'bb': 1.00,
        'lat': 32.7513, 'lon': -97.0832,
        'altitude': 550,
        'roof': 'retractable',
        'orientation_deg': 135,
    },
    'Rogers Centre': {
        'team': 'TOR',
        'hr': 1.08,
        'hits': 1.01,
        'runs': 1.04,
        'k': 0.98,
        '2b': 1.00,
        '3b': 0.80,     # Turf but enclosed
        'bb': 1.00,
        'lat': 43.6414, 'lon': -79.3894,
        'altitude': 251,
        'roof': 'retractable',
        'orientation_deg': 0,
    },
    'Nationals Park': {
        'team': 'WSH',
        'hr': 1.05,
        'hits': 1.01,
        'runs': 1.03,
        'k': 0.99,
        '2b': 1.02,
        '3b': 0.90,
        'bb': 1.00,
        'lat': 38.8730, 'lon': -77.0074,
        'altitude': 10,
        'roof': 'open',
        'orientation_deg': 335,
    },
    'Chase Field': {
        'team': 'ARI',
        'hr': 1.10,
        'hits': 1.03,
        'runs': 1.05,
        'k': 0.98,
        '2b': 1.02,
        '3b': 0.88,
        'bb': 1.01,
        'lat': 33.4455, 'lon': -112.0667,
        'altitude': 1082,
        'roof': 'retractable',
        'orientation_deg': 135,
    },
    'Truist Park': {
        'team': 'ATL',
        'hr': 1.05,
        'hits': 1.01,
        'runs': 1.03,
        'k': 0.99,
        '2b': 1.01,
        '3b': 0.88,
        'bb': 1.00,
        'lat': 33.8908, 'lon': -84.4678,
        'altitude': 1050,
        'roof': 'open',
        'orientation_deg': 285,
    },
}

# Map team abbreviation → park name for lookups
TEAM_TO_PARK: Dict[str, str] = {v['team']: k for k, v in PARK_FACTORS.items()}

# Neutral/default factors for unknown venues
NEUTRAL_FACTORS = {
    'hr': 1.00, 'hits': 1.00, 'runs': 1.00, 'k': 1.00,
    '2b': 1.00, '3b': 1.00, 'bb': 1.00,
}

# Stat alias mapping (handle different naming conventions)
STAT_ALIASES = {
    'home_runs': 'hr', 'strikeouts': 'k', 'doubles': '2b', 'triples': '3b',
    'walks': 'bb', 'total_bases': 'hits',  # total bases roughly correlated with hit factor
    'stolen_bases': 'hits',                # not directly measured, use hits as proxy
    'rbis': 'runs', 'earned_runs': 'runs', 'batter_strikeouts': 'k',
    'pitcher_walks': 'bb', 'hits_allowed': 'hits', 'strikeouts_pitched': 'k',
}


# ============================================================================
# PUBLIC API
# ============================================================================

def get_park_factor(venue: str, stat: str) -> float:
    """
    Get park factor for a specific stat at a given venue.

    Args:
        venue: Full ballpark name (e.g., 'Coors Field')
        stat: Stat type ('hr', 'hits', 'runs', 'k', '2b', '3b', 'bb')
              Also accepts prop_type names via STAT_ALIASES.

    Returns:
        Park factor (1.0 = neutral, >1.0 = inflated)
    """
    # Normalize stat name
    normalized_stat = STAT_ALIASES.get(stat.lower(), stat.lower())

    # Look up park
    park = PARK_FACTORS.get(venue)
    if not park:
        # Try fuzzy match on venue name
        venue_lower = venue.lower()
        for park_name, park_data in PARK_FACTORS.items():
            if park_name.lower() in venue_lower or venue_lower in park_name.lower():
                park = park_data
                break

    if not park:
        return NEUTRAL_FACTORS.get(normalized_stat, 1.0)

    return park.get(normalized_stat, NEUTRAL_FACTORS.get(normalized_stat, 1.0))


def get_park_factor_by_team(team: str, stat: str) -> float:
    """
    Convenience lookup: get park factor for a team's home park.

    Args:
        team: Team abbreviation (e.g., 'COL', 'NYY')
        stat: Stat type

    Returns:
        Park factor (1.0 = neutral)
    """
    park_name = TEAM_TO_PARK.get(team.upper())
    if not park_name:
        return 1.0
    return get_park_factor(park_name, stat)


def get_park_info(venue: str) -> Dict:
    """
    Get full park info dict for a venue.

    Returns:
        Park dict with all factors, coordinates, altitude, roof type.
        Returns empty dict if venue not found.
    """
    park = PARK_FACTORS.get(venue)
    if park:
        return park

    # Try fuzzy match
    venue_lower = venue.lower()
    for park_name, park_data in PARK_FACTORS.items():
        if park_name.lower() in venue_lower or venue_lower in park_name.lower():
            return park_data

    return {}


def get_park_info_by_team(team: str) -> Dict:
    """Get full park info by team abbreviation."""
    park_name = TEAM_TO_PARK.get(team.upper(), '')
    return get_park_info(park_name)


def is_dome_or_retractable(venue: str) -> bool:
    """
    Check if a park is fully domed or has a retractable roof.
    Used to skip weather adjustments for controlled-environment parks.

    Args:
        venue: Park name

    Returns:
        True if dome or retractable (weather not a factor)
    """
    info = get_park_info(venue)
    roof = info.get('roof', 'open')
    return roof in ('dome', 'retractable')


def get_altitude(venue: str) -> int:
    """
    Get ballpark altitude in feet above sea level.

    High altitude (especially Coors Field at 5200ft) significantly
    affects ball flight — roughly 5-7% farther per 1000ft elevation.

    Args:
        venue: Park name

    Returns:
        Altitude in feet (0 if unknown)
    """
    return get_park_info(venue).get('altitude', 0)


def get_altitude_adjustment(venue: str) -> float:
    """
    Get a multiplicative adjustment factor for altitude effect on ball flight.

    Coors Field (5200ft): ~1.15-1.20x on HR and total base props
    Sea level parks: 1.0x

    Args:
        venue: Park name

    Returns:
        Multiplier (1.0 for sea level, up to ~1.15 for Coors)
    """
    altitude = get_altitude(venue)
    # Rule of thumb: ~1% ball flight increase per 350ft above sea level
    # Coors: 5200 / 350 * 0.01 ≈ 0.149, so ~14.9% boost
    return 1.0 + (altitude / 350) * 0.010


if __name__ == '__main__':
    # Quick validation
    print("[Park Factors] Validation:")
    print(f"  Coors HR:        {get_park_factor('Coors Field', 'hr'):.2f}")
    print(f"  Oracle Park HR:  {get_park_factor('Oracle Park', 'hr'):.2f}")
    print(f"  Yankee Stadium HR: {get_park_factor('Yankee Stadium', 'hr'):.2f}")
    print(f"  COL by team HR:  {get_park_factor_by_team('COL', 'hr'):.2f}")
    print(f"  NYY by team HR:  {get_park_factor_by_team('NYY', 'hr'):.2f}")
    print(f"  Coors altitude:  {get_altitude('Coors Field')}ft")
    print(f"  Coors alt adj:   {get_altitude_adjustment('Coors Field'):.3f}x")
    print(f"  Tropicana dome:  {is_dome_or_retractable('Tropicana Field')}")
    print(f"  Total parks:     {len(PARK_FACTORS)}")
    print(f"  Teams mapped:    {len(TEAM_TO_PARK)}")
