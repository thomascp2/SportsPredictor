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
    """Pull tonight's matchups from the sport DB so Grok has team names to search."""
    import sqlite3
    db = DB_PATHS.get(sport)
    if not db or not db.exists():
        return []
    try:
        conn = sqlite3.connect(str(db))
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


# ── CLI ───────────────────────────────────────────────────────────────────────

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
