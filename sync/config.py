"""
Sync Configuration
==================
Supabase connection settings and sync parameters.

Set environment variables:
  SUPABASE_URL=https://your-project.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=eyJ...
"""

import os

# Supabase connection
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

# Sync settings
SYNC_BATCH_SIZE = 100          # Rows per upsert batch
GAME_POLL_INTERVAL_SEC = 60    # Live score polling interval
GAME_HOURS_START = 11          # Start polling at 11am ET
GAME_HOURS_END = 2             # Stop polling at 2am ET (next day)

# Database paths (match orchestrator)
NHL_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'nhl', 'database', 'nhl_predictions_v2.db')
NBA_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'nba', 'database', 'nba_predictions.db')

# Tier mapping
TIER_ORDER = ['T1-ELITE', 'T2-STRONG', 'T3-GOOD', 'T4-LEAN', 'T5-FADE']
