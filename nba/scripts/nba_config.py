"""
NBA Prediction System Configuration
====================================

Central configuration for NBA prediction system.
Updated for 2025-26 season and reorganized structure.
"""

import os
from pathlib import Path

# NBA Project paths - updated for reorganized structure
NBA_ROOT = Path(__file__).parent.parent  # Go up to nba/ directory
PROJECT_ROOT = NBA_ROOT.parent  # Go up to SportsPredictor/ directory

# NBA Database path (in nba/database/)
DB_PATH = str(NBA_ROOT / "database" / "nba_predictions.db")

# Learning mode settings (Weeks 2-9)
LEARNING_MODE = True
PROBABILITY_CAP = (0.20, 0.80)  # Widened range for better differentiation
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

print(f"NBA Config loaded: DB={DB_PATH}, Learning Mode={LEARNING_MODE}, Season={SEASON}")
