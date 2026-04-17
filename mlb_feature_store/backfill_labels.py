"""
Backfill prop outcome labels from existing Statcast parquets.

Use this after adding the labels layer to an already-backfilled feature store.
Reads existing hitting parquets — no re-fetching from the API.

Hitter labels (hits, total_bases, home_runs): works on all existing parquets.
Pitcher labels (strikeouts, walks, outs_recorded): requires pitcher column.
  If missing, re-fetch hitting parquets first:
    python backfill.py --start 2024-04-01 --end 2024-10-01 --force

Usage
-----
    python backfill_labels.py --start 2024-04-01 --end 2024-10-01
    python backfill_labels.py --start 2024-04-01   # end defaults to yesterday
"""

import argparse
import sys
from datetime import date

from loguru import logger
from tqdm import tqdm

from feature_store.build_duckdb import (
    get_connection,
    initialize_schema,
    upsert_hitter_labels,
    upsert_pitcher_labels,
)
from labels.compute_labels import compute_labels_for_date
from utils.dates import date_range, from_str, yesterday
from utils.logging import setup_logger


def backfill_labels(start_date: date, end_date: date) -> None:
    setup_logger()

    all_dates = list(date_range(start_date, end_date))
    if not all_dates:
        logger.warning("No dates to process")
        return

    logger.info(f"Label backfill: {start_date} -> {end_date} ({len(all_dates)} days)")

    conn = get_connection()
    initialize_schema(conn)

    hitter_days = 0
    pitcher_days = 0
    errors: list[tuple[date, str]] = []

    bar = tqdm(all_dates, desc="Labels", unit="day", file=sys.stdout, dynamic_ncols=True)
    for d in bar:
        bar.set_postfix_str(str(d))
        try:
            hitter_labels, pitcher_labels = compute_labels_for_date(d)
            upsert_hitter_labels(conn, hitter_labels)
            upsert_pitcher_labels(conn, pitcher_labels)
            if not hitter_labels.empty:
                hitter_days += 1
            if not pitcher_labels.empty:
                pitcher_days += 1
        except Exception as exc:
            errors.append((d, str(exc)))
            logger.error(f"Error on {d}: {exc}")

    conn.commit()
    conn.close()
    bar.close()

    print()
    logger.info(
        f"Label backfill complete — "
        f"hitter labels: {hitter_days} days, pitcher labels: {pitcher_days} days"
    )
    if pitcher_days == 0:
        logger.warning(
            "No pitcher labels written — pitcher column missing from hitting parquets. "
            "Re-fetch with: python backfill.py --start {start} --end {end} --force"
        )
    if errors:
        logger.warning(f"{len(errors)} errors:")
        for d, msg in errors:
            logger.warning(f"  {d}: {msg}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill prop outcome labels")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD (default: yesterday)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    start = from_str(args.start)
    end = from_str(args.end) if args.end else yesterday()
    backfill_labels(start, end)
