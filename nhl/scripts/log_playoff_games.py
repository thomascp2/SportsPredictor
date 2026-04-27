"""
NHL Playoff Game Log Capture
==============================

Standalone script — no prediction logic, no orchestrator dependency.
Fetches completed game stats from NHL API and writes raw rows to player_game_logs.
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
import unicodedata
import requests
from datetime import datetime, timedelta, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from v2_config import DB_PATH

NHL_SCHEDULE_URL  = "https://api-web.nhle.com/v1/schedule/{date}"
NHL_BOXSCORE_URL  = "https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
_FINISHED_STATES  = {'OFF', 'FINAL'}


def _norm(name: str) -> str:
    n = unicodedata.normalize("NFKD", str(name))
    return "".join(c for c in n if not unicodedata.combining(c))


def _toi_to_seconds(toi: str) -> int:
    if not toi or ':' not in toi:
        return 0
    try:
        parts = toi.split(':')
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return 0


def _fetch(url: str, retries: int = 3) -> dict | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                return r.json()
            print(f"  [WARN] HTTP {r.status_code} for {url}")
        except Exception as e:
            print(f"  [WARN] Request error (attempt {attempt+1}): {e}")
        if attempt < retries - 1:
            time.sleep(5)
    return None


def _parse_players(boxscore: dict, game_id: str) -> list[dict]:
    """Extract player stats from NHL boxscore's playerByGameStats section."""
    players = []
    pbg = boxscore.get('playerByGameStats', {})

    for side, is_home in [('awayTeam', 0), ('homeTeam', 1)]:
        team_data = pbg.get(side, {})
        team_abbr = (boxscore.get('awayTeam', {}) if side == 'awayTeam'
                     else boxscore.get('homeTeam', {})).get('abbrev', '')
        opp_abbr  = (boxscore.get('homeTeam', {}) if side == 'awayTeam'
                     else boxscore.get('awayTeam', {})).get('abbrev', '')

        for position in ('forwards', 'defense'):
            for p in team_data.get(position, []):
                name = _norm(p.get('name', {}).get('default', ''))
                if not name:
                    continue

                goals          = p.get('goals', 0) or 0
                assists        = p.get('assists', 0) or 0
                points         = p.get('points', 0) or goals + assists
                shots          = p.get('sog', 0) or 0
                hits           = p.get('hits', 0) or 0
                blocked_shots  = p.get('blockedShots', 0) or 0
                plus_minus     = p.get('plusMinus', 0) or 0
                pim            = p.get('pim', 0) or 0
                toi_seconds    = _toi_to_seconds(p.get('toi', '0:00'))

                players.append({
                    'game_id':       game_id,
                    'player_name':   name,
                    'team':          team_abbr,
                    'opponent':      opp_abbr,
                    'is_home':       is_home,
                    'goals':         goals,
                    'assists':       assists,
                    'points':        points,
                    'shots_on_goal': shots,
                    'hits':          hits,
                    'blocked_shots': blocked_shots,
                    'plus_minus':    plus_minus,
                    'pim':           pim,
                    'toi_seconds':   toi_seconds,
                })

    return players


def _write_game_logs(conn: sqlite3.Connection, players: list[dict], game_date: str) -> int:
    saved = 0
    for p in players:
        shots  = p['shots_on_goal']
        points = p['points']
        try:
            conn.execute("""
                INSERT OR IGNORE INTO player_game_logs (
                    game_id, game_date, player_name, team, opponent, is_home,
                    goals, assists, points, shots_on_goal, toi_seconds,
                    plus_minus, pim, hits, blocked_shots, assists_total,
                    scored_1plus_points, scored_2plus_shots, scored_3plus_shots, scored_4plus_shots,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p['game_id'], game_date, p['player_name'], p['team'], p['opponent'], p['is_home'],
                p['goals'], p['assists'], points, shots, p['toi_seconds'],
                p['plus_minus'], p['pim'], p['hits'], p['blocked_shots'],
                p['assists'],   # assists_total mirrors assists
                1 if points >= 1 else 0,
                1 if shots >= 2 else 0,
                1 if shots >= 3 else 0,
                1 if shots >= 4 else 0,
                datetime.now().isoformat(),
            ))
            saved += 1
        except Exception as e:
            print(f"  [WARN] {p['player_name']}: {e}")
    return saved


def log_date(target_date: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    total = 0
    print(f"\n[NHL Playoff Logger] {target_date}")

    data = _fetch(NHL_SCHEDULE_URL.format(date=target_date))
    if not data:
        print("  No schedule data returned.")
        conn.close()
        return 0

    games = []
    for day in data.get('gameWeek', []):
        if day.get('date') == target_date:
            games = day.get('games', [])
            break

    if not games:
        print("  No games found.")
        conn.close()
        return 0

    for game in games:
        gid   = game.get('id')
        away  = game.get('awayTeam', {}).get('abbrev', '?')
        home  = game.get('homeTeam', {}).get('abbrev', '?')
        state = game.get('gameState', 'UNKNOWN')
        print(f"  {away} @ {home}  state={state}  id={gid}")

        if state not in _FINISHED_STATES:
            print("    [SKIP] game not finished")
            continue

        boxscore = _fetch(NHL_BOXSCORE_URL.format(game_id=gid))
        if not boxscore:
            print("    [WARN] no boxscore returned")
            continue

        players = _parse_players(boxscore, str(gid))
        saved   = _write_game_logs(conn, players, target_date)
        print(f"    {saved} player rows written")
        total += saved
        time.sleep(0.3)

    conn.commit()
    conn.close()
    print(f"[NHL Playoff Logger] Done. {total} total rows written for {target_date}")
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
