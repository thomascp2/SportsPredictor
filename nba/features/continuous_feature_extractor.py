"""
NBA Continuous Feature Extractor
=================================

Extracts features for continuous/regression problems:
- PRA (Points + Rebounds + Assists)
- Minutes
- Usage rate predictions

Features (10 total):
1. Season average
2. L10 average
3. L5 average
4. Season standard deviation
5. L10 standard deviation
6. Trend slope (improving or declining)
7. Trend acceleration (accelerating or decelerating)
8. Average minutes (playing time)
9. Home/Away split
10. Consistency score (inverse of CV)
"""

import sqlite3
import sys
import os
from datetime import datetime
import statistics

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nba_config import DB_PATH, MIN_GAMES_REQUIRED
from features.nba_opponent_feature_extractor import NBAOpponentFeatureExtractor


class ContinuousFeatureExtractor:
    """Extract continuous features from player game logs."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.opp_extractor = NBAOpponentFeatureExtractor(db_path)

    def extract_features(self, player_name, stat_type, game_date, home_away='H', opponent_team=None):
        """
        Extract continuous features for a player-stat combination.

        Args:
            player_name (str): Player name
            stat_type (str): 'pra', 'minutes', 'points', 'rebounds', etc.
            game_date (str): Game date (YYYY-MM-DD) - for temporal safety
            home_away (str): 'H' or 'A'
            opponent_team (str): Opponent team abbreviation (e.g., 'BOS', 'ATL')

        Returns:
            dict: 15 continuous features (10 player + 5 opponent defensive)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get historical games BEFORE game_date (temporal safety)
        query = """
            SELECT game_date, {stat_column}, minutes, home_away
            FROM player_game_logs
            WHERE player_name = ?
              AND game_date < ?
            ORDER BY game_date DESC
        """.format(stat_column=self._get_stat_column(stat_type))

        cursor.execute(query, (player_name, game_date))
        games = cursor.fetchall()

        conn.close()

        # Initialize features
        features = {
            'f_season_avg': 0.0,
            'f_l10_avg': 0.0,
            'f_l5_avg': 0.0,
            'f_season_std': 0.0,
            'f_l10_std': 0.0,
            'f_trend_slope': 0.0,
            'f_trend_acceleration': 0.0,
            'f_avg_minutes': 0.0,
            'f_consistency_score': 0.0,
            'f_home_away_split': 0.0,
            'f_games_played': len(games),
        }

        if len(games) == 0:
            return features

        # Extract stat values
        stat_values = [game[1] for game in games if game[1] is not None]
        minutes_values = [game[2] for game in games if game[2] is not None]

        if not stat_values:
            return features

        # 1-3: Averages (season, L10, L5)
        features['f_season_avg'] = statistics.mean(stat_values)
        features['f_l10_avg'] = statistics.mean(stat_values[:10]) if len(stat_values) >= 10 else features['f_season_avg']
        features['f_l5_avg'] = statistics.mean(stat_values[:5]) if len(stat_values) >= 5 else features['f_season_avg']

        # 4-5: Standard deviations
        if len(stat_values) >= 2:
            features['f_season_std'] = statistics.stdev(stat_values)
        if len(stat_values) >= 10:
            features['f_l10_std'] = statistics.stdev(stat_values[:10])

        # 6-7: Trends
        if len(stat_values) >= 5:
            features['f_trend_slope'] = self._calculate_trend_slope(stat_values[:10])
        if len(stat_values) >= 10:
            features['f_trend_acceleration'] = self._calculate_trend_acceleration(stat_values[:10])

        # 8: Average minutes
        if minutes_values:
            features['f_avg_minutes'] = statistics.mean(minutes_values)

        # 9: Home/Away split
        home_games = [game[1] for game in games if game[3] == 'H' and game[1] is not None]
        away_games = [game[1] for game in games if game[3] == 'A' and game[1] is not None]
        if home_games and away_games:
            home_avg = statistics.mean(home_games)
            away_avg = statistics.mean(away_games)
            split = home_avg - away_avg
            features['f_home_away_split'] = split if home_away == 'H' else -split

        # 10: Consistency score (inverse of coefficient of variation)
        if features['f_season_avg'] > 0 and features['f_season_std'] > 0:
            cv = features['f_season_std'] / features['f_season_avg']
            features['f_consistency_score'] = 1 / (1 + cv)  # Normalize to 0-1

        # 11-15: Opponent defensive features (NEW)
        if opponent_team:
            opp_features = self.opp_extractor.extract_opponent_features(
                opponent_team,
                game_date,
                stat_type
            )
            features.update(opp_features)

        return features

    @staticmethod
    def _get_stat_column(stat_type):
        """Map stat type to database column."""
        stat_map = {
            'points': 'points',
            'rebounds': 'rebounds',
            'assists': 'assists',
            'pra': '(points + rebounds + assists)',
            'minutes': 'minutes',
            'threes': 'threes_made',
            'stocks': '(steals + blocks)',
        }
        return stat_map.get(stat_type, 'points')

    @staticmethod
    def _calculate_trend_slope(values):
        """Calculate trend slope using linear regression."""
        if len(values) < 3:
            return 0.0

        n = len(values)
        x = list(range(n))
        y = values

        x_mean = sum(x) / n
        y_mean = sum(y) / n

        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0

        slope = numerator / denominator
        return slope

    @staticmethod
    def _calculate_trend_acceleration(values):
        """Calculate trend acceleration (2nd derivative)."""
        if len(values) < 5:
            return 0.0

        # Split into two halves and compare slopes
        mid = len(values) // 2
        recent = values[:mid]
        older = values[mid:]

        recent_slope = ContinuousFeatureExtractor._calculate_trend_slope(recent)
        older_slope = ContinuousFeatureExtractor._calculate_trend_slope(older)

        acceleration = recent_slope - older_slope
        return acceleration


# Example usage
if __name__ == "__main__":
    extractor = ContinuousFeatureExtractor()

    # Test feature extraction
    features = extractor.extract_features(
        player_name="LeBron James",
        stat_type="pra",
        game_date="2024-11-09",
        home_away='H'
    )

    print("🏀 Continuous Feature Extraction Test")
    print(f"Player: LeBron James")
    print(f"Stat: PRA")
    print(f"\nFeatures:")
    for key, value in features.items():
        print(f"  {key}: {value:.3f}")
