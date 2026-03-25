"""
MLB Season Projections Engine
==============================

Generates full-season stat projections for batters and pitchers using
Marcel-style weighted averages, age curves, and park factor adjustments.

Designed for two use cases:
  1. Season-long prop bets (sportsbook season total lines):
       "Will Aaron Judge hit OVER/UNDER 42.5 HR this season?"
  2. Context features for daily picks:
       Season pace projection as a baseline for rolling-average models.

Marcel Projection Methodology (Thorn & James, simplified):
  - Weighted average of last 3 seasons: 5/4/3 weights (most recent = 5)
  - Regression to mean: pull projection toward league average (~30%)
  - Age adjustment: +1%/year age 26 and under, -1%/year age 30 and over
  - Playing time: plate appearances (batters) or innings pitched (pitchers)

Usage:
    from season_projections import SeasonProjector

    proj = SeasonProjector()

    # Get a batter's projected season stats
    batter = proj.project_batter('Aaron Judge', player_id=592450)
    print(batter['hr'])          # e.g. 43.2
    print(batter['confidence'])  # 'HIGH' / 'MEDIUM' / 'LOW'

    # Compare against a sportsbook line
    result = proj.evaluate_season_prop('Aaron Judge', 'hr', 42.5, 'OVER')
    print(result['edge'])         # +6.2% edge vs break-even
    print(result['recommendation'])  # 'LEAN OVER'

    # Generate full slate of season prop picks
    picks = proj.get_season_prop_picks()
"""

import sys
import json
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import DB_PATH, MLB_API_BASE, MLB_API_TIMEOUT, SEASON
from park_factors import get_park_factor_by_team


# ============================================================================
# LEAGUE AVERAGE BASELINES (2023-2025 MLB averages, per 650 PA / 180 IP)
# Used for Marcel regression-to-mean step.
# ============================================================================

LEAGUE_AVG_BATTER = {
    'hr':    22,      # HR per 650 PA
    'rbi':   72,
    'runs':  78,
    'hits':  155,
    'sb':    12,
    'walks': 60,
    'k':     155,     # batter strikeouts
    'avg':   0.248,
    'obp':   0.318,
    'slg':   0.411,
    'tb':    255,
}

LEAGUE_AVG_PITCHER = {
    'k_per_9':    8.5,
    'bb_per_9':   3.1,
    'era':        4.20,
    'whip':       1.28,
    'ip':         170,     # per full season (starter)
    'k_total':    160,     # K per season
    'bb_total':   59,
    'hits_allowed_total': 160,
    'er_total':   79,
    'outs_recorded': 510,  # 170 IP * 3
}

# Marcel regression weight: how much to pull toward league average
# Higher = more regression (e.g. volatile stats like HR regress more)
REGRESSION_WEIGHT = {
    'hr': 0.30,
    'rbi': 0.25,
    'runs': 0.25,
    'hits': 0.20,
    'sb': 0.40,        # Very volatile
    'walks': 0.20,
    'k': 0.20,
    'tb': 0.22,
    'k_per_9': 0.20,
    'bb_per_9': 0.30,
    'era': 0.35,
    'whip': 0.30,
}

# Confidence tier based on seasons of data available
CONFIDENCE_TIERS = {
    3: 'HIGH',    # 3 full seasons of data
    2: 'MEDIUM',  # 2 seasons
    1: 'LOW',     # 1 season (high uncertainty)
    0: 'VERY LOW',
}

# Age curve: peak is 27, decline begins ~30
# Returns multiplier relative to peak
def _age_multiplier(age: int, stat: str) -> float:
    """
    Marcel age adjustment. Power stats (HR, SB) decline faster than
    contact stats (hits, BB).
    """
    peak = 27
    if age <= peak:
        annual_gain = 0.010 if stat in ('hr', 'sb', 'tb') else 0.006
        return 1.0 + annual_gain * (peak - age)
    else:
        if stat in ('hr', 'sb'):
            annual_decline = 0.015
        elif stat in ('rbi', 'runs', 'tb'):
            annual_decline = 0.012
        else:
            annual_decline = 0.008
        years_past_peak = max(0, age - peak)
        return max(0.60, 1.0 - annual_decline * years_past_peak)


class SeasonProjector:
    """
    Generates season-long stat projections using Marcel methodology.

    Data flow:
      1. Query player_game_logs for last 1-3 seasons of per-game data
      2. Roll up to per-season totals + playing time
      3. Apply Marcel weights (5/4/3), regression, age curve, park factor
      4. Return projected full-season totals
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._pa_per_game_cache: Dict[str, float] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def project_batter(self, player_name: str, player_id: int = None,
                       team: str = None, home_park: str = None,
                       target_pa: int = 550) -> Dict:
        """
        Project a batter's full-season stats.

        Args:
            player_name: Player name (used for DB lookup)
            player_id: MLB Stats API player ID (used for API lookup)
            team: Team abbreviation for park factor lookup
            home_park: Override park name
            target_pa: Projected plate appearances (default 550)

        Returns:
            Dict with projected stats, confidence, data summary
        """
        seasons = self._get_batter_seasons(player_name, player_id)
        if not seasons:
            return self._empty_projection(player_name, 'batter')

        # Marcel weights: 5 (most recent), 4, 3
        weights = [5, 4, 3]
        weighted_stats = {}
        total_weight = 0

        for i, season_data in enumerate(seasons[:3]):
            w = weights[i]
            pa = season_data.get('pa', 1)
            if pa < 50:
                continue
            per_pa = {
                stat: season_data.get(stat, 0) / pa
                for stat in ('hr', 'rbi', 'runs', 'hits', 'sb', 'walks', 'k', 'tb')
            }
            for stat, rate in per_pa.items():
                weighted_stats[stat] = weighted_stats.get(stat, 0) + rate * w
            total_weight += w

        if total_weight == 0:
            return self._empty_projection(player_name, 'batter')

        # Average per-PA rates across weighted seasons
        avg_rates = {stat: val / total_weight for stat, val in weighted_stats.items()}

        # Regression to mean
        reg_rates = {}
        n_seasons = len([s for s in seasons[:3] if s.get('pa', 0) >= 50])
        for stat, rate in avg_rates.items():
            league_per_pa = LEAGUE_AVG_BATTER[stat] / 650
            reg_w = REGRESSION_WEIGHT.get(stat, 0.25) * (3 - n_seasons + 1) / 3
            reg_rates[stat] = rate * (1 - reg_w) + league_per_pa * reg_w

        # Age adjustment
        age = seasons[0].get('age')
        if age:
            reg_rates = {
                stat: rate * _age_multiplier(age, stat)
                for stat, rate in reg_rates.items()
            }

        # Park factor adjustment
        park_adj = {}
        if team:
            for stat in reg_rates:
                pf_key = {'hr': 'hr', 'hits': 'hits', 'tb': 'hits',
                          'runs': 'runs', 'sb': '3b'}.get(stat)
                if pf_key:
                    pf = get_park_factor_by_team(team, pf_key) or 1.0
                    park_adj[stat] = (pf - 1.0) * 0.5  # Home games only = 50%
                else:
                    park_adj[stat] = 0.0
        else:
            park_adj = {stat: 0.0 for stat in reg_rates}

        # Scale to target_pa
        projections = {}
        for stat, rate in reg_rates.items():
            raw = rate * target_pa * (1 + park_adj.get(stat, 0))
            projections[stat] = round(raw, 1)

        # Add rate stats
        h = projections.get('hits', 0)
        if target_pa > 0 and h > 0:
            projections['avg'] = round(h / (target_pa * 0.82), 3)   # ~82% of PA = AB
        projections['pa_projected'] = target_pa

        return {
            'player_name': player_name,
            'player_type': 'batter',
            'team': team or '',
            'seasons_used': n_seasons,
            'confidence': CONFIDENCE_TIERS.get(n_seasons, 'VERY LOW'),
            'age': age,
            'projections': projections,
            'method': 'marcel',
            'season': SEASON,
        }

    def project_pitcher(self, player_name: str, player_id: int = None,
                        team: str = None, target_ip: float = 165.0) -> Dict:
        """
        Project a pitcher's full-season stats.

        Args:
            player_name: Player name
            player_id: MLB Stats API player ID
            team: Team abbreviation
            target_ip: Projected innings pitched (starter default = 165)

        Returns:
            Dict with projected stats, confidence, data summary
        """
        seasons = self._get_pitcher_seasons(player_name, player_id)
        if not seasons:
            return self._empty_projection(player_name, 'pitcher')

        weights = [5, 4, 3]
        weighted_stats = {}
        total_weight = 0

        for i, season_data in enumerate(seasons[:3]):
            w = weights[i]
            ip = season_data.get('ip', 0)
            if ip < 20:
                continue
            per_ip = {
                'k':     season_data.get('k', 0) / ip,
                'bb':    season_data.get('bb', 0) / ip,
                'hits':  season_data.get('hits', 0) / ip,
                'er':    season_data.get('er', 0) / ip,
            }
            for stat, rate in per_ip.items():
                weighted_stats[stat] = weighted_stats.get(stat, 0) + rate * w
            total_weight += w

        if total_weight == 0:
            return self._empty_projection(player_name, 'pitcher')

        avg_rates = {stat: val / total_weight for stat, val in weighted_stats.items()}

        # Regression
        n_seasons = len([s for s in seasons[:3] if s.get('ip', 0) >= 20])
        league_per_ip = {
            'k':    LEAGUE_AVG_PITCHER['k_per_9'] / 9,
            'bb':   LEAGUE_AVG_PITCHER['bb_per_9'] / 9,
            'hits': LEAGUE_AVG_PITCHER['hits_allowed_total'] / 170,
            'er':   LEAGUE_AVG_PITCHER['er_total'] / 170,
        }
        reg_rates = {}
        for stat, rate in avg_rates.items():
            reg_w = REGRESSION_WEIGHT.get(
                {'k': 'k_per_9', 'bb': 'bb_per_9', 'er': 'era'}.get(stat, stat),
                0.25
            ) * (3 - n_seasons + 1) / 3
            reg_rates[stat] = rate * (1 - reg_w) + league_per_ip[stat] * reg_w

        # Age adjustment
        age = seasons[0].get('age')
        if age:
            reg_rates['k']  = reg_rates['k']  * _age_multiplier(age, 'k_per_9')
            reg_rates['bb'] = reg_rates['bb']  * _age_multiplier(age, 'bb_per_9')

        # Scale to target_ip
        target_outs = round(target_ip * 3)
        projections = {
            'k_total':        round(reg_rates['k'] * target_ip, 1),
            'bb_total':       round(reg_rates['bb'] * target_ip, 1),
            'hits_allowed':   round(reg_rates['hits'] * target_ip, 1),
            'er_total':       round(reg_rates['er'] * target_ip, 1),
            'outs_recorded':  target_outs,
            'ip_projected':   target_ip,
            'era':            round(reg_rates['er'] * 9, 2),
            'whip':           round((reg_rates['bb'] + reg_rates['hits']), 3),
            'k_per_9':        round(reg_rates['k'] * 9, 2),
            'bb_per_9':       round(reg_rates['bb'] * 9, 2),
        }

        return {
            'player_name': player_name,
            'player_type': 'pitcher',
            'team': team or '',
            'seasons_used': n_seasons,
            'confidence': CONFIDENCE_TIERS.get(n_seasons, 'VERY LOW'),
            'age': age,
            'projections': projections,
            'method': 'marcel',
            'season': SEASON,
        }

    def evaluate_season_prop(self, player_name: str, stat: str,
                              line: float, direction: str,
                              player_id: int = None, team: str = None,
                              player_type: str = 'batter') -> Dict:
        """
        Evaluate a sportsbook season-long prop bet.

        Args:
            player_name: Player name
            stat: Stat category (e.g., 'hr', 'k_total', 'hits')
            line: Sportsbook line (e.g., 42.5)
            direction: 'OVER' or 'UNDER'
            player_id: Optional MLB player ID
            team: Team abbreviation
            player_type: 'batter' or 'pitcher'

        Returns:
            Dict with projection, edge, recommendation, confidence
        """
        if player_type == 'pitcher':
            proj = self.project_pitcher(player_name, player_id, team)
        else:
            proj = self.project_batter(player_name, player_id, team)

        if not proj.get('projections'):
            return {
                'player_name': player_name,
                'stat': stat,
                'line': line,
                'direction': direction,
                'projection': None,
                'edge': 0.0,
                'recommendation': 'NO DATA',
                'confidence': 'VERY LOW',
            }

        projection = proj['projections'].get(stat)
        if projection is None:
            return {
                'player_name': player_name,
                'stat': stat,
                'line': line,
                'direction': direction,
                'projection': None,
                'edge': 0.0,
                'recommendation': 'STAT NOT PROJECTED',
                'confidence': 'VERY LOW',
            }

        # Model probability: use normal distribution around projection
        # Standard deviation estimated from historical variance by stat
        STAT_STD_FACTOR = {
            'hr': 0.22, 'rbi': 0.18, 'runs': 0.16, 'hits': 0.10,
            'sb': 0.35, 'tb': 0.12, 'walks': 0.18, 'k': 0.12,
            'k_total': 0.14, 'bb_total': 0.20, 'era': 0.20,
        }
        std_factor = STAT_STD_FACTOR.get(stat, 0.18)
        std_dev = max(projection * std_factor, 2.0)

        # P(OVER line) using normal CDF approximation
        z = (line - projection) / std_dev
        p_over = 0.5 * (1 - _erf(z / 1.4142))

        prob = p_over if direction == 'OVER' else (1 - p_over)
        edge = (prob - 0.524) * 100   # vs ~52.4% break-even (standard -110 juice)

        # Recommendation
        if abs(edge) < 3:
            rec = 'PASS — too close to line'
        elif prob >= 0.65 and edge > 5:
            rec = f'STRONG {direction}'
        elif prob >= 0.57:
            rec = f'LEAN {direction}'
        else:
            rec = f'PASS — edge insufficient'

        return {
            'player_name':  player_name,
            'stat':         stat,
            'line':         line,
            'direction':    direction,
            'projection':   round(projection, 1),
            'std_dev':      round(std_dev, 1),
            'probability':  round(prob, 4),
            'edge':         round(edge, 2),
            'recommendation': rec,
            'confidence':   proj['confidence'],
            'seasons_used': proj['seasons_used'],
            'age':          proj.get('age'),
        }

    def get_season_prop_picks(self, min_edge: float = 5.0,
                              min_confidence: str = 'MEDIUM') -> List[Dict]:
        """
        Generate a ranked list of season-long prop picks from the DB.

        Fetches all players in player_game_logs, projects their season stats,
        and returns any with edge >= min_edge vs estimated sportsbook lines.

        NOTE: Sportsbook lines must be provided externally (DK/FD don't have
        a free API). This method generates projections for YOUR lines to compare.

        Args:
            min_edge: Minimum edge % to include (default 5%)
            min_confidence: Minimum confidence level ('LOW', 'MEDIUM', 'HIGH')

        Returns:
            List of season prop pick dicts, sorted by edge descending
        """
        tier_order = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'VERY LOW': 0}
        min_tier = tier_order.get(min_confidence, 1)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get all unique players in our game logs
        players = conn.execute('''
            SELECT DISTINCT player_name, player_type, team,
                   MAX(game_date) as last_seen
            FROM player_game_logs
            GROUP BY player_name, player_type, team
            ORDER BY last_seen DESC
            LIMIT 500
        ''').fetchall()
        conn.close()

        picks = []
        for row in players:
            pname = row['player_name']
            ptype = row['player_type']
            team  = row['team']

            if ptype == 'batter':
                proj = self.project_batter(pname, team=team)
            else:
                proj = self.project_pitcher(pname, team=team)

            if tier_order.get(proj['confidence'], 0) < min_tier:
                continue

            picks.append({
                'player_name': pname,
                'player_type': ptype,
                'team': team,
                'confidence': proj['confidence'],
                'seasons_used': proj['seasons_used'],
                'projections': proj['projections'],
            })

        return picks

    # ── Data fetchers ──────────────────────────────────────────────────────────

    def _get_batter_seasons(self, player_name: str,
                             player_id: int = None) -> List[Dict]:
        """
        Pull last 3 seasons of batter game logs from:
          1. Local player_game_logs table (games we've tracked)
          2. MLB Stats API career stats (for pre-collection history)
        Returns list sorted most-recent-first.
        """
        seasons = []

        # Try MLB Stats API first — gives us full career history
        api_seasons = self._fetch_api_batter_seasons(player_id, player_name)
        if api_seasons:
            return api_seasons

        # Fall back to local DB
        return self._get_local_batter_seasons(player_name)

    def _get_pitcher_seasons(self, player_name: str,
                              player_id: int = None) -> List[Dict]:
        """Pull last 3 seasons of pitcher game logs."""
        api_seasons = self._fetch_api_pitcher_seasons(player_id, player_name)
        if api_seasons:
            return api_seasons
        return self._get_local_pitcher_seasons(player_name)

    def _fetch_api_batter_seasons(self, player_id: int,
                                   player_name: str) -> List[Dict]:
        """Fetch batter career stats from MLB Stats API."""
        if not player_id:
            player_id = self._lookup_player_id(player_name)
        if not player_id:
            return []

        try:
            url = (f"{MLB_API_BASE}/people/{player_id}/stats"
                   f"?stats=yearByYear&group=hitting&gameType=R")
            req = urllib.request.urlopen(url, timeout=MLB_API_TIMEOUT)
            data = json.loads(req.read())
            stats_list = data.get('stats', [])
            if not stats_list:
                return []

            seasons = []
            current_year = int(SEASON[:4])
            for entry in stats_list[0].get('splits', []):
                yr = int(entry.get('season', 0))
                if yr < current_year - 3 or yr >= current_year:
                    continue
                s = entry.get('stat', {})
                pa = s.get('plateAppearances', 0)
                if pa < 50:
                    continue
                birth_date = None
                try:
                    person = data.get('people', [{}])[0]
                    birth_date = person.get('birthDate', '')
                    if birth_date:
                        birth_year = int(birth_date[:4])
                        age = yr - birth_year
                    else:
                        age = None
                except Exception:
                    age = None

                seasons.append({
                    'season': yr,
                    'pa':     pa,
                    'hr':     s.get('homeRuns', 0),
                    'rbi':    s.get('rbi', 0),
                    'runs':   s.get('runs', 0),
                    'hits':   s.get('hits', 0),
                    'sb':     s.get('stolenBases', 0),
                    'walks':  s.get('baseOnBalls', 0),
                    'k':      s.get('strikeOuts', 0),
                    'tb':     s.get('totalBases', 0),
                    'avg':    float(s.get('avg', 0) or 0),
                    'age':    age,
                })

            seasons.sort(key=lambda x: x['season'], reverse=True)
            # Enrich each entry with age from most recent
            if seasons:
                most_recent_age = seasons[0].get('age')
                for i, s in enumerate(seasons):
                    if s.get('age') is None and most_recent_age:
                        s['age'] = most_recent_age + i
            return seasons[:3]

        except Exception as e:
            print(f"[Projections] API batter fetch failed for {player_name}: {e}")
            return []

    def _fetch_api_pitcher_seasons(self, player_id: int,
                                    player_name: str) -> List[Dict]:
        """Fetch pitcher career stats from MLB Stats API."""
        if not player_id:
            player_id = self._lookup_player_id(player_name)
        if not player_id:
            return []

        try:
            url = (f"{MLB_API_BASE}/people/{player_id}/stats"
                   f"?stats=yearByYear&group=pitching&gameType=R")
            req = urllib.request.urlopen(url, timeout=MLB_API_TIMEOUT)
            data = json.loads(req.read())
            stats_list = data.get('stats', [])
            if not stats_list:
                return []

            seasons = []
            current_year = int(SEASON[:4])
            for entry in stats_list[0].get('splits', []):
                yr = int(entry.get('season', 0))
                if yr < current_year - 3 or yr >= current_year:
                    continue
                s = entry.get('stat', {})
                ip_str = s.get('inningsPitched', '0')
                try:
                    ip = float(ip_str)
                    # Convert fractional innings (e.g. 162.1 = 162 + 1/3 = 162.33)
                    whole = int(ip)
                    frac = ip - whole
                    ip = whole + (frac * 10 / 3)
                except Exception:
                    ip = 0
                if ip < 20:
                    continue
                seasons.append({
                    'season': yr,
                    'ip':     round(ip, 1),
                    'k':      s.get('strikeOuts', 0),
                    'bb':     s.get('baseOnBalls', 0),
                    'hits':   s.get('hits', 0),
                    'er':     s.get('earnedRuns', 0),
                    'era':    float(s.get('era', 4.5) or 4.5),
                    'whip':   float(s.get('whip', 1.3) or 1.3),
                    'age':    None,
                })

            seasons.sort(key=lambda x: x['season'], reverse=True)
            return seasons[:3]

        except Exception as e:
            print(f"[Projections] API pitcher fetch failed for {player_name}: {e}")
            return []

    def _lookup_player_id(self, player_name: str) -> Optional[int]:
        """Search MLB Stats API for a player ID by name."""
        try:
            params = urllib.parse.urlencode({
                'search': player_name,
                'sportId': 1,
            })
            url = f"{MLB_API_BASE}/people/search?{params}"
            req = urllib.request.urlopen(url, timeout=MLB_API_TIMEOUT)
            data = json.loads(req.read())
            people = data.get('people', [])
            if people:
                return people[0].get('id')
        except Exception:
            pass
        return None

    def _get_local_batter_seasons(self, player_name: str) -> List[Dict]:
        """Build season totals from local player_game_logs."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute('''
                SELECT substr(game_date, 1, 4) as season,
                       COUNT(*) as games,
                       SUM(at_bats) as pa,
                       SUM(home_runs) as hr,
                       SUM(rbis) as rbi,
                       SUM(runs) as runs,
                       SUM(hits) as hits,
                       SUM(stolen_bases) as sb,
                       SUM(walks_drawn) as walks,
                       SUM(strikeouts_batter) as k,
                       SUM(total_bases) as tb
                FROM player_game_logs
                WHERE player_name = ? AND player_type = 'batter'
                  AND at_bats > 0
                GROUP BY season
                ORDER BY season DESC
                LIMIT 3
            ''', (player_name,)).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _get_local_pitcher_seasons(self, player_name: str) -> List[Dict]:
        """Build pitcher season totals from local player_game_logs."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute('''
                SELECT substr(game_date, 1, 4) as season,
                       COUNT(*) as games,
                       SUM(innings_pitched) as ip,
                       SUM(strikeouts_pitched) as k,
                       SUM(walks_allowed) as bb,
                       SUM(hits_allowed) as hits,
                       SUM(earned_runs) as er
                FROM player_game_logs
                WHERE player_name = ? AND player_type = 'pitcher'
                  AND innings_pitched > 0
                GROUP BY season
                ORDER BY season DESC
                LIMIT 3
            ''', (player_name,)).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _empty_projection(self, player_name: str, player_type: str) -> Dict:
        return {
            'player_name': player_name,
            'player_type': player_type,
            'team': '',
            'seasons_used': 0,
            'confidence': 'VERY LOW',
            'age': None,
            'projections': {},
            'method': 'none',
            'season': SEASON,
        }


# ── Error function approximation (no scipy needed) ───────────────────────────

def _erf(x: float) -> float:
    """Abramowitz & Stegun approximation of the error function."""
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t)
                  + 1.421413741) * t - 0.284496736) * t
                + 0.254829592) * t * (2.718281828 ** (-x * x))
    return sign * y


# ── CLI interface ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='MLB Season Projections')
    parser.add_argument('--player', type=str, help='Player name')
    parser.add_argument('--type', choices=['batter', 'pitcher'], default='batter')
    parser.add_argument('--team', type=str, help='Team abbreviation')
    parser.add_argument('--stat', type=str, help='Stat for prop evaluation (e.g. hr)')
    parser.add_argument('--line', type=float, help='Sportsbook line')
    parser.add_argument('--direction', choices=['OVER', 'UNDER'], default='OVER')
    parser.add_argument('--id', type=int, dest='player_id', help='MLB player ID')
    args = parser.parse_args()

    projector = SeasonProjector()

    if args.player and args.stat and args.line:
        result = projector.evaluate_season_prop(
            args.player, args.stat, args.line, args.direction,
            player_id=args.player_id, team=args.team, player_type=args.type
        )
        print(f"\n{'='*60}")
        print(f"Season Prop: {result['player_name']} {result['stat'].upper()} "
              f"{result['direction']} {result['line']}")
        print(f"{'='*60}")
        print(f"  Projection:    {result['projection']}")
        print(f"  Model prob:    {result['probability']*100:.1f}%")
        print(f"  Edge vs -110:  {result['edge']:+.1f}%")
        print(f"  Recommendation: {result['recommendation']}")
        print(f"  Confidence:    {result['confidence']} ({result['seasons_used']} seasons)")
        print()

    elif args.player:
        if args.type == 'pitcher':
            proj = projector.project_pitcher(args.player, args.player_id, args.team)
        else:
            proj = projector.project_batter(args.player, args.player_id, args.team)

        print(f"\n{'='*60}")
        print(f"{proj['player_name']} — {SEASON} Season Projection ({proj['method'].upper()})")
        print(f"Confidence: {proj['confidence']} | Seasons of data: {proj['seasons_used']}")
        print(f"{'='*60}")
        for stat, val in sorted(proj['projections'].items()):
            print(f"  {stat:<20} {val}")
        print()

    else:
        print("Usage examples:")
        print("  python season_projections.py --player 'Aaron Judge' --type batter --team NYY")
        print("  python season_projections.py --player 'Aaron Judge' --stat hr --line 42.5 --direction OVER")
        print("  python season_projections.py --player 'Gerrit Cole' --type pitcher --id 543037")
