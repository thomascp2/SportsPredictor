"""
data_orchestrator/config.py

Central configuration for the Data Orchestrator Layer.
All other modules import from here — never hardcode paths or keys elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)   # .env wins over stale shell variables

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR     = _ROOT / "data_orchestrator" / "data"
DB_PATH      = DATA_DIR / "orchestrator.db"
CACHE_DIR    = DATA_DIR / "cache"
LOG_DIR      = DATA_DIR / "logs"

# Create on import
for _d in (DATA_DIR, CACHE_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

# ---------------------------------------------------------------------------
# The Odds API
# ---------------------------------------------------------------------------

ODDS_API_BASE   = "https://api.the-odds-api.com/v4"
ODDS_API_BUDGET = 500          # conservative daily cap (API limit is 600)
ODDS_REGIONS    = "us"
ODDS_FORMAT     = "american"

# Sport key → (api_sport_key, prop_market, display_name)
SPORT_CONFIGS: dict[str, dict] = {
    "NBA": {
        "sport_key": "basketball_nba",
        "market":    "player_points",
        "prop_label": "points",
    },
    "NHL": {
        "sport_key": "icehockey_nhl",
        "market":    "player_shots_on_goal",
        "prop_label": "shots_on_goal",
    },
    "MLB": {
        "sport_key": "baseball_mlb",
        "market":    "batter_total_bases",
        "prop_label": "total_bases",
    },
}

# ---------------------------------------------------------------------------
# NHL API
# ---------------------------------------------------------------------------

NHL_API_BASE    = "https://api-web.nhle.com/v1"
NHL_SEASON      = "20252026"    # update each season

# Active team abbreviations (30 + SEA + VGK)
NHL_TEAMS = [
    "ANA","BOS","BUF","CGY","CAR","CHI","COL","CBJ","DAL","DET",
    "EDM","FLA","LAK","MIN","MTL","NSH","NJD","NYI","NYR","OTT",
    "PHI","PIT","SJS","SEA","STL","TBL","TOR","UTA","VAN","VGK",
    "WSH","WPG",
]

# ---------------------------------------------------------------------------
# NBA API
# ---------------------------------------------------------------------------

NBA_API_TIMEOUT = 30    # seconds — nba_api frequently needs extra time
NBA_API_DELAY   = 0.8   # seconds between requests to avoid 429s

# ---------------------------------------------------------------------------
# Scheduler times (24h, CST = UTC-5)
# ---------------------------------------------------------------------------

# Stats scrape: 3:00 AM CST = 8:00 AM UTC
STATS_HOUR_UTC   = 8
STATS_MINUTE_UTC = 0

# Odds pulls: 9 AM / 3 PM / 6 PM CST → 14:00 / 20:00 / 23:00 UTC
ODDS_PULL_TIMES_UTC = [
    (14, 0),
    (20, 0),
    (23, 0),
]

# ---------------------------------------------------------------------------
# Fuzzy matching threshold (0–100)
# ---------------------------------------------------------------------------

NAME_MATCH_THRESHOLD = 88   # below this → no match, log a warning
