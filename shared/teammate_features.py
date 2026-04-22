"""
shared/teammate_features.py

Phase 5 — Teammate On/Off adjustment features for ML v2.

Two-part system:
  1. LineupStatusClient: fetches today's inactive/injured players from BALLDONTLIE API
  2. TeammateFeatures: computes on/off adjustment factors from player_game_logs

The adjustment factor is multiplicative on the stat level (then regressed into prob space):
  - factor > 1.0: star is OUT, player gets more usage -> boost OVER probability
  - factor < 1.0: star is IN but usage decreases (unusual)
  - factor = 1.0: lineup data unavailable or splits too thin (no change)

Usage:
    from shared.teammate_features import TeammateFeatures, apply_teammate_adjustment

    tf = TeammateFeatures(sport="nba")
    factor = tf.get_adjustment("Austin Reaves", "LAL", "points", "2026-04-22")
    # -> 1.15 if LeBron is confirmed OUT (Reaves averages +15% points without him)
    # -> 1.00 if lineup data unavailable or split is too thin

    adjusted_prob = apply_teammate_adjustment(base_prob=0.60, factor=factor)
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_SHARED_DIR = Path(__file__).resolve().parent
_LINEUP_DB  = _SHARED_DIR / "lineup_status.db"

_BALLDONTLIE_BASE = "https://api.balldontlie.io/v1"

_PROP_TO_COL: dict[str, str] = {
    "points":    "points",
    "rebounds":  "rebounds",
    "assists":   "assists",
    "steals":    "steals",
    "blocks":    "blocks",
    "turnovers": "turnovers",
    "threes":    "threes_made",
    "pra":       "pra",
    "stocks":    "stocks",
}

_MIN_GAMES_WITH    = 5   # min games with star to trust the split
_MIN_GAMES_WITHOUT = 3   # min games without star to trust the split
_MAX_ADJUSTMENT    = 1.30
_MIN_ADJUSTMENT    = 0.75

# ---------------------------------------------------------------------------
# DB schema
# ---------------------------------------------------------------------------

_CREATE_LINEUP = """
CREATE TABLE IF NOT EXISTS lineup_status (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date   TEXT NOT NULL,
    sport       TEXT NOT NULL,
    player_name TEXT NOT NULL,
    team        TEXT NOT NULL,
    status      TEXT NOT NULL,
    reason      TEXT,
    source      TEXT DEFAULT 'balldontlie',
    fetched_at  TEXT NOT NULL,
    UNIQUE(game_date, sport, player_name)
)
"""

_CREATE_FETCH_LOG = """
CREATE TABLE IF NOT EXISTS lineup_fetch_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date    TEXT NOT NULL,
    sport        TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    player_count INTEGER,
    UNIQUE(game_date, sport)
)
"""


# ---------------------------------------------------------------------------
# LineupStatusClient
# ---------------------------------------------------------------------------

class LineupStatusClient:
    """
    Fetches and caches player injury/inactive status from BALLDONTLIE API.

    Free tier: 15 req/min. Results cached in shared/lineup_status.db so each
    date is fetched at most once per sport per day.

    Falls back to empty list when:
    - BALLDONTLIE_API_KEY not set
    - requests library unavailable
    - API request fails
    """

    def __init__(self, db_path: str | Path = None, api_key: str = None):
        self.db_path = Path(db_path) if db_path else _LINEUP_DB
        self.api_key = api_key or os.getenv("BALLDONTLIE_API_KEY", "")
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db()

    def _ensure_db(self):
        with self._get_conn() as conn:
            conn.execute(_CREATE_LINEUP)
            conn.execute(_CREATE_FETCH_LOG)
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

    def _headers(self) -> dict:
        return {"Authorization": self.api_key} if self.api_key else {}

    def _already_fetched(self, game_date: str, sport: str) -> bool:
        row = self._get_conn().execute(
            "SELECT id FROM lineup_fetch_log WHERE game_date=? AND sport=?",
            (game_date, sport),
        ).fetchone()
        return row is not None

    def fetch_injuries(self, game_date: str, sport: str = "nba") -> list[dict]:
        """
        Fetch player injuries from BALLDONTLIE (paid tier required).

        NOTE: /v1/player_injuries requires BALLDONTLIE All-Star plan ($9.99/mo).
        On the free tier this returns 401 and falls through to the log-based
        inference fallback in get_inactive_players().

        Returns list of dicts: {player_name, team, status, reason}.
        Empty list on free plan or any failure.
        """
        if not self.api_key or not _REQUESTS_OK:
            return []

        if self._already_fetched(game_date, sport):
            return self._load_cached(game_date, sport)

        url = f"{_BALLDONTLIE_BASE}/player_injuries"
        cursor = None
        records: list[dict] = []

        while True:
            params = {"per_page": 100}
            if cursor:
                params["cursor"] = cursor

            try:
                resp = _requests.get(url, headers=self._headers(), params=params, timeout=10)
                if resp.status_code == 401:
                    # Paid endpoint — silently return empty (fallback handles it)
                    break
                resp.raise_for_status()
                body = resp.json()
            except Exception:
                break

            data = body.get("data", [])
            if not data:
                break

            now = datetime.utcnow().isoformat()
            conn = self._get_conn()

            for item in data:
                player    = item.get("player", {})
                team_info = item.get("team", {})
                full_name = (
                    f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
                )
                team_abbr = team_info.get("abbreviation", "")
                status    = self._normalize_status(item.get("status", ""))
                reason    = item.get("description", "")

                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO lineup_status
                            (game_date, sport, player_name, team, status, reason, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (game_date, sport, full_name, team_abbr, status, reason, now))
                    records.append({
                        "player_name": full_name,
                        "team":        team_abbr,
                        "status":      status,
                        "reason":      reason,
                    })
                except Exception:
                    continue

            conn.commit()

            meta = body.get("meta", {})
            cursor = meta.get("next_cursor")
            if not cursor:
                break
            time.sleep(0.5)

        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO lineup_fetch_log
                (game_date, sport, fetched_at, player_count)
            VALUES (?, ?, ?, ?)
        """, (game_date, sport, datetime.utcnow().isoformat(), len(records)))
        conn.commit()

        return records

    def infer_inactive_from_logs(
        self,
        team: str,
        game_date: str,
        sport: str,
        db_path: Path,
        lookback: int = 3,
        min_appearances: int = 15,
    ) -> list[str]:
        """
        Fallback: infer likely-inactive players from recent game log absences.

        Logic: if a player appeared in 15+ games this season (established rotation),
        but their team played in the last `lookback` games and the player did NOT
        appear in any of them, flag them as likely inactive.

        This is an inference, not ground truth. Confidence is lower than the
        paid injury API. Returns player names tagged 'inferred_inactive'.
        """
        try:
            conn = sqlite3.connect(str(db_path), timeout=30)
            conn.row_factory = sqlite3.Row

            # Most recent game dates for this team before game_date
            team_dates = conn.execute("""
                SELECT DISTINCT game_date FROM player_game_logs
                WHERE team = ? AND game_date < ?
                ORDER BY game_date DESC
                LIMIT ?
            """, (team, game_date, lookback)).fetchall()

            if len(team_dates) < lookback:
                conn.close()
                return []

            recent_dates = [r["game_date"] for r in team_dates]

            # Established rotation: played 15+ games this season for this team
            rotation = conn.execute("""
                SELECT player_name FROM player_game_logs
                WHERE team = ? AND minutes > 5
                GROUP BY player_name
                HAVING COUNT(*) >= ?
            """, (team, min_appearances)).fetchall()
            rotation_names = {r["player_name"] for r in rotation}

            # Who appeared in the recent games?
            active_recent = conn.execute(f"""
                SELECT DISTINCT player_name FROM player_game_logs
                WHERE team = ?
                  AND game_date IN ({','.join('?' * len(recent_dates))})
                  AND minutes > 5
            """, [team] + recent_dates).fetchall()
            active_names = {r["player_name"] for r in active_recent}
            conn.close()

            # Rotation members who didn't appear in any recent games = likely inactive
            inferred_out = list(rotation_names - active_names)

            if not inferred_out:
                return []

            # Persist inferred status to lineup_status.db
            now = datetime.utcnow().isoformat()
            db_conn = self._get_conn()
            for name in inferred_out:
                try:
                    db_conn.execute("""
                        INSERT OR IGNORE INTO lineup_status
                            (game_date, sport, player_name, team, status, reason, source, fetched_at)
                        VALUES (?, ?, ?, ?, 'inferred_inactive',
                                'missed last 3 team games (log inference)', 'log_inference', ?)
                    """, (game_date, sport, name, team, now))
                except Exception:
                    continue
            db_conn.commit()

            return inferred_out

        except Exception:
            return []

    def get_inactive_players(
        self,
        team: str,
        game_date: str,
        sport: str = "nba",
        game_logs_db: Path = None,
    ) -> list[str]:
        """
        Return player names that are OUT for this team/date.

        Priority:
          1. Paid BALLDONTLIE injury API (status='inactive')
          2. Log-based inference (status='inferred_inactive') — free tier fallback
          3. Empty list if neither source has data
        """
        self.fetch_injuries(game_date, sport)

        rows = self._get_conn().execute("""
            SELECT player_name FROM lineup_status
            WHERE game_date=? AND sport=? AND team=?
              AND status IN ('inactive', 'inferred_inactive')
        """, (game_date, sport, team)).fetchall()

        if rows:
            return [r["player_name"] for r in rows]

        # Fallback: infer from game logs if db_path provided
        if game_logs_db and game_logs_db.exists():
            return self.infer_inactive_from_logs(team, game_date, sport, game_logs_db)

        return []

    def _load_cached(self, game_date: str, sport: str) -> list[dict]:
        rows = self._get_conn().execute("""
            SELECT player_name, team, status, reason FROM lineup_status
            WHERE game_date=? AND sport=?
        """, (game_date, sport)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _normalize_status(raw: str) -> str:
        s = raw.lower()
        if "out" in s:
            return "inactive"
        if "day-to-day" in s or "dtd" in s or "questionable" in s:
            return "day_to_day"
        return "active"


# ---------------------------------------------------------------------------
# TeammateFeatures
# ---------------------------------------------------------------------------

class TeammateFeatures:
    """
    Computes on/off adjustment factors for player props from historical game logs.

    Algorithm per player/prop:
    1. Identify top-N star teammates by average minutes (excludes target player)
    2. Get confirmed inactive players for today's game from LineupStatusClient
    3. For each star that's confirmed OUT:
       - Split player's historical logs into games with/without that star
       - Compute adjustment = avg_without / avg_with (capped at [0.75, 1.30])
    4. Multiply individual star adjustments together, re-cap the combined result
    5. Return 1.0 when data is insufficient or no stars are OUT
    """

    def __init__(
        self,
        sport: str,
        db_path: str | Path = None,
        lineup_client: LineupStatusClient = None,
    ):
        self.sport   = sport.lower()
        self.db_path = Path(db_path) if db_path else self._default_db()
        self.lineup  = lineup_client or LineupStatusClient()

    def _default_db(self) -> Path:
        root = Path(__file__).resolve().parent.parent
        paths = {
            "nba": root / "nba" / "database" / "nba_predictions.db",
            "nhl": root / "nhl" / "database" / "nhl_predictions_v2.db",
            "mlb": root / "mlb" / "database" / "mlb_predictions.db",
        }
        if self.sport not in paths:
            raise ValueError(f"Unsupported sport for teammate features: {self.sport}")
        return paths[self.sport]

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path), timeout=30)
        c.row_factory = sqlite3.Row
        return c

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_adjustment(
        self,
        player_name: str,
        team: str,
        prop_type: str,
        game_date: str,
        n_stars: int = 3,
    ) -> float:
        """
        Return multiplicative stat-level adjustment factor for a player's prop.

        1.0 means no adjustment (data insufficient or no stars OUT).
        Pass the result to apply_teammate_adjustment() to convert to prob space.
        """
        col = _PROP_TO_COL.get(prop_type.lower())
        if col is None:
            return 1.0

        stars = self._identify_stars(player_name, team, n=n_stars)
        if not stars:
            return 1.0

        inactive = self.lineup.get_inactive_players(
            team, game_date, self.sport, game_logs_db=self.db_path
        )
        if not inactive:
            return 1.0

        combined = 1.0
        for star in stars:
            if not _fuzzy_name_match(star, inactive):
                continue
            avg_with, avg_without = self._on_off_split(player_name, team, col, star)
            if avg_with is None or avg_without is None or avg_with < 0.01:
                continue
            raw = avg_without / avg_with
            combined *= max(_MIN_ADJUSTMENT, min(_MAX_ADJUSTMENT, raw))

        return round(max(_MIN_ADJUSTMENT, min(_MAX_ADJUSTMENT, combined)), 4)

    def on_off_report(
        self,
        player_name: str,
        team: str,
        prop_type: str,
        n_stars: int = 5,
    ) -> list[dict]:
        """
        Return on/off split breakdown for all top-N stars — useful for debugging.
        """
        col = _PROP_TO_COL.get(prop_type.lower())
        if col is None:
            return []

        stars = self._identify_stars(player_name, team, n=n_stars)
        report = []
        for star in stars:
            avg_with, avg_without = self._on_off_split(player_name, team, col, star)
            report.append({
                "star":          star,
                "avg_with":      round(avg_with, 2) if avg_with is not None else None,
                "avg_without":   round(avg_without, 2) if avg_without is not None else None,
                "raw_factor":    round(avg_without / avg_with, 4)
                                 if avg_with and avg_without and avg_with > 0.01 else None,
            })
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _identify_stars(self, player_name: str, team: str, n: int) -> list[str]:
        """Top-N teammates by average minutes over the season (min 10 games)."""
        conn = self._conn()
        try:
            rows = conn.execute("""
                SELECT player_name, AVG(minutes) AS avg_min
                FROM player_game_logs
                WHERE team = ?
                  AND player_name != ?
                  AND minutes > 10
                GROUP BY player_name
                HAVING COUNT(*) >= 10
                ORDER BY avg_min DESC
                LIMIT ?
            """, (team, player_name, n)).fetchall()
            return [r["player_name"] for r in rows]
        finally:
            conn.close()

    def _on_off_split(
        self,
        player_name: str,
        team: str,
        col: str,
        star_name: str,
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Split player's game logs into games with/without star, return averages.
        Returns (None, None) if either split has too few games.
        """
        conn = self._conn()
        try:
            star_rows = conn.execute("""
                SELECT game_date FROM player_game_logs
                WHERE player_name = ? AND team = ? AND minutes > 10
            """, (star_name, team)).fetchall()
            star_dates = {r["game_date"] for r in star_rows}

            player_rows = conn.execute(f"""
                SELECT game_date, {col} AS stat FROM player_game_logs
                WHERE player_name = ? AND team = ? AND minutes > 10
            """, (player_name, team)).fetchall()

            with_star    = [r["stat"] for r in player_rows if r["game_date"] in star_dates]
            without_star = [r["stat"] for r in player_rows if r["game_date"] not in star_dates]

            if len(with_star) < _MIN_GAMES_WITH or len(without_star) < _MIN_GAMES_WITHOUT:
                return None, None

            return sum(with_star) / len(with_star), sum(without_star) / len(without_star)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# apply_teammate_adjustment() — converts stat-level factor into prob space
# ---------------------------------------------------------------------------

def apply_teammate_adjustment(
    base_prob: float,
    factor: float,
    regress_strength: float = 0.5,
) -> float:
    """
    Apply a teammate on/off stat factor to a base OVER probability.

    Uses partial regression toward the mean so adjustments are conservative:
        adjusted = base_prob + regress_strength * (factor - 1.0) * (base_prob - 0.5)

    Properties:
    - factor=1.0  -> no change (always)
    - factor=1.15 on base_prob=0.60 -> 0.60 + 0.5*0.15*0.10 = 0.6075
    - Probability stays in (0.01, 0.99)
    - regress_strength=0.5 is conservative; raise toward 1.0 for stronger adjustments

    Args:
        base_prob:        OVER probability from the statistical/ML model (0-1)
        factor:           Adjustment factor from TeammateFeatures.get_adjustment()
        regress_strength: How aggressively to move the probability (default 0.5)
    """
    if factor == 1.0:
        return base_prob
    adjusted = base_prob + regress_strength * (factor - 1.0) * (base_prob - 0.5)
    return round(max(0.01, min(0.99, adjusted)), 4)


# ---------------------------------------------------------------------------
# Fuzzy name matching
# ---------------------------------------------------------------------------

def _fuzzy_name_match(name: str, name_list: list[str]) -> bool:
    """
    True if `name` appears in `name_list` by exact match or shared last name.
    Last-name match requires len > 3 to avoid false positives (e.g. "Lee").
    """
    name_lower = name.lower().strip()
    parts = name_lower.split()
    last = parts[-1] if parts else ""

    for candidate in name_list:
        c_lower = candidate.lower().strip()
        if name_lower == c_lower:
            return True
        c_parts = c_lower.split()
        c_last  = c_parts[-1] if c_parts else ""
        if last and last == c_last and len(last) > 3:
            return True
    return False


# ---------------------------------------------------------------------------
# CLI for testing/debugging
# ---------------------------------------------------------------------------

def _main():
    import argparse

    parser = argparse.ArgumentParser(description="Teammate On/Off Features — ML v2 Phase 5")
    sub = parser.add_subparsers(dest="cmd")

    # Fetch today's injuries
    inj = sub.add_parser("injuries", help="Fetch + cache today's injury report")
    inj.add_argument("--sport",  default="nba")
    inj.add_argument("--date",   default=None)

    # Show inactive players for a team
    team_cmd = sub.add_parser("inactive", help="List confirmed OUT players for a team")
    team_cmd.add_argument("team", help="Team abbreviation (e.g. LAL)")
    team_cmd.add_argument("--sport", default="nba")
    team_cmd.add_argument("--date",  default=None)

    # On/off split report for a player
    report = sub.add_parser("report", help="On/off split report for a player")
    report.add_argument("player", help="Player name")
    report.add_argument("team",   help="Team abbreviation (e.g. LAL)")
    report.add_argument("prop",   help="Prop type (e.g. points)")
    report.add_argument("--sport", default="nba")
    report.add_argument("--stars", type=int, default=5)

    # Compute adjustment for a player on a given date
    adjust = sub.add_parser("adjust", help="Compute on/off adjustment for today")
    adjust.add_argument("player")
    adjust.add_argument("team")
    adjust.add_argument("prop")
    adjust.add_argument("--sport", default="nba")
    adjust.add_argument("--date",  default=None)

    args = parser.parse_args()
    today = datetime.utcnow().date().isoformat()

    if args.cmd == "injuries":
        date = args.date or today
        client = LineupStatusClient()
        records = client.fetch_injuries(date, args.sport)
        out_count = sum(1 for r in records if r["status"] == "inactive")
        dtd_count = sum(1 for r in records if r["status"] == "day_to_day")
        print(f"{args.sport.upper()} {date}: {len(records)} players | "
              f"OUT={out_count} DTD={dtd_count}")
        for r in records:
            if r["status"] == "inactive":
                print(f"  OUT  {r['team']:4s}  {r['player_name']}  ({r['reason']})")
        client.close()

    elif args.cmd == "inactive":
        date = args.date or today
        client = LineupStatusClient()
        players = client.get_inactive_players(args.team, date, args.sport)
        print(f"Confirmed OUT for {args.team} on {date}: {players or '(none)'}")
        client.close()

    elif args.cmd == "report":
        tf = TeammateFeatures(sport=args.sport)
        rows = tf.on_off_report(args.player, args.team, args.prop, n_stars=args.stars)
        print(f"\nOn/Off splits for {args.player} ({args.team}) — {args.prop}")
        print(f"{'Star':<28} {'With':>8} {'Without':>8} {'Factor':>8}")
        print("-" * 56)
        for r in rows:
            factor_str = f"{r['raw_factor']:+.3f}" if r["raw_factor"] is not None else "  n/a"
            with_str   = f"{r['avg_with']:.1f}"   if r["avg_with"]   is not None else "n/a"
            without_str = f"{r['avg_without']:.1f}" if r["avg_without"] is not None else "n/a"
            print(f"{r['star']:<28} {with_str:>8} {without_str:>8} {factor_str:>8}")

    elif args.cmd == "adjust":
        date = args.date or today
        tf = TeammateFeatures(sport=args.sport)
        factor = tf.get_adjustment(args.player, args.team, args.prop, date)
        print(f"Adjustment factor for {args.player} ({args.team}) {args.prop} on {date}: {factor}")
        if factor != 1.0:
            for base in [0.50, 0.55, 0.60, 0.65, 0.70]:
                adj = apply_teammate_adjustment(base, factor)
                print(f"  base={base:.2f} -> adjusted={adj:.4f} (delta={adj-base:+.4f})")

    else:
        parser.print_help()


if __name__ == "__main__":
    _main()
