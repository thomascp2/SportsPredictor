"""
ML Training Pipeline for Sports Predictions
============================================

This module provides the ML training infrastructure for both NHL and NBA
prediction systems. It's designed to be used once sufficient data has
been collected (~5,000+ predictions per prop/line with outcomes).

USAGE:
    python ml_training_pipeline.py --sport nhl --prop points --line 0.5
    python ml_training_pipeline.py --sport nba --prop rebounds --line 7.5
    python ml_training_pipeline.py --sport nhl --all  # Train all prop/line combos

REQUIREMENTS:
    pip install scikit-learn xgboost lightgbm pandas numpy matplotlib

Author: Sports Prediction System
Date: November 2025
"""

import sqlite3
import json
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

# ML Libraries
from sklearn.model_selection import train_test_split, cross_val_score, TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, brier_score_loss, log_loss, classification_report,
    confusion_matrix
)
try:
    from sklearn.calibration import calibration_curve
except ImportError:
    from sklearn.metrics import calibration_curve
from sklearn.calibration import CalibratedClassifierCV

# Optional: Advanced boosting libraries
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    print("NOTE: xgboost not installed. Run: pip install xgboost")

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False

# Model persistence
try:
    from .model_manager import ModelRegistry, ModelMetadata
    MODEL_SAVING_AVAILABLE = True
except ImportError:
    try:
        from model_manager import ModelRegistry, ModelMetadata
        MODEL_SAVING_AVAILABLE = True
    except ImportError:
        MODEL_SAVING_AVAILABLE = False
        print("NOTE: model_manager not found. Models will not be saved.")


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class MLConfig:
    """ML Training Configuration"""
    # Minimum data requirements
    min_samples: int = 3000
    min_positive_rate: float = 0.15  # At least 15% of one class

    # Rolling training window — only train on recent data to avoid
    # stale pre-deadline patterns diluting post-deadline signals.
    # 0 = use all history (legacy behaviour).
    # Recommended: 90 for most props, 60 for volatile combos (pra, stocks).
    training_window_days: int = 90
    
    # Train/Val/Test split
    test_size: float = 0.15
    val_size: float = 0.15
    
    # Cross-validation
    cv_folds: int = 5
    use_time_series_cv: bool = True  # Respect temporal ordering
    
    # Model selection
    models_to_train: List[str] = None
    
    # Calibration — uses a DEDICATED calibration split separate from val.
    # Train→val (model selection) → cal (calibration only) → test (final eval).
    calibrate_probabilities: bool = True
    calibration_method: str = 'isotonic'  # 'isotonic' outperforms 'sigmoid' on skewed sports data
    cal_size: float = 0.10  # 10% of data reserved for calibration (separate from val/test)
    
    # Output
    save_models: bool = True
    model_output_dir: str = 'models'
    
    def __post_init__(self):
        if self.models_to_train is None:
            self.models_to_train = [
                'logistic_regression',
                'random_forest',
                'gradient_boosting',
            ]
            if XGBOOST_AVAILABLE:
                self.models_to_train.append('xgboost')
            if LIGHTGBM_AVAILABLE:
                self.models_to_train.append('lightgbm')


# ============================================================================
# DATA LOADING
# ============================================================================

class DataLoader:
    """Load and prepare data for ML training"""
    
    def __init__(self, sport: str, db_path: str = None):
        self.sport = sport.upper()
        
        if db_path:
            self.db_path = db_path
        elif self.sport == 'NHL':
            self.db_path = 'nhl/database/nhl_predictions_v2.db'
        else:  # NBA
            self.db_path = 'nba/database/nba_predictions.db'
    
    def load_training_data(self, prop_type: str, line: float,
                           training_window_days: int = 0) -> pd.DataFrame:
        """
        Load predictions with outcomes for a specific prop/line.

        Args:
            prop_type: 'points', 'shots', 'rebounds', etc.
            line: The betting line (e.g., 0.5, 2.5, 15.5)
            training_window_days: If > 0, restrict to the most recent N calendar
                days.  Keeps the model focused on current roster/skill levels
                rather than patterns from months ago.

        Returns:
            DataFrame with features and target
        """
        conn = sqlite3.connect(self.db_path)

        if self.sport == 'NHL':
            df = self._load_nhl_data(conn, prop_type, line)
        else:
            df = self._load_nba_data(conn, prop_type, line)

        conn.close()

        # ── Rolling window filter ────────────────────────────────────────────
        if training_window_days > 0 and len(df) > 0 and 'game_date' in df.columns:
            from datetime import date, timedelta
            cutoff = (date.today() - timedelta(days=training_window_days)).isoformat()
            before = len(df)
            df = df[df['game_date'] >= cutoff].copy()
            after = len(df)
            if before != after:
                print(f"  [Window] {training_window_days}d cutoff ({cutoff}): "
                      f"{before:,} -> {after:,} samples kept")

        return df
    
    def _load_nhl_data(self, conn, prop_type: str, line: float) -> pd.DataFrame:
        """Load NHL data (features stored as JSON)"""
        
        query = """
            SELECT 
                p.id,
                p.game_date,
                p.player_name,
                p.team,
                p.opponent,
                p.prediction as model_prediction,
                p.probability as model_probability,
                p.features_json,
                o.actual_stat_value,
                o.actual_outcome,
                o.outcome,
                -- CRITICAL: Train on actual outcome (OVER/UNDER), NOT prediction correctness (HIT/MISS)
                CASE WHEN o.actual_outcome = 'OVER' THEN 1 ELSE 0 END as target
            FROM predictions p
            INNER JOIN prediction_outcomes o ON p.id = o.prediction_id
            WHERE p.prop_type = ? AND p.line = ?
            ORDER BY p.game_date
        """

        df = pd.read_sql_query(query, conn, params=(prop_type, line))

        if len(df) == 0:
            return df
        
        # Parse features from JSON
        features_list = []
        for idx, row in df.iterrows():
            if row['features_json']:
                try:
                    features = json.loads(row['features_json'])
                    features['_idx'] = idx
                    features_list.append(features)
                except:
                    pass
        
        if not features_list:
            return pd.DataFrame()
        
        features_df = pd.DataFrame(features_list).set_index('_idx')
        
        # Merge features with main dataframe
        df = df.join(features_df)
        
        # Drop JSON column
        df = df.drop(columns=['features_json'])
        
        return df
    
    def _load_nba_data(self, conn, prop_type: str, line: float) -> pd.DataFrame:
        """Load NBA data (features stored as columns)"""
        
        query = """
            SELECT 
                p.id,
                p.game_date,
                p.player_name,
                p.team,
                p.opponent,
                p.prediction as model_prediction,
                p.probability as model_probability,
                p.f_season_success_rate,
                p.f_l20_success_rate,
                p.f_l10_success_rate,
                p.f_l5_success_rate,
                p.f_l3_success_rate,
                p.f_current_streak,
                p.f_max_streak,
                p.f_trend_slope,
                p.f_home_away_split,
                p.f_games_played,
                p.f_insufficient_data,
                p.f_season_avg,
                p.f_l10_avg,
                p.f_l5_avg,
                p.f_season_std,
                p.f_l10_std,
                p.f_trend_acceleration,
                p.f_avg_minutes,
                p.f_consistency_score,
                o.actual_value as actual_stat_value,
                o.outcome,
                -- CRITICAL: Train on actual outcome (OVER/UNDER), NOT prediction correctness (HIT/MISS)
                -- For NBA, derive actual_outcome from actual_value > line
                CASE WHEN o.actual_value > p.line THEN 'OVER' ELSE 'UNDER' END as actual_outcome,
                CASE WHEN o.actual_value > p.line THEN 1 ELSE 0 END as target
            FROM predictions p
            INNER JOIN prediction_outcomes o ON p.id = o.prediction_id
            WHERE p.prop_type = ? AND p.line = ?
            ORDER BY p.game_date
        """

        df = pd.read_sql_query(query, conn, params=(prop_type, line))
        return df
    
    def get_feature_columns(self, df: pd.DataFrame) -> List[str]:
        """Get list of feature columns for training"""
        
        # Exclude non-feature columns
        exclude_cols = {
            'id', 'game_date', 'player_name', 'team', 'opponent',
            'model_prediction', 'model_probability', 'actual_stat_value',
            'actual_outcome', 'outcome', 'target', 'features_json', 'prob_over'
        }
        
        feature_cols = [col for col in df.columns if col not in exclude_cols]
        
        # Remove any columns that are all NaN
        feature_cols = [col for col in feature_cols if df[col].notna().any()]
        
        return feature_cols


# ============================================================================
# MODEL TRAINING
# ============================================================================

class ModelTrainer:
    """Train and evaluate ML models"""
    
    def __init__(self, config: MLConfig = None):
        self.config = config or MLConfig()
        self.models = {}
        self.results = {}
        self.best_model = None
        self.scaler = StandardScaler()
    
    def prepare_data(self, df: pd.DataFrame, feature_cols: List[str]) -> Tuple:
        """
        Prepare data for training with a 4-way temporal split:
            Train (65%) → Val (15%) → Cal (10%) → Test (10%)

        Val is used ONLY for model selection (never seen by calibration).
        Cal is used ONLY for isotonic calibration (never seen by training).
        Test is the held-out final evaluation set.

        Returns:
            X_train, X_val, X_cal, X_test,
            y_train, y_val, y_cal, y_test,
            X_train_orig, X_val_orig, X_cal_orig, X_test_orig
        """
        # Sort by date to ensure temporal ordering
        df = df.sort_values('game_date').reset_index(drop=True)

        X = df[feature_cols].copy()
        y = df['target'].copy()

        # Fill NaN with median (conservative approach)
        X = X.fillna(X.median())

        # Temporal split: Train → Val → Cal → Test
        n = len(df)
        train_end = int(n * (1 - self.config.test_size - self.config.val_size - self.config.cal_size))
        val_end   = int(n * (1 - self.config.test_size - self.config.cal_size))
        cal_end   = int(n * (1 - self.config.test_size))

        X_train = X.iloc[:train_end]
        X_val   = X.iloc[train_end:val_end]
        X_cal   = X.iloc[val_end:cal_end]
        X_test  = X.iloc[cal_end:]

        y_train = y.iloc[:train_end]
        y_val   = y.iloc[train_end:val_end]
        y_cal   = y.iloc[val_end:cal_end]
        y_test  = y.iloc[cal_end:]

        # Scale features (fit ONLY on train — no leakage)
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled   = self.scaler.transform(X_val)
        X_cal_scaled   = self.scaler.transform(X_cal)
        X_test_scaled  = self.scaler.transform(X_test)

        return (
            X_train_scaled, X_val_scaled, X_cal_scaled, X_test_scaled,
            y_train.values, y_val.values, y_cal.values, y_test.values,
            X_train, X_val, X_cal, X_test  # Original DataFrames for feature importance
        )
    
    def train_all_models(
        self,
        X_train: np.ndarray,
        X_val: np.ndarray,
        X_cal: np.ndarray,
        y_train: np.ndarray,
        y_val: np.ndarray,
        y_cal: np.ndarray,
    ) -> Dict:
        """
        Train all configured models.

        Calibration pipeline (no data leakage):
          1. Fit base model on X_train
          2. Evaluate uncalibrated model on X_val → used for model selection only
          3. After best model is selected (in train_model()), calibrate on X_cal
          4. X_test is never seen until final evaluation
        """
        results = {}

        for model_name in self.config.models_to_train:
            print(f"\n{'='*60}")
            print(f"Training: {model_name}")
            print('='*60)

            model = self._get_model(model_name)

            # Train on training set only
            model.fit(X_train, y_train)

            # Evaluate UNCALIBRATED on val set — used purely for model selection ranking
            y_pred = model.predict(X_val)
            y_prob = model.predict_proba(X_val)[:, 1]
            metrics = self._calculate_metrics(y_val, y_pred, y_prob)

            results[model_name] = {
                'model': model,       # Raw uncalibrated model (calibration applied later)
                'metrics': metrics,
                'X_cal': X_cal,       # Pass through so caller can calibrate after selection
                'y_cal': y_cal,
            }

            self.models[model_name] = model

            # Print results
            print(f"\nValidation Results:")
            print(f"  Accuracy:    {metrics['accuracy']:.3f}")
            print(f"  Precision:   {metrics['precision']:.3f}")
            print(f"  Recall:      {metrics['recall']:.3f}")
            print(f"  F1 Score:    {metrics['f1']:.3f}")
            print(f"  ROC AUC:     {metrics['roc_auc']:.3f}")
            print(f"  Brier Score: {metrics['brier']:.4f}")
            print(f"  Log Loss:    {metrics['log_loss']:.4f}")

        self.results = results
        return results

    def calibrate_best_model(self, best_model_name: str) -> None:
        """
        Apply isotonic calibration to the selected best model using the
        dedicated calibration set (X_cal/y_cal stored in results).

        Must be called AFTER select_best_model() and BEFORE evaluate_on_test().
        """
        if not self.config.calibrate_probabilities:
            return

        result = self.results[best_model_name]
        X_cal = result['X_cal']
        y_cal = result['y_cal']
        base_model = self.models[best_model_name]

        calibrated = CalibratedClassifierCV(
            base_model,
            method=self.config.calibration_method,
            cv='prefit'
        )
        calibrated.fit(X_cal, y_cal)

        # Replace stored model with calibrated version
        self.models[best_model_name] = calibrated
        self.best_model = calibrated
        print(f"\n[CAL] Applied {self.config.calibration_method} calibration on "
              f"{len(y_cal):,} held-out samples")
    
    def _get_model(self, model_name: str):
        """Get model instance by name"""
        
        if model_name == 'logistic_regression':
            return LogisticRegression(
                max_iter=1000,
                class_weight='balanced',
                random_state=42
            )
        
        elif model_name == 'random_forest':
            return RandomForestClassifier(
                n_estimators=200,
                max_depth=10,
                min_samples_leaf=20,
                class_weight='balanced',
                random_state=42,
                n_jobs=-1
            )
        
        elif model_name == 'gradient_boosting':
            return GradientBoostingClassifier(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.05,
                min_samples_leaf=20,
                random_state=42
            )
        
        elif model_name == 'xgboost' and XGBOOST_AVAILABLE:
            return xgb.XGBClassifier(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.05,
                min_child_weight=20,
                scale_pos_weight=1,  # Adjust for imbalance
                random_state=42,
                use_label_encoder=False,
                eval_metric='logloss'
            )
        
        elif model_name == 'lightgbm' and LIGHTGBM_AVAILABLE:
            return lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.05,
                min_child_samples=20,
                class_weight='balanced',
                random_state=42,
                verbose=-1
            )
        
        else:
            raise ValueError(f"Unknown model: {model_name}")
    
    def _calculate_metrics(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_prob: np.ndarray
    ) -> Dict:
        """Calculate comprehensive metrics"""
        
        # Guard against single-class test sets (happens with highly skewed props)
        unique_labels = np.unique(y_true)
        if len(unique_labels) < 2:
            # Can't compute AUC or log_loss with one class — use accuracy-based fallback
            acc = accuracy_score(y_true, y_pred)
            return {
                'accuracy': acc,
                'precision': precision_score(y_true, y_pred, zero_division=0),
                'recall': recall_score(y_true, y_pred, zero_division=0),
                'f1': f1_score(y_true, y_pred, zero_division=0),
                'roc_auc': 0.5,         # undefined — use neutral
                'brier': 1 - acc,       # approximate
                'log_loss': 1 - acc     # approximate
            }

        return {
            'accuracy': accuracy_score(y_true, y_pred),
            'precision': precision_score(y_true, y_pred, zero_division=0),
            'recall': recall_score(y_true, y_pred, zero_division=0),
            'f1': f1_score(y_true, y_pred, zero_division=0),
            'roc_auc': roc_auc_score(y_true, y_prob),
            'brier': brier_score_loss(y_true, y_prob),
            'log_loss': log_loss(y_true, y_prob, labels=[0, 1])
        }
    
    def select_best_model(self, metric: str = 'brier') -> str:
        """Select best model based on metric (lower is better for brier/log_loss)"""
        
        if metric in ['brier', 'log_loss']:
            # Lower is better
            best_name = min(
                self.results.keys(),
                key=lambda k: self.results[k]['metrics'][metric]
            )
        else:
            # Higher is better
            best_name = max(
                self.results.keys(),
                key=lambda k: self.results[k]['metrics'][metric]
            )
        
        self.best_model = self.models[best_name]
        return best_name
    
    def evaluate_on_test(
        self,
        X_test: np.ndarray,
        y_test: np.ndarray,
        model_name: str = None
    ) -> Dict:
        """Final evaluation on held-out test set"""
        
        if model_name:
            model = self.models[model_name]
        else:
            model = self.best_model
        
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]
        
        metrics = self._calculate_metrics(y_test, y_pred, y_prob)
        
        print("\n" + "="*60)
        print("FINAL TEST SET RESULTS")
        print("="*60)
        print(f"\nModel: {model_name or 'best_model'}")
        print(f"\n{classification_report(y_test, y_pred)}")
        print(f"\nProbabilistic Metrics:")
        print(f"  ROC AUC:     {metrics['roc_auc']:.3f}")
        print(f"  Brier Score: {metrics['brier']:.4f}")
        print(f"  Log Loss:    {metrics['log_loss']:.4f}")
        
        return metrics
    
    def get_feature_importance(
        self,
        feature_names: List[str],
        model_name: str = None
    ) -> pd.DataFrame:
        """Get feature importance from tree-based models"""
        
        if model_name:
            model = self.models[model_name]
        else:
            model = self.best_model
        
        # Handle calibrated models
        if hasattr(model, 'estimator'):
            base_model = model.estimator
        elif hasattr(model, 'base_estimator'):
            base_model = model.base_estimator
        else:
            base_model = model
        
        if hasattr(base_model, 'feature_importances_'):
            importance = base_model.feature_importances_
        elif hasattr(base_model, 'coef_'):
            importance = np.abs(base_model.coef_[0])
        else:
            return pd.DataFrame()
        
        df = pd.DataFrame({
            'feature': feature_names,
            'importance': importance
        }).sort_values('importance', ascending=False)
        
        return df


# ============================================================================
# MODEL SAVING
# ============================================================================

def save_trained_model(
    trainer: ModelTrainer,
    sport: str,
    prop_type: str,
    line: float,
    feature_cols: List[str],
    test_metrics: Dict,
    baseline_metrics: Dict,
    samples: int,
    importance_df: pd.DataFrame,
    training_window_days: int = 90,
) -> Optional[str]:
    """
    Save trained model to registry.

    Args:
        trainer: ModelTrainer instance with trained models
        sport: 'nhl' or 'nba'
        prop_type: 'points', 'shots', etc.
        line: Betting line
        feature_cols: List of feature column names
        test_metrics: Test set metrics
        baseline_metrics: Statistical baseline metrics
        samples: Number of training samples
        importance_df: Feature importance DataFrame

    Returns:
        Version string of saved model, or None if saving failed
    """
    if not MODEL_SAVING_AVAILABLE:
        print("[WARN] Model saving not available - model_manager not found")
        return None

    best_model_name = trainer.select_best_model(metric='brier')
    best_model = trainer.models[best_model_name]
    scaler = trainer.scaler

    # Extract top features from importance DataFrame
    top_features = {}
    if len(importance_df) > 0:
        for _, row in importance_df.head(10).iterrows():
            top_features[row['feature']] = float(row['importance'])

    # Create metadata
    metadata = ModelMetadata(
        sport=sport.upper(),
        prop_type=prop_type,
        line=line,
        model_type=best_model_name,
        version='',  # Will be set by registry
        trained_at=datetime.now().isoformat(),
        training_samples=samples,
        feature_names=feature_cols,
        test_accuracy=test_metrics['accuracy'],
        test_roc_auc=test_metrics['roc_auc'],
        test_brier_score=test_metrics['brier'],
        test_log_loss=test_metrics['log_loss'],
        baseline_accuracy=baseline_metrics['accuracy'],
        improvement_over_baseline=test_metrics['accuracy'] - baseline_metrics['accuracy'],
        is_calibrated=trainer.config.calibrate_probabilities,
        calibration_method=trainer.config.calibration_method,
        training_window_days=training_window_days,
        top_features=top_features
    )

    # Save to registry
    registry = ModelRegistry()
    version = registry.save_model(
        model=best_model,
        scaler=scaler,
        metadata=metadata,
        sport=sport,
        prop_type=prop_type,
        line=line
    )

    print(f"\n[SAVED] Model saved as version: {version}")

    return version


# ============================================================================
# MAIN TRAINING FUNCTION
# ============================================================================

def train_model(
    sport: str,
    prop_type: str,
    line: float,
    db_path: str = None,
    config: MLConfig = None
) -> Dict:
    """
    Main function to train ML model for a specific prop/line
    
    Args:
        sport: 'nhl' or 'nba'
        prop_type: 'points', 'shots', 'rebounds', etc.
        line: The betting line
        db_path: Optional custom database path
        config: Optional ML configuration
        
    Returns:
        Dictionary with training results
    """
    config = config or MLConfig()
    
    print("\n" + "="*70)
    print(f"ML TRAINING: {sport.upper()} - {prop_type} O{line}")
    print("="*70)
    
    # Load data (apply rolling window from config)
    loader = DataLoader(sport, db_path)
    effective_window = config.training_window_days
    df = loader.load_training_data(prop_type, line,
                                   training_window_days=effective_window)

    # Auto-extend window if initial cut yields too few samples.
    # Tries up to 2 extensions (+30d each) before giving up.
    for _extension in range(1, 3):
        if len(df) >= config.min_samples or effective_window == 0:
            break
        extended_window = effective_window + 30 * _extension
        print(f"  [Window] {effective_window}d window: {len(df):,} samples "
              f"< {config.min_samples:,} min. Extending to {extended_window}d...")
        df = loader.load_training_data(prop_type, line,
                                       training_window_days=extended_window)
        effective_window = extended_window  # track for metadata

    if len(df) < config.min_samples:
        print(f"\n[WARN] Insufficient data: {len(df)} samples (need {config.min_samples})")
        return {'status': 'insufficient_data', 'samples': len(df)}
    
    print(f"\nLoaded {len(df):,} samples")
    print(f"Date range: {df['game_date'].min()} to {df['game_date'].max()}")
    print(f"Target distribution: {df['target'].mean():.1%} positive (HIT)")
    
    # Get features
    feature_cols = loader.get_feature_columns(df)
    print(f"Features: {len(feature_cols)}")
    
    # Prepare data
    trainer = ModelTrainer(config)
    (X_train, X_val, X_cal, X_test,
     y_train, y_val, y_cal, y_test,
     X_train_orig, X_val_orig, X_cal_orig, X_test_orig) = trainer.prepare_data(df, feature_cols)

    print(f"\nData split:")
    print(f"  Train: {len(X_train):,} samples")
    print(f"  Val:   {len(X_val):,} samples  (model selection only)")
    print(f"  Cal:   {len(X_cal):,} samples  (calibration only)")
    print(f"  Test:  {len(X_test):,} samples")

    # Train models (uncalibrated — calibration applied after model selection)
    results = trainer.train_all_models(X_train, X_val, X_cal, y_train, y_val, y_cal)

    # Select best model by val Brier score
    best_model_name = trainer.select_best_model(metric='brier')
    print(f"\n[BEST] Model: {best_model_name}")

    # Calibrate ONLY the selected best model on the dedicated cal set
    trainer.calibrate_best_model(best_model_name)

    # Evaluate calibrated model on test set
    test_metrics = trainer.evaluate_on_test(X_test, y_test, best_model_name)
    
    # Feature importance
    print("\n" + "="*60)
    print("TOP 10 FEATURES")
    print("="*60)
    importance_df = trainer.get_feature_importance(feature_cols, best_model_name)
    if len(importance_df) > 0:
        print(importance_df.head(10).to_string(index=False))
    
    # Compare to baseline (statistical model)
    print("\n" + "="*60)
    print("COMPARISON TO STATISTICAL BASELINE")
    print("="*60)
    
    # Statistical model's predictions are in model_prediction column
    # Test set starts after train+val+cal rows
    test_start = len(X_train) + len(X_val) + len(X_cal)
    baseline_pred = (df.iloc[test_start:]['model_prediction'] == 'OVER').astype(int).values
    baseline_prob = df.iloc[test_start:]['model_probability'].values
    
    baseline_metrics = trainer._calculate_metrics(y_test, baseline_pred, baseline_prob)
    
    print(f"\n{'Metric':<15} {'Statistical':<12} {'ML Model':<12} {'Delta':<10}")
    print("-"*50)
    for metric in ['accuracy', 'roc_auc', 'brier', 'log_loss']:
        baseline_val = baseline_metrics[metric]
        ml_val = test_metrics[metric]
        delta = ml_val - baseline_val
        
        # For brier/log_loss, negative delta is better
        if metric in ['brier', 'log_loss']:
            indicator = "[+]" if delta < 0 else "[-]"
        else:
            indicator = "[+]" if delta > 0 else "[-]"
        
        print(f"{metric:<15} {baseline_val:<12.4f} {ml_val:<12.4f} {delta:+.4f} {indicator}")

    # Save model to registry
    saved_version = None
    if config.save_models and MODEL_SAVING_AVAILABLE:
        saved_version = save_trained_model(
            trainer=trainer,
            sport=sport,
            prop_type=prop_type,
            line=line,
            feature_cols=feature_cols,
            test_metrics=test_metrics,
            baseline_metrics=baseline_metrics,
            samples=len(df),
            importance_df=importance_df,
            training_window_days=effective_window,
        )

    return {
        'status': 'success',
        'sport': sport,
        'prop_type': prop_type,
        'line': line,
        'samples': len(df),
        'best_model': best_model_name,
        'test_metrics': test_metrics,
        'baseline_metrics': baseline_metrics,
        'feature_importance': importance_df.to_dict() if len(importance_df) > 0 else {},
        'trainer': trainer,
        'saved_version': saved_version
    }


# ============================================================================
# CLI INTERFACE
# ============================================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='ML Training Pipeline for Sports Predictions'
    )
    parser.add_argument('--sport', choices=['nhl', 'nba'], required=True)
    parser.add_argument('--prop', type=str, help='Prop type (points, shots, rebounds, etc.)')
    parser.add_argument('--line', type=float, help='Betting line (e.g., 0.5, 2.5)')
    parser.add_argument('--all', action='store_true', help='Train all prop/line combos')
    parser.add_argument('--db', type=str, help='Custom database path')
    parser.add_argument('--window', type=int, default=None,
                        help='Override training_window_days for all props (0 = all history)')

    args = parser.parse_args()

    # ── Prop-specific window overrides (post-deadline degraded props use shorter window)
    # pra was most impacted by Feb-6 trade deadline.
    #   pra  60d = 8,899 samples  ✓ (above 3k min)
    #   stocks 60d = 1,406 samples ✗ (below 3k min) — keep stocks at 90d
    # All other NBA props default to 90 days.  NHL is stable — 90 days default.
    PROP_WINDOW_OVERRIDES = {
        'pra': 60,   # 8,899 post-Jan-24 samples — strong post-deadline signal
        # stocks: leave at default 90d (only 1,406 graded at 60d — below min_samples)
    }

    def _make_config(prop_type: str) -> MLConfig:
        if args.window is not None:
            # Explicit CLI override wins over everything
            return MLConfig(training_window_days=args.window)
        window = PROP_WINDOW_OVERRIDES.get(prop_type, 90)
        return MLConfig(training_window_days=window)

    if args.all:
        # Define all prop/line combinations
        if args.sport == 'nhl':
            combos = [
                ('points', 0.5), ('points', 1.5),
                ('shots', 1.5), ('shots', 2.5), ('shots', 3.5),
                # New lower-variance props — will train once 3k+ graded predictions exist
                ('hits', 0.5), ('hits', 1.5), ('hits', 2.5), ('hits', 3.5),
                ('blocked_shots', 0.5), ('blocked_shots', 1.5),
            ]
        else:  # nba
            combos = [
                ('points', 15.5), ('points', 20.5), ('points', 25.5),
                ('rebounds', 7.5), ('rebounds', 10.5),
                ('assists', 5.5), ('assists', 7.5),
                ('threes', 2.5), ('stocks', 2.5),
                ('pra', 30.5), ('pra', 35.5), ('pra', 40.5),
                ('minutes', 28.5), ('minutes', 32.5)
            ]

        results = []
        for prop_type, line in combos:
            result = train_model(args.sport, prop_type, line, args.db,
                                 config=_make_config(prop_type))
            results.append(result)

        # Summary
        print("\n" + "="*70)
        print("TRAINING SUMMARY")
        print("="*70)
        for r in results:
            if r['status'] == 'success':
                improvement = r['baseline_metrics']['brier'] - r['test_metrics']['brier']
                print(f"  {r['prop_type']} O{r['line']}: "
                      f"Brier {r['test_metrics']['brier']:.4f} "
                      f"(delta {improvement:+.4f})")
            else:
                print(f"  {r.get('prop_type', 'unknown')}: {r['status']}")

    elif args.prop and args.line:
        train_model(args.sport, args.prop, args.line, args.db,
                    config=_make_config(args.prop))
    
    else:
        parser.print_help()
        print("\nExample: python ml_training_pipeline.py --sport nhl --prop points --line 0.5")
