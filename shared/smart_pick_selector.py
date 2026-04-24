#!/usr/bin/env python3
"""
Smart Pick Selector - ONLY shows plays that are ACTUALLY available on PrizePicks

Key Features:
1. Fetches REAL PrizePicks lines (not just stored data)
2. Recalculates probability for PP's ACTUAL line (using our Poisson model)
3. Calculates Expected Value based on parlay payouts
4. Filters to high-edge plays only

This solves the problem of showing predictions for lines that don't exist.
"""

import sqlite3
import json
import math
import argparse
import requests
import os
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from fuzzywuzzy import fuzz


def _strip_diacritics(name: str) -> str:
    """Normalize player names to ASCII by stripping diacritical marks.
    'Tim Stützle' -> 'Tim Stutzle', 'Luka Dončić' -> 'Luka Doncic'.
    Used on BOTH sides of the PP<->prediction matching so encodings can't cause misses.
    """
    return ''.join(
        c for c in unicodedata.normalize('NFD', name)
        if unicodedata.category(c) != 'Mn'
    )

# Discord webhook URL — must be set via environment variable (never hardcode)
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')


@dataclass
class SmartPick:
    """A pick that matches an actual PrizePicks line"""
    player_name: str        # PrizePicks display name (full name, e.g. "Sam Bennett")
    local_player_name: str  # Local DB name (may be abbreviated, e.g. "S. Bennett")
    team: str
    opponent: str
    prop_type: str

    # Our prediction
    our_line: float
    our_probability: float
    our_lambda: float  # Expected value (shots/points) - recent form

    # PrizePicks actual line
    pp_line: float
    pp_odds_type: str  # 'standard', 'goblin', 'demon'

    # Recalculated for PP line
    pp_probability: float  # Probability for PP's actual line
    prediction: str  # 'OVER' or 'UNDER'
    edge: float  # pp_probability - break_even

    # ML vs Baseline comparison
    season_avg: float = 0.0  # Naive baseline (season average)
    recent_avg: float = 0.0  # What ML uses (L10 or L5)
    baseline_prob: float = 0.0  # What a naive model would predict
    ml_adjustment: float = 0.0  # pp_probability - baseline_prob (positive = ML likes it more)

    # Expected Value for different parlay sizes
    ev_2leg: float = 0.0
    ev_3leg: float = 0.0
    ev_4leg: float = 0.0
    ev_5leg: float = 0.0
    ev_6leg: float = 0.0

    # Confidence tier
    tier: str = 'T5-FADE'

    # σ-distance and line quality signals
    sigma: float = 0.0              # Standard deviation used for probability calculation
    sigma_distance: float = 0.0     # (variant_line - standard_line) / sigma; 0 = standard line
    parlay_score: float = 0.0       # Probability adjusted for player consistency (lower CoV = better)

    # Line movement (did the market agree with our pick?)
    line_movement: float = 0.0      # Standard line change today (+ = moved up, - = moved down)
    movement_agrees: bool = True    # True if our prediction direction agrees with line movement direction

    # Calibration adjustment
    calibration_correction: float = 0.0  # Historical correction applied to probability

    # Rest / fatigue signal
    days_rest: int = 3              # Player's days since last game (0 = back-to-back)

    # Situational intelligence (advisory only -- NEVER modifies DB predictions)
    situation_flag: str = 'NORMAL'      # DEAD_RUBBER | REDUCED_STAKES | HIGH_STAKES | USAGE_BOOST | NORMAL
    situation_modifier: float = 0.0     # Advisory delta (-0.15 to +0.05)
    situation_notes: str = ''           # e.g. "LAL 4-seed locked, 4 games left -- Doncic/Reaves out"

    def __post_init__(self):
        # Cap probability at 95% - no model can be 100% certain
        if self.pp_probability > 0.95:
            self.pp_probability = 0.95
        self.tier = self._get_tier()
        self._calculate_ev()

    def _get_tier(self) -> str:
        # Tier is based on EDGE above break-even, not raw probability.
        # This ensures goblin/demon picks are tiered correctly:
        #   Standard 75% = edge +19% = T1-ELITE  ✓
        #   Goblin   75% = edge  -1% = T5-FADE   ✓ (was wrongly T1-ELITE before)
        #   Demon    64% = edge +19% = T1-ELITE   ✓ (low prob but very profitable)
        edge = self.edge
        if edge >= 19:
            return 'T1-ELITE'
        elif edge >= 14:
            return 'T2-STRONG'
        elif edge >= 9:
            return 'T3-GOOD'
        elif edge >= 0:
            return 'T4-LEAN'
        else:
            return 'T5-FADE'

    def _calculate_ev(self):
        """
        Calculate expected value using dynamic leg value derived from sigma_distance.

        Leg value scales with how far the line is from standard, using the
        actual PrizePicks payout table. Verified anchors:
          goblin at σ=-1.0 → LV=0.50 → 4-pick total=2.0 → payout=3x  → BE=76.0% ✓
          standard         → LV=1.00 → 4-pick total=4.0 → payout=10x → BE=56.2% ✓
          demon  at σ=+1.0 → LV=1.50 → 4-pick total=6.0 → payout=25x → BE=44.7% ✓
        """
        # Payout table: total leg equivalents → multiplier
        PAYOUT_TABLE = {1.0: 2.0, 2.0: 3.0, 3.0: 5.0, 4.0: 10.0, 5.0: 20.0, 6.0: 25.0}

        def _interp_payout(total_lv: float) -> float:
            total_lv = max(1.0, min(6.0, total_lv))
            keys = sorted(PAYOUT_TABLE.keys())
            for i in range(len(keys) - 1):
                lo, hi = keys[i], keys[i + 1]
                if lo <= total_lv <= hi:
                    t = (total_lv - lo) / (hi - lo)
                    return PAYOUT_TABLE[lo] + t * (PAYOUT_TABLE[hi] - PAYOUT_TABLE[lo])
            return PAYOUT_TABLE[keys[-1]]

        # Dynamic leg value from sigma_distance (falls back to static defaults at σ=0)
        if self.pp_odds_type == 'goblin' and self.sigma_distance != 0.0:
            self.leg_value = max(0.10, min(1.0, 0.5 * abs(self.sigma_distance)))
        elif self.pp_odds_type == 'demon' and self.sigma_distance != 0.0:
            self.leg_value = max(1.0, min(3.0, 1.0 + 0.5 * self.sigma_distance))
        else:
            # Standard, or variant with no σ-distance (fallback to static)
            fallback = {'standard': 1.0, 'goblin': 0.5, 'demon': 1.5}
            self.leg_value = fallback.get(self.pp_odds_type, 1.0)

        p = self.pp_probability
        # EV for N same-type picks: EV = p^N * payout(N * leg_value) - 1
        evs = []
        for n in [2, 3, 4, 5, 6]:
            payout = _interp_payout(n * self.leg_value)
            evs.append(round(p ** n * payout - 1, 4))
        self.ev_2leg, self.ev_3leg, self.ev_4leg, self.ev_5leg, self.ev_6leg = evs

        # Parlay suitability score: reward consistent players (lower CoV = better leg)
        # CoV = sigma / recent_avg; lower = more predictable
        if self.recent_avg > 0 and self.sigma > 0:
            cov = self.sigma / self.recent_avg
            self.parlay_score = round(p / (1.0 + cov), 4)
        else:
            self.parlay_score = round(p * 0.85, 4)  # Slight penalty for unknown variance


class SmartPickSelector:
    """
    Selects picks based on ACTUAL PrizePicks availability.

    Unlike edge_calculator.py which shows predictions for lines that might not exist,
    this starts from PP's actual lines and recalculates our predictions for them.
    """

    # Payout table: total leg-equivalents → multiplier (used by compute_break_even)
    _PAYOUT_TABLE = {1.0: 2.0, 2.0: 3.0, 3.0: 5.0, 4.0: 10.0, 5.0: 20.0, 6.0: 25.0}

    @staticmethod
    def estimate_leg_value(odds_type: str, sigma_distance: float) -> float:
        """
        Estimate leg value for a line variant based on σ-distance from the standard line.

        Derivation (4-pick parlay, verified against PP payout table):
          goblin σ=-0.5 → LV=0.25 → total=1.0 → payout=2x  → break-even=84.1%
          goblin σ=-1.0 → LV=0.50 → total=2.0 → payout=3x  → break-even=76.0% ✓ static
          goblin σ=-1.5 → LV=0.75 → total=3.0 → payout=5x  → break-even=66.9%
          demon  σ=+0.5 → LV=1.25 → total=5.0 → payout=20x → break-even=47.3%
          demon  σ=+1.0 → LV=1.50 → total=6.0 → payout=25x → break-even=44.7% ✓ static
        """
        if odds_type == 'standard':
            return 1.0
        if odds_type == 'goblin':
            # More negative σ = easier line = worse payout = smaller leg value
            return max(0.10, min(1.0, 0.5 * abs(sigma_distance)))
        if odds_type == 'demon':
            # More positive σ = harder line = better payout = larger leg value
            return max(1.0, min(3.0, 1.0 + 0.5 * sigma_distance))
        return 1.0

    @classmethod
    def _interpolate_payout(cls, total_lv: float) -> float:
        """Linearly interpolate payout from the PrizePicks payout table."""
        total_lv = max(1.0, min(6.0, total_lv))
        keys = sorted(cls._PAYOUT_TABLE.keys())
        for i in range(len(keys) - 1):
            lo, hi = keys[i], keys[i + 1]
            if lo <= total_lv <= hi:
                t = (total_lv - lo) / (hi - lo)
                return cls._PAYOUT_TABLE[lo] + t * (cls._PAYOUT_TABLE[hi] - cls._PAYOUT_TABLE[lo])
        return cls._PAYOUT_TABLE[keys[-1]]

    def compute_break_even(self, odds_type: str, sigma_distance: float, n_picks: int = 4) -> float:
        """
        Compute the break-even probability for a line variant.
        Uses dynamic leg value (σ-distance based), not a static constant.
        Falls back to standard leg values when sigma_distance is 0 (no standard line found).
        """
        if sigma_distance == 0.0 and odds_type != 'standard':
            # No standard line found for comparison — use exact static break-evens.
            # Must stay in sync with gsd_module/shared/odds.py BREAK_EVEN_MAP.
            fallback = {'standard': 110 / 210, 'goblin': 320 / 420, 'demon': 100 / 220}
            return fallback.get(odds_type, 110 / 210)
        lv = self.estimate_leg_value(odds_type, sigma_distance)
        total_lv = max(1.0, min(6.0, n_picks * lv))
        payout = self._interpolate_payout(total_lv)
        return (1.0 / payout) ** (1.0 / n_picks)

    def _load_line_movements(self, game_date: str) -> dict:
        """
        Detect today's line movement by comparing first vs latest fetched_at value
        for each (player, prop) standard line.

        Returns: {(player_name_lower, prop_type): {'line_movement': float, 'direction': str}}
        """
        try:
            conn = sqlite3.connect(str(self.pp_db_path))
            # Use CTEs to pre-compute min/max fetched_at per player+prop — avoids
            # correlated subqueries which are O(n²) on large prizepicks_lines tables.
            rows = conn.execute("""
                WITH bounds AS (
                    SELECT
                        LOWER(player_name) AS player_lower,
                        prop_type,
                        MIN(fetched_at) AS first_fetch,
                        MAX(fetched_at) AS last_fetch
                    FROM prizepicks_lines
                    WHERE odds_type = 'standard'
                      AND substr(start_time, 1, 10) = ?
                      AND league = ?
                    GROUP BY LOWER(player_name), prop_type
                ),
                open_lines AS (
                    SELECT LOWER(p.player_name) AS player_lower, p.prop_type, p.line, p.player_name
                    FROM prizepicks_lines p
                    JOIN bounds b
                      ON LOWER(p.player_name) = b.player_lower
                      AND p.prop_type = b.prop_type
                      AND p.fetched_at = b.first_fetch
                    WHERE p.odds_type = 'standard' AND substr(p.start_time, 1, 10) = ?
                ),
                close_lines AS (
                    SELECT LOWER(p.player_name) AS player_lower, p.prop_type, p.line
                    FROM prizepicks_lines p
                    JOIN bounds b
                      ON LOWER(p.player_name) = b.player_lower
                      AND p.prop_type = b.prop_type
                      AND p.fetched_at = b.last_fetch
                    WHERE p.odds_type = 'standard' AND substr(p.start_time, 1, 10) = ?
                )
                SELECT o.player_name, o.prop_type, o.line AS open_line, c.line AS close_line
                FROM open_lines o
                JOIN close_lines c ON o.player_lower = c.player_lower AND o.prop_type = c.prop_type
            """, (game_date, self.sport, game_date, game_date)).fetchall()
            conn.close()

            movements = {}
            for r in rows:
                open_l = r[2] or 0
                close_l = r[3] or 0
                delta = round(close_l - open_l, 1)
                key = (r[0].lower(), r[1])
                movements[key] = {
                    'line_movement': delta,
                    'direction': 'up' if delta > 0.05 else ('down' if delta < -0.05 else 'none'),
                }
            return movements
        except Exception as e:
            print(f"[WARN] Could not load line movements: {e}")
            return {}

    def _load_calibration(self) -> dict:
        """
        Load per-prop-type calibration corrections from prediction_outcomes.
        Bucket predictions into 5% probability windows and compute actual vs predicted hit rate.
        Returns: {(prop_type, prob_bucket): correction_float}
        Requires >= 20 samples per bucket; underpopulated buckets return 0.0.
        """
        try:
            conn = sqlite3.connect(str(self.pred_db_path))
            if self.sport in ('NBA', 'MLB', 'GOLF'):
                # NBA/MLB/GOLF: probability lives in predictions table — join to get it
                rows = conn.execute("""
                    SELECT
                        o.prop_type,
                        ROUND(p.probability / 0.05) * 0.05 AS bucket,
                        COUNT(*) AS n,
                        AVG(CASE WHEN o.outcome = 'HIT' THEN 1.0 ELSE 0.0 END) AS actual_rate,
                        AVG(p.probability) AS avg_predicted
                    FROM prediction_outcomes o
                    JOIN predictions p ON o.prediction_id = p.id
                    WHERE p.probability IS NOT NULL
                    GROUP BY o.prop_type, bucket
                    HAVING n >= 20
                """).fetchall()
            else:
                # NHL: predicted_probability stored directly in prediction_outcomes
                rows = conn.execute("""
                    SELECT
                        prop_type,
                        ROUND(predicted_probability / 0.05) * 0.05 AS bucket,
                        COUNT(*) AS n,
                        AVG(CASE WHEN outcome = 'HIT' THEN 1.0 ELSE 0.0 END) AS actual_rate,
                        ROUND(predicted_probability / 0.05) * 0.05 AS avg_predicted
                    FROM prediction_outcomes
                    WHERE predicted_probability IS NOT NULL
                    GROUP BY prop_type, bucket
                    HAVING n >= 20
                """).fetchall()
            conn.close()

            calibration = {}
            for r in rows:
                prop_type, bucket, n, actual_rate, avg_predicted = r[0], r[1], r[2], r[3], r[4]
                if bucket is None or actual_rate is None or avg_predicted is None:
                    continue
                # Dampen: don't fully trust — only apply 50% of the measured correction
                correction = (actual_rate - avg_predicted) * 0.5
                calibration[(prop_type, round(float(bucket), 2))] = round(correction, 4)
            return calibration
        except Exception as e:
            print(f"[WARN] Could not load calibration: {e}")
            return {}

    def __init__(self, sport: str = 'nhl'):
        self.sport = sport.upper()
        self.root = Path(__file__).parent.parent

        # Database paths
        if sport.lower() == 'nhl':
            self.pred_db_path = self.root / 'nhl' / 'database' / 'nhl_predictions_v2.db'
        elif sport.lower() == 'mlb':
            self.pred_db_path = self.root / 'mlb' / 'database' / 'mlb_predictions.db'
        elif sport.lower() == 'golf':
            self.pred_db_path = self.root / 'golf' / 'database' / 'golf_predictions.db'
        else:
            self.pred_db_path = self.root / 'nba' / 'database' / 'nba_predictions.db'

        self.pp_db_path = self.root / 'shared' / 'prizepicks_lines.db'
        self._intel = None      # PreGameIntel instance (loaded on demand)
        self.game_date = None   # Set to target date inside get_smart_picks()

    def poisson_prob_over(self, lambda_param: float, line: float) -> float:
        """
        Calculate P(X > line) using Poisson distribution (for points).

        For line = k.5, we want P(X >= k+1) = 1 - P(X <= k)
        """
        k = int(line)  # 0.5 -> 0, 1.5 -> 1, 2.5 -> 2, etc.

        # P(X <= k) = sum of P(X = i) for i = 0 to k
        cumulative = 0
        for i in range(k + 1):
            cumulative += (lambda_param ** i) * math.exp(-lambda_param) / math.factorial(i)

        return 1 - cumulative

    def normal_prob_over(self, mean: float, std_dev: float, line: float) -> float:
        """
        Calculate P(X > line) using Normal distribution (for shots).

        Uses error function approximation for CDF.
        """
        if std_dev <= 0:
            return 0.5

        z_score = (line - mean) / std_dev
        # P(X > line) = 1 - CDF(z_score) = 0.5 * (1 - erf(z/sqrt(2)))
        return 0.5 * (1 - self._erf(z_score / math.sqrt(2)))

    def _erf(self, x: float) -> float:
        """Approximation of error function"""
        # Abramowitz and Stegun approximation
        a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
        p = 0.3275911

        sign = 1 if x >= 0 else -1
        x = abs(x)

        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)

        return sign * y

    def fetch_fresh_lines(self) -> int:
        """Fetch fresh lines from PrizePicks API"""
        try:
            from prizepicks_client import PrizePicksIngestion
            ingestion = PrizePicksIngestion()
            result = ingestion.run_ingestion([self.sport])
            count = result.get('total_lines', 0)
            if count == 0:
                msg = (f"[{self.sport}] PP line fetch returned 0 lines. "
                       f"API may be down, blocked, or no lines posted yet. "
                       f"Smart picks will be empty until lines are available.")
                print(f"[WARN] {msg}")
                if DISCORD_WEBHOOK_URL:
                    try:
                        requests.post(DISCORD_WEBHOOK_URL,
                                      json={"content": f":warning: **{self.sport} PP LINE FETCH: 0 LINES**\n{msg}"},
                                      timeout=5)
                    except Exception:
                        pass
            return count
        except Exception as e:
            print(f"Warning: Could not fetch fresh lines: {e}")
            if DISCORD_WEBHOOK_URL:
                try:
                    requests.post(DISCORD_WEBHOOK_URL,
                                  json={"content": f":x: **{self.sport} PP LINE FETCH FAILED**\n`{e}`"},
                                  timeout=5)
                except Exception:
                    pass
            return 0

    def _is_initial_match(self, full_name: str, abbrev_name: str) -> bool:
        """
        Check if abbrev_name ('a. fox') matches full_name ('adam fox').
        Handles the NHL prediction DB abbreviation convention.
        """
        if '. ' not in abbrev_name:
            return False
        parts = abbrev_name.split('. ', 1)
        if len(parts[0]) != 1:
            return False
        initial = parts[0]          # 'a'
        abbrev_last = parts[1]      # 'fox'

        full_parts = full_name.lower().split()
        if len(full_parts) < 2:
            return False
        full_initial = full_parts[0][0]   # 'a' from 'adam'
        full_last = full_parts[-1]        # 'fox'

        return initial == full_initial and abbrev_last == full_last

    def get_smart_picks(
        self,
        game_date: Optional[str] = None,
        min_edge: float = 5.0,
        min_prob: float = 0.55,
        odds_types: List[str] = None,
        refresh_lines: bool = True,
        overs_only: bool = False
    ) -> List[SmartPick]:
        """
        Get smart picks that match ACTUAL PrizePicks lines.

        Args:
            game_date: Date to get picks for (default: today)
            min_edge: Minimum edge percentage (default: 5%)
            min_prob: Minimum probability (default: 55%)
            odds_types: List of odds types to include ['standard', 'goblin', 'demon']
            refresh_lines: Whether to fetch fresh lines first
            overs_only: Only show OVER predictions

        Returns:
            List of SmartPick objects sorted by edge
        """
        if game_date is None:
            game_date = date.today().isoformat()

        self.game_date = game_date

        if self._intel is None:
            try:
                from pregame_intel import PreGameIntel
                self._intel = PreGameIntel()
            except Exception:
                self._intel = None  # Advisory only -- never blocks picks

        if odds_types is None:
            odds_types = ['standard', 'goblin', 'demon']  # Demon BE ~45% — lowest threshold, quality-gated by σ<1.5

        # Optionally refresh lines
        if refresh_lines:
            print(f"[{self.sport}] Fetching fresh PrizePicks lines...")
            count = self.fetch_fresh_lines()
            print(f"[{self.sport}] Fetched {count} lines")

        # Get PrizePicks lines for today
        pp_lines = self._get_pp_lines(game_date, odds_types)
        print(f"[{self.sport}] Found {len(pp_lines)} PP lines")

        # Get our predictions with lambda values
        predictions = self._get_predictions_with_params(game_date)
        print(f"[{self.sport}] Found {len(predictions)} predictions with lambda values")

        # Load auxiliary signals (non-blocking — return empty dict on failure)
        movements = self._load_line_movements(game_date)
        calibration = self._load_calibration()

        # Build lookup: (player_lower, prop_type) → standard line, for σ-distance
        # Use normalized keys so diacritic variants (Stützle/Stutzle) always match.
        standard_lines_by_player = {
            (_strip_diacritics(r['player_name']).lower(), r['prop_type']): r['line']
            for r in pp_lines if r['odds_type'] == 'standard'
        }

        # Build lookup by player + prop.
        # Keys use diacritic-stripped lowercase so 'Stützle' and 'Stutzle' hash the same.
        # Sort each group by probability descending so [0] is always the most
        # confident prediction. This prevents probability inversion when multiple
        # prediction rows exist for the same player+prop (e.g. duplicate STD lines).
        pred_lookup = {}
        for pred in predictions:
            key = (_strip_diacritics(pred['player_name']).lower(), pred['prop_type'])
            if key not in pred_lookup:
                pred_lookup[key] = []
            pred_lookup[key].append(pred)
        for key in pred_lookup:
            pred_lookup[key].sort(key=lambda p: p.get('probability', 0), reverse=True)

        # Match PP lines to our predictions
        smart_picks = []
        matched = 0
        _logged_trades = set()  # Dedupe trade log — one message per player per run

        # Golf: PrizePicks uses different prop names than our internal schema
        _GOLF_PROP_MAP = {'strokes': 'round_score'}

        for pp in pp_lines:
            # Try to find our prediction for this player+prop
            # Strip diacritics so PP 'Stutzle' matches our DB 'Stützle'
            # Golf: map PP prop name to our internal name (strokes -> round_score)
            pp_prop_internal = _GOLF_PROP_MAP.get(pp['prop_type'], pp['prop_type']) if self.sport == 'GOLF' else pp['prop_type']
            key = (_strip_diacritics(pp['player_name']).lower(), pp_prop_internal)

            # If no exact match, try proper fuzzy matching with high threshold
            if key not in pred_lookup:
                best_match_key = None
                best_match_score = 0
                pp_name_lower = _strip_diacritics(pp['player_name']).lower()

                for pred_key in pred_lookup.keys():
                    # Only consider same prop type (use mapped internal name for golf)
                    if pred_key[1] != pp_prop_internal:
                        continue

                    pred_name = pred_key[0]

                    # Initial-name match: handles NHL abbreviated names
                    # e.g. PrizePicks 'Adam Fox' ↔ our DB 'a. fox'
                    if self._is_initial_match(pp_name_lower, pred_name):
                        best_match_key = pred_key
                        best_match_score = 100
                        break

                    # Fall back to fuzzy match for other cases
                    score = fuzz.ratio(pp_name_lower, pred_name)
                    if score > best_match_score and score >= 85:
                        best_match_score = score
                        best_match_key = pred_key

                if best_match_key:
                    key = best_match_key

            if key not in pred_lookup:
                continue

            # Get the prediction with features.
            # NHL/NBA: all predictions for same player+prop share the same statistical
            # parameters — use the highest-prob row (index 0, sorted descending).
            # MLB: each prediction is at a specific line; pick the row whose line
            # is closest to the PP line so stored probability maps to the right threshold.
            if self.sport == 'MLB':
                pred = min(pred_lookup[key],
                           key=lambda p: abs((p.get('line') or 0) - pp['line']))
            else:
                pred = pred_lookup[key][0]
            prop_type = pp['prop_type']

            # Team verification - skip if player changed teams (trade, etc.)
            # Normalize abbreviations: NBA and NHL both have ESPN vs API mismatches
            _TEAM_ALIASES = {
                # NBA
                'NYK': 'NY', 'NOP': 'NO', 'SAS': 'SA', 'GSW': 'GS', 'UTAH': 'UTA',
                # NHL (ESPN vs NHL API)
                'NJD': 'NJ', 'NJ': 'NJD',
                'SJS': 'SJ', 'SJ': 'SJS',
                'LAK': 'LA', 'LA': 'LAK',
                'TBL': 'TB', 'TB': 'TBL',
            }
            def _canonical(t):
                t = t.upper()
                return _TEAM_ALIASES.get(t, t)
            pp_team = _canonical(pp.get('team', ''))
            pred_team = _canonical(pred.get('team', ''))
            if pp_team and pred_team and pp_team != pred_team:
                # Player was traded — PP is authoritative, log and continue.
                # Probability is still valid (based on player stats, not team).
                # PP team is used at SmartPick creation below (pp.get('team')).
                trade_key = (pp['player_name'], pred_team, pp_team)
                if trade_key not in _logged_trades:
                    safe_name = pp['player_name'].encode('ascii', 'replace').decode('ascii')
                    print(f"[INFO] Trade detected: {safe_name} local={pred_team} -> PP={pp_team}")
                    _logged_trades.add(trade_key)

            # Get season average for baseline comparison
            season_avg = pred.get('f_season_avg') or pred.get('season_avg') or 0
            season_std = pred.get('f_season_std') or pred.get('season_std') or 1.0
            recent_avg = 0
            recent_std = 1.0

            # Recalculate probability based on sport and prop type
            std_dev = 1.0  # default; overridden per branch below
            if self.sport == 'NHL' and prop_type in ['points', 'goals', 'assists', 'pp_points']:
                # NHL: Points-based props use Poisson distribution
                lambda_param = pred.get('lambda_param')
                if lambda_param is None or lambda_param <= 0:
                    continue
                pp_prob_over = self.poisson_prob_over(lambda_param, pp['line'])
                our_param = lambda_param
                recent_avg = lambda_param
                std_dev = math.sqrt(lambda_param)  # σ for Poisson = sqrt(λ)
                # Baseline: use season average lambda if available
                baseline_prob_over = self.poisson_prob_over(season_avg, pp['line']) if season_avg > 0 else pp_prob_over
            elif self.sport == 'NHL' and prop_type in ['hits', 'blocked_shots']:
                # NHL: hits/blocked_shots use Normal distribution (same as shots)
                # Try legacy keys first, then canonical f_l10_avg (written by statistical_predictions_v2)
                mean_val = (pred.get('mean_hits') or pred.get('mean_blocked')
                            or pred.get('mean_shots') or pred.get('sog_l10'))
                std_dev = pred.get('std_dev') or 1.5
                if mean_val is None or mean_val <= 0:
                    continue
                pp_prob_over = self.normal_prob_over(mean_val, std_dev, pp['line'])
                our_param = mean_val
                recent_avg = mean_val
                baseline_prob_over = self.normal_prob_over(season_avg, season_std, pp['line']) if season_avg > 0 else pp_prob_over
            elif self.sport == 'NHL':
                # NHL: Shots and other continuous props use Normal distribution
                mean_shots = pred.get('mean_shots') or pred.get('sog_l10')
                std_dev = pred.get('std_dev') or pred.get('sog_std_l10') or 1.5
                if mean_shots is None or mean_shots <= 0:
                    continue
                pp_prob_over = self.normal_prob_over(mean_shots, std_dev, pp['line'])
                our_param = mean_shots
                recent_avg = mean_shots
                # Baseline: use season average
                baseline_prob_over = self.normal_prob_over(season_avg, season_std, pp['line']) if season_avg > 0 else pp_prob_over
            elif self.sport == 'MLB':
                # MLB: probability is pre-computed per specific line in the prediction DB.
                # Use the stored probability from the closest-line prediction (selected above).
                stored_prob = pred.get('probability')
                stored_dir = pred.get('prediction')  # 'OVER' or 'UNDER'
                if stored_prob is None or stored_prob <= 0:
                    continue
                # Convert stored directional probability to P(OVER)
                pp_prob_over = stored_prob if stored_dir == 'OVER' else 1.0 - stored_prob
                our_param = stored_prob
                recent_avg = 0
                baseline_prob_over = pp_prob_over  # no separate baseline for MLB
            elif self.sport == 'GOLF':
                # Golf: round_score uses Normal distribution on scoring average
                mean = pred.get('golf_mean')
                std_dev = pred.get('golf_std') or 3.5
                recent_avg = mean or 0
                recent_std = std_dev
                if mean is None or mean <= 0:
                    continue
                pp_prob_over = self.normal_prob_over(mean, std_dev, pp['line'])
                our_param = mean
                baseline_prob_over = self.normal_prob_over(season_avg, season_std, pp['line']) if season_avg > 0 else pp_prob_over
            else:
                # NBA: All props use Normal distribution
                mean = pred.get('mean') or pred.get('f_l10_avg')
                std_dev = pred.get('std_dev') or pred.get('f_l10_std') or 1.0
                recent_avg = mean or 0
                recent_std = std_dev
                if mean is None or mean <= 0:
                    continue
                pp_prob_over = self.normal_prob_over(mean, std_dev, pp['line'])
                our_param = mean
                # Baseline: use season average with season std
                if season_avg > 0:
                    baseline_prob_over = self.normal_prob_over(season_avg, season_std, pp['line'])
                else:
                    baseline_prob_over = pp_prob_over

            # Compute σ-distance for goblin/demon variants and apply quality gates
            sigma_distance = 0.0
            if pp['odds_type'] != 'standard' and std_dev > 0:
                std_line = standard_lines_by_player.get((_strip_diacritics(pp['player_name']).lower(), prop_type))
                if std_line:
                    sigma_distance = (pp['line'] - std_line) / std_dev
                    # Quality gates: skip junk variants (requires standard line for σ-reference)
                    if pp['odds_type'] == 'goblin' and sigma_distance >= -0.3:
                        continue  # Nearly same as standard but with 84%+ break-even — skip
                    if pp['odds_type'] == 'demon' and sigma_distance >= 1.5:
                        continue  # Too far above standard to be achievable — skip
                else:
                    # No standard line exists for this player/prop — can't compute σ-distance.
                    # For goblin: allow with σ=0; compute_break_even() falls back to static
                    # BE=0.7619, so the pick must still clear a 76% OVER threshold.
                    # For demon: skip — without a σ-reference we can't verify the line isn't
                    # unreachably far above standard (σ>=1.5 gate can't fire).
                    if pp['odds_type'] == 'demon':
                        continue

            matched += 1

            pp_prob_under = 1 - pp_prob_over
            baseline_prob_under = 1 - baseline_prob_over

            # PP platform rule: goblin and demon lines ONLY offer OVER bets.
            # UNDER is not available for non-standard lines on PrizePicks.
            if pp['odds_type'] in ('goblin', 'demon'):
                prediction = 'OVER'
                probability = pp_prob_over
                baseline_prob = baseline_prob_over
            elif pp_prob_over >= pp_prob_under:
                prediction = 'OVER'
                probability = pp_prob_over
                baseline_prob = baseline_prob_over
            else:
                prediction = 'UNDER'
                probability = pp_prob_under
                baseline_prob = baseline_prob_under

            # Apply calibration correction (50%-damped; 0.0 if insufficient history)
            bucket = round(round(probability / 0.05) * 0.05, 2)
            calib_correction = calibration.get((prop_type, bucket), 0.0)
            probability = max(0.45, min(0.95, probability + calib_correction))

            # Calculate ML adjustment (how much better/worse than naive baseline)
            ml_adjustment = (probability - baseline_prob) * 100

            # Skip if overs_only and this is an UNDER
            if overs_only and prediction != 'OVER':
                continue

            # Suppress threes OVER — 0% hit rate in grading (model is degenerate for this combo).
            # The threes model learned to predict UNDER 100% of the time; OVER predictions are
            # always wrong because PP sets three-pointer lines high enough that UNDER always wins.
            if prop_type == 'threes' and prediction == 'OVER':
                continue

            # Suppress degenerate OVER props confirmed by backtesting (2026-04-05 RCA audit):
            #   steals OVER:       97.2% actual OVER rate — PP line far too low, not a real edge
            #   blocked_shots OVER: 94.5% actual OVER rate — same line-mismatch artifact
            #   fantasy OVER:      25.1% hit rate — catastrophically miscalibrated, model/line broken
            #   turnovers OVER:    47.5% hit rate — below standard break-even (52.4%)
            # These are not model signals; they reflect broken PP line-setting or degenerate models.
            # Re-evaluate at start of next season when lines reset.
            if prediction == 'OVER' and prop_type in ('steals', 'blocked_shots', 'fantasy', 'turnovers'):
                continue

            # Suppress demon OVER — 29.41% actual hit rate vs 45.45% break-even (Apr 2026 audit).
            # Statistical model overestimates probability for lines 1-1.5σ above standard;
            # the Normal distribution doesn't account for the fat left-tail of rare big games.
            # Guard is permanent until next full retrain with demon-specific calibration.
            if pp['odds_type'] == 'demon' and prediction == 'OVER':
                continue

            # Suppress confirmed-losing UNDER props (Apr 2026 audit, 54K+ graded NBA rows):
            #   NBA steals UNDER:       11.7% hit rate vs 52.38% BE → -40.7% edge
            #   NBA blocked_shots UNDER: 18.9% hit rate vs 52.38% BE → -33.5% edge
            # PP sets lines so low that UNDER almost never wins — model cannot overcome this.
            # Predictions still generated/stored; re-evaluate at Oct 2026 retrain.
            if self.sport == 'NBA' and prediction == 'UNDER' and prop_type in ('steals', 'blocked_shots'):
                continue

            # Suppress NHL points UNDER — 20.2% hit rate vs 52.38% BE → -32.2% edge (10K+ rows).
            # PP sets points lines near 0.5 making UNDER near-impossible. Re-evaluate Oct 2026.
            if self.sport == 'NHL' and prediction == 'UNDER' and prop_type == 'points':
                continue

            # Suppress NHL shots UNDER — 44.3% hit rate vs 52.38% BE → -8.1% edge (10K+ rows).
            # Re-evaluate Oct 2026.
            if self.sport == 'NHL' and prediction == 'UNDER' and prop_type == 'shots':
                continue

            # Suppress NBA turnovers UNDER — 46.8% hit rate vs 52.38% BE → -5.6% edge (54K+ rows).
            # Re-evaluate Oct 2026.
            if self.sport == 'NBA' and prediction == 'UNDER' and prop_type == 'turnovers':
                continue

            # Suppress MLB pitcher_walks UNDER — 43.3% hit rate vs 52.38% BE → -9.1% edge.
            # Re-evaluate at ~50K graded MLB rows (~Aug 2026).
            if self.sport == 'MLB' and prediction == 'UNDER' and prop_type == 'pitcher_walks':
                continue

            # Suppress MLB outs_recorded UNDER — 38.3% hit rate vs 52.38% BE → -14.1% edge.
            # Suppress MLB earned_runs UNDER — 30.4% hit rate vs 52.38% BE → -22.0% edge.
            # Re-evaluate at ~50K graded MLB rows (~Aug 2026).
            if self.sport == 'MLB' and prediction == 'UNDER' and prop_type in ('outs_recorded', 'earned_runs'):
                continue

            # Suppress MLB hrr OVER — 36-43% hit rate across all odds types vs 45.45% demon BE (388 samples).
            # Re-evaluate at ~50K graded MLB rows (~Aug 2026).
            if self.sport == 'MLB' and prediction == 'OVER' and prop_type == 'hrr':
                continue

            # Dynamic break-even derived from σ-distance and PAYOUTS table
            break_even = self.compute_break_even(pp['odds_type'], sigma_distance)
            edge = (probability - break_even) * 100

            # Filter by minimum edge only — edge already encodes break-even per odds_type.
            # Raw probability threshold is NOT used here because it would incorrectly
            # reject profitable demon picks (e.g. demon 52% is +7% edge = valid play).
            if edge < min_edge:
                continue

            # Line movement signal
            move_info = movements.get((pp['player_name'].lower(), prop_type), {})
            line_movement = move_info.get('line_movement', 0.0)
            move_dir = move_info.get('direction', 'none')
            movement_agrees = (
                (prediction == 'OVER' and move_dir == 'up') or
                (prediction == 'UNDER' and move_dir == 'down') or
                move_dir == 'none'
            )

            # Rest / fatigue signal — extracted from features_json for both NBA and NHL
            days_rest = 3
            try:
                fj = json.loads(pred.get('features_json') or '{}')
                days_rest = int(fj.get('f_days_rest', 3))
            except Exception:
                pass

            # Situational intelligence -- advisory only, never touches DB
            situation_flag = 'NORMAL'
            situation_modifier = 0.0
            situation_notes = ''
            try:
                if self._intel:
                    pick_team = pp.get('team', '') or pred.get('team', '')
                    s_flag, s_mod = self._intel.get_situation_flag(
                        pp['player_name'], pick_team, self.sport.lower(), self.game_date
                    )
                    situation_flag     = s_flag
                    situation_modifier = s_mod
                    situation_notes    = self._intel.get_situation_notes(
                        pp['player_name'], pick_team, self.sport.lower(), self.game_date
                    )
            except Exception:
                pass  # Never block pick generation

            # Create SmartPick - PP team is authoritative (handles recent trades)
            pick = SmartPick(
                player_name=pp['player_name'],
                local_player_name=pred['player_name'],
                team=pp.get('team', '') or pred.get('team', ''),
                opponent=pred.get('opponent', ''),
                prop_type=pp['prop_type'],
                our_line=pred['line'],
                our_probability=pred['probability'],
                our_lambda=our_param,
                pp_line=pp['line'],
                pp_odds_type=pp['odds_type'],
                pp_probability=probability,
                prediction=prediction,
                edge=edge,
                season_avg=season_avg,
                recent_avg=recent_avg,
                baseline_prob=baseline_prob,
                ml_adjustment=ml_adjustment,
                sigma=std_dev,
                sigma_distance=sigma_distance,
                line_movement=line_movement,
                movement_agrees=movement_agrees,
                calibration_correction=calib_correction,
                days_rest=days_rest,
                situation_flag=situation_flag,
                situation_modifier=situation_modifier,
                situation_notes=situation_notes,
            )

            smart_picks.append(pick)

        total_pp = len(pp_lines)
        unmatched = total_pp - matched
        unmatched_rate = unmatched / total_pp if total_pp > 0 else 0
        print(f"[{self.sport}] Matched {matched}/{total_pp} PP lines to predictions "
              f"({unmatched} unmatched, {unmatched_rate:.0%})")
        if total_pp > 10 and unmatched_rate > 0.20:
            msg = (f"[{self.sport}] High unmatched PP line rate: {unmatched}/{total_pp} "
                   f"({unmatched_rate:.0%}). Name matching or prediction coverage may be degraded.")
            print(f"[WARN] {msg}")
            if DISCORD_WEBHOOK_URL:
                try:
                    requests.post(DISCORD_WEBHOOK_URL,
                                  json={"content": f":warning: **{self.sport} UNMATCHED LINES: {unmatched_rate:.0%}**\n{msg}"},
                                  timeout=5)
                except Exception:
                    pass
        print(f"[{self.sport}] Found {len(smart_picks)} picks with edge >= {min_edge}%")

        # Dedup: for each (player, prop, odds_type), keep only the highest-edge variant.
        # This prevents multiple goblin or demon lines for the same player/prop from
        # cluttering the picks — only the sweet-spot variant (best edge) survives.
        best_by_key: Dict[tuple, SmartPick] = {}
        for pick in smart_picks:
            key = (pick.player_name.lower(), pick.prop_type, pick.pp_odds_type)
            if key not in best_by_key or pick.edge > best_by_key[key].edge:
                best_by_key[key] = pick
        smart_picks = list(best_by_key.values())

        # Sort by edge descending
        smart_picks.sort(key=lambda x: x.edge, reverse=True)

        return smart_picks

    def _get_pp_lines(self, game_date: str, odds_types: List[str]) -> List[Dict]:
        """Get PrizePicks lines for a date"""
        conn = sqlite3.connect(self.pp_db_path)
        conn.row_factory = sqlite3.Row

        placeholders = ','.join(['?' for _ in odds_types])

        # Sport-specific prop types
        if self.sport == 'NHL':
            props = ('shots', 'points', 'goals', 'assists', 'pp_points', 'hits', 'blocked_shots')
        elif self.sport == 'MLB':
            props = ('strikeouts', 'outs_recorded', 'pitcher_walks', 'hits_allowed', 'earned_runs',
                     'hits', 'total_bases', 'home_runs', 'rbis', 'runs',
                     'stolen_bases', 'walks', 'batter_strikeouts', 'hrr')
        elif self.sport == 'GOLF':
            # PrizePicks stores golf round score as 'strokes'; make_cut not on PP
            props = ('strokes',)
        else:
            # NBA
            props = ('points', 'rebounds', 'assists', 'threes', 'pra',
                     'pts_rebs', 'pts_asts', 'rebs_asts', 'steals',
                     'blocked_shots', 'turnovers', 'blks+stls', 'fantasy')

        prop_placeholders = ','.join(['?' for _ in props])

        # Match by game date (from start_time) rather than fetch_date.
        # Always take the LATEST ingested row per (player, prop, odds_type) using MAX(id).
        # PP changes lines mid-day by creating a new projection_id, which would leave both
        # old and new rows in the DB if we used SELECT DISTINCT. Taking MAX(id) ensures we
        # always serve the current line, never stale ones.
        query = f'''
            SELECT p.player_name, p.prop_type, p.line, p.odds_type, p.team
            FROM prizepicks_lines p
            INNER JOIN (
                SELECT player_name, prop_type, odds_type, MAX(id) AS max_id
                FROM prizepicks_lines
                WHERE substr(start_time, 1, 10) = ?
                  AND league = ?
                  AND odds_type IN ({placeholders})
                  AND prop_type IN ({prop_placeholders})
                GROUP BY player_name, prop_type, odds_type
            ) latest ON p.id = latest.max_id
        '''

        # PrizePicks stores golf lines under league='PGA' (not 'GOLF')
        league_name = 'PGA' if self.sport == 'GOLF' else self.sport
        params = [game_date, league_name] + odds_types + list(props)
        rows = conn.execute(query, params).fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def _get_predictions_with_params(self, game_date: str) -> List[Dict]:
        """Get our predictions with statistical parameters extracted from features"""
        conn = sqlite3.connect(self.pred_db_path)
        conn.row_factory = sqlite3.Row

        # Different query based on sport (NHL/MLB use features_json; NBA uses f_* columns)
        if self.sport == 'GOLF':
            # Golf predictions have no team/opponent columns
            rows = conn.execute('''
                SELECT player_name, '' AS team, '' AS opponent, prop_type, line,
                       prediction, probability, features_json
                FROM predictions
                WHERE game_date = ?
            ''', (game_date,)).fetchall()
        elif self.sport in ('NHL', 'MLB'):
            rows = conn.execute('''
                SELECT player_name, team, opponent, prop_type, line,
                       prediction, probability, features_json
                FROM predictions
                WHERE game_date = ?
            ''', (game_date,)).fetchall()
        else:
            # NBA has f_l10_avg, f_l10_std as columns
            rows = conn.execute('''
                SELECT player_name, team, opponent, prop_type, line,
                       prediction, probability, features_json,
                       f_l10_avg, f_l10_std, f_season_avg, f_season_std
                FROM predictions
                WHERE game_date = ?
            ''', (game_date,)).fetchall()

        predictions = []
        for row in rows:
            pred = dict(row)

            if self.sport == 'GOLF':
                # Golf: Extract scoring avg/std from features_json
                try:
                    features = json.loads(row['features_json'])
                    pred['golf_mean'] = (features.get('f_scoring_avg_l10_rounds')
                                         or features.get('f_scoring_avg_l5_rounds'))
                    pred['golf_std'] = features.get('f_scoring_std_l10_rounds') or 3.5
                    pred['f_season_avg'] = features.get('f_scoring_avg_l10_rounds') or 0
                    pred['f_season_std'] = features.get('f_scoring_std_l10_rounds') or 3.5
                except:
                    pred['golf_mean'] = None
                    pred['golf_std'] = 3.5
                    pred['f_season_avg'] = 0
                    pred['f_season_std'] = 3.5
            elif self.sport in ('NHL', 'MLB'):
                # NHL/MLB: Extract parameters from features_json
                try:
                    features = json.loads(row['features_json'])
                    # For points (Poisson) — try legacy key then canonical
                    pred['lambda_param'] = features.get('lambda_param') or features.get('f_lambda_param')
                    # For shots / hits / blocked_shots (Normal) — try legacy then canonical
                    pred['mean_shots'] = (features.get('mean_shots') or features.get('sog_l10')
                                          or features.get('f_l10_avg'))
                    pred['std_dev'] = (features.get('std_dev') or features.get('sog_std_l10')
                                       or features.get('f_std_dev'))
                    pred['sog_l10'] = features.get('sog_l10') or features.get('f_l10_avg')
                    pred['sog_std_l10'] = features.get('sog_std_l10') or features.get('f_std_dev')
                    # Season averages for baseline comparison
                    pred['f_season_avg'] = (features.get('season_avg') or features.get('pts_l20')
                                            or features.get('sog_season') or features.get('f_season_avg'))
                    pred['f_season_std'] = (features.get('season_std') or features.get('sog_std_season')
                                            or features.get('f_season_std') or 1.0)
                except:
                    pred['lambda_param'] = None
                    pred['mean_shots'] = None
                    pred['std_dev'] = None
                    pred['f_season_avg'] = None
                    pred['f_season_std'] = 1.0
            else:
                # NBA: Use columns directly (all props use Normal distribution)
                pred['mean'] = row['f_l10_avg'] or row['f_season_avg']
                pred['std_dev'] = row['f_l10_std'] or row['f_season_std'] or 1.0
                pred['f_season_avg'] = row['f_season_avg']
                pred['f_season_std'] = row['f_season_std'] or 1.0
                pred['lambda_param'] = None  # NBA doesn't use Poisson

                # Also try features_json as backup
                try:
                    features = json.loads(row['features_json']) if row['features_json'] else {}
                    if not pred['mean']:
                        pred['mean'] = features.get('f_l10_avg') or features.get('f_season_avg')
                    if not pred['std_dev'] or pred['std_dev'] == 1.0:
                        pred['std_dev'] = features.get('f_l10_std') or features.get('f_season_std') or 1.0
                    if not pred['f_season_avg']:
                        pred['f_season_avg'] = features.get('f_season_avg')
                    if not pred['f_season_std'] or pred['f_season_std'] == 1.0:
                        pred['f_season_std'] = features.get('f_season_std') or 1.0
                except:
                    pass

            predictions.append(pred)

        conn.close()
        return predictions

    def generate_report(
        self,
        picks: List[SmartPick],
        show_ev: bool = True
    ) -> str:
        """Generate a formatted report of smart picks"""
        lines = []
        lines.append("=" * 130)
        lines.append(f"  {self.sport} SMART PICKS - {date.today().isoformat()}")
        lines.append("  Only showing plays ACTUALLY AVAILABLE on PrizePicks")
        lines.append("=" * 130)
        lines.append(f"  Total Smart Picks: {len(picks)}")
        lines.append("")
        lines.append("  COLUMNS: Prob=Model probability | Edge=vs breakeven | ML Adj=vs season avg (^=hot, v=cold) | Avg=Season->Recent")
        lines.append("")

        # Group by prop type
        by_prop = defaultdict(list)
        for pick in picks:
            by_prop[pick.prop_type].append(pick)

        for prop_type, prop_picks in sorted(by_prop.items()):
            lines.append(f"  {prop_type.upper()} ({len(prop_picks)} plays)")
            lines.append("-" * 130)

            header = f"  {'Player':<18} {'Matchup':<12} {'Line':^16} {'Prob':>6} {'Edge':>7} {'ML Adj':>8} {'Avg':>12} {'Tier':<10}"
            lines.append(header)

            for pick in prop_picks[:10]:  # Top 10 per prop
                line_str = f"{pick.prediction} {pick.pp_line:.1f}"
                if pick.pp_odds_type != 'standard':
                    line_str += f" ({pick.pp_odds_type[:3]})"

                # Format matchup as "TEAM vs OPP"
                matchup = f"{pick.team} vs {pick.opponent}" if pick.team and pick.opponent else ""
                matchup = matchup[:12]  # Truncate if too long

                # ML adjustment with direction indicator
                if pick.ml_adjustment > 0.5:
                    ml_adj_str = f"+{pick.ml_adjustment:4.1f}% ^"  # Hot - recent form better than season
                elif pick.ml_adjustment < -0.5:
                    ml_adj_str = f"{pick.ml_adjustment:5.1f}% v"  # Cold - recent form worse than season
                else:
                    ml_adj_str = f"{pick.ml_adjustment:5.1f}%  "  # Neutral

                # Show season vs recent average
                avg_str = f"{pick.season_avg:4.1f}->{pick.recent_avg:4.1f}" if pick.season_avg > 0 else ""

                row = f"  {pick.player_name:<18} {matchup:<12} {line_str:^16} {pick.pp_probability*100:5.1f}% {pick.edge:+6.1f}% {ml_adj_str:>8} {avg_str:>12} {pick.tier:<10}"
                lines.append(row)

            lines.append("")

        # ML adjustment explanation
        lines.append("=" * 130)
        lines.append("  ML ADJUSTMENT EXPLAINED")
        lines.append("-" * 130)
        lines.append("  ML Adj shows how much BETTER (^) or WORSE (v) our model is vs a naive season-average approach:")
        lines.append("    +10% ^ = Player's recent form is HOT - L10 avg much higher than season avg, model sees 10% more edge")
        lines.append("    -5% v  = Player's recent form is COLD - L10 avg lower than season avg, model is more conservative")
        lines.append("    0%     = Recent form matches season average - no adjustment needed")
        lines.append("")
        lines.append("  WHY THIS MATTERS: A casual bettor using season averages would miss these edges.")
        lines.append("  Our model captures recent form, trends, and momentum that season averages ignore.")
        lines.append("")

        # Parlay building tips
        lines.append("=" * 130)
        lines.append("  PRIZEPICKS PAYOUT GUIDE")
        lines.append("-" * 130)
        lines.append("  Total Leg Value  Payout  Required Win Rate")
        lines.append("  2.0 legs         3x      58.5% per pick")
        lines.append("  3.0 legs         5x      58.5% per pick")
        lines.append("  4.0 legs         10x     56.2% per pick")
        lines.append("  5.0 legs         20x     54.9% per pick")
        lines.append("  6.0 legs         25x     55.1% per pick")
        lines.append("")
        lines.append("  LEG VALUES: Goblin=0.5x (easier) | Standard=1.0x | Demon=1.5x (harder)")
        lines.append("=" * 130)

        return "\n".join(lines)

    def generate_discord_message(self, picks: List[SmartPick], game_date: str) -> str:
        """Generate a Discord-formatted message with picks"""
        lines = []

        # Header (Windows-safe, no emojis in code - Discord will render them)
        sport_label = {"NBA": "[NBA]", "NHL": "[NHL]", "MLB": "[MLB]"}.get(self.sport, f"[{self.sport}]")
        lines.append(f"```")
        lines.append(f"{sport_label} SMART PICKS - {game_date}")
        lines.append(f"{'='*50}")

        if not picks:
            lines.append("No high-edge picks found for this date.")
            lines.append("```")
            return "\n".join(lines)

        lines.append(f"Found {len(picks)} verified picks (edge >= 5%)")
        lines.append("")

        # Group by tier for easier reading
        elite_picks = [p for p in picks if p.tier == 'T1-ELITE']
        strong_picks = [p for p in picks if p.tier == 'T2-STRONG']
        good_picks = [p for p in picks if p.tier == 'T3-GOOD']

        if elite_picks:
            lines.append("[FIRE] ELITE TIER (+19% edge above break-even)")
            lines.append("-" * 50)
            for p in elite_picks[:8]:
                trend = "[HOT]" if p.ml_adjustment > 5 else ("[COLD]" if p.ml_adjustment < -5 else "[--]")
                lines.append(f"{trend} {p.player_name}")
                lines.append(f"   {p.prediction} {p.pp_line} {p.prop_type} ({p.pp_odds_type})")
                lines.append(f"   {p.team} vs {p.opponent} | {p.pp_probability*100:.0f}% | +{p.edge:.0f}% edge")
                lines.append("")

        if strong_picks:
            lines.append("[STRONG] STRONG TIER (+14-18% edge)")
            lines.append("-" * 50)
            for p in strong_picks[:6]:
                trend = "[HOT]" if p.ml_adjustment > 5 else ("[COLD]" if p.ml_adjustment < -5 else "[--]")
                lines.append(f"{trend} {p.player_name}")
                lines.append(f"   {p.prediction} {p.pp_line} {p.prop_type} ({p.pp_odds_type})")
                lines.append(f"   {p.team} vs {p.opponent} | {p.pp_probability*100:.0f}% | +{p.edge:.0f}% edge")
                lines.append("")

        if good_picks:
            lines.append("[GOOD] GOOD TIER (+9-13% edge)")
            lines.append("-" * 50)
            for p in good_picks[:4]:
                lines.append(f"* {p.player_name}: {p.prediction} {p.pp_line} {p.prop_type} ({p.pp_odds_type}) | {p.pp_probability*100:.0f}% | +{p.edge:.0f}% edge")

        lines.append("")
        lines.append("=" * 50)
        lines.append("[HOT] = Recent form > season avg")
        lines.append("[COLD] = Recent form < season avg")
        lines.append("```")

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Smart Pick Selector - Only actual PP lines')
    parser.add_argument('--sport', choices=['nhl', 'nba'], default='nhl', help='Sport')
    parser.add_argument('--date', help='Game date (YYYY-MM-DD), defaults to today')
    parser.add_argument('--min-edge', type=float, default=5.0, help='Minimum edge %%')
    parser.add_argument('--min-prob', type=float, default=0.55, help='Minimum probability')
    parser.add_argument('--include-demon', action='store_true', help='Include demon odds')
    parser.add_argument('--no-refresh', action='store_true', help='Skip fetching fresh lines')
    parser.add_argument('--overs-only', action='store_true', help='Only show OVER predictions')
    parser.add_argument('--show-ev', action='store_true', help='Show EV calculations')
    parser.add_argument('--discord', action='store_true', help='Output Discord-formatted message')
    parser.add_argument('--post-discord', action='store_true', help='Post picks to Discord webhook')

    args = parser.parse_args()

    game_date = args.date or date.today().isoformat()

    selector = SmartPickSelector(args.sport)

    odds_types = ['standard', 'goblin']
    if args.include_demon:
        odds_types.append('demon')

    picks = selector.get_smart_picks(
        game_date=game_date,
        min_edge=args.min_edge,
        min_prob=args.min_prob,
        odds_types=odds_types,
        refresh_lines=not args.no_refresh,
        overs_only=args.overs_only
    )

    if args.post_discord:
        # Post to Discord webhook
        message = selector.generate_discord_message(picks, game_date)
        if DISCORD_WEBHOOK_URL:
            try:
                response = requests.post(
                    DISCORD_WEBHOOK_URL,
                    json={"content": message},
                    timeout=10
                )
                if response.status_code == 204:
                    print(f"[OK] Posted {len(picks)} picks to Discord!")
                else:
                    print(f"[WARN] Discord returned status {response.status_code}")
            except Exception as e:
                print(f"[ERROR] Failed to post to Discord: {e}")
        else:
            print("[WARN] No Discord webhook configured")
    elif args.discord:
        # Discord-formatted output (print only)
        print(selector.generate_discord_message(picks, game_date))
    else:
        report = selector.generate_report(picks, show_ev=args.show_ev)
        print(report)


if __name__ == '__main__':
    main()
