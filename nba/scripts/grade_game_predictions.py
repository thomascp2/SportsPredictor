"""
NBA Game Prediction Grading — Grade yesterday's game predictions.

Fetches final scores from ESPN API, updates the games table,
then grades all predictions using the shared grader.

Usage:
    python grade_game_predictions.py              # Yesterday's games
    python grade_game_predictions.py 2026-03-24   # Specific date
    python grade_game_predictions.py --force      # Re-grade
"""

import sqlite3
import json
import os
import sys
import argparse
import urllib.request
from datetime import datetime, timedelta

# Path setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NBA_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(NBA_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))

from nba_config import DB_PATH
from grade_game_predictions import GamePredictionGrader
from game_discord_notifications import send_game_grading_alert


def fetch_final_scores(db_path: str, game_date: str) -> int:
    """
    Fetch final scores from ESPN and update games table.

    Returns number of games updated.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check which games need scores
    games_needing_scores = conn.execute("""
        SELECT game_id, home_team, away_team
        FROM games
        WHERE game_date = ?
          AND (home_score IS NULL OR away_score IS NULL)
    """, (game_date,)).fetchall()

    if not games_needing_scores:
        existing = conn.execute("""
            SELECT COUNT(*) FROM games
            WHERE game_date = ? AND home_score IS NOT NULL
        """, (game_date,)).fetchone()[0]
        conn.close()
        print(f"  [NBA] All {existing} games already have scores for {game_date}")
        return existing

    # Fetch from ESPN
    updated = 0
    try:
        espn_date = game_date.replace("-", "")
        url = (f"https://site.api.espn.com/apis/site/v2/sports/basketball"
               f"/nba/scoreboard?dates={espn_date}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        for event in data.get("events", []):
            status = event.get("status", {}).get("type", {}).get("completed", False)
            if not status:
                continue

            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])
            if len(competitors) < 2:
                continue

            home_comp = next((c for c in competitors
                             if c.get("homeAway") == "home"), None)
            away_comp = next((c for c in competitors
                             if c.get("homeAway") == "away"), None)

            if not home_comp or not away_comp:
                continue

            home_abbr = home_comp.get("team", {}).get("abbreviation", "")
            away_abbr = away_comp.get("team", {}).get("abbreviation", "")
            home_score = int(home_comp.get("score", 0))
            away_score = int(away_comp.get("score", 0))

            # Handle ESPN abbreviation differences
            abbr_map = {
                "GS": "GSW", "SA": "SAS", "NY": "NYK",
                "NO": "NOP", "WSH": "WAS", "PHX": "PHO",
                "UTAH": "UTA",
            }
            home_abbr = abbr_map.get(home_abbr, home_abbr)
            away_abbr = abbr_map.get(away_abbr, away_abbr)

            # Check if updated_at column exists
            cols = [r[1] for r in conn.execute("PRAGMA table_info(games)").fetchall()]
            if "updated_at" in cols:
                conn.execute("""
                    UPDATE games
                    SET home_score = ?, away_score = ?, updated_at = ?
                    WHERE game_date = ? AND home_team = ? AND away_team = ?
                """, (home_score, away_score,
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      game_date, home_abbr, away_abbr))
            else:
                conn.execute("""
                    UPDATE games
                    SET home_score = ?, away_score = ?
                    WHERE game_date = ? AND home_team = ? AND away_team = ?
                """, (home_score, away_score,
                      game_date, home_abbr, away_abbr))

            if conn.total_changes > 0:
                updated += 1
                print(f"    {away_abbr} {away_score} @ {home_abbr} {home_score}")

    except Exception as e:
        print(f"  [NBA] ESPN API error: {e}")

    conn.commit()
    conn.close()
    return updated


def main():
    parser = argparse.ArgumentParser(description="Grade NBA Game Predictions")
    parser.add_argument("date", nargs="?",
                        default=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                        help="Date to grade (default: yesterday)")
    parser.add_argument("--force", action="store_true",
                        help="Re-grade even if outcomes exist")
    args = parser.parse_args()

    game_date = args.date
    print(f"\n{'='*60}")
    print(f"  NBA Game Prediction Grading - {game_date}")
    print(f"{'='*60}")

    # Step 1: Fetch final scores
    print(f"\n  Step 1: Fetching final scores...")
    scores_count = fetch_final_scores(DB_PATH, game_date)
    if scores_count == 0:
        print(f"  [NBA] No final scores available for {game_date}")
        print(f"  Games may not have been played or aren't finished yet.")
        return

    # Step 2: Grade predictions
    print(f"\n  Step 2: Grading predictions...")
    grader = GamePredictionGrader(sport="nba", db_path=DB_PATH)
    results = grader.grade_date(game_date, force=args.force)

    # Print results
    print(f"\n  --- Grading Results ---")
    if results["graded"] == 0:
        print(f"  {results.get('message', 'No predictions to grade')}")
    else:
        print(f"  Graded:   {results['graded']}")
        print(f"  Hits:     {results['hits']}")
        print(f"  Misses:   {results['misses']}")
        print(f"  Pushes:   {results['pushes']}")
        print(f"  Accuracy: {results['accuracy']}%")

        # Send Discord notification
        try:
            send_game_grading_alert("nba", results)
            print(f"  [DISCORD] Grading notification sent")
        except Exception as e:
            print(f"  [DISCORD] Failed: {e}")

    # Step 3: Performance summary
    print(f"\n  Step 3: Recent performance (last 30 days)...")
    summary = grader.get_performance_summary(30)
    if summary:
        print(f"\n  {'Bet Type + Tier':<30} {'Hits':>5} {'Miss':>5} {'Total':>6} {'Acc':>7}")
        print(f"  {'-'*55}")
        for key, v in sorted(summary.items()):
            print(f"  {key:<30} {v['hits']:>5} {v['misses']:>5} {v['total']:>6} {v['accuracy']:>6.1f}%")

    print(f"\n  Done!")


if __name__ == "__main__":
    main()
