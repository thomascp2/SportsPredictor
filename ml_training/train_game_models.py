"""
Game-Level ML Training Pipeline
================================

Trains XGBoost, LightGBM, and Logistic Regression models for full-game
predictions: moneyline (who wins), spread (covers?), and totals (over/under).

Uses backfilled game_training_data table created by backfill_game_features.py.

Usage:
    python train_game_models.py --sport nhl --bet-type moneyline
    python train_game_models.py --sport nba --bet-type spread --line 5.5
    python train_game_models.py --sport nba --all
    python train_game_models.py --sport all --all
"""

import sqlite3
import json
import os
import sys
import argparse
import joblib
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import warnings
warnings.filterwarnings('ignore')

from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, roc_auc_score, brier_score_loss, log_loss,
    classification_report
)
from sklearn.calibration import CalibratedClassifierCV

try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Config ────────────────────────────────────────────────────────────────────

MIN_TRAINING_SAMPLES = 100  # Minimum games to attempt training
SPORT_DEFAULTS = {
    "nhl": {"total_line": 6.0, "spread_line": 1.5},
    "nba": {"total_line": 224.0, "spread_line": 5.5},
    "mlb": {"total_line": 9.0, "spread_line": 1.5},
}


# ── Data Loading ──────────────────────────────────────────────────────────────

def load_training_data(db_path: str, bet_type: str, line: float = None) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Load game training data and create labels for the specified bet type.

    Args:
        db_path: Path to sport database
        bet_type: 'moneyline', 'spread', or 'total'
        line: Spread or total line value (required for spread/total)

    Returns:
        (X features DataFrame, y labels Series)
    """
    conn = sqlite3.connect(db_path)

    rows = conn.execute("""
        SELECT game_date, home_team, away_team,
               home_win, margin, total, features_json
        FROM game_training_data
        ORDER BY game_date ASC
    """).fetchall()

    conn.close()

    if not rows:
        return pd.DataFrame(), pd.Series()

    # Parse features
    records = []
    labels = []

    for row in rows:
        game_date, home, away, home_win, margin, total_score, feat_json = row

        try:
            features = json.loads(feat_json)
        except (json.JSONDecodeError, TypeError):
            continue

        # Create label based on bet type
        if bet_type == "moneyline":
            label = home_win  # 1 = home wins
        elif bet_type == "spread":
            if line is None:
                continue
            # Home covers spread: margin > -spread
            # If spread = -5.5 (home favored by 5.5), home needs to win by 6+
            label = 1 if margin > (-line) else 0
        elif bet_type == "total":
            if line is None:
                continue
            label = 1 if total_score > line else 0  # 1 = over
        else:
            continue

        records.append(features)
        labels.append(label)

    if not records:
        return pd.DataFrame(), pd.Series()

    X = pd.DataFrame(records)
    y = pd.Series(labels, name="label")

    # Drop non-numeric columns and NaN-heavy columns
    X = X.select_dtypes(include=[np.number])
    X = X.dropna(axis=1, thresh=int(len(X) * 0.5))  # Drop cols with >50% NaN
    X = X.fillna(X.median())

    return X, y


# ── Model Training ────────────────────────────────────────────────────────────

def train_models(X: pd.DataFrame, y: pd.Series, sport: str, bet_type: str,
                 line: float = None) -> Dict:
    """
    Train multiple models and return the best one.

    Uses time-series split to respect temporal ordering.
    """
    n = len(X)
    if n < MIN_TRAINING_SAMPLES:
        print(f"  [SKIP] Only {n} samples (need {MIN_TRAINING_SAMPLES})")
        return {"success": False, "reason": f"insufficient data ({n} samples)"}

    # Time-series split: train on first 70%, calibrate on 15%, test on last 15%
    train_end = int(n * 0.70)
    cal_end = int(n * 0.85)

    X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
    X_cal, y_cal = X.iloc[train_end:cal_end], y.iloc[train_end:cal_end]
    X_test, y_test = X.iloc[cal_end:], y.iloc[cal_end:]

    print(f"  Train: {len(X_train)}, Calibrate: {len(X_cal)}, Test: {len(X_test)}")
    print(f"  Positive rate: {y.mean():.1%} (train), {y_test.mean():.1%} (test)")

    # Scale features
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_cal_s = scaler.transform(X_cal)
    X_test_s = scaler.transform(X_test)

    # Train models
    models = {}

    # 1. Logistic Regression (baseline)
    try:
        lr = LogisticRegression(max_iter=1000, C=1.0, random_state=42)
        lr.fit(X_train_s, y_train)
        models["logistic_regression"] = lr
    except Exception as e:
        print(f"  [WARN] LogReg failed: {e}")

    # 2. XGBoost
    if XGBOOST_AVAILABLE:
        try:
            xgb_model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=1.0,
                reg_lambda=1.0,
                random_state=42,
                eval_metric="logloss",
                verbosity=0,
            )
            xgb_model.fit(X_train_s, y_train)
            models["xgboost"] = xgb_model
        except Exception as e:
            print(f"  [WARN] XGBoost failed: {e}")

    # 3. LightGBM
    if LIGHTGBM_AVAILABLE:
        try:
            lgb_model = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=1.0,
                reg_lambda=1.0,
                random_state=42,
                verbose=-1,
            )
            lgb_model.fit(X_train_s, y_train)
            models["lightgbm"] = lgb_model
        except Exception as e:
            print(f"  [WARN] LightGBM failed: {e}")

    if not models:
        return {"success": False, "reason": "no models trained successfully"}

    # ── Evaluate all models ───────────────────────────────────────────────
    results = {}
    best_model_name = None
    best_brier = 1.0

    for name, model in models.items():
        y_pred = model.predict(X_test_s)
        y_prob = model.predict_proba(X_test_s)[:, 1]

        acc = accuracy_score(y_test, y_pred)
        try:
            auc = roc_auc_score(y_test, y_prob)
        except ValueError:
            auc = 0.5
        brier = brier_score_loss(y_test, y_prob)

        results[name] = {
            "accuracy": round(acc, 4),
            "roc_auc": round(auc, 4),
            "brier_score": round(brier, 4),
        }
        print(f"  {name:<25} acc={acc:.1%}  auc={auc:.3f}  brier={brier:.4f}")

        if brier < best_brier:
            best_brier = brier
            best_model_name = name

    print(f"  ** Best model: {best_model_name} (Brier={best_brier:.4f})")

    # ── Calibrate best model ──────────────────────────────────────────────
    best_model = models[best_model_name]

    try:
        calibrated = CalibratedClassifierCV(
            best_model, method="isotonic", cv="prefit"
        )
        calibrated.fit(X_cal_s, y_cal)

        # Re-evaluate calibrated model
        y_cal_prob = calibrated.predict_proba(X_test_s)[:, 1]
        cal_brier = brier_score_loss(y_test, y_cal_prob)
        cal_acc = accuracy_score(y_test, calibrated.predict(X_test_s))
        print(f"  Calibrated {best_model_name}: acc={cal_acc:.1%}  brier={cal_brier:.4f}")

        final_model = calibrated
        final_brier = cal_brier
    except Exception as e:
        print(f"  [WARN] Calibration failed: {e}. Using uncalibrated model.")
        final_model = best_model
        final_brier = best_brier

    # ── Save model ────────────────────────────────────────────────────────
    model_dir = os.path.join(PROJECT_ROOT, "ml_training", "model_registry",
                              f"{sport}_games", bet_type)
    os.makedirs(model_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    line_str = f"_{line}" if line else ""
    model_file = os.path.join(model_dir, f"model{line_str}_{timestamp}.joblib")
    scaler_file = os.path.join(model_dir, f"scaler{line_str}_{timestamp}.joblib")
    meta_file = os.path.join(model_dir, f"metadata{line_str}_{timestamp}.json")

    joblib.dump(final_model, model_file)
    joblib.dump(scaler, scaler_file)

    # Feature importance (if available)
    top_features = {}
    if hasattr(best_model, "feature_importances_"):
        importances = best_model.feature_importances_
        feat_names = X.columns.tolist()
        sorted_idx = np.argsort(importances)[::-1][:15]
        top_features = {feat_names[i]: round(float(importances[i]), 4)
                       for i in sorted_idx if importances[i] > 0.01}

    metadata = {
        "sport": sport,
        "bet_type": bet_type,
        "line": line,
        "model_type": best_model_name,
        "trained_at": datetime.now().isoformat(),
        "training_samples": len(X_train),
        "test_samples": len(X_test),
        "feature_names": X.columns.tolist(),
        "feature_count": len(X.columns),
        "results": results,
        "best_model": best_model_name,
        "test_accuracy": results[best_model_name]["accuracy"],
        "test_roc_auc": results[best_model_name]["roc_auc"],
        "test_brier_score": final_brier,
        "calibrated": True,
        "top_features": top_features,
        "model_file": os.path.basename(model_file),
        "scaler_file": os.path.basename(scaler_file),
    }

    with open(meta_file, "w") as f:
        json.dump(metadata, f, indent=2)

    # Update latest pointer
    latest_file = os.path.join(model_dir, f"latest{line_str}.txt")
    with open(latest_file, "w") as f:
        f.write(timestamp)

    print(f"  Saved to: {model_dir}")

    return {
        "success": True,
        "best_model": best_model_name,
        "accuracy": results[best_model_name]["accuracy"],
        "brier_score": final_brier,
        "training_samples": len(X_train),
        "top_features": top_features,
        "model_file": model_file,
    }


# ── Train all bet types for a sport ──────────────────────────────────────────

def train_all_for_sport(sport: str) -> Dict:
    """Train models for all bet types for a sport."""
    db_map = {
        "nhl": os.path.join(PROJECT_ROOT, "nhl", "database", "nhl_predictions_v2.db"),
        "nba": os.path.join(PROJECT_ROOT, "nba", "database", "nba_predictions.db"),
        "mlb": os.path.join(PROJECT_ROOT, "mlb", "database", "mlb_predictions.db"),
    }

    db_path = db_map.get(sport)
    if not db_path or not os.path.exists(db_path):
        print(f"[TRAIN] Database not found for {sport}")
        return {}

    defaults = SPORT_DEFAULTS.get(sport, {})
    all_results = {}

    # Moneyline
    print(f"\n--- {sport.upper()} Moneyline ---")
    X, y = load_training_data(db_path, "moneyline")
    if len(X) >= MIN_TRAINING_SAMPLES:
        all_results["moneyline"] = train_models(X, y, sport, "moneyline")
    else:
        print(f"  [SKIP] Only {len(X)} samples for moneyline")

    # Spread (use default line)
    spread_line = defaults.get("spread_line", 1.5)
    print(f"\n--- {sport.upper()} Spread ({spread_line}) ---")
    X, y = load_training_data(db_path, "spread", line=spread_line)
    if len(X) >= MIN_TRAINING_SAMPLES:
        all_results[f"spread_{spread_line}"] = train_models(X, y, sport, "spread", line=spread_line)
    else:
        print(f"  [SKIP] Only {len(X)} samples for spread")

    # Total (use default line)
    total_line = defaults.get("total_line", 6.0)
    print(f"\n--- {sport.upper()} Total ({total_line}) ---")
    X, y = load_training_data(db_path, "total", line=total_line)
    if len(X) >= MIN_TRAINING_SAMPLES:
        all_results[f"total_{total_line}"] = train_models(X, y, sport, "total", line=total_line)
    else:
        print(f"  [SKIP] Only {len(X)} samples for total")

    return all_results


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Game-Level ML Models")
    parser.add_argument("--sport", choices=["nhl", "nba", "mlb", "all"], required=True)
    parser.add_argument("--bet-type", choices=["moneyline", "spread", "total"])
    parser.add_argument("--line", type=float, help="Spread or total line value")
    parser.add_argument("--all", action="store_true", help="Train all bet types")
    args = parser.parse_args()

    sports = ["nhl", "nba", "mlb"] if args.sport == "all" else [args.sport]

    for sport in sports:
        print(f"\n{'='*60}")
        print(f"  Training {sport.upper()} Game Prediction Models")
        print(f"{'='*60}")

        if args.all or (not args.bet_type):
            results = train_all_for_sport(sport)
            print(f"\n  Summary: {sum(1 for r in results.values() if r.get('success'))}/"
                  f"{len(results)} models trained successfully")
        else:
            db_map = {
                "nhl": os.path.join(PROJECT_ROOT, "nhl", "database", "nhl_predictions_v2.db"),
                "nba": os.path.join(PROJECT_ROOT, "nba", "database", "nba_predictions.db"),
                "mlb": os.path.join(PROJECT_ROOT, "mlb", "database", "mlb_predictions.db"),
            }
            X, y = load_training_data(db_map[sport], args.bet_type, args.line)
            if len(X) >= MIN_TRAINING_SAMPLES:
                train_models(X, y, sport, args.bet_type, args.line)
            else:
                print(f"  Only {len(X)} samples — need {MIN_TRAINING_SAMPLES}")
