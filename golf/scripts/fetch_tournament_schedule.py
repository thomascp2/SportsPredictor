"""
Fetch PGA Tour Tournament Schedule
=====================================

Queries the ESPN Golf API for upcoming and active PGA Tour events,
then prints a schedule summary for monitoring and orchestrator health checks.

Can also be used to check whether a tournament is active on a given date,
which the orchestrator uses to decide whether to run the golf prediction pipeline.

Usage:
    # Show next 14 days of events
    python fetch_tournament_schedule.py

    # Check if a specific date has an active tournament
    python fetch_tournament_schedule.py --date 2025-04-10

    # Show events for the next N days
    python fetch_tournament_schedule.py --days 30
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import date, timedelta

# Path setup
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from espn_golf_api import ESPNGolfApi
from golf_config import has_active_tournament, MAJOR_NAMES


def get_active_tournament(target_date: str = None):
    """
    Check whether a PGA Tour tournament is active on the given date.

    Returns:
        dict | None: Event info dict if active, None otherwise.
    """
    d = target_date or date.today().isoformat()
    api = ESPNGolfApi()
    event = api.get_tournament_by_date(d)
    if not event:
        return None
    # Confirm the date falls within the event window
    start = event.get("start_date", "")
    end = event.get("end_date", "")
    if start and end:
        if not (start <= d <= end):
            return None
    return event


def print_schedule(days_ahead: int = 14):
    """Print upcoming PGA Tour events."""
    api = ESPNGolfApi()
    events = api.get_upcoming_events(days_ahead=days_ahead)

    today = date.today().isoformat()
    print(f"\nPGA Tour Schedule — next {days_ahead} days from {today}")
    print("=" * 60)

    if not events:
        print("  No events found. Either off-season or ESPN API unavailable.")
        return

    for event in events:
        name = event.get("name", "Unknown")
        course = event.get("course_name", "Unknown course")
        start = event.get("start_date", "?")
        end = event.get("end_date", "?")
        status = event.get("status", "pre")
        current_round = event.get("current_round", 1)
        is_major = any(m.lower() in name.lower() for m in MAJOR_NAMES)
        major_tag = " [MAJOR]" if is_major else ""

        if status == "in":
            status_str = f"LIVE (Round {current_round})"
        elif status == "post":
            status_str = "COMPLETED"
        else:
            status_str = f"Upcoming ({start})"

        print(f"\n  {name}{major_tag}")
        print(f"    Course : {course}")
        print(f"    Dates  : {start} to {end}")
        print(f"    Status : {status_str}")
        print(f"    ID     : {event.get('event_id', 'N/A')}")


def check_date(target_date: str):
    """Check and report whether a tournament is active on the given date."""
    # Quick heuristic check first
    if not has_active_tournament(target_date):
        print(f"\nNo PGA Tour tournament expected on {target_date} (off-season or non-tournament day).")
        return False

    event = get_active_tournament(target_date)
    if event:
        name = event.get("name", "Unknown")
        course = event.get("course_name", "Unknown course")
        status = event.get("status", "pre")
        current_round = event.get("current_round", 1)
        print(f"\n[GOLF] Active tournament on {target_date}:")
        print(f"  Event  : {name}")
        print(f"  Course : {course}")
        print(f"  Status : {status} | Round {current_round}")
        print(f"  ID     : {event.get('event_id', 'N/A')}")
        return True
    else:
        print(f"\nNo active tournament found on {target_date} (ESPN API returned nothing).")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and display PGA Tour tournament schedule"
    )
    parser.add_argument(
        "--date", "-d",
        help="Check for an active tournament on this date (YYYY-MM-DD)",
        default=None,
    )
    parser.add_argument(
        "--days", "-n",
        help="Number of days ahead to show schedule (default: 14)",
        type=int,
        default=14,
    )
    args = parser.parse_args()

    if args.date:
        check_date(args.date)
    else:
        print_schedule(days_ahead=args.days)


if __name__ == "__main__":
    main()
