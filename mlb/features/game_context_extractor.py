"""
MLB Game Context Extractor
===========================

Packages park factors, weather, and Vegas odds into a unified feature dict.
These 'ctx_*' features provide the macro-level game environment that
affects all props regardless of player-specific stats.

Features extracted (~15 features, all 'ctx_' prefixed):
  Park:    ctx_park_hr_factor, ctx_park_hits_factor, ctx_park_k_factor,
           ctx_park_runs_factor, ctx_altitude
  Vegas:   ctx_game_total, ctx_home_ml, ctx_implied_home_runs, ctx_implied_away_runs
  Weather: ctx_temperature, ctx_wind_speed, ctx_wind_direction_encoded,
           ctx_conditions_encoded, ctx_is_dome
  Game:    ctx_day_night

Usage:
    extractor = GameContextExtractor(db_path)
    ctx = extractor.extract(game_id, home_team, away_team, venue, player_type)
    # ctx = {'ctx_park_hr_factor': 1.40, 'ctx_game_total': 9.5, ...}
"""

import sqlite3
from typing import Dict, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from mlb_config import get_db_connection
from park_factors import get_park_factor, get_park_info, get_altitude, is_dome_or_retractable
from espn_mlb_api import ESPNMLBApi


# Neutral defaults when game context is unavailable
DEFAULT_CONTEXT = {
    'ctx_park_hr_factor':        1.00,
    'ctx_park_hits_factor':      1.00,
    'ctx_park_k_factor':         1.00,
    'ctx_park_runs_factor':      1.00,
    'ctx_altitude':              0,
    'ctx_game_total':            9.0,    # League average O/U
    'ctx_home_ml':               -110,
    'ctx_implied_home_runs':     4.5,
    'ctx_implied_away_runs':     4.5,
    'ctx_temperature':           68,
    'ctx_wind_speed':            5,
    'ctx_wind_direction_encoded': 0.0,  # 0 = calm/neutral
    'ctx_conditions_encoded':    0.0,   # 0 = clear
    'ctx_is_dome':               0,
    'ctx_day_night':             1,     # 1 = night (most games)
}

# Wind direction encoding
WIND_DIRECTION_ENCODING = {
    'Out':    1.0,   # Blowing toward CF — boosts HR
    'L-R':    0.3,   # Slight crosswind
    'R-L':   -0.3,   # Slight crosswind
    'In':    -1.0,   # Blowing from CF — suppresses HR
    'Calm':   0.0,
    'Dome':   0.0,
    'Variable': 0.0,
}

# Weather conditions encoding
CONDITIONS_ENCODING = {
    'Clear':      0.0,
    'Clouds':     0.1,
    'Drizzle':    0.5,
    'Rain':       0.8,
    'Thunderstorm': 1.0,
    'Snow':       1.0,
    'Mist':       0.3,
    'Fog':        0.4,
}


class GameContextExtractor:
    """
    Extracts game-level context features (park, weather, Vegas) for a prediction.

    Reads from the game_context table first, falls back to live API calls
    if the context hasn't been saved yet.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path
        self._espn_api = ESPNMLBApi()

    def extract(self, game_id: str, home_team: str, away_team: str,
                venue: str, day_night: str = 'night') -> Dict:
        """
        Extract all game context features for a single game.

        Args:
            game_id: MLB game ID (as stored in game_context table)
            home_team: Home team abbreviation
            away_team: Away team abbreviation
            venue: Ballpark name (e.g., 'Coors Field')
            day_night: 'day' or 'night'

        Returns:
            Dict of ctx_* features
        """
        # Try DB first (fastest path — game_context should be populated already)
        db_context = self._get_from_db(game_id)

        if db_context:
            return self._build_features(db_context, venue)

        # Fallback: compute from venue name directly (no Vegas, no live weather)
        return self._build_features_from_venue(venue, day_night)

    def extract_from_row(self, game_context_row: Dict) -> Dict:
        """
        Build feature dict directly from a game_context DB row.

        Args:
            game_context_row: Dict from game_context table

        Returns:
            Dict of ctx_* features
        """
        return self._build_features(game_context_row,
                                    game_context_row.get('venue', ''))

    # -------------------------------------------------------------------------
    # Internal methods
    # -------------------------------------------------------------------------

    def _get_from_db(self, game_id: str) -> Optional[Dict]:
        """Fetch game_context row from database."""
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.execute(
                'SELECT * FROM game_context WHERE game_id = ?',
                (str(game_id),)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _build_features(self, game_context: Dict, venue: str) -> Dict:
        """
        Build ctx_* feature dict from a game_context DB row.

        Args:
            game_context: Dict with DB row fields
            venue: Ballpark name (may be in game_context or passed separately)
        """
        features = {}

        # Use venue from context if not provided
        venue = venue or game_context.get('venue', '')

        # --- Park factors ---
        features['ctx_park_hr_factor']   = get_park_factor(venue, 'hr')
        features['ctx_park_hits_factor'] = get_park_factor(venue, 'hits')
        features['ctx_park_k_factor']    = get_park_factor(venue, 'k')
        features['ctx_park_runs_factor'] = get_park_factor(venue, 'runs')
        features['ctx_altitude']         = get_altitude(venue)
        features['ctx_is_dome']          = 1 if is_dome_or_retractable(venue) else 0

        # --- Vegas ---
        game_total = game_context.get('game_total')
        home_ml    = game_context.get('home_ml')
        away_ml    = game_context.get('away_ml')

        features['ctx_game_total'] = game_total or DEFAULT_CONTEXT['ctx_game_total']
        features['ctx_home_ml']    = home_ml or DEFAULT_CONTEXT['ctx_home_ml']

        # Implied team run totals from moneyline + game total
        if game_total and home_ml:
            home_prob = ESPNMLBApi.ml_to_implied_prob(home_ml)
            # Simple implied run split (favorite gets slightly more of the total)
            # Normalized around 0.5 win probability → equal run split
            home_implied = game_total * home_prob * (1 / 0.5) * 0.5
            home_implied = max(game_total * 0.35, min(game_total * 0.65, home_implied))
            features['ctx_implied_home_runs'] = round(home_implied, 2)
            features['ctx_implied_away_runs'] = round(game_total - home_implied, 2)
        else:
            features['ctx_implied_home_runs'] = DEFAULT_CONTEXT['ctx_implied_home_runs']
            features['ctx_implied_away_runs'] = DEFAULT_CONTEXT['ctx_implied_away_runs']

        # --- Weather ---
        # Skip weather for domed parks
        if features['ctx_is_dome']:
            features['ctx_temperature']           = 72
            features['ctx_wind_speed']            = 0
            features['ctx_wind_direction_encoded'] = 0.0
            features['ctx_conditions_encoded']    = 0.0
        else:
            temp = game_context.get('temperature')
            wind_speed = game_context.get('wind_speed')
            wind_dir = game_context.get('wind_direction', 'Calm')
            conditions = game_context.get('conditions', 'Clear')

            features['ctx_temperature']           = temp or DEFAULT_CONTEXT['ctx_temperature']
            features['ctx_wind_speed']            = wind_speed or DEFAULT_CONTEXT['ctx_wind_speed']
            features['ctx_wind_direction_encoded'] = WIND_DIRECTION_ENCODING.get(wind_dir, 0.0)
            features['ctx_conditions_encoded']    = CONDITIONS_ENCODING.get(conditions, 0.0)

        # --- Game ---
        day_night = game_context.get('day_night', 'night')
        features['ctx_day_night'] = 0 if day_night == 'day' else 1

        return features

    def _build_features_from_venue(self, venue: str, day_night: str = 'night') -> Dict:
        """Build minimal features from just the venue name (no DB context available)."""
        features = dict(DEFAULT_CONTEXT)

        if venue:
            features['ctx_park_hr_factor']   = get_park_factor(venue, 'hr')
            features['ctx_park_hits_factor'] = get_park_factor(venue, 'hits')
            features['ctx_park_k_factor']    = get_park_factor(venue, 'k')
            features['ctx_park_runs_factor'] = get_park_factor(venue, 'runs')
            features['ctx_altitude']         = get_altitude(venue)
            features['ctx_is_dome']          = 1 if is_dome_or_retractable(venue) else 0

        features['ctx_day_night'] = 0 if day_night == 'day' else 1
        return features

    # -------------------------------------------------------------------------
    # Altitude adjustment helper
    # -------------------------------------------------------------------------

    @staticmethod
    def get_altitude_hr_boost(venue: str) -> float:
        """
        Compute the altitude-based HR probability boost.

        Coors Field (5200ft) gets approximately +12-14% on HR props
        due to thin air allowing ball to travel farther.

        Returns:
            Additive probability boost (e.g., 0.12 for Coors)
        """
        alt = get_altitude(venue)
        if alt < 500:
            return 0.0
        # Roughly 1% boost per 500ft above 500ft threshold
        boost = (alt - 500) / 500 * 0.01
        return round(min(boost, 0.15), 3)  # Cap at 15%
