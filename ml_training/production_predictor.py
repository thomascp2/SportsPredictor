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

        # Break-even rates by odds type (exact fractions — no approximations).
        # Tiers are assigned by edge above break-even, NOT raw probability.
        # A goblin pick at 77% raw probability has edge=(0.77-0.7619)*100=+0.81pp → T4-LEAN,
        # NOT T1-ELITE. Using raw probability for tiers was the pre-Mar-8 bug (fixed in
        # smart_pick_selector.py); this file now matches that fix.
        # NOTE: smart_pick_selector.py is the authoritative tier source for Supabase/display.
        # These tiers are used for intermediate logging and non-Supabase consumers only.
        self._break_evens = {
            'standard': 110 / 210,  # 0.52381
            'goblin':   320 / 420,  # 0.76190
            'demon':    100 / 220,  # 0.45455
        }

    def _is_model_degenerate(self, metadata) -> bool:
        """Return True if model should be blocked from production use.

        Three failure modes:
          1. Brier < 0.01: outputs near-0 or near-1 probs exclusively (always-one-class)
          2. Accuracy > 0.98: memorised a degenerate class distribution
          3. improvement_over_baseline <= 0: model hurts more than always-majority-class.
             Measured against always-majority-class baseline (post-2026-04-15 models).
             For pre-fix models the stored baseline was the stat model — those may have
             inflated improvement numbers, so we also apply a hard accuracy floor.
          4. Test accuracy < 0.50: worse than a coin flip on the test set, actively harmful.
        """
        if metadata.test_brier_score is not None and metadata.test_brier_score < 0.01:
            return True
        if metadata.test_accuracy is not None and metadata.test_accuracy > 0.98:
            return True
        if metadata.test_accuracy is not None and metadata.test_accuracy < 0.50:
            return True
        if (metadata.improvement_over_baseline is not None
                and metadata.improvement_over_baseline <= 0.0):
            return True
        return False

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
        statistical_prediction: Dict = None,
        odds_type: str = 'standard'
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

        # Degeneracy check: refuse to use a model that predicts one class with near-certainty.
        # Falls back to statistical prediction if provided; raises otherwise.
        if self._is_model_degenerate(metadata):
            print(f"[M4-GUARD] Degenerate model detected: {sport} {prop_type} @ {line} "
                  f"(Brier={metadata.test_brier_score:.4f}, acc={metadata.test_accuracy:.1%}). "
                  f"Falling back to statistical prediction.")
            if statistical_prediction:
                return statistical_prediction
            raise ValueError(
                f"Degenerate model: {sport} {prop_type} @ {line} — "
                f"Brier={metadata.test_brier_score:.4f}. No statistical fallback provided."
            )

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
        confidence_tier = self._assign_confidence_tier(confidence_prob, odds_type)

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
        ml_weight: float = 0.6,
        odds_type: str = 'standard'
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

        # Degeneracy check before ensemble: degenerate models corrupt the blend.
        # Fall back to pure statistical rather than polluting ensemble_prob_over.
        cached = self._get_cached_model(sport, prop_type, line)
        if self._is_model_degenerate(cached['metadata']):
            print(f"[M4-GUARD] Degenerate model in ensemble: {sport} {prop_type} @ {line} — "
                  f"using statistical-only prediction.")
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
        confidence_tier = self._assign_confidence_tier(confidence_prob, odds_type)

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
        features_list: List[Dict],
        odds_type: str = 'standard'
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

        if self._is_model_degenerate(metadata):
            raise ValueError(
                f"[M4-GUARD] Degenerate model: {sport} {prop_type} @ {line} "
                f"(Brier={metadata.test_brier_score:.4f}). Cannot batch-predict."
            )

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
            confidence_tier = self._assign_confidence_tier(confidence_prob, odds_type)

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

        Tries three name lookups before falling back to a sensible default:
          1. Exact match: features[name]
          2. Add f_ prefix: features['f_' + name]   (new naming convention)
          3. Strip f_ prefix: features[name[2:]]     (old naming convention)
        This prevents feature-name drift between training eras from causing silent
        0.0 substitutions for critical features like sog_l10 / f_l10_avg.
        """
        feature_vector = []

        for feature_name in expected_order:
            # Try exact name first, then cross-naming-convention fallbacks
            value = features.get(feature_name)
            if value is None:
                value = features.get(f"f_{feature_name}")
            if value is None and feature_name.startswith("f_"):
                value = features.get(feature_name[2:])

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

    def _assign_confidence_tier(self, confidence_prob: float, odds_type: str = 'standard') -> str:
        """Assign confidence tier based on edge above break-even (not raw probability).

        Args:
            confidence_prob: Directional confidence (P(predicted direction winning)).
            odds_type: 'standard', 'goblin', or 'demon' — determines break-even.
        """
        break_even = self._break_evens.get(odds_type, self._break_evens['standard'])
        edge = (confidence_prob - break_even) * 100
        if edge >= 19:
            return 'T1-ELITE'
        if edge >= 14:
            return 'T2-STRONG'
        if edge >= 9:
            return 'T3-GOOD'
        if edge >= 0:
            return 'T4-LEAN'
        return 'T5-FADE'

    def predict_bma(
        self,
        sport: str,
        prop_type: str,
        line: float,
        features: Dict,
        statistical_prediction: Dict,
        mab_weights: Dict = None,
        odds_type: str = 'standard',
        n_bootstrap: int = 200,
    ) -> Dict:
        """
        Bayesian Model Averaging — return probability distribution across all models.

        Instead of a single blended probability, returns the full distribution:
          - mean: weighted average across all available models
          - std: spread (uncertainty measure)
          - ci_lower/ci_upper: 95% credible interval via bootstrap
          - confidence: HIGH/MEDIUM/LOW based on std
          - component_probs: per-model probabilities for inspection

        MAB weights default to equal if not provided. Pass weights from
        ThompsonSamplingMAB.sample_weights() for dynamic allocation.

        Args:
            sport: 'nba', 'nhl', 'mlb'
            prop_type: e.g. 'points'
            line: betting line
            features: feature dict
            statistical_prediction: stat model output (always included as 'stat')
            mab_weights: dict of model_name → weight (from ThompsonSamplingMAB)
                         e.g. {'xgb': 0.45, 'stat': 0.25, ...}
                         If None, equal weights are used.
            odds_type: 'standard', 'goblin', or 'demon'
            n_bootstrap: number of bootstrap draws for CI estimation

        Returns:
            {
                'prediction':       'OVER' or 'UNDER',
                'probability':      float,   # BMA mean (directional confidence)
                'prob_over':        float,   # BMA mean P(OVER)
                'prob_std':         float,   # uncertainty — lower is better
                'ci_lower':         float,   # 2.5th percentile of bootstrap
                'ci_upper':         float,   # 97.5th percentile
                'model_confidence': str,     # 'HIGH' / 'MEDIUM' / 'LOW'
                'component_probs':  dict,    # model_name → prob_over
                'mab_weights_used': dict,    # actual weights applied
                'confidence_tier':  str,
                'expected_value':   float,
                'model_version':    str,
            }
        """
        # Collect component model probabilities
        component_probs: Dict[str, float] = {}

        # Statistical model (always available)
        stat_prob = statistical_prediction.get('probability', 0.5)
        stat_pred = statistical_prediction.get('prediction', 'OVER')
        stat_prob_over = stat_prob if stat_pred == 'OVER' else (1.0 - stat_prob)
        component_probs['stat'] = float(stat_prob_over)

        # ML model (if available and not degenerate)
        if self.is_model_available(sport, prop_type, line):
            cached = self._get_cached_model(sport, prop_type, line)
            if not self._is_model_degenerate(cached['metadata']):
                try:
                    ml_result = self.predict(sport, prop_type, line, features, odds_type=odds_type)
                    component_probs['xgb'] = float(ml_result.get('ml_prob_over', 0.5))
                except Exception:
                    pass

        # Normalize MAB weights to only the models we actually have probs for
        available_models = list(component_probs.keys())

        if mab_weights and all(m in mab_weights for m in available_models):
            raw_weights = {m: mab_weights[m] for m in available_models}
        else:
            # Equal weights fallback
            raw_weights = {m: 1.0 / len(available_models) for m in available_models}

        # Normalize weights
        total_w = sum(raw_weights.values())
        weights_used = {m: w / total_w for m, w in raw_weights.items()}

        # BMA mean
        bma_prob_over = sum(component_probs[m] * weights_used[m] for m in available_models)

        # Bootstrap CI: resample model weights with Dirichlet noise
        rng = np.random.default_rng(seed=42)
        bootstrap_probs = []
        weight_values = np.array([weights_used[m] for m in available_models])
        prob_values   = np.array([component_probs[m] for m in available_models])

        for _ in range(n_bootstrap):
            # Add Dirichlet noise to weights (concentration = 5 → mild perturbation)
            noisy_weights = rng.dirichlet(weight_values * 5 + 0.5)
            bootstrap_probs.append(float(np.dot(noisy_weights, prob_values)))

        bootstrap_array = np.array(bootstrap_probs)
        prob_std  = float(np.std(bootstrap_array))
        ci_lower  = float(np.percentile(bootstrap_array, 2.5))
        ci_upper  = float(np.percentile(bootstrap_array, 97.5))

        # Confidence label based on std
        if prob_std < 0.03:
            model_confidence = 'HIGH'
        elif prob_std < 0.07:
            model_confidence = 'MEDIUM'
        else:
            model_confidence = 'LOW'

        # Direction and final confidence
        prediction   = 'OVER' if bma_prob_over > 0.5 else 'UNDER'
        final_prob   = bma_prob_over if prediction == 'OVER' else (1.0 - bma_prob_over)
        confidence_tier = self._assign_confidence_tier(final_prob, odds_type)
        expected_value  = statistical_prediction.get('expected_value', line)

        return {
            'prediction':       prediction,
            'probability':      round(final_prob, 4),
            'prob_over':        round(bma_prob_over, 4),
            'prob_std':         round(prob_std, 4),
            'ci_lower':         round(ci_lower, 4),
            'ci_upper':         round(ci_upper, 4),
            'model_confidence': model_confidence,
            'component_probs':  {m: round(p, 4) for m, p in component_probs.items()},
            'mab_weights_used': {m: round(w, 4) for m, w in weights_used.items()},
            'confidence_tier':  confidence_tier,
            'expected_value':   expected_value,
            'model_version':    'bma_v2',
        }

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
