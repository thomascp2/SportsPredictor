"""
Backfill script: Re-grade all NBA threes predictions with corrected ESPN parsing.

Root cause: espn_nba_api.py parse_made_attempted() looked for '3PM-3PA', '3P', etc.
but ESPN actually returns the column header as '3PT'. As a result, threes_made was
stored as 0 for every player for 101 dates (2025-11-10 through 2026-03-17).

Fix: '3PT' added to parse_made_attempted key list in espn_nba_api.py (2026-03-18).

This script re-runs the grading pipeline for each affected date, which:
  1. Re-fetches actual stats from ESPN with the corrected 3PT key
  2. Updates player_game_logs.threes_made with correct values
  3. Recalculates outcome (HIT/MISS) for all threes predictions
  4. Syncs corrected data to Supabase

Usage:
    cd C:/Users/thoma/SportsPredictor
    python nba/scripts/backfill_threes_regrade.py

    # Or for a specific date range:
    python nba/scripts/backfill_threes_regrade.py --start 2026-02-20 --end 2026-03-17

    # Dry run (show what would be re-graded, don't execute):
    python nba/scripts/backfill_threes_regrade.py --dry-run
"""

import sys
import os
import argparse
import sqlite3
import subprocess
import time
from datetime import datetime, date

# Add parent directories to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'nba_predictions.db')
GRADE_SCRIPT = os.path.join(os.path.dirname(__file__), 'auto_grade_multi_api_FIXED.py')

# All dates confirmed affected by the 3PT parsing bug
AFFECTED_DATES = [
    '2025-11-10', '2025-11-11', '2025-11-14', '2025-11-15', '2025-11-16',
    '2025-11-17', '2025-11-19', '2025-11-20', '2025-11-21', '2025-11-22',
    '2025-11-23', '2025-11-24', '2025-11-25', '2025-11-26', '2025-11-28',
    '2025-11-29', '2025-11-30', '2025-12-01', '2025-12-02', '2025-12-03',
    '2025-12-04', '2025-12-05', '2025-12-06', '2025-12-07', '2025-12-08',
    '2025-12-09', '2025-12-10', '2025-12-12', '2025-12-13', '2025-12-14',
    '2025-12-15', '2025-12-17', '2025-12-18', '2025-12-19', '2025-12-20',
    '2025-12-21', '2025-12-22', '2025-12-23', '2025-12-25', '2025-12-26',
    '2025-12-27', '2025-12-28', '2025-12-29', '2025-12-30', '2025-12-31',
    '2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05',
    '2026-01-06', '2026-01-07', '2026-01-08', '2026-01-09', '2026-01-10',
    '2026-01-11', '2026-01-12', '2026-01-13', '2026-01-14', '2026-01-15',
    '2026-01-16', '2026-01-17', '2026-01-18', '2026-01-19', '2026-01-20',
    '2026-01-21', '2026-01-22', '2026-01-23', '2026-01-24', '2026-01-25',
    '2026-01-26', '2026-02-08', '2026-02-09', '2026-02-10', '2026-02-11',
    '2026-02-12', '2026-02-20', '2026-02-21', '2026-02-22', '2026-02-23',
    '2026-02-24', '2026-02-25', '2026-02-26', '2026-02-27', '2026-02-28',
    '2026-03-01', '2026-03-02', '2026-03-04', '2026-03-05', '2026-03-06',
    '2026-03-07', '2026-03-08', '2026-03-09', '2026-03-10', '2026-03-11',
    '2026-03-12', '2026-03-13', '2026-03-14', '2026-03-15', '2026-03-16',
    '2026-03-17',
]


def get_threes_count(game_date):
    """Check how many threes outcomes exist for a date and how many have actual_value=0."""
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute(
        'SELECT COUNT(*) FROM prediction_outcomes WHERE game_date=? AND prop_type="threes"',
        (game_date,)
    ).fetchone()[0]
    zeros = conn.execute(
        'SELECT COUNT(*) FROM prediction_outcomes WHERE game_date=? AND prop_type="threes" AND actual_value=0',
        (game_date,)
    ).fetchone()[0]
    conn.close()
    return total, zeros


def regrade_date(game_date, dry_run=False):
    """Re-run grading script for a specific date."""
    total, zeros = get_threes_count(game_date)
    if total == 0:
        return 'skip', 'No threes predictions for this date'

    print(f"  {game_date}: {zeros}/{total} threes outcomes have actual_value=0", end='')
    if zeros == 0:
        print(' -> already clean, skipping')
        return 'skip', 'Already clean'

    print(f' -> re-grading...')
    if dry_run:
        return 'dry_run', f'{zeros} outcomes would be re-graded'

    result = subprocess.run(
        [sys.executable, GRADE_SCRIPT, game_date],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), '..', '..', 'nba')
    )

    if result.returncode != 0:
        print(f"    ERROR: {result.stderr[-200:]}")
        return 'error', result.stderr[-200:]

    # Verify improvement
    _, zeros_after = get_threes_count(game_date)
    improvement = zeros - zeros_after
    print(f"    Fixed {improvement} threes outcomes (zeros: {zeros} -> {zeros_after})")
    return 'ok', f'Fixed {improvement}'


def main():
    parser = argparse.ArgumentParser(description='Re-grade NBA threes predictions with corrected ESPN 3PT parsing')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD), default: earliest affected')
    parser.add_argument('--end', help='End date (YYYY-MM-DD), default: latest affected')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without executing')
    parser.add_argument('--delay', type=float, default=2.0, help='Seconds between grading runs (default: 2)')
    args = parser.parse_args()

    dates = AFFECTED_DATES
    if args.start:
        dates = [d for d in dates if d >= args.start]
    if args.end:
        dates = [d for d in dates if d <= args.end]

    print(f"[BACKFILL] NBA Threes Re-grading")
    print(f"[BACKFILL] Root cause: ESPN uses '3PT' column header, code looked for '3PM-3PA'")
    print(f"[BACKFILL] Fix applied: espn_nba_api.py (2026-03-18)")
    print(f"[BACKFILL] Dates to process: {len(dates)}")
    if args.dry_run:
        print(f"[BACKFILL] DRY RUN - no changes will be made")
    print()

    results = {'ok': 0, 'skip': 0, 'error': 0, 'dry_run': 0}

    for i, game_date in enumerate(dates, 1):
        print(f"[{i:3d}/{len(dates)}]", end=' ')
        status, msg = regrade_date(game_date, dry_run=args.dry_run)
        results[status] = results.get(status, 0) + 1

        if status == 'ok' and i < len(dates):
            time.sleep(args.delay)  # Avoid hammering ESPN API

    print()
    print(f"[BACKFILL] Complete: {results['ok']} re-graded, {results['skip']} skipped, {results['error']} errors")

    if results['ok'] > 0 and not args.dry_run:
        print()
        print("[BACKFILL] Next step: sync corrected data to Supabase:")
        print("  python orchestrator.py --sport nba --mode once --operation grading")
        print("  (or run sync/supabase_sync.py manually for each affected date)")


if __name__ == '__main__':
    main()
