"""
Gold-layer feature merge.

Joins Statcast rolling aggregates with FanGraphs season-level metrics
and applies park factors to produce the final ML-ready feature tables.
"""

from datetime import date
from pathlib import Path

import pandas as pd
from loguru import logger

from config.settings import PATHS
from ingest.park_factors import apply_park_factor
from utils.io import save_parquet


def build_hitter_features(
    hitter_rolling: pd.DataFrame,
    fg_hitting: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge Statcast rolling features with FanGraphs metrics for hitters.

    Final schema:
        player_id, date, wRC+, WPA, RE24, avg_ev, avg_la, xwoba,
        ev_7d, xwoba_14d, opp_strength_7d, park_adjusted_woba

    Parameters
    ----------
    hitter_rolling:
        Output of add_hitter_rolling_features() (+ opponent strength).
    fg_hitting:
        FanGraphs hitting DataFrame with IDfg, wRC+, WPA, RE24, wOBA columns.

    Returns
    -------
    Gold-layer hitter feature DataFrame.
    """
    if hitter_rolling.empty:
        return pd.DataFrame()

    df = hitter_rolling.rename(columns={"batter": "player_id", "game_date": "date"})
    df["player_id"] = df["player_id"].astype(str)

    fg_cols = ["IDfg", "wRC+", "WPA", "RE24", "wOBA"]
    available_fg = [c for c in fg_cols if c in fg_hitting.columns]
    if available_fg and not fg_hitting.empty:
        fg = fg_hitting[available_fg].copy()
        fg = fg.rename(columns={"IDfg": "player_id"})
        fg["player_id"] = fg["player_id"].astype(str)
        df = df.merge(fg, on="player_id", how="left")

    # Park-adjust wOBA using the home team column when present
    home_col = "home_team" if "home_team" in df.columns else None
    woba_col = "wOBA" if "wOBA" in df.columns else None

    if home_col and woba_col:
        df = apply_park_factor(df, team_col=home_col, metric_col=woba_col, output_col="park_adjusted_woba")
    elif woba_col:
        df["park_adjusted_woba"] = df[woba_col]
    else:
        df["park_adjusted_woba"] = float("nan")

    # Map opp_wrc_plus_7d -> opp_strength_7d for the canonical output name
    if "opp_wrc_plus_7d" in df.columns:
        df = df.rename(columns={"opp_wrc_plus_7d": "opp_strength_7d"})

    output_cols = [
        "player_id", "date",
        "wRC+", "WPA", "RE24",
        "avg_ev", "avg_la", "xwoba",
        "ev_7d", "xwoba_14d",
        "opp_strength_7d", "park_adjusted_woba",
    ]
    present = [c for c in output_cols if c in df.columns]
    result = df[present].copy()
    logger.info(f"Hitter feature table: {len(result):,} rows, cols={list(result.columns)}")
    return result


def build_pitcher_features(
    pitcher_rolling: pd.DataFrame,
    fg_pitching: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge Statcast rolling features with FanGraphs metrics for pitchers.

    Final schema:
        pitcher_id, date, avg_velocity, whiff_rate, xwoba_allowed,
        velocity_trend_7d, opponent_strength, park_adjusted_xwoba

    Parameters
    ----------
    pitcher_rolling:
        Output of add_pitcher_rolling_features() (+ opponent strength).
    fg_pitching:
        FanGraphs pitching DataFrame.

    Returns
    -------
    Gold-layer pitcher feature DataFrame.
    """
    if pitcher_rolling.empty:
        return pd.DataFrame()

    df = pitcher_rolling.rename(columns={"pitcher": "pitcher_id", "game_date": "date"})
    df["pitcher_id"] = df["pitcher_id"].astype(str)

    # Park-adjust xwoba_allowed
    home_col = "home_team" if "home_team" in df.columns else None
    if home_col and "xwoba_allowed" in df.columns:
        df = apply_park_factor(
            df, team_col=home_col, metric_col="xwoba_allowed", output_col="park_adjusted_xwoba"
        )
    elif "xwoba_allowed" in df.columns:
        df["park_adjusted_xwoba"] = df["xwoba_allowed"]
    else:
        df["park_adjusted_xwoba"] = float("nan")

    output_cols = [
        "pitcher_id", "date",
        "avg_velocity", "whiff_rate", "xwoba_allowed",
        "velocity_trend_7d", "opponent_strength",
        "park_adjusted_xwoba",
    ]
    present = [c for c in output_cols if c in df.columns]
    result = df[present].copy()
    logger.info(f"Pitcher feature table: {len(result):,} rows, cols={list(result.columns)}")
    return result


def save_gold_features(
    hitter_features: pd.DataFrame,
    pitcher_features: pd.DataFrame,
    partition_date: date,
) -> list[Path]:
    """
    Write gold-layer feature tables to Parquet partitioned by date.

    Parameters
    ----------
    hitter_features:
        Output of build_hitter_features().
    pitcher_features:
        Output of build_pitcher_features().
    partition_date:
        Date used to name the output files.

    Returns
    -------
    List of paths written.
    """
    written: list[Path] = []
    date_str = partition_date.isoformat()

    if not hitter_features.empty:
        path = PATHS.gold_features / f"hitters_{date_str}.parquet"
        save_parquet(hitter_features, path)
        written.append(path)

    if not pitcher_features.empty:
        path = PATHS.gold_features / f"pitchers_{date_str}.parquet"
        save_parquet(pitcher_features, path)
        written.append(path)

    return written
