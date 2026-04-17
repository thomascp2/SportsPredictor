#!/usr/bin/env python3
"""
PEGASUS/pipeline/prizepicks_client.py

In-memory PrizePicks line fetcher for PEGASUS.

Key differences from shared/prizepicks_client.py:
  - NO SQLite storage — pure in-memory, per-session cache
  - Clean PEGASUS-friendly return types (PPLine dataclass, lookup dicts)
  - Name normalization built in — diacritics, initials, whitespace
  - Line-movement detection: compare live PP line vs stored SQLite line
  - Covers NHL, NBA, MLB in one fetch call

Design:
  - Non-fatal: any fetch failure returns empty dict, logs to console
  - Rate-limited: 2s minimum between requests (same as shared client)
  - One cache per (sport, date) per process — call get_lines() once, reuse

Usage:
    from PEGASUS.pipeline.prizepicks_client import get_lines, match_pick

    lines = get_lines("nba", "2026-04-15")
    # → {norm_key: PPLine, ...}

    pp_line = match_pick(pick, lines)
    if pp_line:
        if abs(pp_line.line - pick.line) > 0.01:
            print(f"Line moved: {pick.line} -> {pp_line.line}")
"""
from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    requests = None  # type: ignore
    _REQUESTS_AVAILABLE = False

# ---------------------------------------------------------------------------
# PPLine dataclass
# ---------------------------------------------------------------------------

@dataclass
class PPLine:
    """A single PrizePicks line for a player prop."""
    player_name:  str
    prop:         str           # normalized to our prop type (e.g. "points", "hits")
    line:         float
    odds_type:    str           # standard / goblin / demon
    sport:        str           # nhl / nba / mlb
    start_time:   str           # ISO string
    raw_stat_type: str          # original PrizePicks stat_type string
    is_promo:     bool = False

    @property
    def norm_key(self) -> str:
        """Lookup key: normalized_player_name:prop"""
        return f"{_norm(self.player_name)}:{self.prop}"


# ---------------------------------------------------------------------------
# Stat-type mapping (mirrors shared/prizepicks_client.py STAT_TYPE_MAP)
# ---------------------------------------------------------------------------

_STAT_TYPE_MAP: dict[str, str] = {
    # NHL
    "Points": "points", "Goals": "goals", "Assists": "assists",
    "Shots": "shots", "Shots On Goal": "shots", "SOG": "shots",
    "Saves": "saves", "Goals Against": "goals_against",
    "Blocked Shots": "blocked_shots", "Hits": "hits",
    "Power Play Points": "pp_points",

    # NBA
    "Pts": "points", "Rebs": "rebounds", "Asts": "assists",
    "Pts+Rebs": "pts_rebs", "Pts+Asts": "pts_asts", "Rebs+Asts": "rebs_asts",
    "Pts+Rebs+Asts": "pra", "3-PT Made": "threes", "3-Pointers Made": "threes",
    "Steals": "steals", "Blocks": "blocks", "Stls+Blks": "stocks",
    "Turnovers": "turnovers", "Fantasy Score": "fantasy",

    # MLB pitcher
    "Strikeouts": "strikeouts", "Pitcher Strikeouts": "strikeouts",
    "Outs Recorded": "outs_recorded", "Pitching Outs": "outs_recorded",
    "Walks Allowed": "pitcher_walks", "Walks": "pitcher_walks",
    "Hits Allowed": "hits_allowed",
    "Earned Runs Allowed": "earned_runs", "Earned Runs": "earned_runs",

    # MLB batter
    "Hits": "hits", "Total Bases": "total_bases", "Home Runs": "home_runs",
    "RBIs": "rbis", "RBI": "rbis",
    "Runs Scored": "runs", "Runs": "runs",
    "Stolen Bases": "stolen_bases",
    "Hitter Strikeouts": "batter_strikeouts", "Batter Strikeouts": "batter_strikeouts",
    "H+R+RBI": "hrr", "Hits+Runs+RBIs": "hrr", "H+R+RBIs": "hrr",
}

_LEAGUE_IDS: dict[str, int] = {
    "NHL": 8, "NBA": 7, "MLB": 2, "NFL": 9,
}

_LEAGUE_ALIASES: dict[str, set[str]] = {
    "GOLF": {"GOLF", "PGA"},
}

_ENDPOINTS = [
    "https://partner-api.prizepicks.com/projections",
    "https://api.prizepicks.com/projections",
]

_MIN_REQUEST_INTERVAL = 2.0   # seconds between API calls
_last_request_time: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Normalize player name: strip diacritics, lowercase, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return " ".join(stripped.lower().split())


def _initial_match(db_name: str, pp_name: str) -> bool:
    """
    Return True if db_name could be an abbreviated form of pp_name.

    Example: "A. Fox" matches "Adam Fox" — first token is an initial.
    """
    db_parts = _norm(db_name).split()
    pp_parts = _norm(pp_name).split()
    if not db_parts or not pp_parts:
        return False
    if len(db_parts) >= 2 and len(db_parts[0]) == 1:
        # db has initial "a. fox" vs pp "adam fox"
        return db_parts[0] == pp_parts[0][0] and db_parts[1:] == pp_parts[1:]
    return False


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


# ---------------------------------------------------------------------------
# API fetch (raw → List[dict])
# ---------------------------------------------------------------------------

def _fetch_raw(sport: str) -> list[dict]:
    """
    Fetch and parse PrizePicks projections for a sport.
    Returns list of PPLine-ready dicts. Returns [] on any failure.
    """
    if not _REQUESTS_AVAILABLE:
        print("[PEGASUS/pp_client] WARNING: requests not installed — cannot fetch PP lines.")
        return []

    league_id = _LEAGUE_IDS.get(sport.upper())
    if league_id is None:
        print(f"[PEGASUS/pp_client] Unknown sport: {sport}")
        return []

    params = {"per_page": 1000, "single_stat": "true", "league_id": league_id}
    headers = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":          "application/json; charset=UTF-8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://app.prizepicks.com/",
        "Origin":          "https://app.prizepicks.com",
    }

    response_json = None
    for endpoint in _ENDPOINTS:
        for attempt in range(3):
            _rate_limit()
            try:
                resp = requests.get(endpoint, params=params, headers=headers, timeout=30)
                if resp.status_code == 200:
                    ct = resp.headers.get("Content-Type", "")
                    if "application/json" in ct:
                        response_json = resp.json()
                        break
                    break  # non-JSON from this endpoint
                elif resp.status_code == 429:
                    wait = min(int(resp.headers.get("Retry-After", 45)), 120)
                    if attempt < 2:
                        print(f"  [WARN] PP 429 — waiting {wait}s ...")
                        time.sleep(wait)
                    break
                elif resp.status_code in (403,):
                    break
                elif resp.status_code in (500, 502, 503, 521):
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                else:
                    break
            except Exception as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    print(f"  [WARN] PP fetch error: {exc}")

        if response_json:
            break

    if not response_json:
        return []

    # Parse players + leagues from 'included'
    players: dict[str, dict] = {}
    leagues: dict[str, dict] = {}
    for item in response_json.get("included", []):
        t  = item.get("type", "")
        i  = item.get("id", "")
        a  = item.get("attributes", {})
        if t == "new_player":
            players[i] = {"name": a.get("name", ""), "team": a.get("team", "")}
        elif t == "league":
            leagues[i] = {"name": a.get("name", "")}

    # Parse projections
    accepted = _LEAGUE_ALIASES.get(sport.upper(), {sport.upper()})
    results: list[dict] = []
    for item in response_json.get("data", []):
        if item.get("type") != "projection":
            continue
        attrs = item.get("attributes", {})
        rels  = item.get("relationships", {})

        league_id_str = rels.get("league", {}).get("data", {}).get("id", "")
        league_name   = leagues.get(league_id_str, {}).get("name", "")
        if league_name.upper() not in accepted:
            continue

        player_id   = rels.get("new_player", {}).get("data", {}).get("id", "")
        player_info = players.get(player_id, {})

        raw_stat    = attrs.get("stat_type", "")
        prop_type   = _STAT_TYPE_MAP.get(raw_stat, raw_stat.lower().replace(" ", "_"))
        odds_t      = (attrs.get("odds_type") or "standard").lower()

        try:
            line = float(attrs.get("line_score", 0))
        except (TypeError, ValueError):
            continue

        results.append({
            "player_name":  player_info.get("name", ""),
            "prop":         prop_type,
            "line":         line,
            "odds_type":    odds_t,
            "sport":        sport.lower(),
            "start_time":   attrs.get("start_time", ""),
            "raw_stat_type": raw_stat,
            "is_promo":     bool(attrs.get("is_promo", False)),
        })

    return results


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

# _line_cache[(sport, date)] = {norm_key: PPLine}
_line_cache: dict[tuple[str, str], dict[str, PPLine]] = {}


def get_lines(sport: str, game_date: Optional[str] = None) -> dict[str, PPLine]:
    """
    Fetch live PP lines for a sport. Cached per (sport, date) per process.

    Args:
        sport:      "nhl" | "nba" | "mlb"
        game_date:  YYYY-MM-DD (used as cache key; defaults to today)

    Returns:
        dict keyed by "{normalized_player_name}:{prop}" → PPLine
        Empty dict on any API failure.
    """
    from datetime import date as _date
    if game_date is None:
        game_date = _date.today().isoformat()

    cache_key = (sport.lower(), game_date)
    if cache_key in _line_cache:
        return _line_cache[cache_key]

    print(f"  [PEGASUS/pp_client] Fetching {sport.upper()} lines from PrizePicks ...")
    try:
        raw = _fetch_raw(sport)
    except Exception as exc:
        print(f"  [PEGASUS/pp_client] {sport.upper()} fetch failed (non-fatal): {exc}")
        _line_cache[cache_key] = {}
        return {}

    result: dict[str, PPLine] = {}
    for r in raw:
        if not r.get("player_name") or not r.get("prop"):
            continue
        pl = PPLine(
            player_name   = r["player_name"],
            prop          = r["prop"],
            line          = r["line"],
            odds_type     = r["odds_type"],
            sport         = r["sport"],
            start_time    = r["start_time"],
            raw_stat_type = r["raw_stat_type"],
            is_promo      = r["is_promo"],
        )
        # Store under normalized key; last-write wins for duplicates
        result[pl.norm_key] = pl

    _line_cache[cache_key] = result
    print(f"  [PEGASUS/pp_client] {sport.upper()}: {len(result)} live lines cached.")
    return result


def get_all_lines(game_date: Optional[str] = None) -> dict[str, PPLine]:
    """
    Fetch live PP lines for all three PEGASUS sports (NHL + NBA + MLB).
    Returns merged dict. Duplicate keys (same player/prop in multiple sports) last-write wins.
    """
    combined: dict[str, PPLine] = {}
    for sport in ("nhl", "nba", "mlb"):
        try:
            combined.update(get_lines(sport, game_date))
        except Exception as exc:
            print(f"  [PEGASUS/pp_client] {sport.upper()} get_all_lines error (skipped): {exc}")
    return combined


# ---------------------------------------------------------------------------
# Pick matcher
# ---------------------------------------------------------------------------

def match_pick(pick, lines: dict[str, PPLine]) -> Optional[PPLine]:
    """
    Try to match a PEGASUSPick (or any object with .player_name and .prop) to a live PP line.

    Matching order:
      1. Exact normalized name + prop
      2. Initial abbreviation match (e.g., "A. Fox" → "Adam Fox")

    Returns PPLine or None.
    """
    prop  = getattr(pick, "prop", "")
    pname = getattr(pick, "player_name", "")

    # 1. Exact normalized match
    key = f"{_norm(pname)}:{prop}"
    if key in lines:
        return lines[key]

    # 2. Initial abbreviation: scan for a match where _initial_match holds
    for norm_key, pp_line in lines.items():
        if pp_line.prop != prop:
            continue
        if _initial_match(pname, pp_line.player_name):
            return pp_line

    return None


def detect_line_movement(pick, lines: dict[str, PPLine]) -> Optional[float]:
    """
    Return the line delta (live_line - stored_line) if a line has moved, else None.

    Positive delta = PP moved the line UP (harder to go OVER).
    Negative delta = PP moved the line DOWN (easier to go OVER).
    """
    pp_line = match_pick(pick, lines)
    if pp_line is None:
        return None
    delta = pp_line.line - getattr(pick, "line", pp_line.line)
    if abs(delta) < 0.01:
        return None
    return round(delta, 2)
