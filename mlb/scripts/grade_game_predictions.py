"""
MLB Game Prediction Grading — Grade yesterday's game predictions.

Fetches final scores from MLB Stats API, updates the games table,
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
MLB_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(MLB_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))

from mlb_config import DB_PATH
from grade_game_predictions import GamePredictionGrader
from game_discord_notifications import send_game_grading_alert
from elo_engine import EloEngine, TEAM_ALIASES


def fetch_final_scores(db_path: str, game_date: str) -> int:
    """
    Fetch final scores from MLB Stats API and update games table.

    Returns number of games updated.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check which tables exist
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    # Prefer game_context (has correct game_ids matching MLB API gamePk).
    # Fall back to games table only if game_context has no data for this date.
    gc_count = 0
    if "game_context" in tables:
        try:
            gc_count = conn.execute(
                "SELECT COUNT(*) FROM game_context WHERE game_date = ?", (game_date,)
            ).fetchone()[0]
        except Exception:
            pass
    score_table = "game_context" if gc_count > 0 else ("games" if "games" in tables else "game_context")

    # Check which games need scores
    try:
        games_needing_scores = conn.execute(f"""
            SELECT game_id, home_team, away_team
            FROM {score_table}
            WHERE game_date = ?
              AND (home_score IS NULL OR away_score IS NULL)
        """, (game_date,)).fetchall()
    except Exception:
        games_needing_scores = []

    if not games_needing_scores:
        try:
            existing = conn.execute(f"""
                SELECT COUNT(*) FROM {score_table}
                WHERE game_date = ? AND home_score IS NOT NULL
            """, (game_date,)).fetchone()[0]
        except Exception:
            existing = 0
        conn.close()
        if existing > 0:
            print(f"  [MLB] All {existing} games already have scores for {game_date}")
        return existing

    # Build team ID → abbreviation map (MLB Stats API no longer embeds
    # abbreviation in the schedule response — must fetch separately).
    team_id_to_abbr = {}
    try:
        teams_url = "https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2026"
        teams_req = urllib.request.Request(teams_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(teams_req, timeout=15) as tresp:
            teams_data = json.loads(tresp.read())
        for t in teams_data.get("teams", []):
            tid = t.get("id")
            abbr = t.get("abbreviation") or t.get("teamCode", "").upper()
            if tid and abbr:
                team_id_to_abbr[tid] = abbr
    except Exception as e:
        print(f"  [MLB] Could not fetch team abbreviations: {e}")

    # Fetch from MLB Stats API
    updated = 0
    try:
        url = (f"https://statsapi.mlb.com/api/v1/schedule"
               f"?date={game_date}&sportId=1&gameType=R"
               f"&hydrate=linescore")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                status = game.get("status", {}).get("abstractGameState", "")
                if status != "Final":
                    continue

                teams = game.get("teams", {})
                home_info = teams.get("home", {})
                away_info = teams.get("away", {})

                # Use team ID lookup — abbreviation is no longer in schedule response
                home_id = home_info.get("team", {}).get("id")
                away_id = away_info.get("team", {}).get("id")
                home_abbr = team_id_to_abbr.get(home_id, "")
                away_abbr = team_id_to_abbr.get(away_id, "")
                game_pk = str(game.get("gamePk", ""))
                home_score = home_info.get("score")
                away_score = away_info.get("score")

                if home_score is not None and away_score is not None:
                    rows_updated = 0
                    for table in [score_table, "games"]:
                        if table not in tables:
                            continue
                        try:
                            cols = [r[1] for r in
                                    conn.execute(f"PRAGMA table_info({table})").fetchall()]
                            if "home_score" not in cols:
                                continue

                            # Primary match: game_id (gamePk) — most reliable
                            if game_pk and "game_id" in cols:
                                cur = conn.execute(f"""
                                    UPDATE {table}
                                    SET home_score = ?, away_score = ?,
                                        status = 'final'
                                    WHERE game_id = ?
                                """, (home_score, away_score, game_pk))
                                rows_updated += cur.rowcount

                            # Fallback: team abbreviation match
                            if home_abbr and away_abbr:
                                cur = conn.execute(f"""
                                    UPDATE {table}
                                    SET home_score = ?, away_score = ?,
                                        status = 'final'
                                    WHERE game_date = ?
                                      AND home_team = ? AND away_team = ?
                                      AND home_score IS NULL
                                """, (home_score, away_score,
                                      game_date, home_abbr, away_abbr))
                                rows_updated += cur.rowcount
                        except Exception:
                            pass

                    if rows_updated > 0:
                        updated += 1
                        print(f"    {away_abbr or away_id} {away_score} @ {home_abbr or home_id} {home_score}")

    except Exception as e:
        print(f"  [MLB] API error: {e}")

    conn.commit()
    conn.close()
    return updated


def update_elo_ratings(db_path: str, game_date: str) -> int:
    """Update MLB Elo ratings from newly scored games on game_date."""
    elo = EloEngine(sport="mlb")
    elo.load()  # OK if file missing — starts from defaults

    aliases = TEAM_ALIASES.get("mlb", {})
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    games = []
    for table in ("game_context", "games"):
        try:
            rows = conn.execute(f"""
                SELECT home_team, away_team, home_score, away_score
                FROM {table}
                WHERE game_date = ? AND home_score IS NOT NULL AND away_score IS NOT NULL
            """, (game_date,)).fetchall()
            if rows:
                games = rows
                break
        except Exception:
            continue
    conn.close()

    updated = 0
    for g in games:
        home = aliases.get(g["home_team"], g["home_team"])
        away = aliases.get(g["away_team"], g["away_team"])
        elo.update(home, away, g["home_score"], g["away_score"], game_date)
        updated += 1

    if updated:
        elo.save()
        print(f"  [ELO] Updated {updated} game(s) — ratings saved")

    return updated


def main():
    parser = argparse.ArgumentParser(description="Grade MLB Game Predictions")
    parser.add_argument("date", nargs="?",
                        default=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                        help="Date to grade (default: yesterday)")
    parser.add_argument("--force", action="store_true",
                        help="Re-grade even if outcomes exist")
    args = parser.parse_args()

    game_date = args.date
    print(f"\n{'='*60}")
    print(f"  MLB Game Prediction Grading - {game_date}")
    print(f"{'='*60}")

    # Step 1: Fetch final scores
    print(f"\n  Step 1: Fetching final scores...")
    scores_count = fetch_final_scores(DB_PATH, game_date)
    if scores_count == 0:
        print(f"  [MLB] No final scores available for {game_date}")
        print(f"  Games may not have been played or aren't finished yet.")
        return

    # Step 1b: Update Elo ratings from final scores
    update_elo_ratings(DB_PATH, game_date)

    # Step 2: Grade predictions
    print(f"\n  Step 2: Grading predictions...")
    grader = GamePredictionGrader(sport="mlb", db_path=DB_PATH)
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
            send_game_grading_alert("mlb", results)
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
