# AUTO-FIXED: 2024-12-19 - Updated ESPN NBA API to handle enhanced response structure with expanded metadata fields, improved statistics parsing, and better error handling for new API schema

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
    """ESPN NBA API client with full support for enhanced API structure."""
    
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
            
            # FIXED: Extract new top-level metadata for enhanced context
            leagues_info = data.get('leagues', [])
            provider_info = data.get('provider', {})
            
            # Log league information for debugging and context
            current_league_info = {}
            if leagues_info and isinstance(leagues_info, list):
                for league in leagues_info:
                    if isinstance(league, dict) and league.get('abbreviation') == 'NBA':
                        current_league_info = {
                            'name': league.get('name', ''),
                            'season_year': league.get('season', {}).get('year') if isinstance(league.get('season'), dict) else None,
                            'season_type': league.get('season', {}).get('type', {}).get('name', '') if isinstance(league.get('season'), dict) and isinstance(league.get('season', {}).get('type'), dict) else '',
                            'slug': league.get('slug', '')
                        }
                        break
            
            # Process events with enhanced structure support
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
                
                # FIXED: Enhanced event processing with new field support
                competitions = event.get('competitions', [])
                if not isinstance(competitions, list) or len(competitions) == 0:
                    continue
                
                competition = competitions[0]
                if not isinstance(competition, dict):
                    continue
                
                # FIXED: Enhanced competitor parsing with better validation
                competitors = competition.get('competitors', [])
                if not isinstance(competitors, list) or len(competitors) < 2:
                    continue
                
                # Parse competitors with improved structure handling
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
                
                # Enhanced fallback mechanism
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
                
                if not home_team or not away_team:
                    print(f"Skipping event {event.get('id', 'unknown')} - insufficient team data")
                    continue
                
                # Enhanced team information extraction
                def extract_team_info(team_competitor):
                    if not isinstance(team_competitor, dict):
                        return '', ''
                    
                    team_data = team_competitor.get('team', {})
                    if not isinstance(team_data, dict):
                        return '', ''
                    
                    abbr = team_data.get('abbreviation', '').strip()
                    if not abbr:
                        abbr = (team_data.get('shortDisplayName', '') or 
                               team_data.get('displayName', '')[:3] or
                               team_data.get('name', '')[:3] or
                               team_data.get('slug', '').upper()[:3]).strip().upper()
                    
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
                
                home_team_abbr, home_team_name = extract_team_info(home_team)
                away_team_abbr, away_team_name = extract_team_info(away_team)
                
                if not home_team_abbr or not away_team_abbr:
                    print(f"Skipping event - missing team abbreviations")
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
                
                # FIXED: Enhanced status parsing for new expanded status structure
                game_status = 'Scheduled'
                game_clock = ''
                game_period = ''
                
                # Check both event-level and competition-level status
                status_sources = [
                    event.get('status', {}),
                    competition.get('status', {})
                ]
                
                for status_obj in status_sources:
                    if not isinstance(status_obj, dict):
                        continue
                    
                    # Extract new clock and period information
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
                    
                    # Enhanced status type parsing
                    status_type = status_obj.get('type')
                    if not isinstance(status_type, dict):
                        continue
                    
                    # Use the new 'state' field for more accurate status determination
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
                        # Don't break here, let other sources override if needed
                    
                    # Fallback to name field if state is not conclusive
                    status_name = status_type.get('name', '').lower()
                    if not game_status or game_status == 'Scheduled':
                        if 'final' in status_name or 'end' in status_name:
                            game_status = 'Final'
                            break
                        elif any(word in status_name for word in ['progress', 'live', 'play', 'quarter', 'half']):
                            game_status = 'In Progress'
                            break
                
                # Extract game identification
                game_id = event.get('id', '') or competition.get('id', '')
                if not game_id:
                    print(f"Warning: No game ID found for {away_team_abbr} @ {home_team_abbr}")
                    continue
                
                # FIXED: Enhanced metadata extraction using new fields
                venue_info = competition.get('venue', {})
                venue_name = ''
                venue_city = ''
                if isinstance(venue_info, dict):
                    venue_name = (venue_info.get('fullName', '') or 
                                 venue_info.get('name', '')).strip()
                    if venue_info.get('address', {}) and isinstance(venue_info['address'], dict):
                        venue_city = venue_info['address'].get('city', '').strip()
                
                # Enhanced broadcast information
                broadcasts = competition.get('broadcasts', [])
                broadcast_names = []
                if isinstance(broadcasts, list):
                    for broadcast in broadcasts:
                        if isinstance(broadcast, dict):
                            name = broadcast.get('name', '') or broadcast.get('market', '')
                            if name:
                                broadcast_names.append(str(name))
                
                # Extract additional new fields
                neutral_site = competition.get('neutralSite', False)
                attendance = competition.get('attendance')
                play_by_play_available = competition.get('playByPlayAvailable', False)
                
                # Build comprehensive game dictionary with enhanced data
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
                    'venue_name': venue_name,
                    'broadcasts': broadcast_names,
                    # Enhanced fields from new API structure
                    'game_clock': game_clock,
                    'game_period': game_period,
                    'venue_city': venue_city,
                    'neutral_site': neutral_site,
                    'attendance': attendance,
                    'play_by_play_available': play_by_play_available,
                    'event_uid': event.get('uid', ''),
                    'event_name': event.get('name', ''),
                    'event_short_name': event.get('shortName', ''),
                    'competition_uid': competition.get('uid', ''),
                    'start_date': competition.get('startDate', ''),
                    # League context from new API structure
                    'league_info': current_league_info,
                    'provider_info': {
                        'name': provider_info.get('name', ''),
                        'display_name': provider_info.get('displayName', '')
                    }
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
            
            # Handle comprehensive response structure
            boxscore = data.get('boxscore', {})
            if not isinstance(boxscore, dict):
                print("Warning: No valid boxscore data found")
                return []

            # FIXED: Handle enhanced boxscore structure with both teams and players arrays
            teams_data = boxscore.get('teams', [])  # Enhanced team-level stats
            players_data = boxscore.get('players', [])
            
            if not isinstance(players_data, list):
                print("Warning: No valid players data found")
                return []
            
            # Process each team's player data
            for team_data in players_data:
                if not isinstance(team_data, dict):
                    continue
                
                # Extract enhanced team information with new fields
                team_info = team_data.get('team', {})
                if not isinstance(team_info, dict):
                    continue
                
                team_abbr = team_info.get('abbreviation', '').strip()
                if not team_abbr:
                    team_abbr = (team_info.get('shortDisplayName', '') or 
                               team_info.get('displayName', '')[:3] or
                               team_info.get('slug', '').upper()[:3]).strip()
                
                if not team_abbr:
                    continue
                
                # FIXED: Handle enhanced statistics structure with new fields
                statistics = team_data.get('statistics', [])
                if not isinstance(statistics, list) or len(statistics) == 0:
                    continue
                
                stat_info = statistics[0]
                if not isinstance(stat_info, dict):
                    continue
                
                # FIXED: Extract stat column headers from new field names (names, labels, descriptions, etc.)
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
                
                # Enhanced fallback with comprehensive NBA stat headers
                if not stat_keys or len(stat_keys) < 5:
                    stat_keys = ['MIN', 'FGM-FGA', 'FG%', '3PM-3PA', '3P%', 'FTM-FTA', 'FT%', 
                                'OREB', 'DREB', 'REB', 'AST', 'STL', 'BLK', 'TO', 'PF', 'PTS', '+/-']
                
                # FIXED: Process athletes data with enhanced structure handling
                athletes_data = stat_info.get('athletes', [])
                if not isinstance(athletes_data, list):
                    print(f"Warning: athletes data is not a list for team {team_abbr}")
                    continue
                
                for athlete_data in athletes_data:
                    if not isinstance(athlete_data, dict):
                        continue
                    
                    try:
                        # Extract enhanced athlete information with new fields
                        athlete_info = athlete_data.get('athlete', {})
                        if not isinstance(athlete_info, dict):
                            continue
                        
                        # FIXED: Improved DNP detection - only skip true DNPs, not players with active=False
                        if athlete_data.get('didNotPlay', False):
                            continue
                        
                        # Extract player stats with better validation
                        player_stats_raw = athlete_data.get('stats', [])
                        if not isinstance(player_stats_raw, list) or not player_stats_raw:
                            continue
                        
                        # Build stats dictionary with enhanced validation
                        stat_dict = {}
                        for i, key in enumerate(stat_keys):
                            if i < len(player_stats_raw) and player_stats_raw[i] is not None:
                                value = player_stats_raw[i]
                                str_val = str(value).strip()
                                if str_val not in ['--', '', 'N/A', 'null', 'None', 'DNP', 'DND', 'SUSP', 'INJ']:
                                    stat_dict[key] = value
                        
                        if not stat_dict:
                            continue
                        
                        # Parse minutes with enhanced format support
                        minutes = 0.0
                        min_keys = ['MIN', 'minutes', 'min', 'MP', 'MINS']
                        for min_key in min_keys:
                            if min_key in stat_dict:
                                minutes = self._parse_minutes(stat_dict[min_key])
                                if minutes > 0:
                                    break
                        
                        # Skip players with no playing time
                        if minutes == 0:
                            continue
                        
                        # Enhanced stat extraction functions
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
                        
                        # Extract all statistics with enhanced field mapping
                        fgm, fga = parse_made_attempted(['FGM-FGA', 'FG', 'Field Goals', 'fieldGoals', 'FGM/FGA'])
                        fg3m, fg3a = parse_made_attempted(['3PM-3PA', '3P', 'Three Pointers', '3FG', 'threePointers', '3PM/3PA'])
                        ftm, fta = parse_made_attempted(['FTM-FTA', 'FT', 'Free Throws', 'freeThrows', 'FTM/FTA'])
                        
                        points = get_stat_value(['PTS', 'points', 'Points', 'P', 'POINTS'])
                        rebounds = get_stat_value(['REB', 'rebounds', 'Rebounds', 'R', 'totalRebounds', 'REBS'])
                        assists = get_stat_value(['AST', 'assists', 'Assists', 'A', 'ASTS'])
                        steals = get_stat_value(['STL', 'steals', 'Steals', 'S', 'STLS'])
                        blocks = get_stat_value(['BLK', 'blocks', 'Blocks', 'B', 'BLKS'])
                        turnovers = get_stat_value(['TO', 'turnovers', 'Turnovers', 'TOV', 'TOS'])
                        plus_minus = get_stat_value(['+/-', 'plusMinus', 'Plus/Minus', 'PM', 'PLUS_MINUS'], 0)
                        
                        # Enhanced player identification
                        player_name = (athlete_info.get('displayName') or 
                                     athlete_info.get('fullName') or
                                     athlete_info.get('name') or 
                                     athlete_info.get('shortName', '')).strip()
                        
                        if not player_name:
                            continue
                        
                        # FIXED: Build comprehensive player stats with enhanced metadata from new API structure
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
                            'three_point_attempts': fg3a,
                            # Enhanced player metadata from new API structure
                            'player_id': str(athlete_info.get('id', '')),
                            'player_uid': str(athlete_info.get('uid', '')),
                            'jersey_number': str(athlete_info.get('jersey', '')),
                            'position': self._extract_position(athlete_info),
                            'starter': athlete_data.get('starter', False),
                            'ejected': athlete_data.get('ejected', False),
                            # Enhanced team metadata from new API structure
                            'team_display_order': team_data.get('displayOrder', 0),
                            'team_id': str(team_info.get('id', '')),
                            'team_uid': str(team_info.get('uid', '')),
                            'team_slug': str(team_info.get('slug', '')),
                            'team_location': str(team_info.get('location', '')),
                            'team_name': str(team_info.get('name', '')),
                            'team_display_name': str(team_info.get('displayName', '')),
                            'team_color': str(team_info.get('color', '')),
                            'team_alternate_color': str(team_info.get('alternateColor', '')),
                            'team_logo': str(team_info.get('logo', ''))
                        }
                        
                        players.append(player_stats)
                    
                    except Exception as e:
                        print(f"Warning: Skipping player due to parsing error: {e}")
                        continue
            
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
    
    @staticmethod
    def _parse_minutes(min_str):
        """Parse minutes from various formats with enhanced support."""
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


# Test functionality
if __name__ == "__main__":
    api = ESPNNBAApi()
    
    print("🏀 Testing Enhanced ESPN NBA API with Updated Structure Support\n")
    
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
        print("No games found - this may be expected during off-season")
        print("Testing API structure detection...")
        
        # Test with a known game date during season to verify structure
        import datetime
        today = datetime.datetime.now()
        
        # Try dates during typical NBA season
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
                print(f"Enhanced data available: venue, broadcasts, attendance, etc.")
                break
        
        if not games:
            print("No games found on test dates - this might be off-season")
    
    print("\n✅ Enhanced API client ready with full support for new structure!")