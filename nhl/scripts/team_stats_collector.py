"""
NHL Team Stats Collector — Builds rolling team profiles from game data.

Aggregates from two sources:
    1. Local player_game_logs (primary — already have 37k+ rows)
    2. Local games table (W/L/OTL records, scoring)

Populates the existing team_stats table and adds rolling window stats
to a new team_rolling_stats table for ML features.

Usage:
    python team_stats_collector.py                # Update all teams
    python team_stats_collector.py --team BOS     # Single team
    python team_stats_collector.py --rebuild      # Full rebuild from scratch
"""

import sqlite3
import os
import sys
import argparse
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    from v2_config import DB_PATH
except ImportError:
    DB_PATH = os.path.join(SCRIPT_DIR, "..", "database", "nhl_predictions_v2.db")

SEASON = "2025-2026"
SEASON_START_DATE = "2025-10-01"  # Only use 2025-26 games for stats

# ── Schema ────────────────────────────────────────────────────────────────────

ROLLING_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_rolling_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    window TEXT NOT NULL,          -- 'L5', 'L10', 'L20', 'season'

    -- Record
    games_played INTEGER,
    wins INTEGER,
    losses INTEGER,
    otl INTEGER,
    win_pct REAL,

    -- Offense
    goals_for_avg REAL,
    shots_for_avg REAL,
    pp_opportunities INTEGER,
    pp_goals INTEGER,
    pp_pct REAL,

    -- Defense
    goals_against_avg REAL,
    shots_against_avg REAL,
    pk_opportunities INTEGER,
    pk_kills INTEGER,
    pk_pct REAL,

    -- Derived
    goal_diff_avg REAL,           -- GF - GA per game
    shot_diff_avg REAL,           -- SF - SA per game
    scoring_first_pct REAL,       -- % of games scoring first (future)
    home_win_pct REAL,
    away_win_pct REAL,

    -- Player aggregates from game_logs
    avg_hits_per_game REAL,
    avg_blocks_per_game REAL,
    avg_pim_per_game REAL,

    last_updated TEXT NOT NULL,
    UNIQUE(team, as_of_date, window)
)
"""


def ensure_tables(conn):
    """Create tables if they don't exist."""
    conn.execute(ROLLING_STATS_SCHEMA)
    conn.commit()


# ── Data aggregation from games table ─────────────────────────────────────────

def get_team_games(conn, team, as_of_date=None, last_n=None, season_start=SEASON_START_DATE):
    """
    Fetch game results for a team, optionally filtered.

    Returns list of dicts with: game_date, is_home, team_score, opp_score, result
    """
    query = """
        SELECT game_date,
               CASE WHEN home_team = ? THEN 1 ELSE 0 END as is_home,
               CASE WHEN home_team = ? THEN home_score ELSE away_score END as team_score,
               CASE WHEN home_team = ? THEN away_score ELSE home_score END as opp_score
        FROM games
        WHERE (home_team = ? OR away_team = ?)
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND (game_state = 'FINAL' OR game_state = 'OFF')
          AND game_date >= ?
    """
    params = [team, team, team, team, team, season_start]

    if as_of_date:
        query += " AND game_date <= ?"
        params.append(as_of_date)

    query += " ORDER BY game_date DESC"

    if last_n:
        query += f" LIMIT {last_n}"

    cursor = conn.execute(query, params)
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, row)) for row in cursor.fetchall()]

    # Add result column
    for g in rows:
        if g["team_score"] > g["opp_score"]:
            g["result"] = "W"
        elif g["team_score"] < g["opp_score"]:
            # Check if it was OT/SO (score diff of 1 for away team in NHL could be OT)
            g["result"] = "L"  # Simplified — OTL detection needs period data
        else:
            g["result"] = "OTL"

    return rows


def get_team_player_aggregates(conn, team, as_of_date=None, last_n_games=None):
    """
    Aggregate player-level stats into team totals per game.
    Uses player_game_logs which has hits, blocked_shots, pim, shots, goals, etc.
    """
    query = """
        SELECT game_date,
               SUM(goals) as total_goals,
               SUM(assists) as total_assists,
               SUM(shots_on_goal) as total_shots,
               SUM(hits) as total_hits,
               SUM(blocked_shots) as total_blocks,
               SUM(pim) as total_pim,
               COUNT(DISTINCT player_name) as players_used
        FROM player_game_logs
        WHERE team = ?
    """
    params = [team]

    if as_of_date:
        query += " AND game_date <= ?"
        params.append(as_of_date)

    query += " GROUP BY game_date ORDER BY game_date DESC"

    if last_n_games:
        query += f" LIMIT {last_n_games}"

    cursor = conn.execute(query, params)
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ── Stats calculation ─────────────────────────────────────────────────────────

def calculate_window_stats(games, player_aggs):
    """Calculate aggregated stats from a window of games."""
    if not games:
        return None

    n = len(games)
    wins = sum(1 for g in games if g["result"] == "W")
    losses = sum(1 for g in games if g["result"] == "L")
    otl = sum(1 for g in games if g["result"] == "OTL")

    gf = sum(g["team_score"] or 0 for g in games)
    ga = sum(g["opp_score"] or 0 for g in games)

    home_games = [g for g in games if g["is_home"]]
    away_games = [g for g in games if not g["is_home"]]
    home_wins = sum(1 for g in home_games if g["result"] == "W")
    away_wins = sum(1 for g in away_games if g["result"] == "W")

    # Player aggregates
    total_hits = 0
    total_blocks = 0
    total_pim = 0
    total_shots = 0
    agg_count = 0

    if player_aggs:
        for pa in player_aggs:
            total_hits += pa.get("total_hits") or 0
            total_blocks += pa.get("total_blocks") or 0
            total_pim += pa.get("total_pim") or 0
            total_shots += pa.get("total_shots") or 0
            agg_count += 1

    agg_n = max(agg_count, 1)

    return {
        "games_played": n,
        "wins": wins,
        "losses": losses,
        "otl": otl,
        "win_pct": round(wins / n, 4) if n else 0,
        "goals_for_avg": round(gf / n, 2) if n else 0,
        "goals_against_avg": round(ga / n, 2) if n else 0,
        "goal_diff_avg": round((gf - ga) / n, 2) if n else 0,
        "shots_for_avg": round(total_shots / agg_n, 2) if agg_count else None,
        "shots_against_avg": None,  # Need opponent data — future enhancement
        "shot_diff_avg": None,
        "pp_opportunities": None,   # Need special teams data from API
        "pp_goals": None,
        "pp_pct": None,
        "pk_opportunities": None,
        "pk_kills": None,
        "pk_pct": None,
        "scoring_first_pct": None,
        "home_win_pct": round(home_wins / len(home_games), 4) if home_games else None,
        "away_win_pct": round(away_wins / len(away_games), 4) if away_games else None,
        "avg_hits_per_game": round(total_hits / agg_n, 2) if agg_count else None,
        "avg_blocks_per_game": round(total_blocks / agg_n, 2) if agg_count else None,
        "avg_pim_per_game": round(total_pim / agg_n, 2) if agg_count else None,
    }


# ── Main update logic ────────────────────────────────────────────────────────

def update_team(conn, team, as_of_date=None):
    """Update all rolling windows for a team."""
    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")

    windows = {
        "L5": 5,
        "L10": 10,
        "L20": 20,
        "season": None,  # All games
    }

    for window_name, last_n in windows.items():
        games = get_team_games(conn, team, as_of_date, last_n)
        player_aggs = get_team_player_aggregates(conn, team, as_of_date, last_n)

        stats = calculate_window_stats(games, player_aggs)
        if not stats:
            continue

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("""
            INSERT OR REPLACE INTO team_rolling_stats
            (team, as_of_date, window, games_played, wins, losses, otl, win_pct,
             goals_for_avg, shots_for_avg, pp_opportunities, pp_goals, pp_pct,
             goals_against_avg, shots_against_avg, pk_opportunities, pk_kills, pk_pct,
             goal_diff_avg, shot_diff_avg, scoring_first_pct,
             home_win_pct, away_win_pct,
             avg_hits_per_game, avg_blocks_per_game, avg_pim_per_game,
             last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            team, as_of_date, window_name,
            stats["games_played"], stats["wins"], stats["losses"], stats["otl"], stats["win_pct"],
            stats["goals_for_avg"], stats["shots_for_avg"],
            stats["pp_opportunities"], stats["pp_goals"], stats["pp_pct"],
            stats["goals_against_avg"], stats["shots_against_avg"],
            stats["pk_opportunities"], stats["pk_kills"], stats["pk_pct"],
            stats["goal_diff_avg"], stats["shot_diff_avg"], stats["scoring_first_pct"],
            stats["home_win_pct"], stats["away_win_pct"],
            stats["avg_hits_per_game"], stats["avg_blocks_per_game"], stats["avg_pim_per_game"],
            now,
        ))

    conn.commit()


def update_season_totals(conn, team):
    """Update the existing team_stats table with season totals."""
    games = get_team_games(conn, team, season_start=SEASON_START_DATE)
    player_aggs = get_team_player_aggregates(conn, team)
    stats = calculate_window_stats(games, player_aggs)

    if not stats:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT OR REPLACE INTO team_stats
        (team, season, games_played, wins, losses, otl,
         goals_per_game, shots_per_game, pp_pct,
         goals_against_per_game, shots_against_per_game, pk_pct, save_pct,
         last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        team, SEASON,
        stats["games_played"], stats["wins"], stats["losses"], stats["otl"],
        stats["goals_for_avg"], stats["shots_for_avg"], stats["pp_pct"],
        stats["goals_against_avg"], stats["shots_against_avg"], stats["pk_pct"], None,
        now,
    ))
    conn.commit()


def get_all_teams(conn):
    """Get all teams that have played games this season."""
    cursor = conn.execute("""
        SELECT DISTINCT team FROM (
            SELECT home_team as team FROM games WHERE game_date >= ?
            UNION
            SELECT away_team as team FROM games WHERE game_date >= ?
        ) ORDER BY team
    """, (SEASON_START_DATE, SEASON_START_DATE))
    return [r[0] for r in cursor.fetchall()]


def run(team=None, rebuild=False):
    """Main entry point."""
    conn = sqlite3.connect(DB_PATH)
    ensure_tables(conn)

    teams = [team] if team else get_all_teams(conn)

    if rebuild:
        conn.execute("DELETE FROM team_rolling_stats")
        conn.execute("DELETE FROM team_stats")
        conn.commit()
        print(f"[NHL Team Stats] Cleared existing data for rebuild")

    print(f"[NHL Team Stats] Updating {len(teams)} teams...")

    for t in teams:
        update_team(conn, t)
        update_season_totals(conn, t)

    # Summary
    cursor = conn.execute("SELECT COUNT(*) FROM team_rolling_stats")
    rolling_count = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(*) FROM team_stats")
    season_count = cursor.fetchone()[0]

    print(f"[NHL Team Stats] Done: {rolling_count} rolling stat rows, {season_count} season rows")

    # Show top teams by goal differential
    cursor = conn.execute("""
        SELECT team, goals_for_avg, goals_against_avg, goal_diff_avg, win_pct
        FROM team_rolling_stats
        WHERE window = 'season'
        ORDER BY goal_diff_avg DESC LIMIT 10
    """)
    print(f"\n{'Team':<6} {'GF/G':>6} {'GA/G':>6} {'Diff':>6} {'Win%':>6}")
    print("-" * 35)
    for row in cursor.fetchall():
        team, gf, ga, diff, wpct = row
        print(f"{team:<6} {gf:>6.2f} {ga:>6.2f} {diff:>+6.2f} {wpct:>6.1%}")

    conn.close()
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NHL Team Stats Collector")
    parser.add_argument("--team", type=str, help="Single team abbreviation")
    parser.add_argument("--rebuild", action="store_true", help="Full rebuild")
    args = parser.parse_args()

    run(team=args.team, rebuild=args.rebuild)
