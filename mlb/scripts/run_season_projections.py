"""
MLB Season Projections — Batch Runner
======================================

Fetches all active MLB players from the Stats API, runs Marcel projections
for each one, and saves results to the season_projections table in the DB.

Run once at the start of each season (or after major trades).
Output is read by the Streamlit dashboard Season Props tab.

Usage:
    cd mlb
    python scripts/run_season_projections.py
    python scripts/run_season_projections.py --season 2026 --force
    python scripts/run_season_projections.py --team NYY   # single team
"""

import sys
import json
import sqlite3
import urllib.request
import urllib.parse
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import DB_PATH, MLB_API_BASE, MLB_API_TIMEOUT, SEASON, initialize_database
from season_projections import SeasonProjector

# PrizePicks-relevant season prop stats per player type
# These map to our projection keys
BATTER_SEASON_STATS = ['hr', 'k', 'tb', 'rbi', 'runs', 'hits', 'sb']
PITCHER_SEASON_STATS = ['k_total', 'bb_total', 'hits_allowed', 'er_total']

# Minimum projected PA / IP to bother storing
MIN_PA = 200
MIN_IP = 40

# Positions classified as pitchers
PITCHER_POSITIONS = {'P', 'SP', 'RP', 'CL'}


def fetch_all_active_players(season: str) -> List[Dict]:
    """
    Fetch all players on active MLB rosters for a given season.
    Returns list of {player_id, player_name, team, position, player_type}
    """
    all_players = []
    seen_ids = set()

    # Get all 30 team IDs first
    url = f"{MLB_API_BASE}/teams?sportId=1&season={season}"
    try:
        req = urllib.request.urlopen(url, timeout=MLB_API_TIMEOUT)
        data = json.loads(req.read())
        teams = data.get('teams', [])
    except Exception as e:
        print(f"[ERROR] Could not fetch teams: {e}")
        return []

    print(f"[Batch] Fetching rosters for {len(teams)} teams...")

    for team in teams:
        team_id   = team['id']
        team_abbr = team.get('abbreviation', '')
        time.sleep(0.1)   # gentle rate limiting

        try:
            url = (f"{MLB_API_BASE}/teams/{team_id}/roster"
                   f"?rosterType=active&season={season}"
                   f"&hydrate=person(fullName,birthDate,primaryPosition)")
            req = urllib.request.urlopen(url, timeout=MLB_API_TIMEOUT)
            roster = json.loads(req.read()).get('roster', [])
        except Exception:
            continue

        current_year = int(season)
        for entry in roster:
            person     = entry.get('person', {})
            pid        = person.get('id')
            name       = person.get('fullName', '')
            pos_code   = entry.get('position', {}).get('abbreviation', 'OF')
            birth_date = person.get('birthDate', '')

            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)

            # Calculate age from birth date already provided by the hydrated roster
            if birth_date:
                try:
                    age = current_year - int(birth_date[:4])
                except (ValueError, TypeError):
                    age = None
            else:
                age = None

            player_type = 'pitcher' if pos_code in PITCHER_POSITIONS else 'batter'
            all_players.append({
                'player_id':   pid,
                'player_name': name,
                'team':        team_abbr,
                'position':    pos_code,
                'player_type': player_type,
                'age':         age,
            })

    print(f"[Batch] Found {len(all_players)} active players "
          f"({sum(1 for p in all_players if p['player_type']=='pitcher')} P, "
          f"{sum(1 for p in all_players if p['player_type']=='batter')} B)")
    return all_players


def run_batch(season: str = SEASON, force: bool = False,
              team_filter: str = None, db_path: str = None) -> Dict:
    """
    Main batch function. Projects all active players and saves to DB.

    Args:
        season:      Season year string (e.g. '2026')
        force:       Overwrite existing projections if True
        team_filter: Only project one team (e.g. 'NYY') — useful for testing
        db_path:     Override DB path

    Returns:
        Summary dict
    """
    db_path = db_path or DB_PATH
    initialize_database(db_path)

    conn = sqlite3.connect(db_path)

    # Check existing projections
    existing = conn.execute(
        "SELECT COUNT(*) FROM season_projections WHERE season = ?", (season,)
    ).fetchone()[0]

    if existing > 0 and not force:
        print(f"[Batch] {existing} projections already exist for {season}. "
              f"Use --force to overwrite.")
        conn.close()
        return {'skipped': True, 'existing': existing}

    if force and existing > 0:
        conn.execute("DELETE FROM season_projections WHERE season = ?", (season,))
        conn.commit()
        print(f"[Batch] Cleared {existing} existing projections for {season}")

    projector  = SeasonProjector(db_path)
    players    = fetch_all_active_players(season)

    if team_filter:
        players = [p for p in players if p['team'].upper() == team_filter.upper()]
        print(f"[Batch] Filtered to {len(players)} players on {team_filter}")

    saved   = 0
    skipped = 0
    errors  = 0

    for i, player in enumerate(players):
        pname = player['player_name']
        pid   = player['player_id']
        team  = player['team']
        ptype = player['player_type']

        # Progress every 50 players
        if i % 50 == 0:
            pct = i / len(players) * 100
            print(f"[Batch] {i}/{len(players)} ({pct:.0f}%) — {pname} ({team})")

        try:
            if ptype == 'pitcher':
                proj = projector.project_pitcher(pname, player_id=pid, team=team)
                stats_to_save = PITCHER_SEASON_STATS
                min_scale = proj['projections'].get('ip_projected', 0)
                if min_scale < MIN_IP:
                    skipped += 1
                    continue
            else:
                proj = projector.project_batter(pname, player_id=pid, team=team)
                stats_to_save = BATTER_SEASON_STATS
                min_scale = proj['projections'].get('pa_projected', 0)
                if min_scale < MIN_PA:
                    skipped += 1
                    continue

            if not proj['projections'] or proj['seasons_used'] == 0:
                skipped += 1
                continue

            now = datetime.now().isoformat()
            rows = []
            for stat in stats_to_save:
                projection = proj['projections'].get(stat)
                if projection is None:
                    continue

                # Estimate std_dev for this stat
                STD_FACTORS = {
                    'hr': 0.22, 'k': 0.20, 'tb': 0.12, 'rbi': 0.18,
                    'runs': 0.16, 'hits': 0.10, 'sb': 0.35,
                    'k_total': 0.14, 'bb_total': 0.20,
                    'hits_allowed': 0.12, 'er_total': 0.22,
                }
                std_factor = STD_FACTORS.get(stat, 0.18)
                std_dev = round(max(projection * std_factor, 1.0), 1)

                # Age: prefer roster value (already fetched, reliable) over
                # the stats-API-derived value inside the projection dict.
                row_age = player.get('age') or proj.get('age')
                rows.append((
                    season, pname, pid, team, ptype,
                    stat, round(projection, 1), std_dev,
                    proj['confidence'], proj['seasons_used'],
                    row_age, proj['method'], now,
                ))

            if rows:
                conn.executemany('''
                    INSERT OR REPLACE INTO season_projections
                    (season, player_name, player_id, team, player_type,
                     stat, projection, std_dev, confidence, seasons_used,
                     age, method, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''', rows)
                saved += len(rows)

            # Gentle rate limiting — avoid hammering the API
            time.sleep(0.15)

        except Exception as e:
            print(f"[ERROR] {pname}: {e}")
            errors += 1

    conn.commit()
    conn.close()

    total_players = len(players) - skipped - errors
    print(f"\n[Batch] Complete!")
    print(f"  Players projected: {total_players}")
    print(f"  Stat rows saved:   {saved}")
    print(f"  Skipped (low PA/IP): {skipped}")
    print(f"  Errors:            {errors}")

    return {
        'season': season,
        'players': total_players,
        'saved': saved,
        'skipped': skipped,
        'errors': errors,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run MLB season projections for all players')
    parser.add_argument('--season', default=SEASON, help='Season year (default: current)')
    parser.add_argument('--force', action='store_true', help='Overwrite existing projections')
    parser.add_argument('--team',  help='Only project one team (e.g. NYY) — for testing')
    args = parser.parse_args()

    result = run_batch(season=args.season, force=args.force, team_filter=args.team)
    print(f"\nDone: {result}")
