"""
Golf Historical Round Log Backfill
=====================================

Backfills player_round_logs with 5 seasons of PGA Tour history (2020–2024)
using the ESPN Golf API's historical event data.

This is a one-time data collection script. Once complete, the grading script
(auto_grade_daily.py) keeps the database current going forward.

Strategy:
  1. Fetch all PGA Tour event IDs for each season via ESPN's season calendar
  2. For each event, fetch the full leaderboard (all players, all rounds)
  3. Store round scores, cut status, finish positions
  4. Rate-limit to avoid overwhelming the ESPN API (~0.5s between requests)
  5. Resume-safe: skips events already fully loaded (via UNIQUE constraint)

Expected data volume:
  ~46 events/season × ~5 seasons × ~120 players × ~3.5 rounds avg = ~96,000 rows
  (cut eliminates ~50% of field after R2; R3/R4 = ~80 players)

Estimated runtime: ~45–90 minutes for full backfill (API rate-limited)

Usage:
    # Full backfill (2020–2024)
    python backfill_round_logs.py

    # Single season
    python backfill_round_logs.py --season 2024

    # Dry run — show what would be loaded without writing
    python backfill_round_logs.py --dry-run

    # Resume from a specific season/event if interrupted
    python backfill_round_logs.py --season 2023
"""

import sys
import os
import sqlite3
import argparse
import logging
import time
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from golf_config import DB_PATH, DATA_COLLECTION_START, init_database
from espn_golf_api import ESPNGolfApi

logging.basicConfig(
    level=logging.INFO,
    format="[GOLF][BACKFILL] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Seasons to backfill (PGA Tour season year = calendar year the season ends)
DEFAULT_SEASONS = [2020, 2021, 2022, 2023, 2024]

# Rate limiting between ESPN API calls (seconds)
API_RATE_LIMIT = 0.5


# ============================================================================
# Helpers
# ============================================================================

def event_is_loaded(conn, event_id: str) -> bool:
    """Check if we already have data for this event."""
    row = conn.execute(
        "SELECT COUNT(*) FROM player_round_logs WHERE tournament_id = ?",
        (event_id,),
    ).fetchone()
    return row[0] > 0


def infer_round_date(event_start_date: str, round_number: int) -> str:
    """
    Estimate the calendar date of a specific round.
    PGA Tour rounds: R1=Thursday, R2=Friday, R3=Saturday, R4=Sunday.
    """
    start = date.fromisoformat(event_start_date)
    return (start + timedelta(days=round_number - 1)).isoformat()


def save_leaderboard_to_db(conn, leaderboard: list, event: dict, season: int, dry_run: bool = False):
    """
    Persist all round scores from a leaderboard entry into player_round_logs.

    Returns:
        int: Number of rows inserted
    """
    inserted = 0
    event_id   = event["event_id"]
    event_name = event.get("name", "Unknown Tournament")
    course_name = event.get("course_name", "")
    start_date  = event.get("start_date", "2020-01-01")

    for entry in leaderboard:
        player_name = entry.get("player_name", "")
        if not player_name:
            continue

        made_cut_val = (
            1 if entry.get("made_cut") is True
            else 0 if entry.get("made_cut") is False
            else None
        )
        finish_pos = entry.get("position")

        for round_data in entry.get("rounds", []):
            round_num = round_data.get("round")
            score = round_data.get("score")
            if not round_num or score is None:
                continue

            round_date = infer_round_date(start_date, round_num)

            if dry_run:
                inserted += 1
                continue

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO player_round_logs
                        (player_name, tournament_name, tournament_id, course_name,
                         round_number, round_score, game_date, season,
                         made_cut, finish_position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        player_name, event_name, event_id, course_name,
                        round_num, score, round_date, season,
                        made_cut_val if round_num >= 3 else None,
                        finish_pos,
                    ),
                )
                inserted += 1
            except sqlite3.Error as e:
                logger.debug(f"DB insert error for {player_name} R{round_num}: {e}")

    return inserted


# ============================================================================
# Main backfill
# ============================================================================

def backfill_season(season: int, api: ESPNGolfApi, conn, dry_run: bool = False):
    """
    Backfill all events for a single PGA Tour season.

    Returns:
        dict: {'events_processed': int, 'events_skipped': int, 'rows_inserted': int}
    """
    logger.info(f"Starting backfill for {season} PGA Tour season...")

    events = api.get_historical_event_ids(season)
    if not events:
        logger.warning(f"No events found for season {season}. ESPN calendar may not cover this year.")
        return {"events_processed": 0, "events_skipped": 0, "rows_inserted": 0}

    logger.info(f"  Found {len(events)} events for {season} season")

    events_processed = 0
    events_skipped   = 0
    rows_inserted    = 0

    for i, event_stub in enumerate(events, start=1):
        event_id   = event_stub.get("event_id", "")
        event_name = event_stub.get("name", f"Event {event_id}")
        start_date = event_stub.get("start_date", "")

        if not event_id:
            continue

        # Skip events outside our target date range
        if start_date and start_date < DATA_COLLECTION_START:
            events_skipped += 1
            continue

        # Skip if already loaded (resume-safe)
        if not dry_run and event_is_loaded(conn, event_id):
            logger.debug(f"  [{i}/{len(events)}] SKIP (already loaded): {event_name}")
            events_skipped += 1
            continue

        logger.info(f"  [{i}/{len(events)}] Loading: {event_name} ({start_date})")

        # Fetch full leaderboard
        leaderboard = api.get_leaderboard(event_id)
        time.sleep(API_RATE_LIMIT)  # Rate limit

        if not leaderboard:
            logger.warning(f"    No leaderboard data for event {event_id}")
            events_skipped += 1
            continue

        # Build full event dict for storage
        full_event = {
            "event_id":    event_id,
            "name":        event_name,
            "start_date":  start_date,
            "end_date":    event_stub.get("end_date", ""),
            "course_name": "",  # Not available from calendar stub; OK to leave blank
        }

        n = save_leaderboard_to_db(conn, leaderboard, full_event, season, dry_run=dry_run)
        if not dry_run:
            conn.commit()

        logger.info(f"    {len(leaderboard)} players, {n} rows {'(dry run)' if dry_run else 'inserted'}")
        rows_inserted += n
        events_processed += 1

    logger.info(
        f"Season {season}: {events_processed} events processed, "
        f"{events_skipped} skipped, {rows_inserted} rows inserted"
    )
    return {
        "events_processed": events_processed,
        "events_skipped": events_skipped,
        "rows_inserted": rows_inserted,
    }


def run_backfill(seasons: list, dry_run: bool = False):
    """Run backfill for multiple seasons."""
    if not dry_run:
        init_database()

    api = ESPNGolfApi()
    conn = sqlite3.connect(DB_PATH) if not dry_run else None

    total_events = 0
    total_rows   = 0

    try:
        for season in seasons:
            result = backfill_season(season, api, conn, dry_run=dry_run)
            total_events += result["events_processed"]
            total_rows   += result["rows_inserted"]
    finally:
        if conn:
            conn.close()

    print(f"\n[GOLF] Backfill complete:")
    print(f"  Seasons processed : {len(seasons)}")
    print(f"  Total events      : {total_events}")
    print(f"  Total rows        : {total_rows:,}")
    if dry_run:
        print("  (DRY RUN — no data written)")

    return {"total_events": total_events, "total_rows": total_rows}


# ============================================================================
# Entry point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Backfill PGA Tour historical round data (2020–2024)"
    )
    parser.add_argument(
        "--season", "-s",
        type=int,
        help="Backfill a specific season only (e.g., 2024)",
        default=None,
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be loaded without writing to database",
    )
    args = parser.parse_args()

    seasons = [args.season] if args.season else DEFAULT_SEASONS

    print(f"\n[GOLF] Starting backfill for seasons: {seasons}")
    if args.dry_run:
        print("  DRY RUN mode — no data will be written")
    print()

    run_backfill(seasons, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
