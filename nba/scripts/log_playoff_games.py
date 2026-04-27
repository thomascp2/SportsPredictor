"""
NBA Playoff Game Log Capture
=============================

Standalone script — no prediction logic, no orchestrator dependency.
Fetches completed game stats from ESPN and writes raw rows to player_game_logs.
Designed to run daily via Task Scheduler during playoffs to build a historical dataset
for future standalone playoff stat models.

Usage:
    python log_playoff_games.py               # defaults to yesterday
    python log_playoff_games.py 2026-04-26    # specific date
    python log_playoff_games.py --backfill 2026-04-19  # fill from start of playoffs
"""

import sqlite3
import sys
import time
from datetime import datetime, timedelta, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from nba_config import DB_PATH
from espn_nba_api import ESPNNBAApi


def _is_finished(game: dict) -> bool:
    status = game.get('status', '')
    return 'Final' in status or status in ('STATUS_FINAL', 'completed')


def _write_game_logs(conn: sqlite3.Connection, game: dict, players: list, game_date: str) -> int:
    home_abbr = game.get('home_team', '')
    away_abbr = game.get('away_team', '')
    game_id   = str(game.get('game_id', ''))
    saved = 0

    for p in players:
        if not p.get('player_name'):
            continue

        team    = p.get('team', '')
        is_home = team == home_abbr
        opp     = away_abbr if is_home else home_abbr
        home_away = 'home' if is_home else 'away'

        pts  = p.get('points', 0) or 0
        reb  = p.get('rebounds', 0) or 0
        ast  = p.get('assists', 0) or 0
        stl  = p.get('steals', 0) or 0
        blk  = p.get('blocks', 0) or 0
        tov  = p.get('turnovers', 0) or 0
        fg3m = p.get('threes_made', 0) or 0
        fga  = p.get('fga', 0) or 0
        fgm  = p.get('fgm', 0) or 0
        fta  = p.get('fta', 0) or 0
        ftm  = p.get('ftm', 0) or 0
        pm   = p.get('plus_minus', 0) or 0
        mins = p.get('minutes', 0.0) or 0.0

        pra    = pts + reb + ast
        stocks = stl + blk

        try:
            conn.execute("""
                INSERT OR IGNORE INTO player_game_logs (
                    game_id, game_date, player_name, team, opponent, home_away,
                    minutes, points, rebounds, assists, steals, blocks, turnovers,
                    threes_made, fga, fgm, fta, ftm, plus_minus, pra, stocks, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game_id, game_date, p['player_name'], team, opp, home_away,
                mins, pts, reb, ast, stl, blk, tov,
                fg3m, fga, fgm, fta, ftm, pm, pra, stocks,
                datetime.now().isoformat(),
            ))
            saved += 1
        except Exception as e:
            print(f"  [WARN] {p['player_name']}: {e}")

    return saved


def log_date(target_date: str) -> int:
    api  = ESPNNBAApi()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    total = 0
    print(f"\n[NBA Playoff Logger] {target_date}")

    games = api.get_scoreboard(target_date)
    if not games:
        print("  No games found.")
        conn.close()
        return 0

    for game in games:
        home = game.get('home_team', '?')
        away = game.get('away_team', '?')
        gid  = game.get('game_id', '')
        status = game.get('status', 'unknown')
        print(f"  {away} @ {home}  status={status}  id={gid}")

        if not _is_finished(game):
            print("    [SKIP] game not finished")
            continue

        players = api.get_boxscore(gid)
        if not players:
            print("    [WARN] no boxscore returned")
            continue

        saved = _write_game_logs(conn, game, players, target_date)
        print(f"    {saved} player rows written")
        total += saved
        time.sleep(0.3)

    conn.commit()
    conn.close()
    print(f"[NBA Playoff Logger] Done. {total} total rows written for {target_date}")
    return total


def main():
    args = sys.argv[1:]

    if '--backfill' in args:
        idx   = args.index('--backfill')
        start = date.fromisoformat(args[idx + 1])
        end   = date.today() - timedelta(days=1)
        d = start
        while d <= end:
            log_date(d.isoformat())
            d += timedelta(days=1)
    elif args:
        log_date(args[0])
    else:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        log_date(yesterday)


if __name__ == '__main__':
    main()
