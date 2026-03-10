"""
MLB Batter Feature Extractor
=============================

Extracts ~20 features for batter prop predictions from player_game_logs.
Used for: hits, total_bases, home_runs, rbis, runs, stolen_bases,
          walks, batter_strikeouts, hrr

Features capture:
  - Season averages (BA, OBP, SLG, OPS, ISO, K%, BB%)
  - Recent form (last 5 and last 10 games per prop type)
  - Hit rate (% of games over each line threshold)
  - Platoon splits (vs LHP vs RHP)
  - Performance trend over last 10 games
  - Streak (consecutive over/under for this prop+line)
  - Context (home/away, batting order, games played)

Temporal safety: All queries use game_date < target_date.
"""

import math
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from mlb_config import get_db_connection, MIN_BATTER_GAMES_FOR_PREDICTION


# League-average defaults (used when insufficient batter data)
LEAGUE_AVG_BATTER = {
    'f_season_avg':       0.250,
    'f_season_obp':       0.318,
    'f_season_slg':       0.412,
    'f_season_iso':       0.162,    # SLG - AVG
    'f_season_k_pct':     0.230,
    'f_season_bb_pct':    0.085,
    'f_vs_rhp_avg':       0.250,
    'f_vs_lhp_avg':       0.250,
    'f_vs_rhp_k_pct':     0.230,
    'f_vs_lhp_k_pct':     0.230,
    'f_platoon_advantage': 0.0,
    'f_batting_order':    5,
    'f_is_home':          0.5,
    'f_trend_slope':      0.0,
    'f_streak':           0,
    'f_games_played':     0,
    'f_insufficient_data': 1,
}


class BatterFeatureExtractor:
    """
    Extracts batter-specific features from historical game logs.

    Features are prop-specific — the recent form and hit rate features
    vary based on which prop type is being predicted.
    """

    # Map prop type to the DB column containing the actual stat value
    PROP_TO_COLUMN = {
        'hits':              'hits',
        'total_bases':       'total_bases',
        'home_runs':         'home_runs',
        'rbis':              'rbis',
        'runs':              'runs',
        'stolen_bases':      'stolen_bases',
        'walks':             'walks_drawn',
        'batter_strikeouts': 'strikeouts_batter',
        'hrr':               'hrr',
    }

    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def extract(self, player_name: str, team: str, prop_type: str, line: float,
                target_date: str, opposing_pitcher_hand: str = 'R',
                home_away: str = 'home', batting_order: int = 5) -> Dict:
        """
        Extract all batter features for a prediction on target_date.

        Args:
            player_name: Full player name (e.g., 'Freddie Freeman')
            team: Team abbreviation
            prop_type: Prop type (e.g., 'hits', 'total_bases')
            line: PrizePicks line (e.g., 0.5, 1.5)
            target_date: Prediction date (YYYY-MM-DD)
            opposing_pitcher_hand: 'L' or 'R' (for platoon splits)
            home_away: 'home' or 'away'
            batting_order: 1-9 (from lineup, or historical average)

        Returns:
            Dict of feature_name → float
        """
        conn = get_db_connection(self.db_path)
        try:
            games = self._get_batter_games(conn, player_name, team, target_date)

            features = {}
            features['f_games_played'] = len(games)
            features['f_is_home'] = 1 if home_away == 'home' else 0
            features['f_batting_order'] = batting_order

            if len(games) < MIN_BATTER_GAMES_FOR_PREDICTION:
                merged = {**LEAGUE_AVG_BATTER.copy()}
                merged['f_games_played'] = len(games)
                merged['f_is_home'] = features['f_is_home']
                merged['f_batting_order'] = batting_order
                merged['f_insufficient_data'] = 1
                return merged

            features['f_insufficient_data'] = 0

            # Season-level stats
            features.update(self._compute_season_features(games))

            # Platoon splits
            features.update(self._compute_platoon_splits(games, opposing_pitcher_hand))

            # Prop-specific recent form
            stat_col = self.PROP_TO_COLUMN.get(prop_type, 'hits')
            features.update(self._compute_recent_form(games, stat_col, line, prop_type))

            # Trend
            features['f_trend_slope'] = self._compute_trend(games, stat_col)

            # Streak (consecutive over/under this line)
            features['f_streak'] = self._compute_streak(games, stat_col, line)

            return features

        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Data fetching
    # -------------------------------------------------------------------------

    def _get_batter_games(self, conn: sqlite3.Connection, player_name: str,
                           team: str, target_date: str) -> List[Dict]:
        """Fetch batter's historical game logs with temporal safety."""
        cursor = conn.execute('''
            SELECT
                game_date, hits, total_bases, home_runs, rbis, runs,
                stolen_bases, walks_drawn, strikeouts_batter, hrr,
                at_bats, doubles, triples,
                opposing_pitcher_hand, home_away
            FROM player_game_logs
            WHERE player_type = 'batter'
              AND game_date < ?
              AND at_bats > 0
              AND (player_name = ? OR player_name LIKE ?)
            ORDER BY game_date DESC
            LIMIT 60
        ''', (target_date, player_name, f'%{player_name.split()[-1]}%'))

        return [dict(row) for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Feature computation
    # -------------------------------------------------------------------------

    def _compute_season_features(self, games: List[Dict]) -> Dict:
        """Compute season batting averages from game log data."""
        total_ab  = sum(g.get('at_bats', 0) or 0 for g in games)
        total_h   = sum(g.get('hits', 0) or 0 for g in games)
        total_tb  = sum(g.get('total_bases', 0) or 0 for g in games)
        total_bb  = sum(g.get('walks_drawn', 0) or 0 for g in games)
        total_k   = sum(g.get('strikeouts_batter', 0) or 0 for g in games)
        total_2b  = sum(g.get('doubles', 0) or 0 for g in games)
        total_3b  = sum(g.get('triples', 0) or 0 for g in games)
        total_hr  = sum(g.get('home_runs', 0) or 0 for g in games)
        total_games = len(games)

        pa = total_ab + total_bb  # Plate appearances (simplified)

        avg = total_h / total_ab if total_ab > 0 else 0.250
        obp = (total_h + total_bb) / pa if pa > 0 else 0.320
        slg = total_tb / total_ab if total_ab > 0 else 0.400
        iso = max(0, slg - avg)
        k_pct = total_k / pa if pa > 0 else 0.230
        bb_pct = total_bb / pa if pa > 0 else 0.085

        return {
            'f_season_avg':    round(avg, 3),
            'f_season_obp':    round(obp, 3),
            'f_season_slg':    round(slg, 3),
            'f_season_iso':    round(iso, 3),
            'f_season_k_pct':  round(k_pct, 3),
            'f_season_bb_pct': round(bb_pct, 3),
        }

    def _compute_platoon_splits(self, games: List[Dict],
                                 opposing_pitcher_hand: str) -> Dict:
        """
        Compute performance splits vs LHP and RHP.

        Also computes platoon_advantage: positive if facing a pitcher
        where the batter historically performs better.
        """
        vs_rhp = [g for g in games if g.get('opposing_pitcher_hand') == 'R']
        vs_lhp = [g for g in games if g.get('opposing_pitcher_hand') == 'L']

        def batting_avg(game_list: List[Dict]) -> float:
            ab = sum(g.get('at_bats', 0) or 0 for g in game_list)
            h  = sum(g.get('hits', 0) or 0 for g in game_list)
            return h / ab if ab > 0 else 0.250

        def k_pct(game_list: List[Dict]) -> float:
            pa = sum((g.get('at_bats', 0) or 0) + (g.get('walks_drawn', 0) or 0)
                     for g in game_list)
            k  = sum(g.get('strikeouts_batter', 0) or 0 for g in game_list)
            return k / pa if pa > 0 else 0.230

        rhp_avg = batting_avg(vs_rhp) if vs_rhp else 0.250
        lhp_avg = batting_avg(vs_lhp) if vs_lhp else 0.250
        rhp_k   = k_pct(vs_rhp) if vs_rhp else 0.230
        lhp_k   = k_pct(vs_lhp) if vs_lhp else 0.230

        # Platoon advantage: favorable = batter has higher avg vs this pitcher hand
        if opposing_pitcher_hand == 'R' and vs_rhp and vs_lhp:
            platoon_adv = rhp_avg - lhp_avg
        elif opposing_pitcher_hand == 'L' and vs_rhp and vs_lhp:
            platoon_adv = lhp_avg - rhp_avg
        else:
            platoon_adv = 0.0

        return {
            'f_vs_rhp_avg':       round(rhp_avg, 3),
            'f_vs_lhp_avg':       round(lhp_avg, 3),
            'f_vs_rhp_k_pct':     round(rhp_k, 3),
            'f_vs_lhp_k_pct':     round(lhp_k, 3),
            'f_platoon_advantage': round(max(-0.1, min(0.1, platoon_adv)), 4),
        }

    def _compute_recent_form(self, games: List[Dict], stat_col: str,
                              line: float, prop_type: str) -> Dict:
        """
        Compute last-5 and last-10 game performance for the specific prop stat.

        Also computes hit rate (% of games the batter went over the line).
        """
        l5  = games[:5]
        l10 = games[:10]

        def avg_stat(game_list: List[Dict]) -> float:
            vals = [g.get(stat_col, 0) or 0 for g in game_list]
            return sum(vals) / len(vals) if vals else 0.0

        def hit_rate(game_list: List[Dict], threshold: float) -> float:
            """% of games batter exceeded the line."""
            hits = sum(1 for g in game_list if (g.get(stat_col, 0) or 0) > threshold)
            return hits / len(game_list) if game_list else 0.5

        l5_avg   = avg_stat(l5)
        l10_avg  = avg_stat(l10)
        l5_rate  = hit_rate(l5, line)
        l10_rate = hit_rate(l10, line)

        return {
            f'f_l5_{prop_type}_avg':     round(l5_avg, 3),
            f'f_l10_{prop_type}_avg':    round(l10_avg, 3),
            f'f_l5_{prop_type}_rate':    round(l5_rate, 3),
            f'f_l10_{prop_type}_rate':   round(l10_rate, 3),
        }

    def _compute_trend(self, games: List[Dict], stat_col: str) -> float:
        """
        Compute trend slope for a stat over last 10 games.

        Positive = improving, Negative = declining.
        Normalized via tanh to approximately -1 to +1.
        """
        l10 = games[:10]
        if len(l10) < 3:
            return 0.0

        vals = [g.get(stat_col, 0) or 0 for g in l10]
        vals.reverse()  # Oldest first

        n = len(vals)
        x_mean = (n - 1) / 2.0
        y_mean = sum(vals) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(vals))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den != 0 else 0.0

        # Normalize relative to average stat value
        avg_stat = y_mean or 1.0
        normalized = slope / max(avg_stat, 0.1)

        return round(math.tanh(normalized), 4)

    def _compute_streak(self, games: List[Dict], stat_col: str, line: float) -> int:
        """
        Compute current streak for going OVER a line.

        Returns:
          Positive int = consecutive games OVER line
          Negative int = consecutive games UNDER line
          0 = no streak data
        """
        streak = 0
        for game in games:
            val = game.get(stat_col, 0) or 0
            if val > line:
                if streak >= 0:
                    streak += 1
                else:
                    break  # Streak broken
            else:
                if streak <= 0:
                    streak -= 1
                else:
                    break

        return streak
