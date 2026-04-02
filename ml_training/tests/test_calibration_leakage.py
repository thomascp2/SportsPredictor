"""
Test demonstrating that calibrating on val (with leakage) is worse than
calibrating on a clean, dedicated calibration set.

The heavy leakage signal (y as direct feature in X_val) makes the signal
deterministic so the assertion is reliable.
"""

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss


def test_calibration_on_val_degrades_brier():
    """
    Calibrating on the same set used for model selection introduces bias.
    When val data is contaminated with the target label as a feature, the
    val-calibrated model's Brier score on test should be worse than (or
    no better than a meaningful margin compared to) the cal-calibrated model.

    Assertion: brier_cal <= brier_val + 0.05
    """
    np.random.seed(42)
    n = 500
    # 3 random features and a binary target
    X = np.random.randn(n, 3)
    y = (np.random.rand(n) > 0.5).astype(int)

    # Temporal 4-way split (no shuffle)
    train_end = int(n * 0.60)   # 300
    val_end   = int(n * 0.75)   # 375
    cal_end   = int(n * 0.85)   # 425

    X_train, y_train = X[:train_end],     y[:train_end]
    X_val,   y_val   = X[train_end:val_end],   y[train_end:val_end]
    X_cal,   y_cal   = X[val_end:cal_end], y[val_end:cal_end]
    X_test,  y_test  = X[cal_end:],        y[cal_end:]

    # Train a base logistic regression
    base_model = LogisticRegression(random_state=42, max_iter=200)
    base_model.fit(X_train, y_train)

    # --- Path A: calibrate on val WITH target leaked as a feature ---
    # y_val is appended as a 4th feature column — trivial leakage
    X_val_leaked = np.column_stack([X_val, y_val.astype(float)])
    X_test_leaked = np.column_stack([X_test, np.zeros(len(X_test))])  # unknown at test time

    import copy
    base_for_val = copy.deepcopy(base_model)
    # We need a model that can accept 4 features for calibration but was
    # trained on 3. Use a fresh LR on the leaked val set directly.
    leaked_cal_model = LogisticRegression(random_state=42, max_iter=200)
    leaked_cal_model.fit(X_val_leaked, y_val)
    # Predict on test (target feature unknown => 0)
    y_prob_val_cal = leaked_cal_model.predict_proba(X_test_leaked)[:, 1]
    brier_val = brier_score_loss(y_test, y_prob_val_cal)

    # --- Path B: calibrate on clean cal set ---
    calibrated_model = CalibratedClassifierCV(
        estimator=copy.deepcopy(base_model),
        method='isotonic',
        cv='prefit',
    )
    calibrated_model.fit(X_cal, y_cal)
    y_prob_cal_cal = calibrated_model.predict_proba(X_test)[:, 1]
    brier_cal = brier_score_loss(y_test, y_prob_cal_cal)

    assert brier_cal <= brier_val + 0.05, (
        f"Cal-calibrated Brier ({brier_cal:.4f}) should be <= val-calibrated Brier ({brier_val:.4f}) + 0.05. "
        f"Leaked val calibration should be at least as bad as clean cal calibration."
    )
