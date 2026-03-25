#!/usr/bin/env python3
"""
Game Score Sync - Polls ESPN/NHL APIs and syncs live scores to Supabase
=======================================================================

Designed to run continuously during game hours, polling every 60 seconds.
Syncs to Supabase daily_games table for Realtime subscriptions from mobile app.

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

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

from sync.config import (
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
    GAME_POLL_INTERVAL_SEC, GAME_HOURS_START, GAME_HOURS_END
)


class GameSync:
    """Syncs live game scores from ESPN/NHL APIs to Supabase."""

    # ESPN API endpoints
    ESPN_NBA_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
    ESPN_NHL_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"

    def __init__(self):
        if not SUPABASE_AVAILABLE:
            raise RuntimeError("supabase-py not installed")
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("requests not installed")

        self.client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    def sync_scores(self, sport: str, game_date: Optional[str] = None) -> Dict:
        """Fetch and sync live scores for a sport."""
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

        # Upsert to Supabase
        synced = 0
        for game in games:
            game['game_date'] = game_date
            game['sport'] = sport_upper
            try:
                self.client.table('daily_games').upsert(
                    game,
                    on_conflict='game_date,sport,game_id'
                ).execute()
                synced += 1
            except Exception as e:
                print(f"[GAME SYNC ERROR] {game.get('game_id')}: {e}")

        # Lock props for games that have started
        live_games = [g for g in games if g.get('status') in ('live', 'final')]
        if live_games:
            self._lock_started_games(sport_upper, game_date, live_games)

        print(f"[GAME SYNC] {sport_upper}: {synced}/{len(games)} games synced "
              f"({sum(1 for g in games if g['status'] == 'live')} live)")

        return {'synced': synced, 'total': len(games), 'sport': sport_upper}

    def _fetch_espn_nba(self, game_date: str) -> List[Dict]:
        """Fetch NBA scores from ESPN API."""
        try:
            # ESPN date format: YYYYMMDD
            espn_date = game_date.replace('-', '')
            resp = requests.get(
                self.ESPN_NBA_URL,
                params={'dates': espn_date},
                timeout=10
            )
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
                    'home_score': int(home.get('score', 0)),
                    'away_score': int(away.get('score', 0)),
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
            resp = requests.get(
                self.ESPN_NHL_URL,
                params={'dates': espn_date},
                timeout=10
            )
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
                    'home_score': int(home.get('score', 0)),
                    'away_score': int(away.get('score', 0)),
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
        """Extract broadcast info from ESPN competition data."""
        broadcasts = competition.get('broadcasts', [])
        if broadcasts:
            names = []
            for b in broadcasts:
                for n in b.get('names', []):
                    names.append(n)
            return ', '.join(names[:2])
        return ''

    def _lock_started_games(self, sport: str, game_date: str, live_games: list):
        """Lock props for games that have started (no more picks allowed)."""
        for game in live_games:
            home = game.get('home_team', '')
            away = game.get('away_team', '')
            if not home or not away:
                continue
            try:
                # Lock props where team matches either home or away
                self.client.table('daily_props').update({
                    'status': 'locked'
                }).eq('game_date', game_date).eq('sport', sport).eq(
                    'status', 'open'
                ).or_(f"team.eq.{home},team.eq.{away}").execute()
            except Exception as e:
                # Non-critical, log and continue
                pass

    def run_continuous(self, sports: List[str]):
        """Run continuous polling loop during game hours."""
        print(f"[GAME SYNC] Starting continuous sync for {', '.join(s.upper() for s in sports)}")
        print(f"[GAME SYNC] Polling every {GAME_POLL_INTERVAL_SEC}s")

        while True:
            hour = datetime.now().hour

            # Only poll during game hours (11am - 2am ET)
            is_game_hours = hour >= GAME_HOURS_START or hour < GAME_HOURS_END

            if is_game_hours:
                for sport in sports:
                    try:
                        self.sync_scores(sport)
                    except Exception as e:
                        print(f"[GAME SYNC ERROR] {sport.upper()}: {e}")

            time.sleep(GAME_POLL_INTERVAL_SEC)


def main():
    parser = argparse.ArgumentParser(description='Sync live game scores to Supabase')
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
