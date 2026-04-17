"""
Central configuration for the MLB feature store pipeline.
All paths, constants, and toggles live here.
"""

from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Paths(BaseModel):
    """Resolved directory paths for the data lake layers."""

    base: Path = Path(__file__).resolve().parents[1] / "data"
    raw_statcast: Path = Field(default=None)
    raw_fangraphs: Path = Field(default=None)
    raw_schedule: Path = Field(default=None)
    silver_hitters: Path = Field(default=None)
    silver_pitchers: Path = Field(default=None)
    gold_features: Path = Field(default=None)
    duckdb: Path = Field(default=None)

    def model_post_init(self, __context) -> None:
        self.raw_statcast = self.base / "raw" / "statcast"
        self.raw_fangraphs = self.base / "raw" / "fangraphs"
        self.raw_schedule = self.base / "raw" / "schedule"
        self.silver_hitters = self.base / "silver" / "hitters"
        self.silver_pitchers = self.base / "silver" / "pitchers"
        self.gold_features = self.base / "gold" / "features"
        self.duckdb = self.base / "mlb.duckdb"

    def ensure_all(self) -> None:
        """Create all directories if they do not exist."""
        for field_name, value in self.__dict__.items():
            if isinstance(value, Path) and field_name != "duckdb":
                value.mkdir(parents=True, exist_ok=True)


class PipelineSettings(BaseSettings):
    """Runtime settings — can be overridden via environment variables (MLB_ prefix)."""

    model_config = {"env_prefix": "MLB_", "extra": "ignore"}

    statcast_columns: list[str] = [
        "launch_speed",
        "launch_angle",
        "estimated_woba_using_speedangle",
        "events",
        "batter",
        "pitcher",       # needed for pitcher label derivation
        "game_date",
        "home_team",
        "away_team",
    ]

    pitching_columns: list[str] = [
        "pitcher",
        "release_speed",
        "pfx_x",
        "pfx_z",
        "estimated_woba_using_speedangle",
        "game_date",
        "home_team",
        "away_team",
    ]

    fangraphs_hitting_stats: list[str] = [
        "wRC+",
        "WAR",
        "BABIP",
        "wOBA",
        "ISO",
        "K%",
        "BB%",
        "RE24",
        "WPA",
    ]

    rolling_windows: dict[str, int] = {
        "ev_7d": 7,
        "xwoba_14d": 14,
        "pa_30d": 30,
        "velocity_7d": 7,
        "whiff_7d": 7,
    }

    hard_hit_ev_threshold: float = 95.0  # mph — proxy for hard hit rate

    fangraphs_base_url: str = "https://www.fangraphs.com/api/leaders/major-league/data"
    fangraphs_page_size: int = 2_000_000


PATHS = Paths()
SETTINGS = PipelineSettings()
