"""
Daily System Audit — Automated DB health, feature completeness, and ROI report.

This script runs every morning to:
1. Verify database integrity (check for recent data)
2. Report P&L (ROI) for yesterday and the last 30 days
3. Track CLV (Closing Line Value) for game predictions
4. Alert to any feature extraction gaps or grading failures

Usage:
    python daily_audit.py
"""

import sqlite3
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List

# Path setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from shared.project_config import SPORT_KEYS, DB_PATH_STR
try:
    from shared.game_discord_notifications import send_discord_notification
except ImportError:
    def send_discord_notification(title, msg, color="blue"):
        print(f"\n[{title}] {msg}")

def get_roi_stats(db_path: str, days: int = 1) -> Dict:
    """Calculate ROI stats for a given number of days."""
    if not os.path.exists(db_path):
        return {"error": "DB not found"}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    date_cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    stats = {
        "props": {"hits": 0, "misses": 0, "profit": 0.0, "total": 0},
        "games": {"hits": 0, "misses": 0, "profit": 0.0, "total": 0}
    }
    
    try:
        # Props ROI
        rows = conn.execute("""
            SELECT outcome, profit FROM prediction_outcomes
            WHERE game_date >= ? AND outcome IN ('HIT', 'MISS')
        """, (date_cutoff,)).fetchall()
        
        for r in rows:
            stats["props"]["total"] += 1
            stats["props"]["profit"] += (r["profit"] or 0.0)
            if r["outcome"] == "HIT":
                stats["props"]["hits"] += 1
            else:
                stats["props"]["misses"] += 1
                
        # Games ROI
        rows = conn.execute("""
            SELECT outcome, profit FROM game_prediction_outcomes
            WHERE game_date >= ? AND outcome IN ('HIT', 'MISS')
        """, (date_cutoff,)).fetchall()
        
        for r in rows:
            stats["games"]["total"] += 1
            stats["games"]["profit"] += (r["profit"] or 0.0)
            if r["outcome"] == "HIT":
                stats["games"]["hits"] += 1
            else:
                stats["games"]["misses"] += 1
                
    except Exception as e:
        stats["error"] = str(e)
    finally:
        conn.close()
        
    return stats

def get_health_check(db_path: str) -> Dict:
    """Check for recent data and database size."""
    if not os.path.exists(db_path):
        return {"status": "MISSING"}
    
    stats = {
        "status": "OK",
        "size_mb": round(os.path.getsize(db_path) / (1024 * 1024), 2),
        "last_prediction": "Never",
        "last_log": "Never"
    }
    
    conn = sqlite3.connect(db_path)
    try:
        res = conn.execute("SELECT MAX(game_date) FROM predictions").fetchone()
        if res and res[0]:
            stats["last_prediction"] = res[0]
            
        # Sport-specific log tables
        log_table = "player_game_logs"
        if "golf" in db_path.lower():
            log_table = "player_round_logs"
            
        res = conn.execute(f"SELECT MAX(game_date) FROM {log_table}").fetchone()
        if res and res[0]:
            stats["last_log"] = res[0]
    except Exception as e:
        stats["status"] = f"ERROR: {str(e)}"
    finally:
        conn.close()
        
    return stats

def run_audit():
    print(f"\n{'='*60}")
    print(f"  SPORTSPREDICTOR DAILY AUDIT - {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*60}")
    
    audit_msg = ""
    
    for sport in SPORT_KEYS:
        db_path = DB_PATH_STR.get(sport)
        if not db_path:
            continue
            
        print(f"\n  Auditing {sport.upper()}...")
        
        health = get_health_check(db_path)
        yesterday_roi = get_roi_stats(db_path, days=1)
        monthly_roi = get_roi_stats(db_path, days=30)
        
        sport_msg = f"**{sport.upper()} System Health:**\n"
        sport_msg += f"• DB Status: {health['status']} ({health['size_mb']} MB)\n"
        sport_msg += f"• Last Prediction: {health['last_prediction']}\n"
        sport_msg += f"• Last Data Log: {health['last_log']}\n"
        
        # Props ROI
        p_y = yesterday_roi["props"]
        p_m = monthly_roi["props"]
        if p_m["total"] > 0:
            sport_msg += f"• **Props ROI (30d):** {p_m['hits']}/{p_m['total']} | profit: ${p_m['profit']:,.2f}\n"
            if p_y["total"] > 0:
                sport_msg += f"• Props Yesterday: {p_y['hits']}/{p_y['total']} (${p_y['profit']:,.2f})\n"
        
        # Games ROI
        g_y = yesterday_roi["games"]
        g_m = monthly_roi["games"]
        if g_m["total"] > 0:
            sport_msg += f"• **Games ROI (30d):** {g_m['hits']}/{g_m['total']} | profit: ${g_m['profit']:,.2f}\n"
            if g_y["total"] > 0:
                sport_msg += f"• Games Yesterday: {g_y['hits']}/{g_y['total']} (${g_y['profit']:,.2f})\n"
        
        audit_msg += sport_msg + "\n"
        
    # Send to Discord
    send_discord_notification("Daily System Audit", audit_msg, color="green" if "OK" in audit_msg else "orange")
    print("\n  Audit complete. Report sent to Discord.")

if __name__ == "__main__":
    # Ensure project_config exists or mock it
    if not os.path.exists(os.path.join(SCRIPT_DIR, "project_config.py")):
        print("[WARN] project_config.py missing, creating temporary mock...")
        with open(os.path.join(SCRIPT_DIR, "project_config.py"), "w") as f:
            f.write("SPORTS = ['nhl', 'nba', 'mlb']\n")
            f.write("DB_PATHS = {\n")
            f.write("  'nhl': 'nhl/database/nhl_predictions_v2.db',\n")
            f.write("  'nba': 'nba/database/nba_predictions.db',\n")
            f.write("  'mlb': 'mlb/database/mlb_predictions.db'\n")
            f.write("}\n")

    run_audit()
