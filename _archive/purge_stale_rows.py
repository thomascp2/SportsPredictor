#!/usr/bin/env python3
"""
Purge Stale Supabase Rows (daily_props)
========================================
Stale rows accumulate when PrizePicks adjusts a line mid-day (e.g. 24.5 → 25.5).
The upsert conflict key is (game_date, player_name, prop_type, line), so the old
line creates a new row and the old one is never deleted.

Strategy: for each (game_date, player_name, prop_type, sport) group with multiple
lines, keep the row with the highest line (most recent PP adjustment) or the one
with is_smart_pick=True if there's a conflict. Delete all others.

Usage:
    python sync/purge_stale_rows.py --dry-run          # show what would be deleted
    python sync/purge_stale_rows.py --sport nba        # dry-run for one sport
    python sync/purge_stale_rows.py --execute          # actually delete
    python sync/purge_stale_rows.py --execute --sport nba
"""

import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sync.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

try:
    from supabase import create_client
except ImportError:
    print("ERROR: supabase-py not installed. Run: pip install supabase")
    sys.exit(1)

PAGE_SIZE = 1000


def fetch_all(client, sport: str) -> list:
    """Fetch all rows for a sport with pagination."""
    rows = []
    offset = 0
    while True:
        resp = (
            client.table("daily_props")
            .select("id, game_date, player_name, prop_type, line, odds_type, is_smart_pick, ai_tier, created_at")
            .eq("sport", sport.upper())
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def find_stale(rows: list) -> tuple[list, list]:
    """
    Group by (game_date, player_name, prop_type).
    Within each group, keep best row; mark the rest as stale.

    Keep priority:
      1. is_smart_pick=True (always keep over non-smart)
      2. Most recent created_at (actual latest PP line, up or down)
      3. Non-null ai_tier as tiebreaker
    """
    groups = defaultdict(list)
    for row in rows:
        # odds_type distinguishes standard/goblin/demon — each can have a different valid line
        key = (row["game_date"], row["player_name"], row["prop_type"], row.get("odds_type") or "standard")
        groups[key].append(row)

    keep_ids = []
    stale_ids = []

    for key, group in groups.items():
        if len(group) == 1:
            keep_ids.append(group[0]["id"])
            continue

        # Sort: smart picks first, then most recent created_at, then has tier
        def sort_key(r):
            return (
                1 if r.get("is_smart_pick") else 0,
                r.get("created_at") or "",   # ISO string sorts correctly
                1 if r.get("ai_tier") else 0,
            )

        sorted_group = sorted(group, key=sort_key, reverse=True)
        keep_ids.append(sorted_group[0]["id"])
        stale_ids.extend(r["id"] for r in sorted_group[1:])

    return keep_ids, stale_ids


def delete_in_batches(client, ids: list, dry_run: bool, batch_size: int = 100) -> int:
    """Delete rows by id list. Returns count deleted."""
    if not ids:
        return 0
    if dry_run:
        return len(ids)

    deleted = 0
    for i in range(0, len(ids), batch_size):
        batch = ids[i : i + batch_size]
        client.table("daily_props").delete().in_("id", batch).execute()
        deleted += len(batch)
        print(f"  Deleted {deleted}/{len(ids)}...", end="\r")
    print()
    return deleted


def run(sports: list, dry_run: bool):
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    mode = "DRY RUN" if dry_run else "EXECUTE"
    print(f"\n=== Stale Row Purge [{mode}] ===\n")

    total_stale = 0
    total_kept = 0

    for sport in sports:
        print(f"[{sport.upper()}] Fetching all rows...")
        rows = fetch_all(client, sport)
        print(f"[{sport.upper()}] Total rows: {len(rows):,}")

        keep_ids, stale_ids = find_stale(rows)
        total_stale += len(stale_ids)
        total_kept += len(keep_ids)

        print(f"[{sport.upper()}] Keep: {len(keep_ids):,} | Stale: {len(stale_ids):,}")

        if stale_ids and not dry_run:
            print(f"[{sport.upper()}] Deleting {len(stale_ids):,} stale rows...")
            deleted = delete_in_batches(client, stale_ids, dry_run=False)
            print(f"[{sport.upper()}] Deleted {deleted:,} rows.")
        elif stale_ids:
            print(f"[{sport.upper()}] Would delete {len(stale_ids):,} rows (dry-run).")
        else:
            print(f"[{sport.upper()}] No stale rows found.")

        # Show a sample of stale rows for sanity check
        if stale_ids and dry_run:
            stale_rows = [r for r in rows if r["id"] in set(stale_ids[:10])]
            if stale_rows:
                print(f"\n  Sample stale rows ({sport.upper()}):")
                for r in stale_rows[:5]:
                    smart = "SMART" if r.get("is_smart_pick") else "     "
                    print(f"    [{smart}] {r['game_date']} | {r['player_name']:<25} | {r['prop_type']:<15} | line={r['line']}")

        print()

    print(f"--- Summary ---")
    print(f"Total kept : {total_kept:,}")
    print(f"Total stale: {total_stale:,}")
    if dry_run:
        print(f"\nRun with --execute to delete {total_stale:,} stale rows.")
    else:
        print(f"\nPurge complete.")


def main():
    parser = argparse.ArgumentParser(description="Purge stale daily_props rows from Supabase")
    parser.add_argument("--sport", choices=["nba", "nhl", "mlb"], help="Sport to purge (default: nba + nhl)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Show what would be deleted (default)")
    parser.add_argument("--execute", action="store_true", help="Actually delete rows")
    args = parser.parse_args()

    dry_run = not args.execute

    if args.sport:
        sports = [args.sport]
    else:
        sports = ["nba", "nhl"]

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY not set.")
        sys.exit(1)

    run(sports, dry_run=dry_run)


if __name__ == "__main__":
    main()
