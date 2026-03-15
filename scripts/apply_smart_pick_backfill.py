#!/usr/bin/env python3
"""
Run this ONCE after applying supabase/migrations/002_add_is_smart_pick.sql
to mark today's smart picks and verify the column is working.

Usage:
    python scripts/apply_smart_pick_backfill.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sync.supabase_sync import SupabaseSync

sb = SupabaseSync()

# Verify column exists
try:
    r = sb.client.table('daily_props').select('is_smart_pick').limit(1).execute()
    print('[OK] is_smart_pick column exists')
except Exception as e:
    print('[ERROR] Column missing. Apply supabase/migrations/002_add_is_smart_pick.sql first.')
    print(f'  Error: {e}')
    sys.exit(1)

# Re-run today's pp-sync for both sports so is_smart_pick gets set properly
from datetime import date
today = date.today().isoformat()
print(f'\nRe-syncing smart picks for {today} to set is_smart_pick=True ...')

for sport in ['nhl', 'nba']:
    try:
        result = sb.sync_smart_picks(sport, game_date=today)
        print(f'  [{sport.upper()}] Smart picks synced: {result.get("synced", 0)}')
    except Exception as e:
        print(f'  [{sport.upper()}] Error: {e}')

print('\nDone. Restart the dashboard to see correct tier stats.')
