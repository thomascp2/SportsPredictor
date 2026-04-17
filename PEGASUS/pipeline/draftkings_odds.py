#!/usr/bin/env python3
"""
PEGASUS/pipeline/draftkings_odds.py

DraftKings sportsbook unofficial API — player prop implied odds.

Uses the publicly accessible DraftKings sportsbook JSON API (no key, no registration).
This is for personal research only — do NOT redistribute data or use commercially.

API endpoint (confirmed stable as of 2026-04):
    https://sportsbook-nash.draftkings.com/api/sportscontent/dkusoh/v1/
        leagues/{league_id}/categories/{category_id}

Returns:
    dict[(normalized_player_name, prop): {"over_odds": int, "under_odds": int, "line": float}]

Design:
  - Non-fatal: returns {} on any failure (exception, timeout, parse error)
  - Cache per (sport, date) per process — one API call per sport per day
  - Uses american_to_implied() + remove_vig() from odds_client.py
  - No keys required — uses the same User-Agent pattern as prizepicks_client.py

Usage:
    from PEGASUS.pipeline.draftkings_odds import get_dk_props

    # Fetch NBA player prop odds for today
    dk = get_dk_props("nba", "2026-04-15")
    # dk = {("kawhi leonard", "pts_asts"): {"over_odds": -115, "under_odds": -105, "line": 34.5}}

    # Get implied prob for a specific player/prop
    if ("kawhi leonard", "pts_asts") in dk:
        info = dk[("kawhi leonard", "pts_asts")]
        from PEGASUS.pipeline.odds_client import remove_vig
        fair_over, fair_under = remove_vig(info["over_odds"], info["under_odds"])
        # fair_under = 0.512 → "implied_probability" for an UNDER pick

Wiring into pick_selector:
    Called from get_picks() as optional enrichment.
    Sets pick.implied_probability = fair_prob(direction) when DK has the line.
    If DK has no data (no games, rate-limited, etc.) pick.implied_probability stays None.
"""
from __future__ import annotations

import time
import unicodedata
from typing import Optional

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _requests = None  # type: ignore
    _REQUESTS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL       = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusoh/v1"
_REQUEST_TIMEOUT = (5.0, 25.0)   # (connect, read) — read can be slow for large responses
_MIN_INTERVAL    = 3.0            # seconds between requests

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://sportsbook.draftkings.com/",
    "Origin":          "https://sportsbook.draftkings.com",
}

# DraftKings league IDs for the sportsbook API
_LEAGUE_IDS: dict[str, int] = {
    "nba": 42648,
    "nhl": 42133,
    "mlb": 84240,
}

# DraftKings category IDs for player props (per-league)
# These are the top-level "Player Props" category for each sport.
# Subcategories (Points, Rebounds, Assists, etc.) live under these.
_PLAYER_PROP_CATEGORIES: dict[str, int] = {
    "nba": 1000074,   # NBA Player Props
    "nhl": 1000096,   # NHL Player Props
    "mlb": 1000045,   # MLB Player Props
}

# Map DraftKings subcategory names (lowercased) to our prop type strings
# These are matched against "subcategoryName" in the market record.
_SUBCAT_TO_PROP: dict[str, str] = {
    # NBA
    "points":                    "points",
    "rebounds":                  "rebounds",
    "assists":                   "assists",
    "3-point field goals made":  "threes",
    "3 point field goals made":  "threes",
    "threes":                    "threes",
    "pts + rebs":                "pts_rebs",
    "pts+rebs":                  "pts_rebs",
    "pts + asts":                "pts_asts",
    "pts+asts":                  "pts_asts",
    "rebs + asts":               "rebs_asts",
    "rebs+asts":                 "rebs_asts",
    "pts + rebs + asts":         "pra",
    "pts+rebs+asts":             "pra",
    "steals":                    "steals",
    "blocks":                    "blocks",
    "steals + blocks":           "stocks",
    "steals+blocks":             "stocks",
    "turnovers":                 "turnovers",
    "fantasy points":            "fantasy",
    # NHL
    "shots on goal":             "shots",
    "shots":                     "shots",
    "goals":                     "goals",
    "assists":                   "assists",
    "points":                    "points",
    "hits":                      "hits",
    "blocked shots":             "blocked_shots",
    # MLB (batter)
    "hits":                      "hits",
    "total bases":               "total_bases",
    "home runs":                 "home_runs",
    "strikeouts":                "strikeouts",
    # MLB (pitcher)
    "pitcher strikeouts":        "strikeouts",
    "outs recorded":             "outs_recorded",
    "walks":                     "pitcher_walks",
}

# ---------------------------------------------------------------------------
# In-memory cache: (sport, date) -> {(norm_name, prop): {"over_odds": int, ...}}
# ---------------------------------------------------------------------------

_cache: dict[tuple[str, str], dict] = {}
_last_request_time: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Normalize player name: strip diacritics, lowercase, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return " ".join(stripped.lower().split())


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_time = time.time()


def _fetch(sport: str) -> Optional[dict]:
    """
    Fetch raw DraftKings player prop data for a sport.

    Returns the parsed JSON dict or None on any failure.
    """
    if not _REQUESTS_AVAILABLE:
        print("[PEGASUS/dk_odds] WARNING: requests not installed.")
        return None

    league_id = _LEAGUE_IDS.get(sport.lower())
    category  = _PLAYER_PROP_CATEGORIES.get(sport.lower())
    if not league_id or not category:
        return None

    url = f"{_BASE_URL}/leagues/{league_id}/categories/{category}"
    _rate_limit()

    try:
        resp = _requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 429:
            print(f"[PEGASUS/dk_odds] {sport.upper()} rate-limited (429) — returning empty.")
        elif resp.status_code == 403:
            print(f"[PEGASUS/dk_odds] {sport.upper()} geo-blocked (403) — returning empty.")
        else:
            print(f"[PEGASUS/dk_odds] {sport.upper()} unexpected status {resp.status_code}.")
    except Exception as exc:
        print(f"[PEGASUS/dk_odds] {sport.upper()} fetch failed (non-fatal): {exc}")

    return None


# ---------------------------------------------------------------------------
# Parser: raw JSON → {(norm_name, prop): {over_odds, under_odds, line}}
# ---------------------------------------------------------------------------

def _parse_props(data: dict) -> dict[tuple[str, str], dict]:
    """
    Parse DraftKings API response into player prop lookup dict.

    DraftKings response shape (confirmed 2026-04):
        data["markets"]: list of market records
            - marketId, marketName, subcategoryId, subcategoryName, status
        data["selections"]: list of selection records
            - selectionId, marketId, label ("Over"/"Under"), oddsAmerican, handicap

    marketName format: "{PlayerName} - {PropType}" (e.g. "LeBron James - Points")
    OR in newer formats: playerName and propName fields directly on the market.

    Returns: {(normalized_player_name, prop): {"over_odds": int, "under_odds": int, "line": float}}
    """
    result: dict[tuple[str, str], dict] = {}

    markets    = data.get("markets", [])
    selections = data.get("selections", [])

    if not markets or not selections:
        return result

    # Build selection index: marketId -> {label: selection_dict}
    sel_by_market: dict[str, dict] = {}
    for sel in selections:
        mid   = str(sel.get("marketId", ""))
        label = (sel.get("label") or "").strip().upper()  # "OVER" / "UNDER"
        if label in ("OVER", "UNDER"):
            if mid not in sel_by_market:
                sel_by_market[mid] = {}
            sel_by_market[mid][label] = sel

    # Parse each market
    for mkt in markets:
        # Only open markets
        if (mkt.get("status") or "").upper() not in ("OPEN", ""):
            continue

        mid = str(mkt.get("marketId", ""))
        if mid not in sel_by_market:
            continue

        sels = sel_by_market[mid]
        over_sel  = sels.get("OVER")
        under_sel = sels.get("UNDER")
        if not over_sel or not under_sel:
            continue

        # Get odds (American format, stored as string or int in DK API)
        try:
            over_odds  = int(over_sel.get("oddsAmerican") or over_sel.get("trueOdds") or 0)
            under_odds = int(under_sel.get("oddsAmerican") or under_sel.get("trueOdds") or 0)
            if over_odds == 0 or under_odds == 0:
                continue
        except (TypeError, ValueError):
            continue

        # Get the line (handicap) — should be same on both selections for player props
        try:
            line = float(over_sel.get("handicap") or under_sel.get("handicap") or 0)
        except (TypeError, ValueError):
            continue

        # Get player name and prop from market
        # Try direct playerName / participantName fields first
        player_name = (
            mkt.get("playerName")
            or mkt.get("participantName")
            or ""
        )

        # Parse subcategory → our prop type
        subcat_name = (mkt.get("subcategoryName") or "").lower().strip()
        prop = _SUBCAT_TO_PROP.get(subcat_name)

        # Fallback: parse "{PlayerName} - {Subcategory}" from marketName
        if not player_name or not prop:
            market_name = mkt.get("marketName") or ""
            if " - " in market_name:
                parts = market_name.split(" - ", 1)
                if not player_name:
                    player_name = parts[0].strip()
                if not prop:
                    prop = _SUBCAT_TO_PROP.get(parts[1].strip().lower())

        if not player_name or not prop:
            continue  # can't match without both

        key = (_norm(player_name), prop)
        # Last-write wins for duplicate keys
        result[key] = {
            "over_odds":  over_odds,
            "under_odds": under_odds,
            "line":       line,
        }

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_dk_props(
    sport: str,
    game_date: str,
) -> dict[tuple[str, str], dict]:
    """
    Fetch DraftKings player prop odds for a sport.

    Args:
        sport:      "nhl" | "nba" | "mlb"
        game_date:  YYYY-MM-DD (used as cache key only — DK returns today's lines)

    Returns:
        dict keyed by (normalized_player_name, prop) ->
            {"over_odds": int, "under_odds": int, "line": float}

        Returns empty dict {} on any API failure, geo-block, or rate-limit.
        Never raises — fully non-fatal.

    Example:
        dk = get_dk_props("nba", "2026-04-15")
        info = dk.get(("kawhi leonard", "pts_asts"))
        # → {"over_odds": -115, "under_odds": -105, "line": 34.5}
    """
    cache_key = (sport.lower(), game_date)
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        print(f"  [PEGASUS/dk_odds] Fetching {sport.upper()} player prop odds from DraftKings ...")
        raw = _fetch(sport)
        if raw is None:
            _cache[cache_key] = {}
            return {}

        result = _parse_props(raw)
        _cache[cache_key] = result
        n = len(result)
        if n > 0:
            print(f"  [PEGASUS/dk_odds] {sport.upper()}: {n} player-prop lines cached.")
        else:
            print(f"  [PEGASUS/dk_odds] {sport.upper()}: no prop lines returned "
                  f"(no games today or market not open yet).")
        return result

    except Exception as exc:
        print(f"  [PEGASUS/dk_odds] {sport.upper()} error (non-fatal): {exc}")
        _cache[cache_key] = {}
        return {}


def get_implied_prob(
    player_name: str,
    prop: str,
    direction: str,
    sport: str,
    game_date: str,
) -> Optional[float]:
    """
    Convenience function: return vig-removed implied probability for one player/prop/direction.

    Returns None if DK has no data for this player/prop, or on any error.
    Uses remove_vig() from odds_client.py internally.
    """
    try:
        from PEGASUS.pipeline.odds_client import remove_vig
    except ImportError:
        return None

    dk = get_dk_props(sport, game_date)
    key = (_norm(player_name), prop)
    info = dk.get(key)
    if not info:
        return None

    try:
        fair_over, fair_under = remove_vig(info["over_odds"], info["under_odds"])
        return round(fair_over if direction.upper() == "OVER" else fair_under, 4)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------

def _main_cli() -> None:
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(description="PEGASUS DraftKings odds fetcher")
    parser.add_argument("sport", choices=["nba", "nhl", "mlb"], help="Sport")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--player", default=None, help="Filter to a specific player name")
    args = parser.parse_args()

    game_date = args.date or date.today().isoformat()
    dk = get_dk_props(args.sport, game_date)

    if not dk:
        print(f"\nNo {args.sport.upper()} prop lines from DraftKings today.")
        print("Possible reasons: no games, geo-block, API rate-limit, or market not open.")
        return

    print(f"\nDraftKings {args.sport.upper()} player props — {game_date}")
    print(f"{'Player':<30} {'Prop':<20} {'Line':>6}  {'Over':>6}  {'Under':>6}")
    print("-" * 75)

    for (norm_name, prop), info in sorted(dk.items()):
        if args.player and args.player.lower() not in norm_name:
            continue
        print(
            f"  {norm_name:<28} {prop:<20} {info['line']:>6.1f}  "
            f"{info['over_odds']:>+6}  {info['under_odds']:>+6}"
        )


if __name__ == "__main__":
    _main_cli()
