"""
DuckDB feature store builder.

Creates and maintains the mlb.duckdb file, manages the ingestion_metadata
table for incremental backfill tracking, and exposes upsert helpers for
each feature table defined in schema.sql.
"""

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from loguru import logger

from config.settings import PATHS


def get_connection() -> duckdb.DuckDBPyConnection:
    """Open (or create) the DuckDB feature store and return a connection."""
    PATHS.duckdb.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(PATHS.duckdb))


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Execute schema.sql to create all tables if they do not exist.

    Parameters
    ----------
    conn:
        Open DuckDB connection.
    """
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    # DuckDB executescript not available — split on semicolons
    for statement in sql.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)
    logger.info("DuckDB schema initialized")


def get_last_ingested_date(
    conn: duckdb.DuckDBPyConnection,
    data_type: str,
) -> date | None:
    """
    Return the most recently ingested date for a data type.

    Parameters
    ----------
    conn:
        Open DuckDB connection.
    data_type:
        Label for the ingestion type (e.g. 'statcast_hitting').

    Returns
    -------
    Last ingested date, or None if never run.
    """
    row = conn.execute(
        "SELECT last_ingested_date FROM ingestion_metadata WHERE data_type = ?",
        [data_type],
    ).fetchone()
    return row[0] if row else None


def set_last_ingested_date(
    conn: duckdb.DuckDBPyConnection,
    data_type: str,
    d: date,
) -> None:
    """
    Upsert the last ingested date for a data type.

    Parameters
    ----------
    conn:
        Open DuckDB connection.
    data_type:
        Label for the ingestion type.
    d:
        Date to record.
    """
    conn.execute(
        """
        INSERT INTO ingestion_metadata (data_type, last_ingested_date, updated_at)
        VALUES (?, ?, current_timestamp)
        ON CONFLICT (data_type) DO UPDATE SET
            last_ingested_date = excluded.last_ingested_date,
            updated_at = excluded.updated_at
        """,
        [data_type, d],
    )


def _upsert(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    df: pd.DataFrame,
    pk_cols: list[str],
) -> None:
    """
    Generic upsert: delete matching PKs then insert fresh rows.

    Parameters
    ----------
    conn:
        Open DuckDB connection.
    table:
        Target table name.
    df:
        DataFrame whose columns must match the table schema.
    pk_cols:
        Primary key column names used to identify rows to delete.
    """
    if df.empty:
        return

    # Build a WHERE clause on pk_cols to delete existing rows
    where = " AND ".join(f"t.{c} = s.{c}" for c in pk_cols)
    pk_select = ", ".join(pk_cols)
    conn.execute(
        f"DELETE FROM {table} t USING df s WHERE {where}"
    )
    cols = ", ".join(df.columns)
    conn.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM df")
    logger.info(f"Upserted {len(df):,} rows into {table}")


def upsert_hitters_daily(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """Upsert hitter daily aggregates (player_id, date primary key)."""
    if df.empty:
        return
    # Align column names to schema
    rename = {"batter": "player_id", "game_date": "date"}
    out = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    out["player_id"] = out["player_id"].astype(str)
    schema_cols = ["player_id", "date", "avg_ev", "avg_la", "xwoba", "pa", "hard_hit_rate"]
    present = [c for c in schema_cols if c in out.columns]
    _upsert(conn, "hitters_daily", out[present], ["player_id", "date"])


def upsert_pitchers_daily(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """Upsert pitcher daily aggregates (pitcher_id, date primary key)."""
    if df.empty:
        return
    rename = {"pitcher": "pitcher_id", "game_date": "date"}
    out = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    out["pitcher_id"] = out["pitcher_id"].astype(str)
    schema_cols = [
        "pitcher_id", "date", "avg_velocity", "avg_break_x",
        "avg_break_z", "xwoba_allowed", "whiff_rate", "pitches_thrown",
    ]
    # pitches_thrown may be named pitches in some aggregates
    if "pitches" in out.columns and "pitches_thrown" not in out.columns:
        out = out.rename(columns={"pitches": "pitches_thrown"})
    present = [c for c in schema_cols if c in out.columns]
    _upsert(conn, "pitchers_daily", out[present], ["pitcher_id", "date"])


def upsert_player_features(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """Upsert gold-layer hitter features (player_id, date primary key)."""
    if df.empty:
        return
    out = df.copy()
    out["player_id"] = out["player_id"].astype(str)
    # Normalize FanGraphs column names to schema names
    col_map = {"wRC+": "wrc_plus", "WPA": "wpa", "RE24": "re24"}
    out = out.rename(columns={k: v for k, v in col_map.items() if k in out.columns})
    schema_cols = [
        "player_id", "date", "wrc_plus", "wpa", "re24",
        "avg_ev", "avg_la", "xwoba", "ev_7d", "xwoba_14d",
        "opp_strength_7d", "park_adjusted_woba",
    ]
    present = [c for c in schema_cols if c in out.columns]
    _upsert(conn, "player_features", out[present], ["player_id", "date"])


def upsert_pitcher_features(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """Upsert gold-layer pitcher features (pitcher_id, date primary key)."""
    if df.empty:
        return
    out = df.copy()
    out["pitcher_id"] = out["pitcher_id"].astype(str)
    schema_cols = [
        "pitcher_id", "date", "avg_velocity", "whiff_rate", "xwoba_allowed",
        "velocity_trend_7d", "opponent_strength", "park_adjusted_xwoba",
    ]
    present = [c for c in schema_cols if c in out.columns]
    _upsert(conn, "pitcher_features", out[present], ["pitcher_id", "date"])


def upsert_hitter_labels(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """Upsert hitter prop outcome labels (player_id, game_date primary key)."""
    if df.empty:
        return
    out = df.copy()
    out["player_id"] = out["player_id"].astype(str)
    schema_cols = ["player_id", "game_date", "hits", "total_bases", "home_runs"]
    present = [c for c in schema_cols if c in out.columns]
    _upsert(conn, "hitter_labels", out[present], ["player_id", "game_date"])


def upsert_pitcher_labels(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """Upsert pitcher prop outcome labels (player_id, game_date primary key)."""
    if df.empty:
        return
    out = df.copy()
    out["player_id"] = out["player_id"].astype(str)
    schema_cols = ["player_id", "game_date", "strikeouts", "walks", "outs_recorded"]
    present = [c for c in schema_cols if c in out.columns]
    _upsert(conn, "pitcher_labels", out[present], ["player_id", "game_date"])
