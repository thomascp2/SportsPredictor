#!/usr/bin/env python3
"""
Turso Migration — SQLite → Turso (libSQL)
==========================================
Migrates all four sport databases from local SQLite to Turso.
Safe to re-run: uses CREATE TABLE IF NOT EXISTS and INSERT OR IGNORE.

Usage:
    python sync/turso_migrate.py --dry-run          # show counts, test connection
    python sync/turso_migrate.py --sport nhl        # migrate one sport
    python sync/turso_migrate.py                    # migrate all four sports
    python sync/turso_migrate.py --table predictions --sport nba  # one table
"""

import os
import sys
import re
import asyncio
import sqlite3
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
_env_path = PROJECT_ROOT / '.env'
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, val = line.partition('=')
            os.environ.setdefault(key.strip(), val.strip())

try:
    import libsql_client
except ImportError:
    print("ERROR: libsql-client not installed. Run: pip install libsql-client")
    sys.exit(1)

BATCH_SIZE = 200

SKIP_TABLES = {'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4'}

SPORT_CONFIG = {
    'nhl': {
        'db': str(PROJECT_ROOT / 'nhl' / 'database' / 'nhl_predictions_v2.db'),
        'url': os.getenv('TURSO_NHL_URL', ''),
        'token': os.getenv('TURSO_NHL_TOKEN', ''),
    },
    'nba': {
        'db': str(PROJECT_ROOT / 'nba' / 'database' / 'nba_predictions.db'),
        'url': os.getenv('TURSO_NBA_URL', ''),
        'token': os.getenv('TURSO_NBA_TOKEN', ''),
    },
    'mlb': {
        'db': str(PROJECT_ROOT / 'mlb' / 'database' / 'mlb_predictions.db'),
        'url': os.getenv('TURSO_MLB_URL', ''),
        'token': os.getenv('TURSO_MLB_TOKEN', ''),
    },
    'golf': {
        'db': str(PROJECT_ROOT / 'golf' / 'database' / 'golf_predictions.db'),
        'url': os.getenv('TURSO_GOLF_URL', ''),
        'token': os.getenv('TURSO_GOLF_TOKEN', ''),
    },
}


def get_tables(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return [(table_name, create_sql)] for all non-internal tables."""
    cur = conn.cursor()
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
    return [(n, s) for n, s in cur.fetchall() if n not in SKIP_TABLES and s]


def get_indexes(conn: sqlite3.Connection) -> list[str]:
    """Return CREATE INDEX statements for all explicit indexes (not auto-generated)."""
    cur = conn.cursor()
    cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name"
    )
    # Convert to IF NOT EXISTS form for idempotency
    return [
        sql.replace('CREATE INDEX ', 'CREATE INDEX IF NOT EXISTS ', 1)
           .replace('CREATE UNIQUE INDEX ', 'CREATE UNIQUE INDEX IF NOT EXISTS ', 1)
        for (sql,) in cur.fetchall()
    ]


def make_create_if_not_exists(ddl: str) -> str:
    """Convert CREATE TABLE to CREATE TABLE IF NOT EXISTS, stripping FK constraints."""
    ddl = ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
    # Strip FK constraints — both standalone FOREIGN KEY lines and inline REFERENCES clauses
    lines = ddl.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip().upper()
        if stripped.startswith("FOREIGN KEY"):
            continue
        # Strip inline REFERENCES clause (e.g. "col INTEGER REFERENCES table(col),")
        line = re.sub(r'\s+REFERENCES\s+\w+\s*\(\s*\w+\s*\)', '', line, flags=re.IGNORECASE)
        cleaned.append(line)
    # Fix trailing commas before closing paren
    result = []
    for i, line in enumerate(cleaned):
        rest = [l.strip() for l in cleaned[i+1:] if l.strip()]
        if rest and rest[0] == ')' and line.rstrip().endswith(','):
            result.append(line.rstrip()[:-1])
        else:
            result.append(line)
    return '\n'.join(result)


def get_row_count(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
    return cur.fetchone()[0]


def get_local_col_types(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    """Return {col_name: col_type} for a local SQLite table."""
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    return {row[1]: (row[2] or 'TEXT') for row in cur.fetchall()}


async def fix_schema_sport(sport: str, cfg: dict, dry_run: bool):
    """
    Compare local SQLite schema against Turso and apply ALTER TABLE ADD COLUMN
    for any columns that exist locally but are missing from Turso.
    Safe to re-run; ADD COLUMN is idempotent (Turso returns an error we catch+skip).
    """
    db_path = cfg['db']
    url = cfg['url']
    token = cfg['token']

    if not url or not token:
        print(f"[{sport.upper()}] SKIP — credentials not set")
        return

    if not Path(db_path).exists():
        print(f"[{sport.upper()}] SKIP — SQLite DB not found: {db_path}")
        return

    http_url = url.replace("libsql://", "https://")
    sqlite_conn = sqlite3.connect(db_path)
    client = libsql_client.create_client(url=http_url, auth_token=token)

    try:
        tables = get_tables(sqlite_conn)
        any_drift = False

        for table_name, _ in tables:
            local_types = get_local_col_types(sqlite_conn, table_name)

            # Get Turso columns
            try:
                result = await client.execute(f'PRAGMA table_info("{table_name}")')
                turso_cols = {row[1] for row in result.rows}
            except Exception as e:
                print(f"  [{sport.upper()}] {table_name}: can't read Turso schema — {e}")
                continue

            missing = {c: t for c, t in local_types.items() if c not in turso_cols}
            if not missing:
                print(f"  [{sport.upper()}] {table_name}: OK (no drift)")
                continue

            any_drift = True
            for col, col_type in missing.items():
                alter_sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {col_type}'
                if dry_run:
                    print(f"  [{sport.upper()}] {table_name}: DRY RUN — {alter_sql}")
                else:
                    try:
                        await client.execute(alter_sql)
                        print(f"  [{sport.upper()}] {table_name}: added column '{col}' ({col_type})")
                    except Exception as e:
                        # Column may already exist in a partial migration — safe to skip
                        if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                            print(f"  [{sport.upper()}] {table_name}: '{col}' already exists — skipping")
                        else:
                            print(f"  [{sport.upper()}] {table_name}: ERROR adding '{col}' — {e}")

        if not any_drift:
            print(f"  [{sport.upper()}] All tables in sync — no migration needed.")

    finally:
        await client.close()
        sqlite_conn.close()


async def migrate_sport(sport: str, cfg: dict, dry_run: bool, only_table: str | None, reset: bool = False):
    db_path = cfg['db']
    url = cfg['url']
    token = cfg['token']

    if not url or not token:
        print(f"[{sport.upper()}] SKIP — TURSO_{sport.upper()}_URL or TOKEN not set in .env")
        return

    if not Path(db_path).exists():
        print(f"[{sport.upper()}] SKIP — SQLite DB not found: {db_path}")
        return

    # Force HTTP mode — replace libsql:// with https:// for REST transport
    http_url = url.replace("libsql://", "https://")
    print(f"\n[{sport.upper()}] Connecting to Turso: {http_url}")
    url = http_url
    sqlite_conn = sqlite3.connect(db_path)
    sqlite_conn.row_factory = sqlite3.Row

    tables = get_tables(sqlite_conn)
    if only_table:
        tables = [(n, s) for n, s in tables if n == only_table]
        if not tables:
            print(f"[{sport.upper()}] Table '{only_table}' not found.")
            sqlite_conn.close()
            return

    if dry_run:
        print(f"[{sport.upper()}] DRY RUN — tables to migrate:")
        total = 0
        for name, _ in tables:
            count = get_row_count(sqlite_conn, name)
            total += count
            print(f"  {name:<35} {count:>10,} rows")
        print(f"  {'TOTAL':<35} {total:>10,} rows")
        sqlite_conn.close()
        return

    client = libsql_client.create_client(url=url, auth_token=token)

    try:
        # Pass 1: optionally drop all tables, then create schemas
        if reset:
            print(f"  [{sport.upper()}] Dropping existing tables...")
            for table_name, _ in reversed(tables):  # reverse to respect FK order
                await client.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            print(f"  [{sport.upper()}] Tables dropped.")

        print(f"  [{sport.upper()}] Creating schemas (FK constraints stripped for import)...")
        for table_name, ddl in tables:
            create_sql = make_create_if_not_exists(ddl)
            await client.execute(create_sql)
        # Create explicit indexes (not auto-generated by UNIQUE constraints)
        indexes = get_indexes(sqlite_conn)
        for idx_sql in indexes:
            await client.execute(idx_sql)
        if indexes:
            print(f"  [{sport.upper()}] Created {len(indexes)} index(es).")
        print(f"  [{sport.upper()}] All schemas created.")

        # Pass 2: migrate data table by table
        for table_name, ddl in tables:
            row_count = get_row_count(sqlite_conn, table_name)
            if row_count == 0:
                print(f"  [{sport.upper()}] {table_name} — no data, skipping.")
                continue

            print(f"  [{sport.upper()}] {table_name} ({row_count:,} rows)...")

            cur = sqlite_conn.cursor()
            cur.execute(f'SELECT * FROM "{table_name}" LIMIT 1')
            if cur.description is None:
                continue
            cols = [d[0] for d in cur.description]
            placeholders = ', '.join(['?' for _ in cols])
            col_list = ', '.join([f'"{c}"' for c in cols])
            insert_sql = f'INSERT OR IGNORE INTO "{table_name}" ({col_list}) VALUES ({placeholders})'

            cur.execute(f'SELECT * FROM "{table_name}"')
            inserted = 0
            while True:
                batch = cur.fetchmany(BATCH_SIZE)
                if not batch:
                    break
                stmts = [
                    libsql_client.Statement(insert_sql, list(row))
                    for row in batch
                ]
                # Retry up to 3 times on network errors
                for attempt in range(3):
                    try:
                        await asyncio.wait_for(client.batch(stmts), timeout=30.0)
                        break
                    except (asyncio.TimeoutError, Exception) as e:
                        if attempt == 2:
                            raise
                        print(f"\n    Retry {attempt+1}/3 after error: {e}")
                        await asyncio.sleep(2)
                inserted += len(batch)
                print(f"    {inserted:,}/{row_count:,}...", end='\r', flush=True)

            print(f"\n  [{sport.upper()}] {table_name} — {inserted:,} rows migrated.")

    finally:
        await client.close()
        sqlite_conn.close()

    print(f"[{sport.upper()}] Migration complete.")


async def main_async(sports: list[str], dry_run: bool, only_table: str | None,
                     reset: bool = False, fix_schema: bool = False):
    if fix_schema:
        mode = "DRY RUN" if dry_run else "FIX SCHEMA"
        print(f"\n=== Turso Schema Fix [{mode}] ===")
        for sport in sports:
            cfg = SPORT_CONFIG[sport]
            await fix_schema_sport(sport, cfg, dry_run=dry_run)
        print("\n=== Done ===")
        return

    mode = "DRY RUN" if dry_run else "MIGRATE"
    print(f"\n=== Turso Migration [{mode}] ===")

    for sport in sports:
        cfg = SPORT_CONFIG[sport]
        await migrate_sport(sport, cfg, dry_run=dry_run, only_table=only_table, reset=reset)

    print("\n=== Done ===")


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite → Turso")
    parser.add_argument("--sport", choices=["nhl", "nba", "mlb", "golf"],
                        help="Sport to migrate (default: all)")
    parser.add_argument("--table", help="Migrate only this table name")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Show row counts and test connection without writing")
    parser.add_argument("--reset", action="store_true", default=False,
                        help="Drop all tables before migrating (clean slate)")
    parser.add_argument("--fix-schema", action="store_true", default=False,
                        help="Detect schema drift and apply ALTER TABLE ADD COLUMN for missing cols")
    args = parser.parse_args()

    sports = [args.sport] if args.sport else ["nhl", "nba", "mlb", "golf"]
    asyncio.run(main_async(
        sports,
        dry_run=args.dry_run,
        only_table=args.table,
        reset=args.reset,
        fix_schema=args.fix_schema,
    ))


if __name__ == "__main__":
    main()
