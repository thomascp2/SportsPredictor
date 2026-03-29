"""
PGA Tour Traditional Stats Scraper
====================================

Fetches traditional PGA Tour statistics as Strokes Gained proxies.
These stats are available from the PGA Tour's unofficial JSON API
without requiring authentication.

Stats collected (and their SG equivalents):
  driving_distance  → proxy for SG:Off the Tee (distance component)
  driving_accuracy  → proxy for SG:Off the Tee (accuracy component)
  gir_pct           → proxy for SG:Approach the Green
  scrambling_pct    → proxy for SG:Around the Green
  putting_avg       → proxy for SG:Putting
  birdie_avg        → composite form signal

Correlation with true SG categories:
  driving_distance + accuracy → SG:OTT  ~0.75
  gir_pct                     → SG:APP  ~0.80
  scrambling_pct              → SG:ARG  ~0.72
  putting_avg                 → SG:PUTT ~0.78

This is not as precise as DataGolf's SG data, but provides a meaningful
foundation for ML modeling until a paid SG API is added.

Upgrade path:
  When adding DataGolf, replace calls to PGAStatsScraper with DataGolfApi
  and update feature names accordingly (f_sg_* prefix).

Usage:
    from pga_stats_scraper import PGAStatsScraper
    scraper = PGAStatsScraper()
    stats = scraper.get_player_season_stats(season=2024)
    player_stats = scraper.get_stats_for_player("Scottie Scheffler", season=2024)
"""

import requests
import time
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)


# Mapping from PGA Tour stat IDs to our internal names
# These IDs come from the unofficial PGA Tour stats API
PGA_STAT_IDS = {
    "driving_distance": "101",    # Driving Distance
    "driving_accuracy": "102",    # Driving Accuracy Percentage
    "gir_pct":          "103",    # Greens in Regulation Percentage
    "scrambling_pct":   "130",    # Scrambling
    "putting_avg":      "119",    # Putts Per Round (closer to SG:Putting than avg putts)
    "birdie_avg":       "156",    # Birdie Average
    "scoring_avg":      "120",    # Scoring Average (adjusted)
    "sg_total":         "02675",  # SG: Total (available 2016+, not all players)
    "sg_ott":           "02567",  # SG: Off the Tee
    "sg_approach":      "02568",  # SG: Approach the Green
    "sg_arg":           "02569",  # SG: Around the Green
    "sg_putting":       "02564",  # SG: Putting
}

# Preferred stats in priority order (use SG if available, fall back to proxy)
PREFERRED_STATS = [
    "sg_total", "sg_ott", "sg_approach", "sg_arg", "sg_putting",  # True SG (if available)
    "driving_distance", "driving_accuracy", "gir_pct",            # Traditional proxies
    "scrambling_pct", "putting_avg", "birdie_avg", "scoring_avg",
]


class PGAStatsScraper:
    """
    Scrapes PGA Tour seasonal statistics for use as SG proxies.
    Uses the PGA Tour's unofficial stats JSON feed.
    """

    BASE_URL = "https://www.pgatour.com/stats/stat"
    TIMEOUT = 30
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 2

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; SportsPredictor/1.0)",
            "Referer": "https://www.pgatour.com/",
        })
        self._cache = {}  # season -> stat_name -> {player_name: value}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_player_season_stats(self, season: int):
        """
        Fetch all available stats for all players in a given PGA Tour season.

        Args:
            season: PGA Tour season year (e.g., 2024)

        Returns:
            dict: {player_name: {stat_name: value, ...}, ...}
        """
        if season in self._cache:
            return self._cache[season]

        all_player_stats = {}
        for stat_name in PREFERRED_STATS:
            stat_id = PGA_STAT_IDS.get(stat_name)
            if not stat_id:
                continue
            stat_data = self._fetch_stat(stat_id, season)
            for player_name, value in stat_data.items():
                if player_name not in all_player_stats:
                    all_player_stats[player_name] = {}
                all_player_stats[player_name][stat_name] = value

        self._cache[season] = all_player_stats
        return all_player_stats

    def get_stats_for_player(self, player_name: str, season: int):
        """
        Get all seasonal stats for a specific player.

        Args:
            player_name: Full name as returned by ESPN API (e.g., "Scottie Scheffler")
            season: PGA Tour season year

        Returns:
            dict: {stat_name: float, ...} — empty dict if player not found
        """
        all_stats = self.get_player_season_stats(season)
        # Try exact match first
        if player_name in all_stats:
            return all_stats[player_name]
        # Try case-insensitive match
        lower_name = player_name.lower()
        for name, stats in all_stats.items():
            if name.lower() == lower_name:
                return stats
        # Try last-name match as fallback
        last_name = player_name.split()[-1].lower()
        candidates = [
            (name, stats) for name, stats in all_stats.items()
            if name.lower().split()[-1] == last_name
        ]
        if len(candidates) == 1:
            return candidates[0][1]
        return {}

    def get_stat_for_all_players(self, stat_name: str, season: int):
        """
        Get a single stat for all players in a season.

        Returns:
            dict: {player_name: float}
        """
        stat_id = PGA_STAT_IDS.get(stat_name)
        if not stat_id:
            logger.warning(f"Unknown stat name: {stat_name}")
            return {}
        return self._fetch_stat(stat_id, season)

    def get_available_stats(self):
        """Return list of stat names we can fetch."""
        return list(PGA_STAT_IDS.keys())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_stat(self, stat_id: str, season: int):
        """
        Fetch a single stat category from PGA Tour JSON feed.

        PGA Tour URL pattern:
        https://www.pgatour.com/stats/stat.{stat_id}.y{season}.html

        The underlying JSON endpoint is at a slightly different path;
        we attempt the JSON feed and fall back to an alternative format.

        Returns:
            dict: {player_name: float}
        """
        # Try the JSON stats API endpoint
        url = f"https://www.pgatour.com/content/dam/stats/json/{season}/{stat_id}.json"
        data = self._get_json(url)
        if data:
            return self._parse_stat_json(data)

        # Fallback: try the stats feed with different path structure
        url2 = f"https://www.pgatour.com/stats/stat/{stat_id}/y{season}.json"
        data2 = self._get_json(url2)
        if data2:
            return self._parse_stat_json(data2)

        logger.debug(f"No data for stat_id={stat_id}, season={season}")
        return {}

    def _parse_stat_json(self, data: dict):
        """
        Parse PGA Tour stats JSON into {player_name: float} dict.
        The JSON structure varies; handle multiple known formats.
        """
        result = {}

        # Format 1: tourAvgStats / plrsStats array
        plrs = (
            data.get("plrs") or
            data.get("plrsStats") or
            data.get("tourStatsData", {}).get("plrs") or
            []
        )
        if plrs:
            for plr in plrs:
                name = (
                    plr.get("plrName") or
                    plr.get("playerName") or
                    self._build_name(plr.get("firstName", ""), plr.get("lastName", ""))
                )
                if not name:
                    continue
                value = plr.get("avg") or plr.get("statValue") or plr.get("value")
                try:
                    result[name.strip()] = float(value)
                except (ValueError, TypeError):
                    pass
            return result

        # Format 2: rows array (older format)
        rows = data.get("rows") or data.get("data", {}).get("rows") or []
        for row in rows:
            name = row.get("playerName") or self._build_name(
                row.get("firstName", ""), row.get("lastName", "")
            )
            if not name:
                continue
            value = row.get("avg") or row.get("value") or row.get("statValue")
            try:
                result[name.strip()] = float(value)
            except (ValueError, TypeError):
                pass

        return result

    @staticmethod
    def _build_name(first: str, last: str):
        """Build full name from first and last."""
        first = (first or "").strip()
        last = (last or "").strip()
        if first and last:
            return f"{first} {last}"
        return first or last or ""

    def _get_json(self, url: str):
        """GET JSON with retry. Returns parsed dict or None."""
        for attempt in range(self.RETRY_ATTEMPTS):
            try:
                resp = self.session.get(url, timeout=self.TIMEOUT)
                if resp.status_code == 404:
                    return None  # Stat/season doesn't exist — don't retry
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as e:
                logger.debug(f"PGA stats HTTP error {url} (attempt {attempt+1}): {e}")
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logger.debug(f"PGA stats error {url} (attempt {attempt+1}): {e}")
            if attempt < self.RETRY_ATTEMPTS - 1:
                time.sleep(self.RETRY_DELAY)
        return None


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scraper = PGAStatsScraper()

    print("Fetching 2024 season stats...")
    stats = scraper.get_player_season_stats(2024)
    print(f"  Players with stats: {len(stats)}")

    top_players = ["Scottie Scheffler", "Rory McIlroy", "Xander Schauffele", "Collin Morikawa"]
    for player in top_players:
        p_stats = scraper.get_stats_for_player(player, 2024)
        if p_stats:
            print(f"\n  {player}:")
            for stat, val in p_stats.items():
                print(f"    {stat}: {val:.3f}")
        else:
            print(f"\n  {player}: no stats found")
