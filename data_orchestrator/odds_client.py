"""
data_orchestrator/odds_client.py

The Odds API client with daily request budget enforcement and local caching.

Budget: 500 requests/day (conservative cap against the 600/day plan limit).
Caching: odds per (sport, event_id, market) are stored in odds_lines and NOT
         re-fetched within the same calendar day.

Endpoint flow:
  1. GET /v4/sports/{sport_key}/events           → list today's event IDs
  2. GET /v4/sports/{sport_key}/events/{id}/odds → player prop lines per event

Costs: Step 1 = 1 request per sport. Step 2 = 1 request per event.
Typical daily usage: 3 (events list) + ~15 (events × 3 sports) = ~18 requests/pull
Three pulls/day ≈ 54 requests. Very safe against the 500 cap.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
import requests

from .config import (
    ODDS_API_BASE,
    ODDS_API_BUDGET,
    ODDS_API_KEY,
    ODDS_FORMAT,
    ODDS_REGIONS,
    SPORT_CONFIGS,
)
from .storage import DataStore

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"Accept": "application/json"})


# ---------------------------------------------------------------------------
# OddsClient
# ---------------------------------------------------------------------------

class OddsClient:
    """
    Fetches player prop lines from The Odds API.

    Usage:
        client = OddsClient(store)
        df = client.fetch_all_props()           # all 3 sports
        df = client.fetch_props("NBA")          # one sport

    Returns DataFrame with columns:
        fetch_date, sport, player_name, prop_type,
        line, over_price, under_price, implied_over, implied_under,
        bookmaker, event_id, home_team, away_team, commence_utc
    """

    def __init__(self, store: DataStore = None, api_key: str = None):
        self.store   = store or DataStore()
        self.api_key = api_key or ODDS_API_KEY
        if not self.api_key:
            logger.error("ODDS_API_KEY not set — odds fetches will fail")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_all_props(self, fetch_date: str = None) -> pd.DataFrame:
        """Fetch player props for NBA, NHL, and MLB. Returns combined DataFrame."""
        fetch_date = fetch_date or datetime.utcnow().date().isoformat()
        frames: list[pd.DataFrame] = []
        for sport in SPORT_CONFIGS:
            df = self.fetch_props(sport, fetch_date)
            if not df.empty:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def fetch_props(self, sport: str, fetch_date: str = None) -> pd.DataFrame:
        """
        Fetch player prop lines for a single sport.

        Args:
            sport:      'NBA', 'NHL', or 'MLB'
            fetch_date: 'YYYY-MM-DD'. Defaults to today UTC.

        Returns:
            Normalized DataFrame (empty if no games or budget exhausted).
        """
        fetch_date  = fetch_date or datetime.utcnow().date().isoformat()
        cfg         = SPORT_CONFIGS.get(sport.upper())
        if not cfg:
            raise ValueError(f"Unknown sport: {sport}. Use NBA, NHL, MLB.")

        sport_key  = cfg["sport_key"]
        market     = cfg["market"]
        prop_label = cfg["prop_label"]

        logger.info(f"[Odds] Fetching {sport} {prop_label} lines for {fetch_date}")

        if not self._budget_ok():
            logger.warning(f"[Odds] Daily budget ({ODDS_API_BUDGET}) reached — skipping")
            return pd.DataFrame()

        events = self._get_events(sport_key, sport)
        if not events:
            logger.info(f"[Odds] No {sport} events today")
            return pd.DataFrame()

        # Only fetch events not already cached for today
        already_cached = self._cached_event_ids(fetch_date, sport)
        new_events = [e for e in events if e["id"] not in already_cached]

        if not new_events:
            logger.info(f"[Odds] {sport} odds already cached for {fetch_date}")
            return self.store.get_odds(fetch_date, sport)

        all_rows: list[dict] = []

        for event in new_events:
            if not self._budget_ok():
                logger.warning("[Odds] Budget reached mid-fetch — stopping")
                break

            rows = self._get_event_odds(
                sport_key=sport_key,
                market=market,
                event=event,
                sport=sport,
                prop_label=prop_label,
                fetch_date=fetch_date,
            )
            all_rows.extend(rows)

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        saved = self.store.upsert_odds(df)
        logger.info(f"[Odds] {saved} lines saved for {sport} on {fetch_date}")
        return df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _budget_ok(self) -> bool:
        used = self.store.requests_used_today()
        return used < ODDS_API_BUDGET

    def _cached_event_ids(self, fetch_date: str, sport: str) -> set[str]:
        existing = self.store.get_odds(fetch_date, sport)
        if existing.empty or "event_id" not in existing.columns:
            return set()
        return set(existing["event_id"].dropna().unique())

    def _get_events(self, sport_key: str, sport: str) -> list[dict]:
        """Fetch today's event list. Cost: 1 API request."""
        url    = f"{ODDS_API_BASE}/sports/{sport_key}/events"
        params = {"apiKey": self.api_key, "dateFormat": "iso"}

        try:
            resp = _SESSION.get(url, params=params, timeout=15)
            self._log_request(resp, f"events/{sport_key}", sport, "list")

            if resp.status_code == 401:
                logger.error("[Odds] Invalid API key (401)")
                return []
            if resp.status_code == 422:
                logger.info(f"[Odds] No {sport} events available today (422)")
                return []
            resp.raise_for_status()

            return resp.json()

        except requests.exceptions.Timeout:
            logger.warning(f"[Odds] Events request timed out for {sport_key}")
            return []
        except Exception as exc:
            logger.warning(f"[Odds] Events fetch failed for {sport_key}: {exc}")
            return []

    def _get_event_odds(
        self,
        sport_key: str,
        market: str,
        event: dict,
        sport: str,
        prop_label: str,
        fetch_date: str,
    ) -> list[dict]:
        """Fetch player prop odds for a single event. Cost: 1 API request."""
        event_id     = event["id"]
        home_team    = event.get("home_team", "")
        away_team    = event.get("away_team", "")
        commence_utc = event.get("commence_time", "")

        url    = f"{ODDS_API_BASE}/sports/{sport_key}/events/{event_id}/odds"
        params = {
            "apiKey":      self.api_key,
            "regions":     ODDS_REGIONS,
            "markets":     market,
            "oddsFormat":  ODDS_FORMAT,
            "dateFormat":  "iso",
        }

        try:
            resp = _SESSION.get(url, params=params, timeout=15)
            self._log_request(resp, f"events/{event_id}/odds", sport, market)

            if resp.status_code in (401, 404):
                logger.warning(f"[Odds] {resp.status_code} for event {event_id}")
                return []
            resp.raise_for_status()
            body = resp.json()

        except requests.exceptions.Timeout:
            logger.warning(f"[Odds] Timeout for event {event_id}")
            return []
        except Exception as exc:
            logger.warning(f"[Odds] Props fetch failed for event {event_id}: {exc}")
            return []

        return self._parse_bookmaker_rows(
            body=body,
            sport=sport,
            prop_label=prop_label,
            fetch_date=fetch_date,
            event_id=event_id,
            home_team=home_team,
            away_team=away_team,
            commence_utc=commence_utc,
        )

    def _parse_bookmaker_rows(
        self,
        body: dict,
        sport: str,
        prop_label: str,
        fetch_date: str,
        event_id: str,
        home_team: str,
        away_team: str,
        commence_utc: str,
    ) -> list[dict]:
        """
        Parse The Odds API response into normalized rows.

        Each outcome in the API looks like:
          {"name": "Over", "description": "LeBron James", "price": -130, "point": 24.5}

        We build one row per (player, bookmaker) with both OVER and UNDER prices.
        """
        rows: list[dict] = []
        bookmakers = body.get("bookmakers", [])

        for bk in bookmakers:
            bk_key   = bk.get("key", "")
            markets  = bk.get("markets", [])

            for mkt in markets:
                if mkt.get("key") != _market_key_for(prop_label):
                    continue

                # Group outcomes by player name
                player_sides: dict[str, dict] = {}
                for outcome in mkt.get("outcomes", []):
                    player = outcome.get("description", "")
                    side   = outcome.get("name", "")       # "Over" or "Under"
                    price  = outcome.get("price")          # American odds int
                    line   = outcome.get("point")          # float

                    if not player or not side or price is None:
                        continue

                    if player not in player_sides:
                        player_sides[player] = {"line": line}

                    if side.lower() == "over":
                        player_sides[player]["over_price"]  = int(price)
                    elif side.lower() == "under":
                        player_sides[player]["under_price"] = int(price)

                # Emit one row per player with both sides
                for player, sides in player_sides.items():
                    over_p  = sides.get("over_price")
                    under_p = sides.get("under_price")

                    implied_over  = _remove_vig_over(over_p, under_p)
                    implied_under = _remove_vig_under(over_p, under_p)

                    rows.append({
                        "fetch_date":    fetch_date,
                        "sport":         sport,
                        "player_name":   player,
                        "prop_type":     prop_label,
                        "line":          sides.get("line"),
                        "over_price":    over_p,
                        "under_price":   under_p,
                        "implied_over":  implied_over,
                        "implied_under": implied_under,
                        "bookmaker":     bk_key,
                        "event_id":      event_id,
                        "home_team":     home_team,
                        "away_team":     away_team,
                        "commence_utc":  commence_utc,
                    })

        return rows

    def _log_request(self, resp: requests.Response, endpoint: str, sport: str, market: str):
        used      = _safe_int(resp.headers.get("x-requests-used"))
        remaining = _safe_int(resp.headers.get("x-requests-remaining"))
        self.store.log_api_request(endpoint, sport, market, used, remaining, resp.status_code)
        if remaining is not None and remaining < 100:
            logger.warning(f"[Odds] Low budget: {remaining} requests remaining today")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market_key_for(prop_label: str) -> str:
    """Map our prop label back to The Odds API market key."""
    _map = {
        "points":        "player_points",
        "shots_on_goal": "player_shots_on_goal",
        "total_bases":   "batter_total_bases",
    }
    return _map.get(prop_label, prop_label)


def _remove_vig_over(over_p: Optional[int], under_p: Optional[int]) -> Optional[float]:
    if over_p is None or under_p is None:
        return None
    raw_o = _american_to_implied(over_p)
    raw_u = _american_to_implied(under_p)
    total = raw_o + raw_u
    return round(raw_o / total, 4) if total > 0 else None


def _remove_vig_under(over_p: Optional[int], under_p: Optional[int]) -> Optional[float]:
    if over_p is None or under_p is None:
        return None
    raw_o = _american_to_implied(over_p)
    raw_u = _american_to_implied(under_p)
    total = raw_o + raw_u
    return round(raw_u / total, 4) if total > 0 else None


def _american_to_implied(odds: int) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def _safe_int(val) -> Optional[int]:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None
