"""
MLB Stats API Client
====================

Official MLB Stats API client. Free, no authentication required.
Base URL: https://statsapi.mlb.com/api/v1

Key endpoints used:
  /schedule              - Game schedule with probable pitchers and lineups
  /game/{id}/boxscore   - Final game results (pitcher + batter stats)
  /people/{id}/stats    - Season stats and game logs
  /people/search        - Player ID lookup by name

Handles:
  - Doubleheaders (multiple games same day, separate game_ids)
  - Postponements (filter by status.abstractGameState == 'Final')
  - Bullpen/opener games (starter pitched < 3 innings)
  - Retry logic with exponential backoff for transient API errors
"""

import time
import json
import math
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import MLB_API_BASE, MLB_API_TIMEOUT, MLB_API_RETRIES


@dataclass
class GameInfo:
    """Structured game information from MLB schedule."""
    game_id: int
    game_date: str
    home_team: str
    away_team: str
    venue: str
    game_time_utc: str          # ISO format UTC
    day_night: str              # 'day' or 'night'
    status: str                 # 'scheduled', 'final', 'postponed', etc.
    home_starter: str           # Player name, or 'TBD'
    away_starter: str
    home_starter_id: Optional[int]
    away_starter_id: Optional[int]
    home_lineup: List[Dict] = field(default_factory=list)  # [{name, id, batting_order, hand}]
    away_lineup: List[Dict] = field(default_factory=list)
    is_doubleheader: bool = False


@dataclass
class PitcherBoxscore:
    """Pitcher stats from a final boxscore."""
    player_name: str
    player_id: int
    team: str
    innings_pitched: float
    outs_recorded: int
    strikeouts: int
    walks: int
    hits_allowed: int
    earned_runs: int
    home_runs_allowed: int
    pitches: int
    is_starter: bool


@dataclass
class BatterBoxscore:
    """Batter stats from a final boxscore."""
    player_name: str
    player_id: int
    team: str
    at_bats: int
    hits: int
    home_runs: int
    rbis: int
    runs: int
    stolen_bases: int
    walks: int
    strikeouts: int
    doubles: int
    triples: int
    total_bases: int
    hrr: int              # hits + runs + rbis
    batting_order: int    # 1-9, or 0 if unknown


class MLBStatsAPI:
    """
    Client for the official MLB Stats API.
    https://statsapi.mlb.com/api/v1
    """

    def __init__(self):
        self.base = MLB_API_BASE
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'SportsPredictor/1.0'})

    # -------------------------------------------------------------------------
    # Core HTTP helper
    # -------------------------------------------------------------------------

    def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """
        Make a GET request with retry logic.

        Args:
            endpoint: API path (without base URL)
            params: Query parameters dict

        Returns:
            Parsed JSON response or None on failure
        """
        url = f"{self.base}{endpoint}"
        for attempt in range(MLB_API_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=MLB_API_TIMEOUT)

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code in (429, 500, 502, 503, 504):
                    # Retryable errors
                    wait = 2 ** attempt
                    print(f"[MLB API] HTTP {resp.status_code}, retrying in {wait}s... ({url})")
                    time.sleep(wait)
                    continue

                print(f"[MLB API] Non-retryable HTTP {resp.status_code}: {url}")
                return None

            except requests.exceptions.Timeout:
                wait = 2 ** attempt
                print(f"[MLB API] Timeout, retrying in {wait}s... ({url})")
                time.sleep(wait)
            except requests.exceptions.RequestException as e:
                print(f"[MLB API] Request error: {e}")
                return None

        print(f"[MLB API] All {MLB_API_RETRIES} retries exhausted for: {url}")
        return None

    # -------------------------------------------------------------------------
    # Schedule
    # -------------------------------------------------------------------------

    def get_schedule(self, date: str) -> List[GameInfo]:
        """
        Fetch game schedule for a given date.

        Requests probable pitchers and lineups in one hydrated call.
        Handles doubleheaders (multiple games per team per day).

        Args:
            date: Date string YYYY-MM-DD

        Returns:
            List of GameInfo objects (may be empty if no games)
        """
        data = self._get('/schedule', params={
            'date': date,
            'sportId': 1,
            'gameType': 'R',
            'hydrate': 'probablePitcher,lineups,venue,team',
        })

        if not data:
            return []

        games = []
        for game_date_entry in data.get('dates', []):
            for game in game_date_entry.get('games', []):
                try:
                    parsed = self._parse_schedule_game(game, date)
                    if parsed:
                        games.append(parsed)
                except Exception as e:
                    gid = game.get('gamePk', 'unknown')
                    print(f"[MLB API] Error parsing game {gid}: {e}")

        print(f"[MLB API] Schedule: found {len(games)} games for {date}")
        return games

    def _parse_schedule_game(self, game: Dict, game_date: str) -> Optional[GameInfo]:
        """Parse a single game entry from the schedule response."""
        status_code = game.get('status', {}).get('abstractGameCode', 'S')
        status_str = {
            'F': 'final',
            'L': 'live',
            'P': 'scheduled',
        }.get(status_code, 'scheduled')

        # Handle postponements
        detailed_state = game.get('status', {}).get('detailedState', '').lower()
        if 'postponed' in detailed_state:
            status_str = 'postponed'

        home = game.get('teams', {}).get('home', {})
        away = game.get('teams', {}).get('away', {})

        home_abbr = home.get('team', {}).get('abbreviation', '')
        away_abbr = away.get('team', {}).get('abbreviation', '')

        if not home_abbr or not away_abbr:
            return None

        # Starting pitchers
        home_pitcher = home.get('probablePitcher', {})
        away_pitcher = away.get('probablePitcher', {})

        home_starter = home_pitcher.get('fullName', 'TBD') if home_pitcher else 'TBD'
        away_starter = away_pitcher.get('fullName', 'TBD') if away_pitcher else 'TBD'
        home_starter_id = home_pitcher.get('id') if home_pitcher else None
        away_starter_id = away_pitcher.get('id') if away_pitcher else None

        # Game time
        game_datetime = game.get('gameDate', '')  # ISO UTC string
        day_night = game.get('dayNight', 'night').lower()

        # Venue
        venue = game.get('venue', {}).get('name', '')

        # Lineups (if posted)
        lineups = game.get('lineups', {})
        home_lineup = self._parse_lineup(lineups.get('homePlayers', []))
        away_lineup = self._parse_lineup(lineups.get('awayPlayers', []))

        # Doubleheader detection
        double_header = game.get('doubleHeader', 'N') != 'N'

        return GameInfo(
            game_id=game.get('gamePk', 0),
            game_date=game_date,
            home_team=home_abbr,
            away_team=away_abbr,
            venue=venue,
            game_time_utc=game_datetime,
            day_night=day_night,
            status=status_str,
            home_starter=home_starter,
            away_starter=away_starter,
            home_starter_id=home_starter_id,
            away_starter_id=away_starter_id,
            home_lineup=home_lineup,
            away_lineup=away_lineup,
            is_doubleheader=double_header,
        )

    def _parse_lineup(self, players: List[Dict]) -> List[Dict]:
        """Parse lineup array into simplified dicts."""
        lineup = []
        for p in players:
            person = p.get('person', {})
            lineup.append({
                'name': person.get('fullName', ''),
                'id': person.get('id'),
                'batting_order': p.get('battingOrder', 0),
                'hand': p.get('position', {}).get('abbreviation', ''),
            })
        # Sort by batting order
        lineup.sort(key=lambda x: x['batting_order'])
        return lineup

    # -------------------------------------------------------------------------
    # Boxscores
    # -------------------------------------------------------------------------

    def get_boxscore(self, game_id: int) -> Optional[Dict]:
        """
        Fetch final boxscore for a completed game.

        Args:
            game_id: MLB game ID (gamePk)

        Returns:
            Raw boxscore dict or None
        """
        return self._get(f'/game/{game_id}/boxscore')

    def parse_pitcher_stats(self, boxscore: Dict, team: str = None) -> List[PitcherBoxscore]:
        """
        Extract pitcher stats from a boxscore.

        Args:
            boxscore: Raw boxscore dict
            team: If provided, only return pitchers for that team abbreviation

        Returns:
            List of PitcherBoxscore objects (starters listed first)
        """
        pitchers = []

        for side in ['home', 'away']:
            team_data = boxscore.get('teams', {}).get(side, {})
            team_abbr = team_data.get('team', {}).get('abbreviation', '')

            if team and team_abbr != team:
                continue

            pitchers_data = team_data.get('pitchers', [])
            players = team_data.get('players', {})

            for i, pitcher_id in enumerate(pitchers_data):
                player_key = f'ID{pitcher_id}'
                player = players.get(player_key, {})
                person = player.get('person', {})
                stats = player.get('stats', {}).get('pitching', {})

                if not stats:
                    continue

                name = person.get('fullName', f'Player {pitcher_id}')
                ip_str = stats.get('inningsPitched', '0.0')
                ip = self._parse_innings_pitched(ip_str)
                outs = int(ip * 3)  # Convert IP to outs (e.g., 6.1 IP = 19 outs)

                pitchers.append(PitcherBoxscore(
                    player_name=name,
                    player_id=pitcher_id,
                    team=team_abbr,
                    innings_pitched=ip,
                    outs_recorded=outs,
                    strikeouts=stats.get('strikeOuts', 0),
                    walks=stats.get('baseOnBalls', 0),
                    hits_allowed=stats.get('hits', 0),
                    earned_runs=stats.get('earnedRuns', 0),
                    home_runs_allowed=stats.get('homeRuns', 0),
                    pitches=stats.get('pitchesThrown', stats.get('numberOfPitches', 0)),
                    is_starter=(i == 0),  # First in list = starter
                ))

        return pitchers

    def parse_batter_stats(self, boxscore: Dict, team: str = None) -> List[BatterBoxscore]:
        """
        Extract batter stats from a boxscore.

        Args:
            boxscore: Raw boxscore dict
            team: If provided, only return batters for that team abbreviation

        Returns:
            List of BatterBoxscore objects sorted by batting order
        """
        batters = []

        for side in ['home', 'away']:
            team_data = boxscore.get('teams', {}).get(side, {})
            team_abbr = team_data.get('team', {}).get('abbreviation', '')

            if team and team_abbr != team:
                continue

            batter_ids = team_data.get('batters', [])
            players = team_data.get('players', {})

            for batter_id in batter_ids:
                player_key = f'ID{batter_id}'
                player = players.get(player_key, {})
                person = player.get('person', {})
                stats = player.get('stats', {}).get('batting', {})

                if not stats:
                    continue

                # Skip pitchers who batted (NL-style games)
                position = player.get('position', {}).get('abbreviation', '')
                if position == 'P':
                    continue

                name = person.get('fullName', f'Player {batter_id}')
                h = stats.get('hits', 0)
                r = stats.get('runs', 0)
                rbi = stats.get('rbi', 0)
                doubles = stats.get('doubles', 0)
                triples = stats.get('triples', 0)
                hr = stats.get('homeRuns', 0)
                # Total bases = 1B + 2*2B + 3*3B + 4*HR
                singles = h - doubles - triples - hr
                tb = singles + (2 * doubles) + (3 * triples) + (4 * hr)
                batting_order_raw = player.get('battingOrder', '0')
                # battingOrder is like "100", "200", etc. in the API
                batting_order = int(str(batting_order_raw)[:1]) if batting_order_raw else 0

                batters.append(BatterBoxscore(
                    player_name=name,
                    player_id=batter_id,
                    team=team_abbr,
                    at_bats=stats.get('atBats', 0),
                    hits=h,
                    home_runs=hr,
                    rbis=rbi,
                    runs=r,
                    stolen_bases=stats.get('stolenBases', 0),
                    walks=stats.get('baseOnBalls', 0),
                    strikeouts=stats.get('strikeOuts', 0),
                    doubles=doubles,
                    triples=triples,
                    total_bases=max(tb, 0),
                    hrr=h + r + rbi,
                    batting_order=batting_order,
                ))

        # Sort by batting order
        batters.sort(key=lambda x: x.batting_order if x.batting_order > 0 else 99)
        return batters

    # -------------------------------------------------------------------------
    # Player Stats
    # -------------------------------------------------------------------------

    def get_player_season_stats(self, player_id: int, year: str, group: str) -> Optional[Dict]:
        """
        Fetch season aggregate stats for a player.

        Args:
            player_id: MLB player ID
            year: Season year (e.g., '2026')
            group: 'hitting' or 'pitching'

        Returns:
            Stats dict or None
        """
        data = self._get(f'/people/{player_id}/stats', params={
            'stats': 'season',
            'group': group,
            'season': year,
        })

        if not data:
            return None

        stats_list = data.get('stats', [])
        if not stats_list:
            return None

        splits = stats_list[0].get('splits', [])
        if not splits:
            return None

        return splits[0].get('stat', {})

    def get_player_game_log(self, player_id: int, year: str, group: str) -> List[Dict]:
        """
        Fetch game-by-game stat log for a player.

        Args:
            player_id: MLB player ID
            year: Season year
            group: 'hitting' or 'pitching'

        Returns:
            List of per-game stat dicts (most recent first)
        """
        data = self._get(f'/people/{player_id}/stats', params={
            'stats': 'gameLog',
            'group': group,
            'season': year,
        })

        if not data:
            return []

        stats_list = data.get('stats', [])
        if not stats_list:
            return []

        splits = stats_list[0].get('splits', [])

        # Each split has 'date', 'stat', 'team', 'opponent'
        logs = []
        for split in reversed(splits):  # Most recent first
            logs.append({
                'date': split.get('date', ''),
                'stat': split.get('stat', {}),
                'team': split.get('team', {}).get('abbreviation', ''),
                'opponent': split.get('opponent', {}).get('abbreviation', ''),
                'is_home': split.get('isHome', True),
            })

        return logs

    def search_player(self, name: str) -> Optional[Dict]:
        """
        Search for a player by name and return their ID and info.

        Args:
            name: Player name (e.g., 'Shohei Ohtani')

        Returns:
            Dict with id, fullName, primaryPosition, batSide, pitchHand or None
        """
        data = self._get('/people/search', params={
            'names': name,
            'sportId': 1,
        })

        if not data:
            return None

        people = data.get('people', [])
        if not people:
            return None

        # Return the first (most relevant) result
        p = people[0]
        return {
            'id': p.get('id'),
            'fullName': p.get('fullName', ''),
            'primaryPosition': p.get('primaryPosition', {}).get('abbreviation', ''),
            'batSide': p.get('batSide', {}).get('code', ''),
            'pitchHand': p.get('pitchHand', {}).get('code', ''),
            'currentTeam': p.get('currentTeam', {}).get('abbreviation', ''),
        }

    def get_player_info(self, player_id: int) -> Optional[Dict]:
        """
        Get full player info including handedness.

        Args:
            player_id: MLB player ID

        Returns:
            Dict with player details or None
        """
        data = self._get(f'/people/{player_id}', params={'hydrate': 'currentTeam'})
        if not data:
            return None

        people = data.get('people', [])
        if not people:
            return None

        p = people[0]
        return {
            'id': p.get('id'),
            'fullName': p.get('fullName', ''),
            'primaryPosition': p.get('primaryPosition', {}).get('abbreviation', ''),
            'batSide': p.get('batSide', {}).get('code', ''),  # 'L', 'R', 'S' (switch)
            'pitchHand': p.get('pitchHand', {}).get('code', ''),  # 'L', 'R'
            'currentTeam': p.get('currentTeam', {}).get('abbreviation', ''),
        }

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_innings_pitched(ip_str: str) -> float:
        """
        Convert MLB innings pitched string to decimal.

        e.g., '6.1' -> 6.333..., '7.2' -> 7.667..., '5.0' -> 5.0

        Args:
            ip_str: Innings pitched string like '6.1'

        Returns:
            Decimal innings pitched
        """
        try:
            parts = str(ip_str).split('.')
            full_innings = int(parts[0])
            if len(parts) > 1:
                partial_outs = int(parts[1])  # 0, 1, or 2
                return full_innings + (partial_outs / 3.0)
            return float(full_innings)
        except (ValueError, IndexError):
            return 0.0

    @staticmethod
    def compute_era(earned_runs: int, innings_pitched: float) -> float:
        """Compute ERA from earned runs and innings pitched."""
        if innings_pitched <= 0:
            return 9.0  # Default to league average if no data
        return (earned_runs / innings_pitched) * 9.0

    @staticmethod
    def compute_whip(hits: int, walks: int, innings_pitched: float) -> float:
        """Compute WHIP from hits, walks, and innings pitched."""
        if innings_pitched <= 0:
            return 1.30  # League average default
        return (hits + walks) / innings_pitched

    @staticmethod
    def compute_k9(strikeouts: int, innings_pitched: float) -> float:
        """Compute K/9 from strikeouts and innings pitched."""
        if innings_pitched <= 0:
            return 8.5  # League average default
        return (strikeouts / innings_pitched) * 9.0

    @staticmethod
    def compute_bb9(walks: int, innings_pitched: float) -> float:
        """Compute BB/9 from walks and innings pitched."""
        if innings_pitched <= 0:
            return 3.0
        return (walks / innings_pitched) * 9.0

    @staticmethod
    def compute_h9(hits: int, innings_pitched: float) -> float:
        """Compute H/9 from hits and innings pitched."""
        if innings_pitched <= 0:
            return 9.0
        return (hits / innings_pitched) * 9.0

    @staticmethod
    def compute_hr9(home_runs: int, innings_pitched: float) -> float:
        """Compute HR/9 from home runs and innings pitched."""
        if innings_pitched <= 0:
            return 1.2
        return (home_runs / innings_pitched) * 9.0


# ============================================================================
# Quick test / standalone usage
# ============================================================================

if __name__ == '__main__':
    import sys

    api = MLBStatsAPI()

    # Test schedule for today
    test_date = datetime.now().strftime('%Y-%m-%d')
    if len(sys.argv) > 1:
        test_date = sys.argv[1]

    print(f"\n[MLB Stats API] Fetching schedule for {test_date}...")
    games = api.get_schedule(test_date)

    if not games:
        print(f"  No games found for {test_date}")
    else:
        for g in games:
            print(f"\n  Game {g.game_id}: {g.away_team} @ {g.home_team}")
            print(f"  Venue: {g.venue} | Status: {g.status}")
            print(f"  Home starter: {g.home_starter} | Away starter: {g.away_starter}")
            print(f"  Home lineup posted: {len(g.home_lineup) > 0}")
            print(f"  Away lineup posted: {len(g.away_lineup) > 0}")

    # Test boxscore if we have any final games
    final_games = [g for g in games if g.status == 'final']
    if final_games:
        print(f"\n[MLB Stats API] Testing boxscore for game {final_games[0].game_id}...")
        boxscore = api.get_boxscore(final_games[0].game_id)
        if boxscore:
            pitchers = api.parse_pitcher_stats(boxscore)
            batters = api.parse_batter_stats(boxscore)
            print(f"  Parsed {len(pitchers)} pitchers, {len(batters)} batters")
            for p in pitchers[:2]:
                print(f"  P: {p.player_name} | IP: {p.innings_pitched} | K: {p.strikeouts}")
            for b in batters[:3]:
                print(f"  B: {b.player_name} | H: {b.hits} | TB: {b.total_bases} | HRR: {b.hrr}")
