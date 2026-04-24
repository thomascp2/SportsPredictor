#!/usr/bin/env python3
"""
One-off: push updated data_quality_flag values from local SQLite -> Turso.

The normal grading sync uses INSERT OR IGNORE so it never updates existing rows.
This script runs a targeted UPDATE for every prediction_outcomes row where
data_quality_flag IS NOT NULL, so the cloud dashboard reflects the correct values.

Usage:
    python tools/sync_data_quality_flags.py
    python tools/sync_data_quality_flags.py --sport nba
"""

import os
import sys
import asyncio
import sqlite3
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_env_path = PROJECT_ROOT / '.env'
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            os.environ.setdefault(k.strip(), v.strip())

try:
    import libsql_client
except ImportError:
    print("ERROR: libsql-client not installed. Run: pip install libsql-client")
    sys.exit(1)

from sync.config import NHL_DB_PATH, NBA_DB_PATH, MLB_DB_PATH

SPORT_CONFIG = {
    'nhl': {'db': str(NHL_DB_PATH), 'url_env': 'TURSO_NHL_URL', 'token_env': 'TURSO_NHL_TOKEN'},
    'nba': {'db': str(NBA_DB_PATH), 'url_env': 'TURSO_NBA_URL', 'token_env': 'TURSO_NBA_TOKEN'},
    'mlb': {'db': str(MLB_DB_PATH), 'url_env': 'TURSO_MLB_URL', 'token_env': 'TURSO_MLB_TOKEN'},
}

BATCH_SIZE = 200


def _turso_client(sport: str):
    cfg = SPORT_CONFIG[sport]
    url = os.getenv(cfg['url_env'], '').replace('libsql://', 'https://')
    token = os.getenv(cfg['token_env'], '')
    return libsql_client.create_client(url=url, auth_token=token)


async def _batch_execute(client, stmts, max_retries=3):
    for attempt in range(max_retries):
        try:
            await client.batch(stmts)
            return
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            print(f"  [WARN] Retry {attempt+1}/{max_retries}: {e}")
            await asyncio.sleep(2 ** attempt)


async def sync_flags_for_sport(sport: str):
    cfg = SPORT_CONFIG[sport]
    conn = sqlite3.connect(cfg['db'])
    conn.row_factory = sqlite3.Row

    # Detect primary key column (id or prediction_id)
    cols_info = conn.execute("PRAGMA table_info(prediction_outcomes)").fetchall()
    col_names = [c['name'] for c in cols_info]
    pk = 'id' if 'id' in col_names else 'prediction_id'

    rows = conn.execute(
        f"SELECT {pk}, data_quality_flag FROM prediction_outcomes WHERE data_quality_flag IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        print(f"  [{sport.upper()}] No flagged rows — nothing to sync.")
        return

    print(f"  [{sport.upper()}] {len(rows)} flagged rows to update in Turso...")

    client = _turso_client(sport)
    updated = 0
    try:
        # Add column if it doesn't exist yet in Turso
        try:
            await client.execute(
                'ALTER TABLE prediction_outcomes ADD COLUMN data_quality_flag TEXT'
            )
            print(f"  [{sport.upper()}] Added data_quality_flag column to Turso.")
        except Exception:
            pass  # Column already exists

        sql = f'UPDATE prediction_outcomes SET data_quality_flag = ? WHERE {pk} = ?'
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            stmts = [
                libsql_client.Statement(sql, [r['data_quality_flag'], r[pk]])
                for r in batch
            ]
            await _batch_execute(client, stmts)
            updated += len(batch)
            print(f"  [{sport.upper()}] {updated}/{len(rows)}...", end='\r', flush=True)
        print(f"\n  [{sport.upper()}] Done — {updated} rows updated.")
    finally:
        await client.close()


async def main(sports):
    for sport in sports:
        await sync_flags_for_sport(sport)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sport', default='all', choices=['nhl', 'nba', 'mlb', 'all'])
    args = parser.parse_args()

    sports = list(SPORT_CONFIG.keys()) if args.sport == 'all' else [args.sport]
    asyncio.run(main(sports))
