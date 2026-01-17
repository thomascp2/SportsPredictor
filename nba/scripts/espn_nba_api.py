# AUTO-FIXED: 2024-12-19 - Updated to handle ESPN NBA API v2 structure with enhanced events, competitions, competitors, and status fields

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
            
            # FIXED: Handle new API v2 structure - extract league and provider info safely
            leagues = data.get('leagues', [])
            league_info = {}
            if leagues and isinstance(leagues, list) and len(leagues) > 0:
                league_data = leagues[0]
                if isinstance(league_data, dict):
                    league_info = {
                        'name': league_data.get('name', 'NBA'),
                        'abbreviation': league_data.get('abbreviation', 'NBA'),
                        'season': league_data.get('season', {})
                    }
            
            # Extract provider information if available
            provider_info = data.get('provider', {})
            
            # Core events processing - same as before but more robust
            events = data.get('events', [])
            if not isinstance(events, list):
                print("Warning: events field is not a list or missing")
                return []
            
            for event in events:
                if not isinstance(event, dict):
                    continue
                
                # Extract competitions with validation
                competitions = event.get('competitions', [])
                if not isinstance(competitions, list) or len(competitions) == 0:
                    continue
                
                competition = competitions[0]
                if not isinstance(competition, dict):
                    continue
                
                # FIXED: Enhanced competitors parsing - handle expanded competitor structure
                competitors = competition.get('competitors', [])
                if not isinstance(competitors, list) or len(competitors) < 2:
                    continue
                
                # Parse competitors - the core structure is still there, just with more fields
                home_team = None
                away_team = None
                
                for competitor in competitors:
                    if not isinstance(competitor, dict):
                        continue
                    
                    home_away = competitor.get('homeAway', '').lower()
                    if home_away == 'home':
                        home_team = competitor
                    elif home_away == 'away':
                        away_team = competitor
                
                # Fallback if homeAway detection failed
                if not home_team or not away_team:
                    if len(competitors) >= 2:
                        away_team = competitors[0]
                        home_team = competitors[1]
                
                if not home_team or not away_team:
                    continue
                
                # FIXED: Robust team information extraction for expanded competitor structure
                def extract_team_info(team_obj):
                    if not isinstance(team_obj, dict):
                        return '', ''
                    
                    team_data = team_obj.get('team', {})
                    if not isinstance(team_data, dict):
                        return '', ''
                    
                    # Get abbreviation - core field should still be there
                    abbr = (team_data.get('abbreviation') or 
                           team_data.get('shortDisplayName') or
                           team_data.get('displayName', '')[:3].upper() or
                           team_data.get('name', '')[:3].upper())
                    
                    # Get full name with fallbacks for new structure
                    name = (team_data.get('displayName') or 
                           team_data.get('name') or 
                           team_data.get('longName') or '')
                    
                    # Construct name from parts if needed
                    if not name:
                        location = team_data.get('location', '')
                        team_name = team_data.get('name', '')
                        if location and team_name:
                            name = f"{location} {team_name}"
                        else:
                            name = location or team_name
                    
                    return str(abbr).strip(), str(name).strip()
                
                home_team_abbr, home_team_name = extract_team_info(home_team)
                away_team_abbr, away_team_name = extract_team_info(away_team)
                
                if not home_team_abbr or not away_team_abbr:
                    continue
                
                # FIXED: Enhanced score extraction - handle expanded competitor structure
                def extract_score(team_obj):
                    if not isinstance(team_obj, dict):
                        return None
                    
                    score_value = team_obj.get('score')
                    if score_value is None or score_value == '':
                        return None
                    
                    try:
                        score_str = str(score_value).strip()
                        if score_str and score_str not in ['--', '', 'null', 'undefined', 'None']:
                            return int(float(score_str))
                    except (ValueError, TypeError):
                        pass
                    
                    return None
                
                home_score = extract_score(home_team)
                away_score = extract_score(away_team)
                
                # FIXED: Enhanced status parsing for new API v2 structure
                game_status = 'Scheduled'
                
                # Try competition status first, then event status
                status_sources = [
                    competition.get('status', {}),
                    event.get('status', {})
                ]
                
                for status_obj in status_sources:
                    if not isinstance(status_obj, dict):
                        continue
                    
                    status_type = status_obj.get('type')
                    if not status_type:
                        continue
                    
                    # FIXED: Handle enhanced status type structure with new fields
                    if isinstance(status_type, dict):
                        # New v2 status structure includes state, completed, detail, etc.
                        state = status_type.get('state', '').lower()
                        completed = status_type.get('completed', False)
                        name = status_type.get('name', '').upper()
                        detail = status_type.get('detail', '').upper()
                        short_detail = status_type.get('shortDetail', '').upper()
                        description = status_type.get('description', '').upper()
                        
                        # Primary detection using state field (most reliable)
                        if completed or state == 'post':
                            game_status = 'Final'
                            break
                        elif state == 'in':
                            game_status = 'In Progress'
                            break
                        elif state == 'pre':
                            game_status = 'Scheduled'
                        
                        # Secondary detection using text content for robustness
                        status_text = f"{name} {detail} {short_detail} {description}".upper()
                        
                        if any(term in status_text for term in ['FINAL', 'ENDED', 'COMPLETE', 'FINISHED']):
                            game_status = 'Final'
                            break
                        elif any(term in status_text for term in ['PROGRESS', 'LIVE', 'HALFTIME', 'QUARTER', '1ST', '2ND', '3RD', '4TH', 'OT', 'OVERTIME']):
                            game_status = 'In Progress'
                            break
                        elif any(term in status_text for term in ['POSTPONED', 'DELAYED', 'CANCELLED', 'SUSPENDED']):
                            game_status = 'Postponed'
                            break
                    
                    elif isinstance(status_type, str):
                        # Fallback for simple string status (legacy support)
                        status_name = status_type.upper()
                        if 'FINAL' in status_name:
                            game_status = 'Final'
                            break
                        elif any(term in status_name for term in ['PROGRESS', 'LIVE', 'IN']):
                            game_status = 'In Progress'
                            break
                    
                    # Additional check using new clock/period information
                    if game_status == 'Scheduled':
                        clock = status_obj.get('displayClock') or status_obj.get('clock')
                        period = status_obj.get('period', 0)
                        
                        # If there's clock time or period info, game is likely in progress
                        if (clock and str(clock).strip() not in ['0:00', '', '00:00']) or (isinstance(period, (int, float)) and period > 0):
                            game_status = 'In Progress'
                            break
                
                # Extract game ID - multiple methods for robustness
                game_id = event.get('id', '')
                
                if not game_id:
                    # Try to extract from UID (new field in v2)
                    uid = event.get('uid', '')
                    if uid and '~e:' in uid:
                        parts = uid.split('~')
                        for part in parts:
                            if part.startswith('e:'):
                                game_id = part[2:]
                                break
                
                if not game_id:
                    game_id = competition.get('id', '') or competition.get('uid', '')
                
                if not game_id:
                    continue
                
                # FIXED: Extract additional metadata from expanded API v2 structure
                season_info = event.get('season', {})
                season_year = 0
                if isinstance(season_info, dict):
                    year_val = season_info.get('year', 0)
                    try:
                        season_year = int(year_val) if year_val else 0
                    except (ValueError, TypeError):
                        season_year = 0
                
                # Venue information from enhanced structure
                venue_info = competition.get('venue', {})
                venue_name = ''
                venue_indoor = None
                if isinstance(venue_info, dict):
                    venue_name = venue_info.get('fullName', '') or venue_info.get('name', '')
                    venue_indoor = venue_info.get('indoor')
                
                # Attendance from enhanced data
                attendance = 0
                if competition.get('attendance'):
                    try:
                        attendance = int(competition['attendance'])
                    except (ValueError, TypeError):
                        attendance = 0
                
                # Broadcast information from enhanced structure
                broadcasts = competition.get('broadcasts', [])
                broadcast_info = []
                if isinstance(broadcasts, list):
                    for broadcast in broadcasts:
                        if isinstance(broadcast, dict):
                            name = broadcast.get('name') or broadcast.get('shortName')
                            if name:
                                broadcast_info.append(str(name))
                
                # Build game info with enhanced v2 data while maintaining compatibility
                game_info = {
                    # Core fields for backward compatibility
                    'game_id': str(game_id),
                    'game_date': game_date,
                    'home_team': home_team_abbr,
                    'away_team': away_team_abbr,
                    'status': game_status,
                    'home_score': home_score,
                    'away_score': away_score,
                    'espn_game_id': str(game_id),
                    
                    # Enhanced metadata from API v2
                    'home_team_name': home_team_name,
                    'away_team_name': away_team_name,
                    'event_name': event.get('name', ''),
                    'event_short_name': event.get('shortName', ''),
                    'event_uid': event.get('uid', ''),
                    'season_year': season_year,
                    'event_date': event.get('date', ''),
                    'competition_id': competition.get('id', ''),
                    'venue_name': venue_name,
                    'venue_indoor': venue_indoor,
                    'attendance': attendance,
                    'neutral_site': bool(competition.get('neutralSite', False)),
                    'conference_competition': bool(competition.get('conferenceCompetition', False)),
                    'play_by_play_available': bool(competition.get('playByPlayAvailable', False)),
                    'broadcasts': broadcast_info,
                    'competition_recent': bool(competition.get('recent', False)),
                    'time_valid': bool(competition.get('timeValid', True)),
                    'start_date': competition.get('startDate', ''),
                    'league_info': league_info,
                    'provider_info': provider_info
                }
                
                games.append(game_info)
            
            return games
            
        except requests.exceptions.RequestException as e:
            print(f"ESPN API request error: {e}")
            return []
        except Exception as e:
            print(f"ESPN API parsing error: {e}")
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
            
            # Handle boxscore structure - enhanced but core structure maintained
            boxscore = data.get('boxscore', {})
            if not isinstance(boxscore, dict):
                return []
            
            # Handle players array structure
            players_data = boxscore.get('players', [])
            if not isinstance(players_data, list):
                return []
            
            for team_data in players_data:
                if not isinstance(team_data, dict):
                    continue
                
                # Enhanced team info extraction
                team_info = team_data.get('team', {})
                if not isinstance(team_info, dict):
                    continue
                
                team_abbr = (team_info.get('abbreviation') or 
                           team_info.get('shortDisplayName') or
                           team_info.get('displayName', '')[:3] or
                           team_info.get('name', '')[:3]).strip()
                
                if not team_abbr:
                    continue
                
                # Handle statistics structure
                statistics = team_data.get('statistics', [])
                if not isinstance(statistics, list) or len(statistics) == 0:
                    continue
                
                stat_info = statistics[0]
                if not isinstance(stat_info, dict):
                    continue
                
                # Extract stat headers - enhanced for v2 structure
                stat_keys = []
                
                if 'names' in stat_info and isinstance(stat_info['names'], list):
                    stat_keys = [str(k).strip() for k in stat_info['names'] if k is not None]
                elif 'labels' in stat_info and isinstance(stat_info['labels'], list):
                    stat_keys = [str(k).strip() for k in stat_info['labels'] if k is not None]
                elif 'descriptions' in stat_info and isinstance(stat_info['descriptions'], list):
                    stat_keys = [str(k).strip() for k in stat_info['descriptions'] if k is not None]
                elif 'keys' in stat_info:
                    keys_data = stat_info['keys']
                    if isinstance(keys_data, list):
                        stat_keys = [str(k).strip() for k in keys_data if k is not None]
                    elif isinstance(keys_data, str):
                        if ',' in keys_data:
                            stat_keys = [k.strip() for k in keys_data.split(',')]
                        else:
                            stat_keys = [keys_data.strip()]
                
                # Fallback to standard NBA stats
                if not stat_keys:
                    stat_keys = ['MIN', 'FGM-FGA', 'FG%', '3PM-3PA', '3P%', 'FTM-FTA', 'FT%', 
                                'OREB', 'DREB', 'REB', 'AST', 'STL', 'BLK', 'TO', 'PF', 'PTS', '+/-']
                
                # Handle athletes data structure
                athletes_data = stat_info.get('athletes', [])
                
                if not isinstance(athletes_data, list):
                    if isinstance(athletes_data, dict):
                        athletes_data = (athletes_data.get('items', []) or 
                                       athletes_data.get('data', []) or 
                                       athletes_data.get('players', []) or [])
                    else:
                        continue
                
                for athlete_data in athletes_data:
                    if not isinstance(athlete_data, dict):
                        continue
                    
                    try:
                        # Enhanced athlete info extraction
                        athlete_info = athlete_data.get('athlete', {})
                        if not isinstance(athlete_info, dict):
                            continue
                        
                        # Check if player played
                        did_not_play = athlete_data.get('didNotPlay', False)
                        if isinstance(did_not_play, bool) and did_not_play:
                            continue
                        elif isinstance(did_not_play, str) and did_not_play.lower() in ['true', 'yes', '1']:
                            continue
                        
                        # Get stats with enhanced handling
                        player_stats_data = athlete_data.get('stats', [])
                        
                        if not isinstance(player_stats_data, list):
                            if isinstance(player_stats_data, dict):
                                player_stats_data = list(player_stats_data.values()) if player_stats_data else []
                            elif isinstance(player_stats_data, str):
                                if ',' in player_stats_data:
                                    player_stats_data = [v.strip() for v in player_stats_data.split(',')]
                                else:
                                    player_stats_data = [player_stats_data.strip()]
                            else:
                                continue
                        
                        if not player_stats_data:
                            continue
                        
                        # Build stats dictionary
                        stat_dict = {}
                        for i, key in enumerate(stat_keys):
                            if i < len(player_stats_data) and player_stats_data[i] is not None:
                                value = player_stats_data[i]
                                value_str = str(value).strip()
                                if value_str and value_str not in ['--', '', 'N/A', 'null', 'undefined', 'None']:
                                    stat_dict[key] = value
                        
                        if not stat_dict:
                            continue
                        
                        # Parse minutes
                        minutes = 0.0
                        for min_key in ['MIN', 'minutes', 'min', 'Minutes', 'MP']:
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
                                    if '-' in val_str:
                                        try:
                                            parts = val_str.split('-')
                                            if len(parts) >= 2:
                                                made = int(float(parts[0].strip()))
                                                attempted = int(float(parts[1].strip()))
                                                return made, attempted
                                        except (ValueError, IndexError):
                                            continue
                            return 0, 0
                        
                        def get_stat_value(keys, default=0):
                            for key in keys:
                                if key in stat_dict and stat_dict[key] is not None:
                                    val_str = str(stat_dict[key]).strip()
                                    if val_str not in ['--', '', 'N/A', 'null', 'undefined']:
                                        try:
                                            if val_str.startswith('+'):
                                                val_str = val_str[1:]
                                            return int(float(val_str))
                                        except (ValueError, TypeError):
                                            continue
                            return default
                        
                        # Extract shooting stats
                        fgm, fga = parse_made_attempted(['FGM-FGA', 'FG', 'Field Goals'])
                        fg3m, _ = parse_made_attempted(['3PM-3PA', '3P', '3PT', '3-Point Field Goals'])
                        ftm, fta = parse_made_attempted(['FTM-FTA', 'FT', 'Free Throws'])
                        
                        # Extract counting stats
                        points = get_stat_value(['PTS', 'points', 'Points'])
                        rebounds = get_stat_value(['REB', 'rebounds', 'Total Rebounds'])
                        assists = get_stat_value(['AST', 'assists', 'Assists'])
                        steals = get_stat_value(['STL', 'steals', 'Steals'])
                        blocks = get_stat_value(['BLK', 'blocks', 'Blocks'])
                        turnovers = get_stat_value(['TO', 'turnovers', 'Turnovers'])
                        plus_minus = get_stat_value(['+/-', 'plusMinus', 'Plus/Minus'], 0)
                        
                        # Extract rebound breakdown
                        oreb = get_stat_value(['OREB', 'offensiveRebounds', 'Offensive Rebounds'])
                        dreb = get_stat_value(['DREB', 'defensiveRebounds', 'Defensive Rebounds'])
                        
                        if rebounds == 0 and (oreb > 0 or dreb > 0):
                            rebounds = oreb + dreb
                        
                        # Enhanced player name extraction
                        player_name = (athlete_info.get('displayName') or 
                                     athlete_info.get('name') or 
                                     athlete_info.get('fullName') or
                                     athlete_info.get('shortName') or '')
                        
                        if not player_name:
                            first = athlete_info.get('firstName', '').strip()
                            last = athlete_info.get('lastName', '').strip()
                            if first and last:
                                player_name = f"{first} {last}"
                            elif first or last:
                                player_name = first or last
                        
                        if not player_name:
                            continue
                        
                        # Build player stats object
                        player_stats = {
                            'game_id': str(game_id),
                            'player_name': player_name.strip(),
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
                            'plus_minus': plus_minus
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
            return []
    
    @staticmethod
    def _parse_minutes(min_str):
        """Parse minutes from various formats: MM:SS, decimal, or integer."""
        if not min_str or str(min_str).strip() in ['--', '', 'N/A', 'None', 'null']:
            return 0.0
        
        try:
            min_str = str(min_str).strip()
            
            if ':' in min_str:
                # MM:SS format
                parts = min_str.split(':')
                if len(parts) >= 2:
                    minutes = int(parts[0]) if parts[0].strip().isdigit() else 0
                    seconds = int(parts[1]) if parts[1].strip().isdigit() else 0
                    return float(minutes) + (float(seconds) / 60.0)
            else:
                # Decimal or integer format
                return float(min_str.replace(',', ''))
        except (ValueError, TypeError, IndexError):
            pass
        
        return 0.0


# Test functionality
if __name__ == "__main__":
    api = ESPNNBAApi()
    
    print("🏀 Testing ESPN NBA API v2 Compatibility\n")
    
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
            
            # Show enhanced API v2 metadata
            if game.get('season_year'):
                print(f"   Season: {game['season_year']}")
            if game.get('venue_name'):
                print(f"   Venue: {game['venue_name']}")
            if game.get('attendance') and game['attendance'] > 0:
                print(f"   Attendance: {game['attendance']:,}")
            if game.get('broadcasts'):
                print(f"   TV: {', '.join(game['broadcasts'])}")
            print()
        
        # Test boxscore on first completed game
        completed_games = [g for g in games if g['status'] == 'Final']
        if completed_games:
            print(f"Testing boxscore for completed game...")
            boxscore = api.get_boxscore(completed_games[0]['espn_game_id'])
            print(f"✅ Retrieved {len(boxscore)} player stats\n")
            
            if boxscore:
                print("Sample player stats:")
                for player in boxscore[:5]:  # Show first 5 players
                    print(f"  {player['player_name']:20} {player['team']:4} "
                          f"{player['points']:2}pts {player['rebounds']:2}reb "
                          f"{player['assists']:2}ast ({player['minutes']:.1f}min)")
        else:
            print("No completed games found for boxscore test")
    else:
        print("No games found - API may be working but no games scheduled")