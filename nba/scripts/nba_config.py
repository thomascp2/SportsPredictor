"""
NBA Prediction System Configuration
====================================

Central configuration for NBA prediction system.
Updated for 2025-26 season and reorganized structure.
"""

import os
import json
from pathlib import Path
from datetime import datetime

# NBA Project paths - updated for reorganized structure
NBA_ROOT = Path(__file__).parent.parent  # Go up to nba/ directory
PROJECT_ROOT = NBA_ROOT.parent  # Go up to SportsPredictor/ directory

# NBA Database path (in nba/database/)
DB_PATH = str(NBA_ROOT / "database" / "nba_predictions.db")

# Learning mode settings
# REVERTED TO STATISTICAL MODE (2026-04-05): NBA ML retrain (Mar 15) trained on concept-drifted
# data — UNDER hit rate collapsed from 83% to 47% post-retrain. Statistical model (rolling
# success-rate features) naturally tracks real-world hit rates and was profitable pre-ML.
# Re-enable LEARNING_MODE = False only after clean retrain with filtered training data.
LEARNING_MODE = True
PROBABILITY_CAP = (0.20, 0.80)  # Statistical mode cap: normal dist can hit 99% on easy lines
MODEL_TYPE = "statistical_only"  # No ML until Week 8+

# Date/time settings (EST/CST)
TIMEZONE = "America/Chicago"
PREDICT_TODAY_START_HOUR = 6   # 6 AM
PREDICT_TOMORROW_START_HOUR = 20  # 8 PM

# Discord webhook (set in environment variable)
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

# Data collection phase
SEASON = "2025-26"  # UPDATED FOR 2025-26 SEASON
DATA_COLLECTION_START = "2025-10-22"  # NBA season start
DATA_COLLECTION_END = "2026-01-05"    # Week 8+

# NBA-specific settings
MIN_GAMES_REQUIRED = 5  # Player history threshold
MIN_MINUTES_PER_GAME = 15.0  # Filter bench players (for exploitation phase)

# Player classification (for exploration phase)
STARTERS_COUNT = 5  # Typical NBA starters
SIGNIFICANT_BENCH_COUNT = 3  # Significant bench players (6th-8th man)
EXPLORATION_PLAYERS_PER_TEAM = STARTERS_COUNT + SIGNIFICANT_BENCH_COUNT  # 8 players

# Prop bet targets (10 core features)
CORE_PROPS = {
    # Binary (Over/Under)
    'points': [15.5, 20.5, 25.5],           # Points O15.5, O20.5, O25.5
    'rebounds': [7.5, 10.5],                # Rebounds O7.5, O10.5
    'assists': [5.5, 7.5],                  # Assists O5.5, O7.5
    'threes': [2.5],                        # 3PM O2.5
    'stocks': [2.5],                        # Stocks (STL+BLK) O2.5

    # Continuous (for regression)
    'pra': [30.5, 35.5, 40.5],             # Points + Rebounds + Assists
    'minutes': [28.5, 32.5],                # Minutes O28.5, O32.5
}

# Blowout filter — skip all player props when the spread is this large.
# Games with a spread >= 13.5 pts frequently feature garbage-time minutes
# that invalidate almost every individual stat prop.
BLOWOUT_SPREAD_THRESHOLD = 13.5

# Feature importance thresholds
MIN_FEATURE_IMPORTANCE = 0.01  # Drop features below this in ML training

# API endpoints
NBA_STATS_API = "https://stats.nba.com/stats"
COVERS_NBA_URL = "https://www.covers.com/sport/basketball/nba"

# Request headers (NBA Stats API requires user agent)
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nba.com/',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
}

# ============================================================================
# NBA SCHEDULE CACHE (for game-day awareness)
# ============================================================================

NBA_SCHEDULE_CDN_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
NBA_DATA_DIR = NBA_ROOT / "data"
NBA_SCHEDULE_CACHE_PATH = NBA_DATA_DIR / "nba_schedule_cache.json"
SCHEDULE_CACHE_MAX_AGE_DAYS = 7


def nba_has_games(target_date: str, force_refresh: bool = False) -> tuple:
    """
    Check if there are NBA games (regular season or Play-In) on a given date.

    Uses a locally cached copy of the full NBA season schedule from the
    NBA CDN. The cache refreshes every 7 days (or on force_refresh).

    Fail-open: if the CDN is unreachable and no cache exists, assumes
    games exist (preserves old behavior).

    Args:
        target_date: Date string in YYYY-MM-DD format
        force_refresh: Force re-download of schedule from CDN

    Returns:
        Tuple of (has_games: bool, game_count: int)
    """
    schedule = _load_schedule_cache(force_refresh)
    if schedule is None:
        # Fail-open: assume games exist
        print(f"[SCHEDULE] No cache available, assuming games exist for {target_date}")
        return (True, -1)

    game_count = schedule.get(target_date, 0)
    return (game_count > 0, game_count)


def _load_schedule_cache(force_refresh: bool = False) -> dict | None:
    """
    Load the schedule cache, refreshing from CDN if stale or missing.

    Returns:
        Dict mapping date strings to regular-season game counts, or None on failure.
    """
    # Ensure data directory exists
    NBA_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Check if cache exists and is fresh
    if not force_refresh and NBA_SCHEDULE_CACHE_PATH.exists():
        try:
            with open(NBA_SCHEDULE_CACHE_PATH, 'r') as f:
                cache = json.load(f)
            fetched_at = datetime.fromisoformat(cache['fetched_at'])
            age_days = (datetime.now() - fetched_at).days
            if age_days < SCHEDULE_CACHE_MAX_AGE_DAYS:
                return cache.get('schedule', {})
            else:
                print(f"[SCHEDULE] Cache is {age_days} days old, refreshing...")
        except (json.JSONDecodeError, KeyError, ValueError):
            print("[SCHEDULE] Cache file corrupt, refreshing...")

    # Fetch from CDN
    return _fetch_and_cache_schedule()


def _fetch_and_cache_schedule() -> dict | None:
    """
    Fetch full season schedule from NBA CDN and cache locally.

    Returns:
        Dict mapping date strings to regular-season game counts, or None on failure.
    """
    try:
        import requests
    except ImportError:
        print("[SCHEDULE] requests library not available")
        # Try to fall back to stale cache
        return _read_stale_cache()

    try:
        print(f"[SCHEDULE] Fetching NBA schedule from CDN...")
        resp = requests.get(NBA_SCHEDULE_CDN_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[SCHEDULE] CDN fetch failed: {e}")
        return _read_stale_cache()

    # Parse: count regular-season games per date
    # Regular season game IDs start with '002', All-Star/special start with '003'
    schedule = {}
    try:
        game_dates = data['leagueSchedule']['gameDates']
        for gd in game_dates:
            date_str = gd['gameDate'][:10]  # "MM/DD/YYYY HH:MM:SS" or ISO format
            # Normalize date to YYYY-MM-DD
            date_str = _normalize_date(date_str)
            if not date_str:
                continue

            reg_season_count = 0
            for game in gd.get('games', []):
                game_id = str(game.get('gameId', ''))
                # Regular season: '002', Play-In: '005', Playoffs: '004'
                if game_id.startswith('002') or game_id.startswith('004') or game_id.startswith('005'):
                    reg_season_count += 1

            if reg_season_count > 0:
                schedule[date_str] = reg_season_count
    except (KeyError, TypeError) as e:
        print(f"[SCHEDULE] Error parsing CDN data: {e}")
        return _read_stale_cache()

    # Save cache
    cache = {
        'fetched_at': datetime.now().isoformat(),
        'season': SEASON,
        'schedule': schedule,
    }
    try:
        with open(NBA_SCHEDULE_CACHE_PATH, 'w') as f:
            json.dump(cache, f, indent=2)
        print(f"[SCHEDULE] Cached {len(schedule)} game dates")
    except Exception as e:
        print(f"[SCHEDULE] Failed to write cache: {e}")

    return schedule


def _normalize_date(date_str: str) -> str | None:
    """Normalize a date string to YYYY-MM-DD format."""
    # Try ISO format first (YYYY-MM-DD...)
    if len(date_str) >= 10 and date_str[4] == '-':
        return date_str[:10]
    # Try MM/DD/YYYY format
    for fmt in ('%m/%d/%Y', '%m/%d/%Y %H:%M:%S'):
        try:
            return datetime.strptime(date_str, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def _read_stale_cache() -> dict | None:
    """Read stale cache as fallback when CDN is unreachable."""
    if NBA_SCHEDULE_CACHE_PATH.exists():
        try:
            with open(NBA_SCHEDULE_CACHE_PATH, 'r') as f:
                cache = json.load(f)
            print("[SCHEDULE] Using stale cache as fallback")
            return cache.get('schedule', {})
        except (json.JSONDecodeError, KeyError):
            pass
    return None


print(f"NBA Config loaded: DB={DB_PATH}, Learning Mode={LEARNING_MODE}, Season={SEASON}")
