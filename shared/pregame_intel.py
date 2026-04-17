"""
Pre-Game Intelligence — Grok-Powered Real-Time Sweep
=====================================================

Calls xAI Grok (live web search) once per sport per day to gather:
  - Confirmed OUT / DOUBTFUL / QUESTIONABLE players
  - Load management / minutes restriction announcements
  - NHL goalie confirmations (post-morning-skate)
  - Key notes (injuries, coaching decisions, late scratches)

Results are cached to data/pregame_intel/{sport}_{date}.json so the
Grok call fires exactly once even if prediction scripts are re-run.

Integration points:
  - nhl/scripts/generate_predictions_daily_V6.py  (filters player loop)
  - nba/scripts/generate_predictions_daily.py      (filters player loop)
  - orchestrator.py                                (runs before predictions)

Usage:
    from pregame_intel import PreGameIntel

    intel = PreGameIntel()
    intel.fetch('nba', '2026-03-28', ['BOS vs MIA', 'LAL vs GSW'])

    if intel.is_player_out('Jayson Tatum', 'nba', '2026-03-28'):
        # skip prediction

    starter = intel.get_goalie_starter('BOS', 'nhl', '2026-03-28')
"""

import os
import sys
import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR    = PROJECT_ROOT / 'data' / 'pregame_intel'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Grok config ───────────────────────────────────────────────────────────────

GROK_API_URL = 'https://api.x.ai/v1/chat/completions'
GROK_MODEL   = os.getenv('GROK_INTEL_MODEL', 'grok-3')
# NOTE: read at call time (not import time) so the orchestrator's env var is
# always picked up even when the module was imported before the var was set.
XAI_API_KEY  = ''  # populated lazily in _call_grok()

SPORT_NAMES = {
    'nba': 'NBA basketball',
    'nhl': 'NHL hockey',
    'mlb': 'MLB baseball',
}

# ── Prompt ────────────────────────────────────────────────────────────────────

PROMPT = """You are a sports injury and lineup analyst. Today is {date}.

Use your live web search RIGHT NOW to find the current {league} injury report and player availability.

Search ALL of the following:
1. "ESPN {league} injury report {date}" — pull the full league-wide list
2. Official {league}.com injury designations released today
3. Beat reporter posts from the last 12 hours on player status
4. Any "load management", "rest night", or "minutes restriction" announcements
{goalie_line}

Tonight's games (search injuries for EVERY team listed):
{matchups}

Return ONLY a raw JSON object — no markdown code fences, no explanation, just the JSON.

{{
  "out_players": ["Full Player Name", ...],
  "doubtful_players": ["Full Player Name", ...],
  "questionable_players": ["Full Player Name", ...],
  "load_management": ["Full Player Name", ...],
  "goalie_starters": {{"TEAM_ABBR": "Full Goalie Name", ...}},
  "key_notes": ["One-sentence note about the status", ...]
}}

Definitions:
- out_players: officially OUT, inactive, scratched, or confirmed DNP tonight
- doubtful_players: listed DOUBTFUL or very unlikely to play
- questionable_players: listed QUESTIONABLE, GTD, or day-to-day
- load_management: announced rest, minutes cap, or load management
- goalie_starters: confirmed starting goalie per post-morning-skate report (NHL only)
- key_notes: anything affecting prop bets tonight (max 5 notes)

There are almost always injured or questionable players on any {league} game day.
Search each team playing tonight specifically. Return empty arrays only if you
genuinely find zero updates after a thorough search.
"""

# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(sport: str, game_date: str) -> Path:
    return CACHE_DIR / f'{sport}_{game_date}.json'


def _load_cache(sport: str, game_date: str) -> Optional[Dict]:
    path = _cache_path(sport, game_date)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_cache(sport: str, game_date: str, data: Dict) -> None:
    try:
        _cache_path(sport, game_date).write_text(json.dumps(data, indent=2))
    except OSError as e:
        print(f'  [INTEL] Cache write failed: {e}')


# ── Grok call ─────────────────────────────────────────────────────────────────

def _call_grok(prompt: str) -> Optional[str]:
    """POST to Grok API. Returns raw content string or None on failure."""
    # Read at call time so the key is always current regardless of import order
    api_key = os.getenv('XAI_API_KEY', '')
    if not api_key:
        print('  [INTEL] XAI_API_KEY not set — skipping pre-game intel fetch')
        return None

    payload = json.dumps({
        'model': GROK_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.1,        # Low temp — we want factual, consistent output
        'max_tokens': 1500,
        'response_format': {'type': 'json_object'},  # Force JSON output
    }).encode('utf-8')

    req = urllib.request.Request(
        GROK_API_URL,
        data=payload,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type':  'application/json',
            'User-Agent':    'FreePicks-Intel/1.0',
        },
        method='POST',
    )

    try:
        resp = urllib.request.urlopen(req, timeout=45)
        data = json.loads(resp.read())
        return data['choices'][0]['message']['content']
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:300]
        print(f'  [INTEL] Grok HTTP {e.code}: {body}')
        return None
    except Exception as e:
        print(f'  [INTEL] Grok error: {e}')
        return None


def _parse_response(raw: str) -> Optional[Dict]:
    """Parse Grok JSON response into intel dict."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try extracting JSON block from response if Grok added surrounding text
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                print('  [INTEL] Could not parse Grok response as JSON')
                return None
        else:
            print('  [INTEL] No JSON found in Grok response')
            return None

    def _clean(name: str) -> str:
        """Strip Grok-appended context like '(LAC - Knee Soreness)' leaving just the name."""
        return re.sub(r'\s*\(.*\)', '', name).strip()

    # Normalise: ensure all expected keys exist, strip any parenthetical context
    normalised = {
        'out_players':          [_clean(p) for p in data.get('out_players', []) if p],
        'doubtful_players':     [_clean(p) for p in data.get('doubtful_players', []) if p],
        'questionable_players': [_clean(p) for p in data.get('questionable_players', []) if p],
        'load_management':      [_clean(p) for p in data.get('load_management', []) if p],
        'goalie_starters':      {k.upper(): v for k, v in (data.get('goalie_starters') or {}).items()},
        'key_notes':            [n.strip() for n in data.get('key_notes', []) if n],
        'fetched_at':           datetime.now().isoformat(),
        'model':                GROK_MODEL,
    }
    return normalised


def _empty_intel() -> Dict:
    """Safe default when no data available — pipeline runs normally."""
    return {
        'out_players': [],
        'doubtful_players': [],
        'questionable_players': [],
        'load_management': [],
        'goalie_starters': {},
        'key_notes': [],
        'fetched_at': None,
        'model': None,
    }


# ── DB matchup helper ─────────────────────────────────────────────────────────

DB_PATHS = {
    'nba': PROJECT_ROOT / 'nba' / 'database' / 'nba_predictions.db',
    'nhl': PROJECT_ROOT / 'nhl' / 'database' / 'nhl_predictions_v2.db',
    'mlb': PROJECT_ROOT / 'mlb' / 'database' / 'mlb_predictions.db',
}

def _get_matchups_from_db(sport: str, game_date: str) -> List[str]:
    """Pull tonight's matchups from the sport DB so Grok has team names to search.
    Checks game_context first (MLB primary), then falls back to games table."""
    import sqlite3
    db = DB_PATHS.get(sport)
    if not db or not db.exists():
        return []
    try:
        conn = sqlite3.connect(str(db))
        # Check game_context first (MLB stores schedule here)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if 'game_context' in tables:
            rows = conn.execute(
                'SELECT DISTINCT away_team, home_team FROM game_context WHERE game_date = ?',
                (game_date,)
            ).fetchall()
            if rows:
                conn.close()
                return [f'{away} vs {home}' for away, home in rows]
        # Fallback to games table
        rows = conn.execute(
            'SELECT away_team, home_team FROM games WHERE game_date = ?', (game_date,)
        ).fetchall()
        conn.close()
        return [f'{away} vs {home}' for away, home in rows]
    except Exception:
        return []


# ── Name matching ─────────────────────────────────────────────────────────────

def _name_matches(player_name: str, target: str) -> bool:
    """Case-insensitive name comparison with light normalisation."""
    def _norm(s):
        return re.sub(r'[^a-z]', '', s.lower())
    return _norm(player_name) == _norm(target)


def _player_in_list(player_name: str, names: List[str]) -> bool:
    return any(_name_matches(player_name, n) for n in names)


# ── Main class ────────────────────────────────────────────────────────────────

class PreGameIntel:
    """
    Fetches and caches pre-game player availability intel via Grok.

    Call fetch() once before prediction generation to populate the cache.
    Then use the is_*() helpers inside the player loop to filter predictions.
    """

    def __init__(self):
        self._cache: Dict[str, Dict] = {}   # (sport, date) -> intel dict

    def fetch(self, sport: str, game_date: str, matchups: List[str]) -> Dict:
        """
        Fetch pre-game intel for a sport/date. Returns cached result if already run today.

        Args:
            sport:      'nba', 'nhl', or 'mlb'
            game_date:  'YYYY-MM-DD'
            matchups:   List of strings like ['BOS vs MIA', 'LAL vs GSW']

        Returns:
            Intel dict with out_players, questionable_players, etc.
        """
        cache_key = f'{sport}_{game_date}'

        # In-memory cache (prevents double-call within same process)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # File cache (prevents re-call if script is rerun)
        cached = _load_cache(sport, game_date)
        if cached and cached.get('fetched_at'):
            # Only use cache if it was populated by a real Grok call (fetched_at set).
            # A null fetched_at means a previous run got an empty fallback — re-fetch.
            print(f'  [INTEL] Loaded cached intel for {sport.upper()} {game_date} '
                  f'({len(cached.get("out_players", []))} OUT, '
                  f'{len(cached.get("questionable_players", []))} QUESTIONABLE)')
            self._cache[cache_key] = cached
            return cached
        elif cached and not cached.get('fetched_at'):
            print(f'  [INTEL] Stale empty cache for {sport.upper()} {game_date} — re-fetching')

        # Fresh Grok call
        print(f'  [INTEL] Fetching pre-game intel for {sport.upper()} {game_date}...')

        sport_name  = SPORT_NAMES.get(sport, sport.upper())
        league      = sport.upper()

        # If no matchups passed, try to pull them from the sport's games DB
        if not matchups:
            matchups = _get_matchups_from_db(sport, game_date)

        matchup_str = '\n'.join(f'  - {m}' for m in matchups) if matchups \
                      else f'  - (all {league} games scheduled for {game_date})'

        goalie_line = '5. NHL morning skate goalie confirmations from beat reporters (NHL only)' \
                      if sport == 'nhl' else ''

        prompt = PROMPT.format(
            date=game_date,
            sport_name=sport_name,
            league=league,
            matchups=matchup_str,
            goalie_line=goalie_line,
        )

        raw    = _call_grok(prompt)
        intel  = _parse_response(raw)

        if intel is None:
            print('  [INTEL] No intel retrieved — predictions will run without player filter')
            intel = _empty_intel()
        else:
            out_count = len(intel['out_players'])
            q_count   = len(intel['questionable_players'])
            lm_count  = len(intel['load_management'])
            g_count   = len(intel['goalie_starters'])
            print(f'  [INTEL] Intel received: {out_count} OUT, {q_count} QUESTIONABLE, '
                  f'{lm_count} load mgmt, {g_count} goalie confirmations')
            if intel['key_notes']:
                for note in intel['key_notes'][:3]:
                    print(f'    * {note}')
            if out_count > 0:
                print(f'    OUT: {", ".join(intel["out_players"])}')

        _save_cache(sport, game_date, intel)
        self._cache[cache_key] = intel
        return intel

    def load(self, sport: str, game_date: str) -> Dict:
        """Load cached intel without making a new Grok call."""
        cache_key = f'{sport}_{game_date}'
        if cache_key in self._cache:
            return self._cache[cache_key]
        cached = _load_cache(sport, game_date)
        if cached:
            self._cache[cache_key] = cached
            return cached
        return _empty_intel()

    # ── Player status helpers ─────────────────────────────────────────────────

    def is_player_out(self, player_name: str, sport: str, game_date: str) -> bool:
        """True if player is confirmed OUT — skip prediction entirely."""
        intel = self.load(sport, game_date)
        return _player_in_list(player_name, intel.get('out_players', []))

    def is_player_doubtful(self, player_name: str, sport: str, game_date: str) -> bool:
        """True if player is doubtful — still predict but flag confidence."""
        intel = self.load(sport, game_date)
        return _player_in_list(player_name, intel.get('doubtful_players', []))

    def is_player_questionable(self, player_name: str, sport: str, game_date: str) -> bool:
        """True if player is questionable / GTD."""
        intel = self.load(sport, game_date)
        return _player_in_list(player_name, intel.get('questionable_players', []))

    def is_load_management(self, player_name: str, sport: str, game_date: str) -> bool:
        """True if player has announced load management / minutes restriction."""
        intel = self.load(sport, game_date)
        return _player_in_list(player_name, intel.get('load_management', []))

    def get_goalie_starter(self, team_abbr: str, game_date: str) -> Optional[str]:
        """
        Return confirmed starting goalie name for a team, or None if unconfirmed.
        team_abbr should match standard NHL abbreviation (e.g. 'TOR', 'BOS').
        """
        intel = self.load('nhl', game_date)
        return intel.get('goalie_starters', {}).get(team_abbr.upper())

    def get_status(self, player_name: str, sport: str, game_date: str) -> str:
        """
        Return player's status string: 'OUT', 'DOUBTFUL', 'QUESTIONABLE',
        'LOAD_MGMT', or 'ACTIVE'.
        """
        if self.is_player_out(player_name, sport, game_date):
            return 'OUT'
        if self.is_player_doubtful(player_name, sport, game_date):
            return 'DOUBTFUL'
        if self.is_load_management(player_name, sport, game_date):
            return 'LOAD_MGMT'
        if self.is_player_questionable(player_name, sport, game_date):
            return 'QUESTIONABLE'
        return 'ACTIVE'

    def get_notes(self, sport: str, game_date: str) -> List[str]:
        """Return key notes for the day."""
        return self.load(sport, game_date).get('key_notes', [])

    # ── Betting context ───────────────────────────────────────────────────────

    def fetch_betting_context(self, sport: str, game_date: str,
                              matchups: Optional[List[str]] = None) -> Dict:
        """
        Fetch betting context (line movement, sharp action, prop moves) via Grok.
        Cached to data/pregame_intel/{sport}_{date}_betting.json.
        """
        cache_path = _cache_path_betting(sport, game_date)
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text())
                if data.get('fetched_at'):
                    print(f'  [INTEL] Loaded cached betting context for {sport.upper()} {game_date}')
                    return data
            except (json.JSONDecodeError, OSError):
                pass

        print(f'  [INTEL] Fetching betting context for {sport.upper()} {game_date}...')

        if not matchups:
            matchups = _get_matchups_from_db(sport, game_date)

        matchup_str = '\n'.join(f'  - {m}' for m in matchups) if matchups \
                      else f'  - (all {sport.upper()} games today)'

        prompt = BETTING_CONTEXT_PROMPT.format(
            date=game_date,
            league=sport.upper(),
            matchups=matchup_str,
        )

        raw = _call_grok(prompt)
        empty = {'line_moves': [], 'sharp_action': [], 'prop_moves': [],
                 'key_angles': [], 'fetched_at': None, 'model': None}
        if not raw:
            try:
                cache_path.write_text(json.dumps(empty, indent=2))
            except OSError:
                pass
            return empty

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}

        result = {
            'line_moves':   data.get('line_moves', []),
            'sharp_action': data.get('sharp_action', []),
            'prop_moves':   data.get('prop_moves', []),
            'key_angles':   data.get('key_angles', []),
            'fetched_at':   datetime.now().isoformat(),
            'model':        GROK_MODEL,
        }

        lm = len(result['line_moves'])
        sa = len(result['sharp_action'])
        pm = len(result['prop_moves'])
        print(f'  [INTEL] Betting context: {lm} line moves, {sa} sharp actions, {pm} prop moves')
        for angle in result['key_angles'][:3]:
            print(f'    * {angle}')

        try:
            cache_path.write_text(json.dumps(result, indent=2))
        except OSError as exc:
            print(f'  [INTEL] Cache write failed: {exc}')

        return result

    def load_betting_context(self, sport: str, game_date: str) -> Dict:
        """Load cached betting context without a new Grok call."""
        cache_path = _cache_path_betting(sport, game_date)
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {'line_moves': [], 'sharp_action': [], 'prop_moves': [], 'key_angles': []}

    def fetch_season_context(self, sport: str, game_date: str, teams: List[str]) -> Dict:
        """Fetch seeding/motivation context for each team. One Grok call covers all teams."""
        cache_path = _cache_path_season_context(sport, game_date)
        empty = {'team_contexts': {}, 'key_notes': [], 'fetched_at': None}

        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text())
                if data.get('fetched_at'):
                    print(f'  [INTEL] Loaded cached season context for {sport.upper()} {game_date}')
                    return data
            except (json.JSONDecodeError, OSError):
                pass

        if not teams:
            return empty

        print(f'  [INTEL] Fetching season context for {sport.upper()} {game_date} ({len(teams)} teams)...')
        prompt = SEASON_CONTEXT_PROMPT.format(
            date=game_date, league=sport.upper(),
            year=game_date[:4],
            teams='\n'.join(f'  - {t}' for t in teams),
        )
        raw = _call_grok(prompt)
        if not raw:
            cache_path.write_text(json.dumps(empty, indent=2))
            return empty

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}

        result = {
            'team_contexts': data.get('team_contexts', {}),
            'key_notes':     data.get('key_notes', []),
            'fetched_at':    datetime.now().isoformat(),
            'model':         GROK_MODEL,
        }
        high_risk = [t for t, ctx in result['team_contexts'].items()
                     if ctx.get('risk_level') == 'high']
        print(f'  [INTEL] Season context: {len(result["team_contexts"])} teams, {len(high_risk)} high-risk')
        if high_risk:
            print(f'    Dead rubber risk: {", ".join(high_risk)}')
        cache_path.write_text(json.dumps(result, indent=2))
        return result

    def get_season_context(self, team: str, sport: str, game_date: str) -> Dict:
        """Return cached season context for a single team."""
        cache_path = _cache_path_season_context(sport, game_date)
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text())
                return data.get('team_contexts', {}).get(team.upper(), {})
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def get_usage_beneficiaries(self, absent_players: List[str], team: str,
                                sport: str, game_date: str) -> List[Dict]:
        """When stars are OUT, identify teammates who absorb usage via Grok."""
        if not absent_players:
            return []

        cache_path = CACHE_DIR / f'{sport}_{game_date}_usage_{team.upper()}.json'
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text())
                if data.get('fetched_at'):
                    return data.get('beneficiaries', [])
            except (json.JSONDecodeError, OSError):
                pass

        absent_str = ', '.join(absent_players)
        prompt = USAGE_BENEFICIARY_PROMPT.format(
            date=game_date, team=team.upper(), league=sport.upper(),
            absent_players='\n'.join(f'  - {p}' for p in absent_players),
            absent_str=absent_str,
        )
        raw = _call_grok(prompt)
        if not raw:
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}

        beneficiaries = data.get('beneficiaries', [])
        cache_path.write_text(json.dumps(
            {'beneficiaries': beneficiaries, 'fetched_at': datetime.now().isoformat()},
            indent=2
        ))
        return beneficiaries

    def get_situation_flag(self, player_name: str, team: str,
                           sport: str, game_date: str) -> tuple:
        """Return (flag, modifier) combining team motivation + player injury status."""
        ctx = self.get_season_context(team, sport, game_date)
        motivation = ctx.get('motivation_score', 0.5)
        if ctx.get('seeding_status') == 'eliminated':
            motivation = min(motivation, 0.15)
        injury_status = self.get_status(player_name, sport, game_date)
        return _situation_flag_from_context(injury_status, motivation)

    def get_situation_notes(self, player_name: str, team: str,
                            sport: str, game_date: str) -> str:
        """Return human-readable situational note for a player pick."""
        ctx = self.get_season_context(team, sport, game_date)
        if not ctx:
            return ''
        parts = []
        status_labels = {
            'locked_in': 'seed locked', 'clinched_playoffs': 'playoffs clinched',
            'fighting_for_seeding': 'fighting for seeding',
            'bubble': 'BUBBLE -- must win', 'eliminated': 'eliminated',
        }
        label = status_labels.get(ctx.get('seeding_status', ''), '')
        seed = ctx.get('seed')
        if seed and label:
            parts.append(f'{team.upper()} {seed}-seed {label}')
        elif label:
            parts.append(f'{team.upper()} {label}')
        if ctx.get('games_remaining') is not None:
            parts.append(f'{ctx["games_remaining"]} games left')
        if ctx.get('season_ending_outs'):
            parts.append(f'{", ".join(ctx["season_ending_outs"][:3])} out for season')
        narrative = ctx.get('rest_narrative', '')
        if narrative and len(narrative) < 80:
            parts.append(narrative)
        player_status = self.get_status(player_name, sport, game_date)
        if player_status != 'ACTIVE':
            parts.append(f'{player_name}: {player_status}')
        return ' -- '.join(parts) if parts else ''


# ── Discord poster ────────────────────────────────────────────────────────────

def post_intel_to_discord(sport: str, game_date: str, webhook_url: str) -> bool:
    """Post today's pre-game intel + betting context as a Discord embed."""
    if not webhook_url:
        return False

    try:
        import requests as _requests
    except ImportError:
        print('  [INTEL] requests not installed — cannot post to Discord')
        return False

    intel_obj = PreGameIntel()
    intel     = intel_obj.load(sport, game_date)
    betting   = intel_obj.load_betting_context(sport, game_date)

    fields = []

    injury_lines = []
    if intel.get('out_players'):
        injury_lines.append(f"OUT: {', '.join(intel['out_players'][:6])}")
    if intel.get('doubtful_players'):
        injury_lines.append(f"DOUBTFUL: {', '.join(intel['doubtful_players'][:4])}")
    if intel.get('questionable_players'):
        injury_lines.append(f"GTD: {', '.join(intel['questionable_players'][:4])}")
    if intel.get('goalie_starters'):
        starters = ', '.join(f"{t}: {g}" for t, g in intel['goalie_starters'].items())
        injury_lines.append(f"Goalies: {starters}")
    if injury_lines:
        fields.append({"name": "Injuries / Lineup",
                       "value": '\n'.join(injury_lines), "inline": False})

    if betting.get('sharp_action'):
        sa_lines = [
            f"{s.get('game','?')} - {s.get('side','?')} ({s.get('bet_type','?')}): {s.get('note','')}"
            for s in betting['sharp_action'][:4]
        ]
        fields.append({"name": "Sharp Action", "value": '\n'.join(sa_lines), "inline": False})

    if betting.get('line_moves'):
        lm_lines = [
            f"{m.get('game','?')} {m.get('bet_type','?')} {m.get('direction','?')} "
            f"{m.get('amount','')}: {m.get('note','')}"
            for m in betting['line_moves'][:4]
        ]
        fields.append({"name": "Line Moves", "value": '\n'.join(lm_lines), "inline": False})

    if betting.get('key_angles'):
        fields.append({"name": "Key Angles",
                       "value": '\n'.join(f"* {a}" for a in betting['key_angles'][:4]),
                       "inline": False})

    if intel.get('key_notes'):
        fields.append({"name": "News Notes",
                       "value": '\n'.join(f"* {n}" for n in intel['key_notes'][:4]),
                       "inline": False})

    if not fields:
        return False

    embed = {
        "title": f"[{sport.upper()}] Pre-Game Intel - {game_date}",
        "color": 0x5865F2,
        "fields": fields,
        "footer": {"text": f"Powered by Grok | {datetime.now().strftime('%H:%M CST')}"},
    }
    try:
        r = _requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        return r.status_code in (200, 204)
    except Exception as exc:
        print(f'  [INTEL] Discord post failed: {exc}')
        return False


# ── Betting context prompt ────────────────────────────────────────────────────

BETTING_CONTEXT_PROMPT = """You are a sharp sports betting analyst. Today is {date}.

Use your live web search RIGHT NOW to find relevant betting intel for tonight's {league} games.

Search for:
1. "{league} line movement today" — which lines have moved 1.5+ points/goals since open
2. "{league} sharp money action {date}" — where the sharp/professional bettors are going
3. "{league} reverse line movement {date}" — bets going opposite to public money
4. "{league} steam move {date}" — coordinated sharp action
5. Notable prop line movement — any player props that moved significantly

Tonight's games:
{matchups}

Return ONLY a raw JSON object — no markdown code fences, no explanation.

{{
  "line_moves": [
    {{"game": "AWAY @ HOME", "bet_type": "spread|total|moneyline", "direction": "up|down", "amount": "1.5", "note": "brief context"}}
  ],
  "sharp_action": [
    {{"game": "AWAY @ HOME", "bet_type": "spread|total|moneyline", "side": "AWAY|HOME|OVER|UNDER", "note": "why sharps like it"}}
  ],
  "prop_moves": [
    {{"player": "Full Name", "prop": "points|assists etc", "direction": "up|down", "note": "brief context"}}
  ],
  "key_angles": ["One-sentence betting angle, max 5 items"]
}}

Return empty arrays if you genuinely find nothing relevant after a thorough search.
"""


def _cache_path_betting(sport: str, game_date: str) -> Path:
    return CACHE_DIR / f'{sport}_{game_date}_betting.json'


def _cache_path_season_context(sport: str, game_date: str) -> Path:
    return CACHE_DIR / f'{sport}_{game_date}_season_context.json'


# ── Season context prompts ────────────────────────────────────────────────────

SEASON_CONTEXT_PROMPT = """You are a professional sports analyst evaluating
end-of-season team motivation and roster availability. Today is {date}.

Use your live web search RIGHT NOW to assess the playoff/seeding situation
for each team listed.

For EACH team below, search:
1. "{team} {league} standings games remaining {date}"
2. "{team} playoff seeding clinched locked eliminated {year}"
3. "{team} resting starters load management end of season"
4. "{team} players out for rest of regular season"
5. Coach quotes about rest, development, or playing starters

Teams to assess:
{teams}

SEEDING STATUS values (pick exactly one per team):
- "locked_in": Exact seed locked -- cannot move up or down
- "clinched_playoffs": In playoffs but seed still moveable
- "fighting_for_seeding": Actively competing for a better seed
- "bubble": On the edge of making/missing play-in or playoffs
- "eliminated": Mathematically eliminated
- "unknown": Cannot determine

MOTIVATION SCORE: 0.0 = no incentive, 1.0 = maximum urgency
  locked_in -> 0.10-0.25
  clinched_playoffs -> 0.40-0.60
  fighting_for_seeding -> 0.65-0.80
  bubble -> 0.85-1.00
  eliminated -> 0.05-0.15

Return ONLY raw JSON -- no markdown, no explanation:

{{
  "team_contexts": {{
    "TEAM_ABBR": {{
      "games_remaining": 4,
      "seeding_status": "locked_in",
      "seed": 4,
      "can_move_up": false,
      "can_fall": false,
      "motivation_score": 0.15,
      "season_ending_outs": ["Player Name"],
      "rest_narrative": "Brief description of rest/load management situation",
      "risk_level": "high"
    }}
  }},
  "key_notes": ["One-sentence situational note, max 5"]
}}
"""


USAGE_BENEFICIARY_PROMPT = """You are an NBA/NHL usage and role analyst.
Today is {date}.

The following players are OUT for {team} ({league}):
{absent_players}

Use your live web search to find who absorbs their usage:
1. "{team} lineup changes without {absent_str}"
2. "{team} usage rate distribution without {absent_str}"
3. Which teammates absorb extra shots, assists, and minutes

Return ONLY raw JSON:

{{
  "beneficiaries": [
    {{
      "player": "Full Player Name",
      "usage_boost_pct": 15,
      "affected_props": ["points", "assists"],
      "direction": "OVER",
      "notes": "Brief reason why this player benefits"
    }}
  ]
}}

Return empty list if absences don't meaningfully shift usage.
"""


def _situation_flag_from_context(injury_status: str, motivation_score: float) -> tuple:
    """
    Derive (situation_flag, situation_modifier) from injury status + motivation.
    modifier is ADVISORY ONLY -- never applied to DB predictions.
    """
    if motivation_score <= 0.25:
        if injury_status in ('OUT', 'DOUBTFUL'):
            return 'DEAD_RUBBER', -0.15
        elif injury_status == 'QUESTIONABLE':
            return 'DEAD_RUBBER', -0.10
        else:
            return 'DEAD_RUBBER', -0.06
    elif motivation_score <= 0.50:
        return 'REDUCED_STAKES', -0.03
    elif motivation_score >= 0.85:
        if injury_status == 'QUESTIONABLE':
            return 'HIGH_STAKES', +0.05
        return 'HIGH_STAKES', +0.03
    else:
        return 'NORMAL', 0.0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Fetch pre-game intel via Grok')
    parser.add_argument('sport', choices=['nba', 'nhl', 'mlb'])
    parser.add_argument('--date',     default=datetime.now().strftime('%Y-%m-%d'))
    parser.add_argument('--matchups', nargs='*', default=[],
                        help='e.g. "BOS vs MIA" "LAL vs GSW"')
    parser.add_argument('--force',    action='store_true',
                        help='Ignore cache and re-fetch from Grok')
    args = parser.parse_args()

    if args.force:
        _cache_path(args.sport, args.date).unlink(missing_ok=True)

    intel_obj = PreGameIntel()
    result    = intel_obj.fetch(args.sport, args.date, args.matchups)

    print(f'\n=== Pre-Game Intel: {args.sport.upper()} {args.date} ===')
    print(f'OUT         : {result["out_players"] or "none"}')
    print(f'DOUBTFUL    : {result["doubtful_players"] or "none"}')
    print(f'QUESTIONABLE: {result["questionable_players"] or "none"}')
    print(f'LOAD MGMT   : {result["load_management"] or "none"}')
    if result['goalie_starters']:
        print(f'GOALIES     : {result["goalie_starters"]}')
    if result['key_notes']:
        print('NOTES:')
        for note in result['key_notes']:
            print(f'  * {note}')
