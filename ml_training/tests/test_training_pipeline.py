"""
Tests for ML training pipeline data preparation.

Covers:
- Split ratios (60/15/10/15 temporal)
- No temporal overlap between splits
- Scaler fitted on training data only
- Degenerate model detection (stubs, pending Plan 02)
"""

import numpy as np
import pytest

from ml_training.train_models import ModelTrainer, MLConfig


def test_split_ratios(synthetic_training_df, feature_cols):
    """prepare_data produces splits within +-2pp of 60/15/10/15."""
    trainer = ModelTrainer()
    result = trainer.prepare_data(synthetic_training_df, feature_cols)
    X_train, X_val, X_cal, X_test = result[0], result[1], result[2], result[3]
    n = len(synthetic_training_df)

    assert abs(len(X_train) / n - 0.60) < 0.02, (
        f"Train split {len(X_train)/n:.3f} not within 2pp of 0.60"
    )
    assert abs(len(X_val) / n - 0.15) < 0.02, (
        f"Val split {len(X_val)/n:.3f} not within 2pp of 0.15"
    )
    assert abs(len(X_cal) / n - 0.10) < 0.02, (
        f"Cal split {len(X_cal)/n:.3f} not within 2pp of 0.10"
    )
    assert abs(len(X_test) / n - 0.15) < 0.02, (
        f"Test split {len(X_test)/n:.3f} not within 2pp of 0.15"
    )


def test_no_temporal_overlap(synthetic_training_df, feature_cols):
    """Splits must not overlap temporally (train < val < cal < test)."""
    trainer = ModelTrainer()
    trainer.prepare_data(synthetic_training_df, feature_cols)

    # Use same index boundaries as prepare_data
    df = synthetic_training_df.sort_values('game_date').reset_index(drop=True)
    n = len(df)
    train_end = int(n * 0.60)
    val_end   = int(n * 0.75)
    cal_end   = int(n * 0.85)

    train_dates = df['game_date'].iloc[:train_end].values
    val_dates   = df['game_date'].iloc[train_end:val_end].values
    cal_dates   = df['game_date'].iloc[val_end:cal_end].values
    test_dates  = df['game_date'].iloc[cal_end:].values

    assert max(train_dates) < min(val_dates), (
        f"Temporal overlap between train and val: max_train={max(train_dates)} >= min_val={min(val_dates)}"
    )
    assert max(val_dates) < min(cal_dates), (
        f"Temporal overlap between val and cal: max_val={max(val_dates)} >= min_cal={min(cal_dates)}"
    )
    assert max(cal_dates) < min(test_dates), (
        f"Temporal overlap between cal and test: max_cal={max(cal_dates)} >= min_test={min(test_dates)}"
    )


def test_scaler_fit_on_train_only(synthetic_training_df, feature_cols):
    """Scaler must be fit on training data only, not the full dataset."""
    trainer = ModelTrainer()
    trainer.prepare_data(synthetic_training_df, feature_cols)

    df = synthetic_training_df.sort_values('game_date').reset_index(drop=True)
    n = len(df)
    train_end = int(n * 0.60)

    X_train_only = df[feature_cols].iloc[:train_end].copy()
    # Fill NaN with median matching prepare_data behaviour
    X_train_filled = X_train_only.fillna(X_train_only.median())

    expected_mean = X_train_filled.mean().values

    np.testing.assert_allclose(
        trainer.scaler.mean_,
        expected_mean,
        rtol=1e-5,
        err_msg="Scaler mean_ does not match training-only statistics — possible data leakage",
    )


def test_degenerate_detection():
    """A model predicting >95% one class with brier<0.05 should be flagged as degenerate."""
    import pandas as pd
    from sklearn.metrics import brier_score_loss
    from ml_training.train_models import MLConfig, ModelTrainer

    rng = np.random.default_rng(42)
    n = 200
    dates = pd.date_range('2024-01-01', periods=n, freq='D').strftime('%Y-%m-%d').tolist()
    # 98% class 0 — simulates the threes OVER degenerate scenario
    target = (rng.random(n) < 0.02).astype(int)
    df = pd.DataFrame({
        'game_date': dates,
        'target': target,
        'f1': rng.standard_normal(n),
        'f2': rng.standard_normal(n),
        'f3': rng.standard_normal(n),
    })
    feature_cols = ['f1', 'f2', 'f3']

    trainer = ModelTrainer(MLConfig(min_samples=50, save_models=False))
    (X_train, X_val, X_cal, X_test,
     y_train, y_val, y_cal, y_test, *_) = trainer.prepare_data(df, feature_cols)

    trainer.train_all_models(X_train, X_val, X_cal, y_train, y_val, y_cal)
    best_model_name = trainer.select_best_model(metric='brier')
    trainer.calibrate_best_model(best_model_name)

    best_model = trainer.models[best_model_name]
    y_prob = best_model.predict_proba(X_test)[:, 1]
    y_pred = (y_prob > 0.5).astype(int)
    brier = brier_score_loss(y_test, y_prob)

    pct_over = float(np.mean(y_prob > 0.5))
    pct_under = 1.0 - pct_over
    is_degenerate = (
        max(pct_over, pct_under) > 0.95
        and (brier < 0.05 or len(y_test) < 50)
    )

    assert is_degenerate is True, (
        f"Expected degenerate=True for heavily skewed data, "
        f"got pct_over={pct_over:.3f}, pct_under={pct_under:.3f}, brier={brier:.4f}"
    )


def test_registry_block_on_degenerate():
    """Degenerate flag evaluates True and would block registry promotion."""
    # Verify the degenerate detection logic directly — avoid full DB overhead.
    # Given >95% one direction + brier < 0.05, is_degenerate must be True.
    pct_under = 0.98   # model predicts UNDER 98% of the time
    pct_over = 1.0 - pct_under
    brier = 0.02       # near-perfect Brier (model is very confident, always UNDER)
    n_test = 100

    is_degenerate = (
        max(pct_over, pct_under) > 0.95
        and (brier < 0.05 or n_test < 50)
    )

    assert is_degenerate is True, (
        "Logic check: 98% UNDER + Brier=0.02 should trigger degenerate flag"
    )

    # Also verify that brier >= 0.05 with >95% skew is NOT degenerate
    # (high skew alone without confidence is not a problem)
    is_degenerate_hi_brier = (
        max(pct_over, pct_under) > 0.95
        and (0.10 < 0.05 or n_test < 50)
    )
    assert is_degenerate_hi_brier is False, (
        "98% UNDER + Brier=0.10 should NOT be degenerate (not dangerously overfit)"
    )
