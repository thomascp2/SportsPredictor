"""
ESPN MLB API Client (Hidden API - Vegas Odds)
=============================================

Uses ESPN's undocumented scoreboard/summary APIs to extract:
  - Game moneylines (home/away)
  - Game total (over/under line)
  - Consensus odds from sportsbooks

These ESPN endpoints are free, require no API key, and are the same
pattern already used by the NBA pipeline in this project.

Endpoints:
  Scoreboard: https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={yyyymmdd}
  Summary:    https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={espn_id}

ESPN team abbreviations sometimes differ from MLB Stats API — see ESPN_TO_MLB_TEAM in mlb_config.py.
"""

import time
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import ESPN_API_BASE, MLB_API_TIMEOUT, ESPN_TO_MLB_TEAM, normalize_team


class ESPNMLBApi:
    """
    Client for ESPN's hidden MLB API endpoints.

    Primarily used to extract Vegas odds (moneylines and game totals)
    since these are not available in the official MLB Stats API.
    """

    SCOREBOARD_URL = f"{ESPN_API_BASE}/scoreboard"
    SUMMARY_URL = f"{ESPN_API_BASE}/summary"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; SportsPredictor/1.0)',
            'Accept': 'application/json',
        })

    def _get(self, url: str, params: Dict = None) -> Optional[Dict]:
        """GET with retry logic (max 3 attempts, exponential backoff)."""
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=MLB_API_TIMEOUT)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = 2 ** attempt
                    print(f"[ESPN] HTTP {resp.status_code}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                print(f"[ESPN] HTTP {resp.status_code}: {url}")
                return None
            except requests.exceptions.Timeout:
                time.sleep(2 ** attempt)
            except requests.exceptions.RequestException as e:
                print(f"[ESPN] Request error: {e}")
                return None
        return None

    # -------------------------------------------------------------------------
    # Scoreboard — get list of ESPN game IDs for a date
    # -------------------------------------------------------------------------

    def get_scoreboard(self, date: str) -> List[Dict]:
        """
        Get all MLB games on a given date with their ESPN event IDs.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            List of event dicts with keys: espn_id, home_team, away_team, status
        """
        date_str = date.replace('-', '')  # ESPN wants YYYYMMDD
        data = self._get(self.SCOREBOARD_URL, params={'dates': date_str, 'limit': 50})

        if not data:
            return []

        events = []
        for event in data.get('events', []):
            espn_id = event.get('id', '')
            competitions = event.get('competitions', [])
            if not competitions:
                continue

            comp = competitions[0]
            competitors = comp.get('competitors', [])

            home_team = away_team = ''
            for c in competitors:
                abbr = normalize_team(c.get('team', {}).get('abbreviation', ''))
                if c.get('homeAway') == 'home':
                    home_team = abbr
                else:
                    away_team = abbr

            status = comp.get('status', {}).get('type', {}).get('name', '')

            events.append({
                'espn_id': espn_id,
                'home_team': home_team,
                'away_team': away_team,
                'status': status,
            })

        return events

    # -------------------------------------------------------------------------
    # Game summary — extract Vegas odds
    # -------------------------------------------------------------------------

    def get_game_odds(self, espn_game_id: str) -> Dict:
        """
        Fetch Vegas odds for a specific ESPN game.

        Tries multiple data locations in the ESPN response:
          1. pickcenter (best: per-book odds)
          2. odds array
          3. competitions[0].odds

        Args:
            espn_game_id: ESPN event ID (string)

        Returns:
            Dict with keys: home_ml, away_ml, game_total
            Values are None if not available.
        """
        result = {'home_ml': None, 'away_ml': None, 'game_total': None}

        data = self._get(self.SUMMARY_URL, params={'event': espn_game_id})
        if not data:
            return result

        # --- Try pickcenter (list of books; use consensus/last) ---
        pickcenter = data.get('pickcenter', [])
        if pickcenter:
            # Last entry tends to be consensus
            odds_entry = pickcenter[-1]
            result['game_total'] = self._extract_total(odds_entry)
            result['home_ml'] = self._extract_ml(odds_entry, 'home')
            result['away_ml'] = self._extract_ml(odds_entry, 'away')

        # --- Fallback: header.competitions[0].odds ---
        if result['game_total'] is None:
            try:
                comps = data.get('header', {}).get('competitions', [])
                if comps:
                    comp_odds = comps[0].get('odds', [{}])
                    if comp_odds:
                        o = comp_odds[0]
                        result['game_total'] = o.get('overUnder')
                        result['home_ml'] = o.get('homeTeamOdds', {}).get('moneyLine')
                        result['away_ml'] = o.get('awayTeamOdds', {}).get('moneyLine')
            except (KeyError, IndexError, TypeError):
                pass

        return result

    def get_all_game_odds(self, date: str) -> Dict[Tuple[str, str], Dict]:
        """
        Fetch Vegas odds for all games on a date.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            Dict keyed by (away_team, home_team) → odds dict
            e.g., {('NYY', 'BOS'): {'home_ml': -120, 'away_ml': 110, 'game_total': 8.5}}
        """
        events = self.get_scoreboard(date)
        odds_by_matchup = {}

        for event in events:
            espn_id = event['espn_id']
            home = event['home_team']
            away = event['away_team']

            if not home or not away:
                continue

            odds = self.get_game_odds(espn_id)
            odds_by_matchup[(away, home)] = odds

            print(f"[ESPN] {away} @ {home}: total={odds['game_total']} "
                  f"home_ml={odds['home_ml']} away_ml={odds['away_ml']}")

            # Small delay to avoid rate limiting
            time.sleep(0.2)

        print(f"[ESPN] Retrieved odds for {len(odds_by_matchup)} games on {date}")
        return odds_by_matchup

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _extract_total(self, odds_entry: Dict) -> Optional[float]:
        """Extract game total (O/U) from an odds entry."""
        # Try direct overUnder field
        total = odds_entry.get('overUnder')
        if total is not None:
            return float(total)

        # Try nested total fields
        total = odds_entry.get('total', {})
        if isinstance(total, dict):
            return total.get('open') or total.get('current')

        return None

    def _extract_ml(self, odds_entry: Dict, side: str) -> Optional[int]:
        """
        Extract moneyline for home or away team.

        Args:
            odds_entry: Odds dict from ESPN
            side: 'home' or 'away'
        """
        team_key = f'{side}TeamOdds'
        team_odds = odds_entry.get(team_key, {})

        ml = team_odds.get('moneyLine') or team_odds.get('current', {}).get('moneyLine')
        if ml is not None:
            return int(ml)

        return None

    @staticmethod
    def ml_to_implied_prob(moneyline: Optional[int]) -> float:
        """
        Convert American moneyline to implied probability.

        Args:
            moneyline: American odds (e.g., -150, +120)

        Returns:
            Implied probability as decimal (0 to 1)
        """
        if moneyline is None:
            return 0.5  # Default to even if unknown

        if moneyline < 0:
            return abs(moneyline) / (abs(moneyline) + 100)
        else:
            return 100 / (moneyline + 100)

    @staticmethod
    def implied_team_run_total(moneyline: Optional[int], game_total: Optional[float],
                               side: str) -> Optional[float]:
        """
        Estimate a team's implied run total from ML and game O/U.

        Uses the market-implied win probability to split the total
        between home and away expected runs.

        Args:
            moneyline: Team's moneyline (negative = favorite)
            game_total: Game over/under line
            side: 'home' or 'away'

        Returns:
            Estimated team run total or None
        """
        if game_total is None:
            return None

        try:
            home_ml = moneyline if side == 'home' else None
            home_prob = ESPNMLBApi.ml_to_implied_prob(moneyline) if side == 'home' else 0.5

            # Simple split: favorite gets slightly more of the total
            # Home implied runs ≈ game_total * home_prob (rough approximation)
            # Better: use standard run line model
            # Average MLB game: ~4.5 runs per team, total ~9.0
            # Favorite gets proportionally more based on ML strength
            home_implied = game_total * home_prob * (1 / 0.5)  # Normalize around 0.5
            home_implied = min(max(home_implied, game_total * 0.35), game_total * 0.65)

            if side == 'home':
                return round(home_implied, 2)
            else:
                return round(game_total - home_implied, 2)
        except Exception:
            return None


# ============================================================================
# Validation schema for api_health_monitor.py
# ============================================================================

ESPN_MLB_SCHEMA = {
    'espn_mlb_scoreboard': {
        'events': [{
            'id': 'str',
            'competitions': [{
                'competitors': [{'team': {'abbreviation': 'str'}}],
            }],
        }],
    },
    'espn_mlb_summary': {
        'header': {
            'competitions': [{}],
        },
    },
}


# ============================================================================
# Quick test / standalone usage
# ============================================================================

if __name__ == '__main__':
    import sys

    api = ESPNMLBApi()

    test_date = datetime.now().strftime('%Y-%m-%d')
    if len(sys.argv) > 1:
        test_date = sys.argv[1]

    print(f"\n[ESPN MLB] Fetching scoreboard for {test_date}...")
    events = api.get_scoreboard(test_date)

    if not events:
        print(f"  No events found (off-season or API issue)")
    else:
        print(f"  Found {len(events)} events\n")
        for e in events[:3]:  # Show first 3
            print(f"  ESPN ID {e['espn_id']}: {e['away_team']} @ {e['home_team']}")
            odds = api.get_game_odds(e['espn_id'])
            print(f"    Odds: home_ml={odds['home_ml']} away_ml={odds['away_ml']} "
                  f"total={odds['game_total']}")
