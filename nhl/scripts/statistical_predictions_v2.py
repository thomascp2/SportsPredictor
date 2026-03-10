"""
Statistical Prediction Engine V2.2 - ASYMMETRIC CAPS

CHANGES IN V2.2 (2025-11-19):
- Implemented asymmetric probability caps based on calibration analysis:
  - UNDER predictions (min_prob): 15% (was 20%) - these hit at 88.7%, can allow more confidence
  - OVER predictions (max_prob): 75% (was 80%) - these hit at 81%, slightly overconfident
- Keeps all opponent features from V2.1

CRITICAL FIX (2025-11-19):
The extractors were returning opponent features but this script was
manually constructing features_for_ml and DISCARDING them!

Now includes:
- Points: 17 features (12 player + 5 opponent)
- Shots: 18 features (13 player + 5 opponent)

Opponent features:
- opp_points_allowed_l10/l5, opp_scoring_pct_allowed, opp_points_std, opp_defensive_trend
- opp_shots_allowed_l10/l5, opp_shots_std, opp_shots_trend, opp_defensive_consistency

Date: 2025-11-19
Status: PRODUCTION READY (Data Collection Phase)
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import sys
import math

# Import feature extractors
sys.path.insert(0, '.')
from features.binary_feature_extractor import BinaryFeatureExtractor
from features.continuous_feature_extractor import ContinuousFeatureExtractor


class StatisticalPredictionEngine:
    """
    Statistical prediction engine using proper distributions
    
    Key approach:
    - Points: Binary classification with Poisson distribution
    - Shots: Continuous prediction with Normal distribution
    - Learning mode: 15-75% asymmetric probability caps (V2.2)
    - Feature storage: Saves all features as JSON for ML training
    - Probability: Represents confidence in the prediction direction
    - NOW INCLUDES: Opponent defensive features!
    """
    
    def __init__(self, db_path: str = 'database/nhl_predictions_v2.db', learning_mode: bool = True, batch_id: str = None):
        """Initialize prediction engine"""
        self.db_path = db_path
        self.learning_mode = learning_mode
        
        # Generate batch_id for this prediction run (required by database)
        if batch_id is None:
            self.batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        else:
            self.batch_id = batch_id
        
        # Initialize feature extractors
        self.binary_extractor = BinaryFeatureExtractor(db_path)
        self.continuous_extractor = ContinuousFeatureExtractor(db_path)
        
        # V2.2: Asymmetric caps based on calibration analysis
        # - UNDER predictions at 20% cap hit at 88.7% -> allow 18% (slightly more confidence)
        # - OVER predictions at 80% cap hit at 81.0% -> tighten to 77% (slightly less overconfidence)
        # Conservative approach for data collection phase - preserve signal for ML training
        self.min_prob = 0.18 if learning_mode else 0.10
        self.max_prob = 0.77 if learning_mode else 0.90
        
        # Database connection for saving predictions
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        
        print(f'INFO: Statistical Prediction Engine V2.2 WITH ASYMMETRIC CAPS')
        print(f'INFO: Batch ID: {self.batch_id}')
        print(f'INFO: Learning Mode: {learning_mode}')
        if learning_mode:
            print(f'INFO:   Probability Cap: {self.min_prob:.0%}-{self.max_prob:.0%} (asymmetric)')
            print(f'INFO:   Points features: 17 (12 player + 5 opponent)')
            print(f'INFO:   Shots features: 18 (13 player + 5 opponent)')
    
    def __del__(self):
        """Clean up database connection"""
        if hasattr(self, 'conn'):
            self.conn.close()
    
    def predict_points(
        self,
        player: str,
        team: str,
        game_date: str,
        opponent: str,
        is_home: bool,
        line: float = 0.5,
        save: bool = True
    ) -> Optional[Dict]:
        """
        Predict points using binary classification
        
        Uses Poisson distribution based on recent performance
        NOW INCLUDES opponent defensive features!
        
        Args:
            line: Points line to predict (0.5 or 1.5 typically)
        """
        # Temporal safety: Only use data from before game_date
        cutoff_date = (datetime.strptime(game_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Extract binary features (includes opponent features!)
        features = self.binary_extractor.extract_features(
            player_name=player,
            team=team,
            game_date=cutoff_date,
            opponent=opponent,
            is_home=is_home
        )
        
        # Check if we have sufficient data
        if features.get('insufficient_data', 0.0) == 1.0:
            return None
        
        # Calculate probability using Poisson distribution
        success_rate_l5 = features.get('success_rate_l5', 0.425)
        success_rate_l10 = features.get('success_rate_l10', 0.425)
        
        # Estimate PPG from success rate
        ppg_recent = success_rate_l5 * 1.2
        success_rate = success_rate_l10
        
        # Poisson parameter (lambda) = expected points
        lambda_param = ppg_recent
        
        # P(X > line) using Poisson distribution
        # For O0.5: P(X > 0.5) = 1 - P(X = 0) = 1 - e^(-lambda)
        # For O1.5: P(X > 1.5) = 1 - P(X = 0) - P(X = 1) = 1 - e^(-lambda) * (1 + lambda)
        
        if line == 0.5:
            # P(X >= 1) = 1 - P(X = 0)
            prob_over = 1 - math.exp(-lambda_param)
        elif line == 1.5:
            # P(X >= 2) = 1 - P(X = 0) - P(X = 1)
            prob_over = 1 - math.exp(-lambda_param) * (1 + lambda_param)
        else:
            # General case: sum probabilities for k = 0 to floor(line)
            prob_at_or_below = sum(
                (lambda_param ** k) * math.exp(-lambda_param) / math.factorial(k)
                for k in range(int(line) + 1)
            )
            prob_over = 1 - prob_at_or_below
        
        # Adjust based on recent success rate
        prob_over = (prob_over * 0.7) + (success_rate * 0.3)
        
        # Apply learning mode caps
        prob_over = max(self.min_prob, min(self.max_prob, prob_over))
        
        # Determine prediction
        prediction = 'OVER' if prob_over > 0.5 else 'UNDER'
        
        # Store probability as confidence in the prediction
        if prediction == 'OVER':
            confidence_prob = prob_over
        else:
            confidence_prob = 1 - prob_over
        
        # Assign confidence tier (based on confidence in prediction)
        confidence_tier = self._assign_confidence_tier(confidence_prob)
        
        # Include ALL features from extractor, including opponent features
        features_for_ml = {
            # Player features (12)
            'success_rate_season': features.get('success_rate_season', 0.35),
            'success_rate_l20': features.get('success_rate_l20', 0.35),
            'success_rate_l10': features.get('success_rate_l10', 0.35),
            'success_rate_l5': features.get('success_rate_l5', 0.35),
            'success_rate_l3': features.get('success_rate_l3', 0.35),
            'current_streak': features.get('current_streak', 0),
            'max_hot_streak': features.get('max_hot_streak', 0),
            'recent_momentum': features.get('recent_momentum', 0.35),
            'games_played': features.get('games_played', 0),
            'is_home': int(is_home),
            'line': line,  # NEW: Include the line being predicted
            'lambda_param': lambda_param,
            'poisson_prob': prob_over,  # Store the calculated probability
            
            # Opponent defensive features (5)
            'opp_points_allowed_l10': features.get('opp_points_allowed_l10', 0.65),
            'opp_points_allowed_l5': features.get('opp_points_allowed_l5', 0.65),
            'opp_scoring_pct_allowed': features.get('opp_scoring_pct_allowed', 0.35),
            'opp_points_std': features.get('opp_points_std', 0.5),
            'opp_defensive_trend': features.get('opp_defensive_trend', 0.0),
            
            # Reference
            'prob_over': prob_over,
        }
        
        # Build prediction dict
        prediction_data = {
            'game_date': game_date,
            'player_name': player,
            'team': team,
            'opponent': opponent,
            'prop_type': 'points',
            'line': line,  # Use the actual line parameter
            'prediction': prediction,
            'probability': confidence_prob,
            'confidence_tier': confidence_tier,
            'expected_value': lambda_param,  # ADD: Expected points (for EV calculation)
            'model_version': 'statistical_v2.2_asym',
            'prediction_batch_id': self.batch_id,
            'features': features_for_ml,
            'created_at': datetime.now().isoformat()
        }

        # Save to database (unless save=False for hybrid engine)
        if save:
            self._save_prediction(prediction_data)

        return prediction_data

    def predict_shots(
        self,
        player: str,
        team: str,
        game_date: str,
        opponent: str,
        is_home: bool,
        line: float = 2.5,
        save: bool = True
    ) -> Optional[Dict]:
        """
        Predict shots using continuous distribution

        Uses Normal distribution based on shot volume and consistency.
        NOW INCLUDES opponent defensive features!
        """
        # Temporal safety: Only use data from before game_date
        cutoff_date = (datetime.strptime(game_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Extract continuous features (includes opponent features!)
        features = self.continuous_extractor.extract_features(
            player_name=player,
            team=team,
            game_date=cutoff_date,
            opponent=opponent,
            is_home=is_home
        )
        
        # Check if we have sufficient data
        if features.get('insufficient_data', 0.0) == 1.0:
            return None
        
        # Calculate probability using Normal distribution
        mean_shots = features.get('sog_l10', 2.5)
        std_dev = features.get('sog_std_l10', 1.5)
        
        # P(X > line) using normal CDF
        z_score = (line - mean_shots) / std_dev if std_dev > 0 else 0
        
        # P(X > line) = 1 - CDF(z_score)
        prob_over = 0.5 * (1 - self._erf(z_score / math.sqrt(2)))
        
        # Apply learning mode caps
        prob_over = max(self.min_prob, min(self.max_prob, prob_over))
        
        # Determine prediction
        prediction = 'OVER' if prob_over > 0.5 else 'UNDER'
        
        # Store probability as confidence in the prediction
        if prediction == 'OVER':
            confidence_prob = prob_over
        else:
            confidence_prob = 1 - prob_over
        
        # Assign confidence tier
        confidence_tier = self._assign_confidence_tier(confidence_prob)
        
        # Include ALL features from extractor, including opponent features
        features_for_ml = {
            # Player features (13)
            'sog_season': features.get('sog_season', 2.5),
            'sog_l10': features.get('sog_l10', 2.5),
            'sog_l5': features.get('sog_l5', 2.5),
            'sog_std_season': features.get('sog_std_season', 1.2),
            'sog_std_l10': features.get('sog_std_l10', 1.2),
            'sog_trend': features.get('sog_trend', 0.0),
            'avg_toi_minutes': features.get('avg_toi_minutes', 15.0),
            'games_played': features.get('games_played', 0),
            'is_home': int(is_home),
            'line': line,
            'mean_shots': mean_shots,
            'std_dev': std_dev,
            'z_score': z_score,
            
            # Opponent defensive features (5)
            'opp_shots_allowed_l10': features.get('opp_shots_allowed_l10', 2.5),
            'opp_shots_allowed_l5': features.get('opp_shots_allowed_l5', 2.5),
            'opp_shots_std': features.get('opp_shots_std', 1.2),
            'opp_shots_trend': features.get('opp_shots_trend', 0.0),
            'opp_defensive_consistency': features.get('opp_defensive_consistency', 1.2),
            
            # Reference
            'prob_over': prob_over,
        }
        
        # Build prediction dict
        prediction_data = {
            'game_date': game_date,
            'player_name': player,
            'team': team,
            'opponent': opponent,
            'prop_type': 'shots',
            'line': line,
            'prediction': prediction,
            'probability': confidence_prob,
            'confidence_tier': confidence_tier,
            'expected_value': mean_shots,  # ADD: Expected shots (for EV calculation)
            'model_version': 'statistical_v2.2_asym',
            'prediction_batch_id': self.batch_id,
            'features': features_for_ml,
            'created_at': datetime.now().isoformat()
        }

        # Save to database (unless save=False for hybrid engine)
        if save:
            self._save_prediction(prediction_data)

        return prediction_data

    def _predict_count_prop(
        self,
        player: str,
        team: str,
        game_date: str,
        opponent: str,
        is_home: bool,
        prop_type: str,
        db_column: str,
        lines: list,
        league_avg: float,
        league_std: float,
        save: bool = True
    ) -> list:
        """
        Generic prediction for any count-based NHL prop (hits, blocked_shots, assists).

        Queries player_game_logs for the given db_column, computes Normal distribution
        parameters, and generates predictions for each line. Returns list of prediction dicts.

        Args:
            prop_type:   Stored as prop_type in predictions table (e.g. 'hits')
            db_column:   Column in player_game_logs (e.g. 'hits')
            lines:       List of lines to predict (e.g. [0.5, 1.5, 2.5])
            league_avg:  Default mean when no player history exists
            league_std:  Default std dev when no player history exists
        """
        cutoff_date = (datetime.strptime(game_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')

        # Query player history for this stat
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT game_date, {db_column}, toi_seconds
            FROM player_game_logs
            WHERE player_name = ? AND team = ? AND game_date < ?
            ORDER BY game_date DESC
            LIMIT 30
        """, (player, team, cutoff_date))
        rows = cursor.fetchall()

        if len(rows) < 5:
            return []  # Insufficient data — skip this player for this prop

        values = [r[1] for r in rows]
        values_l10 = values[:10]
        values_l5 = values[:5]
        toi_vals = [r[2] for r in rows[:10] if r[2] > 0]

        mean_season = sum(values) / len(values)
        mean_l10 = sum(values_l10) / len(values_l10)
        mean_l5 = sum(values_l5) / len(values_l5)

        variance_l10 = sum((v - mean_l10) ** 2 for v in values_l10) / max(len(values_l10) - 1, 1)
        std_l10 = max(variance_l10 ** 0.5, 0.5)

        avg_toi_minutes = (sum(toi_vals) / len(toi_vals) / 60) if toi_vals else 15.0

        # Trend: slope of L10 values (most recent first → oldest first for regression)
        trend = 0.0
        if len(values_l10) >= 4:
            n = len(values_l10)
            x = list(range(n))
            x_mean = sum(x) / n
            y = list(reversed(values_l10))  # oldest first
            y_mean = sum(y) / n
            num = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
            den = sum((xi - x_mean) ** 2 for xi in x) or 1
            trend = num / den

        results = []
        for line in lines:
            z_score = (line - mean_l10) / std_l10 if std_l10 > 0 else 0
            prob_over = 0.5 * (1 - self._erf(z_score / math.sqrt(2)))
            prob_over = max(self.min_prob, min(self.max_prob, prob_over))

            prediction = 'OVER' if prob_over > 0.5 else 'UNDER'
            confidence_prob = prob_over if prediction == 'OVER' else 1 - prob_over
            confidence_tier = self._assign_confidence_tier(confidence_prob)

            features_for_ml = {
                f'{prop_type}_season': mean_season,
                f'{prop_type}_l10': mean_l10,
                f'{prop_type}_l5': mean_l5,
                f'{prop_type}_std_l10': std_l10,
                f'{prop_type}_trend': trend,
                'avg_toi_minutes': avg_toi_minutes,
                'games_played': float(len(values)),
                'is_home': int(is_home),
                'line': line,
                'mean_val': mean_l10,
                'mean_hits': mean_l10,    # alias used by smart_pick_selector
                'mean_blocked': mean_l10,  # alias used by smart_pick_selector
                'std_dev': std_l10,
                'z_score': z_score,
                'prob_over': prob_over,
            }

            prediction_data = {
                'game_date': game_date,
                'player_name': player,
                'team': team,
                'opponent': opponent,
                'prop_type': prop_type,
                'line': line,
                'prediction': prediction,
                'probability': confidence_prob,
                'confidence_tier': confidence_tier,
                'expected_value': mean_l10,
                'model_version': 'statistical_v2.2_count_prop',
                'prediction_batch_id': self.batch_id,
                'features': features_for_ml,
                'created_at': datetime.now().isoformat()
            }

            if save:
                self._save_prediction(prediction_data)

            results.append(prediction_data)

        return results

    def predict_hits(self, player, team, game_date, opponent, is_home,
                     lines=None, save=True):
        """Predict hits using Normal distribution. Lines default to [0.5, 1.5, 2.5, 3.5]."""
        if lines is None:
            lines = [0.5, 1.5, 2.5, 3.5]
        return self._predict_count_prop(
            player, team, game_date, opponent, is_home,
            prop_type='hits', db_column='hits', lines=lines,
            league_avg=2.5, league_std=2.0, save=save
        )

    def predict_blocked_shots(self, player, team, game_date, opponent, is_home,
                              lines=None, save=True):
        """Predict blocked shots using Normal distribution. Lines default to [0.5, 1.5]."""
        if lines is None:
            lines = [0.5, 1.5]
        return self._predict_count_prop(
            player, team, game_date, opponent, is_home,
            prop_type='blocked_shots', db_column='blocked_shots', lines=lines,
            league_avg=1.0, league_std=1.2, save=save
        )

    def _assign_confidence_tier(self, confidence_prob: float) -> str:
        """
        Assign confidence tier based on confidence in prediction
        
        Updated for V2.2 asymmetric caps (max now 85% instead of 80%)
        """
        if self.learning_mode:
            if confidence_prob >= 0.70:
                return 'T2-STRONG'
            elif confidence_prob >= 0.65:
                return 'T3-GOOD'
            elif confidence_prob >= 0.55:
                return 'T4-LEAN'
            else:
                return 'T5-FADE'
        else:
            if confidence_prob >= 0.75:
                return 'T1-ELITE'
            elif confidence_prob >= 0.65:
                return 'T2-STRONG'
            elif confidence_prob >= 0.60:
                return 'T3-GOOD'
            elif confidence_prob >= 0.55:
                return 'T4-LEAN'
            else:
                return 'T5-FADE'
    
    def _save_prediction(self, prediction_data: Dict):
        """Save prediction to database WITH FEATURES"""
        try:
            features_dict = prediction_data.get('features', {})
            features_json = json.dumps(features_dict) if features_dict else None
            
            self.cursor.execute("""
                INSERT INTO predictions (
                    game_date, player_name, team, opponent, 
                    prop_type, line, prediction, probability, 
                    confidence_tier, expected_value, model_version, prediction_batch_id, 
                    features_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prediction_data['game_date'],
                prediction_data['player_name'],
                prediction_data['team'],
                prediction_data['opponent'],
                prediction_data['prop_type'],
                prediction_data['line'],
                prediction_data['prediction'],
                prediction_data['probability'],
                prediction_data['confidence_tier'],
                prediction_data.get('expected_value'),
                prediction_data['model_version'],
                prediction_data['prediction_batch_id'],
                features_json,
                prediction_data['created_at']
            ))
            
            self.conn.commit()
            
        except sqlite3.IntegrityError as e:
            print(f'WARNING: Failed to save prediction: {e}')
        except Exception as e:
            print(f'ERROR: Failed to save prediction: {e}')
    
    def _erf(self, x: float) -> float:
        """Approximation of error function for normal CDF"""
        a1 =  0.254829592
        a2 = -0.284496736
        a3 =  1.421413741
        a4 = -1.453152027
        a5 =  1.061405429
        p  =  0.3275911
        
        sign = 1 if x >= 0 else -1
        x = abs(x)
        
        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
        
        return sign * y


# Test function
if __name__ == '__main__':
    print('Testing Statistical Prediction Engine V2.2 WITH ASYMMETRIC CAPS')
    print('='*70)
    print()
    
    engine = StatisticalPredictionEngine(learning_mode=True)
    
    print()
    print('Testing points predictions (O0.5 and O1.5)...')
    
    for line in [0.5, 1.5]:
        pred = engine.predict_points(
            player='C. McDavid',
            team='EDM',
            game_date='2025-11-20',
            opponent='CGY',
            is_home=True,
            line=line
        )
        
        if pred:
            print(f'\n  O{line} {pred["prediction"]}: {pred["probability"]*100:.1f}%')
        else:
            print(f'\n  O{line}: Insufficient data')
    
    print()
    print('Testing shots prediction...')
    pred = engine.predict_shots(
        player='C. McDavid',
        team='EDM',
        game_date='2025-11-20',
        opponent='CGY',
        is_home=True,
        line=2.5
    )
    
    if pred:
        print(f'  Prediction: {pred["prediction"]} ({pred["probability"]*100:.1f}%)')
        print(f'  Feature count: {len(pred["features"])}')
        print()
        
        # Check for opponent features
        opp_features = [k for k in pred['features'].keys() if k.startswith('opp_')]
        print(f'  Opponent features ({len(opp_features)}): {opp_features}')
    else:
        print('  Insufficient data')
    
    print()
    print('='*70)
    print('V2.2 CHANGES (with V5 multi-line points):')
    print('  - Asymmetric caps: 18% (UNDER) / 77% (OVER) - conservative for ML')
    print('  - Points: Now supports O0.5 and O1.5 lines')
    print('  - Shots: O1.5, O2.5, O3.5 (unchanged)')
    print('  - Model version: statistical_v2.2_asym')
    print('  - Platform target: Underdog Fantasy (UNDER bets available)')
    print('='*70)
