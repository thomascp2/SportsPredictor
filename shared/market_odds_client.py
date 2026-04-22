"""
shared/market_odds_client.py

Market implied probability client for ML v2 true-edge calculation.

True edge = model_probability - market_implied_probability
(vs. the old formula: pp_edge = model_probability - PP_break_even)

Data source: The Odds API (the-odds-api.com)
  - Free tier (current): game totals only. Player props return None.
  - Paid tier ($30/mo): player prop implied probabilities populate automatically.
  When ODDS_API_KEY is upgraded to a paid plan, `get_market_implied()` will
  start returning real values and true_edge will light up across the system.

Persistence: shared/market_lines.db (SQLite)
  Cached per (player_name, prop_type, sport, game_date) so each prop is
  fetched once per day regardless of how many times it's queried.

Usage:
    from shared.market_odds_client import MarketOddsClient, compute_true_edge

    client = MarketOddsClient()
    implied = client.get_market_implied("LeBron James", "points", "nba", "2026-04-22")
    # → 0.54 when paid plan active; None on free plan

    edge_info = compute_true_edge(model_prob=0.62, market_implied=implied,
                                  pp_break_even=0.5238)
    # → {"true_edge": 0.08, "pp_edge": 0.096, "has_market_data": True}
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date as _date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Shared utilities from the existing odds client
# ---------------------------------------------------------------------------
try:
    from PEGASUS.pipeline.odds_client import (
        american_to_implied,
        remove_vig,
        true_ev_from_prob,
        get_implied_probability as _odds_api_prop,
        get_game_totals as _odds_api_totals,
    )
    _ODDS_CLIENT_AVAILABLE = True
except ImportError:
    _ODDS_CLIENT_AVAILABLE = False
    def american_to_implied(odds):
        odds = float(odds)
        return abs(odds) / (abs(odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)
    def remove_vig(over_odds, under_odds):
        raw_over = american_to_implied(over_odds)
        raw_under = american_to_implied(under_odds)
        total = raw_over + raw_under
        return raw_over / total, raw_under / total
    def true_ev_from_prob(our_prob, fair_prob):
        return (our_prob / fair_prob) - 1.0 if fair_prob > 0 else 0.0
    def _odds_api_prop(*args, **kwargs):
        return None
    def _odds_api_totals(*args, **kwargs):
        return []


# ---------------------------------------------------------------------------
# Database path
# ---------------------------------------------------------------------------

_SHARED_DIR = Path(__file__).resolve().parent
_DB_PATH    = _SHARED_DIR / "market_lines.db"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_PLAYER_PROPS = """
CREATE TABLE IF NOT EXISTS market_player_props (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date    DATE    NOT NULL,
    sport        TEXT    NOT NULL,
    player_name  TEXT    NOT NULL,
    prop_type    TEXT    NOT NULL,
    line         REAL,
    implied_over REAL,
    implied_under REAL,
    source       TEXT    DEFAULT 'odds_api',
    fetched_at   TEXT,
    UNIQUE(game_date, sport, player_name, prop_type)
)
"""

_CREATE_GAME_TOTALS = """
CREATE TABLE IF NOT EXISTS market_game_totals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date   DATE    NOT NULL,
    sport       TEXT    NOT NULL,
    home_team   TEXT,
    away_team   TEXT,
    total       REAL,
    over_odds   REAL,
    under_odds  REAL,
    fair_over   REAL,
    fair_under  REAL,
    bookmaker   TEXT,
    fetched_at  TEXT,
    UNIQUE(game_date, sport, home_team, away_team)
)
"""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MarketOddsClient:
    """
    Fetches and caches sportsbook implied probabilities for player props.

    When The Odds API is on a paid plan:
      - get_market_implied() returns fair (vig-removed) probability
      - true_edge is computed vs the market, not vs PP break-even

    When on free plan:
      - get_market_implied() returns None for player props
      - game totals still work (useful as a game environment signal)
      - true_edge is not computable; pp_edge is used as the fallback
    """

    def __init__(self, db_path: str | Path = None):
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db()

    # ------------------------------------------------------------------
    # DB setup
    # ------------------------------------------------------------------

    def _ensure_db(self):
        with self._get_conn() as conn:
            conn.execute(_CREATE_PLAYER_PROPS)
            conn.execute(_CREATE_GAME_TOTALS)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), timeout=30)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Player prop implied probability
    # ------------------------------------------------------------------

    def get_market_implied(
        self,
        player_name: str,
        prop_type: str,
        sport: str,
        game_date: str,
        direction: str = "OVER",
    ) -> Optional[float]:
        """
        Return the vig-removed market implied probability for a player prop.

        Returns None when:
          - No ODDS_API_KEY set, OR
          - Free-tier key (player props not in plan), OR
          - Player/prop not available in API

        When a paid plan is active this is the fair probability (vig removed
        from the two-sided market), meaning it sums to 1.0 with the other side.
        """
        sport_lower = sport.lower()
        direction_upper = direction.upper()

        # Check cache first
        cached = self._lookup_cached(game_date, sport_lower, player_name, prop_type)
        if cached is not None:
            return cached.get("implied_over") if direction_upper == "OVER" else cached.get("implied_under")

        if not _ODDS_CLIENT_AVAILABLE:
            self._write_null_cache(game_date, sport_lower, player_name, prop_type)
            return None

        # Fetch from Odds API
        implied_over = _odds_api_prop(player_name, prop_type, sport_lower, game_date, "OVER")
        implied_under = _odds_api_prop(player_name, prop_type, sport_lower, game_date, "UNDER")

        # Persist (including None — avoids re-fetching on free plan)
        self._write_cache(game_date, sport_lower, player_name, prop_type, implied_over, implied_under)

        return implied_over if direction_upper == "OVER" else implied_under

    def bulk_fetch_player_props(
        self,
        picks: list[dict],
        sport: str,
        game_date: str,
    ) -> dict[str, Optional[float]]:
        """
        Fetch market implied probabilities for a list of picks.

        picks: list of dicts with keys: player_name, prop_type, prediction
        Returns: dict keyed by "{player_name}|{prop_type}" → implied_prob or None
        """
        results = {}
        for pick in picks:
            player = pick.get("player_name", "")
            prop = pick.get("prop_type", "")
            direction = pick.get("prediction", "OVER")
            key = f"{player}|{prop}"
            results[key] = self.get_market_implied(player, prop, sport, game_date, direction)
            time.sleep(0.1)  # mild rate-limit between prop fetches
        return results

    # ------------------------------------------------------------------
    # Game totals (free tier — always works)
    # ------------------------------------------------------------------

    def fetch_game_totals(self, sport: str, game_date: str) -> list[dict]:
        """
        Fetch game-level over/under totals from the free Odds API tier.

        Returns list of game total records. Empty list if no key or no games.
        This provides a game environment signal (high total = offensive game)
        even when player prop odds aren't available.
        """
        if not _ODDS_CLIENT_AVAILABLE:
            return []

        totals = _odds_api_totals(sport.lower(), game_date)

        # Persist to DB
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        for g in totals:
            conn.execute("""
                INSERT OR REPLACE INTO market_game_totals
                    (game_date, sport, home_team, away_team, total,
                     over_odds, under_odds, fair_over, fair_under, bookmaker, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game_date, sport.lower(),
                g.get("home_team", ""), g.get("away_team", ""),
                g.get("total"), g.get("over_odds"), g.get("under_odds"),
                g.get("fair_over_prob"), g.get("fair_under_prob"),
                g.get("bookmaker", ""), now,
            ))
        conn.commit()
        return totals

    def get_game_total(self, sport: str, home_team: str, away_team: str, game_date: str) -> Optional[float]:
        """
        Look up cached game total for a specific game.
        Matches on normalized team names (case-insensitive partial match).
        """
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT total FROM market_game_totals
            WHERE game_date = ? AND sport = ?
            ORDER BY id DESC
        """, (game_date, sport.lower())).fetchall()

        if not rows:
            return None

        home_norm = home_team.lower().strip()
        away_norm = away_team.lower().strip()

        for row in rows:
            # Just return first match if only one game today, or check team names
            if row["total"] is not None:
                return float(row["total"])

        return None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _lookup_cached(self, game_date, sport, player_name, prop_type) -> Optional[dict]:
        """Return cached row dict if exists, else None."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT implied_over, implied_under FROM market_player_props
            WHERE game_date = ? AND sport = ? AND player_name = ? AND prop_type = ?
        """, (game_date, sport, player_name, prop_type)).fetchone()

        if row is None:
            return None
        return {"implied_over": row["implied_over"], "implied_under": row["implied_under"]}

    def _write_cache(self, game_date, sport, player_name, prop_type, implied_over, implied_under, source="odds_api"):
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO market_player_props
                (game_date, sport, player_name, prop_type, implied_over, implied_under, source, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (game_date, sport, player_name, prop_type, implied_over, implied_under, source, now))
        conn.commit()

    def _write_null_cache(self, game_date, sport, player_name, prop_type):
        self._write_cache(game_date, sport, player_name, prop_type, None, None, source="no_client")

    # ------------------------------------------------------------------
    # Coverage report
    # ------------------------------------------------------------------

    def coverage_report(self, game_date: str, sport: str) -> dict:
        """
        Report how many props have market implied probabilities for a given date/sport.
        Useful for monitoring when paid plan is active.
        """
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN implied_over IS NOT NULL THEN 1 ELSE 0 END) as covered
            FROM market_player_props
            WHERE game_date = ? AND sport = ?
        """, (game_date, sport.lower())).fetchone()

        total   = rows["total"] if rows else 0
        covered = rows["covered"] if rows else 0
        pct     = round(covered / total * 100, 1) if total > 0 else 0.0

        return {
            "date":         game_date,
            "sport":        sport.upper(),
            "total_props":  total,
            "with_market":  covered,
            "coverage_pct": pct,
            "has_data":     covered > 0,
        }


# ---------------------------------------------------------------------------
# Edge computation utilities (no API needed)
# ---------------------------------------------------------------------------

def compute_true_edge(
    model_prob: float,
    market_implied: Optional[float],
    pp_break_even: float,
) -> dict:
    """
    Compute both edge flavors and return a unified dict.

    true_edge  = model_prob - market_implied   (vs the market — requires paid plan)
    pp_edge    = model_prob - pp_break_even    (vs PrizePicks payout — always available)

    When market_implied is None (free plan / no data):
      - true_edge = None
      - pp_edge is the operative measure (same as current system)

    When market_implied is available:
      - true_edge is the primary measure
      - pp_edge is kept for comparison

    Returns:
        {
            "true_edge":       float or None,   # vs market (primary when available)
            "pp_edge":         float,            # vs PP break-even (always present)
            "has_market_data": bool,
            "model_prob":      float,
            "market_implied":  float or None,
            "pp_break_even":   float,
        }
    """
    pp_edge = (model_prob - pp_break_even) * 100.0

    if market_implied is None:
        return {
            "true_edge":       None,
            "pp_edge":         round(pp_edge, 2),
            "has_market_data": False,
            "model_prob":      round(model_prob, 4),
            "market_implied":  None,
            "pp_break_even":   round(pp_break_even, 4),
        }

    true_edge = (model_prob - market_implied) * 100.0

    return {
        "true_edge":       round(true_edge, 2),
        "pp_edge":         round(pp_edge, 2),
        "has_market_data": True,
        "model_prob":      round(model_prob, 4),
        "market_implied":  round(market_implied, 4),
        "pp_break_even":   round(pp_break_even, 4),
    }


def american_odds_to_edge(model_prob: float, over_odds: int, under_odds: int) -> dict:
    """
    Compute true edge directly from raw American odds (no Odds API needed).

    Useful when you have odds from another source (e.g., a scraped line).
    Removes vig before comparing to model probability.

    Example:
        over_odds=-115, under_odds=-105
        fair_over=0.521, fair_under=0.479
        model_prob=0.60 → true_edge = (0.60 - 0.521) * 100 = +7.9%
    """
    fair_over, fair_under = remove_vig(over_odds, under_odds)
    true_edge = (model_prob - fair_over) * 100.0
    return {
        "true_edge":    round(true_edge, 2),
        "fair_over":    round(fair_over, 4),
        "fair_under":   round(fair_under, 4),
        "model_prob":   round(model_prob, 4),
        "over_odds":    over_odds,
        "under_odds":   under_odds,
    }


# ---------------------------------------------------------------------------
# CLI for testing
# ---------------------------------------------------------------------------

def _main():
    import argparse

    parser = argparse.ArgumentParser(description="Market Odds Client — ML v2 true edge")
    sub = parser.add_subparsers(dest="cmd")

    # Fetch game totals
    gt = sub.add_parser("totals", help="Fetch game totals (free tier)")
    gt.add_argument("sport", choices=["nba", "nhl", "mlb"])
    gt.add_argument("--date", default=None)

    # Test player prop (shows None on free plan, real prob on paid)
    pp = sub.add_parser("prop", help="Fetch player prop implied prob")
    pp.add_argument("player", help="Player name")
    pp.add_argument("prop", help="Prop type (e.g. points)")
    pp.add_argument("sport", choices=["nba", "nhl", "mlb"])
    pp.add_argument("--date", default=None)

    # Coverage report
    cov = sub.add_parser("coverage", help="Coverage report for a date")
    cov.add_argument("sport", choices=["nba", "nhl", "mlb"])
    cov.add_argument("--date", default=None)

    # Edge calculation demo
    edge = sub.add_parser("edge", help="Compute true edge from raw odds")
    edge.add_argument("model_prob", type=float, help="Model probability (0-1)")
    edge.add_argument("over_odds",  type=int,   help="American odds for OVER (e.g. -115)")
    edge.add_argument("under_odds", type=int,   help="American odds for UNDER (e.g. -105)")

    args = parser.parse_args()
    d = _date.today().isoformat()

    client = MarketOddsClient()

    if args.cmd == "totals":
        game_date = args.date or d
        totals = client.fetch_game_totals(args.sport, game_date)
        if not totals:
            print(f"No game totals for {args.sport.upper()} on {game_date}.")
            print("Check ODDS_API_KEY is set in .env")
        for g in totals:
            print(f"  {g['away_team']} @ {g['home_team']}  O/U {g['total']}  "
                  f"fair OVER={g['fair_over_prob']:.3f}  UNDER={g['fair_under_prob']:.3f}")

    elif args.cmd == "prop":
        game_date = args.date or d
        implied = client.get_market_implied(args.player, args.prop, args.sport, game_date)
        if implied is None:
            print(f"No market implied for {args.player} {args.prop} — free plan or not found.")
            print("Upgrade ODDS_API_KEY to paid plan to see player prop odds.")
        else:
            print(f"{args.player} {args.prop} OVER implied: {implied:.4f} ({implied*100:.1f}%)")

    elif args.cmd == "coverage":
        game_date = args.date or d
        report = client.coverage_report(game_date, args.sport)
        print(f"Coverage: {report['with_market']}/{report['total_props']} props "
              f"({report['coverage_pct']}%) — {report['sport']} {game_date}")

    elif args.cmd == "edge":
        result = american_odds_to_edge(args.model_prob, args.over_odds, args.under_odds)
        print(f"Model: {result['model_prob']:.1%}  |  "
              f"Fair OVER: {result['fair_over']:.1%}  |  "
              f"True Edge: {result['true_edge']:+.1f}%")

    else:
        parser.print_help()

    client.close()


if __name__ == "__main__":
    _main()
