"""
MLB Team Stats Collector — Builds rolling team profiles from game data.

MLB has unique considerations:
    - Starting pitcher dominates game variance (~40%)
    - Park factors matter enormously (Coors vs Oracle)
    - Bullpen usage over recent days predicts fatigue
    - Weather affects scoring (already have weather_client.py)

Sources:
    1. Local games table
    2. Local player_game_logs (once populated)
    3. MLB Stats API (statsapi.mlb.com) for team-level stats

Usage:
    python team_stats_collector.py                # Update all teams
    python team_stats_collector.py --team NYY     # Single team
    python team_stats_collector.py --rebuild      # Full rebuild
"""

import sqlite3
import os
import sys
import json
import argparse
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    from mlb_config import DB_PATH
except ImportError:
    DB_PATH = os.path.join(SCRIPT_DIR, "..", "database", "mlb_predictions.db")

SEASON = "2026"

# MLB Stats API
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

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
    runs_per_game REAL,
    batting_avg REAL,
    obp REAL,
    slg REAL,
    ops REAL,
    hr_per_game REAL,
    k_rate_batting REAL,
    bb_rate_batting REAL,
    sb_per_game REAL,

    -- Pitching
    team_era REAL,
    team_whip REAL,
    k_per_9 REAL,
    bb_per_9 REAL,
    hr_per_9 REAL,
    bullpen_era REAL,

    -- Defense
    runs_allowed_per_game REAL,

    -- Derived
    run_diff_per_game REAL,
    pythagorean_win_pct REAL,     -- Expected W% from runs scored/allowed

    last_updated TEXT NOT NULL,
    UNIQUE(team, season)
)
"""

ROLLING_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_rolling_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    window TEXT NOT NULL,          -- 'L5', 'L10', 'L20', 'L30', 'season'

    -- Record
    games_played INTEGER,
    wins INTEGER,
    losses INTEGER,
    win_pct REAL,

    -- Offense
    runs_per_game REAL,
    hits_per_game REAL,
    hr_per_game REAL,
    sb_per_game REAL,
    k_per_game_batting REAL,
    bb_per_game_batting REAL,

    -- Pitching / Defense
    runs_allowed_per_game REAL,
    era_estimate REAL,

    -- Derived
    run_diff_per_game REAL,
    pythagorean_win_pct REAL,

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


# ── Data from games table ────────────────────────────────────────────────────

def get_team_games(conn, team, as_of_date=None, last_n=None):
    """Fetch game results for a team from games table."""
    # Check if games table exists and has the right columns
    cursor = conn.execute("SELECT sql FROM sqlite_master WHERE name='games' AND type='table'")
    schema_row = cursor.fetchone()
    if not schema_row:
        return []

    schema = schema_row[0]

    # MLB games table may have different column names
    # Try common patterns
    if "home_team" in schema:
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
    else:
        return []

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
    """Aggregate player stats per game from player_game_logs."""
    # Check if table has data
    cursor = conn.execute("SELECT COUNT(*) FROM player_game_logs WHERE team = ?", (team,))
    if cursor.fetchone()[0] == 0:
        return []

    query = """
        SELECT game_date,
               SUM(CASE WHEN player_type = 'batter' THEN hits ELSE 0 END) as total_hits,
               SUM(CASE WHEN player_type = 'batter' THEN home_runs ELSE 0 END) as total_hr,
               SUM(CASE WHEN player_type = 'batter' THEN rbis ELSE 0 END) as total_rbi,
               SUM(CASE WHEN player_type = 'batter' THEN runs ELSE 0 END) as total_runs,
               SUM(CASE WHEN player_type = 'batter' THEN stolen_bases ELSE 0 END) as total_sb,
               SUM(CASE WHEN player_type = 'batter' THEN strikeouts_batter ELSE 0 END) as total_k_batting,
               SUM(CASE WHEN player_type = 'batter' THEN walks_drawn ELSE 0 END) as total_bb_batting,
               SUM(CASE WHEN player_type = 'pitcher' THEN strikeouts_pitched ELSE 0 END) as total_k_pitching,
               SUM(CASE WHEN player_type = 'pitcher' THEN earned_runs ELSE 0 END) as total_er,
               SUM(CASE WHEN player_type = 'pitcher' THEN walks_allowed ELSE 0 END) as total_bb_pitching,
               SUM(CASE WHEN player_type = 'pitcher' THEN hits_allowed ELSE 0 END) as total_hits_allowed
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

def pythagorean_win_pct(runs_scored, runs_allowed, exponent=1.83):
    """
    Bill James Pythagorean expectation.
    MLB uses exponent ~1.83 (not 2.0 as originally proposed).
    """
    if runs_scored <= 0 or runs_allowed <= 0:
        return 0.5
    rs_exp = runs_scored ** exponent
    ra_exp = runs_allowed ** exponent
    return round(rs_exp / (rs_exp + ra_exp), 4)


def calculate_window_stats(games, player_aggs):
    """Calculate aggregated stats from a window of games."""
    if not games:
        return None

    n = len(games)
    wins = sum(1 for g in games if g["result"] == "W")
    losses = n - wins

    total_rs = sum(g["team_score"] or 0 for g in games)
    total_ra = sum(g["opp_score"] or 0 for g in games)

    home_games = [g for g in games if g["is_home"]]
    away_games = [g for g in games if not g["is_home"]]
    home_wins = sum(1 for g in home_games if g["result"] == "W")
    away_wins = sum(1 for g in away_games if g["result"] == "W")

    rpg = total_rs / n
    rapg = total_ra / n

    # Player aggregates (if available)
    total_hits = total_hr = total_sb = total_k_bat = total_bb_bat = 0
    total_er = 0
    agg_n = 0

    for pa in (player_aggs or []):
        total_hits += pa.get("total_hits") or 0
        total_hr += pa.get("total_hr") or 0
        total_sb += pa.get("total_sb") or 0
        total_k_bat += pa.get("total_k_batting") or 0
        total_bb_bat += pa.get("total_bb_batting") or 0
        total_er += pa.get("total_er") or 0
        agg_n += 1

    an = max(agg_n, 1)

    # ERA estimate: earned_runs / innings * 9. Without innings, use runs_allowed as proxy.
    era_est = round(rapg * 9 / 9, 2) if rapg else None  # Simplified — RA/9

    return {
        "games_played": n,
        "wins": wins,
        "losses": losses,
        "win_pct": round(wins / n, 4),
        "runs_per_game": round(rpg, 2),
        "runs_allowed_per_game": round(rapg, 2),
        "run_diff_per_game": round((total_rs - total_ra) / n, 2),
        "hits_per_game": round(total_hits / an, 2) if agg_n else None,
        "hr_per_game": round(total_hr / an, 2) if agg_n else None,
        "sb_per_game": round(total_sb / an, 2) if agg_n else None,
        "k_per_game_batting": round(total_k_bat / an, 2) if agg_n else None,
        "bb_per_game_batting": round(total_bb_bat / an, 2) if agg_n else None,
        "era_estimate": era_est,
        "pythagorean_win_pct": pythagorean_win_pct(total_rs, total_ra),
        "home_win_pct": round(home_wins / len(home_games), 4) if home_games else None,
        "away_win_pct": round(away_wins / len(away_games), 4) if away_games else None,
    }


# ── MLB API fetch (fallback when no local data) ──────────────────────────────

def fetch_team_standings_api():
    """Fetch current standings from MLB Stats API."""
    import urllib.request

    url = f"{MLB_API_BASE}/standings?leagueId=103,104&season={SEASON}"
    headers = {"User-Agent": "FreePicks/1.0"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        teams = {}
        for record_group in data.get("records", []):
            for tr in record_group.get("teamRecords", []):
                abbr = tr.get("team", {}).get("abbreviation", "")
                teams[abbr] = {
                    "wins": tr.get("wins", 0),
                    "losses": tr.get("losses", 0),
                    "win_pct": float(tr.get("winningPercentage", "0.500")),
                    "runs_scored": tr.get("runsScored", 0),
                    "runs_allowed": tr.get("runsAllowed", 0),
                    "games_played": tr.get("gamesPlayed", 0),
                }
        return teams
    except Exception as e:
        print(f"[MLB Team Stats] API fetch failed: {e}")
        return {}


# ── Main update logic ────────────────────────────────────────────────────────

def update_team(conn, team, as_of_date=None):
    """Update all rolling windows for a team."""
    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")

    # MLB has longer seasons — add L30 window
    windows = {"L5": 5, "L10": 10, "L20": 20, "L30": 30, "season": None}

    for window_name, last_n in windows.items():
        games = get_team_games(conn, team, as_of_date, last_n)
        player_aggs = get_team_player_aggregates(conn, team, as_of_date, last_n)
        stats = calculate_window_stats(games, player_aggs)

        if not stats:
            continue

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("""
            INSERT OR REPLACE INTO team_rolling_stats
            (team, as_of_date, window, games_played, wins, losses, win_pct,
             runs_per_game, hits_per_game, hr_per_game, sb_per_game,
             k_per_game_batting, bb_per_game_batting,
             runs_allowed_per_game, era_estimate,
             run_diff_per_game, pythagorean_win_pct,
             home_win_pct, away_win_pct, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            team, as_of_date, window_name,
            stats["games_played"], stats["wins"], stats["losses"], stats["win_pct"],
            stats["runs_per_game"], stats["hits_per_game"], stats["hr_per_game"],
            stats["sb_per_game"], stats["k_per_game_batting"], stats["bb_per_game_batting"],
            stats["runs_allowed_per_game"], stats["era_estimate"],
            stats["run_diff_per_game"], stats["pythagorean_win_pct"],
            stats["home_win_pct"], stats["away_win_pct"], now,
        ))

    conn.commit()


def get_all_teams(conn):
    """Get all teams from games table."""
    try:
        cursor = conn.execute("""
            SELECT DISTINCT team FROM (
                SELECT home_team as team FROM games WHERE home_score IS NOT NULL
                UNION
                SELECT away_team as team FROM games WHERE away_score IS NOT NULL
            ) ORDER BY team
        """)
        return [r[0] for r in cursor.fetchall()]
    except Exception:
        return []


def run(team=None, rebuild=False):
    """Main entry point."""
    conn = sqlite3.connect(DB_PATH)
    ensure_tables(conn)

    teams = [team] if team else get_all_teams(conn)

    if not teams:
        print("[MLB Team Stats] No game data yet. Attempting API fetch...")
        api_data = fetch_team_standings_api()
        if api_data:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for t, data in api_data.items():
                gp = data["games_played"]
                if gp == 0:
                    continue
                rpg = data["runs_scored"] / gp if gp else 0
                rapg = data["runs_allowed"] / gp if gp else 0
                conn.execute("""
                    INSERT OR REPLACE INTO team_stats
                    (team, season, games_played, wins, losses,
                     runs_per_game, runs_allowed_per_game, run_diff_per_game,
                     pythagorean_win_pct, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    t, SEASON, gp, data["wins"], data["losses"],
                    round(rpg, 2), round(rapg, 2), round(rpg - rapg, 2),
                    pythagorean_win_pct(data["runs_scored"], data["runs_allowed"]),
                    now,
                ))
            conn.commit()
            cursor = conn.execute("SELECT COUNT(*) FROM team_stats")
            print(f"[MLB Team Stats] Loaded {cursor.fetchone()[0]} teams from API")
        else:
            print("[MLB Team Stats] No data available (season may not have started)")
        conn.close()
        return True

    if rebuild:
        conn.execute("DELETE FROM team_rolling_stats")
        conn.execute("DELETE FROM team_stats")
        conn.commit()
        print("[MLB Team Stats] Cleared existing data for rebuild")

    print(f"[MLB Team Stats] Updating {len(teams)} teams...")

    for t in teams:
        update_team(conn, t)

    cursor = conn.execute("SELECT COUNT(*) FROM team_rolling_stats")
    rolling_count = cursor.fetchone()[0]
    print(f"[MLB Team Stats] Done: {rolling_count} rolling stat rows")

    # Top teams
    cursor = conn.execute("""
        SELECT team, runs_per_game, runs_allowed_per_game, run_diff_per_game,
               win_pct, pythagorean_win_pct
        FROM team_rolling_stats
        WHERE window = 'season'
        ORDER BY run_diff_per_game DESC LIMIT 10
    """)
    rows = cursor.fetchall()
    if rows:
        print(f"\n{'Team':<6} {'R/G':>6} {'RA/G':>6} {'Diff':>6} {'Win%':>6} {'Pyth':>6}")
        print("-" * 40)
        for row in rows:
            t, rpg, rapg, diff, wpct, pyth = row
            print(f"{t:<6} {rpg or 0:>6.2f} {rapg or 0:>6.2f} {diff or 0:>+6.2f} "
                  f"{wpct or 0:>6.1%} {pyth or 0:>6.1%}")

    conn.close()
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLB Team Stats Collector")
    parser.add_argument("--team", type=str, help="Single team abbreviation")
    parser.add_argument("--rebuild", action="store_true", help="Full rebuild")
    args = parser.parse_args()

    run(team=args.team, rebuild=args.rebuild)
