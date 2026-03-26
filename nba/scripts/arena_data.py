"""
NBA Arena Data — Coordinates, timezone, and physical characteristics for all 30 arenas.

Used for:
    - Travel distance calculations (rest/rotation features)
    - Timezone crossing detection
    - Altitude adjustments (Denver)

Usage:
    from arena_data import get_arena_info, get_travel_distance, TEAM_TO_ARENA

    info = get_arena_info("TD Garden")
    dist = get_travel_distance("BOS", "LAL")  # miles between arenas
"""

import math
from typing import Dict, Optional, Tuple

# ── Arena database ────────────────────────────────────────────────────────────

ARENA_DATA: Dict[str, Dict] = {
    "State Farm Arena": {
        "team": "ATL",
        "city": "Atlanta, GA",
        "lat": 33.7573,
        "lon": -84.3963,
        "altitude": 1050,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 18118,
        "roof": "dome",
    },
    "TD Garden": {
        "team": "BOS",
        "city": "Boston, MA",
        "lat": 42.3662,
        "lon": -71.0621,
        "altitude": 20,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 19156,
        "roof": "dome",
    },
    "Barclays Center": {
        "team": "BKN",
        "city": "Brooklyn, NY",
        "lat": 40.6826,
        "lon": -73.9754,
        "altitude": 30,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 17732,
        "roof": "dome",
    },
    "Spectrum Center": {
        "team": "CHA",
        "city": "Charlotte, NC",
        "lat": 35.2251,
        "lon": -80.8392,
        "altitude": 748,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 19077,
        "roof": "dome",
    },
    "United Center": {
        "team": "CHI",
        "city": "Chicago, IL",
        "lat": 41.8807,
        "lon": -87.6742,
        "altitude": 594,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 20917,
        "roof": "dome",
    },
    "Rocket Mortgage FieldHouse": {
        "team": "CLE",
        "city": "Cleveland, OH",
        "lat": 41.4965,
        "lon": -81.6882,
        "altitude": 653,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 19432,
        "roof": "dome",
    },
    "American Airlines Center": {
        "team": "DAL",
        "city": "Dallas, TX",
        "lat": 32.7905,
        "lon": -96.8103,
        "altitude": 430,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 19200,
        "roof": "dome",
    },
    "Ball Arena": {
        "team": "DEN",
        "city": "Denver, CO",
        "lat": 39.7487,
        "lon": -105.0077,
        "altitude": 5280,
        "timezone": "America/Denver",
        "utc_offset": -7,
        "capacity": 19520,
        "roof": "dome",
    },
    "Little Caesars Arena": {
        "team": "DET",
        "city": "Detroit, MI",
        "lat": 42.3411,
        "lon": -83.0553,
        "altitude": 600,
        "timezone": "America/Detroit",
        "utc_offset": -5,
        "capacity": 20332,
        "roof": "dome",
    },
    "Chase Center": {
        "team": "GSW",
        "city": "San Francisco, CA",
        "lat": 37.7680,
        "lon": -122.3877,
        "altitude": 7,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 18064,
        "roof": "dome",
    },
    "Toyota Center": {
        "team": "HOU",
        "city": "Houston, TX",
        "lat": 29.7508,
        "lon": -95.3621,
        "altitude": 50,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 18055,
        "roof": "dome",
    },
    "Gainbridge Fieldhouse": {
        "team": "IND",
        "city": "Indianapolis, IN",
        "lat": 39.7640,
        "lon": -86.1555,
        "altitude": 715,
        "timezone": "America/Indiana/Indianapolis",
        "utc_offset": -5,
        "capacity": 17923,
        "roof": "dome",
    },
    "Intuit Dome": {
        "team": "LAC",
        "city": "Inglewood, CA",
        "lat": 33.9425,
        "lon": -118.3413,
        "altitude": 100,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 18000,
        "roof": "dome",
    },
    "Crypto.com Arena": {
        "team": "LAL",
        "city": "Los Angeles, CA",
        "lat": 34.0430,
        "lon": -118.2673,
        "altitude": 269,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 18997,
        "roof": "dome",
    },
    "FedExForum": {
        "team": "MEM",
        "city": "Memphis, TN",
        "lat": 35.1382,
        "lon": -90.0506,
        "altitude": 337,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 17794,
        "roof": "dome",
    },
    "Kaseya Center": {
        "team": "MIA",
        "city": "Miami, FL",
        "lat": 25.7814,
        "lon": -80.1870,
        "altitude": 7,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 19600,
        "roof": "dome",
    },
    "Fiserv Forum": {
        "team": "MIL",
        "city": "Milwaukee, WI",
        "lat": 43.0451,
        "lon": -87.9174,
        "altitude": 617,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 17341,
        "roof": "dome",
    },
    "Target Center": {
        "team": "MIN",
        "city": "Minneapolis, MN",
        "lat": 44.9795,
        "lon": -93.2761,
        "altitude": 830,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 18978,
        "roof": "dome",
    },
    "Smoothie King Center": {
        "team": "NOP",
        "city": "New Orleans, LA",
        "lat": 29.9490,
        "lon": -90.0821,
        "altitude": 3,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 16867,
        "roof": "dome",
    },
    "Madison Square Garden": {
        "team": "NYK",
        "city": "New York, NY",
        "lat": 40.7505,
        "lon": -73.9934,
        "altitude": 33,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 19812,
        "roof": "dome",
    },
    "Paycom Center": {
        "team": "OKC",
        "city": "Oklahoma City, OK",
        "lat": 35.4634,
        "lon": -97.5151,
        "altitude": 1201,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 18203,
        "roof": "dome",
    },
    "Kia Center": {
        "team": "ORL",
        "city": "Orlando, FL",
        "lat": 28.5392,
        "lon": -81.3839,
        "altitude": 82,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 18846,
        "roof": "dome",
    },
    "Wells Fargo Center": {
        "team": "PHI",
        "city": "Philadelphia, PA",
        "lat": 39.9012,
        "lon": -75.1720,
        "altitude": 39,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 20478,
        "roof": "dome",
    },
    "Footprint Center": {
        "team": "PHX",
        "city": "Phoenix, AZ",
        "lat": 33.4457,
        "lon": -112.0712,
        "altitude": 1086,
        "timezone": "America/Phoenix",
        "utc_offset": -7,
        "capacity": 18055,
        "roof": "dome",
    },
    "Moda Center": {
        "team": "POR",
        "city": "Portland, OR",
        "lat": 45.5316,
        "lon": -122.6668,
        "altitude": 50,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 19393,
        "roof": "dome",
    },
    "Golden 1 Center": {
        "team": "SAC",
        "city": "Sacramento, CA",
        "lat": 38.5802,
        "lon": -121.4997,
        "altitude": 30,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 17608,
        "roof": "dome",
    },
    "Frost Bank Center": {
        "team": "SAS",
        "city": "San Antonio, TX",
        "lat": 29.4270,
        "lon": -98.4375,
        "altitude": 650,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 18418,
        "roof": "dome",
    },
    "Scotiabank Arena": {
        "team": "TOR",
        "city": "Toronto, ON",
        "lat": 43.6435,
        "lon": -79.3791,
        "altitude": 249,
        "timezone": "America/Toronto",
        "utc_offset": -5,
        "capacity": 19800,
        "roof": "dome",
    },
    "Delta Center": {
        "team": "UTA",
        "city": "Salt Lake City, UT",
        "lat": 40.7683,
        "lon": -111.9011,
        "altitude": 4226,
        "timezone": "America/Denver",
        "utc_offset": -7,
        "capacity": 18306,
        "roof": "dome",
    },
    "Capital One Arena": {
        "team": "WAS",
        "city": "Washington, DC",
        "lat": 38.8981,
        "lon": -77.0209,
        "altitude": 25,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 20356,
        "roof": "dome",
    },
}

# ── Lookup dictionaries ───────────────────────────────────────────────────────

TEAM_TO_ARENA: Dict[str, str] = {v["team"]: k for k, v in ARENA_DATA.items()}

# ── Helper functions ──────────────────────────────────────────────────────────

def get_arena_info(arena_name: str) -> Optional[Dict]:
    """Get full arena info by arena name."""
    return ARENA_DATA.get(arena_name)


def get_arena_by_team(team: str) -> Optional[Dict]:
    """Get arena info by team abbreviation."""
    arena_name = TEAM_TO_ARENA.get(team)
    if arena_name:
        return ARENA_DATA.get(arena_name)
    return None


def get_coordinates(team: str) -> Optional[Tuple[float, float]]:
    """Get (lat, lon) tuple for a team's arena."""
    info = get_arena_by_team(team)
    if info:
        return (info["lat"], info["lon"])
    return None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in miles using Haversine formula."""
    R = 3959  # Earth's radius in miles
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return round(R * c, 1)


def get_travel_distance(team_from: str, team_to: str) -> Optional[float]:
    """Calculate travel distance in miles between two teams' arenas."""
    coords_from = get_coordinates(team_from)
    coords_to = get_coordinates(team_to)
    if coords_from and coords_to:
        return _haversine(coords_from[0], coords_from[1],
                          coords_to[0], coords_to[1])
    return None


def get_timezone_diff(team_from: str, team_to: str) -> Optional[int]:
    """
    Get timezone difference in hours between two teams.
    Positive = traveling east, negative = traveling west.
    """
    info_from = get_arena_by_team(team_from)
    info_to = get_arena_by_team(team_to)
    if info_from and info_to:
        return info_to["utc_offset"] - info_from["utc_offset"]
    return None


def get_altitude(team: str) -> Optional[int]:
    """Get arena altitude in feet."""
    info = get_arena_by_team(team)
    if info:
        return info["altitude"]
    return None


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"NBA Arenas: {len(ARENA_DATA)}")
    print(f"\nSample: TD Garden")
    print(f"  {get_arena_info('TD Garden')}")
    print(f"\nBOS -> LAL distance: {get_travel_distance('BOS', 'LAL')} miles")
    print(f"BOS -> LAL timezone diff: {get_timezone_diff('BOS', 'LAL')} hours")
    print(f"DEN altitude: {get_altitude('DEN')} ft")
    print(f"\nAll teams: {sorted(TEAM_TO_ARENA.keys())}")
