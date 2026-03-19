"""
NHL features_json Backfill Migration
=====================================

Rewrites legacy NHL features_json keys to the canonical f_ prefix schema
defined in shared/canonical_schema.py.

Safe to run multiple times — already-canonical records are detected by the
presence of any 'f_' prefixed key and skipped.

Usage:
    cd /path/to/SportsPredictor
    python shared/migrate_features_schema.py [--dry-run]
"""

import sqlite3
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.canonical_schema import normalize_features_json


NHL_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'nhl', 'database', 'nhl_predictions_v2.db')
DRY_RUN = '--dry-run' in sys.argv


def migrate():
    db_path = os.path.normpath(NHL_DB_PATH)
    if not os.path.exists(db_path):
        print(f"[ERROR] NHL DB not found at: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id, prop_type, features_json FROM predictions WHERE features_json IS NOT NULL")
    rows = cursor.fetchall()

    total = len(rows)
    updated = 0
    skipped_canonical = 0
    skipped_empty = 0
    errors = 0

    print(f"[MIGRATE] NHL predictions to process: {total:,}")
    if DRY_RUN:
        print("[MIGRATE] DRY RUN — no changes will be written\n")

    for row_id, prop_type, features_json_raw in rows:
        if not features_json_raw:
            skipped_empty += 1
            continue

        try:
            features = json.loads(features_json_raw)
        except json.JSONDecodeError:
            errors += 1
            continue

        # Skip if already canonical (any f_ prefixed key present)
        if any(k.startswith('f_') for k in features):
            skipped_canonical += 1
            continue

        normalized = normalize_features_json(features, sport='nhl', prop_type=prop_type or '')

        if not DRY_RUN:
            cursor.execute(
                "UPDATE predictions SET features_json = ? WHERE id = ?",
                (json.dumps(normalized), row_id)
            )
        updated += 1

    if not DRY_RUN:
        conn.commit()
        print(f"[MIGRATE] Committed {updated:,} updated records")
    else:
        print(f"[MIGRATE] Would update {updated:,} records (dry run)")

    conn.close()

    print(f"\n[SUMMARY]")
    print(f"  Total rows:          {total:,}")
    print(f"  Updated:             {updated:,}")
    print(f"  Already canonical:   {skipped_canonical:,}")
    print(f"  Empty features_json: {skipped_empty:,}")
    print(f"  Parse errors:        {errors:,}")
    print(f"\n  Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == '__main__':
    migrate()
