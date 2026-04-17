"""
Seed the DuckDB `players` table with player_id -> name mappings.

Sources (in priority order):
  1. Main MLB SQLite DB  (mlb/database/mlb_predictions.db) — player_game_logs
  2. pybaseball chadwick_register()                        — fills any gaps

Usage:
    python -m ml.build_players          # seed / refresh from both sources
    python -m ml.build_players --check  # print coverage stats, no writes
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

# Path resolution — this module lives in mlb_feature_store/ml/
_REPO_ROOT = Path(__file__).parent.parent.parent          # SportsPredictor/
_MLB_DB    = _REPO_ROOT / "mlb" / "database" / "mlb_predictions.db"

from feature_store.build_duckdb import get_connection, initialize_schema


# ---------------------------------------------------------------------------
# Source 1 — Main MLB SQLite DB
# ---------------------------------------------------------------------------

def _load_from_main_db() -> pd.DataFrame:
    """Pull distinct player_id + player_name from player_game_logs."""
    try:
        import sqlite3
        conn = sqlite3.connect(str(_MLB_DB))
        df = pd.read_sql_query(
            """
            SELECT DISTINCT
                CAST(player_id AS TEXT) AS player_id,
                player_name,
                player_type
            FROM player_game_logs
            WHERE player_id IS NOT NULL AND player_name IS NOT NULL
            """,
            conn,
        )
        conn.close()
        df["player_id"] = df["player_id"].astype(str)
        print(f"  Main MLB DB: {len(df):,} players loaded")
        return df
    except Exception as e:
        print(f"  Main MLB DB: FAILED — {e}")
        return pd.DataFrame(columns=["player_id", "player_name", "player_type"])


# ---------------------------------------------------------------------------
# Source 2 — pybaseball chadwick register
# ---------------------------------------------------------------------------

def _load_from_chadwick(missing_ids: set[str]) -> pd.DataFrame:
    """
    Pull name mappings for `missing_ids` from pybaseball chadwick_register.

    The chadwick register maps MLBAM IDs (key_mlbam) to player names.
    """
    if not missing_ids:
        return pd.DataFrame(columns=["player_id", "player_name", "player_type"])

    try:
        from pybaseball import chadwick_register
        print(f"  Fetching chadwick register for {len(missing_ids)} missing players ...")
        cw = chadwick_register()
        # Filter to the IDs we need
        cw["key_mlbam"] = cw["key_mlbam"].astype("Int64").astype(str)
        cw = cw[cw["key_mlbam"].isin(missing_ids)].copy()
        cw["player_name"] = (
            cw["name_first"].fillna("").str.strip()
            + " "
            + cw["name_last"].fillna("").str.strip()
        ).str.strip()
        cw = cw[cw["player_name"] != ""][["key_mlbam", "player_name"]].rename(
            columns={"key_mlbam": "player_id"}
        )
        cw["player_type"] = None
        print(f"  Chadwick: {len(cw):,} additional players found")
        return cw
    except ImportError:
        print("  pybaseball not installed — skipping chadwick fallback")
        return pd.DataFrame(columns=["player_id", "player_name", "player_type"])
    except Exception as e:
        print(f"  Chadwick: FAILED — {e}")
        return pd.DataFrame(columns=["player_id", "player_name", "player_type"])


# ---------------------------------------------------------------------------
# Coverage check
# ---------------------------------------------------------------------------

def _check_coverage(conn) -> None:
    """Print coverage stats: how many feature store player_ids have a name."""
    total_hitters  = conn.execute("SELECT COUNT(DISTINCT player_id) FROM hitter_labels").fetchone()[0]
    total_pitchers = conn.execute("SELECT COUNT(DISTINCT player_id) FROM pitcher_labels").fetchone()[0]
    named          = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]

    all_ids = set(
        r[0] for r in conn.execute(
            "SELECT DISTINCT player_id FROM hitter_labels "
            "UNION SELECT DISTINCT player_id FROM pitcher_labels"
        ).fetchall()
    )
    named_ids = set(r[0] for r in conn.execute("SELECT player_id FROM players").fetchall())
    covered = len(all_ids & named_ids)
    total   = len(all_ids)

    print(f"\nPlayer coverage:")
    print(f"  Unique hitter IDs in feature store:  {total_hitters:,}")
    print(f"  Unique pitcher IDs in feature store: {total_pitchers:,}")
    print(f"  Total distinct IDs:                  {total:,}")
    print(f"  Named in players table:              {named:,}")
    print(f"  Coverage:                            {covered}/{total} ({100*covered/total:.1f}%)")

    if covered < total:
        missing = all_ids - named_ids
        print(f"\n  Missing IDs (first 10): {sorted(missing)[:10]}")


# ---------------------------------------------------------------------------
# Main upsert
# ---------------------------------------------------------------------------

def build_players(check_only: bool = False) -> None:
    conn = get_connection()
    initialize_schema(conn)

    if check_only:
        _check_coverage(conn)
        conn.close()
        return

    print("Building player lookup table ...")

    # Source 1: main MLB DB
    df1 = _load_from_main_db()

    # Determine which IDs are still missing
    all_ids = set(
        r[0] for r in conn.execute(
            "SELECT DISTINCT player_id FROM hitter_labels "
            "UNION SELECT DISTINCT player_id FROM pitcher_labels"
        ).fetchall()
    )
    covered = set(df1["player_id"].tolist())
    missing = all_ids - covered

    # Source 2: chadwick for gaps
    df2 = _load_from_chadwick(missing)

    # Merge — df1 takes priority
    combined = pd.concat([df1, df2], ignore_index=True)
    combined = combined.drop_duplicates(subset=["player_id"], keep="first")
    combined["updated_at"] = datetime.utcnow().isoformat()

    # Upsert into DuckDB
    conn.execute("DELETE FROM players WHERE player_id IN (SELECT player_id FROM combined)")
    cols = "player_id, player_name, player_type, updated_at"
    conn.execute(f"INSERT INTO players ({cols}) SELECT {cols} FROM combined")

    print(f"  Upserted {len(combined):,} players into DuckDB players table")
    _check_coverage(conn)
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Seed MLB player name lookup")
    parser.add_argument("--check", action="store_true", help="Print coverage stats only")
    args = parser.parse_args()
    build_players(check_only=args.check)


if __name__ == "__main__":
    main()
