"""
MLB ML Prediction — terminal output for a given date.

For each player with features available on the target date, runs all
trained regression models and prints predicted values + P(OVER) for
each standard line using the Poisson distribution (count-based props).

Usage:
    # Show predictions for a specific date (uses all players with features)
    python -m ml.predict --date 2025-09-01

    # Filter to specific players by MLB player_id
    python -m ml.predict --date 2025-09-01 --players 660271 592789

    # Pitcher predictions only
    python -m ml.predict --date 2025-09-01 --type pitcher

    # Hitter predictions only
    python -m ml.predict --date 2025-09-01 --type hitter

    # Top N predictions per prop (by P(OVER) distance from 50%)
    python -m ml.predict --date 2025-09-01 --top 10

Notes:
    - Date must exist in the feature store. For future dates, the most
      recent available features per player are used (--latest flag).
    - Poisson P(OVER line) = 1 - poisson.cdf(floor(line), mu=predicted_value)
"""

import argparse
import pickle
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import poisson

from ml.train import DB_PATH, MODELS_DIR, PROP_CONFIG, HITTER_FEATURES, PITCHER_FEATURES

# Lines to show per prop (same as evaluate.py)
PROP_LINES = {
    "hits":          [0.5, 1.5, 2.5],
    "total_bases":   [1.5, 2.5, 3.5],
    "home_runs":     [0.5, 1.5],
    "strikeouts":    [3.5, 4.5, 5.5, 6.5, 7.5],
    "walks":         [1.5, 2.5],
    "outs_recorded": [14.5, 17.5],
}

HITTER_PROPS  = ["hits", "total_bases", "home_runs"]
PITCHER_PROPS = ["strikeouts", "walks", "outs_recorded"]


def load_model(prop: str):
    path = MODELS_DIR / f"{prop}.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def p_over(predicted_mean: float, line: float) -> float:
    """
    P(actual > line) using Poisson distribution.
    line is typically a half-integer (e.g. 1.5), so floor(line) = 1.
    P(X > 1.5) = P(X >= 2) = 1 - P(X <= 1) = 1 - poisson.cdf(1, mu)
    """
    if predicted_mean <= 0:
        return 0.0
    k = int(line)  # floor — for half-integer lines this is correct
    return float(1.0 - poisson.cdf(k, mu=predicted_mean))


def fetch_features(
    conn: duckdb.DuckDBPyConnection,
    date: str,
    player_ids: list[str] | None,
    latest: bool,
    player_type: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (hitter_df, pitcher_df) for the given date."""
    date_filter = f"pf.date = '{date}'" if not latest else f"pf.date = (SELECT MAX(date) FROM player_features WHERE player_id = pf.player_id)"
    pitcher_date = f"pf.date = '{date}'" if not latest else f"pf.date = (SELECT MAX(date) FROM pitcher_features WHERE pitcher_id = pf.pitcher_id)"

    player_clause = ""
    if player_ids:
        ids = ", ".join(f"'{p}'" for p in player_ids)
        player_clause = f"AND pf.player_id IN ({ids})"

    hitter_df = pd.DataFrame()
    pitcher_df = pd.DataFrame()

    if player_type in ("hitter", "both"):
        q = f"""
            SELECT player_id, date, avg_ev, avg_la, xwoba, ev_7d, xwoba_14d
            FROM player_features pf
            WHERE {date_filter}
            {player_clause}
        """
        hitter_df = conn.execute(q).fetchdf()

    if player_type in ("pitcher", "both"):
        pitcher_player_clause = ""
        if player_ids:
            ids = ", ".join(f"'{p}'" for p in player_ids)
            pitcher_player_clause = f"AND pf.pitcher_id IN ({ids})"
        q = f"""
            SELECT pitcher_id AS player_id, date, avg_velocity, whiff_rate,
                   xwoba_allowed, velocity_trend_7d, park_adjusted_xwoba
            FROM pitcher_features pf
            WHERE {pitcher_date}
            {pitcher_player_clause}
        """
        pitcher_df = conn.execute(q).fetchdf()

    return hitter_df, pitcher_df


def run_predictions(
    df: pd.DataFrame,
    props: list[str],
    top_n: int | None,
) -> list[dict]:
    """Run all models on df and return list of result dicts."""
    rows = []
    for prop in props:
        model = load_model(prop)
        if model is None:
            continue
        _, features, _ = PROP_CONFIG[prop]
        sub = df[["player_id"] + features].dropna()
        if sub.empty:
            continue
        preds = np.clip(model.predict(sub[features].values), 0, None)
        lines = PROP_LINES.get(prop, [])
        for pid, pred in zip(sub["player_id"], preds):
            row = {"player_id": pid, "prop": prop, "predicted": round(float(pred), 3)}
            for line in lines:
                row[f"P(>{line})"] = round(p_over(pred, line), 3)
            rows.append(row)

    if top_n and rows:
        # Rank by edge = abs(best line probability - 0.5) — most confident picks
        def best_edge(r):
            prob_cols = [v for k, v in r.items() if k.startswith("P(>")]
            if not prob_cols:
                return 0
            return max(abs(p - 0.5) for p in prob_cols)
        rows.sort(key=best_edge, reverse=True)
        rows = rows[:top_n]

    return rows


def print_results(rows: list[dict], date: str) -> None:
    if not rows:
        print("No predictions generated.")
        return

    print(f"\nMLB Prop Predictions — {date}")
    print("=" * 70)

    by_prop: dict[str, list[dict]] = {}
    for r in rows:
        by_prop.setdefault(r["prop"], []).append(r)

    for prop, prop_rows in by_prop.items():
        lines = PROP_LINES.get(prop, [])
        # Build header
        line_headers = "  ".join(f"P(>{l})" for l in lines)
        print(f"\n  {prop.upper()}")
        print(f"  {'Player ID':<12}  {'Predicted':>9}  {line_headers}")
        print("  " + "-" * (30 + 9 * len(lines)))
        for r in sorted(prop_rows, key=lambda x: x["predicted"], reverse=True):
            pred_str = f"{r['predicted']:>9.3f}"
            prob_strs = "  ".join(f"{r.get(f'P(>{l})', 0):>6.3f}" for l in lines)
            print(f"  {r['player_id']:<12}  {pred_str}  {prob_strs}")

    print(f"\n  Total predictions: {len(rows)}")


def main():
    parser = argparse.ArgumentParser(description="Generate MLB prop predictions")
    parser.add_argument("--date",    required=False, default=None,
                        help="Date to predict for (YYYY-MM-DD). Defaults to latest in DB.")
    parser.add_argument("--players", nargs="*", default=None,
                        help="Optional MLB player IDs to filter to")
    parser.add_argument("--type",    choices=["hitter", "pitcher", "both"],
                        default="both", help="Which player type to predict")
    parser.add_argument("--top",     type=int, default=None,
                        help="Show only top N picks per run (by confidence)")
    parser.add_argument("--latest",  action="store_true",
                        help="Use each player's most recent features (ignore --date)")
    args = parser.parse_args()

    # Check models exist
    trained = [p for p in PROP_CONFIG if (MODELS_DIR / f"{p}.pkl").exists()]
    if not trained:
        print("No trained models found. Run: python -m ml.train")
        sys.exit(1)

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    # Resolve date
    if args.date is None and not args.latest:
        row = conn.execute("SELECT MAX(date) FROM player_features").fetchone()
        args.date = str(row[0])
        print(f"No --date specified, using latest available: {args.date}")

    hitter_df, pitcher_df = fetch_features(
        conn, args.date or "9999-12-31", args.players, args.latest,
        "both" if args.type == "both" else args.type,
    )
    conn.close()

    if hitter_df.empty and pitcher_df.empty:
        print(f"No features found for date {args.date}. Try --latest or a different --date.")
        sys.exit(1)

    rows = []

    if args.type in ("hitter", "both") and not hitter_df.empty:
        rows += run_predictions(hitter_df, HITTER_PROPS, top_n=None)

    if args.type in ("pitcher", "both") and not pitcher_df.empty:
        rows += run_predictions(pitcher_df, PITCHER_PROPS, top_n=None)

    if args.top:
        def best_edge(r):
            prob_cols = [v for k, v in r.items() if k.startswith("P(>")]
            return max((abs(p - 0.5) for p in prob_cols), default=0)
        rows.sort(key=best_edge, reverse=True)
        rows = rows[:args.top]

    print_results(rows, args.date or "latest")


if __name__ == "__main__":
    main()
