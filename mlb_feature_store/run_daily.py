"""
Daily MLB ingestion pipeline.

Steps
-----
1. Determine the last ingested date from DuckDB metadata.
2. Skip if today's data has already been processed.
3. Ingest Statcast hitting + pitching for the target date.
4. Ingest FanGraphs season stats (skipped if already on disk).
5. Aggregate hitters and pitchers to daily silver.
6. Compute rolling features (hitters + pitchers).
7. Compute opponent strength.
8. Merge gold-layer feature tables.
9. Upsert all four DuckDB tables and update metadata.

Usage
-----
    python run_daily.py                   # defaults to yesterday
    python run_daily.py --date 2024-05-10
"""

import argparse
import sys
from datetime import date, timedelta

from loguru import logger

from config.settings import PATHS
from feature_store.build_duckdb import (
    get_connection,
    get_last_ingested_date,
    initialize_schema,
    set_last_ingested_date,
    upsert_hitter_labels,
    upsert_hitters_daily,
    upsert_pitcher_features,
    upsert_pitcher_labels,
    upsert_pitchers_daily,
    upsert_player_features,
)
from labels.compute_labels import compute_labels_for_date
from ingest.fangraphs_hitting import ingest_fangraphs_hitting, load_fangraphs_hitting
from ingest.fangraphs_pitching import ingest_fangraphs_pitching, load_fangraphs_pitching
from ingest.statcast_hitting import ingest_statcast_hitting, load_statcast_hitting
from ingest.statcast_pitching import ingest_statcast_pitching, load_statcast_pitching
from transform.aggregate_hitters import aggregate_hitters_for_date, save_hitters_silver
from transform.aggregate_pitchers import aggregate_pitchers_for_date, save_pitchers_silver
from transform.merge_features import build_hitter_features, build_pitcher_features, save_gold_features
from transform.opponent_strength import add_hitter_opponent_strength, add_pitcher_opponent_strength
from transform.rolling_features import add_hitter_rolling_features, add_pitcher_rolling_features
from utils.logging import setup_logger


DATA_TYPE_HITTING = "statcast_hitting"
DATA_TYPE_PITCHING = "statcast_pitching"


def run_daily(target_date: date | None = None, force: bool = False) -> None:
    """
    Execute the full daily ingestion and feature computation pipeline.

    Parameters
    ----------
    target_date:
        Date to process.  Defaults to yesterday (last complete game day).
    """
    setup_logger()
    PATHS.ensure_all()

    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    season = target_date.year
    date_str = target_date.isoformat()
    logger.info(f"=== Daily pipeline starting for {date_str} ===")

    conn = get_connection()
    initialize_schema(conn)

    last_hitting = get_last_ingested_date(conn, DATA_TYPE_HITTING)
    if not force and last_hitting and last_hitting >= target_date:
        logger.info(f"Already ingested through {last_hitting}; nothing to do for {target_date}.")
        conn.close()
        return

    # ------------------------------------------------------------------
    # Step 1: Ingest raw data
    # ------------------------------------------------------------------
    logger.info("Step 1 — Ingesting Statcast data")
    ingest_statcast_hitting(target_date, target_date, force=force)
    ingest_statcast_pitching(target_date, target_date)

    logger.info("Step 1b — Ingesting FanGraphs season data (skips if cached)")
    ingest_fangraphs_hitting(season)
    ingest_fangraphs_pitching(season)

    fg_hitting = load_fangraphs_hitting(season)
    fg_pitching = load_fangraphs_pitching(season)

    # ------------------------------------------------------------------
    # Step 2: Aggregate to daily silver
    # ------------------------------------------------------------------
    logger.info("Step 2 — Aggregating daily stats")
    hitter_daily = aggregate_hitters_for_date(target_date)
    pitcher_daily = aggregate_pitchers_for_date(target_date)

    save_hitters_silver(hitter_daily, target_date)
    save_pitchers_silver(pitcher_daily, target_date)

    upsert_hitters_daily(conn, hitter_daily)
    upsert_pitchers_daily(conn, pitcher_daily)

    # ------------------------------------------------------------------
    # Step 3: Rolling features
    # ------------------------------------------------------------------
    logger.info("Step 3 — Computing rolling features")
    hitter_rolling = add_hitter_rolling_features(hitter_daily) if not hitter_daily.empty else hitter_daily
    pitcher_rolling = add_pitcher_rolling_features(pitcher_daily) if not pitcher_daily.empty else pitcher_daily

    # ------------------------------------------------------------------
    # Step 4: Opponent strength
    # ------------------------------------------------------------------
    logger.info("Step 4 — Computing opponent strength")
    hitter_with_opp = add_hitter_opponent_strength(hitter_rolling, fg_hitting)
    pitcher_with_opp = add_pitcher_opponent_strength(pitcher_rolling, fg_hitting)

    # ------------------------------------------------------------------
    # Step 5: Gold features
    # ------------------------------------------------------------------
    logger.info("Step 5 — Building gold feature tables")
    hitter_features = build_hitter_features(hitter_with_opp, fg_hitting)
    pitcher_features = build_pitcher_features(pitcher_with_opp, fg_pitching)
    save_gold_features(hitter_features, pitcher_features, target_date)

    # ------------------------------------------------------------------
    # Step 6: Update DuckDB
    # ------------------------------------------------------------------
    logger.info("Step 6 — Updating DuckDB feature store")
    upsert_player_features(conn, hitter_features)
    upsert_pitcher_features(conn, pitcher_features)
    set_last_ingested_date(conn, DATA_TYPE_HITTING, target_date)
    set_last_ingested_date(conn, DATA_TYPE_PITCHING, target_date)

    # ------------------------------------------------------------------
    # Step 7: Prop outcome labels
    # ------------------------------------------------------------------
    logger.info("Step 7 — Computing prop outcome labels")
    hitter_labels, pitcher_labels = compute_labels_for_date(target_date)
    upsert_hitter_labels(conn, hitter_labels)
    upsert_pitcher_labels(conn, pitcher_labels)

    conn.commit()
    conn.close()
    logger.info(f"=== Daily pipeline complete for {date_str} ===")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily MLB ingestion pipeline")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: yesterday)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    target = date.fromisoformat(args.date) if args.date else None
    run_daily(target)
