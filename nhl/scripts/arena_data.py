"""
NHL Arena Data — Coordinates, timezone, and physical characteristics for all 32 arenas.

Used for:
    - Travel distance calculations (rest/rotation features)
    - Timezone crossing detection
    - Altitude adjustments (Denver)

Usage:
    from arena_data import get_arena_info, get_travel_distance, TEAM_TO_ARENA

    info = get_arena_info("TD Garden")
    dist = get_travel_distance("BOS", "NYR")  # miles between arenas
"""

import math
from typing import Dict, Optional, Tuple

# ── Arena database ────────────────────────────────────────────────────────────
# lat/lon from Google Maps, altitude in feet, timezone as UTC offset

ARENA_DATA: Dict[str, Dict] = {
    "Honda Center": {
        "team": "ANA",
        "city": "Anaheim, CA",
        "lat": 33.8078,
        "lon": -117.8765,
        "altitude": 157,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 17174,
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
    "TD Garden": {
        "team": "BOS",
        "city": "Boston, MA",
        "lat": 42.3662,
        "lon": -71.0621,
        "altitude": 20,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 17850,
        "roof": "dome",
    },
    "KeyBank Center": {
        "team": "BUF",
        "city": "Buffalo, NY",
        "lat": 42.8750,
        "lon": -78.8764,
        "altitude": 600,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 19070,
        "roof": "dome",
    },
    "Scotiabank Saddledome": {
        "team": "CGY",
        "city": "Calgary, AB",
        "lat": 51.0375,
        "lon": -114.0519,
        "altitude": 3438,
        "timezone": "America/Edmonton",
        "utc_offset": -7,
        "capacity": 19289,
        "roof": "dome",
    },
    "Lenovo Center": {
        "team": "CAR",
        "city": "Raleigh, NC",
        "lat": 35.8033,
        "lon": -78.7220,
        "altitude": 315,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 18680,
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
        "capacity": 19717,
        "roof": "dome",
    },
    "Ball Arena": {
        "team": "COL",
        "city": "Denver, CO",
        "lat": 39.7487,
        "lon": -105.0077,
        "altitude": 5280,
        "timezone": "America/Denver",
        "utc_offset": -7,
        "capacity": 18007,
        "roof": "dome",
    },
    "Nationwide Arena": {
        "team": "CBJ",
        "city": "Columbus, OH",
        "lat": 39.9691,
        "lon": -83.0060,
        "altitude": 777,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 18500,
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
        "capacity": 18532,
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
        "capacity": 19515,
        "roof": "dome",
    },
    "Rogers Place": {
        "team": "EDM",
        "city": "Edmonton, AB",
        "lat": 53.5469,
        "lon": -113.4979,
        "altitude": 2116,
        "timezone": "America/Edmonton",
        "utc_offset": -7,
        "capacity": 18347,
        "roof": "dome",
    },
    "Amerant Bank Arena": {
        "team": "FLA",
        "city": "Sunrise, FL",
        "lat": 26.1584,
        "lon": -80.3256,
        "altitude": 10,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 19250,
        "roof": "dome",
    },
    "Crypto.com Arena": {
        "team": "LAK",
        "city": "Los Angeles, CA",
        "lat": 34.0430,
        "lon": -118.2673,
        "altitude": 269,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 18230,
        "roof": "dome",
    },
    "Xcel Energy Center": {
        "team": "MIN",
        "city": "Saint Paul, MN",
        "lat": 44.9448,
        "lon": -93.1010,
        "altitude": 780,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 17954,
        "roof": "dome",
    },
    "Bell Centre": {
        "team": "MTL",
        "city": "Montreal, QC",
        "lat": 45.4961,
        "lon": -73.5693,
        "altitude": 118,
        "timezone": "America/Montreal",
        "utc_offset": -5,
        "capacity": 21302,
        "roof": "dome",
    },
    "Bridgestone Arena": {
        "team": "NSH",
        "city": "Nashville, TN",
        "lat": 36.1592,
        "lon": -86.7785,
        "altitude": 550,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 17159,
        "roof": "dome",
    },
    "Prudential Center": {
        "team": "NJD",
        "city": "Newark, NJ",
        "lat": 40.7335,
        "lon": -74.1712,
        "altitude": 30,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 16514,
        "roof": "dome",
    },
    "UBS Arena": {
        "team": "NYI",
        "city": "Elmont, NY",
        "lat": 40.7177,
        "lon": -73.7256,
        "altitude": 60,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 17255,
        "roof": "dome",
    },
    "Madison Square Garden": {
        "team": "NYR",
        "city": "New York, NY",
        "lat": 40.7505,
        "lon": -73.9934,
        "altitude": 33,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 18006,
        "roof": "dome",
    },
    "Canadian Tire Centre": {
        "team": "OTT",
        "city": "Ottawa, ON",
        "lat": 45.2969,
        "lon": -75.9272,
        "altitude": 253,
        "timezone": "America/Toronto",
        "utc_offset": -5,
        "capacity": 18652,
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
        "capacity": 19543,
        "roof": "dome",
    },
    "PPG Paints Arena": {
        "team": "PIT",
        "city": "Pittsburgh, PA",
        "lat": 40.4395,
        "lon": -79.9890,
        "altitude": 1223,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 18387,
        "roof": "dome",
    },
    "SAP Center": {
        "team": "SJS",
        "city": "San Jose, CA",
        "lat": 37.3328,
        "lon": -121.9010,
        "altitude": 82,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 17562,
        "roof": "dome",
    },
    "Climate Pledge Arena": {
        "team": "SEA",
        "city": "Seattle, WA",
        "lat": 47.6221,
        "lon": -122.3540,
        "altitude": 200,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 17151,
        "roof": "dome",
    },
    "Enterprise Center": {
        "team": "STL",
        "city": "St. Louis, MO",
        "lat": 38.6268,
        "lon": -90.2028,
        "altitude": 466,
        "timezone": "America/Chicago",
        "utc_offset": -6,
        "capacity": 18096,
        "roof": "dome",
    },
    "Amalie Arena": {
        "team": "TBL",
        "city": "Tampa, FL",
        "lat": 27.9427,
        "lon": -82.4519,
        "altitude": 8,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 19092,
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
        "capacity": 18819,
        "roof": "dome",
    },
    "Rogers Arena": {
        "team": "VAN",
        "city": "Vancouver, BC",
        "lat": 49.2778,
        "lon": -123.1089,
        "altitude": 10,
        "timezone": "America/Vancouver",
        "utc_offset": -8,
        "capacity": 18910,
        "roof": "dome",
    },
    "T-Mobile Arena": {
        "team": "VGK",
        "city": "Las Vegas, NV",
        "lat": 36.1029,
        "lon": -115.1785,
        "altitude": 2001,
        "timezone": "America/Los_Angeles",
        "utc_offset": -8,
        "capacity": 17500,
        "roof": "dome",
    },
    "Canada Life Centre": {
        "team": "WPG",
        "city": "Winnipeg, MB",
        "lat": 49.8928,
        "lon": -97.1436,
        "altitude": 761,
        "timezone": "America/Winnipeg",
        "utc_offset": -6,
        "capacity": 15321,
        "roof": "dome",
    },
    "Capital One Arena": {
        "team": "WSH",
        "city": "Washington, DC",
        "lat": 38.8981,
        "lon": -77.0209,
        "altitude": 25,
        "timezone": "America/New_York",
        "utc_offset": -5,
        "capacity": 18573,
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
    """
    Calculate travel distance in miles between two teams' arenas.
    Returns None if either team not found.
    """
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
    print(f"NHL Arenas: {len(ARENA_DATA)}")
    print(f"\nSample: TD Garden")
    print(f"  {get_arena_info('TD Garden')}")
    print(f"\nBOS -> LAK distance: {get_travel_distance('BOS', 'LAK')} miles")
    print(f"BOS -> LAK timezone diff: {get_timezone_diff('BOS', 'LAK')} hours")
    print(f"COL altitude: {get_altitude('COL')} ft")
    print(f"\nAll teams: {sorted(TEAM_TO_ARENA.keys())}")
