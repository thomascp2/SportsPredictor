"""
Generate ML predictions for a given date and write them to the DuckDB
`ml_predictions` table.

Designed to run daily after the feature pipeline completes.

Usage:
    python -m ml.predict_to_db                    # use latest date in feature store
    python -m ml.predict_to_db --date 2026-04-13  # specific date
    python -m ml.predict_to_db --date 2026-04-13 --force  # overwrite existing rows

Safeguards applied before inference:
  1. Feature clipping — caps hitter/pitcher features to training-realistic bounds
     so small-sample 2026 outliers (e.g. xwoba=1.03 on 8 PA) don't extrapolate wildly.
  2. Starter-only filter — outs_recorded / strikeouts / walks are only predicted
     for pitchers whose historical avg outs/appearance >= 12 (starters).
     Relievers never appear on PrizePicks for these props anyway.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ml.train import DB_PATH, MODELS_DIR, PROP_CONFIG, HITTER_FEATURES, PITCHER_FEATURES
from ml.predict import HITTER_PROPS, PITCHER_PROPS, load_model, p_over, PROP_LINES
from feature_store.build_duckdb import get_connection, initialize_schema

MODEL_VERSION = "xgboost_v1"

# ---------------------------------------------------------------------------
# Feature clip bounds — keep inference inside the training distribution.
# Values are per-feature [min, max]. None means no clip on that side.
# Derived from 2024-2025 Statcast training data with a reasonable margin.
# ---------------------------------------------------------------------------
HITTER_CLIP = {
    "avg_ev":     (60.0, 105.0),
    "avg_la":     (-20.0, 50.0),
    "xwoba":      (0.0,   0.600),   # 0.600 = elite; 1.035 is impossible noise
    "ev_7d":      (60.0, 105.0),
    "xwoba_14d":  (0.0,   0.600),
}

PITCHER_CLIP = {
    "avg_velocity":        (78.0, 101.0),
    "whiff_rate":          (0.0,   0.65),
    "xwoba_allowed":       (0.0,   0.750),
    "velocity_trend_7d":   (78.0, 101.0),
    "park_adjusted_xwoba": (0.0,   0.750),
}

# Minimum average outs/appearance to be considered a starter.
STARTER_MIN_AVG_OUTS = 12.0
# Minimum appearances required before we trust the avg (small sample = exclude).
STARTER_MIN_APPEARANCES = 5


def _clip_features(df: pd.DataFrame, clip_map: dict) -> pd.DataFrame:
    """Clip feature columns to [min, max] bounds in-place."""
    df = df.copy()
    for col, (lo, hi) in clip_map.items():
        if col in df.columns:
            df[col] = df[col].clip(lower=lo, upper=hi)
    return df


def _get_starter_pitcher_ids(conn: duckdb.DuckDBPyConnection) -> set:
    """
    Return the set of pitcher_ids who qualify as starters based on their
    historical label data: avg outs/appearance >= 12 with >= 5 appearances.

    Relievers are excluded — they never appear on PrizePicks for
    outs_recorded / strikeouts / walks props.
    """
    rows = conn.execute(f"""
        SELECT player_id
        FROM pitcher_labels
        GROUP BY player_id
        HAVING COUNT(*) >= {STARTER_MIN_APPEARANCES}
           AND AVG(outs_recorded) >= {STARTER_MIN_AVG_OUTS}
    """).fetchall()
    return {r[0] for r in rows}


def _resolve_date(conn: duckdb.DuckDBPyConnection, date_str: str | None) -> str:
    if date_str:
        return date_str
    row = conn.execute("SELECT MAX(date) FROM player_features").fetchone()
    d = str(row[0])
    print(f"No --date specified, using latest in feature store: {d}")
    return d


def _fetch_hitter_features(conn: duckdb.DuckDBPyConnection, date: str) -> pd.DataFrame:
    df = conn.execute(f"""
        SELECT pf.player_id, p.player_name,
               pf.avg_ev, pf.avg_la, pf.xwoba, pf.ev_7d, pf.xwoba_14d
        FROM player_features pf
        LEFT JOIN players p ON pf.player_id = p.player_id
        WHERE pf.date = '{date}'
    """).fetchdf()
    return _clip_features(df, HITTER_CLIP)


def _fetch_pitcher_features(conn: duckdb.DuckDBPyConnection, date: str) -> pd.DataFrame:
    df = conn.execute(f"""
        SELECT pf.pitcher_id AS player_id, p.player_name,
               pf.avg_velocity, pf.whiff_rate, pf.xwoba_allowed,
               pf.velocity_trend_7d, pf.park_adjusted_xwoba
        FROM pitcher_features pf
        LEFT JOIN players p ON pf.pitcher_id = p.player_id
        WHERE pf.date = '{date}'
    """).fetchdf()
    return _clip_features(df, PITCHER_CLIP)


def _run_models(
    df: pd.DataFrame,
    props: list[str],
    starter_ids: set | None = None,
) -> list[dict]:
    """
    Run trained XGBoost models for each prop and return prediction rows.

    Args:
        df:          Feature DataFrame (hitter or pitcher).
        props:       List of prop names to predict.
        starter_ids: If provided, restrict pitcher-only props to these IDs.
    """
    rows = []
    for prop in props:
        model = load_model(prop)
        if model is None:
            continue
        _, features, starter_only = PROP_CONFIG[prop]
        sub = df[["player_id", "player_name"] + features].dropna(subset=features)

        # Starter-only filter: skip relievers for outs_recorded/strikeouts/walks
        if starter_only and starter_ids is not None:
            before = len(sub)
            sub = sub[sub["player_id"].isin(starter_ids)]
            filtered = before - len(sub)
            if filtered > 0:
                print(f"    [{prop}] filtered {filtered} relievers (avg outs < {STARTER_MIN_AVG_OUTS})")

        if sub.empty:
            continue

        preds = np.clip(model.predict(sub[features].values), 0, None)
        for (_, row), pred in zip(sub.iterrows(), preds):
            rows.append({
                "player_id":       row["player_id"],
                "player_name":     row.get("player_name"),
                "prop":            prop,
                "predicted_value": round(float(pred), 4),
            })
    return rows


def _latest_feature_date(conn: duckdb.DuckDBPyConnection) -> str:
    """Return the most recent date that has features in the store."""
    row = conn.execute("SELECT MAX(date) FROM player_features").fetchone()
    return str(row[0])


def predict_to_db(date_str: str | None = None, force: bool = False) -> int:
    """
    Generate predictions for `date_str` and upsert into ml_predictions.
    Returns number of rows written.
    """
    rw_conn = get_connection()
    initialize_schema(rw_conn)

    date = _resolve_date(rw_conn, date_str)

    # Check if already populated
    existing = rw_conn.execute(
        f"SELECT COUNT(*) FROM ml_predictions WHERE game_date = '{date}'"
    ).fetchone()[0]
    if existing > 0 and not force:
        print(f"  {date}: already has {existing} ML predictions — skipping (use --force to overwrite)")
        rw_conn.close()
        return existing

    hitter_df  = _fetch_hitter_features(rw_conn, date)
    pitcher_df = _fetch_pitcher_features(rw_conn, date)

    if hitter_df.empty and pitcher_df.empty:
        # Fall back to latest available features — common on game day before
        # Statcast data lands (usually 24hrs after games complete).
        latest = _latest_feature_date(rw_conn)
        if latest and latest != date:
            print(f"  {date}: no features — using latest available ({latest})")
            hitter_df  = _fetch_hitter_features(rw_conn, latest)
            pitcher_df = _fetch_pitcher_features(rw_conn, latest)
        if hitter_df.empty and pitcher_df.empty:
            print(f"  {date}: no features found — run backfill first")
            rw_conn.close()
            return 0

    # Build starter set once (used for all starter-only pitcher props)
    starter_ids = _get_starter_pitcher_ids(rw_conn)
    print(f"  Starter filter: {len(starter_ids)} qualified starters identified")

    rows = []
    rows += _run_models(hitter_df,  HITTER_PROPS)
    rows += _run_models(pitcher_df, PITCHER_PROPS, starter_ids=starter_ids)

    if not rows:
        print(f"  {date}: no predictions generated — models may be missing")
        rw_conn.close()
        return 0

    df = pd.DataFrame(rows)
    df["game_date"]     = date
    df["model_version"] = MODEL_VERSION
    df["created_at"]    = datetime.utcnow().isoformat()

    # Upsert
    if force and existing:
        rw_conn.execute(f"DELETE FROM ml_predictions WHERE game_date = '{date}'")

    rw_conn.execute("""
        INSERT INTO ml_predictions
            (player_id, player_name, game_date, prop, predicted_value, model_version, created_at)
        SELECT player_id, player_name, game_date, prop, predicted_value, model_version, created_at
        FROM df
        ON CONFLICT (player_id, game_date, prop) DO UPDATE SET
            player_name     = excluded.player_name,
            predicted_value = excluded.predicted_value,
            model_version   = excluded.model_version,
            created_at      = excluded.created_at
    """)

    n = len(df)
    hitter_count  = len(hitter_df)
    pitcher_count = len([r for r in rows if r["prop"] in PITCHER_PROPS]) // max(len(PITCHER_PROPS), 1)
    print(f"  {date}: wrote {n} ML predictions ({hitter_count} hitters, {len(starter_ids)} starters)")
    rw_conn.close()
    return n


def main():
    parser = argparse.ArgumentParser(description="Write ML predictions to DuckDB")
    parser.add_argument("--date",  default=None, help="Date YYYY-MM-DD (default: latest in feature store)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing rows")
    args = parser.parse_args()

    trained = [p for p in PROP_CONFIG if (MODELS_DIR / f"{p}.pkl").exists()]
    if not trained:
        print("No trained models found. Run: python -m ml.train")
        sys.exit(1)

    n = predict_to_db(args.date, args.force)
    if n == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
