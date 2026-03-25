"""
MLB Pitcher Feature Extractor
==============================

Extracts ~25 features for pitcher prop predictions from the player_game_logs table.
Used for: strikeouts, outs_recorded, pitcher_walks, hits_allowed, earned_runs

Features capture:
  - Season-level efficiency rates (K/9, BB/9, WHIP, ERA, FIP-proxy)
  - Recent form in last 3 and last 5 starts
  - Consistency (standard deviation of key stats)
  - Trend (improving or declining over last 5 starts)
  - Efficiency proxies (average pitches, pitches-per-out)
  - Context (home/away, days rest)
  - Data quality flags (insufficient data warning)

Temporal safety: All queries use game_date < target_date — no future data.
"""

import math
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from mlb_config import get_db_connection, MIN_PITCHER_STARTS_FOR_PREDICTION
from mlb_stats_api import MLBStatsAPI


# League-average defaults (used when insufficient pitcher data)
LEAGUE_AVG_PITCHER = {
    'f_season_k9':           8.5,    # ~2024 MLB average
    'f_season_bb9':          3.2,
    'f_season_whip':         1.30,
    'f_season_h9':           9.0,
    'f_season_er9':          4.20,   # ERA
    'f_season_hr9':          1.25,
    'f_l3_avg_k':            5.5,
    'f_l5_avg_k':            5.5,
    'f_l3_avg_outs':         15.0,   # ~5 innings
    'f_l5_avg_outs':         15.0,
    'f_l3_avg_hits':         6.0,
    'f_l5_avg_er':           2.5,
    'f_avg_pitches':         90.0,
    'f_avg_pitches_per_out': 5.0,
    'f_days_rest':           5,
    'f_is_home':             0.5,    # Unknown
    'f_trend_k':             0.0,    # Flat trend
    'f_std_k':               2.5,
    'f_std_outs':            4.0,
    'f_insufficient_data':   1,
    'f_starts_counted':      0,
}


class PitcherFeatureExtractor:
    """
    Extracts pitcher-specific features from historical game logs.

    All features are prefixed with 'f_' to match the NHL pattern and make
    them identifiable in the features_json blob.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path
        self._api = MLBStatsAPI()

    def extract(self, player_name: str, team: str, target_date: str,
                home_away: str = 'home', player_id: int = None) -> Dict:
        """
        Extract all pitcher features for a prediction on target_date.

        Args:
            player_name: Full player name (e.g., 'Gerrit Cole')
            team: Team abbreviation (e.g., 'NYY')
            target_date: Date of prediction (YYYY-MM-DD) — features use data < this date
            home_away: 'home' or 'away'
            player_id: Optional MLB player ID (for API enrichment)

        Returns:
            Dict of feature_name → float (all 'f_' prefixed)
        """
        conn = get_db_connection(self.db_path)
        try:
            starts = self._get_pitcher_starts(conn, player_name, team, target_date)

            if len(starts) < MIN_PITCHER_STARTS_FOR_PREDICTION:
                # Insufficient local data — try to enrich from MLB API
                api_features = self._get_api_features(player_name, player_id, target_date)
                features = {**LEAGUE_AVG_PITCHER.copy(), **api_features}
                features['f_insufficient_data'] = 1
                features['f_starts_counted'] = len(starts)
                features['f_is_home'] = 1 if home_away == 'home' else 0
                features['f_days_rest'] = self._compute_days_rest(starts, target_date)
                return features

            # Compute features from historical starts
            features = {}
            features['f_insufficient_data'] = 0
            features['f_starts_counted'] = len(starts)
            features['f_is_home'] = 1 if home_away == 'home' else 0

            # Season aggregates
            season_features = self._compute_season_features(starts)
            features.update(season_features)

            # Recent form
            recent_features = self._compute_recent_features(starts)
            features.update(recent_features)

            # Efficiency
            efficiency_features = self._compute_efficiency_features(starts)
            features.update(efficiency_features)

            # Trend
            trend_features = self._compute_trend_features(starts)
            features.update(trend_features)

            # Context
            features['f_days_rest'] = self._compute_days_rest(starts, target_date)

            return features

        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Data fetching
    # -------------------------------------------------------------------------

    def _get_pitcher_starts(self, conn: sqlite3.Connection, player_name: str,
                             team: str, target_date: str) -> List[Dict]:
        """
        Fetch pitcher's historical starts from player_game_logs.

        Only includes games where the pitcher actually started (outs_recorded > 0).
        Respects temporal boundary: game_date < target_date.
        """
        cursor = conn.execute('''
            SELECT
                game_date, outs_recorded, strikeouts_pitched,
                walks_allowed, hits_allowed, earned_runs,
                home_runs_allowed, pitches, innings_pitched, opponent
            FROM player_game_logs
            WHERE player_type = 'pitcher'
              AND game_date < ?
              AND outs_recorded > 0
              AND (player_name = ? OR player_name LIKE ?)
            ORDER BY game_date DESC
            LIMIT 30
        ''', (target_date, player_name, f'%{player_name.split()[-1]}%'))

        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _get_api_features(self, player_name: str, player_id: int,
                           target_date: str) -> Dict:
        """
        Try to get season stats from MLB API when local data is insufficient.

        Returns empty dict if API unavailable.
        """
        if not player_id:
            # Try name search
            result = self._api.search_player(player_name)
            if result:
                player_id = result.get('id')

        if not player_id:
            return {}

        year = target_date[:4]
        stats = self._api.get_player_season_stats(player_id, year, 'pitching')
        if not stats:
            return {}

        ip = self._api.compute_era  # Grab the static methods
        ip_val = float(stats.get('inningsPitched', '0').split('.')[0] or 0)
        # Convert '5.2' → decimal
        ip_str = stats.get('inningsPitched', '0.0')
        ip_dec = MLBStatsAPI._parse_innings_pitched(ip_str)

        if ip_dec <= 0:
            return {}

        so = stats.get('strikeOuts', 0)
        bb = stats.get('baseOnBalls', 0)
        h = stats.get('hits', 0)
        er = stats.get('earnedRuns', 0)
        hr = stats.get('homeRuns', 0)

        return {
            'f_season_k9':  MLBStatsAPI.compute_k9(so, ip_dec),
            'f_season_bb9': MLBStatsAPI.compute_bb9(bb, ip_dec),
            'f_season_whip': MLBStatsAPI.compute_whip(h, bb, ip_dec),
            'f_season_h9':  MLBStatsAPI.compute_h9(h, ip_dec),
            'f_season_er9': MLBStatsAPI.compute_era(er, ip_dec),
            'f_season_hr9': MLBStatsAPI.compute_hr9(hr, ip_dec),
        }

    # -------------------------------------------------------------------------
    # Feature computation
    # -------------------------------------------------------------------------

    def _compute_season_features(self, starts: List[Dict]) -> Dict:
        """Compute season-aggregate features (all starts available)."""
        total_outs = sum(s.get('outs_recorded', 0) for s in starts)
        total_ip = total_outs / 3.0

        if total_ip <= 0:
            return {k: v for k, v in LEAGUE_AVG_PITCHER.items()
                    if k.startswith('f_season_')}

        total_k  = sum(s.get('strikeouts_pitched', 0) for s in starts)
        total_bb = sum(s.get('walks_allowed', 0) for s in starts)
        total_h  = sum(s.get('hits_allowed', 0) for s in starts)
        total_er = sum(s.get('earned_runs', 0) for s in starts)
        total_hr = sum(s.get('home_runs_allowed', 0) for s in starts)

        return {
            'f_season_k9':  MLBStatsAPI.compute_k9(total_k, total_ip),
            'f_season_bb9': MLBStatsAPI.compute_bb9(total_bb, total_ip),
            'f_season_whip': MLBStatsAPI.compute_whip(total_h, total_bb, total_ip),
            'f_season_h9':  MLBStatsAPI.compute_h9(total_h, total_ip),
            'f_season_er9': MLBStatsAPI.compute_era(total_er, total_ip),
            'f_season_hr9': MLBStatsAPI.compute_hr9(total_hr, total_ip),
        }

    def _compute_recent_features(self, starts: List[Dict]) -> Dict:
        """Compute last-3 and last-5 start averages."""
        l3 = starts[:3]
        l5 = starts[:5]

        def safe_avg(data, key):
            vals = [d.get(key, 0) or 0 for d in data]
            return sum(vals) / len(vals) if vals else 0.0

        return {
            'f_l3_avg_k':     safe_avg(l3, 'strikeouts_pitched'),
            'f_l5_avg_k':     safe_avg(l5, 'strikeouts_pitched'),
            'f_l3_avg_outs':  safe_avg(l3, 'outs_recorded'),
            'f_l5_avg_outs':  safe_avg(l5, 'outs_recorded'),
            'f_l3_avg_hits':  safe_avg(l3, 'hits_allowed'),
            'f_l5_avg_er':    safe_avg(l5, 'earned_runs'),
        }

    def _compute_efficiency_features(self, starts: List[Dict]) -> Dict:
        """Compute pitch efficiency features."""
        pitches = [s.get('pitches', 0) or 0 for s in starts[:10] if s.get('pitches')]
        outs    = [s.get('outs_recorded', 0) or 0 for s in starts[:10] if s.get('outs_recorded')]

        avg_pitches = sum(pitches) / len(pitches) if pitches else 90.0

        pitches_per_out = []
        for s in starts[:10]:
            p = s.get('pitches', 0) or 0
            o = s.get('outs_recorded', 0) or 0
            if p > 0 and o > 0:
                pitches_per_out.append(p / o)

        avg_ppo = sum(pitches_per_out) / len(pitches_per_out) if pitches_per_out else 5.0

        return {
            'f_avg_pitches':          avg_pitches,
            'f_avg_pitches_per_out':  avg_ppo,
        }

    def _compute_trend_features(self, starts: List[Dict]) -> Dict:
        """
        Compute trend (slope) of Ks over last 5 starts.

        Positive = improving (K rate going up)
        Negative = declining (K rate going down)
        Normalized to approximately -1 to +1 range.
        """
        l5 = starts[:5]
        if len(l5) < 3:
            return {'f_trend_k': 0.0, 'f_std_k': 2.5, 'f_std_outs': 4.0}

        # Ks in reverse chronological order (starts[0] = most recent)
        ks = [s.get('strikeouts_pitched', 0) or 0 for s in l5]
        ks.reverse()  # Oldest first for trend calculation

        slope = self._linear_slope(ks)
        normalized_slope = math.tanh(slope / 2.0)  # Normalize to -1 to +1

        # Standard deviations
        k_vals = [s.get('strikeouts_pitched', 0) or 0 for s in starts[:10]]
        o_vals = [s.get('outs_recorded', 0) or 0 for s in starts[:10]]
        std_k   = self._std(k_vals)
        std_outs = self._std(o_vals)

        return {
            'f_trend_k':  normalized_slope,
            'f_std_k':    std_k,
            'f_std_outs': std_outs,
        }

    def _compute_days_rest(self, starts: List[Dict], target_date: str) -> int:
        """Compute days since most recent start."""
        if not starts:
            return 5  # Default: normal rest

        try:
            last_start_date = starts[0].get('game_date', '')
            if not last_start_date:
                return 5
            last_dt = datetime.strptime(last_start_date, '%Y-%m-%d')
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')
            return (target_dt - last_dt).days
        except (ValueError, TypeError):
            return 5

    # -------------------------------------------------------------------------
    # Math helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _linear_slope(values: List[float]) -> float:
        """Compute slope of a simple linear regression."""
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        den = sum((i - x_mean) ** 2 for i in range(n))
        return num / den if den != 0 else 0.0

    @staticmethod
    def _std(values: List[float]) -> float:
        """Compute standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)
