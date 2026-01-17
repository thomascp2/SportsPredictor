"""
NBA Opponent Feature Extractor
================================

Extracts defensive features for the OPPONENT team.

Key insight: It's not just about how good the PLAYER is,
it's also about how good the DEFENSE is!

Example:
  LeBron vs Atlanta (weak defense) → easier matchup
  LeBron vs Boston (strong defense) → harder matchup

CRITICAL: All features must use data from BEFORE game_date (temporal safety).

Based on NHL Opponent Feature Extractor
Date: 2025-11-27
"""

import sqlite3
import sys
import os
from typing import Dict
import statistics

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nba_config import DB_PATH


class NBAOpponentFeatureExtractor:
    """
    Extracts defensive features for opponent NBA teams.

    These features help the model understand defensive matchup difficulty.
    Answers the question: "How hard is it to score/rebound/assist against THIS team?"
    """

    def __init__(self, db_path=DB_PATH):
        """
        Initialize opponent feature extractor.

        Args:
            db_path: Path to nba_predictions.db
        """
        self.db_path = db_path

    def extract_opponent_features(self,
                                  opponent_team: str,
                                  game_date: str,
                                  stat_type: str = 'points') -> Dict[str, float]:
        """
        Extract defensive features for opponent team.

        This analyzes how the opponent performs DEFENSIVELY by looking at
        stats from opposing players when they play AGAINST this team.

        Args:
            opponent_team: Opponent team abbreviation (e.g., 'BOS', 'ATL')
            game_date: Game date (YYYY-MM-DD) - prediction date
            stat_type: 'points', 'rebounds', 'assists', 'threes', 'stocks'

        Returns:
            Dict of opponent defensive features (all floats)

        Note:
            Uses ONLY data from BEFORE game_date (temporal safety)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Map stat type to column name
        stat_column = self._get_stat_column(stat_type)

        # Get stats of players who played AGAINST this opponent team
        # (This tells us how good the opponent's DEFENSE is)
        query = f"""
            SELECT
                pgl.game_date,
                {stat_column} as stat_value,
                pgl.home_away
            FROM player_game_logs pgl
            WHERE
                -- Player's team opponent was this team
                pgl.opponent = ?
                -- Only use games before prediction date (temporal safety)
                AND pgl.game_date < ?
            ORDER BY pgl.game_date DESC
            LIMIT 200
        """

        cursor.execute(query, (opponent_team, game_date))
        opponent_games = cursor.fetchall()

        conn.close()

        if len(opponent_games) < 20:
            # Not enough data - return league averages
            return self._get_default_opponent_features(stat_type)

        # Extract opponent defensive stats
        stat_values = [float(row[1]) if row[1] is not None else 0.0 for row in opponent_games]

        features = {}

        # Average stat allowed (L10 and L5)
        features[f'opp_{stat_type}_allowed_l10'] = statistics.mean(stat_values[:10]) if len(stat_values) >= 10 else statistics.mean(stat_values)
        features[f'opp_{stat_type}_allowed_l5'] = statistics.mean(stat_values[:5]) if len(stat_values) >= 5 else statistics.mean(stat_values)

        # How consistent is their defense? (lower std = more consistent)
        features[f'opp_{stat_type}_std'] = statistics.stdev(stat_values[:10]) if len(stat_values) >= 10 else 0.0

        # Is their defense getting better or worse?
        features[f'opp_{stat_type}_defensive_trend'] = self._calc_defensive_trend(stat_values[:10])

        # Overall defensive rating (how many stats total they allow)
        features[f'opp_{stat_type}_defensive_rating'] = statistics.mean(stat_values[:20])

        return features

    def _get_stat_column(self, stat_type: str) -> str:
        """Map stat type to database column name."""
        mapping = {
            'points': 'points',
            'rebounds': 'rebounds',
            'assists': 'assists',
            'threes': 'threes_made',
            'stocks': '(steals + blocks)',  # Calculated field
            'pra': '(points + rebounds + assists)'  # Calculated field
        }
        return mapping.get(stat_type, 'points')

    def _calc_defensive_trend(self, values: list) -> float:
        """
        Calculate defensive trend using simple linear regression.

        Positive trend = defense getting worse (allowing MORE)
        Negative trend = defense getting better (allowing LESS)

        Args:
            values: List of stats allowed (most recent first)

        Returns:
            Trend coefficient normalized to -1 to +1
        """
        if len(values) < 3:
            return 0.0

        # Reverse so oldest is first for regression
        values_reversed = values[::-1]
        n = len(values_reversed)

        # Calculate slope using simple linear regression
        x_mean = (n - 1) / 2.0  # Mean of indices
        y_mean = sum(values_reversed) / n

        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(values_reversed))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0

        slope = numerator / denominator

        # Normalize to -1 to +1 range
        # Typical slope range is -2 to +2 per game for NBA
        max_slope = 2.0
        normalized_trend = max(-1.0, min(1.0, slope / max_slope))

        return float(normalized_trend)

    def _get_default_opponent_features(self, stat_type: str) -> Dict[str, float]:
        """
        Return default opponent features when insufficient data.

        Uses league averages.

        Args:
            stat_type: 'points', 'rebounds', 'assists', 'threes', 'stocks'

        Returns:
            Dict of default features
        """
        # NBA league averages (approximate)
        defaults = {
            'points': {
                f'opp_points_allowed_l10': 14.5,
                f'opp_points_allowed_l5': 14.5,
                f'opp_points_std': 8.0,
                f'opp_points_defensive_trend': 0.0,
                f'opp_points_defensive_rating': 14.5
            },
            'rebounds': {
                f'opp_rebounds_allowed_l10': 6.5,
                f'opp_rebounds_allowed_l5': 6.5,
                f'opp_rebounds_std': 3.5,
                f'opp_rebounds_defensive_trend': 0.0,
                f'opp_rebounds_defensive_rating': 6.5
            },
            'assists': {
                f'opp_assists_allowed_l10': 4.5,
                f'opp_assists_allowed_l5': 4.5,
                f'opp_assists_std': 3.0,
                f'opp_assists_defensive_trend': 0.0,
                f'opp_assists_defensive_rating': 4.5
            },
            'threes': {
                f'opp_threes_allowed_l10': 2.0,
                f'opp_threes_allowed_l5': 2.0,
                f'opp_threes_std': 1.5,
                f'opp_threes_defensive_trend': 0.0,
                f'opp_threes_defensive_rating': 2.0
            },
            'stocks': {
                f'opp_stocks_allowed_l10': 1.5,
                f'opp_stocks_allowed_l5': 1.5,
                f'opp_stocks_std': 1.2,
                f'opp_stocks_defensive_trend': 0.0,
                f'opp_stocks_defensive_rating': 1.5
            }
        }

        return defaults.get(stat_type, defaults['points'])


# Test function
if __name__ == '__main__':
    extractor = NBAOpponentFeatureExtractor()

    # Test extraction
    features = extractor.extract_opponent_features('BOS', '2025-11-29', 'points')

    print("Opponent Features for BOS (points):")
    for key, value in features.items():
        print(f"  {key}: {value:.3f}")
