"""
data_orchestrator/storage.py

SQLite persistence layer.

Tables:
  raw_stats       — one row per player per game date (box score data)
  odds_lines      — one row per player/prop/bookmaker per fetch
  api_request_log — tracks Odds API usage against daily budget
  nhl_roster      — full player names for initial-name expansion

All writes are upserts (INSERT OR REPLACE) so reruns are safe.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

import pandas as pd

from .config import DB_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS raw_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date   TEXT    NOT NULL,
    sport       TEXT    NOT NULL,
    player_name TEXT    NOT NULL,
    player_id   TEXT,
    team        TEXT    NOT NULL,
    opponent    TEXT,
    home_away   TEXT,
    -- NBA
    points      REAL,
    assists     REAL,
    rebounds    REAL,
    minutes     TEXT,
    -- NHL
    shots_on_goal  INTEGER,
    goals          INTEGER,
    nhl_assists    INTEGER,
    time_on_ice    TEXT,
    -- MLB
    total_bases  REAL,
    at_bats      INTEGER,
    hits         INTEGER,
    -- metadata
    fetched_at  TEXT    NOT NULL,
    UNIQUE(game_date, sport, player_name, team)
);

CREATE TABLE IF NOT EXISTS odds_lines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_date   TEXT    NOT NULL,
    sport        TEXT    NOT NULL,
    player_name  TEXT    NOT NULL,
    prop_type    TEXT    NOT NULL,
    line         REAL,
    over_price   INTEGER,
    under_price  INTEGER,
    implied_over REAL,
    implied_under REAL,
    bookmaker    TEXT    NOT NULL,
    event_id     TEXT,
    home_team    TEXT,
    away_team    TEXT,
    commence_utc TEXT,
    fetched_at   TEXT    NOT NULL,
    UNIQUE(fetch_date, sport, player_name, prop_type, bookmaker)
);

CREATE TABLE IF NOT EXISTS api_request_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    endpoint            TEXT,
    sport               TEXT,
    market              TEXT,
    requests_used       INTEGER,
    requests_remaining  INTEGER,
    http_status         INTEGER
);

CREATE TABLE IF NOT EXISTS nhl_roster (
    player_id   TEXT    PRIMARY KEY,
    full_name   TEXT    NOT NULL,
    team        TEXT    NOT NULL,
    position    TEXT,
    season      TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS player_registry (
    player_id   TEXT    NOT NULL,
    sport       TEXT    NOT NULL,
    full_name   TEXT    NOT NULL,
    team        TEXT,
    position    TEXT,
    active      INTEGER DEFAULT 1,
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (player_id, sport)
);

CREATE INDEX IF NOT EXISTS idx_raw_stats_date    ON raw_stats(game_date, sport);
CREATE INDEX IF NOT EXISTS idx_odds_lines_date   ON odds_lines(fetch_date, sport);
CREATE INDEX IF NOT EXISTS idx_nhl_roster_name   ON nhl_roster(full_name);
CREATE INDEX IF NOT EXISTS idx_registry_sport    ON player_registry(sport, full_name);
"""


# ---------------------------------------------------------------------------
# DataStore
# ---------------------------------------------------------------------------

class DataStore:
    """Thread-safe SQLite wrapper for the orchestrator."""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or DB_PATH
        self._ensure_schema()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self):
        with self._conn() as conn:
            conn.executescript(_DDL)

    # ------------------------------------------------------------------
    # raw_stats
    # ------------------------------------------------------------------

    def upsert_stats(self, df: pd.DataFrame) -> int:
        """
        Upsert rows into raw_stats.
        df must have at minimum: game_date, sport, player_name, team.
        Returns rows written.
        """
        if df.empty:
            return 0

        now = datetime.utcnow().isoformat()
        cols = [
            "game_date", "sport", "player_name", "player_id",
            "team", "opponent", "home_away",
            "points", "assists", "rebounds", "minutes",
            "shots_on_goal", "goals", "nhl_assists", "time_on_ice",
            "total_bases", "at_bats", "hits",
        ]

        with self._conn() as conn:
            count = 0
            for _, row in df.iterrows():
                values = [row.get(c) for c in cols] + [now]
                conn.execute(f"""
                    INSERT OR REPLACE INTO raw_stats
                        ({', '.join(cols)}, fetched_at)
                    VALUES ({', '.join(['?'] * (len(cols) + 1))})
                """, values)
                count += 1
        return count

    def get_stats(self, game_date: str, sport: str = None) -> pd.DataFrame:
        query = "SELECT * FROM raw_stats WHERE game_date = ?"
        params: list = [game_date]
        if sport:
            query += " AND sport = ?"
            params.append(sport.upper())

        with self._conn() as conn:
            return pd.read_sql_query(query, conn, params=params)

    # ------------------------------------------------------------------
    # odds_lines
    # ------------------------------------------------------------------

    def upsert_odds(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0

        now = datetime.utcnow().isoformat()
        cols = [
            "fetch_date", "sport", "player_name", "prop_type",
            "line", "over_price", "under_price",
            "implied_over", "implied_under",
            "bookmaker", "event_id", "home_team", "away_team", "commence_utc",
        ]

        with self._conn() as conn:
            count = 0
            for _, row in df.iterrows():
                values = [row.get(c) for c in cols] + [now]
                conn.execute(f"""
                    INSERT OR REPLACE INTO odds_lines
                        ({', '.join(cols)}, fetched_at)
                    VALUES ({', '.join(['?'] * (len(cols) + 1))})
                """, values)
                count += 1
        return count

    def get_odds(self, fetch_date: str, sport: str = None) -> pd.DataFrame:
        query = "SELECT * FROM odds_lines WHERE fetch_date = ?"
        params: list = [fetch_date]
        if sport:
            query += " AND sport = ?"
            params.append(sport.upper())

        with self._conn() as conn:
            return pd.read_sql_query(query, conn, params=params)

    # ------------------------------------------------------------------
    # NHL roster
    # ------------------------------------------------------------------

    def upsert_nhl_roster(self, players: list[dict], team: str, season: str):
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            for p in players:
                conn.execute("""
                    INSERT OR REPLACE INTO nhl_roster
                        (player_id, full_name, team, position, season, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    str(p["id"]), p["full_name"], team,
                    p.get("position", ""), season, now,
                ))

    def get_nhl_roster(self) -> dict[str, str]:
        """Returns {player_id: full_name} mapping."""
        with self._conn() as conn:
            rows = conn.execute("SELECT player_id, full_name FROM nhl_roster").fetchall()
            return {r["player_id"]: r["full_name"] for r in rows}

    # ------------------------------------------------------------------
    # API request tracking
    # ------------------------------------------------------------------

    def log_api_request(
        self,
        endpoint: str,
        sport: str,
        market: str,
        requests_used: int,
        requests_remaining: int,
        http_status: int,
    ):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO api_request_log
                    (timestamp, endpoint, sport, market,
                     requests_used, requests_remaining, http_status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                endpoint, sport, market,
                requests_used, requests_remaining, http_status,
            ))

    # ------------------------------------------------------------------
    # Player registry (all active players — not just game-log participants)
    # ------------------------------------------------------------------

    def upsert_registry(self, players: list[dict], sport: str):
        """
        players: list of {player_id, full_name, team?, position?}
        """
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            for p in players:
                conn.execute("""
                    INSERT OR REPLACE INTO player_registry
                        (player_id, sport, full_name, team, position, active, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                """, (
                    str(p["player_id"]), sport.upper(), p["full_name"],
                    p.get("team", ""), p.get("position", ""), now,
                ))

    def get_registry_names(self, sport: str) -> list[str]:
        """Return all active player full names for a sport."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT full_name FROM player_registry
                WHERE sport = ? AND active = 1
                ORDER BY full_name
            """, (sport.upper(),)).fetchall()
            return [r["full_name"] for r in rows]

    def registry_size(self, sport: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM player_registry WHERE sport=? AND active=1",
                (sport.upper(),)
            ).fetchone()
            return row[0] if row else 0

    def requests_used_today(self) -> int:
        """Count API requests logged since midnight UTC today."""
        today = datetime.utcnow().date().isoformat()
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS cnt FROM api_request_log
                WHERE timestamp >= ?
            """, (today,)).fetchone()
            return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # Merged view for ML consumption
    # ------------------------------------------------------------------

    def get_merged_picks(self, game_date: str, sport: str = None) -> pd.DataFrame:
        """
        Join raw_stats + odds_lines on (game_date/fetch_date, sport, player_name).
        Returns a clean DataFrame ready for XGBoost/Bayesian ingestion.
        """
        query = """
            SELECT
                s.game_date,
                s.sport,
                s.player_name,
                s.team,
                s.opponent,
                s.home_away,
                -- NBA
                s.points   AS actual_points,
                s.assists,
                s.rebounds,
                -- NHL
                s.shots_on_goal AS actual_sog,
                s.goals,
                -- MLB
                s.total_bases AS actual_total_bases,
                s.at_bats,
                s.hits,
                -- Odds
                o.prop_type,
                o.line        AS prop_line,
                o.over_price,
                o.under_price,
                o.implied_over,
                o.implied_under,
                o.bookmaker,
                o.home_team,
                o.away_team,
                o.commence_utc
            FROM raw_stats s
            LEFT JOIN odds_lines o
                ON  s.game_date = o.fetch_date
                AND s.sport     = o.sport
                AND s.player_name = o.player_name
            WHERE s.game_date = ?
        """
        params: list = [game_date]
        if sport:
            query += " AND s.sport = ?"
            params.append(sport.upper())

        with self._conn() as conn:
            return pd.read_sql_query(query, conn, params=params)
