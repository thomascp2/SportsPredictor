#!/usr/bin/env python3
"""
Game Score Sync - Polls ESPN APIs and syncs live scores to Turso
================================================================

Fetches NBA/NHL scores from ESPN scoreboard API and writes them to the
game_scores table in each sport's Turso database. Runs continuously during
game hours, polling every 60 seconds.

Usage:
    python -m sync.game_sync --sport nba          # Poll NBA scores
    python -m sync.game_sync --sport all --once    # Single sync, both sports
    python -m sync.game_sync --sport all           # Continuous polling
"""

import os
import sys
import time
import json
import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from sync.config import GAME_POLL_INTERVAL_SEC, GAME_HOURS_START, GAME_HOURS_END

# Turso config per sport (mirrors turso_sync.py SPORT_CONFIG)
_TURSO_SPORT_CFG = {
    'nba': ('TURSO_NBA_URL', 'TURSO_NBA_TOKEN'),
    'nhl': ('TURSO_NHL_URL', 'TURSO_NHL_TOKEN'),
}

GAME_SCORES_DDL = '''
CREATE TABLE IF NOT EXISTS game_scores (
    game_date  TEXT NOT NULL,
    sport      TEXT NOT NULL,
    game_id    TEXT NOT NULL,
    home_team  TEXT,
    away_team  TEXT,
    home_score INTEGER,
    away_score INTEGER,
    status     TEXT,
    period     TEXT,
    clock      TEXT,
    start_time TEXT,
    broadcast  TEXT,
    PRIMARY KEY (game_date, sport, game_id)
)
'''

COLS = ['game_date', 'sport', 'game_id', 'home_team', 'away_team',
        'home_score', 'away_score', 'status', 'period', 'clock',
        'start_time', 'broadcast']


def _turso_pipeline(sport: str, statements: list) -> bool:
    """Send a batch of SQL statements to Turso via HTTP pipeline. Returns True on success."""
    url_env, tok_env = _TURSO_SPORT_CFG.get(sport.lower(), (None, None))
    if not url_env:
        return False
    base_url = os.getenv(url_env, '').replace('libsql://', 'https://')
    token = os.getenv(tok_env, '')
    if not base_url or not token:
        print(f"[GAME SYNC] Turso env vars missing for {sport.upper()} — skipping.")
        return False

    requests_list = [{'type': 'execute', 'stmt': s} for s in statements]
    requests_list.append({'type': 'close'})
    payload = {'requests': requests_list}
    try:
        resp = requests.post(
            base_url.rstrip('/') + '/v2/pipeline',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json=payload, timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[GAME SYNC ERROR] Turso pipeline {sport.upper()}: {e}")
        return False


def _ensure_table(sport: str):
    """Create game_scores table in Turso if it doesn't exist."""
    _turso_pipeline(sport, [{'sql': GAME_SCORES_DDL}])


class GameSync:
    """Syncs live game scores from ESPN APIs to Turso game_scores table."""

    ESPN_NBA_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
    ESPN_NHL_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"

    def __init__(self):
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("requests not installed")

    def sync_scores(self, sport: str, game_date: Optional[str] = None) -> Dict:
        """Fetch ESPN scores for a sport and upsert to Turso game_scores."""
        if game_date is None:
            game_date = date.today().isoformat()

        sport_upper = sport.upper()

        if sport_upper == 'NBA':
            games = self._fetch_espn_nba(game_date)
        elif sport_upper == 'NHL':
            games = self._fetch_espn_nhl(game_date)
        else:
            return {'error': f'Unknown sport: {sport}'}

        if not games:
            return {'synced': 0, 'sport': sport_upper, 'date': game_date}

        _ensure_table(sport)

        # Build upsert statements
        col_list = ', '.join(COLS)
        placeholders = ', '.join(['?' for _ in COLS])
        upsert_sql = f'INSERT OR REPLACE INTO game_scores ({col_list}) VALUES ({placeholders})'

        statements = []
        for g in games:
            g['game_date'] = game_date
            g['sport'] = sport_upper
            vals = [g.get(c) for c in COLS]
            statements.append({'sql': upsert_sql, 'args': [
                {'type': 'text' if isinstance(v, str) else 'integer' if isinstance(v, int) else 'null',
                 'value': str(v) if v is not None else None}
                for v in vals
            ]})

        success = _turso_pipeline(sport, statements)
        synced = len(games) if success else 0

        live = sum(1 for g in games if g.get('status') == 'live')
        print(f"[GAME SYNC] {sport_upper}: {synced}/{len(games)} games synced ({live} live)")
        return {'synced': synced, 'total': len(games), 'sport': sport_upper}

    def _fetch_espn_nba(self, game_date: str) -> List[Dict]:
        """Fetch NBA scores from ESPN API."""
        try:
            espn_date = game_date.replace('-', '')
            resp = requests.get(self.ESPN_NBA_URL, params={'dates': espn_date}, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            games = []
            for event in data.get('events', []):
                competition = event.get('competitions', [{}])[0]
                competitors = competition.get('competitors', [])
                home = next((c for c in competitors if c.get('homeAway') == 'home'), {})
                away = next((c for c in competitors if c.get('homeAway') == 'away'), {})
                status_obj = event.get('status', {})
                status_type = status_obj.get('type', {}).get('name', '')
                if status_type == 'STATUS_IN_PROGRESS':
                    status = 'live'
                elif status_type == 'STATUS_FINAL':
                    status = 'final'
                else:
                    status = 'scheduled'
                period = status_obj.get('period', 0)
                clock = status_obj.get('displayClock', '')
                games.append({
                    'game_id': event.get('id', ''),
                    'home_team': home.get('team', {}).get('abbreviation', ''),
                    'away_team': away.get('team', {}).get('abbreviation', ''),
                    'home_score': int(home.get('score', 0) or 0),
                    'away_score': int(away.get('score', 0) or 0),
                    'status': status,
                    'period': f"Q{period}" if period and status == 'live' else str(period),
                    'clock': clock,
                    'start_time': event.get('date', ''),
                    'broadcast': self._get_broadcast(competition),
                })
            return games
        except Exception as e:
            print(f"[GAME SYNC ERROR] ESPN NBA fetch failed: {e}")
            return []

    def _fetch_espn_nhl(self, game_date: str) -> List[Dict]:
        """Fetch NHL scores from ESPN API."""
        try:
            espn_date = game_date.replace('-', '')
            resp = requests.get(self.ESPN_NHL_URL, params={'dates': espn_date}, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            games = []
            for event in data.get('events', []):
                competition = event.get('competitions', [{}])[0]
                competitors = competition.get('competitors', [])
                home = next((c for c in competitors if c.get('homeAway') == 'home'), {})
                away = next((c for c in competitors if c.get('homeAway') == 'away'), {})
                status_obj = event.get('status', {})
                status_type = status_obj.get('type', {}).get('name', '')
                if status_type == 'STATUS_IN_PROGRESS':
                    status = 'live'
                elif status_type == 'STATUS_FINAL':
                    status = 'final'
                else:
                    status = 'scheduled'
                period = status_obj.get('period', 0)
                clock = status_obj.get('displayClock', '')
                games.append({
                    'game_id': event.get('id', ''),
                    'home_team': home.get('team', {}).get('abbreviation', ''),
                    'away_team': away.get('team', {}).get('abbreviation', ''),
                    'home_score': int(home.get('score', 0) or 0),
                    'away_score': int(away.get('score', 0) or 0),
                    'status': status,
                    'period': f"P{period}" if period and status == 'live' else str(period),
                    'clock': clock,
                    'start_time': event.get('date', ''),
                    'broadcast': self._get_broadcast(competition),
                })
            return games
        except Exception as e:
            print(f"[GAME SYNC ERROR] ESPN NHL fetch failed: {e}")
            return []

    def _get_broadcast(self, competition: Dict) -> str:
        broadcasts = competition.get('broadcasts', [])
        if broadcasts:
            names = []
            for b in broadcasts:
                for n in b.get('names', []):
                    names.append(n)
            return ', '.join(names[:2])
        return ''

    def run_continuous(self, sports: List[str]):
        """Run continuous polling loop during game hours."""
        print(f"[GAME SYNC] Starting continuous sync for {', '.join(s.upper() for s in sports)}")
        print(f"[GAME SYNC] Polling every {GAME_POLL_INTERVAL_SEC}s -> Turso game_scores")

        while True:
            hour = datetime.now().hour
            is_game_hours = hour >= GAME_HOURS_START or hour < GAME_HOURS_END
            if is_game_hours:
                for sport in sports:
                    try:
                        self.sync_scores(sport)
                    except Exception as e:
                        print(f"[GAME SYNC ERROR] {sport.upper()}: {e}")
            time.sleep(GAME_POLL_INTERVAL_SEC)


def main():
    parser = argparse.ArgumentParser(description='Sync live game scores to Turso')
    parser.add_argument('--sport', choices=['nba', 'nhl', 'all'], default='all')
    parser.add_argument('--once', action='store_true', help='Single sync then exit')
    parser.add_argument('--date', help='Date to sync (YYYY-MM-DD)')
    args = parser.parse_args()

    syncer = GameSync()
    sports = ['nba', 'nhl'] if args.sport == 'all' else [args.sport]

    if args.once:
        for sport in sports:
            syncer.sync_scores(sport, args.date)
    else:
        syncer.run_continuous(sports)


if __name__ == '__main__':
    main()
