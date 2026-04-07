"""
Sync Configuration
==================
Supabase connection settings and sync parameters.

Set environment variables:
  SUPABASE_URL=https://your-project.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=eyJ...
"""

import os
from pathlib import Path

# Auto-load .env from project root if present
_env_path = Path(__file__).parent.parent / '.env'
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, value = line.partition('=')
            os.environ.setdefault(key.strip(), value.strip())

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
MLB_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mlb', 'database', 'mlb_predictions.db')
GOLF_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'golf', 'database', 'golf_predictions.db')

# Tier mapping
TIER_ORDER = ['T1-ELITE', 'T2-STRONG', 'T3-GOOD', 'T4-LEAN', 'T5-FADE']
