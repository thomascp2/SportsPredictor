import sqlite3
import os
from pathlib import Path
from datetime import date
import pandas as pd

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DB_PATHS = {
    "NBA": PROJECT_ROOT / "nba" / "database" / "nba_predictions.db",
    "NHL": PROJECT_ROOT / "nhl" / "database" / "nhl_predictions_v2.db",
    "MLB": PROJECT_ROOT / "mlb" / "database" / "mlb_predictions.db"
}

# --- STYLING ---
GREEN = "\033[92m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def get_picks(sport, db_path, min_edge=0.05):
    if not db_path.exists(): return []
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    today = date.today().isoformat()
    
    # Dynamically check if confidence_tier exists
    cursor = conn.execute("PRAGMA table_info(predictions)")
    cols = [c['name'] for c in cursor.fetchall()]
    has_tier = 'confidence_tier' in cols
    
    tier_col = "confidence_tier" if has_tier else "'N/A' as confidence_tier"
    
    query = f"""
        SELECT player_name, prop_type, line, prediction, probability, {tier_col}
        FROM predictions 
        WHERE game_date = ? AND probability >= ?
        ORDER BY probability DESC
    """
    # Note: Adjust threshold based on sport (some use 0.54, some use 0.60)
    rows = conn.execute(query, (today, 0.60)).fetchall()
    conn.close()
    
    picks = []
    for r in rows:
        picks.append({
            "Sport": sport,
            "Player": r['player_name'],
            "Prop": r['prop_type'],
            "Line": r['line'],
            "Pick": r['prediction'],
            "Prob": f"{r['probability']*100:.1f}%",
            "Tier": r['confidence_tier']
        })
    return picks

def run_cli_dashboard():
    print(f"{BOLD}{CYAN}============================================================{RESET}")
    print(f"{BOLD}             🔥 TOP SMART PICKS FOR TODAY 🔥{RESET}")
    print(f"{BOLD}{CYAN}============================================================{RESET}")
    
    all_picks = []
    for sport, path in DB_PATHS.items():
        all_picks.extend(get_picks(sport, path))
    
    if not all_picks:
        print(f"\n   {BOLD}No high-confidence picks found yet. Run pipelines?{RESET}\n")
        return

    # Print a clean manual table
    header = f"{'SPORT':<6} | {'PLAYER':<18} | {'PROP':<15} | {'LINE':<5} | {'PICK':<5} | {'PROB':<6}"
    print(f"{BOLD}{header}{RESET}")
    print("-" * len(header))
    
    for p in all_picks[:20]: # Show top 20
        color = GREEN if "T1" in p['Tier'] else ""
        print(f"{color}{p['Sport']:<6} | {p['Player']:<18} | {p['Prop']:<15} | {p['Line']:<5} | {p['Pick']:<5} | {p['Prob']:<6}{RESET}")
    
    print(f"{CYAN}============================================================{RESET}")

if __name__ == "__main__":
    run_cli_dashboard()
