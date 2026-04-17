"""
Pitcher daily aggregation.

Reads raw Statcast pitching Parquet files and produces a silver-layer
pitcher daily aggregate: one row per (pitcher, game_date) with the
velocity, movement, and stuff-quality metrics used for rolling features.
"""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import PATHS
from ingest.statcast_pitching import load_statcast_pitching


def aggregate_pitchers_for_date(game_date: date) -> pd.DataFrame:
    """
    Aggregate Statcast pitch-level data to pitcher daily metrics for one date.

    Parameters
    ----------
    game_date:
        The game date to aggregate.

    Returns
    -------
    DataFrame with columns:
        pitcher, game_date, avg_velocity, avg_break_x, avg_break_z,
        xwoba_allowed, whiff_rate, pitches_thrown
    """
    raw = load_statcast_pitching(game_date)
    if raw.empty:
        logger.warning(f"aggregate_pitchers: no data for {game_date}")
        return pd.DataFrame(
            columns=[
                "pitcher", "game_date", "avg_velocity", "avg_break_x",
                "avg_break_z", "xwoba_allowed", "whiff_rate", "pitches_thrown",
            ]
        )

    grouped = raw.groupby("pitcher")

    agg_dict: dict[str, pd.Series] = {
        "avg_velocity": grouped["release_speed"].mean(),
        "avg_break_x": grouped["pfx_x"].mean(),
        "avg_break_z": grouped["pfx_z"].mean(),
        "xwoba_allowed": grouped["estimated_woba_using_speedangle"].mean(),
        "pitches_thrown": grouped["release_speed"].count(),
    }

    if "whiff_rate" in raw.columns:
        agg_dict["whiff_rate"] = grouped["whiff_rate"].mean()

    agg = pd.DataFrame(agg_dict).reset_index()
    agg["game_date"] = game_date

    cols = [
        "pitcher", "game_date", "avg_velocity", "avg_break_x",
        "avg_break_z", "xwoba_allowed", "whiff_rate", "pitches_thrown",
    ]
    for col in cols:
        if col not in agg.columns:
            agg[col] = np.nan

    agg = agg[cols]
    logger.info(f"Aggregated {len(agg)} pitchers for {game_date}")
    return agg


def aggregate_pitchers_range(start: date, end: date) -> pd.DataFrame:
    """
    Aggregate all dates in [start, end] and return a combined DataFrame.

    Parameters
    ----------
    start:
        First date (inclusive).
    end:
        Last date (inclusive).

    Returns
    -------
    Concatenated daily pitcher aggregates sorted by (pitcher, game_date).
    """
    from utils.dates import date_range

    frames: list[pd.DataFrame] = []
    for d in date_range(start, end):
        frame = aggregate_pitchers_for_date(d)
        if not frame.empty:
            frames.append(frame)

    if not frames:
        logger.warning(f"No pitcher data aggregated for {start} to {end}")
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True).sort_values(
        ["pitcher", "game_date"]
    )


def save_pitchers_silver(df: pd.DataFrame, partition_date: date) -> Path:
    """
    Write a daily pitcher aggregate to the silver layer as Parquet.

    Parameters
    ----------
    df:
        Output of aggregate_pitchers_for_date().
    partition_date:
        Used to name the output file.

    Returns
    -------
    Path to the written file.
    """
    PATHS.silver_pitchers.mkdir(parents=True, exist_ok=True)
    path = PATHS.silver_pitchers / f"{partition_date.isoformat()}.parquet"
    df.to_parquet(path, index=False)
    logger.info(f"Saved pitcher aggregate -> {path.name}")
    return path


def load_pitchers_silver(game_date: date) -> pd.DataFrame:
    """Load silver pitcher aggregate for a specific date."""
    path = PATHS.silver_pitchers / f"{game_date.isoformat()}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)
