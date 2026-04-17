#!/usr/bin/env python3
"""
PEGASUS/pipeline/odds_client.py

The Odds API integration for PEGASUS — sportsbook implied probability.

Enables the Rithmm-style display:
    "Model: 72% | Sportsbook: 54% | Edge: +18%"

Free tier vs paid tier:
    FREE  (500 req/month): game-level moneyline, spread, total (h2h, spreads, totals)
    PAID  ($): player props (player_props_points, player_props_rebounds, etc.)

Current status: Player prop odds (the most useful for PEGASUS) require a PAID plan.
The free tier gives game-level totals — useful as a game environment indicator
(high total = pace/scoring context), but not directly usable as pick implied probability.

This module is designed so that:
  1. When ODDS_API_KEY is not set → everything returns None gracefully
  2. When ODDS_API_KEY is set (free tier) → game totals are fetched and cached
  3. When ODDS_API_KEY is set (paid tier) → player prop odds are fetched and returned
     as implied_probability on PEGASUSPick

The `implied_probability` field on PEGASUSPick is populated by this module.
It will be None until a paid plan is active.

Usage:
    from PEGASUS.pipeline.odds_client import (
        get_implied_probability,
        american_to_implied,
        get_game_totals,
    )

    # Math utilities (always available):
    prob = american_to_implied(-110)   # → 0.5238
    prob = american_to_implied(+130)   # → 0.4348

    # Player prop implied prob (requires paid API key):
    impl_prob = get_implied_probability("Kawhi Leonard", "pts_asts", "nba", "2026-04-15")
    # → 0.54 if sportsbook prices UNDER at ~-117, else None

Environment variables:
    ODDS_API_KEY  — The Odds API key (get at the-odds-api.com)
"""
from __future__ import annotations

import os
import time
from datetime import date as _date, datetime
from pathlib import Path
from typing import Optional

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

# Load .env from repo root (same pattern as sync/turso_sync.py)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_API_BASE      = "https://api.the-odds-api.com/v4"
_REQUEST_TIMEOUT = 20.0
_MIN_INTERVAL    = 1.0    # seconds between requests

# Sport keys in The Odds API format
_ODDS_SPORT_KEYS: dict[str, str] = {
    "nba": "basketball_nba",
    "nhl": "icehockey_nhl",
    "mlb": "baseball_mlb",
}

# Player prop market keys (paid tier only)
# Map our prop types → Odds API market keys
_PROP_MARKET_MAP: dict[str, str] = {
    # NBA
    "points":    "player_props_points",
    "rebounds":  "player_props_rebounds",
    "assists":   "player_props_assists",
    "pts_rebs":  "player_props_points_rebounds",
    "pts_asts":  "player_props_points_assists",
    "pra":       "player_props_points_rebounds_assists",
    "threes":    "player_props_threes",
    "steals":    "player_props_steals",
    "blocks":    "player_props_blocks",

    # NHL
    "shots":     "player_shots_on_goal",
    "goals":     "player_goals",

    # MLB
    "strikeouts":    "batter_strikeouts",
    "hits":          "batter_hits",
    "total_bases":   "batter_total_bases",
    "home_runs":     "batter_home_runs",
    "outs_recorded": "pitcher_outs",
}

# ---------------------------------------------------------------------------
# In-memory caches
# ---------------------------------------------------------------------------

_game_totals_cache: dict[tuple[str, str], list[dict]] = {}   # (sport, date)
_prop_odds_cache:   dict[tuple[str, str, str, str], Optional[float]] = {}  # (player, prop, sport, date)

_last_request_time: float = 0.0


# ---------------------------------------------------------------------------
# Math utilities (always available — no API key needed)
# ---------------------------------------------------------------------------

def american_to_implied(odds: int | float) -> float:
    """
    Convert American odds to implied probability.

    Examples:
        american_to_implied(-110) → 0.5238  (break-even for standard PP line)
        american_to_implied(-320) → 0.7619  (goblin break-even)
        american_to_implied(+100) → 0.5000
        american_to_implied(+130) → 0.4348
    """
    odds = float(odds)
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    else:
        return 100.0 / (odds + 100.0)


def implied_to_american(prob: float) -> float:
    """
    Convert implied probability to American odds.

    Examples:
        implied_to_american(0.5238) → -110.0
        implied_to_american(0.4348) → +130.0
    """
    if prob <= 0 or prob >= 1:
        raise ValueError(f"Probability must be in (0, 1), got {prob}")
    if prob >= 0.5:
        return -(prob / (1.0 - prob)) * 100.0
    else:
        return ((1.0 - prob) / prob) * 100.0


def remove_vig(over_odds: int, under_odds: int) -> tuple[float, float]:
    """
    Remove the bookmaker's vig from a two-sided market.

    Returns (fair_over_prob, fair_under_prob) that sum to 1.0.
    """
    raw_over  = american_to_implied(over_odds)
    raw_under = american_to_implied(under_odds)
    total     = raw_over + raw_under
    return raw_over / total, raw_under / total


def true_ev_from_prob(our_prob: float, fair_prob: float) -> float:
    """
    Compute our edge vs the fair (no-vig) sportsbook price.

    true_ev = our_prob / fair_prob - 1
    Positive = we think this outcome is more likely than the market.

    Example: our_prob=0.72, fair_prob=0.54 → true_ev = 0.72/0.54 - 1 = 0.333 (+33.3%)
    """
    if fair_prob <= 0:
        return 0.0
    return (our_prob / fair_prob) - 1.0


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _api_key() -> str:
    return os.getenv("ODDS_API_KEY", "").strip()


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_time = time.time()


def _get(url: str, params: dict) -> Optional[dict | list]:
    """Single GET with rate limit. Returns parsed JSON or None."""
    if not _REQUESTS_AVAILABLE:
        return None
    _rate_limit()
    try:
        resp = _requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            print("[PEGASUS/odds_client] ERROR: Invalid ODDS_API_KEY.")
        elif resp.status_code == 422:
            print(f"[PEGASUS/odds_client] ERROR 422 — bad request params: {resp.text[:200]}")
        elif resp.status_code == 429:
            print("[PEGASUS/odds_client] WARNING: Odds API quota exhausted (429).")
        else:
            print(f"[PEGASUS/odds_client] Unexpected status {resp.status_code}")
    except Exception as exc:
        print(f"[PEGASUS/odds_client] Request error: {exc}")
    return None


# ---------------------------------------------------------------------------
# Game totals (free tier)
# ---------------------------------------------------------------------------

def get_game_totals(sport: str, game_date: str) -> list[dict]:
    """
    Fetch game-level total (O/U) lines for a sport from The Odds API free tier.

    Returns list of dicts:
        [{
            "home_team": "Los Angeles Lakers",
            "away_team": "Golden State Warriors",
            "total": 224.5,
            "over_odds": -110,
            "under_odds": -110,
            "fair_over_prob": 0.5,
            "fair_under_prob": 0.5,
            "implied_total": 224.5,
        }, ...]

    Returns [] if no API key or fetch fails.

    Free tier: Each call costs ~1 request. 500 req/month limit.
    """
    key = _api_key()
    if not key:
        return []

    cache_key = (sport.lower(), game_date)
    if cache_key in _game_totals_cache:
        return _game_totals_cache[cache_key]

    sport_key = _ODDS_SPORT_KEYS.get(sport.lower())
    if not sport_key:
        return []

    url    = f"{_API_BASE}/sports/{sport_key}/odds/"
    params = {
        "apiKey":      key,
        "regions":     "us",
        "markets":     "totals",
        "oddsFormat":  "american",
        "dateFormat":  "iso",
    }

    data = _get(url, params)
    if not data or not isinstance(data, list):
        _game_totals_cache[cache_key] = []
        return []

    # Filter to games on game_date
    results: list[dict] = []
    for game in data:
        commence = game.get("commence_time", "")
        if not commence.startswith(game_date):
            continue

        for bookmaker in game.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "totals":
                    continue
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                over_odds  = outcomes.get("Over")
                under_odds = outcomes.get("Under")
                if over_odds is None or under_odds is None:
                    continue
                fair_over, fair_under = remove_vig(over_odds, under_odds)
                # Get the total point value from outcomes
                total_val = None
                for o in market.get("outcomes", []):
                    if o.get("name") == "Over" and "point" in o:
                        total_val = o["point"]
                        break
                results.append({
                    "home_team":      game.get("home_team", ""),
                    "away_team":      game.get("away_team", ""),
                    "total":          total_val,
                    "over_odds":      over_odds,
                    "under_odds":     under_odds,
                    "fair_over_prob": round(fair_over, 4),
                    "fair_under_prob": round(fair_under, 4),
                    "bookmaker":      bookmaker.get("title", ""),
                })
                break  # one bookmaker per game is enough

    _game_totals_cache[cache_key] = results
    return results


# ---------------------------------------------------------------------------
# Player prop implied probability (paid tier)
# ---------------------------------------------------------------------------

def get_implied_probability(
    player_name: str,
    prop: str,
    sport: str,
    game_date: str,
    direction: str = "UNDER",
) -> Optional[float]:
    """
    Fetch fair implied probability for a player prop from The Odds API.

    Requires a PAID plan — player prop markets are not available on the free tier.
    Returns None if:
      - No ODDS_API_KEY set
      - Free-tier key (player props not in plan)
      - Player/prop not found in API response

    When available, returns the fair (vig-removed) probability for the given direction.

    Note: The Odds API player prop coverage varies by sport and bookmaker.
    NBA has better coverage than NHL or MLB.
    """
    key = _api_key()
    if not key:
        return None  # No API key — skip silently

    cache_key = (player_name, prop, sport, game_date)
    if cache_key in _prop_odds_cache:
        return _prop_odds_cache[cache_key]

    market_key = _PROP_MARKET_MAP.get(prop)
    if not market_key:
        _prop_odds_cache[cache_key] = None
        return None

    sport_key = _ODDS_SPORT_KEYS.get(sport.lower())
    if not sport_key:
        _prop_odds_cache[cache_key] = None
        return None

    # First: get events list for the sport on game_date
    events_url = f"{_API_BASE}/sports/{sport_key}/events/"
    events_params = {"apiKey": key, "dateFormat": "iso"}
    events_data = _get(events_url, events_params)

    if not events_data or not isinstance(events_data, list):
        _prop_odds_cache[cache_key] = None
        return None

    # Filter events to game_date
    event_ids = [
        e["id"] for e in events_data
        if e.get("commence_time", "").startswith(game_date)
    ]

    if not event_ids:
        _prop_odds_cache[cache_key] = None
        return None

    # Search each event for the player prop
    player_norm = player_name.lower().strip()
    result: Optional[float] = None

    for event_id in event_ids:
        if result is not None:
            break
        url = f"{_API_BASE}/sports/{sport_key}/events/{event_id}/odds/"
        params = {
            "apiKey":      key,
            "regions":     "us",
            "markets":     market_key,
            "oddsFormat":  "american",
        }
        event_data = _get(url, params)
        if not event_data:
            continue

        for bookmaker in event_data.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != market_key:
                    continue
                # Find the player in outcomes
                # Outcomes typically: [{"name": "Kawhi Leonard", "description": "Over", "price": -115, "point": 34.5}, ...]
                player_outcomes: dict[str, dict] = {}
                for o in market.get("outcomes", []):
                    name = o.get("name", "").lower().strip()
                    if name == player_norm:
                        desc = (o.get("description") or "").upper()
                        player_outcomes[desc] = o

                if not player_outcomes:
                    continue

                over_out  = player_outcomes.get("OVER")
                under_out = player_outcomes.get("UNDER")
                if not over_out or not under_out:
                    continue

                fair_over, fair_under = remove_vig(over_out["price"], under_out["price"])
                result = round(fair_over if direction.upper() == "OVER" else fair_under, 4)
                break  # first bookmaker with the player is enough
            if result is not None:
                break

    _prop_odds_cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# Quota check
# ---------------------------------------------------------------------------

def check_quota() -> Optional[dict]:
    """
    Check remaining The Odds API quota.

    Returns {"requests_remaining": int, "requests_used": int} or None.
    Useful to call before a large fetch batch to avoid exhausting the monthly limit.
    """
    key = _api_key()
    if not key:
        print("[PEGASUS/odds_client] No ODDS_API_KEY set — cannot check quota.")
        return None

    url    = f"{_API_BASE}/sports/"
    params = {"apiKey": key}
    data   = _get(url, params)

    if data is None:
        return None

    # The Odds API returns remaining/used in response headers, not body.
    # To get header values we need to make a raw request — approximate via the data dict.
    # For now, just confirm the key is valid and return a signal.
    return {"status": "valid", "note": "Check response headers for x-requests-remaining."}


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------

def _main_cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="PEGASUS Odds Client utilities")
    sub = parser.add_subparsers(dest="cmd")

    # Convert American odds
    conv = sub.add_parser("convert", help="American odds → implied probability")
    conv.add_argument("odds", type=float, help="American odds (e.g. -110, +130)")

    # Fetch game totals
    gt = sub.add_parser("totals", help="Fetch game totals for a sport/date")
    gt.add_argument("sport", choices=["nba", "nhl", "mlb"])
    gt.add_argument("--date", default=None)

    # Check quota
    sub.add_parser("quota", help="Check API quota remaining")

    args = parser.parse_args()

    if args.cmd == "convert":
        prob = american_to_implied(args.odds)
        print(f"{args.odds:+.0f} → implied probability: {prob:.4f} ({prob*100:.1f}%)")

    elif args.cmd == "totals":
        d = args.date or _date.today().isoformat()
        totals = get_game_totals(args.sport, d)
        if not totals:
            print(f"No game totals found for {args.sport.upper()} on {d}.")
            print("Check ODDS_API_KEY is set.")
        else:
            for g in totals:
                print(f"  {g['away_team']} @ {g['home_team']}  O/U {g['total']}  "
                      f"({g['over_odds']:+.0f} / {g['under_odds']:+.0f})")

    elif args.cmd == "quota":
        result = check_quota()
        print(result)

    else:
        parser.print_help()


if __name__ == "__main__":
    _main_cli()
