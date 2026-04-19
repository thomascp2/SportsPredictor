"""
NBA Statistical Prediction Engine
==================================

Statistical models for data collection phase (Weeks 1-7).
Uses Poisson/Normal distributions with feature-based adjustments.

Binary Props (Poisson):
- Points, Rebounds, Assists, Threes, Stocks

Continuous Props (Normal):
- PRA, Minutes

Learning Mode: Caps probabilities at 30-70% during data collection.
"""

import sys
import os
import math

# Lazy import scipy to avoid hang on Windows when scipy.stats initializes DLLs
_poisson = None
_norm = None

def _get_scipy():
    global _poisson, _norm
    if _poisson is None:
        from scipy.stats import poisson as _p, norm as _n
        _poisson = _p
        _norm = _n
    return _poisson, _norm

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nba_config import LEARNING_MODE, PROBABILITY_CAP
from features.binary_feature_extractor import BinaryFeatureExtractor
from features.continuous_feature_extractor import ContinuousFeatureExtractor


class NBAStatisticalPredictor:
    """Statistical prediction engine for NBA props."""

    def __init__(self, learning_mode=LEARNING_MODE):
        self.learning_mode = learning_mode
        self.prob_cap = PROBABILITY_CAP
        self.binary_extractor = BinaryFeatureExtractor()
        self.continuous_extractor = ContinuousFeatureExtractor()

    def predict_binary_prop(self, player_name, stat_type, line, game_date, home_away='H', opponent_team=None):
        """
        Predict binary prop (Over/Under).

        Args:
            player_name (str): Player name
            stat_type (str): 'points', 'rebounds', 'assists', 'threes', 'stocks'
            line (float): Over/Under line (e.g., 15.5)
            game_date (str): Game date (YYYY-MM-DD)
            home_away (str): 'H' or 'A'
            opponent_team (str): Opponent team abbreviation (e.g., 'BOS', 'ATL')

        Returns:
            dict: {
                'prediction': 'OVER' or 'UNDER',
                'probability': float (0.20-0.80 in learning mode),
                'features': dict (24 total with opponent features)
            }
        """
        # Extract features (including opponent defensive features)
        features = self.binary_extractor.extract_features(
            player_name, stat_type, line, game_date, home_away, opponent_team
        )

        # If insufficient data, return default
        if features['f_insufficient_data'] == 1 or features['f_games_played'] < 5:
            return {
                'prediction': 'UNDER',
                'probability': 0.50,
                'features': features,
                'expected_value': line,
                'method': 'insufficient_data'
            }

        # Compute absolute expected stat value (weighted recent average)
        l5 = features['f_l5_avg']
        l10 = features['f_l10_avg']
        season = features['f_season_avg']
        mu = 0.40 * l5 + 0.35 * l10 + 0.25 * season

        # Trend adjustment in stat units (matches continuous method)
        mu += features['f_trend_slope'] * 2

        # Opponent defensive adjustments to mu (in stat units, not probability)
        if opponent_team:
            league_avg = {
                'points': 14.5, 'rebounds': 6.5, 'assists': 4.5,
                'threes': 2.0, 'stocks': 1.5, 'steals': 1.0,
                'blocked_shots': 0.5, 'turnovers': 2.5
            }.get(stat_type, 0.0)

            if league_avg > 0:
                opp_rating = features.get(f'opp_{stat_type}_defensive_rating', 0.0)
                if opp_rating > league_avg + 3:
                    mu += 1.5   # Weak defense — expect more
                elif opp_rating > league_avg + 1.5:
                    mu += 0.75
                elif opp_rating < league_avg - 3:
                    mu -= 1.5   # Strong defense — expect less
                elif opp_rating < league_avg - 1.5:
                    mu -= 0.75

            opp_trend = features.get(f'opp_{stat_type}_defensive_trend', 0.0)
            if opp_trend > 0.3:   # Defense getting worse
                mu += 0.5
            elif opp_trend < -0.3:  # Defense improving
                mu -= 0.5

        mu = max(mu, 0.0)

        # Sigma from stored rolling std; fall back to Poisson approximation
        sigma = features['f_l10_std'] if features['f_l10_std'] > 0 else features['f_season_std']
        if sigma <= 0:
            sigma = max(math.sqrt(mu), mu * 0.20, 0.5)

        # Convert to probability via normal CDF
        try:
            _, norm = _get_scipy()
            probability = float(1.0 - norm.cdf(line, loc=mu, scale=sigma))
        except Exception:
            probability = 0.5

        probability = max(0.0, min(1.0, probability))

        # Home/away split is in probability units — apply as fine-tuning
        adjustments = features['f_home_away_split'] * 0.1
        probability = max(0.0, min(1.0, probability + adjustments))

        # B2B / rest fatigue adjustment
        days_rest = features.get('f_days_rest', 3)
        opp_days_rest = features.get('f_opp_days_rest', 3)
        if days_rest == 0:
            probability -= 0.025  # Player on B2B — slight underperformance expected
        elif days_rest >= 4:
            probability += 0.010  # Well-rested — slight positive boost
        if opp_days_rest == 0:
            probability += 0.015  # Opponent on B2B — easier matchup
        probability = max(0.0, min(1.0, probability))

        # Minutes trend suppression (load management / rotation change signal).
        # When a player's L5 minutes are trending well below their season average,
        # all counting-stat OVERs are penalized because fewer minutes = fewer
        # opportunities to hit the line.  We scale the suppression continuously
        # rather than using a hard cut so the signal survives into ML training.
        if features.get('f_minutes_trending_down', 0.0) == 1.0:
            minutes_pct = features.get('f_minutes_pct_of_season', 1.0)
            # At 88% minutes  → ~3% suppression;  at 75% → ~6.25% (hard-capped at 8%)
            suppression = (1.0 - minutes_pct) * 0.25
            suppression = min(suppression, 0.08)
            probability -= suppression
            probability = max(0.0, min(1.0, probability))

        # Apply learning mode cap
        if self.learning_mode:
            probability = self._apply_learning_cap(probability)

        # Determine prediction
        prediction = 'OVER' if probability > 0.5 else 'UNDER'

        return {
            'prediction': prediction,
            'probability': probability,
            'features': features,
            'expected_value': mu,
            'method': 'statistical_binary_ev'
        }

    def predict_continuous_prop(self, player_name, stat_type, line, game_date, home_away='H', opponent_team=None):
        """
        Predict continuous prop (Over/Under based on normal distribution).

        Args:
            player_name (str): Player name
            stat_type (str): 'pra', 'minutes'
            line (float): Over/Under line (e.g., 30.5)
            game_date (str): Game date (YYYY-MM-DD)
            home_away (str): 'H' or 'A'
            opponent_team (str): Opponent team abbreviation (e.g., 'BOS', 'ATL')

        Returns:
            dict: {
                'prediction': 'OVER' or 'UNDER',
                'probability': float (0.20-0.80 in learning mode),
                'features': dict (15 total with opponent features),
                'expected_value': float
            }
        """
        # Extract features (including opponent defensive features)
        features = self.continuous_extractor.extract_features(
            player_name, stat_type, game_date, home_away, opponent_team
        )

        # If insufficient data, return default
        if features.get('f_games_played', 0) < 5:
            return {
                'prediction': 'UNDER',
                'probability': 0.50,
                'features': features,
                'expected_value': line,
                'method': 'insufficient_data'
            }

        # Base prediction from L10 average (more recent = more relevant)
        mu = features['f_l10_avg']
        sigma = features['f_l10_std'] if features['f_l10_std'] > 0 else features['f_season_std']

        # Adjustments based on trends
        trend_adjustment = features['f_trend_slope'] * 2
        mu += trend_adjustment

        # Home/Away adjustment
        mu += features['f_home_away_split']

        # Opponent defensive adjustments (NEW)
        if opponent_team:
            opp_rating = features.get(f'opp_{stat_type}_defensive_rating', 0.0)
            opp_trend = features.get(f'opp_{stat_type}_defensive_trend', 0.0)

            # Adjust expected value based on opponent defense
            league_avg = {
                'pra': 35.0, 'minutes': 28.0, 'points': 14.5,
                'rebounds': 6.5, 'assists': 4.5
            }.get(stat_type, 0.0)

            if league_avg > 0:
                # Weak defense = higher expected value
                if opp_rating > league_avg + 3:
                    mu += 2.0
                elif opp_rating > league_avg + 1.5:
                    mu += 1.0
                # Strong defense = lower expected value
                elif opp_rating < league_avg - 3:
                    mu -= 2.0
                elif opp_rating < league_avg - 1.5:
                    mu -= 1.0

            # Trending defense adjustments
            if opp_trend > 0.3:  # Defense getting worse
                mu += 1.0
            elif opp_trend < -0.3:  # Defense improving
                mu -= 1.0

        # If sigma is 0, use season std or default
        if sigma == 0:
            sigma = features['f_season_std'] if features['f_season_std'] > 0 else mu * 0.2

        # Calculate probability of OVER using normal distribution
        try:
            _, norm = _get_scipy()
            probability = 1 - norm.cdf(line, loc=mu, scale=sigma)
        except:
            probability = 0.50

        # B2B / rest fatigue adjustment
        days_rest = features.get('f_days_rest', 3)
        opp_days_rest = features.get('f_opp_days_rest', 3)
        if days_rest == 0:
            probability -= 0.025
        elif days_rest >= 4:
            probability += 0.010
        if opp_days_rest == 0:
            probability += 0.015
        probability = max(0.0, min(1.0, probability))

        # Apply learning mode cap
        if self.learning_mode:
            probability = self._apply_learning_cap(probability)

        # Determine prediction
        prediction = 'OVER' if probability > 0.5 else 'UNDER'

        return {
            'prediction': prediction,
            'probability': probability,
            'features': features,
            'expected_value': mu,
            'method': 'statistical_continuous'
        }

    def predict_prop(self, player_name, stat_type, line, game_date, home_away='H', opponent_team=None):
        """
        Unified prediction interface. Automatically determines binary vs continuous.

        Args:
            player_name (str): Player name
            stat_type (str): Prop type
            line (float): Over/Under line
            game_date (str): Game date (YYYY-MM-DD)
            home_away (str): 'H' or 'A'
            opponent_team (str): Opponent team abbreviation (e.g., 'BOS', 'ATL')

        Returns:
            dict: Prediction results
        """
        continuous_stats = ['pra', 'minutes']

        if stat_type in continuous_stats:
            return self.predict_continuous_prop(
                player_name, stat_type, line, game_date, home_away, opponent_team
            )
        else:
            return self.predict_binary_prop(
                player_name, stat_type, line, game_date, home_away, opponent_team
            )

    def _apply_learning_cap(self, probability):
        """Apply learning mode probability cap (30-70%)."""
        min_prob, max_prob = self.prob_cap
        return max(min_prob, min(max_prob, probability))


# Example usage
if __name__ == "__main__":
    predictor = NBAStatisticalPredictor()

    # Test binary prediction
    print("🏀 NBA Statistical Prediction Engine Test\n")

    result = predictor.predict_prop(
        player_name="LeBron James",
        stat_type="points",
        line=25.5,
        game_date="2024-11-09",
        home_away='H'
    )

    print("Binary Prediction (Points O25.5):")
    print(f"  Prediction: {result['prediction']}")
    print(f"  Probability: {result['probability']:.2%}")
    print(f"  Method: {result['method']}")

    # Test continuous prediction
    result2 = predictor.predict_prop(
        player_name="LeBron James",
        stat_type="pra",
        line=35.5,
        game_date="2024-11-09",
        home_away='H'
    )

    print("\nContinuous Prediction (PRA O35.5):")
    print(f"  Prediction: {result2['prediction']}")
    print(f"  Probability: {result2['probability']:.2%}")
    print(f"  Expected Value: {result2.get('expected_value', 'N/A')}")
    print(f"  Method: {result2['method']}")
