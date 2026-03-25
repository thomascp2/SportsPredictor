"""
Production Predictor
====================

Loads trained ML models and generates predictions compatible with
the existing statistical prediction format.

Supports:
- NHL (JSON features, 17-18 features)
- NBA (column features, 20+ features)
- Ensemble mode (combine ML + statistical)
- Fallback to statistical when ML unavailable
"""

import numpy as np
from typing import Dict, Optional, List
from pathlib import Path

try:
    from .model_manager import ModelRegistry, ModelMetadata
except ImportError:
    from model_manager import ModelRegistry, ModelMetadata


class ProductionPredictor:
    """
    Production-ready ML predictor that integrates with existing pipelines.

    Returns predictions in the same format as StatisticalPredictionEngine:
    {
        'prediction': 'OVER' or 'UNDER',
        'probability': float,
        'confidence_tier': str,
        'expected_value': float,
        'features': dict,
        'model_version': str
    }
    """

    def __init__(self, registry_dir: str = None):
        """
        Initialize predictor with model registry.

        Args:
            registry_dir: Path to model registry directory
        """
        self.registry = ModelRegistry(registry_dir)
        self._model_cache = {}  # Cache loaded models for performance

        # Confidence tier thresholds (match statistical engine)
        self.tier_thresholds = [
            ('T1-ELITE', 0.75),
            ('T2-STRONG', 0.70),
            ('T3-GOOD', 0.65),
            ('T4-LEAN', 0.55),
            ('T5-FADE', 0.0)
        ]

    def _get_cached_model(self, sport: str, prop_type: str, line: float) -> Dict:
        """Get model from cache or load it"""
        cache_key = f"{sport}_{prop_type}_{line}"

        if cache_key not in self._model_cache:
            model, scaler, metadata = self.registry.load_model(sport, prop_type, line)
            self._model_cache[cache_key] = {
                'model': model,
                'scaler': scaler,
                'metadata': metadata
            }

        return self._model_cache[cache_key]

    def is_model_available(self, sport: str, prop_type: str, line: float) -> bool:
        """Check if ML model is available for this combination"""
        return self.registry.is_model_available(sport, prop_type, line)

    def get_model_stats(self, sport: str, prop_type: str, line: float) -> Dict:
        """Get model statistics without loading the full model"""
        return self.registry.get_model_stats(sport, prop_type, line)

    def predict(
        self,
        sport: str,
        prop_type: str,
        line: float,
        features: Dict,
        statistical_prediction: Dict = None
    ) -> Dict:
        """
        Generate ML prediction for a single instance.

        Args:
            sport: 'nhl' or 'nba'
            prop_type: 'points', 'shots', 'rebounds', etc.
            line: Betting line
            features: Feature dictionary from feature extractor
            statistical_prediction: Optional statistical prediction for fallback

        Returns:
            Prediction dict compatible with existing pipeline
        """
        if not self.is_model_available(sport, prop_type, line):
            # Fall back to statistical prediction if provided
            if statistical_prediction:
                return statistical_prediction
            raise ValueError(f"No ML model available for {sport} {prop_type} @ {line}")

        cached = self._get_cached_model(sport, prop_type, line)
        model = cached['model']
        scaler = cached['scaler']
        metadata = cached['metadata']

        # Prepare features in correct order
        feature_vector = self._prepare_features(features, metadata.feature_names)

        # Scale features
        feature_vector_scaled = scaler.transform([feature_vector])

        # Get prediction probability
        prob_over = model.predict_proba(feature_vector_scaled)[0][1]

        # Determine prediction direction
        prediction = 'OVER' if prob_over > 0.5 else 'UNDER'

        # Confidence probability (how confident in the prediction direction)
        confidence_prob = prob_over if prediction == 'OVER' else (1 - prob_over)

        # Assign confidence tier
        confidence_tier = self._assign_confidence_tier(confidence_prob)

        # Get expected value from features (lambda for points, mean for shots)
        expected_value = features.get('lambda_param', features.get('mean_shots', line))

        # Build result dict (same format as StatisticalPredictionEngine)
        result = {
            'prediction': prediction,
            'probability': confidence_prob,
            'confidence_tier': confidence_tier,
            'expected_value': expected_value,
            'features': features,
            'model_version': f"ml_{metadata.version}",
            'ml_prob_over': prob_over,  # Raw probability for analysis
            'ml_model_type': metadata.model_type
        }

        return result

    def predict_ensemble(
        self,
        sport: str,
        prop_type: str,
        line: float,
        features: Dict,
        statistical_prediction: Dict,
        ml_weight: float = 0.6
    ) -> Dict:
        """
        Generate ensemble prediction combining ML and statistical models.

        Args:
            sport: 'nhl' or 'nba'
            prop_type: 'points', 'shots', etc.
            line: Betting line
            features: Feature dictionary
            statistical_prediction: Statistical model prediction
            ml_weight: Weight for ML prediction (0-1), default 0.6 (60% ML, 40% stat)

        Returns:
            Ensemble prediction dict
        """
        if not self.is_model_available(sport, prop_type, line):
            return statistical_prediction

        # Get ML prediction
        ml_result = self.predict(sport, prop_type, line, features)

        # Extract statistical probability
        stat_prob = statistical_prediction['probability']
        stat_pred = statistical_prediction['prediction']

        # Convert statistical probability to prob_over for comparison
        # Statistical stores confidence in predicted direction
        if stat_pred == 'UNDER':
            stat_prob_over = 1 - stat_prob
        else:
            stat_prob_over = stat_prob

        ml_prob_over = ml_result['ml_prob_over']

        # Weighted ensemble
        ensemble_prob_over = (ml_weight * ml_prob_over) + ((1 - ml_weight) * stat_prob_over)

        # Determine final prediction
        prediction = 'OVER' if ensemble_prob_over > 0.5 else 'UNDER'
        confidence_prob = ensemble_prob_over if prediction == 'OVER' else (1 - ensemble_prob_over)
        confidence_tier = self._assign_confidence_tier(confidence_prob)

        return {
            'prediction': prediction,
            'probability': confidence_prob,
            'confidence_tier': confidence_tier,
            'expected_value': ml_result['expected_value'],
            'features': features,
            'model_version': f"ensemble_ml{int(ml_weight*100)}",
            'ml_prob_over': ml_prob_over,
            'stat_prob_over': stat_prob_over,
            'ensemble_weight': ml_weight
        }

    def predict_batch(
        self,
        sport: str,
        prop_type: str,
        line: float,
        features_list: List[Dict]
    ) -> List[Dict]:
        """
        Generate predictions for multiple instances efficiently.

        Args:
            sport: 'nhl' or 'nba'
            prop_type: 'points', 'shots', etc.
            line: Betting line
            features_list: List of feature dictionaries

        Returns:
            List of prediction dicts
        """
        if not self.is_model_available(sport, prop_type, line):
            raise ValueError(f"No ML model available for {sport} {prop_type} @ {line}")

        cached = self._get_cached_model(sport, prop_type, line)
        model = cached['model']
        scaler = cached['scaler']
        metadata = cached['metadata']

        # Prepare all feature vectors
        feature_matrix = []
        for features in features_list:
            feature_vector = self._prepare_features(features, metadata.feature_names)
            feature_matrix.append(feature_vector)

        feature_matrix = np.array(feature_matrix)

        # Scale features
        feature_matrix_scaled = scaler.transform(feature_matrix)

        # Get all predictions at once
        probs_over = model.predict_proba(feature_matrix_scaled)[:, 1]

        # Build results
        results = []
        for i, (features, prob_over) in enumerate(zip(features_list, probs_over)):
            prediction = 'OVER' if prob_over > 0.5 else 'UNDER'
            confidence_prob = prob_over if prediction == 'OVER' else (1 - prob_over)
            confidence_tier = self._assign_confidence_tier(confidence_prob)

            expected_value = features.get('lambda_param', features.get('mean_shots', line))

            results.append({
                'prediction': prediction,
                'probability': confidence_prob,
                'confidence_tier': confidence_tier,
                'expected_value': expected_value,
                'features': features,
                'model_version': f"ml_{metadata.version}",
                'ml_prob_over': prob_over,
                'ml_model_type': metadata.model_type
            })

        return results

    def _prepare_features(self, features: Dict, expected_order: List[str]) -> np.ndarray:
        """
        Prepare features in the order expected by the model.

        Handles missing features by using sensible default values.
        """
        feature_vector = []

        for feature_name in expected_order:
            value = features.get(feature_name)

            if value is None:
                # Use sensible defaults based on feature type
                if 'rate' in feature_name or 'pct' in feature_name:
                    value = 0.5  # Default success rate
                elif 'streak' in feature_name:
                    value = 0  # No streak
                elif 'trend' in feature_name:
                    value = 0.0  # No trend
                elif 'std' in feature_name:
                    value = 1.0  # Default standard deviation
                elif 'is_home' in feature_name:
                    value = 0  # Away game default
                elif 'games_played' in feature_name:
                    value = 10  # Assume some games played
                elif 'insufficient_data' in feature_name:
                    value = 0  # Assume sufficient data
                else:
                    value = 0.0  # Generic default

            feature_vector.append(float(value))

        return np.array(feature_vector)

    def _assign_confidence_tier(self, confidence_prob: float) -> str:
        """Assign confidence tier based on probability"""
        for tier, threshold in self.tier_thresholds:
            if confidence_prob >= threshold:
                return tier
        return 'T5-FADE'

    def clear_cache(self):
        """Clear the model cache (useful after retraining)"""
        self._model_cache.clear()

    def list_available_models(self, sport: str = None) -> List[Dict]:
        """List all available models in the registry"""
        return self.registry.list_models(sport)


if __name__ == "__main__":
    # Test the predictor
    predictor = ProductionPredictor()

    print("\nAvailable Models:")
    print("-" * 40)
    models = predictor.list_available_models()

    if not models:
        print("No models found. Run training first:")
        print("  python ml_training/train_models.py --sport nhl --all")
    else:
        for m in models:
            print(f"  {m['sport']} {m['prop_type']} @ {m['line']}: {m['model_type']}")
