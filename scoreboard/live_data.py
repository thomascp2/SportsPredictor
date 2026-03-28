"""
Live Data Fetcher
Pulls scores and player stats from ESPN, NHL, and MLB APIs.
All functions return empty dicts/lists on failure — never raise.
"""
import sys
import requests
from pathlib import Path
from datetime import datetime, timezone

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / 'nba' / 'scripts'))
sys.path.insert(0, str(_ROOT / 'nhl' / 'scripts'))
sys.path.insert(0, str(_ROOT / 'mlb' / 'scripts'))


def _to_local(utc_str):
    if not utc_str:
        return ''
    try:
        dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
        return dt.astimezone().strftime('%I:%M %p').lstrip('0')
    except Exception:
        return ''


# ─── Game Schedules ───────────────────────────────────────────────────────────

def nba_games(game_date):
    try:
        from espn_nba_api import ESPNNBAApi
        raw = ESPNNBAApi().get_scoreboard(game_date)
        out = []
        for g in raw:
            s = g.get('status', '')
            if 'Final' in s or s.lower() == 'final':
                status = 'final'
            elif 'Progress' in s or 'Halftime' in s or s.lower() == 'in_progress':
                status = 'live'
            else:
                status = 'scheduled'
            out.append({
                'game_id': str(g.get('espn_game_id') or g.get('game_id', '')),
                'sport': 'NBA',
                'away_team': g.get('away_team', ''),
                'home_team': g.get('home_team', ''),
                'away_score': g.get('away_score'),
                'home_score': g.get('home_score'),
                'status': status,
                'period': g.get('game_period', ''),
                'clock': g.get('game_clock', ''),
                'start_time_local': _to_local(g.get('start_date', '')),
            })
        return out
    except Exception:
        return []


def nhl_games(game_date):
    try:
        r = requests.get(f'https://api-web.nhle.com/v1/schedule/{game_date}', timeout=10)
        if r.status_code != 200:
            return []
        out = []
        for day in r.json().get('gameWeek', []):
            if day.get('date') != game_date:
                continue
            for g in day.get('games', []):
                state = g.get('gameState', 'FUT')
                status = ('final' if state in ('FINAL', 'OFF')
                          else 'live' if state in ('LIVE', 'CRIT')
                          else 'scheduled')
                pd = g.get('periodDescriptor', {})
                period = ''
                if pd.get('number'):
                    ptype = pd.get('periodType', 'REG')
                    period = 'OT' if ptype == 'OT' else ('SO' if ptype == 'SO' else f"P{pd['number']}")
                clock = g.get('clock', {}).get('timeRemaining', '') if status == 'live' else ''
                away, home = g.get('awayTeam', {}), g.get('homeTeam', {})
                out.append({
                    'game_id': str(g.get('id', '')),
                    'sport': 'NHL',
                    'away_team': away.get('abbrev', ''),
                    'home_team': home.get('abbrev', ''),
                    'away_score': away.get('score'),
                    'home_score': home.get('score'),
                    'status': status,
                    'period': period,
                    'clock': clock,
                    'start_time_local': _to_local(g.get('startTimeUTC', '')),
                })
        return out
    except Exception:
        return []


def mlb_games(game_date):
    try:
        r = requests.get(
            'https://statsapi.mlb.com/api/v1/schedule',
            params={'date': game_date, 'sportId': 1, 'hydrate': 'linescore,team'},
            timeout=10
        )
        if r.status_code != 200:
            return []
        out = []
        for d in r.json().get('dates', []):
            for g in d.get('games', []):
                abstract = g.get('status', {}).get('abstractGameState', 'Preview')
                status = ('final' if abstract == 'Final'
                          else 'live' if abstract == 'Live'
                          else 'scheduled')
                ls = g.get('linescore', {})
                period = ''
                if status == 'live' and ls.get('currentInning'):
                    half = 'T' if ls.get('inningHalf') == 'Top' else 'B'
                    period = f"{half}{ls['currentInning']}"
                away = g.get('teams', {}).get('away', {})
                home = g.get('teams', {}).get('home', {})
                out.append({
                    'game_id': str(g.get('gamePk', '')),
                    'sport': 'MLB',
                    'away_team': away.get('team', {}).get('abbreviation', ''),
                    'home_team': home.get('team', {}).get('abbreviation', ''),
                    'away_score': away.get('score'),
                    'home_score': home.get('score'),
                    'status': status,
                    'period': period,
                    'clock': '',
                    'start_time_local': _to_local(g.get('gameDate', '')),
                })
        return out
    except Exception:
        return []


def cbb_tournament_games(game_date):
    """Fetch NCAA Tournament games from ESPN (groups=100 = NCAA Tournament only)."""
    try:
        r = requests.get(
            'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard',
            params={'dates': game_date.replace('-', ''), 'groups': 100, 'limit': 50},
            timeout=10
        )
        if r.status_code != 200:
            return []
        out = []
        for event in r.json().get('events', []):
            comp = event.get('competitions', [{}])[0]
            competitors = comp.get('competitors', [])
            if len(competitors) < 2:
                continue

            home_c = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away_c = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            if not home_c or not away_c:
                continue

            def abbr(c):
                return (c.get('team', {}).get('abbreviation') or
                        c.get('team', {}).get('shortDisplayName', '')[:6]).upper()

            def score(c):
                s = c.get('score')
                try:
                    return int(float(str(s))) if s not in (None, '', '--') else None
                except Exception:
                    return None

            def seed(c):
                return c.get('curatedRank', {}).get('current')

            status_obj = event.get('status', {})
            stype      = status_obj.get('type', {})
            state      = stype.get('state', '').lower()
            completed  = stype.get('completed', False)
            sname      = stype.get('name', '')

            if completed or state == 'post':
                status = 'final'
            elif state == 'in':
                status = 'live'
            else:
                status = 'scheduled'

            period_num = status_obj.get('period', 0)
            clock      = status_obj.get('displayClock', '') if status == 'live' else ''
            period = ''
            if status == 'live':
                if sname == 'STATUS_HALFTIME':
                    period = 'HLF'
                elif period_num == 1:
                    period = '1H'
                elif period_num == 2:
                    period = '2H'
                elif period_num >= 3:
                    ot = period_num - 2
                    period = 'OT' if ot == 1 else f'{ot}OT'

            notes       = comp.get('notes', [])
            round_label = notes[0].get('headline', '') if notes else ''
            # Shorten e.g. "NCAA Men's Basketball Championship - South Region - Elite 8" → "Elite 8"
            if ' - ' in round_label:
                round_label = round_label.rsplit(' - ', 1)[-1]

            start_time = comp.get('startDate', '') or event.get('date', '')

            away_seed = seed(away_c)
            home_seed = seed(home_c)

            out.append({
                'game_id':          str(event.get('id', '')),
                'sport':            'CBB',
                'away_team':        abbr(away_c),
                'home_team':        abbr(home_c),
                'away_score':       score(away_c),
                'home_score':       score(home_c),
                'status':           status,
                'period':           period,
                'clock':            clock,
                'start_time_local': _to_local(start_time),
                'round_label':      round_label,
                'away_seed':        away_seed,
                'home_seed':        home_seed,
                'away_team_name':   away_c.get('team', {}).get('shortDisplayName', ''),
                'home_team_name':   home_c.get('team', {}).get('shortDisplayName', ''),
            })
        return out
    except Exception:
        return []


def cbb_player_stats(game_id):
    """Fetch CBB player stats from ESPN summary endpoint."""
    try:
        r = requests.get(
            'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary',
            params={'event': game_id}, timeout=10
        )
        if r.status_code != 200:
            return {}
        result = {}
        for team_data in r.json().get('boxscore', {}).get('players', []):
            stats_list = team_data.get('statistics', [])
            if not stats_list:
                continue
            stat_info = stats_list[0]
            # CBB keys: ['MIN','PTS','FG','3PT','FT','REB','AST','TO','STL','BLK',...]
            keys = stat_info.get('names') or stat_info.get('labels') or stat_info.get('keys') or []

            for ath in stat_info.get('athletes', []):
                if ath.get('didNotPlay', False):
                    continue
                name = (ath.get('athlete', {}).get('displayName') or '').strip()
                if not name:
                    continue
                raw = ath.get('stats', [])
                sd = {keys[i]: raw[i] for i in range(min(len(keys), len(raw)))}

                def gv(ks):
                    for k in ks:
                        if k in sd:
                            try:
                                return int(float(str(sd[k]).lstrip('+')))
                            except Exception:
                                pass
                    return 0

                def pm(ks):
                    for k in ks:
                        if k in sd:
                            s = str(sd[k])
                            for sep in ('-', '/'):
                                if sep in s:
                                    try:
                                        return int(float(s.split(sep)[0].strip()))
                                    except Exception:
                                        pass
                    return 0

                pts = gv(['PTS', 'points'])
                reb = gv(['REB', 'rebounds'])
                ast = gv(['AST', 'assists'])
                result[name] = {
                    'points':      pts,
                    'rebounds':    reb,
                    'assists':     ast,
                    'steals':      gv(['STL', 'steals']),
                    'blocks':      gv(['BLK', 'blocks']),
                    'threes_made': pm(['3PT', '3PM-3PA', '3P']),
                    'pra':         pts + reb + ast,
                    'turnovers':   gv(['TO', 'turnovers']),
                }
        return result
    except Exception:
        return {}


def all_games(game_date):
    games = []
    games.extend(cbb_tournament_games(game_date))  # NCAA Tournament first
    games.extend(nba_games(game_date))
    games.extend(nhl_games(game_date))
    games.extend(mlb_games(game_date))
    return games


# ─── Player Stats ─────────────────────────────────────────────────────────────

def nba_player_stats(game_id):
    try:
        from espn_nba_api import ESPNNBAApi
        players = ESPNNBAApi().get_boxscore(game_id)
        return {
            p['player_name']: {
                'points':      p.get('points', 0),
                'rebounds':    p.get('rebounds', 0),
                'assists':     p.get('assists', 0),
                'steals':      p.get('steals', 0),
                'blocks':      p.get('blocks', 0),
                'threes_made': p.get('threes_made', 0),
                'pra':         p.get('points', 0) + p.get('rebounds', 0) + p.get('assists', 0),
                'turnovers':   p.get('turnovers', 0),
            }
            for p in players if p.get('player_name')
        }
    except Exception:
        return {}


def nhl_player_stats(game_id):
    try:
        r = requests.get(f'https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore', timeout=10)
        if r.status_code != 200:
            return {}
        result = {}
        pgs = r.json().get('playerByGameStats', {})
        for team_key in ('awayTeam', 'homeTeam'):
            td = pgs.get(team_key, {})
            for pos in ('forwards', 'defense'):
                for p in td.get(pos, []):
                    name = p.get('name', {}).get('default', '')
                    if name:
                        result[name] = {
                            'goals':         p.get('goals', 0),
                            'assists':       p.get('assists', 0),
                            'points':        p.get('goals', 0) + p.get('assists', 0),
                            'shots':         p.get('shots', 0),
                            'hits':          p.get('hits', 0),
                            'blocked_shots': p.get('blockedShots', 0),
                        }
        return result
    except Exception:
        return {}


def mlb_player_stats(game_id):
    try:
        r = requests.get(f'https://statsapi.mlb.com/api/v1/game/{game_id}/boxscore', timeout=10)
        if r.status_code != 200:
            return {}
        result = {}
        for team_key in ('home', 'away'):
            for _, pd in r.json().get('teams', {}).get(team_key, {}).get('players', {}).items():
                name = pd.get('person', {}).get('fullName', '')
                if not name:
                    continue
                stats = pd.get('stats', {})
                b, p = stats.get('batting', {}), stats.get('pitching', {})
                ps = {}
                if b:
                    ps.update({
                        'hits':       b.get('hits', 0),
                        'home_runs':  b.get('homeRuns', 0),
                        'rbi':        b.get('rbi', 0),
                        'total_bases': b.get('totalBases', 0),
                        'strikeouts_b': b.get('strikeOuts', 0),
                    })
                if p and p.get('inningsPitched'):
                    try:
                        ip_f = float(p.get('inningsPitched', '0.0'))
                    except (ValueError, TypeError):
                        ip_f = 0.0
                    ps.update({
                        'strikeouts':     p.get('strikeOuts', 0),
                        'innings_pitched': ip_f,
                        'hits_allowed':   p.get('hits', 0),
                        'earned_runs':    p.get('earnedRuns', 0),
                        'walks_allowed':  p.get('baseOnBalls', 0),
                    })
                if ps:
                    result[name] = ps
        return result
    except Exception:
        return {}


def player_stats(sport, game_id):
    if sport == 'NBA':
        return nba_player_stats(game_id)
    elif sport == 'CBB':
        return cbb_player_stats(game_id)
    elif sport == 'NHL':
        return nhl_player_stats(game_id)
    elif sport == 'MLB':
        return mlb_player_stats(game_id)
    return {}
