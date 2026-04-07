"""
NBA Team Stats Collector — Builds rolling team profiles from game data.

Aggregates from two sources:
    1. Local player_game_logs (primary — 31k+ rows)
    2. Local games table (W/L records, scoring)

Creates team_stats and team_rolling_stats tables for ML features.

Usage:
    python team_stats_collector.py                # Update all teams
    python team_stats_collector.py --team BOS     # Single team
    python team_stats_collector.py --rebuild      # Full rebuild
"""

import sqlite3
import os
import sys
import argparse
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    from nba_config import DB_PATH
except ImportError:
    DB_PATH = os.path.join(SCRIPT_DIR, "..", "database", "nba_predictions.db")

SEASON = "2025-2026"
# Only include games from this date onward — prevents mixing old-season data.
SEASON_START_DATE = "2025-10-01"

# ── Schema ────────────────────────────────────────────────────────────────────

TEAM_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team TEXT NOT NULL,
    season TEXT NOT NULL,
    games_played INTEGER,
    wins INTEGER,
    losses INTEGER,

    -- Offense
    points_per_game REAL,
    fgm_per_game REAL,
    fga_per_game REAL,
    fg_pct REAL,
    threes_per_game REAL,
    ftm_per_game REAL,
    fta_per_game REAL,
    ft_pct REAL,
    assists_per_game REAL,
    turnovers_per_game REAL,

    -- Defense
    points_allowed_per_game REAL,
    steals_per_game REAL,
    blocks_per_game REAL,
    rebounds_per_game REAL,

    -- Derived
    pace_estimate REAL,           -- estimated possessions per game
    off_rating_estimate REAL,     -- points per 100 possessions (estimated)
    def_rating_estimate REAL,     -- points allowed per 100 possessions (estimated)
    net_rating_estimate REAL,

    last_updated TEXT NOT NULL,
    UNIQUE(team, season)
)
"""

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
    win_pct REAL,

    -- Offense
    points_per_game REAL,
    fgm_per_game REAL,
    fga_per_game REAL,
    fg_pct REAL,
    threes_per_game REAL,
    assists_per_game REAL,
    turnovers_per_game REAL,
    ftm_per_game REAL,
    fta_per_game REAL,

    -- Defense
    points_allowed_per_game REAL,
    steals_per_game REAL,
    blocks_per_game REAL,
    rebounds_per_game REAL,

    -- Derived
    point_diff_avg REAL,
    pace_estimate REAL,
    off_rating_estimate REAL,
    def_rating_estimate REAL,
    net_rating_estimate REAL,

    -- Splits
    home_win_pct REAL,
    away_win_pct REAL,

    last_updated TEXT NOT NULL,
    UNIQUE(team, as_of_date, window)
)
"""


def ensure_tables(conn):
    """Create tables if they don't exist."""
    conn.execute(TEAM_STATS_SCHEMA)
    conn.execute(ROLLING_STATS_SCHEMA)
    conn.commit()


# ── Data aggregation ──────────────────────────────────────────────────────────

def get_team_games(conn, team, as_of_date=None, last_n=None, season_start=None):
    """Fetch game results for a team.

    Args:
        season_start: earliest date to include (e.g. '2025-10-01' for 2025-26).
                      Prevents mixing old-season data with current-season stats.
    """
    query = """
        SELECT game_date,
               CASE WHEN home_team = ? THEN 1 ELSE 0 END as is_home,
               CASE WHEN home_team = ? THEN home_score ELSE away_score END as team_score,
               CASE WHEN home_team = ? THEN away_score ELSE home_score END as opp_score
        FROM games
        WHERE (home_team = ? OR away_team = ?)
          AND home_score IS NOT NULL AND away_score IS NOT NULL
    """
    params = [team, team, team, team, team]

    if season_start:
        query += " AND game_date >= ?"
        params.append(season_start)

    if as_of_date:
        query += " AND game_date <= ?"
        params.append(as_of_date)

    query += " ORDER BY game_date DESC"

    if last_n:
        query += f" LIMIT {last_n}"

    cursor = conn.execute(query, params)
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, row)) for row in cursor.fetchall()]

    for g in rows:
        g["result"] = "W" if (g["team_score"] or 0) > (g["opp_score"] or 0) else "L"

    return rows


def get_team_player_aggregates(conn, team, as_of_date=None, last_n_games=None):
    """Aggregate player stats into team totals per game."""
    query = """
        SELECT game_date,
               SUM(points) as total_points,
               SUM(rebounds) as total_rebounds,
               SUM(assists) as total_assists,
               SUM(steals) as total_steals,
               SUM(blocks) as total_blocks,
               SUM(turnovers) as total_turnovers,
               SUM(threes_made) as total_threes,
               SUM(fga) as total_fga,
               SUM(fgm) as total_fgm,
               SUM(fta) as total_fta,
               SUM(ftm) as total_ftm,
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


def get_opponent_scoring(conn, team, as_of_date=None, last_n_games=None, season_start=None):
    """Get opponent scoring for defensive stats."""
    query = """
        SELECT game_date,
               CASE WHEN home_team = ? THEN away_score ELSE home_score END as opp_points
        FROM games
        WHERE (home_team = ? OR away_team = ?)
          AND home_score IS NOT NULL AND away_score IS NOT NULL
    """
    params = [team, team, team]

    if season_start:
        query += " AND game_date >= ?"
        params.append(season_start)

    if as_of_date:
        query += " AND game_date <= ?"
        params.append(as_of_date)

    query += " ORDER BY game_date DESC"

    if last_n_games:
        query += f" LIMIT {last_n_games}"

    cursor = conn.execute(query, params)
    return [r[1] for r in cursor.fetchall()]


# ── Stats calculation ─────────────────────────────────────────────────────────

def calculate_window_stats(games, player_aggs, opp_points_list):
    """Calculate aggregated stats from a window of games."""
    if not games:
        return None

    n = len(games)
    wins = sum(1 for g in games if g["result"] == "W")
    losses = n - wins

    home_games = [g for g in games if g["is_home"]]
    away_games = [g for g in games if not g["is_home"]]
    home_wins = sum(1 for g in home_games if g["result"] == "W")
    away_wins = sum(1 for g in away_games if g["result"] == "W")

    team_pts = sum(g["team_score"] or 0 for g in games)
    opp_pts = sum(opp_points_list[:n]) if opp_points_list else sum(g["opp_score"] or 0 for g in games)

    # Player aggregate averages
    total_fgm = total_fga = total_ftm = total_fta = 0
    total_assists = total_turnovers = total_threes = 0
    total_steals = total_blocks = total_rebounds = 0
    agg_n = 0

    for pa in (player_aggs or []):
        total_fgm += pa.get("total_fgm") or 0
        total_fga += pa.get("total_fga") or 0
        total_ftm += pa.get("total_ftm") or 0
        total_fta += pa.get("total_fta") or 0
        total_assists += pa.get("total_assists") or 0
        total_turnovers += pa.get("total_turnovers") or 0
        total_threes += pa.get("total_threes") or 0
        total_steals += pa.get("total_steals") or 0
        total_blocks += pa.get("total_blocks") or 0
        total_rebounds += pa.get("total_rebounds") or 0
        agg_n += 1

    an = max(agg_n, 1)

    # Estimate pace: possessions ~ FGA - ORB + TOV + 0.44*FTA (simplified)
    # Without ORB data, use: possessions ~ FGA + 0.44*FTA + TOV
    est_poss = (total_fga / an) + 0.44 * (total_fta / an) + (total_turnovers / an) if agg_n else None

    ppg = team_pts / n
    papg = opp_pts / n

    off_rtg = (ppg / est_poss * 100) if est_poss and est_poss > 0 else None
    def_rtg = (papg / est_poss * 100) if est_poss and est_poss > 0 else None
    net_rtg = (off_rtg - def_rtg) if off_rtg and def_rtg else None

    return {
        "games_played": n,
        "wins": wins,
        "losses": losses,
        "win_pct": round(wins / n, 4),
        "points_per_game": round(ppg, 2),
        "fgm_per_game": round(total_fgm / an, 2) if agg_n else None,
        "fga_per_game": round(total_fga / an, 2) if agg_n else None,
        "fg_pct": round(total_fgm / total_fga, 4) if total_fga else None,
        "threes_per_game": round(total_threes / an, 2) if agg_n else None,
        "assists_per_game": round(total_assists / an, 2) if agg_n else None,
        "turnovers_per_game": round(total_turnovers / an, 2) if agg_n else None,
        "ftm_per_game": round(total_ftm / an, 2) if agg_n else None,
        "fta_per_game": round(total_fta / an, 2) if agg_n else None,
        "ft_pct": round(total_ftm / total_fta, 4) if total_fta else None,
        "points_allowed_per_game": round(papg, 2),
        "steals_per_game": round(total_steals / an, 2) if agg_n else None,
        "blocks_per_game": round(total_blocks / an, 2) if agg_n else None,
        "rebounds_per_game": round(total_rebounds / an, 2) if agg_n else None,
        "point_diff_avg": round((team_pts - opp_pts) / n, 2),
        "pace_estimate": round(est_poss, 1) if est_poss else None,
        "off_rating_estimate": round(off_rtg, 1) if off_rtg else None,
        "def_rating_estimate": round(def_rtg, 1) if def_rtg else None,
        "net_rating_estimate": round(net_rtg, 1) if net_rtg else None,
        "home_win_pct": round(home_wins / len(home_games), 4) if home_games else None,
        "away_win_pct": round(away_wins / len(away_games), 4) if away_games else None,
    }


# ── Main update logic ────────────────────────────────────────────────────────

def update_team(conn, team, as_of_date=None):
    """Update all rolling windows for a team."""
    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")

    windows = {"L5": 5, "L10": 10, "L20": 20, "season": None}

    for window_name, last_n in windows.items():
        # Always scope to current season to avoid mixing old-season data.
        # L5/L10/L20 windows are already bounded by last_n, but season window
        # would otherwise pull in all historical games across multiple years.
        games = get_team_games(conn, team, as_of_date, last_n,
                               season_start=SEASON_START_DATE)
        player_aggs = get_team_player_aggregates(conn, team, as_of_date, last_n)
        opp_points = get_opponent_scoring(conn, team, as_of_date, last_n,
                                          season_start=SEASON_START_DATE)
        stats = calculate_window_stats(games, player_aggs, opp_points)

        if not stats:
            continue

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("""
            INSERT OR REPLACE INTO team_rolling_stats
            (team, as_of_date, window, games_played, wins, losses, win_pct,
             points_per_game, fgm_per_game, fga_per_game, fg_pct,
             threes_per_game, assists_per_game, turnovers_per_game,
             ftm_per_game, fta_per_game,
             points_allowed_per_game, steals_per_game, blocks_per_game, rebounds_per_game,
             point_diff_avg, pace_estimate, off_rating_estimate, def_rating_estimate, net_rating_estimate,
             home_win_pct, away_win_pct, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            team, as_of_date, window_name,
            stats["games_played"], stats["wins"], stats["losses"], stats["win_pct"],
            stats["points_per_game"], stats["fgm_per_game"], stats["fga_per_game"], stats["fg_pct"],
            stats["threes_per_game"], stats["assists_per_game"], stats["turnovers_per_game"],
            stats["ftm_per_game"], stats["fta_per_game"],
            stats["points_allowed_per_game"], stats["steals_per_game"],
            stats["blocks_per_game"], stats["rebounds_per_game"],
            stats["point_diff_avg"], stats["pace_estimate"],
            stats["off_rating_estimate"], stats["def_rating_estimate"], stats["net_rating_estimate"],
            stats["home_win_pct"], stats["away_win_pct"], now,
        ))

    conn.commit()


def update_season_totals(conn, team):
    """Update season-level team_stats table."""
    games = get_team_games(conn, team)
    player_aggs = get_team_player_aggregates(conn, team)
    opp_points = get_opponent_scoring(conn, team)
    stats = calculate_window_stats(games, player_aggs, opp_points)

    if not stats:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT OR REPLACE INTO team_stats
        (team, season, games_played, wins, losses,
         points_per_game, fgm_per_game, fga_per_game, fg_pct,
         threes_per_game, ftm_per_game, fta_per_game, ft_pct,
         assists_per_game, turnovers_per_game,
         points_allowed_per_game, steals_per_game, blocks_per_game, rebounds_per_game,
         pace_estimate, off_rating_estimate, def_rating_estimate, net_rating_estimate,
         last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        team, SEASON,
        stats["games_played"], stats["wins"], stats["losses"],
        stats["points_per_game"], stats["fgm_per_game"], stats["fga_per_game"], stats["fg_pct"],
        stats["threes_per_game"], stats["ftm_per_game"], stats["fta_per_game"], stats["ft_pct"],
        stats["assists_per_game"], stats["turnovers_per_game"],
        stats["points_allowed_per_game"], stats["steals_per_game"],
        stats["blocks_per_game"], stats["rebounds_per_game"],
        stats["pace_estimate"], stats["off_rating_estimate"],
        stats["def_rating_estimate"], stats["net_rating_estimate"],
        now,
    ))
    conn.commit()


def get_all_teams(conn):
    """Get all teams that have played games."""
    cursor = conn.execute("""
        SELECT DISTINCT team FROM (
            SELECT home_team as team FROM games WHERE home_score IS NOT NULL
            UNION
            SELECT away_team as team FROM games WHERE away_score IS NOT NULL
        ) ORDER BY team
    """)
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
        print("[NBA Team Stats] Cleared existing data for rebuild")

    print(f"[NBA Team Stats] Updating {len(teams)} teams...")

    for t in teams:
        update_team(conn, t)
        update_season_totals(conn, t)

    # Summary
    cursor = conn.execute("SELECT COUNT(*) FROM team_rolling_stats")
    rolling_count = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(*) FROM team_stats")
    season_count = cursor.fetchone()[0]

    print(f"[NBA Team Stats] Done: {rolling_count} rolling stat rows, {season_count} season rows")

    # Top teams by point differential
    cursor = conn.execute("""
        SELECT team, points_per_game, points_allowed_per_game, point_diff_avg, win_pct,
               pace_estimate, off_rating_estimate, net_rating_estimate
        FROM team_rolling_stats
        WHERE window = 'season'
        ORDER BY point_diff_avg DESC LIMIT 10
    """)
    print(f"\n{'Team':<6} {'PPG':>6} {'PAPG':>6} {'Diff':>6} {'Win%':>6} {'Pace':>6} {'ORtg':>6} {'Net':>6}")
    print("-" * 55)
    for row in cursor.fetchall():
        t, ppg, papg, diff, wpct, pace, ortg, net = row
        print(f"{t:<6} {ppg:>6.1f} {papg:>6.1f} {diff:>+6.1f} {wpct:>6.1%} "
              f"{pace or 0:>6.1f} {ortg or 0:>6.1f} {net or 0:>+6.1f}")

    conn.close()
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NBA Team Stats Collector")
    parser.add_argument("--team", type=str, help="Single team abbreviation")
    parser.add_argument("--rebuild", action="store_true", help="Full rebuild")
    args = parser.parse_args()

    run(team=args.team, rebuild=args.rebuild)
