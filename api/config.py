"""
API Configuration
=================
Database paths, CORS settings, and constants.
"""

from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Database paths
DB_PATHS = {
    'nba': PROJECT_ROOT / 'nba' / 'database' / 'nba_predictions.db',
    'nhl': PROJECT_ROOT / 'nhl' / 'database' / 'nhl_predictions_v2.db',
    'prizepicks': PROJECT_ROOT / 'shared' / 'prizepicks_lines.db',
}

# CORS settings - allow Expo development
CORS_ORIGINS = [
    "http://localhost:19006",      # Expo web
    "http://localhost:8081",       # Metro bundler
    "http://localhost:3000",       # React dev
    "http://127.0.0.1:19006",
    "http://127.0.0.1:8081",
    "exp://192.168.*.*:*",         # Expo Go on local network
    "*",                           # Allow all for development
]

# Parlay payout structure
PAYOUTS = {
    2: 3.0,
    3: 5.0,
    4: 10.0,
    5: 20.0,
    6: 25.0,
}

# Leg values by odds type
LEG_VALUES = {
    'goblin': 0.5,
    'standard': 1.0,
    'demon': 1.5,
}

# Break-even rates by odds type — exact fractions, single source of truth for the API.
# Import these everywhere instead of hardcoding. Must stay in sync with
# gsd_module/shared/odds.py BREAK_EVEN_MAP and smart_pick_selector.py.
# standard: 110/210 = 0.52381 (NOT 0.56 — that was a pre-Mar-8-2026 bug; overstated edge by 3.6pp)
# goblin:   320/420 = 0.76190 (NOT 0.76)
# demon:    100/220 = 0.45455 (NOT 0.45)
BREAK_EVEN_RATES = {
    'standard': 110 / 210,  # 0.52381
    'goblin':   320 / 420,  # 0.76190
    'demon':    100 / 220,  # 0.45455
}

# API settings
API_VERSION = "v1"
API_TITLE = "SportsPredictor API"
API_DESCRIPTION = "Sports prediction data for NBA and NHL"

# Cache settings (in seconds)
CACHE_TTL = {
    'picks': 300,      # 5 minutes - picks don't change often
    'scores': 30,      # 30 seconds - live scores need to be fresh
    'schedule': 3600,  # 1 hour - game schedule rarely changes
    'performance': 600, # 10 minutes - stats update slowly
}
