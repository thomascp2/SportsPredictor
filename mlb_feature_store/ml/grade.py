"""
Grade MLB ML predictions against actual Statcast outcomes.

Joins ml_predictions with hitter_labels / pitcher_labels (which are
populated by run_daily.py) and writes actual_value back to ml_predictions.
Then prints a per-prop, per-line accuracy report.

This must run AFTER run_daily.py for the same date, so labels are present.

Usage:
    python -m ml.grade                    # grade yesterday
    python -m ml.grade --date 2026-04-12  # specific date
    python -m ml.grade --report           # show accuracy report only (no writes)
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
from scipy.stats import poisson

from feature_store.build_duckdb import get_connection, initialize_schema
from ml.train import PROP_CONFIG, HITTER_FEATURES, PITCHER_FEATURES

PROP_LINES = {
    "hits":          [0.5, 1.5, 2.5],
    "total_bases":   [1.5, 2.5, 3.5],
    "home_runs":     [0.5, 1.5],
    "strikeouts":    [3.5, 4.5, 5.5, 6.5, 7.5],
    "walks":         [1.5, 2.5],
    "outs_recorded": [14.5, 17.5],
}

HITTER_PROPS  = {"hits", "total_bases", "home_runs"}
PITCHER_PROPS = {"strikeouts", "walks", "outs_recorded"}


def _p_over(mu: float, line: float) -> float:
    if mu <= 0:
        return 0.0
    return float(1.0 - poisson.cdf(int(line), mu=mu))


def _add_actual_value_column(conn: duckdb.DuckDBPyConnection) -> None:
    """Add actual_value column to ml_predictions if it doesn't exist."""
    cols = [r[0] for r in conn.execute("DESCRIBE ml_predictions").fetchall()]
    if "actual_value" not in cols:
        conn.execute("ALTER TABLE ml_predictions ADD COLUMN actual_value DOUBLE")
    if "graded_at" not in cols:
        conn.execute("ALTER TABLE ml_predictions ADD COLUMN graded_at TIMESTAMP")


def grade_date(conn: duckdb.DuckDBPyConnection, game_date: str) -> int:
    """
    Join ml_predictions for game_date with hitter/pitcher labels,
    write actual_value + graded_at back to ml_predictions.
    Returns number of rows updated.
    """
    _add_actual_value_column(conn)

    # Check labels exist for this date
    hl_count = conn.execute(
        f"SELECT COUNT(*) FROM hitter_labels WHERE game_date = '{game_date}'"
    ).fetchone()[0]
    pl_count = conn.execute(
        f"SELECT COUNT(*) FROM pitcher_labels WHERE game_date = '{game_date}'"
    ).fetchone()[0]

    if hl_count == 0 and pl_count == 0:
        print(f"  [SKIP] No labels for {game_date} — run_daily.py first")
        return 0

    # Update hitter props
    hitter_sql = f"""
        UPDATE ml_predictions
        SET actual_value = hl.{{}},
            graded_at    = current_timestamp
        FROM hitter_labels hl
        WHERE ml_predictions.player_id = hl.player_id
          AND ml_predictions.game_date  = hl.game_date
          AND ml_predictions.game_date  = '{game_date}'
          AND ml_predictions.prop       = '{{}}'
    """
    # DuckDB UPDATE...FROM requires the SET to reference the joined table directly,
    # but prop is a string column. We update one prop at a time.
    updated = 0
    for prop in HITTER_PROPS:
        target_col = PROP_CONFIG[prop][0]  # 'hits', 'total_bases', 'home_runs'
        conn.execute(f"""
            UPDATE ml_predictions
            SET actual_value = hl.{target_col},
                graded_at    = current_timestamp
            FROM hitter_labels hl
            WHERE ml_predictions.player_id = hl.player_id
              AND ml_predictions.game_date  = hl.game_date
              AND ml_predictions.game_date  = '{game_date}'
              AND ml_predictions.prop       = '{prop}'
        """)
        n = conn.execute(
            f"SELECT COUNT(*) FROM ml_predictions "
            f"WHERE game_date='{game_date}' AND prop='{prop}' AND actual_value IS NOT NULL"
        ).fetchone()[0]
        updated += n

    for prop in PITCHER_PROPS:
        target_col = PROP_CONFIG[prop][0]  # 'strikeouts', 'walks', 'outs_recorded'
        conn.execute(f"""
            UPDATE ml_predictions
            SET actual_value = pl.{target_col},
                graded_at    = current_timestamp
            FROM pitcher_labels pl
            WHERE ml_predictions.player_id = pl.player_id
              AND ml_predictions.game_date  = pl.game_date
              AND ml_predictions.game_date  = '{game_date}'
              AND ml_predictions.prop       = '{prop}'
        """)

    # Total graded rows
    total = conn.execute(
        f"SELECT COUNT(*) FROM ml_predictions "
        f"WHERE game_date='{game_date}' AND actual_value IS NOT NULL"
    ).fetchone()[0]

    # Log in grading ledger
    initialize_schema(conn)
    conn.execute("""
        INSERT INTO ml_grading_log (game_date, graded_at, rows_graded)
        VALUES (?, current_timestamp, ?)
        ON CONFLICT (game_date) DO UPDATE SET
            graded_at   = excluded.graded_at,
            rows_graded = excluded.rows_graded
    """, [game_date, total])

    return total


def print_accuracy_report(conn: duckdb.DuckDBPyConnection, game_date: str | None = None) -> None:
    """Print per-prop / per-line accuracy for graded ML predictions."""
    date_filter = f"AND game_date = '{game_date}'" if game_date else ""

    df = conn.execute(f"""
        SELECT prop, predicted_value, actual_value, game_date
        FROM ml_predictions
        WHERE actual_value IS NOT NULL {date_filter}
        ORDER BY prop
    """).fetchdf()

    if df.empty:
        print("  No graded ML predictions found.")
        return

    date_range = f"{df['game_date'].min()} -> {df['game_date'].max()}" if not game_date else game_date

    print(f"\nML Model Accuracy Report  [{date_range}]")
    print("=" * 60)

    for prop in sorted(df["prop"].unique()):
        prop_df = df[df["prop"] == prop].copy()
        prop_df["predicted_value"] = prop_df["predicted_value"].clip(lower=0)
        lines = PROP_LINES.get(prop, [])

        # MAE
        mae = (prop_df["predicted_value"] - prop_df["actual_value"]).abs().mean()
        naive_mae = (prop_df["actual_value"].mean() - prop_df["actual_value"]).abs().mean()
        print(f"\n  {prop.upper()}  (n={len(prop_df):,}  MAE={mae:.3f}  baseline={naive_mae:.3f})")

        if lines:
            print(f"  {'Line':>6}  {'N_over':>7}  {'Over%':>6}  {'Acc':>6}  {'vs naive':>9}")
            print("  " + "-" * 44)
            for line in lines:
                actual_over = prop_df["actual_value"] > line
                pred_over   = prop_df["predicted_value"] > line
                n_over      = int(actual_over.sum())
                if len(prop_df) == 0:
                    continue
                over_pct  = actual_over.mean() * 100
                acc       = (actual_over == pred_over).mean() * 100
                naive_acc = max(over_pct, 100 - over_pct)
                sign = "+" if acc >= naive_acc else ""
                print(f"  {line:>6.1f}  {n_over:>7,}  {over_pct:>5.1f}%  {acc:>5.1f}%  "
                      f"{sign}{acc-naive_acc:>7.1f}%")

    print()


def main():
    parser = argparse.ArgumentParser(description="Grade MLB ML predictions")
    parser.add_argument("--date",   default=None, help="Date to grade YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--report", action="store_true", help="Show accuracy report only (no writes)")
    parser.add_argument("--all",    action="store_true", help="Grade all ungraded dates in ml_predictions")
    args = parser.parse_args()

    conn = get_connection()
    initialize_schema(conn)
    _add_actual_value_column(conn)

    if args.report:
        print_accuracy_report(conn, args.date)
        conn.close()
        return

    if args.all:
        # Find all dates in ml_predictions that have no actual_value
        dates = [
            r[0] for r in conn.execute("""
                SELECT DISTINCT game_date FROM ml_predictions
                WHERE actual_value IS NULL
                ORDER BY game_date
            """).fetchall()
        ]
        if not dates:
            print("All ML predictions already graded.")
        for d in dates:
            n = grade_date(conn, str(d))
            print(f"  {d}: {n} rows graded")
        print_accuracy_report(conn)
    else:
        target = args.date or str(date.today() - timedelta(days=1))
        n = grade_date(conn, target)
        print(f"  {target}: {n} rows graded")
        if n > 0:
            print_accuracy_report(conn, target)

    conn.close()


if __name__ == "__main__":
    main()
