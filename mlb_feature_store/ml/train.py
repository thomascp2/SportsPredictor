"""
MLB ML Training — XGBoost Regression per prop.

Trains one regressor per prop (predict actual value; apply any line threshold at runtime).

Usage:
    python -m ml.train               # train all 6 props
    python -m ml.train --prop hits   # train one prop
    python -m ml.train --list        # show available props

Saves:
    ml/models/{prop}.pkl          XGBoost regressor
    ml/models/metadata.json       per-model metrics + feature list
"""

import argparse
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent.parent / "data" / "mlb.duckdb"
MODELS_DIR = Path(__file__).parent / "models"

HITTER_FEATURES = ["avg_ev", "avg_la", "xwoba", "ev_7d", "xwoba_14d"]

PITCHER_FEATURES = [
    "avg_velocity",
    "whiff_rate",
    "xwoba_allowed",
    "velocity_trend_7d",
    "park_adjusted_xwoba",
]

# prop -> (target_col, feature_set, starter_only)
PROP_CONFIG = {
    "hits":           ("hits",          HITTER_FEATURES,  False),
    "total_bases":    ("total_bases",   HITTER_FEATURES,  False),
    "home_runs":      ("home_runs",     HITTER_FEATURES,  False),
    "strikeouts":     ("strikeouts",    PITCHER_FEATURES, True),
    "walks":          ("walks",         PITCHER_FEATURES, True),
    "outs_recorded":  ("outs_recorded", PITCHER_FEATURES, True),
}

# Temporal split fractions
TRAIN_FRAC = 0.70
VAL_FRAC   = 0.15
# remaining 0.15 -> test (not used in train.py; evaluate.py uses it)

XGB_PARAMS = {
    "n_estimators":     500,
    "learning_rate":    0.05,
    "max_depth":        5,
    "min_child_weight": 3,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "reg_alpha":        0.1,
    "reg_lambda":       1.0,
    "random_state":     42,
    "n_jobs":           -1,
    "early_stopping_rounds": 30,
    "eval_metric":      "mae",
    "verbosity":        0,
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_hitter_data(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Join player_features with hitter_labels on (player_id, date)."""
    query = """
        SELECT
            pf.player_id,
            pf.date,
            pf.avg_ev,
            pf.avg_la,
            pf.xwoba,
            pf.ev_7d,
            pf.xwoba_14d,
            hl.hits,
            hl.total_bases,
            hl.home_runs
        FROM player_features pf
        JOIN hitter_labels hl
            ON pf.player_id = hl.player_id
           AND pf.date = hl.game_date
        ORDER BY pf.date
    """
    df = conn.execute(query).fetchdf()
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_pitcher_data(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Join pitcher_features with pitcher_labels (starter filter applied later)."""
    query = """
        SELECT
            pf.pitcher_id  AS player_id,
            pf.date,
            pf.avg_velocity,
            pf.whiff_rate,
            pf.xwoba_allowed,
            pf.velocity_trend_7d,
            pf.park_adjusted_xwoba,
            pl.strikeouts,
            pl.walks,
            pl.outs_recorded
        FROM pitcher_features pf
        JOIN pitcher_labels pl
            ON pf.pitcher_id = pl.player_id
           AND pf.date = pl.game_date
        ORDER BY pf.date
    """
    df = conn.execute(query).fetchdf()
    df["date"] = pd.to_datetime(df["date"])
    return df


# ---------------------------------------------------------------------------
# Temporal split
# ---------------------------------------------------------------------------

def temporal_split(
    df: pd.DataFrame,
    train_frac: float = TRAIN_FRAC,
    val_frac: float = VAL_FRAC,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split df by date order: train / val / test."""
    df = df.sort_values("date").reset_index(drop=True)
    n = len(df)
    n_train = int(n * train_frac)
    n_val   = int(n * val_frac)
    train = df.iloc[:n_train]
    val   = df.iloc[n_train : n_train + n_val]
    test  = df.iloc[n_train + n_val :]
    return train, val, test


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_prop(
    prop: str,
    hitter_df: pd.DataFrame,
    pitcher_df: pd.DataFrame,
    verbose: bool = True,
) -> dict:
    """Train a single XGBoost regressor for one prop. Returns metadata dict."""
    target_col, features, starter_only = PROP_CONFIG[prop]

    df = pitcher_df if features == PITCHER_FEATURES else hitter_df

    if starter_only:
        df = df[df["outs_recorded"] >= 9].copy()

    # Drop rows missing any feature or the target
    cols_needed = features + [target_col, "date", "player_id"]
    df = df[cols_needed].dropna()

    if len(df) < 500:
        print(f"  [SKIP] {prop}: only {len(df)} clean rows after dropna — insufficient data")
        return {}

    train, val, test = temporal_split(df)

    X_train = train[features].values
    y_train = train[target_col].values
    X_val   = val[features].values
    y_val   = val[target_col].values
    X_test  = test[features].values
    y_test  = test[target_col].values

    model = xgb.XGBRegressor(**XGB_PARAMS)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    # Metrics on val and test
    pred_val  = model.predict(X_val)
    pred_test = model.predict(X_test)

    mae_val  = mean_absolute_error(y_val, pred_val)
    rmse_val = mean_squared_error(y_val, pred_val) ** 0.5
    mae_test  = mean_absolute_error(y_test, pred_test)
    rmse_test = mean_squared_error(y_test, pred_test) ** 0.5

    # Feature importances
    fi = dict(zip(features, model.feature_importances_.tolist()))
    fi_sorted = dict(sorted(fi.items(), key=lambda x: x[1], reverse=True))

    metadata = {
        "prop":         prop,
        "target":       target_col,
        "features":     features,
        "starter_only": starter_only,
        "n_train":      int(len(train)),
        "n_val":        int(len(val)),
        "n_test":       int(len(test)),
        "date_range":   [str(df["date"].min().date()), str(df["date"].max().date())],
        "train_end":    str(train["date"].max().date()),
        "val_end":      str(val["date"].max().date()),
        "val_mae":      round(float(mae_val), 4),
        "val_rmse":     round(float(rmse_val), 4),
        "test_mae":     round(float(mae_test), 4),
        "test_rmse":    round(float(rmse_test), 4),
        "best_iteration": int(model.best_iteration) if hasattr(model, "best_iteration") and model.best_iteration else XGB_PARAMS["n_estimators"],
        "feature_importance": fi_sorted,
        "trained_at":   datetime.utcnow().isoformat(),
    }

    # Save model
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{prop}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    if verbose:
        print(f"  {prop:15s}  n={len(df):,}  val_mae={mae_val:.3f}  test_mae={mae_test:.3f}  "
              f"test_rmse={rmse_test:.3f}  trees={metadata['best_iteration']}")
        top_feat = list(fi_sorted.keys())[0]
        print(f"    top feature: {top_feat} ({fi_sorted[top_feat]:.3f})")

    return metadata


# ---------------------------------------------------------------------------
# Metadata persistence
# ---------------------------------------------------------------------------

def load_metadata() -> dict:
    meta_path = MODELS_DIR / "metadata.json"
    if meta_path.exists():
        with open(meta_path) as f:
            return json.load(f)
    return {}


def save_metadata(all_meta: dict) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = MODELS_DIR / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(all_meta, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train MLB prop regression models")
    parser.add_argument("--prop", default=None, help="Single prop to train (default: all)")
    parser.add_argument("--list", action="store_true", help="List available props and exit")
    args = parser.parse_args()

    if args.list:
        print("Available props:")
        for p, (tgt, feats, starter) in PROP_CONFIG.items():
            tag = " [starters only]" if starter else ""
            print(f"  {p:15s}  target={tgt}  features={len(feats)}{tag}")
        sys.exit(0)

    props_to_train = [args.prop] if args.prop else list(PROP_CONFIG.keys())
    for p in props_to_train:
        if p not in PROP_CONFIG:
            print(f"Unknown prop '{p}'. Use --list to see options.")
            sys.exit(1)

    print(f"Loading data from {DB_PATH} ...")
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    hitter_df = load_hitter_data(conn)
    pitcher_df = load_pitcher_data(conn)
    conn.close()
    print(f"  hitters: {len(hitter_df):,} rows | pitchers: {len(pitcher_df):,} rows")

    print(f"\nTraining {len(props_to_train)} model(s) ...")
    print(f"  {'prop':<15}  {'n':>7}  {'val_mae':>8}  {'test_mae':>9}  {'test_rmse':>10}  {'trees':>6}")
    print("  " + "-" * 65)

    all_meta = load_metadata()
    for prop in props_to_train:
        meta = train_prop(prop, hitter_df, pitcher_df, verbose=True)
        if meta:
            all_meta[prop] = meta

    save_metadata(all_meta)
    print(f"\nModels saved to {MODELS_DIR}/")
    print(f"Metadata saved to {MODELS_DIR}/metadata.json")


if __name__ == "__main__":
    main()
