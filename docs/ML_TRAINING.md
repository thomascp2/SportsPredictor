# ML Training System

## Overview

The ML training system trains machine learning models to predict OVER/UNDER outcomes for player props in NHL and NBA.

## Architecture

```
ml_training/
├── train_models.py          # Main training script
├── model_manager.py         # Model registry and persistence
├── production_predictor.py  # Production inference
└── model_registry/          # Saved models (gitignored)
    └── nhl/
        ├── points_0_5/
        ├── points_1_5/
        ├── shots_1_5/
        ├── shots_2_5/
        └── shots_3_5/
```

## Training

### Train All NHL Models
```bash
python ml_training/train_models.py --sport nhl --all
```

### Train Specific Prop/Line
```bash
python ml_training/train_models.py --sport nhl --prop points --line 0.5
```

## How It Works

### 1. Data Loading
- Loads graded predictions from database
- Joins predictions with outcomes
- **CRITICAL**: Target is `actual_outcome` (OVER/UNDER), NOT prediction correctness (HIT/MISS)

### 2. Feature Engineering
NHL features (18 total):
- Player stats: success_rate_season/l20/l10/l5/l3, current_streak, max_hot_streak, recent_momentum, games_played
- Game context: is_home, line, lambda_param
- Opponent defense: opp_points_allowed_l10/l5, opp_scoring_pct_allowed, opp_points_std, opp_defensive_trend

### 3. Model Training
Tests 4 algorithms:
- Logistic Regression
- Random Forest
- Gradient Boosting
- XGBoost

Selects best model based on ROC AUC with probability calibration.

### 4. Model Persistence
Models saved to `model_registry/{sport}/{prop}_{line}/v{YYYYMMDD}_{num}/`:
- `model.joblib` - Trained model
- `scaler.joblib` - Feature scaler
- `metadata.json` - Training info and metrics

## Production Usage

### HybridPredictionEngine
The prediction scripts use `HybridPredictionEngine` which:
1. Gets statistical prediction
2. Gets ML prediction (if model available)
3. Combines via weighted ensemble (default: 60% ML, 40% Statistical)

```python
from ml_training.production_predictor import ProductionPredictor

predictor = ProductionPredictor()
result = predictor.predict('nhl', 'points', 1.5, features)
# Returns: {'prediction': 'UNDER', 'probability': 0.85, ...}
```

## Important Notes

### Training Target Bug (Fixed Jan 2026)
The original training used HIT/MISS as target, which trained the model to predict "was our prediction correct?" instead of "will it be OVER?". 

**Fix**: Changed target from `o.outcome = 'HIT'` to `o.actual_outcome = 'OVER'`

### Class Imbalance
Some props have severe class imbalance:
- Points O1.5: Only 16% OVER (most players get 0-1 points)
- Shots O1.5: 58% OVER (most active players get 2+ shots)

Models handle this via calibration, but predictions should align with base rates.
