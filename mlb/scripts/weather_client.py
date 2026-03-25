"""
Weather Client for MLB Games
=============================

Fetches real-time weather data at each MLB ballpark using the OpenWeatherMap API.
Weather significantly affects MLB props — especially home runs, total bases, and
pitcher strikeouts.

Key effects:
  Wind Out (blowing to CF): +10-15% HR boost, more total bases
  Wind In  (blowing from CF): -10-15% HR suppression
  Cold (<45°F): Ball doesn't carry as well → HR suppression
  Hot (>90°F):  Ball carries better
  Rain/Dome:    Neutral (dome) or variable (rain game context)

Requires: OPENWEATHERMAP_API_KEY environment variable

Endpoints:
  Forecast: https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={key}&units=imperial
  Current:  https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={key}&units=imperial
"""

import math
import time
import requests
from datetime import datetime, timezone
from typing import Dict, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import OPENWEATHERMAP_API_KEY, OPENWEATHERMAP_BASE, MLB_API_TIMEOUT
from park_factors import PARK_FACTORS, TEAM_TO_PARK, get_park_info, get_park_info_by_team, is_dome_or_retractable


# ============================================================================
# BALLPARK ORIENTATION DATABASE
# Each park's "orientation_deg" = compass direction the batter faces at home plate.
# Wind FROM this direction blows "In" (from CF toward home plate).
# Wind TO this direction blows "Out" (from home plate to CF).
# Crosswinds are perpendicular to this axis.
# ============================================================================

# Neutral weather result for domed parks
DOME_WEATHER = {
    'temperature': 72,
    'wind_speed': 0,
    'wind_direction': 'Dome',
    'conditions': 'Clear',
    'is_dome': True,
    'raw_wind_deg': 0,
}

# Default weather when API unavailable
DEFAULT_WEATHER = {
    'temperature': 68,
    'wind_speed': 5,
    'wind_direction': 'Calm',
    'conditions': 'Clear',
    'is_dome': False,
    'raw_wind_deg': 0,
}


class WeatherClient:
    """
    Fetches and processes weather data for MLB ballparks.

    Uses OpenWeatherMap forecast API to get weather closest to game time.
    Falls back to current weather if forecast unavailable.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or OPENWEATHERMAP_API_KEY
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'SportsPredictor/1.0'})
        self._cache: Dict[str, Dict] = {}  # Simple in-memory cache

    def get_game_weather(self, home_team: str, game_time_utc: str = None,
                         venue: str = None) -> Dict:
        """
        Get weather for a game at the home team's ballpark.

        Args:
            home_team: Team abbreviation (e.g., 'COL', 'NYY')
            game_time_utc: ISO format UTC game time (e.g., '2026-04-01T19:10:00Z')
                           If None, uses current time.
            venue: Park name (optional — used if home_team lookup fails)

        Returns:
            Weather dict with: temperature, wind_speed, wind_direction, conditions,
                               is_dome, raw_wind_deg, wind_effect_hr, wind_effect_k
        """
        # Check if park is a dome/retractable (skip API call)
        park_name = venue or TEAM_TO_PARK.get(home_team.upper(), '')
        if park_name and is_dome_or_retractable(park_name):
            result = dict(DOME_WEATHER)
            result['wind_effect_hr'] = 0.0
            result['wind_effect_k'] = 0.0
            return result

        # Look up park info
        park_info = get_park_info_by_team(home_team.upper()) if not venue else get_park_info(venue)
        if not park_info:
            print(f"[Weather] Unknown park for team {home_team}, using defaults")
            result = dict(DEFAULT_WEATHER)
            result['wind_effect_hr'] = 0.0
            result['wind_effect_k'] = 0.0
            return result

        lat = park_info.get('lat')
        lon = park_info.get('lon')
        if not lat or not lon:
            result = dict(DEFAULT_WEATHER)
            result['wind_effect_hr'] = 0.0
            result['wind_effect_k'] = 0.0
            return result

        if not self.api_key:
            print(f"[Weather] No OPENWEATHERMAP_API_KEY set — using defaults for {home_team}")
            result = dict(DEFAULT_WEATHER)
            result['wind_effect_hr'] = 0.0
            result['wind_effect_k'] = 0.0
            return result

        # Cache key
        cache_key = f"{lat:.3f}_{lon:.3f}"
        if cache_key in self._cache:
            raw = self._cache[cache_key]
        else:
            raw = self._fetch_weather(lat, lon, game_time_utc)
            self._cache[cache_key] = raw

        if not raw:
            result = dict(DEFAULT_WEATHER)
            result['wind_effect_hr'] = 0.0
            result['wind_effect_k'] = 0.0
            return result

        # Process raw data into our standardized format
        orientation_deg = park_info.get('orientation_deg', 0)
        return self._process_weather(raw, orientation_deg)

    def _fetch_weather(self, lat: float, lon: float, game_time_utc: str = None) -> Optional[Dict]:
        """
        Fetch weather data from OpenWeatherMap.

        Tries forecast API first (for future games), falls back to current weather.

        Args:
            lat: Latitude
            lon: Longitude
            game_time_utc: Game time in UTC ISO format

        Returns:
            Raw weather dict or None
        """
        params = {
            'lat': lat,
            'lon': lon,
            'appid': self.api_key,
            'units': 'imperial',  # Fahrenheit, mph
        }

        # Try to get forecast close to game time
        if game_time_utc:
            try:
                game_dt = datetime.fromisoformat(game_time_utc.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                hours_until_game = (game_dt - now).total_seconds() / 3600

                # Forecast API works up to 5 days out
                if 0 < hours_until_game < 120:
                    forecast = self._get_api(f'{OPENWEATHERMAP_BASE}/forecast', params)
                    if forecast:
                        return self._find_closest_forecast(forecast, game_dt)
            except (ValueError, TypeError):
                pass

        # Fallback: current weather
        return self._get_api(f'{OPENWEATHERMAP_BASE}/weather', params)

    def _get_api(self, url: str, params: Dict) -> Optional[Dict]:
        """Make API call with retry."""
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=MLB_API_TIMEOUT)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 401:
                    print(f"[Weather] Invalid API key (401). Check OPENWEATHERMAP_API_KEY.")
                    return None
                if resp.status_code in (429, 500, 502, 503):
                    time.sleep(2 ** attempt)
                    continue
            except requests.exceptions.Timeout:
                time.sleep(2 ** attempt)
            except Exception as e:
                print(f"[Weather] Error: {e}")
                return None
        return None

    def _find_closest_forecast(self, forecast_data: Dict, target_dt: datetime) -> Optional[Dict]:
        """Find the forecast entry closest to game time."""
        forecast_list = forecast_data.get('list', [])
        if not forecast_list:
            return None

        closest = None
        min_diff = float('inf')

        for entry in forecast_list:
            try:
                entry_dt = datetime.fromtimestamp(entry['dt'], tz=timezone.utc)
                diff = abs((entry_dt - target_dt).total_seconds())
                if diff < min_diff:
                    min_diff = diff
                    closest = entry
            except (KeyError, TypeError):
                continue

        return closest

    def _process_weather(self, raw: Dict, park_orientation_deg: int) -> Dict:
        """
        Convert raw OpenWeatherMap data to our standardized format.

        Args:
            raw: Raw API response (single weather entry or current weather)
            park_orientation_deg: Compass direction batter faces at home plate

        Returns:
            Standardized weather dict
        """
        # Extract fields (handle both 'list' entries and 'current' format)
        main = raw.get('main', {})
        wind = raw.get('wind', {})
        weather_list = raw.get('weather', [{}])

        temperature = main.get('temp', 68.0)
        wind_speed = wind.get('speed', 0.0)
        wind_deg = wind.get('deg', 0)   # Meteorological wind direction (FROM)
        conditions_code = weather_list[0].get('main', 'Clear') if weather_list else 'Clear'

        # Parse wind direction relative to ballpark
        wind_direction, wind_scalar = self._parse_wind_direction(
            wind_speed, wind_deg, park_orientation_deg
        )

        # Compute effect multipliers for props
        wind_effect_hr = self._compute_wind_effect_hr(wind_speed, wind_scalar)
        wind_effect_k = self._compute_temperature_effect_k(temperature)

        # Temperature effect on HR (cold air = dense = ball doesn't carry)
        temp_effect_hr = self._compute_temperature_effect_hr(temperature)
        combined_hr_effect = wind_effect_hr + temp_effect_hr

        return {
            'temperature': round(temperature),
            'wind_speed': round(wind_speed),
            'wind_direction': wind_direction,
            'conditions': conditions_code,
            'is_dome': False,
            'raw_wind_deg': wind_deg,
            'wind_scalar': wind_scalar,   # -1=In, 0=Calm/Cross, +1=Out
            'wind_effect_hr': round(combined_hr_effect, 3),  # Additive % adj to HR prob
            'wind_effect_k': round(wind_effect_k, 3),        # Additive % adj to K prob
        }

    def _parse_wind_direction(self, wind_speed: float, wind_deg: int,
                               park_orientation_deg: int) -> tuple:
        """
        Convert meteorological wind direction to ballpark-relative direction.

        Meteorological convention: wind_deg = direction wind is coming FROM.
        e.g., wind_deg=45 means wind is blowing FROM the NE (toward SW).

        Park orientation: compass direction batter faces = direction to CF.

        If wind is coming FROM CF direction (behind pitcher toward plate): "In"
        If wind is blowing TOWARD CF (from plate toward outfield): "Out"
        Perpendicular winds: "L-R" or "R-L"

        Args:
            wind_speed: Wind speed in mph
            wind_deg: Meteorological wind direction (FROM)
            park_orientation_deg: Direction batter faces (toward CF)

        Returns:
            Tuple of (direction_label, scalar) where scalar:
              +1 = Out to CF (boosts HR/TB)
              -1 = In from CF (suppresses HR/TB)
              0  = Calm or crosswind
        """
        if wind_speed < 3:
            return 'Calm', 0.0

        # Wind direction FROM (meteorological) → direction wind is blowing TO
        wind_blowing_to_deg = (wind_deg + 180) % 360

        # Difference between wind's target direction and CF direction
        diff = (wind_blowing_to_deg - park_orientation_deg) % 360
        if diff > 180:
            diff -= 360  # Normalize to -180 to +180

        # Compute scalar: 1.0 = directly out, -1.0 = directly in
        scalar = math.cos(math.radians(diff))

        # Label
        abs_diff = abs(diff)
        if abs_diff <= 45:
            label = 'Out'      # Wind helping fly balls
        elif abs_diff >= 135:
            label = 'In'       # Wind suppressing fly balls
        elif 45 < abs_diff < 135:
            # Crosswind
            if (diff > 0 and diff < 135) or diff < -135:
                label = 'L-R'
            else:
                label = 'R-L'
        else:
            label = 'Variable'

        return label, scalar

    def _compute_wind_effect_hr(self, wind_speed: float, wind_scalar: float) -> float:
        """
        Estimate wind effect on home run probability.

        Research suggests:
          10mph directly out: ~+10% HR (roughly +0.10 on probability)
          10mph directly in:  ~-10% HR (roughly -0.10 on probability)
          Crosswind: minimal effect

        Returns additive probability adjustment (not multiplicative).
        """
        if wind_speed < 3:
            return 0.0

        # Scale: 10mph direct out wind → +0.08 probability boost
        raw_effect = (wind_speed / 10.0) * 0.08 * wind_scalar

        # Cap effect at ±0.15 (15 percentage points max)
        return max(-0.15, min(0.15, raw_effect))

    def _compute_temperature_effect_hr(self, temperature: float) -> float:
        """
        Estimate temperature effect on home run probability.

        Cold air is denser → ball doesn't carry as far.
        Hot air is less dense → ball carries further.

        Baseline: 70°F = 0 effect
        45°F: ~-5% HR suppression
        90°F: ~+5% HR boost
        """
        baseline_temp = 70.0
        temp_diff = temperature - baseline_temp

        # ~0.002 probability change per degree from baseline
        raw_effect = temp_diff * 0.002

        # Cap at ±0.08
        return max(-0.08, min(0.08, raw_effect))

    def _compute_temperature_effect_k(self, temperature: float) -> float:
        """
        Estimate temperature effect on strikeout probability.

        Cold weather can affect pitcher grip and arm elasticity,
        but the effect on Ks is smaller than on HR. Roughly:
        - Cold (<50°F): slight Ks increase (batters less comfortable)
        - Hot (>85°F): negligible effect
        """
        if temperature < 50:
            return 0.02  # Very slight K boost in cold
        return 0.0


# ============================================================================
# Module-level convenience function
# ============================================================================

_default_client = None


def get_game_weather(home_team: str, game_time_utc: str = None, venue: str = None) -> Dict:
    """
    Module-level convenience function. Creates a shared client on first call.

    Args:
        home_team: Team abbreviation
        game_time_utc: ISO UTC game time
        venue: Ballpark name (optional)

    Returns:
        Weather dict
    """
    global _default_client
    if _default_client is None:
        _default_client = WeatherClient()
    return _default_client.get_game_weather(home_team, game_time_utc, venue)


# ============================================================================
# Quick test / standalone usage
# ============================================================================

if __name__ == '__main__':
    import sys

    client = WeatherClient()

    # Test some parks
    test_cases = [
        ('COL', None, 'Coors Field'),
        ('NYY', None, 'Yankee Stadium'),
        ('TB', None, 'Tropicana Field'),  # Dome
        ('CHC', None, 'Wrigley Field'),
    ]

    print("[Weather Client] Park weather tests:\n")
    for team, game_time, park_name in test_cases:
        weather = client.get_game_weather(team, game_time)
        print(f"  {team} ({park_name}):")
        print(f"    Temp: {weather['temperature']}°F")
        print(f"    Wind: {weather['wind_speed']}mph {weather['wind_direction']}")
        print(f"    Cond: {weather['conditions']}")
        print(f"    HR effect: {weather['wind_effect_hr']:+.3f}")
        print(f"    Is dome:   {weather['is_dome']}")
        print()
