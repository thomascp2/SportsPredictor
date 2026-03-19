"""
One-time sync: push corrected threes actual_value + outcome to Supabase.
Run after fix_threes_outcomes.py (or the direct SQL fix) to propagate corrections.
"""

import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'sync'))

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'nba_predictions.db')

def main():
    # Load Supabase client
    from supabase_sync import SupabaseSync
    syncer = SupabaseSync()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get all corrected threes rows (actual_value now set from player_game_logs)
    rows = conn.execute('''
        SELECT player_name, prop_type, line, actual_value, outcome, prediction, game_date
        FROM prediction_outcomes
        WHERE prop_type = 'threes'
          AND game_date >= '2025-11-10'
        ORDER BY game_date
    ''').fetchall()
    conn.close()

    print(f"[SYNC] Pushing {len(rows)} corrected threes rows to Supabase...")

    synced = 0
    errors = 0
    for row in rows:
        row_dict = dict(row)
        try:
            syncer.client.table('daily_props').update({
                'actual_value': row_dict['actual_value'],
                'result': row_dict['outcome'],
                'status': 'graded',
                'graded_at': datetime.now().isoformat(),
            }).eq('game_date', row_dict['game_date']).eq(
                'player_name', syncer._normalize_name(row_dict['player_name'])
            ).eq('prop_type', row_dict['prop_type']).eq(
                'line', row_dict['line']
            ).execute()
            synced += 1
            if synced % 100 == 0:
                print(f"  {synced}/{len(rows)} synced...")
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [ERR] {row_dict['player_name']} {row_dict['game_date']}: {e}")

    print(f"[SYNC] Done: {synced} synced, {errors} errors")

if __name__ == '__main__':
    main()
