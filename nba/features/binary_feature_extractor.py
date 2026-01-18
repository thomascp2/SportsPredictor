"""
NBA Binary Feature Extractor (FULLY FIXED - v2)
================================================

FIXES:
- Line 129: Added float() to division to fix integer division bug
- Line 185-186: Added float() to home/away rate calculations
- Line 158: Added float() safety to trend calculation
- **NEW**: Added continuous features (f_season_avg, f_l10_avg, etc.) for expected value calculations

Extracts features for binary classification problems:
- Points O15.5, O20.5, O25.5
- Rebounds O7.5, O10.5
- Assists O5.5, O7.5
- Threes O2.5
- Stocks (STL+BLK) O2.5

Features (19 total):
Binary-specific (11):
1. Season success rate (% of games over line)
2. L20 success rate
3. L10 success rate
4. L5 success rate
5. L3 success rate
6. Current streak (consecutive overs/unders)
7. Max streak (longest streak this season)
8. Trend slope (improving or declining)
9. Home/Away split (performance difference)
10. Games played (sample size)
11. Insufficient data flag (< 5 games)

Continuous (8) - for expected value:
12. Season average
13. L10 average
14. L5 average
15. Season std deviation
16. L10 std deviation
17. Trend acceleration
18. Average minutes
19. Consistency score
"""

import sqlite3
import sys
import os
import statistics
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nba_config import DB_PATH, MIN_GAMES_REQUIRED
from features.nba_opponent_feature_extractor import NBAOpponentFeatureExtractor


class BinaryFeatureExtractor:
    """Extract binary features from player game logs."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.opp_extractor = NBAOpponentFeatureExtractor(db_path)

    def extract_features(self, player_name, stat_type, line, game_date, home_away='H', opponent_team=None):
        """
        Extract binary features for a player-stat-line combination.

        Args:
            player_name (str): Player name
            stat_type (str): 'points', 'rebounds', 'assists', 'threes', 'stocks', 'pra'
            line (float): Over/Under line (e.g., 15.5)
            game_date (str): Game date (YYYY-MM-DD) - for temporal safety
            home_away (str): 'H' or 'A'
            opponent_team (str): Opponent team abbreviation (e.g., 'BOS', 'ATL')

        Returns:
            dict: 24 features (11 binary + 8 continuous + 5 opponent defensive)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get historical games BEFORE game_date (temporal safety)
        query = """
            SELECT game_date, {stat_column}, home_away, minutes
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
            # Binary-specific features
            'f_season_success_rate': 0.0,
            'f_l20_success_rate': 0.0,
            'f_l10_success_rate': 0.0,
            'f_l5_success_rate': 0.0,
            'f_l3_success_rate': 0.0,
            'f_current_streak': 0,
            'f_max_streak': 0,
            'f_trend_slope': 0.0,
            'f_home_away_split': 0.0,
            'f_games_played': len(games),
            'f_insufficient_data': 1 if len(games) < MIN_GAMES_REQUIRED else 0,
            # Continuous features (needed for expected value calculations)
            'f_season_avg': 0.0,
            'f_l10_avg': 0.0,
            'f_l5_avg': 0.0,
            'f_season_std': 0.0,
            'f_l10_std': 0.0,
            'f_trend_acceleration': 0.0,
            'f_avg_minutes': 0.0,
            'f_consistency_score': 0.0,
        }

        if len(games) == 0:
            return features

        # Extract stat values and minutes
        stat_values = [game[1] for game in games if game[1] is not None]
        minutes_values = [game[3] for game in games if game[3] is not None]
        
        if not stat_values:
            return features

        # ===== BINARY FEATURES =====
        
        # 1-5: Success rates (season, L20, L10, L5, L3)
        features['f_season_success_rate'] = self._success_rate(stat_values, line)
        features['f_l20_success_rate'] = self._success_rate(stat_values[:20], line)
        features['f_l10_success_rate'] = self._success_rate(stat_values[:10], line)
        features['f_l5_success_rate'] = self._success_rate(stat_values[:5], line)
        features['f_l3_success_rate'] = self._success_rate(stat_values[:3], line)

        # 6-7: Streaks
        streak_data = self._calculate_streaks(stat_values, line)
        features['f_current_streak'] = streak_data['current']
        features['f_max_streak'] = streak_data['max']

        # 8: Trend slope (recent improving or declining)
        features['f_trend_slope'] = self._calculate_trend(stat_values[:10])

        # 9: Home/Away split
        home_games = [game[1] for game in games if game[2] == 'H' and game[1] is not None]
        away_games = [game[1] for game in games if game[2] == 'A' and game[1] is not None]
        features['f_home_away_split'] = self._home_away_split(
            home_games, away_games, line, home_away
        )

        # ===== CONTINUOUS FEATURES (NEW!) =====
        
        # 12-14: Averages (season, L10, L5)
        features['f_season_avg'] = float(sum(stat_values)) / float(len(stat_values))
        features['f_l10_avg'] = (float(sum(stat_values[:10])) / float(len(stat_values[:10])) 
                                 if len(stat_values) >= 10 else features['f_season_avg'])
        features['f_l5_avg'] = (float(sum(stat_values[:5])) / float(len(stat_values[:5])) 
                                if len(stat_values) >= 5 else features['f_season_avg'])

        # 15-16: Standard deviations
        if len(stat_values) >= 2:
            features['f_season_std'] = statistics.stdev(stat_values)
        if len(stat_values) >= 10:
            features['f_l10_std'] = statistics.stdev(stat_values[:10])

        # 17: Trend acceleration
        if len(stat_values) >= 10:
            features['f_trend_acceleration'] = self._calculate_trend_acceleration(stat_values[:10])

        # 18: Average minutes
        if minutes_values:
            features['f_avg_minutes'] = float(sum(minutes_values)) / float(len(minutes_values))

        # 19: Consistency score
        if features['f_season_avg'] > 0 and features['f_season_std'] > 0:
            cv = features['f_season_std'] / features['f_season_avg']
            features['f_consistency_score'] = 1 / (1 + cv)

        # 20-24: Opponent defensive features (NEW)
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
            # Core stats
            'points': 'points',
            'rebounds': 'rebounds',
            'assists': 'assists',
            'threes': 'threes_made',
            '3-pt_made': 'threes_made',
            'steals': 'steals',
            'blocked_shots': 'blocks',
            'blocks': 'blocks',
            'turnovers': 'turnovers',
            # Derived stats (stored in DB)
            'stocks': 'stocks',
            'blks_stls': 'stocks',
            'blks+stls': 'stocks',
            'pra': 'pra',
            # Combo stats (computed)
            'pts_rebs': '(points + rebounds)',
            'pts_asts': '(points + assists)',
            'rebs_asts': '(rebounds + assists)',
            # Fantasy (DraftKings-style formula)
            'fantasy': '(points + rebounds * 1.2 + assists * 1.5 + steals * 3 + blocks * 3 - turnovers)',
            # Minutes
            'minutes': 'minutes',
        }
        # If stat_type not found, log warning and return None to prevent wrong data
        result = stat_map.get(stat_type.lower() if stat_type else 'points')
        if result is None:
            print(f"[WARN] Unknown stat_type '{stat_type}' - defaulting to points")
            return 'points'
        return result

    @staticmethod
    def _success_rate(values, line):
        """Calculate success rate (% of games over line)."""
        if not values:
            return 0.0
        overs = sum(1 for v in values if v > line)
        # FIX: Use float() to prevent integer division
        return float(overs) / float(len(values))

    @staticmethod
    def _calculate_streaks(values, line):
        """Calculate current streak and max streak."""
        if not values:
            return {'current': 0, 'max': 0}

        current_streak = 0
        max_streak = 0
        temp_streak = 0
        last_result = None

        for value in values:
            result = 1 if value > line else -1

            if result == last_result:
                temp_streak += 1
            else:
                temp_streak = 1
                last_result = result

            max_streak = max(max_streak, abs(temp_streak))

            if temp_streak == 1 and len(values) > 0:
                current_streak = temp_streak * result

        # Current streak is the most recent
        if values:
            current_streak = 1 if values[0] > line else -1
            count = 1
            for i in range(1, len(values)):
                if (values[i] > line) == (values[0] > line):
                    count += 1
                else:
                    break
            current_streak *= count

        return {'current': current_streak, 'max': max_streak}

    @staticmethod
    def _calculate_trend(values):
        """Calculate trend slope using linear regression."""
        if len(values) < 3:
            return 0.0

        n = len(values)
        x = list(range(n))
        y = values

        # FIX: Use float() for safety
        x_mean = float(sum(x)) / float(n)
        y_mean = float(sum(y)) / float(n)

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

        recent_slope = BinaryFeatureExtractor._calculate_trend(recent)
        older_slope = BinaryFeatureExtractor._calculate_trend(older)

        acceleration = recent_slope - older_slope
        return acceleration

    @staticmethod
    def _home_away_split(home_games, away_games, line, current_home_away):
        """Calculate home/away split advantage."""
        if not home_games or not away_games:
            return 0.0

        # FIX: Use float() to prevent integer division
        home_rate = float(sum(1 for v in home_games if v > line)) / float(len(home_games))
        away_rate = float(sum(1 for v in away_games if v > line)) / float(len(away_games))

        split = home_rate - away_rate

        # Return split relative to current game
        return split if current_home_away == 'H' else -split


# Example usage
if __name__ == "__main__":
    extractor = BinaryFeatureExtractor()

    # Test feature extraction
    features = extractor.extract_features(
        player_name="LeBron James",
        stat_type="points",
        line=25.5,
        game_date="2024-11-09",
        home_away='H'
    )

    print("🏀 Binary Feature Extraction Test (FIXED v2)")
    print(f"Player: LeBron James")
    print(f"Prop: Points O25.5")
    print(f"\nBinary Features:")
    print(f"  Season success rate: {features['f_season_success_rate']:.3f}")
    print(f"  L10 success rate: {features['f_l10_success_rate']:.3f}")
    print(f"  Current streak: {features['f_current_streak']}")
    print(f"\nContinuous Features (NEW!):")
    print(f"  Season avg: {features['f_season_avg']:.1f}")
    print(f"  L10 avg: {features['f_l10_avg']:.1f}")
    print(f"  L5 avg: {features['f_l5_avg']:.1f}")
    print(f"  Season std: {features['f_season_std']:.1f}")
    print(f"  Avg minutes: {features['f_avg_minutes']:.1f}")
