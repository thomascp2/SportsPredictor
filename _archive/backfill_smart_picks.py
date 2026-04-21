#!/usr/bin/env python3
"""
Backfill Smart Pick History: Supabase -> SQLite
================================================
Reads is_smart_pick=True rows from Supabase daily_props and backfills them
into the local SQLite predictions tables.

- ADDITIVE ONLY: never modifies or deletes Supabase data.
- For existing SQLite rows: sets is_smart_pick=1 and ai_tier.
- For rows missing from SQLite: inserts a minimal row from Supabase data.
- Dedup key: (game_date, player_name, prop_type, line)
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sync.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, NHL_DB_PATH, NBA_DB_PATH, MLB_DB_PATH
from supabase import create_client

PAGE_SIZE = 1000


def fetch_all_smart_picks(client, sport: str) -> list:
    """Fetch all is_smart_pick=True rows for sport, paginating past 1000-row cap."""
    print(f"  Fetching {sport} smart picks from Supabase...")
    rows = []
    offset = 0
    while True:
        resp = (
            client.table("daily_props")
            .select(
                "game_date,player_name,team,opponent,prop_type,line,"
                "ai_prediction,ai_probability,ai_tier,ai_edge,odds_type,"
                "actual_value,result,graded_at,created_at"
            )
            .eq("is_smart_pick", True)
            .eq("sport", sport)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = resp.data
        rows.extend(batch)
        print(f"    ...fetched {len(rows):,} so far (batch size {len(batch)})")
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def ensure_columns(conn: sqlite3.Connection, sport: str):
    """Add is_smart_pick and ai_tier columns if they don't exist."""
    c = conn.cursor()
    c.execute("PRAGMA table_info(predictions)")
    existing = {r[1] for r in c.fetchall()}
    added = []
    if "is_smart_pick" not in existing:
        c.execute("ALTER TABLE predictions ADD COLUMN is_smart_pick INTEGER DEFAULT 0")
        added.append("is_smart_pick INTEGER DEFAULT 0")
    if "ai_tier" not in existing:
        c.execute("ALTER TABLE predictions ADD COLUMN ai_tier TEXT DEFAULT NULL")
        added.append("ai_tier TEXT DEFAULT NULL")
    if added:
        conn.commit()
        print(f"  Added columns to {sport} predictions: {', '.join(added)}")
    else:
        print(f"  Columns already present in {sport} predictions.")


def backfill_sport(client, sport: str, db_path: str) -> dict:
    """
    Backfill smart picks for one sport.
    Returns stats: {updated, inserted, skipped}.
    """
    print(f"\n{'='*60}")
    print(f"  BACKFILL: {sport}")
    print(f"{'='*60}")

    # Fetch from Supabase
    rows = fetch_all_smart_picks(client, sport)
    print(f"  Total smart picks from Supabase: {len(rows):,}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Count before — check column existence first
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM predictions")
    count_before = c.fetchone()[0]
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(predictions)").fetchall()}
    smart_before = 0
    if "is_smart_pick" in existing_cols:
        c.execute("SELECT COUNT(*) FROM predictions WHERE is_smart_pick=1")
        smart_before = c.fetchone()[0]

    print(f"  SQLite rows before: {count_before:,} total, {smart_before:,} already marked smart")

    # Ensure columns exist
    ensure_columns(conn, sport)
    c = conn.cursor()
    # Re-read columns after potential ALTER TABLE
    all_cols = {r[1] for r in conn.execute("PRAGMA table_info(predictions)").fetchall()}

    updated = 0
    inserted = 0
    skipped = 0

    for row in rows:
        gd = row["game_date"]
        pn = row["player_name"]
        pt = row["prop_type"]
        ln = row["line"]
        ai_tier = row.get("ai_tier")
        ai_pred = row.get("ai_prediction")
        ai_prob = row.get("ai_probability")

        # Try to find existing SQLite row
        c.execute(
            "SELECT id, is_smart_pick FROM predictions "
            "WHERE game_date=? AND player_name=? AND prop_type=? AND line=?",
            (gd, pn, pt, ln),
        )
        existing = c.fetchall()

        if existing:
            # Update all matching rows (usually just 1, but could be multiple batches)
            c.execute(
                "UPDATE predictions SET is_smart_pick=1, ai_tier=? "
                "WHERE game_date=? AND player_name=? AND prop_type=? AND line=?",
                (ai_tier, gd, pn, pt, ln),
            )
            updated += len(existing)
        else:
            # Row missing from SQLite — insert minimal record from Supabase data
            team = row.get("team", "")
            opp = row.get("opponent", "")
            created = row.get("created_at", datetime.now().isoformat())
            # confidence_tier only exists in NHL schema
            if "confidence_tier" in all_cols:
                c.execute(
                    """INSERT OR IGNORE INTO predictions
                       (game_date, player_name, team, opponent, prop_type, line,
                        prediction, probability, confidence_tier,
                        is_smart_pick, ai_tier, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (gd, pn, team, opp, pt, ln,
                     ai_pred, ai_prob, ai_tier,
                     ai_tier, created),
                )
            else:
                c.execute(
                    """INSERT OR IGNORE INTO predictions
                       (game_date, player_name, team, opponent, prop_type, line,
                        prediction, probability,
                        is_smart_pick, ai_tier, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (gd, pn, team, opp, pt, ln,
                     ai_pred, ai_prob,
                     ai_tier, created),
                )
            if c.rowcount > 0:
                inserted += 1
            else:
                skipped += 1

        # Commit in batches
        if (updated + inserted + skipped) % 5000 == 0:
            conn.commit()
            print(f"    ...{updated+inserted+skipped:,} processed (updated={updated:,}, inserted={inserted:,}, skipped={skipped:,})")

    conn.commit()

    # Count after
    c.execute("SELECT COUNT(*) FROM predictions")
    count_after = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM predictions WHERE is_smart_pick=1")
    smart_after = c.fetchone()[0]

    conn.close()

    print(f"\n  Results for {sport}:")
    print(f"    Supabase smart picks processed : {len(rows):,}")
    print(f"    SQLite rows updated (marked)   : {updated:,}")
    print(f"    SQLite rows inserted (missing) : {inserted:,}")
    print(f"    Skipped (INSERT OR IGNORE dup) : {skipped:,}")
    print(f"    SQLite total rows  before->after: {count_before:,} -> {count_after:,}")
    print(f"    SQLite smart picks before->after: {smart_before:,} -> {smart_after:,}")

    return {
        "sport": sport,
        "supabase_rows": len(rows),
        "updated": updated,
        "inserted": inserted,
        "skipped": skipped,
        "count_before": count_before,
        "count_after": count_after,
        "smart_before": smart_before,
        "smart_after": smart_after,
    }


def main():
    print("Supabase -> SQLite Smart Pick Backfill")
    print(f"Run at: {datetime.now().isoformat()}")
    print()

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--sport', choices=['nhl', 'nba', 'mlb', 'all'], default='all',
                        help='Sport to backfill (default: all)')
    args = parser.parse_args()
    run_sports = [args.sport.upper()] if args.sport != 'all' else ['NHL', 'NBA', 'MLB']

    results = []
    sport_dbs = {'NHL': NHL_DB_PATH, 'NBA': NBA_DB_PATH, 'MLB': MLB_DB_PATH}

    for sport in run_sports:
        db = os.path.normpath(sport_dbs[sport])
        print(f"{sport} DB: {db}")
        r = backfill_sport(client, sport, db)
        results.append(r)
        if sport != run_sports[-1]:
            print(f"\n{sport} done. Proceeding...\n")

    # Summary
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    for r in results:
        print(f"{r['sport']}:")
        print(f"  Supabase rows   : {r['supabase_rows']:,}")
        print(f"  Updated         : {r['updated']:,}")
        print(f"  Inserted (new)  : {r['inserted']:,}")
        print(f"  Skipped (dup)   : {r['skipped']:,}")
        print(f"  Smart picks     : {r['smart_before']:,} -> {r['smart_after']:,}")
        print(f"  Total SQLite    : {r['count_before']:,} -> {r['count_after']:,}")
        print()


if __name__ == "__main__":
    main()
