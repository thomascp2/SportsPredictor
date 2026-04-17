import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path

# Setup paths
MLB_ROOT = Path(__file__).parent.parent
DB_PATH = MLB_ROOT / "database" / "mlb_predictions.db"

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def run_status_report():
    if not DB_PATH.exists():
        print(f"Error: MLB database not found at {DB_PATH}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    print("="*60)
    print("⚾ MLB DATA COLLECTION & PREDICTION STATUS ⚾")
    print("="*60)

    # 1. Overall Stats
    total_preds = cursor.execute("SELECT count(*) FROM predictions").fetchone()[0]
    total_graded = cursor.execute("SELECT count(*) FROM prediction_outcomes").fetchone()[0]
    total_logs = cursor.execute("SELECT count(*) FROM player_game_logs").fetchone()[0]
    unique_days = cursor.execute("SELECT count(DISTINCT game_date) FROM player_game_logs").fetchone()[0]
    
    print(f"Overall Progress:")
    print(f"  - Total Predictions: {total_preds:,}")
    print(f"  - Graded Outcomes:   {total_graded:,}")
    print(f"  - Game Logs:         {total_logs:,}")
    print(f"  - Unique Game Days:  {unique_days}")
    print("-" * 60)

    # 2. Daily Performance (Last 7 Days)
    print(f"{'Date':<12} | {'Preds':<6} | {'Graded':<6} | {'Win%':<8} | {'Logs':<6}")
    print("-" * 60)
    
    daily_stats = cursor.execute("""
        SELECT 
            p.game_date,
            count(p.id) as pred_count,
            count(o.id) as graded_count,
            SUM(CASE WHEN o.outcome = 'HIT' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN o.outcome = 'MISS' THEN 1 ELSE 0 END) as losses,
            (SELECT count(*) FROM player_game_logs l WHERE l.game_date = p.game_date) as log_count
        FROM predictions p
        LEFT JOIN prediction_outcomes o ON p.id = o.prediction_id
        GROUP BY p.game_date
        ORDER BY p.game_date DESC
        LIMIT 7
    """).fetchall()

    for row in daily_stats:
        date = row['game_date']
        preds = row['pred_count']
        graded = row['graded_count']
        logs = row['log_count']
        
        win_rate = "N/A"
        if graded > 0:
            wins = row['wins'] or 0
            losses = row['losses'] or 0
            # Exclude VOIDs from win rate calculation for clarity
            total_decisions = wins + losses
            if total_decisions > 0:
                win_rate = f"{(wins / total_decisions * 100):.1f}%"
        
        print(f"{date:<12} | {preds:<6} | {graded:<6} | {win_rate:<8} | {logs:<6}")

    # 3. Prop Performance (Top 5 Props)
    print("-" * 60)
    print("Top 5 Prop Performance (All-Time):")
    print(f"{'Prop Type':<18} | {'Graded':<6} | {'Win%':<8}")
    
    prop_stats = cursor.execute("""
        SELECT 
            prop_type,
            count(*) as graded_count,
            SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'MISS' THEN 1 ELSE 0 END) as losses
        FROM prediction_outcomes
        GROUP BY prop_type
        HAVING graded_count > 50
        ORDER BY (CAST(SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) AS FLOAT) / 
                 NULLIF(SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) + 
                        SUM(CASE WHEN outcome = 'MISS' THEN 1 ELSE 0 END), 0)) DESC
        LIMIT 5
    """).fetchall()

    for row in prop_stats:
        prop = row['prop_type']
        graded = row['graded_count']
        wins = row['wins'] or 0
        losses = row['losses'] or 0
        total_decisions = wins + losses
        win_rate = f"{(wins / total_decisions * 100):.1f}%" if total_decisions > 0 else "0.0%"
        print(f"{prop:<18} | {graded:<6} | {win_rate:<8}")

    conn.close()
    print("="*60)

if __name__ == "__main__":
    run_status_report()
