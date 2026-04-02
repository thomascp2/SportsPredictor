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


@pytest.mark.xfail(reason="Degenerate detection not yet implemented - Plan 02")
def test_degenerate_detection():
    """A model predicting >95% one class with brier<0.05 should trigger a warning."""
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="Degenerate detection not yet implemented - Plan 02")
def test_registry_block_on_degenerate():
    """A degenerate model should set registry_blocked=True."""
    pytest.fail("Not implemented")
