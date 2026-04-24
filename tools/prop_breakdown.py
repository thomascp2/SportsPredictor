import sqlite3

BE = {'standard': 52.38, 'goblin': 76.19, 'demon': 45.45}

for sport, db in [
    ('NBA', 'nba/database/nba_predictions.db'),
    ('NHL', 'nhl/database/nhl_predictions_v2.db'),
    ('MLB', 'mlb/database/mlb_predictions.db'),
]:
    conn = sqlite3.connect(db)
    c = conn.cursor()
    print(f'\n=== {sport} Smart Picks (post-full-cleanup) ===')
    c.execute('''
        SELECT prop_type, LOWER(COALESCE(odds_type,'standard')), prediction,
               COUNT(*), SUM(outcome='HIT'),
               ROUND(100.0*SUM(outcome='HIT')/COUNT(*),1)
        FROM prediction_outcomes
        WHERE is_smart_pick=1 AND outcome IN ('HIT','MISS')
          AND data_quality_flag IS NULL
        GROUP BY prop_type, odds_type, prediction
        HAVING COUNT(*) >= 20
        ORDER BY prop_type, odds_type, prediction
    ''')
    for r in c.fetchall():
        be = BE.get(r[1], 52.38)
        edge = r[5] - be
        flag = ' <-- LOSING' if edge < 0 else ''
        print(f'  {r[0]:<22} {r[1]:<10} {r[2]:<6} {r[3]:>5} {r[4]:>5} {r[5]:>5.1f}%  {edge:+.1f}%{flag}')
    conn.close()
