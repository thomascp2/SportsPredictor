"""
NBA Stats API Data Fetcher
===========================

Fetches data from NBA Stats API:
- Game schedules
- Player game logs
- Box scores

Official API: https://stats.nba.com/stats
"""

import requests
import time
from datetime import datetime, timedelta
import json
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nba_config import REQUEST_HEADERS, SEASON

class NBAStatsAPI:
    """NBA Stats API client."""

    BASE_URL = "https://stats.nba.com/stats"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def _make_request(self, endpoint, params):
        """Make API request with rate limiting and error handling."""
        url = f"{self.BASE_URL}/{endpoint}"

        try:
            time.sleep(0.6)  # Rate limit: ~100 requests/minute
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ API Error: {e}")
            return None

    def get_scoreboard(self, game_date):
        """
        Get scoreboard for a specific date.

        Args:
            game_date (str): Date in YYYY-MM-DD format

        Returns:
            dict: Scoreboard data with games
        """
        # Convert to NBA API format (MM/DD/YYYY)
        dt = datetime.strptime(game_date, "%Y-%m-%d")
        date_str = dt.strftime("%m/%d/%Y")

        params = {
            'GameDate': date_str,
            'LeagueID': '00',  # NBA
            'DayOffset': '0'
        }

        data = self._make_request('scoreboardV2', params)

        if not data:
            return []

        games = []
        game_header = data.get('resultSets', [])[0].get('rowSet', [])

        for game in game_header:
            games.append({
                'game_id': game[2],
                'game_date': game_date,
                'status': game[4],
                'home_team': self._get_team_tricode(game[6]),
                'away_team': self._get_team_tricode(game[7]),
                'home_score': game[22] if len(game) > 22 else None,
                'away_score': game[21] if len(game) > 21 else None,
            })

        return games

    def get_player_game_log(self, player_id, season=SEASON):
        """
        Get player game log for a season.

        Args:
            player_id (str): NBA player ID
            season (str): Season (e.g., '2024-25')

        Returns:
            list: Game log data
        """
        params = {
            'PlayerID': player_id,
            'Season': season,
            'SeasonType': 'Regular Season',
            'LeagueID': '00'
        }

        data = self._make_request('playergamelog', params)

        if not data:
            return []

        headers = data.get('resultSets', [])[0].get('headers', [])
        rows = data.get('resultSets', [])[0].get('rowSet', [])

        logs = []
        for row in rows:
            log = dict(zip(headers, row))
            logs.append({
                'game_id': log.get('Game_ID'),
                'game_date': log.get('GAME_DATE'),
                'matchup': log.get('MATCHUP'),
                'minutes': float(log.get('MIN', 0)) if log.get('MIN') else 0,
                'points': int(log.get('PTS', 0)),
                'rebounds': int(log.get('REB', 0)),
                'assists': int(log.get('AST', 0)),
                'steals': int(log.get('STL', 0)),
                'blocks': int(log.get('BLK', 0)),
                'turnovers': int(log.get('TOV', 0)),
                'threes_made': int(log.get('FG3M', 0)),
                'fgm': int(log.get('FGM', 0)),
                'fga': int(log.get('FGA', 0)),
                'ftm': int(log.get('FTM', 0)),
                'fta': int(log.get('FTA', 0)),
                'plus_minus': int(log.get('PLUS_MINUS', 0)),
            })

        return logs

    def get_boxscore_traditional(self, game_id):
        """
        Get traditional boxscore for a game.

        Args:
            game_id (str): NBA game ID

        Returns:
            list: Player stats from the game
        """
        params = {
            'GameID': game_id,
            'StartPeriod': '0',
            'EndPeriod': '10',
            'RangeType': '0',
            'StartRange': '0',
            'EndRange': '0'
        }

        data = self._make_request('boxscoretraditionalv2', params)

        if not data:
            return []

        player_stats = []
        for result_set in data.get('resultSets', []):
            if result_set.get('name') == 'PlayerStats':
                headers = result_set.get('headers', [])
                rows = result_set.get('rowSet', [])

                for row in rows:
                    stats = dict(zip(headers, row))
                    player_stats.append({
                        'game_id': game_id,
                        'player_name': stats.get('PLAYER_NAME'),
                        'team': stats.get('TEAM_ABBREVIATION'),
                        'minutes': self._parse_minutes(stats.get('MIN')),
                        'points': int(stats.get('PTS', 0)),
                        'rebounds': int(stats.get('REB', 0)),
                        'assists': int(stats.get('AST', 0)),
                        'steals': int(stats.get('STL', 0)),
                        'blocks': int(stats.get('BLK', 0)),
                        'turnovers': int(stats.get('TO', 0)),
                        'threes_made': int(stats.get('FG3M', 0)),
                        'fgm': int(stats.get('FGM', 0)),
                        'fga': int(stats.get('FGA', 0)),
                        'ftm': int(stats.get('FTM', 0)),
                        'fta': int(stats.get('FTA', 0)),
                        'plus_minus': int(stats.get('PLUS_MINUS', 0)),
                    })

        return player_stats

    def get_team_roster(self, team_id, season=SEASON):
        """
        Get team roster for a season.

        Args:
            team_id (str): NBA team ID
            season (str): Season (e.g., '2024-25')

        Returns:
            list: Roster data
        """
        params = {
            'TeamID': team_id,
            'Season': season,
            'LeagueID': '00'
        }

        data = self._make_request('commonteamroster', params)

        if not data:
            return []

        headers = data.get('resultSets', [])[0].get('headers', [])
        rows = data.get('resultSets', [])[0].get('rowSet', [])

        roster = []
        for row in rows:
            player = dict(zip(headers, row))
            roster.append({
                'player_id': player.get('PLAYER_ID'),
                'player_name': player.get('PLAYER'),
                'number': player.get('NUM'),
                'position': player.get('POSITION'),
            })

        return roster

    @staticmethod
    def _get_team_tricode(team_id):
        """Convert team ID to tricode (e.g., LAL, BOS)."""
        # NBA team ID to tricode mapping
        team_map = {
            1610612737: 'ATL', 1610612738: 'BOS', 1610612751: 'BKN',
            1610612766: 'CHA', 1610612741: 'CHI', 1610612739: 'CLE',
            1610612742: 'DAL', 610612743: 'DEN', 1610612765: 'DET',
            1610612744: 'GSW', 1610612745: 'HOU', 1610612754: 'IND',
            1610612746: 'LAC', 1610612747: 'LAL', 1610612763: 'MEM',
            1610612748: 'MIA', 1610612749: 'MIL', 1610612750: 'MIN',
            1610612740: 'NOP', 1610612752: 'NYK', 1610612760: 'OKC',
            1610612753: 'ORL', 1610612755: 'PHI', 1610612756: 'PHX',
            1610612757: 'POR', 1610612758: 'SAC', 1610612759: 'SAS',
            1610612761: 'TOR', 1610612762: 'UTA', 1610612764: 'WAS',
        }
        return team_map.get(team_id, 'UNK')

    @staticmethod
    def _parse_minutes(min_str):
        """Parse minutes string (e.g., '32:15' -> 32.25)."""
        if not min_str or min_str == 'None':
            return 0.0
        try:
            parts = min_str.split(':')
            return float(parts[0]) + float(parts[1]) / 60
        except:
            return 0.0


# Example usage
if __name__ == "__main__":
    api = NBAStatsAPI()

    # Test scoreboard
    print("🏀 Testing NBA Stats API...")
    games = api.get_scoreboard("2024-11-08")
    print(f"Found {len(games)} games on 2024-11-08")

    if games:
        print(f"\nSample game: {games[0]}")

        # Test boxscore
        game_id = games[0]['game_id']
        boxscore = api.get_boxscore_traditional(game_id)
        print(f"\nBoxscore players: {len(boxscore)}")
        if boxscore:
            print(f"Sample player: {boxscore[0]}")
