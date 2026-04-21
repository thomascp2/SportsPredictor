#!/usr/bin/env python3
"""
Turso Sync — SQLite -> Turso (redundant write layer)
=====================================================
Mirrors prediction data to Turso alongside Supabase.
Writes to the same SQLite-schema tables already migrated by turso_migrate.py.

Operations:
  predictions  — insert new prediction rows for a date
  smart-picks  — update is_smart_pick / ai_tier / ai_edge on existing rows
  grading      — insert prediction_outcomes after grading runs
  all          — predictions + smart-picks + grading

Usage:
    python -m sync.turso_sync --sport nhl --operation predictions
    python -m sync.turso_sync --sport all --operation all
    python -m sync.turso_sync --sport nba --operation smart-picks --date 2026-04-06
"""

import os
import sys
import re
import asyncio
import sqlite3
import argparse
import unicodedata
from datetime import date
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "gsd_module"))

# Load .env
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

from sync.config import NHL_DB_PATH, NBA_DB_PATH, MLB_DB_PATH, GOLF_DB_PATH

BATCH_SIZE = 200          # INSERT batches (fast)
SMART_PICKS_BATCH_SIZE = 50  # UPDATE batches (slower — smaller to avoid timeout)
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3

SPORT_CONFIG = {
    'nhl':  {'db': str(NHL_DB_PATH),  'url_env': 'TURSO_NHL_URL',  'token_env': 'TURSO_NHL_TOKEN'},
    'nba':  {'db': str(NBA_DB_PATH),  'url_env': 'TURSO_NBA_URL',  'token_env': 'TURSO_NBA_TOKEN'},
    'mlb':  {'db': str(MLB_DB_PATH),  'url_env': 'TURSO_MLB_URL',  'token_env': 'TURSO_MLB_TOKEN'},
    'golf': {'db': str(GOLF_DB_PATH), 'url_env': 'TURSO_GOLF_URL', 'token_env': 'TURSO_GOLF_TOKEN'},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(name: str) -> str:
    """ASCII-safe version of a player name for print/log output (Windows cp1252 fix)."""
    return name.encode('ascii', 'replace').decode('ascii')


def _normalize_name(name: str) -> str:
    """Strip diacritics: Stützle -> Stutzle, Doncic == Doncic."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', name)
        if unicodedata.category(c) != 'Mn'
    )


def _turso_client(sport: str):
    cfg = SPORT_CONFIG[sport]
    url = os.getenv(cfg['url_env'], '').replace('libsql://', 'https://')
    token = os.getenv(cfg['token_env'], '')
    if not url or not token:
        raise RuntimeError(f"Missing Turso credentials for {sport.upper()} — check .env")
    return libsql_client.create_client(url=url, auth_token=token)


async def _batch_execute(client, stmts: list):
    """Execute a batch of statements with retry on timeout/network error."""
    for attempt in range(MAX_RETRIES):
        try:
            await asyncio.wait_for(client.batch(stmts), timeout=REQUEST_TIMEOUT)
            return
        except (asyncio.TimeoutError, Exception) as e:
            if attempt == MAX_RETRIES - 1:
                raise
            print(f"    [WARN] Retry {attempt+1}/{MAX_RETRIES} after: {e}")
            await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# sync_predictions — insert new prediction rows
# ---------------------------------------------------------------------------

async def sync_predictions(sport: str, game_date: str):
    """
    Insert predictions for game_date from SQLite into Turso.
    Uses INSERT OR IGNORE — safe to re-run, won't duplicate.
    """
    cfg = SPORT_CONFIG[sport]
    db_path = cfg['db']

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT * FROM predictions WHERE game_date = ?", (game_date,)
    ).fetchall()
    conn.close()

    if not rows:
        print(f"  [{sport.upper()}] No predictions in SQLite for {game_date} — skipping.")
        return 0

    cols = list(rows[0].keys())
    col_list = ', '.join(f'"{c}"' for c in cols)
    placeholders = ', '.join(['?' for _ in cols])
    sql = f'INSERT OR IGNORE INTO predictions ({col_list}) VALUES ({placeholders})'

    client = _turso_client(sport)
    inserted = 0
    try:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            stmts = [libsql_client.Statement(sql, list(r)) for r in batch]
            await _batch_execute(client, stmts)
            inserted += len(batch)
            print(f"  [{sport.upper()}] predictions: {inserted}/{len(rows)}...", end='\r', flush=True)
        print(f"\n  [{sport.upper()}] predictions: {inserted} rows synced to Turso.")
    finally:
        await client.close()

    return inserted


# ---------------------------------------------------------------------------
# sync_smart_picks — update is_smart_pick / ai_tier / ai_edge
# ---------------------------------------------------------------------------

async def sync_smart_picks(sport: str, game_date: str):
    """
    Update is_smart_pick, ai_tier, ai_edge in Turso to match SQLite for game_date.
    Matches on (game_date, player_name, prop_type, line) — same key as upsert conflict.

    Encoding: normalizes player names on both sides so diacritics never cause a miss.
    """
    cfg = SPORT_CONFIG[sport]
    conn = sqlite3.connect(cfg['db'])

    # Only fetch rows that have smart pick data set
    rows = conn.execute('''
        SELECT player_name, prop_type, line, is_smart_pick, ai_tier, odds_type,
               ai_edge, ai_ev_2leg, ai_ev_3leg, ai_ev_4leg
        FROM predictions
        WHERE game_date = ?
          AND is_smart_pick IS NOT NULL
    ''', (game_date,)).fetchall()
    conn.close()

    if not rows:
        print(f"  [{sport.upper()}] No smart pick data in SQLite for {game_date} — skipping.")
        return 0

    client = _turso_client(sport)
    updated = 0
    try:
        # Two-pass update: exact name match + normalized name match for diacritics.
        # Turso doesn't support user-defined functions, so we push both variants.
        # pass 1: exact (e.g. stored as "Stützle")
        # pass 2: normalized (e.g. stored as "Stutzle" from an older sync)
        stmts_exact = []
        stmts_norm = []
        update_sql = '''UPDATE predictions
                        SET is_smart_pick = ?,
                            ai_tier = ?,
                            odds_type = ?,
                            ai_edge = ?,
                            ai_ev_2leg = ?,
                            ai_ev_3leg = ?,
                            ai_ev_4leg = ?
                        WHERE game_date = ?
                          AND player_name = ?
                          AND prop_type = ?
                          AND line = ?'''
        for row in rows:
            player_name, prop_type, line, is_smart, ai_tier, odds_type, \
                ai_edge, ai_ev_2leg, ai_ev_3leg, ai_ev_4leg = row
            norm = _normalize_name(player_name)
            vals = [is_smart, ai_tier, odds_type or 'standard',
                    ai_edge, ai_ev_2leg, ai_ev_3leg, ai_ev_4leg,
                    game_date, player_name, prop_type, line]
            stmts_exact.append(libsql_client.Statement(update_sql, vals))
            # Also push normalized variant for diacritics stored without accents
            if norm != player_name:
                vals_norm = [is_smart, ai_tier, odds_type or 'standard',
                             ai_edge, ai_ev_2leg, ai_ev_3leg, ai_ev_4leg,
                             game_date, norm, prop_type, line]
                stmts_norm.append(libsql_client.Statement(update_sql, vals_norm))

        all_stmts = stmts_exact + stmts_norm
        total = len(all_stmts)
        # Chunk into batches, then run up to 5 batches concurrently
        batches = [all_stmts[i:i + SMART_PICKS_BATCH_SIZE]
                   for i in range(0, total, SMART_PICKS_BATCH_SIZE)]
        CONCURRENCY = 5
        for wave_start in range(0, len(batches), CONCURRENCY):
            wave = batches[wave_start:wave_start + CONCURRENCY]
            await asyncio.gather(*[_batch_execute(client, b) for b in wave])
            updated += sum(len(b) for b in wave)
            print(f"  [{sport.upper()}] smart-picks: {updated}/{total}...", end='\r', flush=True)

        print(f"\n  [{sport.upper()}] smart-picks: {len(rows)} rows updated in Turso.")
    finally:
        await client.close()

    return len(rows)


# ---------------------------------------------------------------------------
# sync_grading — insert prediction_outcomes after grading
# ---------------------------------------------------------------------------

async def sync_grading(sport: str, game_date: str):
    """
    Insert prediction_outcomes for game_date from SQLite into Turso.
    Also updates prediction_outcomes and any graded columns on predictions.
    """
    cfg = SPORT_CONFIG[sport]
    conn = sqlite3.connect(cfg['db'])
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT * FROM prediction_outcomes WHERE game_date = ?", (game_date,)
    ).fetchall()
    conn.close()

    if not rows:
        print(f"  [{sport.upper()}] No grading data in SQLite for {game_date} — skipping.")
        return 0

    cols = list(rows[0].keys())
    col_list = ', '.join(f'"{c}"' for c in cols)
    placeholders = ', '.join(['?' for _ in cols])
    sql = f'INSERT OR IGNORE INTO prediction_outcomes ({col_list}) VALUES ({placeholders})'

    client = _turso_client(sport)
    inserted = 0
    try:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            stmts = [libsql_client.Statement(sql, list(r)) for r in batch]
            await _batch_execute(client, stmts)
            inserted += len(batch)
            print(f"  [{sport.upper()}] grading: {inserted}/{len(rows)}...", end='\r', flush=True)
        print(f"\n  [{sport.upper()}] grading: {inserted} rows synced to Turso.")
    finally:
        await client.close()

    return inserted


# ---------------------------------------------------------------------------
# sync_game_predictions — push game_predictions table to Turso
# ---------------------------------------------------------------------------

async def sync_game_predictions(sport: str, game_date: str):
    """
    Insert game_predictions rows for game_date from SQLite into Turso.
    Creates the table if it doesn't exist. Uses INSERT OR IGNORE.
    Supports NHL, NBA, MLB (golf has no game_predictions table).
    """
    cfg = SPORT_CONFIG.get(sport)
    if not cfg:
        return 0

    db_path = cfg['db']
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM game_predictions WHERE game_date = ?", (game_date,)
        ).fetchall()
        conn.close()
    except Exception:
        return 0

    if not rows:
        return 0

    cols = list(rows[0].keys())
    col_list = ', '.join(f'"{c}"' for c in cols)
    placeholders = ', '.join(['?' for _ in cols])

    # Ensure table exists in Turso with id as primary key for dedup
    col_defs = ', '.join(
        f'"{c}" {"INTEGER PRIMARY KEY" if c == "id" else "TEXT"}' for c in cols
    )
    create_sql = f'CREATE TABLE IF NOT EXISTS game_predictions ({col_defs})'
    insert_sql = f'INSERT OR IGNORE INTO game_predictions ({col_list}) VALUES ({placeholders})'

    client = _turso_client(sport)
    inserted = 0
    try:
        await client.execute(create_sql)
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            stmts = [libsql_client.Statement(insert_sql, list(r)) for r in batch]
            await _batch_execute(client, stmts)
            inserted += len(batch)
        print(f"  [{sport.upper()}] game_predictions: {inserted} rows synced to Turso.")
    finally:
        await client.close()

    return inserted


# ---------------------------------------------------------------------------
# sync_game_prediction_outcomes — push grading results to Turso
# ---------------------------------------------------------------------------

async def sync_game_prediction_outcomes(sport: str, game_date: str):
    """
    Upsert game_prediction_outcomes rows for game_date from SQLite into Turso.
    Uses INSERT OR REPLACE so re-grading overwrites stale rows.
    Supports NHL, NBA, MLB.
    """
    cfg = SPORT_CONFIG.get(sport)
    if not cfg:
        return 0

    db_path = cfg['db']
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM game_prediction_outcomes WHERE game_date = ?", (game_date,)
        ).fetchall()
        conn.close()
    except Exception:
        return 0

    if not rows:
        return 0

    cols = list(rows[0].keys())
    col_list = ', '.join(f'"{c}"' for c in cols)
    placeholders = ', '.join(['?' for _ in cols])

    col_defs = ', '.join(
        f'"{c}" {"INTEGER PRIMARY KEY" if c == "id" else "TEXT"}' for c in cols
    )
    create_sql = f'CREATE TABLE IF NOT EXISTS game_prediction_outcomes ({col_defs})'
    upsert_sql = f'INSERT OR REPLACE INTO game_prediction_outcomes ({col_list}) VALUES ({placeholders})'

    client = _turso_client(sport)
    inserted = 0
    try:
        await client.execute(create_sql)
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            stmts = [libsql_client.Statement(upsert_sql, list(r)) for r in batch]
            await _batch_execute(client, stmts)
            inserted += len(batch)
        print(f"  [{sport.upper()}] game_prediction_outcomes: {inserted} rows synced to Turso.")
    finally:
        await client.close()

    return inserted


# ---------------------------------------------------------------------------
# sync_game_times — populate game_time on predictions from prizepicks_lines.db
# ---------------------------------------------------------------------------

async def sync_game_times(sport: str, game_date: str):
    """
    Update predictions.game_time in Turso using PrizePicks start_time data.
    Replaces the supabase_sync.sync_game_times() role for Turso.
    Reads shared/prizepicks_lines.db, groups by team, pushes earliest start_time.
    """
    import os as _os
    pp_db_candidates = [
        str(Path(__file__).parent.parent / 'shared' / 'prizepicks_lines.db'),
        str(Path(__file__).parent.parent / 'data' / 'prizepicks_lines.db'),
    ]
    pp_db = next((p for p in pp_db_candidates if Path(p).exists()), None)
    if not pp_db:
        print(f"  [{sport.upper()}] game-times: prizepicks_lines.db not found — skipping.")
        return 0

    league_map = {'nhl': 'NHL', 'nba': 'NBA', 'mlb': 'MLB', 'golf': 'PGA'}
    league = league_map.get(sport.lower(), sport.upper())

    pp_conn = sqlite3.connect(pp_db)
    team_times = {}
    try:
        rows = pp_conn.execute(
            "SELECT team, MIN(start_time) as start_time "
            "FROM prizepicks_lines "
            "WHERE fetch_date = ? AND league = ? AND start_time IS NOT NULL "
            "GROUP BY team",
            (game_date, league)
        ).fetchall()
        team_times = {r[0]: r[1] for r in rows if r[1]}
    finally:
        pp_conn.close()

    if not team_times:
        print(f"  [{sport.upper()}] game-times: no PP lines for {game_date} — skipping.")
        return 0

    client = _turso_client(sport)
    updated = 0
    try:
        stmts = []
        for team, game_time in team_times.items():
            stmts.append(libsql_client.Statement(
                "UPDATE predictions SET game_time = ? WHERE game_date = ? AND team = ?",
                [game_time, game_date, team]
            ))
        if stmts:
            await _batch_execute(client, stmts)
            updated = len(stmts)
        print(f"  [{sport.upper()}] game-times: {updated} teams updated in Turso.")
    finally:
        await client.close()

    return updated


# ---------------------------------------------------------------------------
# sync_game_scores — upsert live game scores into Turso game_scores table
# (replaces Supabase daily_games; called by game_sync.py)
# ---------------------------------------------------------------------------

GAME_SCORES_DDL = '''
CREATE TABLE IF NOT EXISTS game_scores (
    game_date  TEXT NOT NULL,
    sport      TEXT NOT NULL,
    game_id    TEXT NOT NULL,
    home_team  TEXT,
    away_team  TEXT,
    home_score INTEGER,
    away_score INTEGER,
    status     TEXT,
    period     TEXT,
    clock      TEXT,
    start_time TEXT,
    broadcast  TEXT,
    PRIMARY KEY (game_date, sport, game_id)
)
'''

async def sync_game_scores(sport: str, games: list):
    """
    Upsert a list of game score dicts into Turso game_scores table.
    Called directly by game_sync.py instead of Supabase.
    games: list of dicts with keys matching game_scores schema.
    """
    if not games:
        return 0

    client = _turso_client(sport)
    inserted = 0
    try:
        await client.execute(GAME_SCORES_DDL)
        cols = ['game_date', 'sport', 'game_id', 'home_team', 'away_team',
                'home_score', 'away_score', 'status', 'period', 'clock',
                'start_time', 'broadcast']
        col_list = ', '.join(cols)
        placeholders = ', '.join(['?' for _ in cols])
        upsert_sql = (f'INSERT OR REPLACE INTO game_scores ({col_list}) '
                      f'VALUES ({placeholders})')
        stmts = []
        for g in games:
            vals = [g.get(c) for c in cols]
            stmts.append(libsql_client.Statement(upsert_sql, vals))
        for i in range(0, len(stmts), BATCH_SIZE):
            await _batch_execute(client, stmts[i:i + BATCH_SIZE])
            inserted += len(stmts[i:i + BATCH_SIZE])
        print(f"  [{sport.upper()}] game-scores: {inserted} rows synced to Turso.")
    finally:
        await client.close()

    return inserted


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def run_sync(sports: list, operation: str, game_date: str):
    print(f"\n=== Turso Sync [{operation.upper()}] {game_date} ===\n")

    for sport in sports:
        print(f"[{sport.upper()}]")
        try:
            if operation in ('predictions', 'all'):
                await sync_predictions(sport, game_date)
            if operation in ('smart-picks', 'all'):
                await sync_smart_picks(sport, game_date)
            if operation in ('grading', 'all'):
                await sync_grading(sport, game_date)
            if operation in ('game-predictions', 'all'):
                await sync_game_predictions(sport, game_date)
            if operation in ('game-outcomes', 'all'):
                await sync_game_prediction_outcomes(sport, game_date)
            if operation in ('game-times', 'all'):
                await sync_game_times(sport, game_date)
        except Exception as e:
            pname = sport.upper()
            print(f"  [{pname}] ERROR: {e}")

    print("\n=== Turso Sync complete ===")


def main():
    parser = argparse.ArgumentParser(description="Sync SQLite predictions to Turso")
    parser.add_argument('--sport', default='all',
                        choices=['nhl', 'nba', 'mlb', 'golf', 'all'])
    parser.add_argument('--operation', default='all',
                        choices=['predictions', 'smart-picks', 'grading', 'game-predictions',
                                 'game-outcomes', 'game-times', 'all'])
    parser.add_argument('--date', default=None,
                        help="Date to sync (default: today, YYYY-MM-DD)")
    args = parser.parse_args()

    game_date = args.date or date.today().isoformat()
    sports = list(SPORT_CONFIG.keys()) if args.sport == 'all' else [args.sport]

    asyncio.run(run_sync(sports, args.operation, game_date))


if __name__ == '__main__':
    main()
