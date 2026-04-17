"""
Incremental MLB data backfill.

Iterates day-by-day from start_date to end_date, calling run_daily()
for each date.  Already-ingested dates are skipped automatically via
the DuckDB ingestion_metadata table.

Usage
-----
    # Full range
    python backfill.py --start 2024-04-01 --end 2025-09-28

    # Start only (end defaults to yesterday)
    python backfill.py --start 2024-04-01

    # Resume from last ingested date in DuckDB (no --start needed)
    python backfill.py --resume
    python backfill.py --resume --end 2025-09-28
"""

import argparse
import sys
from datetime import date, timedelta

from loguru import logger
from tqdm import tqdm

from feature_store.build_duckdb import get_connection, get_last_ingested_date, initialize_schema
from run_daily import DATA_TYPE_HITTING
from utils.dates import date_range, from_str, yesterday
from utils.logging import setup_logger


def _resolve_resume_start() -> date | None:
    """
    Read last_ingested_date from DuckDB and return the day after.

    Returns None if the database has no ingestion history yet.
    """
    try:
        conn = get_connection()
        initialize_schema(conn)
        last = get_last_ingested_date(conn, DATA_TYPE_HITTING)
        conn.close()
    except Exception as exc:
        logger.warning(f"Could not read DuckDB metadata for --resume: {exc}")
        return None

    if last is None:
        logger.warning("--resume: no ingestion history found in DuckDB. Use --start to specify a date.")
        return None

    resume_from = last + timedelta(days=1)
    logger.info(f"--resume: last ingested date was {last}; resuming from {resume_from}")
    return resume_from


def backfill(start_date: date, end_date: date, force: bool = False) -> None:
    """
    Run the daily ingestion pipeline incrementally from start_date to end_date.

    Shows a tqdm progress bar with current date, elapsed time, and ETA.
    Already-ingested dates are silently skipped inside run_daily() via
    the DuckDB metadata check.

    Parameters
    ----------
    start_date:
        First date to ingest (inclusive).
    end_date:
        Last date to ingest (inclusive).
    """
    setup_logger()

    all_dates = list(date_range(start_date, end_date))
    total = len(all_dates)

    if total == 0:
        logger.warning(f"No dates to process (start={start_date}, end={end_date})")
        return

    logger.info(f"Backfill: {start_date} -> {end_date} ({total} calendar days)")

    skipped = 0
    errors: list[tuple[date, str]] = []

    bar = tqdm(
        all_dates,
        total=total,
        desc="Backfill",
        unit="day",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        file=sys.stdout,
        dynamic_ncols=True,
    )

    for d in bar:
        bar.set_postfix_str(str(d))
        try:
            from run_daily import run_daily
            run_daily(target_date=d, force=force)
        except Exception as exc:
            errors.append((d, str(exc)))
            logger.error(f"Error on {d}: {exc}")
            skipped += 1

    bar.close()

    processed = total - skipped
    print()  # blank line after bar
    logger.info(f"Backfill complete — {processed}/{total} days processed, {skipped} errors")

    if errors:
        logger.warning("Failed dates:")
        for d, msg in errors:
            logger.warning(f"  {d}: {msg}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill the MLB feature store",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python backfill.py --start 2024-04-01 --end 2025-09-28
  python backfill.py --start 2024-04-01
  python backfill.py --resume
  python backfill.py --resume --end 2025-09-28
        """,
    )
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD (required unless --resume)")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD (default: yesterday)")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the day after the last ingested date in DuckDB",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch and overwrite existing Statcast parquets (use after schema changes)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    end = from_str(args.end) if args.end else yesterday()

    if args.resume:
        start = _resolve_resume_start()
        if start is None:
            print("Nothing to resume. Use --start to specify a start date.")
            sys.exit(1)
    elif args.start:
        start = from_str(args.start)
    else:
        print("Error: provide --start <date> or --resume")
        sys.exit(1)

    if start > end:
        logger.info(f"Already up to date (start={start}, end={end}). Nothing to do.")
        sys.exit(0)

    backfill(start, end, force=args.force)
