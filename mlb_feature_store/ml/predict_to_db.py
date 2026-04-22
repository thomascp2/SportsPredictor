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
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ml.train import DB_PATH, MODELS_DIR, PROP_CONFIG, HITTER_FEATURES, PITCHER_FEATURES
from ml.predict import HITTER_PROPS, PITCHER_PROPS, load_model, p_over, PROP_LINES
from feature_store.build_duckdb import get_connection, initialize_schema

MODEL_VERSION = "xgboost_v1"

_STAT_DB = Path(__file__).resolve().parents[2] / "mlb" / "database" / "mlb_predictions.db"


def _norm_name(name: str) -> str:
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", str(name))
    return "".join(c for c in n if not unicodedata.combining(c)).lower().strip()


def _load_stat_pitchers(date: str) -> dict[str, str]:
    """Return {normalized_name: canonical_name} for pitchers in the stat model for date."""
    if not _STAT_DB.exists():
        print(f"  Warning: stat model DB not found at {_STAT_DB}")
        return {}
    try:
        con = sqlite3.connect(str(_STAT_DB))
        rows = con.execute(
            "SELECT DISTINCT player_name FROM predictions "
            "WHERE game_date = ? AND prop_type IN ('strikeouts','outs_recorded','pitcher_walks')",
            (date,)
        ).fetchall()
        con.close()
        return {_norm_name(r[0]): r[0] for r in rows}
    except Exception as e:
        print(f"  Warning: could not load stat model pitchers: {e}")
        return {}


def _load_alias_table(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Return {fs_name: canonical_name} from the persistent name_aliases table."""
    rows = conn.execute("SELECT fs_name, canonical_name FROM name_aliases").fetchall()
    return {r[0]: r[1] for r in rows}


def _update_alias_table(
    conn: duckdb.DuckDBPyConnection,
    fs_names: list[str],
    stat_norm_map: dict[str, str],
    existing: dict[str, str],
) -> dict[str, str]:
    """
    Fuzzy-match any fs_names not yet in the alias table against stat_norm_map,
    persist new matches, and return the updated full alias dict.
    """
    new_rows = []
    for fs_name in fs_names:
        if fs_name in existing:
            continue
        norm = _norm_name(fs_name)
        canonical = stat_norm_map.get(norm)
        if canonical:
            new_rows.append((fs_name, canonical))
            existing[fs_name] = canonical

    if new_rows:
        alias_df = pd.DataFrame(new_rows, columns=["fs_name", "canonical_name"])
        conn.execute("""
            INSERT INTO name_aliases (fs_name, canonical_name)
            SELECT fs_name, canonical_name FROM alias_df
            ON CONFLICT (fs_name) DO NOTHING
        """)
        print(f"  Name aliases: added {len(new_rows)} new mappings")

    return existing

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


def _fetch_pitcher_features_for_starters(
    conn: duckdb.DuckDBPyConnection,
    stat_norm_map: dict[str, str],
    lookback_days: int = 30,
) -> pd.DataFrame:
    """
    Fetch the most recent features for each pitcher who appears in today's stat model
    starter list, using up to `lookback_days` of history. This decouples the feature
    date from the prediction date so pitchers who last started 1-2 weeks ago still
    get predictions.
    """
    from datetime import date as _date, timedelta
    cutoff = (_date.today() - timedelta(days=lookback_days)).isoformat()
    df = conn.execute(f"""
        SELECT DISTINCT ON (pf.pitcher_id)
               pf.pitcher_id AS player_id, p.player_name,
               pf.avg_velocity, pf.whiff_rate, pf.xwoba_allowed,
               pf.velocity_trend_7d, pf.park_adjusted_xwoba
        FROM pitcher_features pf
        LEFT JOIN players p ON pf.pitcher_id = p.player_id
        WHERE pf.date >= '{cutoff}'
        ORDER BY pf.pitcher_id, pf.date DESC
    """).fetchdf()
    if df.empty:
        return df
    # Keep only pitchers that fuzzy-match today's starters
    df["_norm"] = df["player_name"].apply(_norm_name)
    df = df[df["_norm"].isin(stat_norm_map)].drop(columns=["_norm"])
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
    if hitter_df.empty:
        latest = _latest_feature_date(rw_conn)
        if latest and latest != date:
            print(f"  {date}: no hitter features — using latest available ({latest})")
            hitter_df = _fetch_hitter_features(rw_conn, latest)
        if hitter_df.empty:
            print(f"  {date}: no hitter features found — run backfill first")
            rw_conn.close()
            return 0

    # Pitchers: load today's starters from stat model, then fetch their most
    # recent features from the feature store (up to 30 days back). This handles
    # the case where a starter last pitched 5-10 days ago and has no entry for today.
    stat_pitchers = _load_stat_pitchers(date)
    if stat_pitchers:
        pitcher_df = _fetch_pitcher_features_for_starters(rw_conn, stat_pitchers)
        print(f"  Pitcher features: {len(pitcher_df)} starters matched from feature store")
    else:
        print(f"  Warning: no stat model pitchers for {date} — falling back to date-locked pitcher features")
        pitcher_df = _fetch_pitcher_features(rw_conn, date)
        if pitcher_df.empty:
            latest = _latest_feature_date(rw_conn)
            if latest and latest != date:
                pitcher_df = _fetch_pitcher_features(rw_conn, latest)

    # Build starter set (historical filter for reliever exclusion — belt-and-suspenders)
    starter_ids = _get_starter_pitcher_ids(rw_conn)
    print(f"  Historical starter filter: {len(starter_ids)} qualified starters")

    rows = []
    rows += _run_models(hitter_df,  HITTER_PROPS)
    rows += _run_models(pitcher_df, PITCHER_PROPS, starter_ids=starter_ids)

    # ── Pitcher name resolution via alias lookup table ────────────────────
    # pitcher_df was already filtered to today's starters, but the player_name
    # in the feature store may differ from the stat model canonical name.
    # Build/update the alias table and apply canonical names so the dashboard join works.
    if stat_pitchers and not pitcher_df.empty:
        alias_map = _load_alias_table(rw_conn)
        fs_pitcher_names = list(pitcher_df["player_name"].dropna().unique())
        alias_map = _update_alias_table(rw_conn, fs_pitcher_names, stat_pitchers, alias_map)

        resolved, skipped = [], 0
        for r in rows:
            if r["prop"] not in PITCHER_PROPS:
                resolved.append(r)
                continue
            canonical = alias_map.get(r.get("player_name", ""))
            if canonical:
                resolved.append({**r, "player_name": canonical})
            else:
                skipped += 1
        rows = resolved
        if skipped:
            print(f"  Name alias: {skipped} pitcher rows still unmatched after alias lookup")

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
