"""
Rolling feature computation.

Takes a multi-day silver-layer aggregate (hitters or pitchers) and
appends rolling window features as specified in SETTINGS.rolling_windows.
All windows are computed per-player in chronological order.
"""

import pandas as pd
from loguru import logger

from config.settings import SETTINGS


def _rolling(
    df: pd.DataFrame,
    group_col: str,
    value_col: str,
    window: int,
    out_col: str,
    min_periods: int = 1,
) -> pd.Series:
    """
    Compute a rolling mean over *window* days per player group.

    Parameters
    ----------
    df:
        DataFrame sorted by (group_col, date).
    group_col:
        Player identifier column.
    value_col:
        Numeric column to roll.
    window:
        Rolling window size in days.
    out_col:
        Name for the resulting Series (for logging only).
    min_periods:
        Minimum observations required; partial windows allowed.

    Returns
    -------
    Series aligned to df's index.
    """
    return (
        df.groupby(group_col)[value_col]
        .transform(lambda s: s.rolling(window, min_periods=min_periods).mean())
        .rename(out_col)
    )


def add_hitter_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Append rolling features to a hitter silver aggregate.

    Input DataFrame must contain columns:
        batter, game_date, avg_ev, xwoba, pa

    Returns
    -------
    Copy of *df* with additional columns:
        ev_7d, xwoba_14d, pa_30d
    """
    required = {"batter", "game_date", "avg_ev", "xwoba", "pa"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"add_hitter_rolling_features: missing columns {missing}")

    result = df.copy().sort_values(["batter", "game_date"])

    windows = SETTINGS.rolling_windows
    result["ev_7d"] = _rolling(result, "batter", "avg_ev", windows["ev_7d"], "ev_7d")
    result["xwoba_14d"] = _rolling(result, "batter", "xwoba", windows["xwoba_14d"], "xwoba_14d")
    result["pa_30d"] = _rolling(result, "batter", "pa", windows["pa_30d"], "pa_30d")

    logger.info(
        f"Hitter rolling features added for {result['batter'].nunique()} players "
        f"over {result['game_date'].nunique()} days."
    )
    return result


def add_pitcher_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Append rolling features to a pitcher silver aggregate.

    Input DataFrame must contain columns:
        pitcher, game_date, avg_velocity, whiff_rate

    Returns
    -------
    Copy of *df* with additional columns:
        velocity_trend_7d, whiff_rate_7d
    """
    required = {"pitcher", "game_date", "avg_velocity"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"add_pitcher_rolling_features: missing columns {missing}")

    result = df.copy().sort_values(["pitcher", "game_date"])

    windows = SETTINGS.rolling_windows
    result["velocity_trend_7d"] = _rolling(
        result, "pitcher", "avg_velocity", windows["velocity_7d"], "velocity_trend_7d"
    )

    if "whiff_rate" in result.columns:
        result["whiff_rate_7d"] = _rolling(
            result, "pitcher", "whiff_rate", windows["whiff_7d"], "whiff_rate_7d"
        )

    logger.info(
        f"Pitcher rolling features added for {result['pitcher'].nunique()} players "
        f"over {result['game_date'].nunique()} days."
    )
    return result
