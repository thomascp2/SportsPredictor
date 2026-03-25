#!/usr/bin/env python3
"""
supabase_local_sync.py
======================

Standalone script that reads local SQLite databases and upserts their data
to Supabase so the cloud dashboard (Streamlit Community Cloud) can serve
them without local filesystem access.

Usage:
    python shared/supabase_local_sync.py --all
    python shared/supabase_local_sync.py --hits-blocks
    python shared/supabase_local_sync.py --season-proj
    python shared/supabase_local_sync.py --szln

Credentials (priority order):
    1. SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY env vars
    2. SUPABASE_URL + SUPABASE_KEY env vars
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from typing import Optional

# Resolve project root (this file lives in shared/)
ROOT = Path(__file__).parent.parent


# ── Supabase client ───────────────────────────────────────────────────────────

def _get_supabase_client():
    """Return a Supabase client or raise RuntimeError if credentials missing."""
    try:
        from supabase import create_client
    except ImportError:
        raise RuntimeError(
            "supabase-py not installed. Run: pip install supabase"
        )

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") or os.getenv("SUPABASE_KEY", "")

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) "
            "environment variables must be set."
        )

    return create_client(url, key)


def _upsert_batches(sb, table: str, rows: list, batch_size: int = 500,
                    on_conflict: str = None, verbose: bool = True) -> int:
    """Upsert rows in batches. Returns total rows upserted."""
    if not rows:
        return 0

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        q = sb.table(table).upsert(batch)
        if on_conflict:
            q = q.on_conflict(on_conflict)
        q.execute()
        total += len(batch)
        if verbose:
            print(f"  [{table}] Upserted {total}/{len(rows)} rows...")

    return total


# ── Sync: NHL Hits & Blocks ───────────────────────────────────────────────────

def sync_hits_blocks(sb=None, verbose: bool = True) -> dict:
    """
    Read nhl/database/hits_blocks.db → daily_picks table and upsert to
    Supabase table nhl_hits_blocks_picks.

    Unique key: run_date
    """
    db_path = ROOT / "nhl" / "database" / "hits_blocks.db"
    if not db_path.exists():
        msg = f"hits_blocks.db not found at {db_path}"
        if verbose:
            print(f"[sync_hits_blocks] SKIP: {msg}")
        return {"success": False, "skipped": True, "reason": msg}

    if sb is None:
        sb = _get_supabase_client()

    try:
        conn = sqlite3.connect(str(db_path))
        rows_raw = conn.execute(
            "SELECT run_date, generated_at, raw_output, model, "
            "prompt_tokens, completion_tokens, games_count, odds_source "
            "FROM daily_picks ORDER BY run_date"
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"success": False, "error": str(e)}

    if not rows_raw:
        if verbose:
            print("[sync_hits_blocks] No rows to sync.")
        return {"success": True, "synced": 0}

    rows = [
        {
            "run_date":          r[0],
            "generated_at":      r[1],
            "raw_output":        r[2],
            "model":             r[3] or "",
            "prompt_tokens":     r[4] or 0,
            "completion_tokens": r[5] or 0,
            "games_count":       r[6] or 0,
            "odds_source":       r[7] or "grok_search",
        }
        for r in rows_raw
    ]

    if verbose:
        print(f"[sync_hits_blocks] Syncing {len(rows)} rows → nhl_hits_blocks_picks")

    try:
        synced = _upsert_batches(sb, "nhl_hits_blocks_picks", rows,
                                 on_conflict="run_date", verbose=verbose)
        return {"success": True, "synced": synced}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Sync: MLB Season Projections ──────────────────────────────────────────────

def sync_season_projections(sb=None, verbose: bool = True) -> dict:
    """
    Read mlb/database/mlb_predictions.db → season_projections (current season)
    and upsert to Supabase table mlb_season_projections.

    Unique key: (season, player_name, stat)
    """
    db_path = ROOT / "mlb" / "database" / "mlb_predictions.db"
    if not db_path.exists():
        msg = f"mlb_predictions.db not found at {db_path}"
        if verbose:
            print(f"[sync_season_projections] SKIP: {msg}")
        return {"success": False, "skipped": True, "reason": msg}

    if sb is None:
        sb = _get_supabase_client()

    try:
        conn = sqlite3.connect(str(db_path))
        rows_raw = conn.execute(
            """
            SELECT season, player_name, player_id, team, player_type,
                   stat, projection, std_dev, confidence, seasons_used,
                   age, method, created_at
            FROM season_projections
            WHERE season = (SELECT MAX(season) FROM season_projections)
            ORDER BY player_name, stat
            """
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"success": False, "error": str(e)}

    if not rows_raw:
        if verbose:
            print("[sync_season_projections] No rows to sync.")
        return {"success": True, "synced": 0}

    rows = [
        {
            "season":       r[0],
            "player_name":  r[1],
            "player_id":    r[2],
            "team":         r[3],
            "player_type":  r[4],
            "stat":         r[5],
            "projection":   r[6],
            "std_dev":      r[7],
            "confidence":   r[8],
            "seasons_used": r[9],
            "age":          r[10],
            "method":       r[11] or "marcel",
            "created_at":   r[12],
        }
        for r in rows_raw
    ]

    if verbose:
        print(f"[sync_season_projections] Syncing {len(rows)} rows → mlb_season_projections")

    try:
        synced = _upsert_batches(sb, "mlb_season_projections", rows,
                                 on_conflict="season,player_name,stat",
                                 verbose=verbose)
        return {"success": True, "synced": synced}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Sync: MLB SZLN ML Picks ───────────────────────────────────────────────────

def sync_szln_picks(sb=None, verbose: bool = True) -> dict:
    """
    Read mlb/database/mlb_predictions.db → season_prop_ml_picks
    (current season, latest fetched_at only) and upsert to Supabase
    table mlb_szln_picks.

    Unique key: (season, player_name, stat, fetched_at)
    """
    db_path = ROOT / "mlb" / "database" / "mlb_predictions.db"
    if not db_path.exists():
        msg = f"mlb_predictions.db not found at {db_path}"
        if verbose:
            print(f"[sync_szln_picks] SKIP: {msg}")
        return {"success": False, "skipped": True, "reason": msg}

    if sb is None:
        sb = _get_supabase_client()

    try:
        conn = sqlite3.connect(str(db_path))

        # Check table exists
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='season_prop_ml_picks'"
        ).fetchone()
        if not exists:
            conn.close()
            if verbose:
                print("[sync_szln_picks] season_prop_ml_picks table not found — skipping.")
            return {"success": True, "skipped": True, "reason": "table not found"}

        # Only latest batch for current season
        latest_fetch = conn.execute(
            "SELECT MAX(fetched_at) FROM season_prop_ml_picks "
            "WHERE season = (SELECT MAX(season) FROM season_prop_ml_picks)"
        ).fetchone()[0]

        if not latest_fetch:
            conn.close()
            if verbose:
                print("[sync_szln_picks] No SZLN picks to sync.")
            return {"success": True, "synced": 0}

        rows_raw = conn.execute(
            """
            SELECT season, fetched_at, player_name, player_id, team,
                   player_type, stat, pp_stat_type, line, odds_type,
                   direction, probability, edge, projection, std_dev,
                   confidence, model_used, key_factors, recommendation,
                   created_at
            FROM season_prop_ml_picks
            WHERE fetched_at = ?
            ORDER BY player_name, stat
            """,
            (latest_fetch,)
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"success": False, "error": str(e)}

    if not rows_raw:
        if verbose:
            print("[sync_szln_picks] No rows to sync.")
        return {"success": True, "synced": 0}

    rows = [
        {
            "season":          r[0],
            "fetched_at":      r[1],
            "player_name":     r[2],
            "player_id":       r[3],
            "team":            r[4],
            "player_type":     r[5],
            "stat":            r[6],
            "pp_stat_type":    r[7],
            "line":            r[8],
            "odds_type":       r[9],
            "direction":       r[10],
            "probability":     r[11],
            "edge":            r[12],
            "projection":      r[13],
            "std_dev":         r[14],
            "confidence":      r[15],
            "model_used":      r[16],
            "key_factors":     r[17],
            "recommendation":  r[18],
            "created_at":      r[19],
        }
        for r in rows_raw
    ]

    if verbose:
        print(f"[sync_szln_picks] Syncing {len(rows)} rows → mlb_szln_picks "
              f"(fetched_at={latest_fetch[:19]})")

    try:
        synced = _upsert_batches(sb, "mlb_szln_picks", rows,
                                 on_conflict="season,player_name,stat,fetched_at",
                                 verbose=verbose)
        return {"success": True, "synced": synced}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── sync_all ──────────────────────────────────────────────────────────────────

def sync_all(verbose: bool = True) -> dict:
    """Run all three sync functions. Returns summary dict."""
    try:
        sb = _get_supabase_client()
    except RuntimeError as e:
        print(f"[sync_all] ERROR: {e}")
        return {"success": False, "error": str(e)}

    results = {}

    if verbose:
        print("\n[sync_all] Starting full Supabase sync...")
        print("-" * 50)

    r1 = sync_hits_blocks(sb=sb, verbose=verbose)
    results["hits_blocks"] = r1
    if verbose:
        status = "OK" if r1.get("success") else "FAILED"
        print(f"  hits_blocks: {status} — {r1.get('synced', 0)} rows")

    if verbose:
        print()
    r2 = sync_season_projections(sb=sb, verbose=verbose)
    results["season_projections"] = r2
    if verbose:
        status = "OK" if r2.get("success") else "FAILED"
        print(f"  season_projections: {status} — {r2.get('synced', 0)} rows")

    if verbose:
        print()
    r3 = sync_szln_picks(sb=sb, verbose=verbose)
    results["szln_picks"] = r3
    if verbose:
        status = "OK" if r3.get("success") else "FAILED"
        print(f"  szln_picks: {status} — {r3.get('synced', 0)} rows")

    overall = all(r.get("success") for r in results.values())
    results["success"] = overall

    if verbose:
        print("-" * 50)
        print(f"[sync_all] Done. Overall: {'SUCCESS' if overall else 'PARTIAL FAILURE'}")

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sync local SQLite data to Supabase for cloud dashboard."
    )
    parser.add_argument("--all", action="store_true",
                        help="Run all sync functions")
    parser.add_argument("--hits-blocks", action="store_true",
                        help="Sync NHL hits & blocks picks")
    parser.add_argument("--season-proj", action="store_true",
                        help="Sync MLB season projections")
    parser.add_argument("--szln", action="store_true",
                        help="Sync MLB SZLN ML picks")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress verbose output")

    args = parser.parse_args()
    verbose = not args.quiet

    if not any([args.all, args.hits_blocks, args.season_proj, args.szln]):
        parser.print_help()
        sys.exit(0)

    if args.all:
        result = sync_all(verbose=verbose)
        sys.exit(0 if result.get("success") else 1)

    try:
        sb = _get_supabase_client()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    exit_code = 0

    if args.hits_blocks:
        r = sync_hits_blocks(sb=sb, verbose=verbose)
        if not r.get("success") and not r.get("skipped"):
            exit_code = 1

    if args.season_proj:
        r = sync_season_projections(sb=sb, verbose=verbose)
        if not r.get("success") and not r.get("skipped"):
            exit_code = 1

    if args.szln:
        r = sync_szln_picks(sb=sb, verbose=verbose)
        if not r.get("success") and not r.get("skipped"):
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
