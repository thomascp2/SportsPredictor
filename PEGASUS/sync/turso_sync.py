#!/usr/bin/env python3
"""
PEGASUS/sync/turso_sync.py

Syncs PEGASUS-enriched picks to per-sport Turso databases.
Writes to the `pegasus_picks` table — separate from the existing `predictions` table,
so it never conflicts with the production Turso sync layer.

Design rules:
  - NON-FATAL: all errors are logged to console, never re-raised to caller
  - Per-sport credentials: TURSO_{SPORT}_URL / TURSO_{SPORT}_TOKEN (same env vars as production)
  - Upsert key: (player_name, prop, game_date, sport) via UNIQUE constraint + INSERT OR REPLACE
  - Follows the same libsql_client / batch / retry pattern as sync/turso_sync.py
  - Called from run_daily.py after JSON write step

Usage (standalone, for testing):
    python PEGASUS/sync/turso_sync.py --date 2026-04-15
    python PEGASUS/sync/turso_sync.py --date 2026-04-15 --sport nba
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths + .env loader
# ---------------------------------------------------------------------------

_SYNC_DIR     = Path(__file__).resolve().parent           # PEGASUS/sync/
_PEGASUS_ROOT = _SYNC_DIR.parent                          # PEGASUS/
_REPO_ROOT    = _PEGASUS_ROOT.parent                      # SportsPredictor/

# Load .env from repo root (same approach as sync/turso_sync.py)
_env_path = _REPO_ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import libsql_client
    _LIBSQL_AVAILABLE = True
except ImportError:
    libsql_client = None  # type: ignore
    _LIBSQL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE      = 100
REQUEST_TIMEOUT = 30.0
MAX_RETRIES     = 3

PEGASUS_VERSION = "step8"

_SPORT_CREDS: dict[str, dict[str, str]] = {
    "nhl": {"url_env": "TURSO_NHL_URL",  "token_env": "TURSO_NHL_TOKEN"},
    "nba": {"url_env": "TURSO_NBA_URL",  "token_env": "TURSO_NBA_TOKEN"},
    "mlb": {"url_env": "TURSO_MLB_URL",  "token_env": "TURSO_MLB_TOKEN"},
}

# DDL — idempotent, runs before every sync to ensure table exists
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pegasus_picks (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date              TEXT    NOT NULL,
    player_name            TEXT    NOT NULL,
    team                   TEXT,
    sport                  TEXT    NOT NULL,
    prop                   TEXT    NOT NULL,
    line                   REAL,
    direction              TEXT,
    odds_type              TEXT,
    raw_stat_probability   REAL,
    ml_probability         REAL,
    blended_probability    REAL,
    calibrated_probability REAL,
    break_even             REAL,
    ai_edge                REAL,
    vs_naive_edge          REAL,
    tier                   TEXT,
    situation_flag         TEXT,
    situation_modifier     REAL,
    situation_notes        TEXT,
    model_version          TEXT,
    source_prediction_id   INTEGER,
    usage_boost            INTEGER,
    implied_probability    REAL,
    true_ev                REAL,
    game_context_flag      TEXT    DEFAULT 'NEUTRAL',
    game_context_notes     TEXT    DEFAULT '',
    pegasus_version        TEXT    DEFAULT 'step8',
    synced_at              TEXT,
    UNIQUE(player_name, prop, game_date, sport)
)
"""

# Upsert SQL — INSERT OR REPLACE so re-runs overwrite stale data
_UPSERT_SQL = """
INSERT OR REPLACE INTO pegasus_picks (
    game_date, player_name, team, sport, prop, line, direction, odds_type,
    raw_stat_probability, ml_probability, blended_probability, calibrated_probability,
    break_even, ai_edge, vs_naive_edge, tier,
    situation_flag, situation_modifier, situation_notes,
    model_version, source_prediction_id, usage_boost,
    implied_probability, true_ev,
    game_context_flag, game_context_notes,
    pegasus_version, synced_at
) VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?,
    ?, ?, ?, ?,
    ?, ?, ?,
    ?, ?, ?,
    ?, ?,
    ?, ?,
    ?, ?
)
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(name: str) -> str:
    """ASCII-safe player name for Windows cp1252 print output."""
    return name.encode("ascii", "replace").decode("ascii")


def _turso_client(sport: str):
    creds = _SPORT_CREDS[sport]
    url   = os.getenv(creds["url_env"], "").replace("libsql://", "https://")
    token = os.getenv(creds["token_env"], "")
    if not url or not token:
        raise RuntimeError(
            f"Missing Turso credentials for {sport.upper()} "
            f"({creds['url_env']} / {creds['token_env']} not set)"
        )
    return libsql_client.create_client(url=url, auth_token=token)


async def _batch_execute(client, stmts: list) -> None:
    """Execute a list of statements with retry on timeout / network error."""
    for attempt in range(MAX_RETRIES):
        try:
            await asyncio.wait_for(client.batch(stmts), timeout=REQUEST_TIMEOUT)
            return
        except (asyncio.TimeoutError, Exception) as exc:
            if attempt == MAX_RETRIES - 1:
                raise
            print(f"    [WARN] Retry {attempt + 1}/{MAX_RETRIES} after: {exc}")
            await asyncio.sleep(2)


def _pick_to_row(pick: dict, synced_at: str) -> list:
    """Map a pick dict to the ordered value list for _UPSERT_SQL."""
    return [
        pick.get("game_date"),
        pick.get("player_name"),
        pick.get("team"),
        pick.get("sport"),
        pick.get("prop"),
        pick.get("line"),
        pick.get("direction"),
        pick.get("odds_type"),
        pick.get("raw_stat_probability"),
        pick.get("ml_probability"),
        pick.get("blended_probability"),
        pick.get("calibrated_probability"),
        pick.get("break_even"),
        pick.get("ai_edge"),
        pick.get("vs_naive_edge"),
        pick.get("tier"),
        pick.get("situation_flag"),
        pick.get("situation_modifier"),
        pick.get("situation_notes"),
        pick.get("model_version"),
        pick.get("source_prediction_id"),
        1 if pick.get("usage_boost") else 0,
        pick.get("implied_probability"),
        pick.get("true_ev"),
        pick.get("game_context_flag", "NEUTRAL"),
        pick.get("game_context_notes", ""),
        PEGASUS_VERSION,
        synced_at,
    ]


# ---------------------------------------------------------------------------
# Per-sport async core
# ---------------------------------------------------------------------------

async def _sync_sport(picks: list[dict], sport: str) -> int:
    """
    Upsert picks for a single sport into its Turso DB.
    Creates the `pegasus_picks` table if it does not exist.
    Returns number of rows upserted.
    """
    if not picks:
        print(f"  [PEGASUS/{sport.upper()}] No picks to sync.")
        return 0

    client    = _turso_client(sport)
    synced_at = datetime.now(timezone.utc).isoformat()

    try:
        # Ensure table exists (idempotent)
        await asyncio.wait_for(client.execute(_CREATE_TABLE_SQL), timeout=REQUEST_TIMEOUT)

        # Build statement list
        stmts = [
            libsql_client.Statement(_UPSERT_SQL, _pick_to_row(p, synced_at))
            for p in picks
        ]

        upserted = 0
        for i in range(0, len(stmts), BATCH_SIZE):
            batch = stmts[i : i + BATCH_SIZE]
            await _batch_execute(client, batch)
            upserted += len(batch)
            print(
                f"  [PEGASUS/{sport.upper()}] pegasus_picks: {upserted}/{len(stmts)}...",
                end="\r",
                flush=True,
            )

        print(f"\n  [PEGASUS/{sport.upper()}] pegasus_picks: {upserted} rows upserted.")
        return upserted

    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_to_turso(
    picks: list,
    game_date: str,
    sports: Optional[list[str]] = None,
) -> dict[str, int]:
    """
    Sync a list of PEGASUS picks to Turso. NON-FATAL — errors log to console,
    never propagate to the caller.

    Args:
        picks:     List of PEGASUSPick dataclass instances or plain dicts.
        game_date: YYYY-MM-DD string (used for logging; each pick already carries it).
        sports:    Sports to sync. Defaults to all sports found in the picks list.

    Returns:
        Dict mapping sport -> rows upserted (0 on error / no picks for that sport).
    """
    if not _LIBSQL_AVAILABLE:
        print(
            "[PEGASUS/turso_sync] WARNING: libsql-client not installed — "
            "Turso sync skipped. Run: pip install libsql-client"
        )
        return {}

    # Normalize: accept PEGASUSPick dataclasses or plain dicts
    pick_dicts: list[dict] = []
    for p in picks:
        if is_dataclass(p) and not isinstance(p, type):
            pick_dicts.append(asdict(p))
        elif isinstance(p, dict):
            pick_dicts.append(p)
        else:
            try:
                pick_dicts.append(vars(p))
            except TypeError:
                pass  # skip unserializable objects

    if sports is None:
        present = {p.get("sport") for p in pick_dicts if p.get("sport")}
        sports  = [s for s in ["nhl", "nba", "mlb"] if s in present]

    results: dict[str, int] = {}

    async def _run_all() -> None:
        for sport in sports:
            if sport not in _SPORT_CREDS:
                print(f"  [PEGASUS/{sport.upper()}] No Turso config — skipping.")
                results[sport] = 0
                continue

            sport_picks = [p for p in pick_dicts if p.get("sport") == sport]
            try:
                n = await _sync_sport(sport_picks, sport)
                results[sport] = n
            except Exception as exc:
                print(f"  [PEGASUS/{sport.upper()}] Turso sync FAILED (non-fatal): {exc}")
                results[sport] = 0

    asyncio.run(_run_all())
    return results


# ---------------------------------------------------------------------------
# Standalone CLI (for testing)
# ---------------------------------------------------------------------------

def _main_cli() -> None:
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(
        description="PEGASUS Turso sync — push today's JSON snapshot to Turso"
    )
    parser.add_argument("--date",  default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--sport", default="all", choices=["nhl", "nba", "mlb", "all"])
    args = parser.parse_args()

    game_date = args.date or date.today().isoformat()
    picks_file = _PEGASUS_ROOT / "data" / "picks" / f"picks_{game_date}.json"

    if not picks_file.exists():
        print(f"[PEGASUS/turso_sync] No snapshot found: {picks_file}")
        print(f"  Run: python PEGASUS/run_daily.py --date {game_date}")
        sys.exit(1)

    payload = json.loads(picks_file.read_text(encoding="utf-8"))
    picks   = payload.get("picks", [])

    sports = ["nhl", "nba", "mlb"] if args.sport == "all" else [args.sport]

    print(f"\n[PEGASUS] Turso sync — {game_date}  ({len(picks)} picks from snapshot)\n")
    results = sync_to_turso(picks, game_date, sports)

    total = sum(results.values())
    print(f"\n[PEGASUS] Sync complete: {total} rows upserted")
    for sport, n in results.items():
        print(f"  {sport.upper()}: {n}")


if __name__ == "__main__":
    _main_cli()
