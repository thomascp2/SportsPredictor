"""
V2 Configuration Module
=======================

Central configuration for V2 rebuild system.
All scripts should import from here for consistency.
"""

import os
from pathlib import Path

# V2 Project root - updated for reorganized structure
V2_ROOT = Path(__file__).parent.parent  # Go up to nhl/ directory

# V2 Database path
DB_PATH = str(V2_ROOT / "database" / "nhl_predictions_v2.db")

# Learning mode settings (Weeks 2-9)
LEARNING_MODE = False
PROBABILITY_CAP = (0.0, 1.0)  # No cap — ML models provide calibrated probabilities
MODEL_TYPE = "statistical_only"  # No ML until Week 10

# Date/time settings (CST)
TIMEZONE = "America/Chicago"
PREDICT_TODAY_START_HOUR = 6   # 6 AM CST
PREDICT_TOMORROW_START_HOUR = 20  # 8 PM CST

# Discord webhook (set in environment variable)
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

# Data collection phase
DATA_COLLECTION_START = "2025-11-05"
DATA_COLLECTION_END = "2026-01-05"

# Feature importance thresholds
MIN_FEATURE_IMPORTANCE = 0.01  # Drop features below this in ML training

print(f"V2 Config loaded: DB={DB_PATH}, Learning Mode={LEARNING_MODE}")
