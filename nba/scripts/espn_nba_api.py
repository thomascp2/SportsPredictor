# AUTO-FIXED: 2024-12-19 - Simplified ESPN NBA API client to handle enhanced response structure with new metadata fields while maintaining robust backwards compatibility

"""
ESPN NBA API Client
===================

Reliable alternative to stats.nba.com API.
ESPN's API updates within 15-30 minutes of games ending.

Advantages:
- Much faster updates than NBA Stats API
- More reliable
- No authentication required
- Better uptime

Usage:
    from espn_nba_api import ESPNNBAApi
    api = ESPNNBAApi()
    games = api.get_scoreboard("2025-11-10")
    boxscore = api.get_boxscore(game_id)
"""

import requests
from datetime import datetime
import time


class ESPNNBAApi:
    """ESPN NBA API client with enhanced support for new API structure."""
    
    def __init__(self):
        self.base_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
    
    def get_scoreboard(self, game_date):
        """
        Get games for a specific date.
        
        Args:
            game_date (str): Date in YYYY-MM-DD format
        
        Returns:
            list: List of game dictionaries compatible with your grading script
        """
        # ESPN uses YYYYMMDD format
        espn_date = game_date.replace('-', '')
        
        url = f"{self.base_url}/scoreboard"
        params = {'dates': espn_date}
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            games = []
            
            # FIXED: Extract enhanced league and provider info from new API structure
            league_info = self._extract_league_info(data.get('leagues', []))
            provider_info = self._extract_provider_info(data.get('provider', {}))
            
            events = data.get('events', [])
            if not isinstance(events, list):
                print("Warning: events field is not a list or missing")
                return []
            
            if len(events) == 0:
                print(f"No games found for {game_date}. This might be an off-season date.")
                return []
            
            for event in events:
                if not isinstance(event, dict):
                    continue
                
                competitions = event.get('competitions', [])
                if not isinstance(competitions, list) or len(competitions) == 0:
                    continue
                
                competition = competitions[0]
                if not isinstance(competition, dict):
                    continue
                
                # Extract teams with enhanced metadata support
                competitors = competition.get('competitors', [])
                if not isinstance(competitors, list) or len(competitors) < 2:
                    continue
                
                home_team, away_team = self._extract_teams(competitors)
                if not home_team or not away_team:
                    continue
                
                # Extract basic game info
                game_id = event.get('id', '') or competition.get('id', '')
                if not game_id:
                    continue
                
                home_team_abbr, home_team_name = self._extract_team_info(home_team)
                away_team_abbr, away_team_name = self._extract_team_info(away_team)
                
                if not home_team_abbr or not away_team_abbr:
                    continue
                
                # Extract scores
                home_score = self._extract_score(home_team)
                away_score = self._extract_score(away_team)
                
                # Extract game status with enhanced status parsing
                game_status, game_clock, game_period = self._extract_status(event, competition)
                
                # FIXED: Extract enhanced venue and broadcast info from new structure
                venue_info = self._extract_venue_info(competition.get('venue', {}))
                broadcast_info = self._extract_broadcast_info(competition.get('broadcasts', []))
                
                # Extract betting lines (spread, game total, moneylines)
                # ESPN returns odds at competition.odds[] for pre-game and live games.
                spread = None
                over_under = None
                home_moneyline = None
                away_moneyline = None
                odds_provider = ''
                odds_details = ''
                try:
                    odds_list = competition.get('odds', [])
                    if isinstance(odds_list, list) and odds_list:
                        odds_obj = odds_list[0]
                        if isinstance(odds_obj, dict):
                            odds_details = str(odds_obj.get('details', ''))
                            over_under = odds_obj.get('overUnder')
                            odds_provider = str(odds_obj.get('provider', {}).get('name', '')
                                                if isinstance(odds_obj.get('provider'), dict)
                                                else '')

                            # Spread: ESPN provides the raw spread value.
                            # Positive = home team favored; negative = away team favored.
                            raw_spread = odds_obj.get('spread')
                            if raw_spread is not None:
                                try:
                                    spread = float(raw_spread)
                                except (ValueError, TypeError):
                                    spread = None

                            # Fall back to parsing the details string ("PHX -7.5" or "7.5")
                            if spread is None and odds_details:
                                try:
                                    parts = odds_details.strip().split()
                                    spread_str = parts[-1] if parts else ''
                                    spread = float(spread_str)
                                except (ValueError, IndexError):
                                    pass

                            # Moneylines
                            home_odds = odds_obj.get('homeTeamOdds', {})
                            away_odds = odds_obj.get('awayTeamOdds', {})
                            if isinstance(home_odds, dict):
                                home_moneyline = home_odds.get('moneyLine') or home_odds.get('current', {}).get('moneyLine')
                            if isinstance(away_odds, dict):
                                away_moneyline = away_odds.get('moneyLine') or away_odds.get('current', {}).get('moneyLine')
                except Exception:
                    pass  # Odds unavailable — non-fatal

                # Build comprehensive game dictionary with new metadata
                game_info = {
                    'game_id': str(game_id),
                    'game_date': game_date,
                    'home_team': home_team_abbr,
                    'away_team': away_team_abbr,
                    'status': game_status,
                    'home_score': home_score,
                    'away_score': away_score,
                    'espn_game_id': str(game_id),
                    'home_team_name': home_team_name,
                    'away_team_name': away_team_name,
                    'venue_name': venue_info.get('name', ''),
                    'broadcasts': broadcast_info,
                    'game_clock': game_clock,
                    'game_period': game_period,
                    'venue_city': venue_info.get('city', ''),
                    'neutral_site': competition.get('neutralSite', False),
                    'attendance': competition.get('attendance'),
                    'play_by_play_available': competition.get('playByPlayAvailable', False),
                    # Enhanced metadata from new API structure
                    'event_uid': event.get('uid', ''),
                    'event_name': event.get('name', ''),
                    'event_short_name': event.get('shortName', ''),
                    'competition_uid': competition.get('uid', ''),
                    'start_date': competition.get('startDate', ''),
                    'league_info': league_info,
                    'provider_info': provider_info,
                    # Betting lines
                    'spread': spread,           # float; positive = home favored
                    'over_under': over_under,   # float; game total
                    'home_moneyline': home_moneyline,
                    'away_moneyline': away_moneyline,
                    'odds_details': odds_details,
                    'odds_provider': odds_provider,
                }
                
                games.append(game_info)
            
            return games
            
        except requests.exceptions.RequestException as e:
            print(f"ESPN API request error: {e}")
            return []
        except Exception as e:
            print(f"ESPN API parsing error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_boxscore(self, game_id):
        """
        Get boxscore for a game using ESPN game ID.
        
        Args:
            game_id (str): ESPN game ID (e.g., "401584893")
        
        Returns:
            list: List of player stat dictionaries
        """
        url = f"{self.base_url}/summary"
        params = {'event': str(game_id)}
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            players = []
            
            boxscore = data.get('boxscore', {})
            if not isinstance(boxscore, dict):
                print("Warning: No valid boxscore data found")
                return []

            players_data = boxscore.get('players', [])
            if not isinstance(players_data, list):
                print("Warning: No valid players data found")
                return []
            
            # Process each team's player data
            for team_data in players_data:
                if not isinstance(team_data, dict):
                    continue
                
                team_info = team_data.get('team', {})
                if not isinstance(team_info, dict):
                    continue
                
                team_abbr = self._extract_team_abbreviation(team_info)
                if not team_abbr:
                    continue
                
                # Extract statistics structure
                statistics = team_data.get('statistics', [])
                if not isinstance(statistics, list) or len(statistics) == 0:
                    continue
                
                stat_info = statistics[0]
                if not isinstance(stat_info, dict):
                    continue
                
                # FIXED: Extract stat headers from enhanced structure with multiple field options
                stat_keys = self._extract_stat_headers(stat_info)
                athletes_data = stat_info.get('athletes', [])
                
                if not isinstance(athletes_data, list):
                    continue
                
                for athlete_data in athletes_data:
                    if not isinstance(athlete_data, dict):
                        continue
                    
                    # Skip DNP players
                    if athlete_data.get('didNotPlay', False):
                        continue
                    
                    athlete_info = athlete_data.get('athlete', {})
                    if not isinstance(athlete_info, dict):
                        continue
                    
                    # Extract player stats
                    player_stats_raw = athlete_data.get('stats', [])
                    if not isinstance(player_stats_raw, list) or not player_stats_raw:
                        continue
                    
                    # Build stats dictionary
                    stat_dict = self._build_stat_dict(stat_keys, player_stats_raw)
                    if not stat_dict:
                        continue
                    
                    # Parse minutes
                    minutes = self._parse_minutes_from_stats(stat_dict)
                    if minutes == 0:
                        continue
                    
                    # Extract player name
                    player_name = self._extract_player_name(athlete_info)
                    if not player_name:
                        continue
                    
                    # Parse all stats with enhanced field mapping
                    parsed_stats = self._parse_player_stats(stat_dict, minutes)
                    
                    # FIXED: Build comprehensive player stats with enhanced metadata
                    player_stats = {
                        'game_id': str(game_id),
                        'player_name': player_name,
                        'team': team_abbr,
                        'minutes': parsed_stats['minutes'],
                        'points': parsed_stats['points'],
                        'rebounds': parsed_stats['rebounds'],
                        'assists': parsed_stats['assists'],
                        'steals': parsed_stats['steals'],
                        'blocks': parsed_stats['blocks'],
                        'turnovers': parsed_stats['turnovers'],
                        'threes_made': parsed_stats['threes_made'],
                        'fga': parsed_stats['fga'],
                        'fgm': parsed_stats['fgm'],
                        'fta': parsed_stats['fta'],
                        'ftm': parsed_stats['ftm'],
                        'plus_minus': parsed_stats['plus_minus'],
                        'three_point_attempts': parsed_stats['three_point_attempts'],
                        # Enhanced metadata from new API structure
                        'player_id': str(athlete_info.get('id', '')),
                        'player_uid': str(athlete_info.get('uid', '')),
                        'jersey_number': str(athlete_info.get('jersey', '')),
                        'position': self._extract_position(athlete_info),
                        'starter': athlete_data.get('starter', False),
                        'ejected': athlete_data.get('ejected', False),
                        'team_id': str(team_info.get('id', '')),
                        'team_uid': str(team_info.get('uid', '')),
                        'team_display_name': str(team_info.get('displayName', '')),
                        'team_color': str(team_info.get('color', '')),
                        'team_logo': str(team_info.get('logo', ''))
                    }
                    
                    players.append(player_stats)
            
            time.sleep(0.3)
            return players
            
        except requests.exceptions.RequestException as e:
            print(f"ESPN boxscore request error: {e}")
            return []
        except Exception as e:
            print(f"ESPN boxscore parsing error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _extract_league_info(self, leagues):
        """Extract enhanced league information from new API structure."""
        if not isinstance(leagues, list):
            return {}
        
        for league in leagues:
            if isinstance(league, dict) and league.get('abbreviation') == 'NBA':
                season_info = league.get('season', {})
                return {
                    'name': league.get('name', ''),
                    'uid': league.get('uid', ''),
                    'slug': league.get('slug', ''),
                    'season_year': season_info.get('year') if isinstance(season_info, dict) else None,
                    'season_type': season_info.get('type', {}).get('name', '') if isinstance(season_info, dict) and isinstance(season_info.get('type'), dict) else '',
                    'season_start': season_info.get('startDate', '') if isinstance(season_info, dict) else '',
                    'season_end': season_info.get('endDate', '') if isinstance(season_info, dict) else '',
                    'calendar_type': league.get('calendarType', ''),
                    'logos': league.get('logos', [])
                }
        return {}
    
    def _extract_provider_info(self, provider):
        """Extract enhanced provider information from new API structure."""
        if not isinstance(provider, dict):
            return {}
        
        return {
            'id': provider.get('id', ''),
            'name': provider.get('name', ''),
            'display_name': provider.get('displayName', ''),
            'priority': provider.get('priority'),
            'logos': provider.get('logos', [])
        }
    
    def _extract_teams(self, competitors):
        """Extract home and away teams from competitors."""
        home_team = None
        away_team = None
        
        for competitor in competitors:
            if not isinstance(competitor, dict):
                continue
            
            team_data = competitor.get('team', {})
            if not isinstance(team_data, dict) or not team_data.get('abbreviation'):
                continue
            
            home_away = competitor.get('homeAway', '').lower()
            if home_away == 'home':
                home_team = competitor
            elif home_away == 'away':
                away_team = competitor
        
        # Fallback if home/away not clearly marked
        if not home_team or not away_team:
            valid_competitors = []
            for comp in competitors:
                if (isinstance(comp, dict) and 
                    isinstance(comp.get('team'), dict) and 
                    comp['team'].get('abbreviation')):
                    valid_competitors.append(comp)
            
            if len(valid_competitors) >= 2:
                away_team = valid_competitors[0]
                home_team = valid_competitors[1]
        
        return home_team, away_team
    
    def _extract_team_info(self, team_competitor):
        """Extract team abbreviation and name with enhanced field support."""
        if not isinstance(team_competitor, dict):
            return '', ''
        
        team_data = team_competitor.get('team', {})
        if not isinstance(team_data, dict):
            return '', ''
        
        # Extract abbreviation with fallbacks
        abbr = team_data.get('abbreviation', '').strip()
        if not abbr:
            abbr = (team_data.get('shortDisplayName', '') or 
                   team_data.get('displayName', '')[:3] or
                   team_data.get('name', '')[:3] or
                   team_data.get('slug', '').upper()[:3]).strip().upper()
        
        # Extract name with enhanced fields
        name = (team_data.get('displayName', '') or 
               team_data.get('name', '') or 
               team_data.get('longName', '')).strip()
        
        if not name:
            location = team_data.get('location', '').strip()
            nickname = team_data.get('nickname', '').strip()
            if location and nickname:
                name = f"{location} {nickname}"
            elif location or nickname:
                name = location or nickname
            else:
                name = abbr
        
        return abbr, name
    
    def _extract_score(self, team_competitor):
        """Extract score from team competitor."""
        if not isinstance(team_competitor, dict):
            return None
        
        score_value = team_competitor.get('score')
        if score_value is None or score_value == '':
            return None
        
        try:
            score_str = str(score_value).strip()
            if score_str and score_str not in ['--', '', 'null', 'None', 'N/A', 'TBD']:
                return int(float(score_str))
        except (ValueError, TypeError):
            pass
        
        return None
    
    def _extract_status(self, event, competition):
        """Extract game status, clock, and period information."""
        game_status = 'Scheduled'
        game_clock = ''
        game_period = ''
        
        status_sources = [
            event.get('status', {}),
            competition.get('status', {})
        ]
        
        for status_obj in status_sources:
            if not isinstance(status_obj, dict):
                continue
            
            if status_obj.get('displayClock'):
                game_clock = str(status_obj['displayClock']).strip()
            
            if status_obj.get('period'):
                try:
                    period_num = int(status_obj['period'])
                    if period_num <= 4:
                        game_period = f"Q{period_num}"
                    else:
                        game_period = f"OT{period_num - 4}"
                except (ValueError, TypeError):
                    game_period = str(status_obj['period'])
            
            status_type = status_obj.get('type')
            if not isinstance(status_type, dict):
                continue
            
            state = status_type.get('state', '').lower().strip()
            completed = status_type.get('completed')
            
            if completed is True:
                game_status = 'Final'
                break
            elif state == 'in':
                game_status = 'In Progress'
                break
            elif state == 'post':
                game_status = 'Final'
                break
            elif state == 'pre':
                game_status = 'Scheduled'
        
        return game_status, game_clock, game_period
    
    def _extract_venue_info(self, venue):
        """Extract venue information with enhanced field support."""
        if not isinstance(venue, dict):
            return {}
        
        venue_info = {
            'name': (venue.get('fullName', '') or venue.get('name', '')).strip(),
            'city': ''
        }
        
        if venue.get('address', {}) and isinstance(venue['address'], dict):
            venue_info['city'] = venue['address'].get('city', '').strip()
        
        return venue_info
    
    def _extract_broadcast_info(self, broadcasts):
        """Extract broadcast information."""
        broadcast_names = []
        if isinstance(broadcasts, list):
            for broadcast in broadcasts:
                if isinstance(broadcast, dict):
                    name = broadcast.get('name', '') or broadcast.get('market', '')
                    if name:
                        broadcast_names.append(str(name))
        return broadcast_names
    
    def _extract_team_abbreviation(self, team_info):
        """Extract team abbreviation with fallbacks."""
        team_abbr = team_info.get('abbreviation', '').strip()
        if not team_abbr:
            team_abbr = (team_info.get('shortDisplayName', '') or 
                        team_info.get('displayName', '')[:3] or
                        team_info.get('slug', '').upper()[:3]).strip()
        return team_abbr
    
    def _extract_stat_headers(self, stat_info):
        """Extract stat headers from enhanced API structure."""
        stat_keys = []
        header_sources = ['names', 'labels', 'keys', 'descriptions', 'headers']
        
        for field_name in header_sources:
            field_value = stat_info.get(field_name)
            if isinstance(field_value, list) and field_value:
                stat_keys = [str(k).strip() for k in field_value if k is not None and str(k).strip()]
                break
            elif isinstance(field_value, str) and field_value.strip():
                stat_keys = [field_value.strip()]
                break
        
        # Fallback to standard NBA stat headers
        if not stat_keys or len(stat_keys) < 5:
            stat_keys = ['MIN', 'FGM-FGA', 'FG%', '3PM-3PA', '3P%', 'FTM-FTA', 'FT%', 
                        'OREB', 'DREB', 'REB', 'AST', 'STL', 'BLK', 'TO', 'PF', 'PTS', '+/-']
        
        return stat_keys
    
    def _build_stat_dict(self, stat_keys, player_stats_raw):
        """Build statistics dictionary from keys and values."""
        stat_dict = {}
        for i, key in enumerate(stat_keys):
            if i < len(player_stats_raw) and player_stats_raw[i] is not None:
                value = player_stats_raw[i]
                str_val = str(value).strip()
                if str_val not in ['--', '', 'N/A', 'null', 'None', 'DNP', 'DND', 'SUSP', 'INJ']:
                    stat_dict[key] = value
        return stat_dict
    
    def _parse_minutes_from_stats(self, stat_dict):
        """Parse minutes from statistics dictionary."""
        min_keys = ['MIN', 'minutes', 'min', 'MP', 'MINS']
        for min_key in min_keys:
            if min_key in stat_dict:
                minutes = self._parse_minutes(stat_dict[min_key])
                if minutes > 0:
                    return minutes
        return 0.0
    
    def _extract_player_name(self, athlete_info):
        """Extract player name with enhanced field support."""
        return (athlete_info.get('displayName') or 
                athlete_info.get('fullName') or
                athlete_info.get('name') or 
                athlete_info.get('shortName', '')).strip()
    
    def _parse_player_stats(self, stat_dict, minutes):
        """Parse all player statistics from stat dictionary."""
        def parse_made_attempted(keys):
            for key in keys:
                if key in stat_dict:
                    val_str = str(stat_dict[key]).strip()
                    separators = ['-', '/']
                    for sep in separators:
                        if sep in val_str and val_str.count(sep) == 1:
                            try:
                                made, attempted = val_str.split(sep)
                                return int(float(made.strip())), int(float(attempted.strip()))
                            except (ValueError, AttributeError):
                                continue
            return 0, 0
        
        def get_stat_value(keys, default=0):
            for key in keys:
                if key in stat_dict and stat_dict[key] is not None:
                    try:
                        val_str = str(stat_dict[key]).strip()
                        if val_str.startswith('+'):
                            val_str = val_str[1:]
                        elif val_str.startswith('-') and len(val_str) > 1:
                            if val_str[1:].replace('.', '').isdigit():
                                return -int(float(val_str[1:]))
                        
                        if val_str.replace('.', '').replace('-', '').isdigit():
                            return int(float(val_str))
                    except (ValueError, TypeError, AttributeError):
                        continue
            return default
        
        # Parse all statistics
        fgm, fga = parse_made_attempted(['FGM-FGA', 'FG', 'Field Goals', 'fieldGoals', 'FGM/FGA'])
        fg3m, fg3a = parse_made_attempted(['3PM-3PA', '3P', 'Three Pointers', '3FG', 'threePointers', '3PM/3PA'])
        ftm, fta = parse_made_attempted(['FTM-FTA', 'FT', 'Free Throws', 'freeThrows', 'FTM/FTA'])
        
        return {
            'minutes': float(minutes),
            'points': get_stat_value(['PTS', 'points', 'Points', 'P', 'POINTS']),
            'rebounds': get_stat_value(['REB', 'rebounds', 'Rebounds', 'R', 'totalRebounds', 'REBS']),
            'assists': get_stat_value(['AST', 'assists', 'Assists', 'A', 'ASTS']),
            'steals': get_stat_value(['STL', 'steals', 'Steals', 'S', 'STLS']),
            'blocks': get_stat_value(['BLK', 'blocks', 'Blocks', 'B', 'BLKS']),
            'turnovers': get_stat_value(['TO', 'turnovers', 'Turnovers', 'TOV', 'TOS']),
            'plus_minus': get_stat_value(['+/-', 'plusMinus', 'Plus/Minus', 'PM', 'PLUS_MINUS'], 0),
            'fgm': fgm,
            'fga': fga,
            'threes_made': fg3m,
            'three_point_attempts': fg3a,
            'ftm': ftm,
            'fta': fta
        }
    
    def _extract_position(self, athlete_info):
        """Extract player position with enhanced field support."""
        if not isinstance(athlete_info, dict):
            return ''
        
        position_data = athlete_info.get('position')
        if isinstance(position_data, dict):
            return (position_data.get('abbreviation', '') or 
                   position_data.get('name', '') or
                   position_data.get('displayName', '')).strip()
        elif isinstance(position_data, str):
            return position_data.strip()
        
        # Fallback to other potential position fields
        for field in ['pos', 'POS', 'Position']:
            if athlete_info.get(field):
                return str(athlete_info[field]).strip()
        
        return ''
    
    @staticmethod
    def _parse_minutes(min_str):
        """Parse minutes from various formats."""
        if not min_str or str(min_str).strip() in ['--', '', 'N/A', 'None', 'null', 'DNP', 'DND', 'SUSP', 'INJ']:
            return 0.0
        
        try:
            min_str = str(min_str).strip()
            
            # Handle MM:SS format
            if ':' in min_str:
                parts = min_str.split(':')
                if len(parts) == 2:
                    minutes, seconds = parts
                    return float(minutes) + (float(seconds) / 60.0)
            else:
                value = float(min_str)
                # Handle seconds format (values > 100 likely in seconds)
                if value > 100:
                    return value / 60.0
                return value
        except (ValueError, TypeError, AttributeError):
            pass
        
        return 0.0


# Test functionality
if __name__ == "__main__":
    api = ESPNNBAApi()
    
    print("🏀 Testing Enhanced ESPN NBA API with New Structure Support\n")
    
    # Test scoreboard
    test_date = "2024-12-19"
    print(f"Fetching games for {test_date}...")
    games = api.get_scoreboard(test_date)
    
    print(f"✅ Found {len(games)} games\n")
    
    if games:
        for game in games:
            away_score = str(game['away_score']) if game['away_score'] is not None else 'N/A'
            home_score = str(game['home_score']) if game['home_score'] is not None else 'N/A'
            
            print(f"{game['away_team']} @ {game['home_team']}: {game['status']}")
            print(f"   Score: {away_score} - {home_score}")
            print(f"   Game ID: {game['espn_game_id']}")
            
            # Show enhanced information from new API structure
            if game.get('game_clock'):
                print(f"   Clock: {game['game_clock']} {game.get('game_period', '')}")
            
            if game.get('venue_name'):
                venue_display = game['venue_name']
                if game.get('venue_city'):
                    venue_display += f" ({game['venue_city']})"
                print(f"   Venue: {venue_display}")
            
            if game.get('broadcasts'):
                print(f"   TV: {', '.join(game['broadcasts'])}")
            
            if game.get('attendance'):
                print(f"   Attendance: {game['attendance']:,}")
            
            # Show enhanced league context
            league_info = game.get('league_info', {})
            if league_info.get('name'):
                season_display = f"{league_info.get('season_year', 'Unknown')}"
                if league_info.get('season_type'):
                    season_display += f" {league_info['season_type']}"
                print(f"   League: {league_info['name']} ({season_display})")
            
            print()
    else:
        print("No games found - testing with historical dates...")
        
        # Test with known game dates during season to verify structure
        test_dates = [
            "2024-01-15",  # Mid-season
            "2024-03-15",  # Late season  
            "2024-11-15",  # Early season
        ]
        
        for test_date in test_dates:
            print(f"Trying {test_date}...")
            games = api.get_scoreboard(test_date)
            if games:
                print(f"✅ Found {len(games)} games for {test_date}")
                print("Enhanced data available: venue, broadcasts, attendance, league info, etc.")
                break
        
        if not games:
            print("No games found on test dates - this might be off-season")
    
    print("\n✅ Enhanced API client ready with support for new metadata fields!")