"""
MLB Opponent Feature Extractor
================================

Extracts features representing the QUALITY of the opposition:
  - For batter props: opposing starting pitcher quality (ERA, WHIP, K/9, etc.)
  - For pitcher props: opposing team's plate discipline (K%, BB%, OPS)

These matchup features are critical for MLB prediction quality.
A good batter vs a bad pitcher is very different from a good batter vs an ace.

Two sub-extractors:
  A) Opposing pitcher features (~10 features with 'opp_pitcher_' prefix)
  B) Opposing team offensive quality (~5 features with 'opp_team_' prefix)

Temporal safety: All queries use game_date < target_date.
"""

import math
import sqlite3
from typing import Dict, List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from mlb_config import get_db_connection
from mlb_stats_api import MLBStatsAPI


# Defaults when opposing pitcher/team data is insufficient
DEFAULT_OPP_PITCHER = {
    'opp_pitcher_era':       4.20,
    'opp_pitcher_whip':      1.30,
    'opp_pitcher_k9':        8.5,
    'opp_pitcher_bb9':       3.2,
    'opp_pitcher_l3_k_avg':  5.5,    # Avg Ks in last 3 starts
    'opp_pitcher_hr9':       1.25,
    'opp_pitcher_days_rest': 5,
    'opp_pitcher_is_home':   0.5,
    'opp_pitcher_known':     0,       # 0 = TBD, 1 = confirmed
    'opp_pitcher_difficulty': 0.5,   # 0=easy, 1=ace; composite score
    'opp_pitcher_lineup_k_rate': 0.23, # Team strikeout tendency
    'opp_pitcher_lineup_tb_rate': 1.2,  # Team total base tendency
}

DEFAULT_OPP_TEAM = {
    'opp_team_k_pct':         0.230,
    'opp_team_bb_pct':        0.085,
    'opp_team_obp':           0.318,
    'opp_team_ops':           0.730,
    'opp_team_recent_scoring': 4.5,  # Runs/game last 14 days
}


class OpponentFeatureExtractor:
    """
    Extracts opposition quality features for both pitcher and batter props.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path
        self._api = MLBStatsAPI()

    # =========================================================================
    # A) Opposing pitcher features (for BATTER props)
    # =========================================================================

    def extract_pitcher_matchup(self, pitcher_name: str, pitcher_id: Optional[int],
                                 target_date: str, batter_hand: str = 'R',
                                 pitcher_is_home: bool = False,
                                 batter_team: str = None) -> Dict:
        """
        Extract opposing starting pitcher features for batter prop predictions.

        Args:
            pitcher_name: Starting pitcher's name (or 'TBD')
            pitcher_id: MLB player ID (optional)
            target_date: Prediction date YYYY-MM-DD
            batter_hand: Batter's hitting hand ('L', 'R', 'S')
            pitcher_is_home: Whether pitcher is at home
            batter_team: Team of the batter (for lineup friction features)

        Returns:
            Dict with 'opp_pitcher_*' features
        """
        if not pitcher_name or pitcher_name == 'TBD':
            result = dict(DEFAULT_OPP_PITCHER)
            result['opp_pitcher_known'] = 0
            return result

        conn = get_db_connection(self.db_path)
        try:
            starts = self._get_pitcher_starts(conn, pitcher_name, target_date)

            features = {}
            features['opp_pitcher_known'] = 1
            features['opp_pitcher_is_home'] = 1 if pitcher_is_home else 0

            if not starts:
                # Try MLB API for season stats
                api_feats = self._get_pitcher_api_features(pitcher_name, pitcher_id,
                                                            target_date)
                features.update({**DEFAULT_OPP_PITCHER, **api_feats})
            else:
                # Season stats from local data
                total_outs = sum(s.get('outs_recorded', 0) or 0 for s in starts)
                total_ip = total_outs / 3.0
                total_k  = sum(s.get('strikeouts_pitched', 0) or 0 for s in starts)
                total_bb = sum(s.get('walks_allowed', 0) or 0 for s in starts)
                total_h  = sum(s.get('hits_allowed', 0) or 0 for s in starts)
                total_er = sum(s.get('earned_runs', 0) or 0 for s in starts)
                total_hr = sum(s.get('home_runs_allowed', 0) or 0 for s in starts)

                features['opp_pitcher_era']  = MLBStatsAPI.compute_era(total_er, total_ip)
                features['opp_pitcher_whip'] = MLBStatsAPI.compute_whip(total_h, total_bb, total_ip)
                features['opp_pitcher_k9']   = MLBStatsAPI.compute_k9(total_k, total_ip)
                features['opp_pitcher_bb9']  = MLBStatsAPI.compute_bb9(total_bb, total_ip)
                features['opp_pitcher_hr9']  = MLBStatsAPI.compute_hr9(total_hr, total_ip)

                # Last 3 starts K average
                l3 = starts[:3]
                l3_ks = [s.get('strikeouts_pitched', 0) or 0 for s in l3]
                features['opp_pitcher_l3_k_avg'] = sum(l3_ks) / len(l3_ks) if l3_ks else 5.5

                # Days rest
                features['opp_pitcher_days_rest'] = self._compute_days_rest(starts, target_date)

                # Difficulty composite: 0 = very easy, 1 = elite ace
                k9_norm  = min(features['opp_pitcher_k9'] / 12.0, 1.0)
                era_norm = max(0, 1.0 - features['opp_pitcher_era'] / 8.0)
                features['opp_pitcher_difficulty'] = round((k9_norm + era_norm) / 2.0, 3)

            # NHL PORT: Lineup Friction (What does THIS PITCHER do against THIS TEAM'S type of lineup?)
            if batter_team:
                friction = self.extract_lineup_friction(batter_team, target_date)
                features.update(friction)
            else:
                features['opp_pitcher_lineup_k_rate'] = 0.23
                features['opp_pitcher_lineup_tb_rate'] = 1.2

            return features

        finally:
            conn.close()

    def extract_lineup_friction(self, team: str, target_date: str) -> Dict:
        """
        Calculate how much 'friction' a lineup provides (K rate, TB rate).
        High K rate lineup = easier for pitcher to get K props.
        """
        conn = get_db_connection(self.db_path)
        try:
            # Get team's last 30 days plate discipline
            games = self._get_team_batting(conn, team, target_date, lookback_days=30)
            if not games:
                return {'opp_pitcher_lineup_k_rate': 0.23, 'opp_pitcher_lineup_tb_rate': 1.2}

            total_pa = sum((g.get('at_bats', 0) or 0) + (g.get('walks_drawn', 0) or 0) for g in games)
            total_k  = sum(g.get('strikeouts_batter', 0) or 0 for g in games)
            total_tb = sum(g.get('total_bases', 0) or 0 for g in games)
            total_g  = len(set(g.get('game_id') for g in games)) or 1

            return {
                'opp_pitcher_lineup_k_rate': round(total_k / total_pa, 4) if total_pa > 0 else 0.23,
                'opp_pitcher_lineup_tb_rate': round(total_tb / total_g, 4) if total_g > 0 else 1.2
            }
        finally:
            conn.close()

    def _get_pitcher_starts(self, conn: sqlite3.Connection, pitcher_name: str,
                             target_date: str) -> List[Dict]:
        """Get pitcher's historical starts before target_date."""
        cursor = conn.execute('''
            SELECT
                game_date, outs_recorded, strikeouts_pitched,
                walks_allowed, hits_allowed, earned_runs, home_runs_allowed, pitches
            FROM player_game_logs
            WHERE player_type = 'pitcher'
              AND game_date < ?
              AND outs_recorded > 0
              AND (player_name = ? OR player_name LIKE ?)
            ORDER BY game_date DESC
            LIMIT 20
        ''', (target_date, pitcher_name, f'%{pitcher_name.split()[-1]}%'))

        return [dict(row) for row in cursor.fetchall()]

    def _get_pitcher_api_features(self, pitcher_name: str, pitcher_id: Optional[int],
                                   target_date: str) -> Dict:
        """Get pitcher stats from MLB API when local data unavailable."""
        if not pitcher_id:
            result = self._api.search_player(pitcher_name)
            if result:
                pitcher_id = result.get('id')

        if not pitcher_id:
            return {}

        year = target_date[:4]
        stats = self._api.get_player_season_stats(pitcher_id, year, 'pitching')
        if not stats:
            return {}

        ip_str = stats.get('inningsPitched', '0.0')
        ip = MLBStatsAPI._parse_innings_pitched(ip_str)
        if ip <= 0:
            return {}

        so = stats.get('strikeOuts', 0)
        bb = stats.get('baseOnBalls', 0)
        h  = stats.get('hits', 0)
        er = stats.get('earnedRuns', 0)
        hr = stats.get('homeRuns', 0)

        era  = MLBStatsAPI.compute_era(er, ip)
        k9   = MLBStatsAPI.compute_k9(so, ip)
        k9_norm  = min(k9 / 12.0, 1.0)
        era_norm = max(0, 1.0 - era / 8.0)

        return {
            'opp_pitcher_era':        era,
            'opp_pitcher_whip':       MLBStatsAPI.compute_whip(h, bb, ip),
            'opp_pitcher_k9':         k9,
            'opp_pitcher_bb9':        MLBStatsAPI.compute_bb9(bb, ip),
            'opp_pitcher_hr9':        MLBStatsAPI.compute_hr9(hr, ip),
            'opp_pitcher_difficulty': round((k9_norm + era_norm) / 2.0, 3),
        }

    def _compute_days_rest(self, starts: List[Dict], target_date: str) -> int:
        """Compute days since most recent start."""
        if not starts:
            return 5
        try:
            from datetime import datetime
            last_dt = datetime.strptime(starts[0]['game_date'], '%Y-%m-%d')
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')
            return (target_dt - last_dt).days
        except Exception:
            return 5

    # =========================================================================
    # B) Opposing team features (for PITCHER props)
    # =========================================================================

    def extract_team_offense(self, opponent_team: str, target_date: str,
                              pitcher_hand: str = 'R') -> Dict:
        """
        Extract opposing team's offensive quality for pitcher prop predictions.

        Args:
            opponent_team: Team abbreviation (the team batting against our pitcher)
            target_date: Prediction date YYYY-MM-DD
            pitcher_hand: 'L' or 'R' (pitcher's throwing hand, for split filtering)

        Returns:
            Dict with 'opp_team_*' features
        """
        conn = get_db_connection(self.db_path)
        try:
            # Get team's recent batting performance (last 14 days before target)
            games = self._get_team_batting(conn, opponent_team, target_date)

            if not games:
                return dict(DEFAULT_OPP_TEAM)

            features = {}

            # Plate discipline aggregates
            total_ab = sum(g.get('at_bats', 0) or 0 for g in games)
            total_h  = sum(g.get('hits', 0) or 0 for g in games)
            total_bb = sum(g.get('walks_drawn', 0) or 0 for g in games)
            total_k  = sum(g.get('strikeouts_batter', 0) or 0 for g in games)
            total_tb = sum(g.get('total_bases', 0) or 0 for g in games)
            pa = total_ab + total_bb

            features['opp_team_k_pct']  = total_k / pa if pa > 0 else 0.230
            features['opp_team_bb_pct'] = total_bb / pa if pa > 0 else 0.085
            features['opp_team_obp']    = (total_h + total_bb) / pa if pa > 0 else 0.318

            slg = total_tb / total_ab if total_ab > 0 else 0.400
            features['opp_team_ops'] = features['opp_team_obp'] + slg

            # Recent scoring (runs/game from game_context table)
            features['opp_team_recent_scoring'] = self._get_team_recent_scoring(
                conn, opponent_team, target_date
            )

            return {k: round(v, 4) for k, v in features.items()}

        finally:
            conn.close()

    def _get_team_batting(self, conn: sqlite3.Connection, team: str,
                           target_date: str, lookback_days: int = 30) -> List[Dict]:
        """Get team's recent individual batting game logs."""
        from datetime import datetime, timedelta
        try:
            cutoff = (datetime.strptime(target_date, '%Y-%m-%d') -
                      timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        except ValueError:
            cutoff = '2020-01-01'

        cursor = conn.execute('''
            SELECT at_bats, hits, walks_drawn, strikeouts_batter, total_bases, game_id
            FROM player_game_logs
            WHERE player_type = 'batter'
              AND team = ?
              AND game_date >= ?
              AND game_date < ?
              AND at_bats > 0
        ''', (team, cutoff, target_date))

        return [dict(row) for row in cursor.fetchall()]

    def _get_team_recent_scoring(self, conn: sqlite3.Connection, team: str,
                                   target_date: str, lookback_days: int = 14) -> float:
        """
        Get team's average runs scored per game in recent history.

        Uses game_context if available; falls back to player_game_logs.
        """
        from datetime import datetime, timedelta
        try:
            cutoff = (datetime.strptime(target_date, '%Y-%m-%d') -
                      timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        except ValueError:
            return 4.5

        cursor = conn.execute('''
            SELECT SUM(runs) as total_runs, COUNT(DISTINCT game_id) as games
            FROM player_game_logs
            WHERE player_type = 'batter'
              AND team = ?
              AND game_date >= ?
              AND game_date < ?
        ''', (team, cutoff, target_date))

        row = cursor.fetchone()
        if row and row['games'] and row['games'] > 0 and row['total_runs']:
            return round(row['total_runs'] / row['games'], 2)

        return 4.5  # League average
