"""
MLB ML Evaluation — terminal report on trained models.

Loads each saved model, runs it on the held-out test split,
and prints:
  1. Per-prop regression metrics (MAE, RMSE, baseline naive-mean MAE)
  2. Per-(prop, line) classification accuracy: did the regressor's
     point estimate correctly predict OVER/UNDER the line?
  3. Feature importance table

Usage:
    python -m ml.evaluate               # evaluate all trained models
    python -m ml.evaluate --prop hits   # one prop
    python -m ml.evaluate --lines       # show per-line accuracy only
"""

import argparse
import json
import pickle
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from ml.train import (
    DB_PATH,
    MODELS_DIR,
    PROP_CONFIG,
    HITTER_FEATURES,
    PITCHER_FEATURES,
    load_hitter_data,
    load_pitcher_data,
    temporal_split,
)

# Lines to evaluate per prop
PROP_LINES = {
    "hits":          [0.5, 1.5, 2.5],
    "total_bases":   [1.5, 2.5, 3.5],
    "home_runs":     [0.5, 1.5],
    "strikeouts":    [3.5, 4.5, 5.5, 6.5, 7.5],
    "walks":         [1.5, 2.5],
    "outs_recorded": [14.5, 17.5],
}


def load_model(prop: str):
    model_path = MODELS_DIR / f"{prop}.pkl"
    if not model_path.exists():
        return None
    with open(model_path, "rb") as f:
        return pickle.load(f)


def load_meta() -> dict:
    meta_path = MODELS_DIR / "metadata.json"
    if not meta_path.exists():
        return {}
    with open(meta_path) as f:
        return json.load(f)


def evaluate_prop(
    prop: str,
    hitter_df: pd.DataFrame,
    pitcher_df: pd.DataFrame,
    show_lines: bool = True,
) -> None:
    model = load_model(prop)
    if model is None:
        print(f"  {prop}: no model file found — run ml/train.py first")
        return

    target_col, features, starter_only = PROP_CONFIG[prop]
    df = pitcher_df if features == PITCHER_FEATURES else hitter_df

    if starter_only:
        df = df[df["outs_recorded"] >= 9].copy()

    cols_needed = features + [target_col, "date", "player_id"]
    df = df[cols_needed].dropna().sort_values("date")

    _, _, test = temporal_split(df)

    if len(test) < 10:
        print(f"  {prop}: test set too small ({len(test)} rows)")
        return

    X_test = test[features].values
    y_test  = test[target_col].values
    preds   = model.predict(X_test)
    preds   = np.clip(preds, 0, None)  # predictions can't be negative counts

    mae      = mean_absolute_error(y_test, preds)
    rmse     = mean_squared_error(y_test, preds) ** 0.5
    baseline = mean_absolute_error(y_test, np.full_like(y_test, float(y_test.mean())))

    print(f"\n{'='*60}")
    print(f"  {prop.upper()}  (n_test={len(test):,})")
    print(f"  MAE:      {mae:.4f}  (naive mean baseline: {baseline:.4f})")
    print(f"  RMSE:     {rmse:.4f}")
    print(f"  Improvement over baseline: {(baseline - mae) / baseline * 100:.1f}%")

    if show_lines:
        lines = PROP_LINES.get(prop, [])
        if lines:
            print(f"\n  {'Line':>6}  {'N_over':>7}  {'Over%':>6}  {'Acc':>6}  {'Note'}")
            print("  " + "-" * 48)
            for line in lines:
                actual_over = (y_test > line)
                pred_over   = (preds > line)
                n_over      = int(actual_over.sum())
                over_pct    = actual_over.mean() * 100
                acc         = (actual_over == pred_over).mean() * 100
                # naive accuracy = pick whichever class is more common
                naive_acc   = max(over_pct, 100 - over_pct)
                note = f"+{acc - naive_acc:.1f}% vs naive" if acc > naive_acc else f"{acc - naive_acc:.1f}% vs naive"
                print(f"  {line:>6.1f}  {n_over:>7,}  {over_pct:>5.1f}%  {acc:>5.1f}%  {note}")

    # Feature importance from metadata
    meta = load_meta().get(prop, {})
    fi = meta.get("feature_importance", {})
    if fi:
        print(f"\n  Feature importances:")
        for feat, score in fi.items():
            bar = "#" * int(score * 30)
            print(f"    {feat:25s} {score:.3f}  {bar}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate trained MLB prop models")
    parser.add_argument("--prop", default=None, help="Single prop to evaluate")
    parser.add_argument("--lines", action="store_true", help="Show per-line accuracy only (no feature importance)")
    args = parser.parse_args()

    props = [args.prop] if args.prop else list(PROP_CONFIG.keys())
    for p in props:
        if p not in PROP_CONFIG:
            print(f"Unknown prop '{p}'")
            sys.exit(1)

    # Check any model exists
    trained = [p for p in props if (MODELS_DIR / f"{p}.pkl").exists()]
    if not trained:
        print("No trained models found. Run: python -m ml.train")
        sys.exit(1)

    print(f"Loading data ...")
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    hitter_df = load_hitter_data(conn)
    pitcher_df = load_pitcher_data(conn)
    conn.close()

    for prop in props:
        evaluate_prop(prop, hitter_df, pitcher_df, show_lines=True)

    print(f"\n{'='*60}")
    print("Done.")


if __name__ == "__main__":
    main()
