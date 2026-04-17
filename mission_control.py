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
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

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


# --- HEALTH REPORT HELPERS ---

def _health_header(sport, db_path):
    icon = {"NBA": "[NBA]", "NHL": "[NHL]", "MLB": "[MLB]"}.get(sport, sport)
    size_mb = db_path.stat().st_size / 1_048_576 if db_path.exists() else 0
    mtime = datetime.fromtimestamp(db_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if db_path.exists() else "N/A"
    print(f"\n{BOLD}{CYAN}{'='*62}{RESET}")
    print(f"{BOLD}  {icon}  {sport} DATABASE HEALTH & PERFORMANCE AUDIT{RESET}")
    print(f"{BOLD}{CYAN}{'='*62}{RESET}")
    print(f"  DB   : {DIM}{db_path}{RESET}")
    print(f"  Size : {size_mb:.1f} MB  |  Last Modified: {mtime}")

def _print_daily_table(cursor, outcomes_col_prediction="prediction"):
    """Last 7 days summary. Works for both NBA and NHL schemas."""
    print(f"\n{BOLD}LAST 7 DAYS:{RESET}")
    print(f"  {'Date':<12} {'Preds':>6}  {'Graded':>7}  {'Hit%':>7}  {'Logs':>6}")
    print(f"  {'-'*46}")
    rows = cursor.execute("""
        SELECT
            p.game_date,
            count(p.id) as pred_count,
            count(o.id) as graded_count,
            SUM(CASE WHEN o.outcome='HIT' THEN 1 ELSE 0 END) as wins,
            (SELECT count(*) FROM player_game_logs l WHERE l.game_date=p.game_date) as logs
        FROM predictions p
        LEFT JOIN prediction_outcomes o ON p.id=o.prediction_id
        GROUP BY p.game_date
        ORDER BY p.game_date DESC
        LIMIT 7
    """).fetchall()
    for row in rows:
        wins    = row[3] or 0
        graded  = row[2]
        logs    = row[4] or 0
        if graded > 0:
            pct   = wins / graded * 100
            color = GREEN if pct >= 60 else (YELLOW if pct >= 50 else RED)
            hit_s = f"{color}{pct:>5.1f}%{RESET}"
        else:
            hit_s = f"{'N/A':>6}"
        print(f"  {row[0]:<12} {row[1]:>6}  {graded:>7}  {hit_s}  {logs:>6}")

def _print_prop_performance(cursor):
    print(f"\n{BOLD}PROP PERFORMANCE (min 50 graded, all-time):{RESET}")
    print(f"  {'Prop':<20} {'Graded':>7}  {'Hit%':>7}  {'OVER%':>7}  {'UNDER%':>8}")
    print(f"  {'-'*56}")
    rows = cursor.execute("""
        SELECT
            prop_type,
            count(*) as graded,
            SUM(CASE WHEN outcome='HIT' THEN 1 ELSE 0 END) as hits,
            SUM(CASE WHEN outcome='HIT' AND prediction='OVER'  THEN 1 ELSE 0 END) as over_hits,
            SUM(CASE WHEN prediction='OVER'  THEN 1 ELSE 0 END) as over_total,
            SUM(CASE WHEN outcome='HIT' AND prediction='UNDER' THEN 1 ELSE 0 END) as under_hits,
            SUM(CASE WHEN prediction='UNDER' THEN 1 ELSE 0 END) as under_total
        FROM prediction_outcomes
        GROUP BY prop_type
        HAVING graded >= 50
        ORDER BY CAST(hits AS FLOAT)/graded DESC
    """).fetchall()
    for r in rows:
        pct  = r[2] / r[1] * 100
        over  = f"{r[3]/r[4]*100:.1f}%" if r[4] > 0 else " N/A"
        under = f"{r[5]/r[6]*100:.1f}%" if r[6] > 0 else " N/A"
        color = GREEN if pct >= 60 else (YELLOW if pct >= 50 else RED)
        print(f"  {r[0]:<20} {r[1]:>7}  {color}{pct:>6.1f}%{RESET}  {over:>7}  {under:>8}")

def _print_ml_readiness(cursor, target=10000):
    print(f"\n{BOLD}ML READINESS  (target: {target:,} per prop/line):{RESET}")
    print(f"  {'Prop':<16} {'Line':>5}  {'Graded':>7}  {'Progress':<28} {'%':>4}")
    print(f"  {'-'*65}")
    rows = cursor.execute("""
        SELECT prop_type, line, count(*) as cnt
        FROM prediction_outcomes
        GROUP BY prop_type, line
        ORDER BY prop_type, line
    """).fetchall()
    for r in rows:
        cnt     = r[2]
        pct     = min(cnt / target * 100, 100)
        filled  = int(pct / 5)          # 20-char bar
        bar     = "#" * filled + "." * (20 - filled)
        color   = GREEN if pct >= 80 else (YELLOW if pct >= 40 else RED)
        print(f"  {r[0]:<16} {r[1]:>5.1f}  {cnt:>7,}  {color}[{bar}]{RESET} {pct:>4.0f}%")


def nba_health_report():
    path = DB_PATHS["NBA"]
    if not path.exists():
        print(f"\n{RED}NBA database not found: {path}{RESET}")
        input(f"\n{CYAN}Press Enter to return to menu...{RESET}")
        return

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    _health_header("NBA", path)

    total_preds  = c.execute("SELECT count(*) FROM predictions").fetchone()[0]
    total_graded = c.execute("SELECT count(*) FROM prediction_outcomes").fetchone()[0]
    total_logs   = c.execute("SELECT count(*) FROM player_game_logs").fetchone()[0]
    unique_days  = c.execute("SELECT count(DISTINCT game_date) FROM player_game_logs").fetchone()[0]
    date_range   = c.execute("SELECT min(game_date), max(game_date) FROM player_game_logs").fetchone()

    print(f"\n{BOLD}OVERALL STATS:{RESET}")
    print(f"  Total Predictions : {total_preds:>10,}")
    print(f"  Graded Outcomes   : {total_graded:>10,}")
    print(f"  Player Game Logs  : {total_logs:>10,}  ({unique_days} game days)")
    if date_range[0]:
        print(f"  Log Date Range    : {date_range[0]}  ->  {date_range[1]}")

    _print_daily_table(c)
    _print_prop_performance(c)
    _print_ml_readiness(c)

    conn.close()
    print(f"\n{BOLD}{CYAN}{'='*62}{RESET}")
    input(f"\n{CYAN}Press Enter to return to menu...{RESET}")


def nhl_health_report():
    path = DB_PATHS["NHL"]
    if not path.exists():
        print(f"\n{RED}NHL database not found: {path}{RESET}")
        input(f"\n{CYAN}Press Enter to return to menu...{RESET}")
        return

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    _health_header("NHL", path)

    total_preds  = c.execute("SELECT count(*) FROM predictions").fetchone()[0]
    total_graded = c.execute("SELECT count(*) FROM prediction_outcomes").fetchone()[0]
    total_logs   = c.execute("SELECT count(*) FROM player_game_logs").fetchone()[0]
    unique_days  = c.execute("SELECT count(DISTINCT game_date) FROM player_game_logs").fetchone()[0]
    date_range   = c.execute("SELECT min(game_date), max(game_date) FROM player_game_logs").fetchone()

    print(f"\n{BOLD}OVERALL STATS:{RESET}")
    print(f"  Total Predictions : {total_preds:>10,}")
    print(f"  Graded Outcomes   : {total_graded:>10,}")
    print(f"  Player Game Logs  : {total_logs:>10,}  ({unique_days} game days)")
    if date_range[0]:
        print(f"  Log Date Range    : {date_range[0]}  ->  {date_range[1]}")

    _print_daily_table(c)
    _print_prop_performance(c)

    # NHL-specific: confidence tier breakdown
    tier_rows = c.execute("""
        SELECT confidence_tier,
               count(*) as graded,
               SUM(CASE WHEN outcome='HIT' THEN 1 ELSE 0 END) as hits
        FROM prediction_outcomes
        WHERE confidence_tier IS NOT NULL
        GROUP BY confidence_tier
        ORDER BY confidence_tier
    """).fetchall()
    if tier_rows:
        print(f"\n{BOLD}CONFIDENCE TIER BREAKDOWN:{RESET}")
        print(f"  {'Tier':<12} {'Graded':>7}  {'Hit%':>7}")
        print(f"  {'-'*30}")
        for r in tier_rows:
            pct   = r[2] / r[1] * 100 if r[1] > 0 else 0
            color = GREEN if pct >= 60 else (YELLOW if pct >= 50 else RED)
            print(f"  {r[0]:<12} {r[1]:>7}  {color}{pct:>6.1f}%{RESET}")

    _print_ml_readiness(c)

    conn.close()
    print(f"\n{BOLD}{CYAN}{'='*62}{RESET}")
    input(f"\n{CYAN}Press Enter to return to menu...{RESET}")


def main_menu():
    while True:
        clear_screen()
        today_str = datetime.now().strftime("%A, %B %d, %Y")

        print(f"{BOLD}{CYAN}============================================================{RESET}")
        print(f"{BOLD}   [B] [NBA] [NHL]  SPORTS PREDICTOR: MISSION CONTROL  [NHL] [NBA] [B]{RESET}")
        print(f"{BOLD}{CYAN}============================================================{RESET}")
        print(f"  Today: {today_str} | Root: {PROJECT_ROOT}")
        print("-" * 60)

        top_pick = get_top_pick()
        if top_pick:
            sport, player, prop, line, pick, prob = top_pick
            print(f"{BOLD}TOP INTELLIGENCE:{RESET}")
            print(f"  {sport}: {player} {prop} {line} ({pick}) @ {prob*100:.1f}% PROBABILITY")
        else:
            print(f"{YELLOW}TOP INTELLIGENCE: Waiting for daily data pipelines...{RESET}")
        print("-" * 60)

        print(f"{BOLD}DATABASE STATUS:{RESET}")
        for sport, path in DB_PATHS.items():
            print(f"  {sport:<4}: {get_db_status(path)}")
        print("-" * 60)

        print(f"{BOLD}CORE COMMANDS:{RESET}")
        print(f"  {CYAN}[1]{RESET} Smart Picks Dashboard  --> {BOLD}(T){RESET}erminal or {BOLD}(B){RESET}rowser?")
        print(f"  {CYAN}[2]{RESET} Kalshi Parlay Lottery --> {BOLD}(T){RESET}erminal or {BOLD}(B){RESET}rowser?")
        print(f"  {CYAN}[3]{RESET} MLB Readiness & Performance Audit")
        print(f"  {CYAN}[4]{RESET} Start ALL Daily Pipelines (NBA/NHL/MLB)")
        print(f"  {CYAN}[5]{RESET} View Live Scoreboard")
        print("-" * 60)
        print(f"{BOLD}DATABASE HEALTH:{RESET}")
        print(f"  {CYAN}[6]{RESET} NBA Health & Performance Audit")
        print(f"  {CYAN}[7]{RESET} NHL Health & Performance Audit")
        print("-" * 60)
        print(f"{BOLD}INTELLIGENCE:{RESET}")
        print(f"  {CYAN}[8]{RESET} StatBot -- Natural Language DB Query {DIM}(AI){RESET}")
        print("-" * 60)
        print(f"  {CYAN}[9]{RESET} Open Project Folder")
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
            nba_health_report()
        elif choice == '7':
            nhl_health_report()
        elif choice == '8':
            sys.path.insert(0, str(PROJECT_ROOT))
            try:
                from scripts.stat_bot import run_statbot
                run_statbot()
            except Exception as e:
                print(f"\n{RED}StatBot failed to load: {e}{RESET}")
                input(f"\n{CYAN}Press Enter to return to menu...{RESET}")
        elif choice == '9':
            os.startfile(PROJECT_ROOT)
        elif choice == 'q':
            print("\nGood luck today!")
            break
        else:
            print(f"\n{RED}Invalid choice.{RESET}"); time.sleep(1)

if __name__ == "__main__":
    main_menu()
