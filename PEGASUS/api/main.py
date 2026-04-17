#!/usr/bin/env python3
"""
PEGASUS/api/main.py

FastAPI server for PEGASUS picks — the mobile-facing endpoint layer.

Mobile reads from THIS API, not from Supabase daily_props.
PEGASUS writes to Turso → mobile hits this FastAPI → clean, enriched picks.

Data source priority:
  1. Turso pegasus_picks table (live, always fresh)
  2. JSON snapshot fallback (PEGASUS/data/picks/picks_{date}.json)

Endpoints:
  GET /picks/{date}                   All picks for a date
  GET /picks/{date}/{player_name}     Single player lookup
  GET /health                         System health + last snapshot date

Query parameters for /picks/{date}:
  sport=nba|nhl|mlb                   Filter by sport
  min_tier=T1-ELITE|T2-STRONG|...     Minimum tier
  direction=OVER|UNDER                Filter by direction
  limit=50                            Max picks to return (default 100)

Port: 8600
Run: uvicorn PEGASUS.api.main:app --port 8600 --reload

Notes:
  - Turso is read-only from this API (PEGASUS never writes via this layer)
  - All CORS origins allowed for mobile dev
  - All responses JSON; errors return {"error": "..."} with appropriate status
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths + env loader
# ---------------------------------------------------------------------------

_API_DIR      = Path(__file__).resolve().parent       # PEGASUS/api/
_PEGASUS_ROOT = _API_DIR.parent                        # PEGASUS/
_REPO_ROOT    = _PEGASUS_ROOT.parent                   # SportsPredictor/
_PICKS_DIR    = _PEGASUS_ROOT / "data" / "picks"

# Load .env from repo root
_env_path = _REPO_ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
except ImportError:
    raise RuntimeError(
        "FastAPI not installed. Run: pip install fastapi uvicorn"
    )

# ---------------------------------------------------------------------------
# Turso client (optional — falls back to JSON snapshots if unavailable)
# ---------------------------------------------------------------------------

try:
    import libsql_client
    _LIBSQL_AVAILABLE = True
except ImportError:
    libsql_client = None  # type: ignore
    _LIBSQL_AVAILABLE = False

_SPORT_CREDS: dict[str, dict[str, str]] = {
    "nhl": {"url_env": "TURSO_NHL_URL",  "token_env": "TURSO_NHL_TOKEN"},
    "nba": {"url_env": "TURSO_NBA_URL",  "token_env": "TURSO_NBA_TOKEN"},
    "mlb": {"url_env": "TURSO_MLB_URL",  "token_env": "TURSO_MLB_TOKEN"},
}

# Tier ordering for min_tier filter
_TIER_ORDER = {"T1-ELITE": 1, "T2-STRONG": 2, "T3-GOOD": 3, "T4-LEAN": 4, "T5-FADE": 5}

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title       = "PEGASUS Picks API",
    description = "Enriched player prop picks — calibrated probability, edge, tier, situational flags",
    version     = "1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # Allow all for mobile dev; restrict in production
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

async def _load_from_turso(sport: str, game_date: str) -> list[dict]:
    """
    Query Turso pegasus_picks for a sport + date.

    Returns list of row dicts, or [] on any error.
    """
    if not _LIBSQL_AVAILABLE:
        return []

    creds = _SPORT_CREDS.get(sport.lower())
    if not creds:
        return []

    url   = os.getenv(creds["url_env"], "").replace("libsql://", "https://")
    token = os.getenv(creds["token_env"], "")
    if not url or not token:
        return []

    try:
        import asyncio
        client = libsql_client.create_client(url=url, auth_token=token)
        try:
            rs = await asyncio.wait_for(
                client.execute(
                    "SELECT * FROM pegasus_picks WHERE game_date = ? ORDER BY ai_edge DESC",
                    [game_date],
                ),
                timeout=15.0,
            )
            cols = [col.name for col in rs.columns]
            return [dict(zip(cols, row)) for row in rs.rows]
        finally:
            await client.close()
    except Exception as exc:
        print(f"[PEGASUS/api] Turso {sport.upper()} read failed: {exc}")
        return []


def _load_from_snapshot(game_date: str) -> list[dict]:
    """Load picks from the JSON daily snapshot."""
    snap = _PICKS_DIR / f"picks_{game_date}.json"
    if not snap.exists():
        return []
    try:
        payload = json.loads(snap.read_text(encoding="utf-8"))
        picks = payload.get("picks", [])
        # Ensure all picks have a game_date field
        for p in picks:
            p.setdefault("game_date", game_date)
        return picks
    except Exception as exc:
        print(f"[PEGASUS/api] Snapshot load failed ({snap}): {exc}")
        return []


async def _load_picks(game_date: str, sports: list[str]) -> list[dict]:
    """
    Load picks for given sports and date.

    Tries Turso first (live data), falls back to JSON snapshot.
    Returns merged and deduplicated list sorted by ai_edge desc.
    """
    all_picks: list[dict] = []

    # Try Turso for each sport
    turso_ok = False
    for sp in sports:
        rows = await _load_from_turso(sp, game_date)
        if rows:
            all_picks.extend(rows)
            turso_ok = True

    # Fall back to JSON snapshot if Turso returned nothing
    if not turso_ok:
        snap_picks = _load_from_snapshot(game_date)
        # Filter by requested sports
        all_picks = [p for p in snap_picks if p.get("sport", "").lower() in sports]

    # Sort by ai_edge descending
    all_picks.sort(key=lambda p: float(p.get("ai_edge") or 0), reverse=True)
    return all_picks


def _apply_filters(
    picks: list[dict],
    sport:     Optional[str],
    min_tier:  Optional[str],
    direction: Optional[str],
) -> list[dict]:
    """Apply optional query filters to a picks list."""
    if sport:
        picks = [p for p in picks if (p.get("sport") or "").lower() == sport.lower()]
    if direction:
        picks = [p for p in picks if (p.get("direction") or "").upper() == direction.upper()]
    if min_tier:
        min_rank = _TIER_ORDER.get(min_tier.upper(), 5)
        picks = [
            p for p in picks
            if _TIER_ORDER.get((p.get("tier") or "T5-FADE").upper(), 5) <= min_rank
        ]
    return picks


def _last_snapshot_date() -> Optional[str]:
    """Return the most recent picks snapshot date available."""
    if not _PICKS_DIR.exists():
        return None
    files = sorted(_PICKS_DIR.glob("picks_*.json"), reverse=True)
    if files:
        return files[0].stem.replace("picks_", "")
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    """
    PEGASUS API health check.

    Returns: system status, last snapshot date, pick counts per sport.
    """
    last_date = _last_snapshot_date()
    picks_by_sport: dict[str, int] = {}

    if last_date:
        snap = _load_from_snapshot(last_date)
        for p in snap:
            sp = (p.get("sport") or "unknown").lower()
            picks_by_sport[sp] = picks_by_sport.get(sp, 0) + 1

    return {
        "status":       "ok",
        "api_version":  "1.0.0",
        "turso_client": _LIBSQL_AVAILABLE,
        "last_snapshot": last_date,
        "picks_by_sport": picks_by_sport,
        "server_time":  datetime.now(timezone.utc).isoformat(),
    }


@app.get("/picks/{game_date}")
async def get_picks_for_date(
    game_date: str,
    sport:     Optional[str] = Query(None, description="Filter by sport: nba|nhl|mlb"),
    min_tier:  Optional[str] = Query(None, description="Min tier: T1-ELITE|T2-STRONG|T3-GOOD|T4-LEAN"),
    direction: Optional[str] = Query(None, description="Filter by direction: OVER|UNDER"),
    limit:     int           = Query(100, ge=1, le=500, description="Max picks to return"),
) -> dict:
    """
    Get all PEGASUS picks for a date.

    Reads from Turso (live) first; falls back to JSON snapshot.

    Returns:
        {
            "game_date": "2026-04-15",
            "sport_filter": "nba",
            "count": 42,
            "picks": [ ... ]
        }
    """
    # Validate date format
    try:
        datetime.strptime(game_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="game_date must be YYYY-MM-DD")

    # Determine sports to query
    valid_sports = ["nhl", "nba", "mlb"]
    if sport:
        if sport.lower() not in valid_sports:
            raise HTTPException(status_code=422, detail=f"sport must be one of {valid_sports}")
        sports = [sport.lower()]
    else:
        sports = valid_sports

    # Load and filter
    picks = await _load_picks(game_date, sports)
    picks = _apply_filters(picks, sport, min_tier, direction)

    # Apply limit
    picks = picks[:limit]

    return {
        "game_date":    game_date,
        "sport_filter": sport,
        "min_tier":     min_tier,
        "direction":    direction,
        "count":        len(picks),
        "picks":        picks,
    }


@app.get("/picks/{game_date}/{player_name}")
async def get_picks_for_player(
    game_date:   str,
    player_name: str,
    sport:       Optional[str] = Query(None, description="Optional sport filter"),
) -> dict:
    """
    Get all PEGASUS picks for a specific player on a date.

    Player name matching is case-insensitive and handles partial names.
    (e.g. "kawhi" matches "Kawhi Leonard")

    Returns:
        {
            "game_date": "2026-04-15",
            "player_query": "kawhi",
            "count": 3,
            "picks": [ ... ]
        }
    """
    try:
        datetime.strptime(game_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="game_date must be YYYY-MM-DD")

    valid_sports = ["nhl", "nba", "mlb"]
    sports = [sport.lower()] if sport and sport.lower() in valid_sports else valid_sports

    picks = await _load_picks(game_date, sports)

    # Match player name (case-insensitive, partial)
    query = player_name.lower().strip()
    picks = [
        p for p in picks
        if query in (p.get("player_name") or "").lower()
    ]

    return {
        "game_date":    game_date,
        "player_query": player_name,
        "count":        len(picks),
        "picks":        picks,
    }


# ---------------------------------------------------------------------------
# Dev runner (uvicorn direct)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print("\nStarting PEGASUS API on http://localhost:8600")
    print("Docs: http://localhost:8600/docs\n")
    uvicorn.run("PEGASUS.api.main:app", host="0.0.0.0", port=8600, reload=True)
