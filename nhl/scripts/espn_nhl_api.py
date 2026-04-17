"""
ESPN NHL API Client
===================
Fetches NHL scoreboard data including game odds (spread, total, moneylines)
from ESPN's public API.

ESPN NHL endpoints used:
  Scoreboard: GET https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=YYYYMMDD
  Summary:    GET https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event=EVENT_ID

NOTE: Unlike NBA, NHL scoreboard does NOT include odds in the response.
Odds (pickcenter) are fetched per-game from the summary endpoint.
"""

import requests
import time
from datetime import datetime


class ESPNNHLApi:
    """ESPN NHL API client — game info and betting odds."""

    def __init__(self):
        self.base_url = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; SportsPredictor/1.0)',
            'Accept': 'application/json',
        })

    def get_scoreboard(self, game_date: str) -> list:
        """
        Fetch all NHL games for a date including odds.

        Flow:
          1. Scoreboard endpoint -> event IDs + team abbreviations
          2. Summary endpoint per event -> pickcenter odds

        Args:
            game_date: 'YYYY-MM-DD'

        Returns:
            List of game dicts including spread, over_under, moneylines, implied probs.
            Returns [] on any error — caller must handle gracefully.
        """
        date_str = game_date.replace('-', '')
        url = f"{self.base_url}/scoreboard"
        params = {'dates': date_str, 'limit': 20}

        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[ESPN-NHL] Scoreboard request error: {e}")
            return []

        games = []
        try:
            events = data.get('events', [])
            if not isinstance(events, list):
                return []

            for event in events:
                if not isinstance(event, dict):
                    continue

                competitions = event.get('competitions', [])
                if not competitions:
                    continue
                competition = competitions[0]
                if not isinstance(competition, dict):
                    continue

                # Teams
                competitors = competition.get('competitors', [])
                if len(competitors) < 2:
                    continue

                home_comp = next((c for c in competitors if c.get('homeAway') == 'home'), None)
                away_comp = next((c for c in competitors if c.get('homeAway') == 'away'), None)
                if not home_comp or not away_comp:
                    continue

                def _abbr(c):
                    t = c.get('team', {})
                    return (t.get('abbreviation') or t.get('shortDisplayName') or '').upper()

                home_abbr = _abbr(home_comp)
                away_abbr = _abbr(away_comp)
                if not home_abbr or not away_abbr:
                    continue

                event_id = str(event.get('id') or competition.get('id') or '')

                # Fetch odds from summary endpoint (pickcenter)
                odds = self._get_odds_from_summary(event_id)

                games.append({
                    'game_id': event_id,
                    'home_team': home_abbr,
                    'away_team': away_abbr,
                    **odds,
                })

                # Brief pause between per-game summary calls
                time.sleep(0.15)

        except Exception as e:
            print(f"[ESPN-NHL] Parse error: {e}")
            return []

        return games

    def _get_odds_from_summary(self, event_id: str) -> dict:
        """
        Fetch betting odds from the ESPN summary endpoint for a single game.

        Returns dict with keys: spread, over_under, home_moneyline, away_moneyline,
        home_implied_prob, away_implied_prob, max_implied_prob, odds_details, odds_provider.
        All values default to None/''.
        """
        defaults = {
            'spread': None,
            'over_under': None,
            'home_moneyline': None,
            'away_moneyline': None,
            'home_implied_prob': None,
            'away_implied_prob': None,
            'max_implied_prob': None,
            'odds_details': '',
            'odds_provider': '',
        }
        if not event_id:
            return defaults

        try:
            resp = self.session.get(
                f"{self.base_url}/summary",
                params={'event': event_id},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[ESPN-NHL] Summary fetch failed for event {event_id}: {e}")
            return defaults

        try:
            pickcenter = data.get('pickcenter', [])
            if not isinstance(pickcenter, list) or not pickcenter:
                return defaults

            pc = pickcenter[0]  # Use first provider (highest priority)
            if not isinstance(pc, dict):
                return defaults

            spread = pc.get('spread')
            over_under = pc.get('overUnder')
            odds_details = str(pc.get('details', ''))
            provider = pc.get('provider', {})
            odds_provider = provider.get('name', '') if isinstance(provider, dict) else ''

            home_odds = pc.get('homeTeamOdds', {})
            away_odds = pc.get('awayTeamOdds', {})
            home_moneyline = home_odds.get('moneyLine') if isinstance(home_odds, dict) else None
            away_moneyline = away_odds.get('moneyLine') if isinstance(away_odds, dict) else None
            home_spread_odds = home_odds.get('spreadOdds') if isinstance(home_odds, dict) else None
            away_spread_odds = away_odds.get('spreadOdds') if isinstance(away_odds, dict) else None

            home_prob = _moneyline_to_prob(home_moneyline)
            away_prob = _moneyline_to_prob(away_moneyline)
            max_prob = max(home_prob or 0.0, away_prob or 0.0) or None

            def _to_int(v):
                try: return int(float(v)) if v is not None else None
                except: return None

            return {
                'spread': float(spread) if spread is not None else None,
                'over_under': float(over_under) if over_under is not None else None,
                'home_moneyline': int(home_moneyline) if home_moneyline is not None else None,
                'away_moneyline': int(away_moneyline) if away_moneyline is not None else None,
                'home_implied_prob': home_prob,
                'away_implied_prob': away_prob,
                'max_implied_prob': max_prob,
                'over_odds':  _to_int(pc.get('overOdds')),
                'under_odds': _to_int(pc.get('underOdds')),
                'home_spread_odds': _to_int(home_spread_odds),
                'away_spread_odds': _to_int(away_spread_odds),
                'odds_details': odds_details,
                'odds_provider': odds_provider,
            }

        except Exception as e:
            print(f"[ESPN-NHL] Odds parse error for event {event_id}: {e}")
            return defaults


def _moneyline_to_prob(ml) -> float | None:
    """Convert American moneyline to implied win probability (0.0-1.0)."""
    if ml is None:
        return None
    try:
        ml = float(ml)
        if ml > 0:
            return 100.0 / (ml + 100.0)
        else:
            return abs(ml) / (abs(ml) + 100.0)
    except (ValueError, TypeError):
        return None
