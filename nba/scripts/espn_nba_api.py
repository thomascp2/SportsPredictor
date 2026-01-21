# AUTO-FIXED: 2024-12-19 - Updated for ESPN NBA API structural changes: enhanced competitor parsing, improved status detection with new state/completed fields, and better handling of expanded competition metadata

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
    """ESPN NBA API client."""
    
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
            
            # Handle new root-level fields (leagues, provider) - informational only
            leagues_info = data.get('leagues', [])
            provider_info = data.get('provider', {})
            
            # Extract events - core structure maintained
            events = data.get('events', [])
            if not isinstance(events, list):
                print("Warning: events field is not a list or missing")
                return []
            
            for event in events:
                if not isinstance(event, dict):
                    continue
                
                # Extract competitions
                competitions = event.get('competitions', [])
                if not isinstance(competitions, list) or len(competitions) == 0:
                    continue
                
                competition = competitions[0]
                if not isinstance(competition, dict):
                    continue
                
                # FIXED: Improved competitor parsing for new API structure
                competitors = competition.get('competitors', [])
                if not isinstance(competitors, list) or len(competitors) < 2:
                    continue
                
                # Parse competitors with enhanced structure handling
                home_team = None
                away_team = None
                
                for competitor in competitors:
                    if not isinstance(competitor, dict):
                        continue
                    
                    # Check for team data validity first
                    team_data = competitor.get('team', {})
                    if not isinstance(team_data, dict) or not team_data.get('abbreviation'):
                        continue
                    
                    home_away = competitor.get('homeAway', '').lower()
                    if home_away == 'home':
                        home_team = competitor
                    elif home_away == 'away':
                        away_team = competitor
                
                # Enhanced fallback with validation
                if not home_team or not away_team:
                    valid_competitors = []
                    for comp in competitors:
                        if (isinstance(comp, dict) and 
                            isinstance(comp.get('team'), dict) and 
                            comp['team'].get('abbreviation')):
                            valid_competitors.append(comp)
                    
                    if len(valid_competitors) >= 2:
                        # First valid competitor is typically away team
                        away_team = valid_competitors[0]
                        home_team = valid_competitors[1]
                
                if not home_team or not away_team:
                    continue
                
                # Enhanced team information extraction
                def extract_team_info(team_competitor):
                    if not isinstance(team_competitor, dict):
                        return '', ''
                    
                    team_data = team_competitor.get('team', {})
                    if not isinstance(team_data, dict):
                        return '', ''
                    
                    # Primary abbreviation extraction
                    abbr = team_data.get('abbreviation', '').strip()
                    if not abbr:
                        # Enhanced fallback chain
                        abbr = (team_data.get('shortDisplayName', '') or 
                               team_data.get('displayName', '')[:3] or
                               team_data.get('name', '')[:3] or
                               team_data.get('slug', '').upper()[:3]).strip().upper()
                    
                    # Full team name with multiple fallbacks
                    name = (team_data.get('displayName', '') or 
                           team_data.get('name', '') or 
                           team_data.get('longName', '')).strip()
                    
                    # Construct name from location + nickname if needed
                    if not name:
                        location = team_data.get('location', '').strip()
                        nickname = team_data.get('nickname', '').strip()
                        if location and nickname:
                            name = f"{location} {nickname}"
                        elif location or nickname:
                            name = location or nickname
                    
                    return abbr, name
                
                home_team_abbr, home_team_name = extract_team_info(home_team)
                away_team_abbr, away_team_name = extract_team_info(away_team)
                
                if not home_team_abbr or not away_team_abbr:
                    continue
                
                # Enhanced score extraction
                def extract_score(team_competitor):
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
                
                home_score = extract_score(home_team)
                away_score = extract_score(away_team)
                
                # FIXED: Enhanced status parsing for new API structure
                game_status = 'Scheduled'
                
                # New API provides status at both event and competition levels
                # Event status is typically more reliable and comprehensive
                status_sources = [
                    event.get('status', {}),
                    competition.get('status', {})
                ]
                
                for status_obj in status_sources:
                    if not isinstance(status_obj, dict):
                        continue
                    
                    status_type = status_obj.get('type')
                    if not status_type:
                        continue
                    
                    # FIXED: Handle new enhanced status.type structure
                    if isinstance(status_type, dict):
                        # New API provides definitive state indicators
                        state = status_type.get('state', '').lower()
                        completed = status_type.get('completed')
                        
                        # Primary status detection using new reliable fields
                        if completed is True:
                            game_status = 'Final'
                            break
                        elif state == 'post':
                            game_status = 'Final'
                            break
                        elif state == 'in':
                            game_status = 'In Progress'
                            break
                        elif state == 'pre':
                            game_status = 'Scheduled'
                        
                        # Secondary detection using text fields for edge cases
                        name = status_type.get('name', '').upper()
                        detail = status_type.get('detail', '').upper()
                        short_detail = status_type.get('shortDetail', '').upper()
                        description = status_type.get('description', '').upper()
                        
                        all_text = f"{name} {detail} {short_detail} {description}".upper()
                        
                        # Enhanced keyword detection for special states
                        if any(word in all_text for word in ['FINAL', 'GAME OVER', 'ENDED']):
                            game_status = 'Final'
                            break
                        elif any(word in all_text for word in ['HALFTIME', 'HALF', '1ST', '2ND', '3RD', '4TH', 'OVERTIME', 'OT', 'LIVE']):
                            game_status = 'In Progress'
                            break
                        elif any(word in all_text for word in ['POSTPONED', 'DELAYED', 'CANCELLED', 'SUSPENDED']):
                            game_status = 'Postponed'
                            break
                    
                    # Backup: Handle legacy string format
                    elif isinstance(status_type, str):
                        status_name = status_type.upper()
                        if 'FINAL' in status_name:
                            game_status = 'Final'
                            break
                        elif any(keyword in status_name for keyword in ['PROGRESS', 'LIVE', 'QUARTER']):
                            game_status = 'In Progress'
                            break
                    
                    # Additional validation using clock/period data
                    clock = status_obj.get('displayClock') or status_obj.get('clock')
                    period = status_obj.get('period')
                    
                    if clock or period:
                        try:
                            # If there's active clock or period info, game is likely in progress
                            if clock and str(clock).strip() not in ['0:00', '', '00:00', 'N/A', '0.0']:
                                if game_status == 'Scheduled':
                                    game_status = 'In Progress'
                            if period and int(period) > 0:
                                if game_status == 'Scheduled':
                                    game_status = 'In Progress'
                        except (ValueError, TypeError):
                            pass
                
                # Extract game ID with enhanced methods
                game_id = event.get('id', '')
                
                if not game_id:
                    game_id = competition.get('id', '')
                
                # Enhanced UID parsing for various formats
                if not game_id:
                    uid = event.get('uid', '')
                    if uid:
                        # Handle different UID formats: s:40~l:46~e:401584893
                        if '~e:' in uid:
                            parts = uid.split('~')
                            for part in parts:
                                if part.startswith('e:'):
                                    game_id = part[2:]
                                    break
                        elif ':' in uid:
                            # Simple colon-separated format
                            game_id = uid.split(':')[-1]
                
                if not game_id:
                    continue
                
                # Extract enhanced metadata from new API fields
                venue_info = competition.get('venue', {})
                venue_name = ''
                if isinstance(venue_info, dict):
                    venue_name = (venue_info.get('fullName', '') or 
                                 venue_info.get('name', '')).strip()
                
                # Enhanced broadcast extraction
                broadcasts = competition.get('broadcasts', [])
                broadcast_names = []
                if isinstance(broadcasts, list):
                    for broadcast in broadcasts:
                        if isinstance(broadcast, dict):
                            # Try multiple broadcast name fields
                            name = (broadcast.get('name', '') or
                                   broadcast.get('names', [''])[0] if broadcast.get('names') else '')
                            if not name and broadcast.get('market'):
                                market = broadcast['market']
                                if isinstance(market, dict):
                                    name = market.get('name', '')
                            if name:
                                broadcast_names.append(str(name))
                        elif isinstance(broadcast, str):
                            broadcast_names.append(broadcast)
                
                # Enhanced attendance parsing
                attendance = 0
                try:
                    attendance_val = competition.get('attendance')
                    if attendance_val:
                        attendance = int(float(str(attendance_val).replace(',', '')))
                except (ValueError, TypeError):
                    attendance = 0
                
                # Build comprehensive game dictionary
                game_info = {
                    # Core required fields (backward compatibility)
                    'game_id': str(game_id),
                    'game_date': game_date,
                    'home_team': home_team_abbr,
                    'away_team': away_team_abbr,
                    'status': game_status,
                    'home_score': home_score,
                    'away_score': away_score,
                    'espn_game_id': str(game_id),
                    
                    # Enhanced fields from new API structure
                    'home_team_name': home_team_name,
                    'away_team_name': away_team_name,
                    'event_name': event.get('name', ''),
                    'short_name': event.get('shortName', ''),
                    'venue_name': venue_name,
                    'broadcasts': broadcast_names,
                    'attendance': attendance,
                    'neutral_site': bool(competition.get('neutralSite', False)),
                    'event_uid': event.get('uid', ''),
                    'season_info': event.get('season', {}),
                    'start_date': competition.get('startDate', ''),
                    'competition_date': competition.get('date', ''),
                    'play_by_play_available': bool(competition.get('playByPlayAvailable', False)),
                    'conference_competition': bool(competition.get('conferenceCompetition', False)),
                    'time_valid': bool(competition.get('timeValid', True)),
                    'competition_uid': competition.get('uid', ''),
                    'competition_format': competition.get('format', {}),
                    'recent': bool(competition.get('recent', False))
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
            
            # Handle boxscore structure
            boxscore = data.get('boxscore', {})
            if not isinstance(boxscore, dict):
                return []
            
            players_data = boxscore.get('players', [])
            if not isinstance(players_data, list):
                return []
            
            for team_data in players_data:
                if not isinstance(team_data, dict):
                    continue
                
                # Extract team information
                team_info = team_data.get('team', {})
                if not isinstance(team_info, dict):
                    continue
                
                team_abbr = (team_info.get('abbreviation') or 
                           team_info.get('shortDisplayName') or
                           team_info.get('displayName', '')[:3] or
                           team_info.get('slug', '').upper()[:3]).strip()
                
                if not team_abbr:
                    continue
                
                # Handle statistics structure
                statistics = team_data.get('statistics', [])
                if not isinstance(statistics, list) or len(statistics) == 0:
                    continue
                
                stat_info = statistics[0]
                if not isinstance(stat_info, dict):
                    continue
                
                # Extract stat column headers
                stat_keys = []
                header_fields = ['names', 'labels', 'keys', 'headers']
                for field in header_fields:
                    if field in stat_info and isinstance(stat_info[field], list):
                        stat_keys = [str(k).strip() for k in stat_info[field] if k is not None]
                        break
                
                # Fallback to standard NBA stats
                if not stat_keys or len(stat_keys) < 10:
                    stat_keys = ['MIN', 'FGM-FGA', 'FG%', '3PM-3PA', '3P%', 'FTM-FTA', 'FT%', 
                                'OREB', 'DREB', 'REB', 'AST', 'STL', 'BLK', 'TO', 'PF', 'PTS', '+/-']
                
                # Process athletes data
                athletes_data = stat_info.get('athletes', [])
                if not isinstance(athletes_data, list):
                    continue
                
                for athlete_data in athletes_data:
                    if not isinstance(athlete_data, dict):
                        continue
                    
                    try:
                        # Extract athlete information
                        athlete_info = athlete_data.get('athlete', {})
                        if not isinstance(athlete_info, dict):
                            continue
                        
                        # Check if player actually played
                        if (athlete_data.get('didNotPlay', False) or
                            athlete_data.get('inactive', False)):
                            continue
                        
                        # Extract player stats
                        player_stats_raw = athlete_data.get('stats', [])
                        if not isinstance(player_stats_raw, list) or not player_stats_raw:
                            continue
                        
                        # Build stats dictionary
                        stat_dict = {}
                        for i, key in enumerate(stat_keys):
                            if i < len(player_stats_raw) and player_stats_raw[i] is not None:
                                value = player_stats_raw[i]
                                str_val = str(value).strip()
                                if str_val not in ['--', '', 'N/A', 'null', 'None', 'DNP', 'DND']:
                                    stat_dict[key] = value
                        
                        if not stat_dict:
                            continue
                        
                        # Parse minutes
                        minutes = 0.0
                        min_keys = ['MIN', 'minutes', 'min', 'MP']
                        for min_key in min_keys:
                            if min_key in stat_dict:
                                minutes = self._parse_minutes(stat_dict[min_key])
                                if minutes > 0:
                                    break
                        
                        if minutes == 0:
                            continue
                        
                        # Helper functions for stat extraction
                        def parse_made_attempted(keys):
                            for key in keys:
                                if key in stat_dict:
                                    val_str = str(stat_dict[key]).strip()
                                    if '-' in val_str and val_str.count('-') == 1:
                                        try:
                                            made, attempted = val_str.split('-')
                                            return int(float(made.strip())), int(float(attempted.strip()))
                                        except (ValueError, AttributeError):
                                            continue
                                    elif '/' in val_str and val_str.count('/') == 1:
                                        try:
                                            made, attempted = val_str.split('/')
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
                                        if val_str.startswith('-') and len(val_str) > 1:
                                            if val_str[1:].replace('.', '').isdigit():
                                                return -int(float(val_str[1:]))
                                        if val_str.replace('.', '').replace('-', '').isdigit():
                                            return int(float(val_str))
                                    except (ValueError, TypeError, AttributeError):
                                        continue
                            return default
                        
                        # Extract shooting stats
                        fgm, fga = parse_made_attempted(['FGM-FGA', 'FG', 'Field Goals'])
                        fg3m, fg3a = parse_made_attempted(['3PM-3PA', '3P', 'Three Pointers', '3FG'])
                        ftm, fta = parse_made_attempted(['FTM-FTA', 'FT', 'Free Throws'])
                        
                        # Extract counting stats
                        points = get_stat_value(['PTS', 'points', 'Points', 'P'])
                        rebounds = get_stat_value(['REB', 'rebounds', 'Rebounds', 'R'])
                        assists = get_stat_value(['AST', 'assists', 'Assists', 'A'])
                        steals = get_stat_value(['STL', 'steals', 'Steals', 'S'])
                        blocks = get_stat_value(['BLK', 'blocks', 'Blocks', 'B'])
                        turnovers = get_stat_value(['TO', 'turnovers', 'Turnovers', 'TOV'])
                        plus_minus = get_stat_value(['+/-', 'plusMinus', 'Plus/Minus', 'PM'], 0)
                        
                        # Extract player name
                        player_name = (athlete_info.get('displayName') or 
                                     athlete_info.get('name') or 
                                     athlete_info.get('fullName') or
                                     athlete_info.get('shortName', '')).strip()
                        
                        if not player_name:
                            continue
                        
                        # Build player stats object
                        player_stats = {
                            'game_id': str(game_id),
                            'player_name': player_name,
                            'team': team_abbr,
                            'minutes': float(minutes),
                            'points': points,
                            'rebounds': rebounds,
                            'assists': assists,
                            'steals': steals,
                            'blocks': blocks,
                            'turnovers': turnovers,
                            'threes_made': fg3m,
                            'fga': fga,
                            'fgm': fgm,
                            'fta': fta,
                            'ftm': ftm,
                            'plus_minus': plus_minus,
                            
                            # Additional enhanced stats
                            'three_point_attempts': fg3a,
                            'player_id': athlete_info.get('id', ''),
                            'jersey_number': athlete_info.get('jersey', ''),
                            'position': (athlete_info.get('position', {}).get('abbreviation', '') 
                                       if isinstance(athlete_info.get('position'), dict) 
                                       else str(athlete_info.get('position', '')))
                        }
                        
                        players.append(player_stats)
                    
                    except Exception as e:
                        print(f"Warning: Skipping player due to parsing error: {e}")
                        continue
            
            time.sleep(0.3)  # Rate limiting
            return players
            
        except requests.exceptions.RequestException as e:
            print(f"ESPN boxscore request error: {e}")
            return []
        except Exception as e:
            print(f"ESPN boxscore parsing error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    @staticmethod
    def _parse_minutes(min_str):
        """Parse minutes from various formats: MM:SS, decimal, or integer."""
        if not min_str or str(min_str).strip() in ['--', '', 'N/A', 'None', 'null', 'DNP', 'DND']:
            return 0.0
        
        try:
            min_str = str(min_str).strip()
            
            if ':' in min_str:
                # MM:SS format
                parts = min_str.split(':')
                if len(parts) == 2:
                    minutes, seconds = parts
                    return float(minutes) + (float(seconds) / 60.0)
            else:
                # Decimal or integer format
                value = float(min_str)
                # Handle edge case of seconds being passed as total
                if value > 100:  # Likely seconds, convert to minutes
                    return value / 60.0
                return value
        except (ValueError, TypeError, AttributeError):
            pass
        
        return 0.0


# Test functionality
if __name__ == "__main__":
    api = ESPNNBAApi()
    
    print("🏀 Testing ESPN NBA API with Updated Structure Support\n")
    
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
            
            # Show enhanced information
            if game.get('venue_name'):
                print(f"   Venue: {game['venue_name']}")
            if game.get('broadcasts'):
                print(f"   TV: {', '.join(game['broadcasts'])}")
            if game.get('attendance', 0) > 0:
                print(f"   Attendance: {game['attendance']:,}")
            print()
        
        # Test boxscore on first completed game
        completed_games = [g for g in games if g['status'] == 'Final']
        if completed_games:
            print(f"Testing boxscore for completed game...")
            boxscore = api.get_boxscore(completed_games[0]['espn_game_id'])
            print(f"✅ Retrieved {len(boxscore)} player stats\n")
            
            if boxscore:
                print("Sample player stats:")
                for player in boxscore[:5]:
                    pos = f"({player.get('position', 'N/A')})" if player.get('position') else ""
                    jersey = f"#{player.get('jersey_number', '')}" if player.get('jersey_number') else ""
                    print(f"  {player['player_name']:20} {jersey:4} {pos:4} {player['team']:4} "
                          f"{player['points']:2}pts {player['rebounds']:2}reb "
                          f"{player['assists']:2}ast ({player['minutes']:.1f}min)")
        else:
            print("No completed games found for boxscore test")
    else:
        print("No games found - testing with recent date...")
        
        # Test with recent date
        import datetime
        recent_date = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        print(f"Trying {recent_date}...")
        games = api.get_scoreboard(recent_date)
        print(f"Found {len(games)} games for {recent_date}")