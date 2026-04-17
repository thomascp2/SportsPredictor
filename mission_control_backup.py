import os
import sys
import subprocess
import time
import sqlite3
from datetime import date, datetime
from pathlib import Path

# --- CONFIGURATION ---
PROJECT_ROOT = Path(__file__).parent.resolve()
DB_PATHS = {
    "NBA": PROJECT_ROOT / "nba" / "database" / "nba_predictions.db",
    "NHL": PROJECT_ROOT / "nhl" / "database" / "nhl_predictions_v2.db",
    "MLB": PROJECT_ROOT / "mlb" / "database" / "mlb_predictions.db"
}

# --- STYLING ---
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_db_status(db_path):
    if not db_path.exists():
        return f"{RED}MISSING{RESET}"
    try:
        conn = sqlite3.connect(str(db_path))
        today = date.today().isoformat()
        res = conn.execute("SELECT count(*) FROM predictions WHERE game_date = ?", (today,)).fetchone()
        count = res[0] if res else 0
        conn.close()
        return f"{GREEN}UPDATED ({count} Preds){RESET}" if count > 0 else f"{YELLOW}STALE (No data for today){RESET}"
    except:
        return f"{RED}ERROR{RESET}"

def run_terminal_command(cmd):
    """Runs a command and stays in the current terminal (synchronous)."""
    subprocess.run(f"set PYTHONPATH=.&& {cmd}", shell=True)
    input(f"\n{CYAN}Press Enter to return to menu...{RESET}")

def launch_async(name, cmd):
    """Launches a command in a new window (asynchronous)."""
    print(f"\n{CYAN}Launching {name} in new window...{RESET}")
    subprocess.Popen(f"start cmd /k \"set PYTHONPATH=.&& {cmd}\"", shell=True)

def get_top_pick():
    today = date.today().isoformat()
    best_bet = None
    best_prob = 0
    for sport, path in DB_PATHS.items():
        if path.exists():
            try:
                conn = sqlite3.connect(str(path))
                res = conn.execute("SELECT player_name, prop_type, line, prediction, probability FROM predictions WHERE game_date = ? ORDER BY probability DESC LIMIT 1", (today,)).fetchone()
                if res and res[4] > best_prob:
                    best_bet = (sport, res[0], res[1], res[2], res[3], res[4])
                    best_prob = res[4]
                conn.close()
            except: pass
    return best_bet

def main_menu():
    while True:
        clear_screen()
        today_str = datetime.now().strftime("%A, %B %d, %Y")
        
        print(f"{BOLD}{CYAN}============================================================{RESET}")
        print(f"{BOLD}   ⚾ 🏀 🏒  SPORTS PREDICTOR: MISSION CONTROL  🏒 🏀 ⚾{RESET}")
        print(f"{BOLD}{CYAN}============================================================{RESET}")
        print(f"  Today: {today_str} | Root: {PROJECT_ROOT}")
        print("-" * 60)
        
        top_pick = get_top_pick()
        if top_pick:
            sport, player, prop, line, pick, prob = top_pick
            print(f"{BOLD}🔥 TOP INTELLIGENCE:{RESET}")
            print(f"  {sport}: {player} {prop} {line} ({pick}) @ {prob*100:.1f}% PROBABILITY")
        else:
            print(f"{YELLOW}⏳ TOP INTELLIGENCE: Waiting for daily data pipelines...{RESET}")
        print("-" * 60)

        print(f"{BOLD}DATABASE STATUS:{RESET}")
        for sport, path in DB_PATHS.items():
            print(f"  {sport:<4}: {get_db_status(path)}")
        print("-" * 60)

        print(f"{BOLD}CORE COMMANDS:{RESET}")
        print(f"  {CYAN}[1]{RESET} Smart Picks Dashboard  --> {BOLD}(T){RESET}erminal or {BOLD}(B){RESET}rowser?")
        print(f"  {CYAN}[2]{RESET} Kalshi Parlay Lottery --> {BOLD}(T){RESET}erminal or {BOLD}(B){RESET}rowser?")
        print(f"  {CYAN}[3]{RESET} MLB Readiness & Performance Audit (Terminal)")
        print(f"  {CYAN}[4]{RESET} Start ALL Daily Pipelines (NBA/NHL/MLB)")
        print(f"  {CYAN}[5]{RESET} View Live Scoreboard (Terminal)")
        print(f"  {CYAN}[6]{RESET} Open Project Folder")
        print("-" * 60)
        print(f"  {RED}[Q]{RESET} Quit Mission Control")
        print("-" * 60)
        
        choice = input(f"{BOLD}Choice > {RESET}").strip().lower()

        if choice == '1':
            sub = input("  Display in (T)erminal or (B)rowser? ").strip().lower()
            if sub == 'b': launch_async("Smart Picks Browser", "streamlit run dashboards/smart_picks_app.py")
            else: run_terminal_command("python scripts/smart_picks_cli.py")
        elif choice == '2':
            sub = input("  Display in (T)erminal or (B)rowser? ").strip().lower()
            if sub == 'b': launch_async("Kalshi Browser", "streamlit run parlay_lottery/app.py")
            else: run_terminal_command("python parlay_lottery/parlay_generator.py")
        elif choice == '3':
            run_terminal_command("python mlb/scripts/status_check.py")
        elif choice == '4':
            print(f"\n{YELLOW}Starting ALL pipelines in separate windows...{RESET}")
            launch_async("NBA Pipeline", "scripts\\nba_game_predictions.bat")
            launch_async("NHL Pipeline", "scripts\\nhl_game_predictions.bat")
            launch_async("MLB Pipeline", "scripts\\mlb_game_predictions.bat")
        elif choice == '5':
            run_terminal_command("python scoreboard/scoreboard.py")
        elif choice == '6':
            os.startfile(PROJECT_ROOT)
        elif choice == 'q':
            print("\nGood luck today! 🍀")
            break
        else:
            print(f"\n{RED}Invalid choice.{RESET}"); time.sleep(1)

if __name__ == "__main__":
    main_menu()
