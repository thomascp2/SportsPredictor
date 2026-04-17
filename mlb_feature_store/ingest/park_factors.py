"""
Park factor mapping.

Static park factor table (2024 values) keyed by MLB team abbreviation.
Values > 1.0 favour hitters; < 1.0 favour pitchers.

Source: publicly available multi-year FanGraphs park factor averages.
"""

from dataclasses import dataclass

import pandas as pd


# Park factors (run-scoring index, 5-year average, ballpark-neutral = 1.00)
_PARK_FACTORS: dict[str, float] = {
    "ARI": 1.048,   # Chase Field — high altitude, warm
    "ATL": 1.012,   # Truist Park
    "BAL": 0.988,   # Camden Yards
    "BOS": 1.035,   # Fenway Park — short left field
    "CHC": 1.008,   # Wrigley Field
    "CHW": 0.995,   # Guaranteed Rate Field
    "CIN": 1.025,   # Great American Ballpark
    "CLE": 0.981,   # Progressive Field
    "COL": 1.158,   # Coors Field — highest park factor in MLB
    "DET": 0.976,   # Comerica Park
    "HOU": 0.975,   # Minute Maid Park
    "KCR": 0.982,   # Kauffman Stadium
    "LAA": 0.991,   # Angel Stadium
    "LAD": 0.967,   # Dodger Stadium — pitcher friendly
    "MIA": 0.961,   # loanDepot Park
    "MIL": 1.005,   # American Family Field
    "MIN": 1.006,   # Target Field
    "NYM": 0.985,   # Citi Field
    "NYY": 1.028,   # Yankee Stadium — short porch
    "OAK": 0.946,   # Oakland Coliseum — foul territory
    "PHI": 1.019,   # Citizens Bank Park
    "PIT": 0.980,   # PNC Park
    "SDP": 0.969,   # Petco Park
    "SEA": 0.962,   # T-Mobile Park
    "SFG": 0.940,   # Oracle Park — deepest park in NL
    "STL": 0.987,   # Busch Stadium
    "TBR": 0.978,   # Tropicana Field
    "TEX": 1.022,   # Globe Life Field
    "TOR": 1.003,   # Rogers Centre
    "WSN": 1.001,   # Nationals Park
}

NEUTRAL_FACTOR = 1.000


@dataclass(frozen=True)
class ParkFactors:
    """Immutable container for the park factor lookup table."""

    factors: dict[str, float]

    def get(self, team: str) -> float:
        """Return park factor for *team*, defaulting to neutral (1.00)."""
        return self.factors.get(team.upper(), NEUTRAL_FACTOR)

    def to_dataframe(self) -> pd.DataFrame:
        """Return the full mapping as a two-column DataFrame."""
        return pd.DataFrame(
            [(team, factor) for team, factor in self.factors.items()],
            columns=["team", "park_factor"],
        )


def get_park_factors() -> ParkFactors:
    """Return the singleton ParkFactors instance."""
    return ParkFactors(factors=_PARK_FACTORS)


def apply_park_factor(
    df: pd.DataFrame,
    team_col: str,
    metric_col: str,
    output_col: str,
) -> pd.DataFrame:
    """
    Multiply *metric_col* by the park factor for each row's *team_col*.

    Parameters
    ----------
    df:
        Source DataFrame — must contain *team_col* and *metric_col*.
    team_col:
        Column containing the home team abbreviation.
    metric_col:
        Numeric column to adjust (e.g. 'xwoba').
    output_col:
        Name of the new park-adjusted column.

    Returns
    -------
    Copy of *df* with *output_col* appended.
    """
    pf = get_park_factors()
    factors = df[team_col].map(pf.factors).fillna(NEUTRAL_FACTOR)
    result = df.copy()
    result[output_col] = df[metric_col] * factors
    return result
