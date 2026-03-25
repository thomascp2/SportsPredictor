"""
Weather Client for MLB Games
=============================

Fetches real-time weather data at each MLB ballpark using the Open-Meteo API.
Open-Meteo is completely FREE — no API key, no account, no rate limits for
reasonable usage (~100 calls/day for a 30-game slate).

Reference: https://open-meteo.com/en/docs

Weather significantly affects MLB props:
  Wind Out (blowing to CF): +10-15% HR boost, more total bases
  Wind In  (blowing from CF): -10-15% HR suppression
  Cold (<45F): Ball doesn't carry as well -> HR suppression
  Hot (>90F):  Ball carries better
  Rain/Dome:   Neutral (dome) or variable

No API key required — drop-in replacement for the previous OpenWeatherMap client.
"""

import math
import time
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone
from typing import Dict, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import MLB_API_TIMEOUT
from park_factors import PARK_FACTORS, TEAM_TO_PARK, get_park_info, get_park_info_by_team, is_dome_or_retractable


# ============================================================================
# OPEN-METEO WMO WEATHER CODE -> HUMAN LABEL
# https://open-meteo.com/en/docs#weathervariables
# ============================================================================
WMO_CODE_LABELS = {
    0: 'Clear', 1: 'Clear', 2: 'Partly Cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Fog',
    51: 'Drizzle', 53: 'Drizzle', 55: 'Drizzle',
    61: 'Rain', 63: 'Rain', 65: 'Heavy Rain',
    71: 'Snow', 73: 'Snow', 75: 'Heavy Snow',
    77: 'Snow Grains',
    80: 'Showers', 81: 'Showers', 82: 'Heavy Showers',
    85: 'Snow Showers', 86: 'Snow Showers',
    95: 'Thunderstorm', 96: 'Thunderstorm', 99: 'Thunderstorm',
}


# Neutral weather for domed parks (controlled environment)
DOME_WEATHER = {
    'temperature': 72,
    'wind_speed': 0,
    'wind_direction': 'Dome',
    'conditions': 'Clear',
    'is_dome': True,
    'raw_wind_deg': 0,
    'wind_effect_hr': 0.0,
    'wind_effect_k': 0.0,
}

# Default fallback when no network or unknown park
DEFAULT_WEATHER = {
    'temperature': 68,
    'wind_speed': 5,
    'wind_direction': 'Calm',
    'conditions': 'Clear',
    'is_dome': False,
    'raw_wind_deg': 0,
    'wind_effect_hr': 0.0,
    'wind_effect_k': 0.0,
}

# Open-Meteo base URL
_OPEN_METEO_BASE = 'https://api.open-meteo.com/v1/forecast'


class WeatherClient:
    """
    Fetches and processes weather data for MLB ballparks.

    Uses Open-Meteo (free, no API key) to get hourly forecast closest to game time.
    Falls back to DEFAULT_WEATHER on any network error — picks still generate.
    """

    def __init__(self, api_key: str = None):
        # api_key kept for backward compatibility but ignored — Open-Meteo is keyless
        self._cache: Dict[str, Dict] = {}

    def get_game_weather(self, home_team: str, game_time_utc: str = None,
                         venue: str = None) -> Dict:
        """
        Get weather for a game at the home team's ballpark.

        Args:
            home_team: Team abbreviation (e.g., 'COL', 'NYY')
            game_time_utc: ISO format UTC game time (e.g., '2026-04-01T19:10:00Z')
                           If None, uses current conditions.
            venue: Park name (optional override)

        Returns:
            Weather dict with: temperature, wind_speed, wind_direction, conditions,
                               is_dome, raw_wind_deg, wind_effect_hr, wind_effect_k
        """
        # Dome / retractable roof parks → controlled environment, skip API
        park_name = venue or TEAM_TO_PARK.get(home_team.upper(), '')
        if park_name and is_dome_or_retractable(park_name):
            return dict(DOME_WEATHER)

        # Look up park coordinates
        park_info = (get_park_info_by_team(home_team.upper())
                     if not venue else get_park_info(venue))
        if not park_info:
            print(f"[Weather] Unknown park for team {home_team}, using defaults")
            return dict(DEFAULT_WEATHER)

        lat = park_info.get('lat')
        lon = park_info.get('lon')
        if not lat or not lon:
            return dict(DEFAULT_WEATHER)

        # Cache by lat/lon + date (one API call per park per run)
        date_str = (game_time_utc or '')[:10]
        cache_key = f"{lat:.3f}_{lon:.3f}_{date_str}"
        if cache_key in self._cache:
            raw = self._cache[cache_key]
        else:
            raw = self._fetch_weather(lat, lon, game_time_utc)
            self._cache[cache_key] = raw

        if not raw:
            return dict(DEFAULT_WEATHER)

        orientation_deg = park_info.get('orientation_deg', 0)
        return self._process_weather(raw, orientation_deg)

    def _fetch_weather(self, lat: float, lon: float,
                       game_time_utc: str = None) -> Optional[Dict]:
        """
        Fetch hourly forecast from Open-Meteo for the park location.

        Returns the single hourly entry closest to game_time_utc,
        or current conditions if no game time provided.
        """
        params = {
            'latitude': lat,
            'longitude': lon,
            'hourly': 'temperature_2m,wind_speed_10m,wind_direction_10m,weather_code',
            'current': 'temperature_2m,wind_speed_10m,wind_direction_10m,weather_code',
            'wind_speed_unit': 'mph',
            'temperature_unit': 'fahrenheit',
            'timezone': 'auto',
            'forecast_days': 2,       # today + tomorrow covers any game window
        }

        url = _OPEN_METEO_BASE + '?' + urllib.parse.urlencode(params)

        for attempt in range(3):
            try:
                req = urllib.request.urlopen(url, timeout=MLB_API_TIMEOUT)
                data = json.loads(req.read())

                # If we have a game time, find the closest hourly forecast entry
                if game_time_utc:
                    return self._find_closest_hourly(data, game_time_utc)

                # Otherwise use current conditions
                curr = data.get('current', {})
                if curr:
                    return {
                        'temp': curr.get('temperature_2m', 68),
                        'wind_speed': curr.get('wind_speed_10m', 5),
                        'wind_deg': curr.get('wind_direction_10m', 0),
                        'wmo_code': curr.get('weather_code', 0),
                    }
                return None

            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[Weather] Open-Meteo unavailable: {e} — using defaults")
                    return None
        return None

    def _find_closest_hourly(self, data: Dict, game_time_utc: str) -> Optional[Dict]:
        """Find the hourly forecast entry nearest to game_time_utc."""
        hourly = data.get('hourly', {})
        times = hourly.get('time', [])
        if not times:
            return None

        try:
            target = datetime.fromisoformat(game_time_utc.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None

        best_idx = 0
        best_diff = float('inf')
        for i, t_str in enumerate(times):
            try:
                # Open-Meteo hourly times are in local timezone ISO format
                t = datetime.fromisoformat(t_str)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                # Normalize target to same offset for comparison
                target_local = target.astimezone(t.tzinfo) if t.tzinfo else target
                diff = abs((t - target_local).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i
            except (ValueError, TypeError):
                continue

        temps = hourly.get('temperature_2m', [])
        winds = hourly.get('wind_speed_10m', [])
        dirs  = hourly.get('wind_direction_10m', [])
        codes = hourly.get('weather_code', [])

        def _safe(lst, idx, default):
            return lst[idx] if lst and idx < len(lst) else default

        return {
            'temp':       _safe(temps, best_idx, 68),
            'wind_speed': _safe(winds, best_idx, 5),
            'wind_deg':   _safe(dirs,  best_idx, 0),
            'wmo_code':   _safe(codes, best_idx, 0),
        }

    def _process_weather(self, raw: Dict, park_orientation_deg: int) -> Dict:
        """Convert raw Open-Meteo entry to our standardized format."""
        temperature = raw.get('temp', 68)
        wind_speed  = raw.get('wind_speed', 5)
        wind_deg    = raw.get('wind_deg', 0)
        wmo_code    = raw.get('wmo_code', 0)
        conditions  = WMO_CODE_LABELS.get(int(wmo_code), 'Clear')

        wind_direction, wind_scalar = self._parse_wind_direction(
            wind_speed, wind_deg, park_orientation_deg
        )

        wind_effect_hr  = self._compute_wind_effect_hr(wind_speed, wind_scalar)
        temp_effect_hr  = self._compute_temperature_effect_hr(temperature)
        wind_effect_k   = self._compute_temperature_effect_k(temperature)

        return {
            'temperature':    round(temperature),
            'wind_speed':     round(wind_speed),
            'wind_direction': wind_direction,
            'conditions':     conditions,
            'is_dome':        False,
            'raw_wind_deg':   wind_deg,
            'wind_scalar':    wind_scalar,
            'wind_effect_hr': round(wind_effect_hr + temp_effect_hr, 3),
            'wind_effect_k':  round(wind_effect_k, 3),
        }

    # ── Wind / temp effect calculators (unchanged from original) ──────────────

    def _parse_wind_direction(self, wind_speed, wind_deg, park_orientation_deg):
        if wind_speed < 3:
            return 'Calm', 0.0
        wind_blowing_to_deg = (wind_deg + 180) % 360
        diff = (wind_blowing_to_deg - park_orientation_deg) % 360
        if diff > 180:
            diff -= 360
        scalar = math.cos(math.radians(diff))
        abs_diff = abs(diff)
        if abs_diff <= 45:
            label = 'Out'
        elif abs_diff >= 135:
            label = 'In'
        elif (diff > 0 and diff < 135) or diff < -135:
            label = 'L-R'
        else:
            label = 'R-L'
        return label, scalar

    def _compute_wind_effect_hr(self, wind_speed, wind_scalar):
        if wind_speed < 3:
            return 0.0
        raw = (wind_speed / 10.0) * 0.08 * wind_scalar
        return max(-0.15, min(0.15, raw))

    def _compute_temperature_effect_hr(self, temperature):
        return max(-0.08, min(0.08, (temperature - 70.0) * 0.002))

    def _compute_temperature_effect_k(self, temperature):
        return 0.02 if temperature < 50 else 0.0


# ── Module-level convenience function ────────────────────────────────────────

_default_client = None


def get_game_weather(home_team: str, game_time_utc: str = None,
                     venue: str = None) -> Dict:
    """Convenience wrapper. Creates a shared client on first call."""
    global _default_client
    if _default_client is None:
        _default_client = WeatherClient()
    return _default_client.get_game_weather(home_team, game_time_utc, venue)


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == '__main__':
    client = WeatherClient()
    test_cases = [
        ('COL', None, 'Coors Field'),
        ('NYY', None, 'Yankee Stadium'),
        ('TB',  None, 'Tropicana Field'),   # Dome
        ('CHC', None, 'Wrigley Field'),
        ('SF',  None, 'Oracle Park'),
    ]
    print("[Weather Client - Open-Meteo] Park weather tests (no API key needed):\n")
    for team, game_time, park_name in test_cases:
        w = client.get_game_weather(team, game_time)
        print(f"  {team} ({park_name}):")
        print(f"    Temp:      {w['temperature']}F")
        print(f"    Wind:      {w['wind_speed']}mph {w['wind_direction']}")
        print(f"    Conditions:{w['conditions']}")
        print(f"    HR effect: {w['wind_effect_hr']:+.3f}")
        print(f"    Is dome:   {w['is_dome']}")
        print()
