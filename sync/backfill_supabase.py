#!/usr/bin/env python3
"""
Supabase Historical Back-fill
==============================

Pushes all local SQLite predictions + grading outcomes that are missing
from Supabase into daily_props. Runs sync/supabase_sync.py for each
unsynced date, skipping dates that already have a matching count.

Usage:
    python sync/backfill_supabase.py                   # both sports, all missing dates
    python sync/backfill_supabase.py --sport nba       # NBA only
    python sync/backfill_supabase.py --sport nhl       # NHL only
    python sync/backfill_supabase.py --dry-run         # print plan, don't sync
    python sync/backfill_supabase.py --since 2026-01-01  # only dates on/after this
"""

import sys
import os
import argparse
import sqlite3
import subprocess
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DATABASES = {
    "nba": ROOT / "nba" / "database" / "nba_predictions.db",
    "nhl": ROOT / "nhl" / "database" / "nhl_predictions_v2.db",
}


def get_local_dates(sport: str) -> list:
    """Return all distinct game_dates in the local predictions table."""
    db = DATABASES[sport]
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT game_date FROM predictions ORDER BY game_date")
    dates = [r[0] for r in cur.fetchall()]
    conn.close()
    return dates


def get_supabase_counts(sport: str, dates: list) -> dict:
    """Return {date: count} for dates already in Supabase."""
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            env_file = ROOT / ".env"
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("SUPABASE_URL="):
                        url = line.split("=", 1)[1].strip()
                    elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                        key = line.split("=", 1)[1].strip()
        sb = create_client(url, key)
        counts = {}
        for d in dates:
            r = (sb.table("daily_props")
                   .select("id", count="exact")
                   .eq("sport", sport.upper())
                   .eq("game_date", d)
                   .execute())
            counts[d] = r.count or 0
        return counts
    except Exception as e:
        print(f"[ERROR] Could not query Supabase: {e}")
        sys.exit(1)


def run_sync(sport: str, game_date: str) -> bool:
    """Run supabase_sync.py for a single sport/date. Returns True on success."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "sync" / "supabase_sync.py"),
         "--sport", sport, "--operation", "all", "--date", game_date],
        capture_output=True, text=True, cwd=str(ROOT)
    )
    if result.returncode != 0:
        print(f"    [FAIL] {result.stderr[-200:].strip()}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Back-fill Supabase from local SQLite")
    parser.add_argument("--sport", choices=["nba", "nhl", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without syncing")
    parser.add_argument("--since", metavar="YYYY-MM-DD",
                        help="Only back-fill dates on or after this date")
    parser.add_argument("--force", action="store_true",
                        help="Re-sync even if Supabase already has rows for the date")
    args = parser.parse_args()

    sports = ["nba", "nhl"] if args.sport == "all" else [args.sport]

    for sport in sports:
        print(f"\n{'='*55}")
        print(f"  {sport.upper()} BACK-FILL")
        print(f"{'='*55}")

        local_dates = get_local_dates(sport)
        if args.since:
            local_dates = [d for d in local_dates if d >= args.since]

        if not local_dates:
            print("  No local dates found.")
            continue

        print(f"  Local dates: {len(local_dates)}  ({local_dates[0]} to {local_dates[-1]})")
        print("  Checking Supabase counts...")
        sb_counts = get_supabase_counts(sport, local_dates)

        missing = [d for d in local_dates if args.force or sb_counts.get(d, 0) == 0]
        already = len(local_dates) - len(missing)

        print(f"  Already synced: {already} dates")
        print(f"  To back-fill:   {len(missing)} dates")

        if not missing:
            print("  Nothing to do.")
            continue

        if args.dry_run:
            print("\n  [DRY RUN] Would sync these dates:")
            for d in missing:
                print(f"    {d}")
            continue

        success = 0
        fail = 0
        for i, d in enumerate(missing, 1):
            print(f"  [{i:3d}/{len(missing)}] {d} ... ", end="", flush=True)
            ok = run_sync(sport, d)
            if ok:
                print("OK")
                success += 1
            else:
                print("FAIL")
                fail += 1

        print(f"\n  Done. {success} synced, {fail} failed.")


if __name__ == "__main__":
    main()
