"""
MLB Statistical Prediction Engine
===================================

Generates OVER/UNDER predictions for all MLB prop types using appropriate
statistical distributions:

  Pitcher props:
    strikeouts    → Normal distribution (K output is approximately normal)
    outs_recorded → Normal distribution
    pitcher_walks → Poisson distribution (BB is count data, low rate)
    hits_allowed  → Poisson distribution
    earned_runs   → Poisson distribution

  Batter props:
    hits               → Poisson (count, high variance)
    total_bases        → Normal (wide range, approximately normal for frequent players)
    home_runs          → Poisson (very low rate, rare events)
    rbis               → Poisson (count data, depends on team context)
    runs               → Poisson (count data)
    stolen_bases       → Bernoulli for O0.5 (binary hit/miss)
    walks              → Bernoulli for O0.5 (binary hit/miss)
    batter_strikeouts  → Bernoulli for O0.5, Normal for O1.5+
    hrr                → Normal (sum of H+R+RBI, approximately normal)

Adjustment pipeline (applied multiplicatively to expected values):
  1. Player's recent form (L5/L10 weighted vs season)
  2. Platoon advantage/disadvantage
  3. Opposing pitcher quality (for batter props)
  4. Park factors (HR, hits, runs, Ks)
  5. Weather effects (wind direction/speed, temperature)
  6. Vegas game total signal (high total = favorable offense environment)
  7. Altitude adjustment (Coors Field etc.)

Output format mirrors NHL/NBA for seamless integration:
  {
    'player_name': str,
    'prop_type': str,
    'line': float,
    'prediction': 'OVER' or 'UNDER',
    'probability': float,   # 0.0 to 1.0
    'confidence_tier': str, # T1-ELITE through T5-FADE
    'expected_value': float, # μ of distribution
    'model_version': str,
    'features': dict,       # Full feature dict (stored as features_json)
  }
"""

import math
from typing import Dict, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import get_confidence_tier, PROBABILITY_CAP


MODEL_VERSION = 'statistical_mlb_v1.0'

# Expected innings pitched per start — used to scale per-9-inning rates
# to absolute counts. This represents a typical MLB starter's workload.
AVG_STARTER_IP = 5.2          # Modern MLB starters average ~5.2 IP per start

# Plate appearances per game by batting order position
# (9 innings, ~4 PA for leadoff, less for lower slots)
PA_BY_ORDER = {
    1: 4.2, 2: 4.1, 3: 4.0, 4: 3.9, 5: 3.8,
    6: 3.7, 7: 3.6, 8: 3.5, 9: 3.4,
    0: 3.8,  # Unknown position — league average
}

# League average context (used when Vegas data unavailable)
LEAGUE_AVG_TOTAL = 9.0  # League average game total O/U


class MLBStatisticalEngine:
    """
    Generates statistical OVER/UNDER predictions for MLB player props.

    Uses feature dicts from the four feature extractors as input.
    Applies distribution-appropriate probability calculations with
    MLB-specific adjustment factors.
    """

    def predict(self, player_name: str, prop_type: str, line: float,
                pitcher_features: Dict = None, batter_features: Dict = None,
                context_features: Dict = None, opponent_features: Dict = None) -> Optional[Dict]:
        """
        Generate a single OVER/UNDER prediction.

        Args:
            player_name: Full player name
            prop_type: e.g., 'strikeouts', 'hits', 'total_bases'
            line: PrizePicks line value (e.g., 4.5, 0.5, 1.5)
            pitcher_features: From PitcherFeatureExtractor.extract() (pitcher props)
            batter_features: From BatterFeatureExtractor.extract() (batter props)
            context_features: From GameContextExtractor.extract()
            opponent_features: From OpponentFeatureExtractor.extract_*()

        Returns:
            Prediction dict or None if insufficient data
        """
        ctx = context_features or {}
        opp = opponent_features or {}
        features_used = {}

        if pitcher_features:
            features_used.update(pitcher_features)
        if batter_features:
            features_used.update(batter_features)
        features_used.update(ctx)
        features_used.update(opp)

        # Dispatch to appropriate prediction method
        try:
            if prop_type == 'strikeouts':
                mu, sigma = self._pitcher_k_distribution(pitcher_features, ctx, opp)
                prob = self._normal_prob_over(line, mu, sigma)

            elif prop_type == 'outs_recorded':
                mu, sigma = self._pitcher_outs_distribution(pitcher_features, ctx, opp)
                prob = self._normal_prob_over(line, mu, sigma)

            elif prop_type == 'pitcher_walks':
                lam = self._pitcher_walks_lambda(pitcher_features, ctx, opp)
                prob = self._poisson_prob_over(line, lam)

            elif prop_type == 'hits_allowed':
                lam = self._pitcher_hits_lambda(pitcher_features, ctx, opp)
                prob = self._poisson_prob_over(line, lam)

            elif prop_type == 'earned_runs':
                lam = self._pitcher_er_lambda(pitcher_features, ctx, opp)
                prob = self._poisson_prob_over(line, lam)

            elif prop_type == 'hits':
                lam = self._batter_hits_lambda(batter_features, ctx, opp)
                prob = self._poisson_prob_over(line, lam)

            elif prop_type == 'total_bases':
                mu, sigma = self._batter_tb_distribution(batter_features, ctx, opp)
                prob = self._normal_prob_over(line, mu, sigma)

            elif prop_type == 'home_runs':
                lam = self._batter_hr_lambda(batter_features, ctx, opp)
                prob = self._poisson_prob_over(line, lam)

            elif prop_type == 'rbis':
                lam = self._batter_rbi_lambda(batter_features, ctx, opp)
                prob = self._poisson_prob_over(line, lam)

            elif prop_type == 'runs':
                lam = self._batter_runs_lambda(batter_features, ctx, opp)
                prob = self._poisson_prob_over(line, lam)

            elif prop_type == 'stolen_bases':
                p = self._batter_sb_probability(batter_features)
                prob = p if line <= 0.5 else self._poisson_prob_over(line, p)

            elif prop_type == 'walks':
                p = self._batter_walk_probability(batter_features, opp)
                prob = p

            elif prop_type == 'batter_strikeouts':
                if line <= 0.5:
                    prob = self._batter_k_probability(batter_features, opp)
                else:
                    mu, sigma = self._batter_k_distribution(batter_features, opp)
                    prob = self._normal_prob_over(line, mu, sigma)

            elif prop_type == 'hrr':
                mu, sigma = self._batter_hrr_distribution(batter_features, ctx, opp)
                prob = self._normal_prob_over(line, mu, sigma)

            else:
                return None

        except Exception as e:
            print(f"[StatEngine] Error predicting {prop_type} for {player_name}: {e}")
            return None

        # Clamp probability
        prob = max(PROBABILITY_CAP[0] + 0.001, min(PROBABILITY_CAP[1] - 0.001, prob))

        # Determine prediction direction and confidence tier
        if prob >= 0.5:
            prediction = 'OVER'
            confidence_prob = prob
        else:
            prediction = 'UNDER'
            confidence_prob = 1.0 - prob

        confidence_tier = get_confidence_tier(confidence_prob)

        # Expected value: estimate of mean (use prop-type average where available)
        expected_value = self._get_expected_value(
            prop_type, pitcher_features, batter_features, ctx, opp
        )

        return {
            'player_name': player_name,
            'prop_type': prop_type,
            'line': line,
            'prediction': prediction,
            'probability': round(confidence_prob, 4),
            'confidence_tier': confidence_tier,
            'expected_value': round(expected_value, 2) if expected_value else None,
            'model_version': MODEL_VERSION,
            'features': features_used,
        }

    # =========================================================================
    # Pitcher prop distributions
    # =========================================================================

    def _pitcher_k_distribution(self, pf: Dict, ctx: Dict, opp: Dict) -> Tuple[float, float]:
        """Strikeout distribution (Normal): μ and σ."""
        pf = pf or {}

        # Base expected K from season rate × expected innings
        k9 = pf.get('f_season_k9', 8.5)
        expected_ip = self._estimate_pitcher_ip(pf)
        mu_season = (k9 / 9.0) * expected_ip

        # Blend with recent form (L5 is 60% weight)
        l5_k = pf.get('f_l5_avg_k', mu_season)
        mu = 0.6 * l5_k + 0.4 * mu_season

        # Adjustments
        mu *= self._opp_k_adjustment(opp)        # Opponent K% vs league avg
        mu *= ctx.get('ctx_park_k_factor', 1.0)  # Park factor for Ks

        sigma = max(pf.get('f_std_k', 2.5), 1.5)

        return max(mu, 0.5), sigma

    def _pitcher_outs_distribution(self, pf: Dict, ctx: Dict, opp: Dict) -> Tuple[float, float]:
        """Outs recorded distribution (Normal)."""
        pf = pf or {}

        l5_outs = pf.get('f_l5_avg_outs', 15.0)
        l3_outs = pf.get('f_l3_avg_outs', l5_outs)
        mu = 0.5 * l3_outs + 0.5 * l5_outs

        # Team-scoring adjustment: high-scoring opponents = fewer outs (early exit)
        scoring = opp.get('opp_team_recent_scoring', 4.5)
        if scoring > 5.5:
            mu *= 0.93
        elif scoring < 3.5:
            mu *= 1.05

        # High game total → pitcher may be pulled earlier
        game_total = ctx.get('ctx_game_total', 9.0)
        if game_total > 11.0:
            mu *= 0.95

        sigma = max(pf.get('f_std_outs', 4.0), 2.0)

        return max(mu, 3.0), sigma

    def _pitcher_walks_lambda(self, pf: Dict, ctx: Dict, opp: Dict) -> float:
        """Walk Poisson λ."""
        pf = pf or {}

        bb9 = pf.get('f_season_bb9', 3.2)
        expected_ip = self._estimate_pitcher_ip(pf)
        lam_season = (bb9 / 9.0) * expected_ip

        # Opponent BB% adjustment
        opp_bb = opp.get('opp_team_bb_pct', 0.085)
        league_avg_bb = 0.085
        adj = opp_bb / league_avg_bb if league_avg_bb > 0 else 1.0
        lam = lam_season * adj

        return max(lam, 0.3)

    def _pitcher_hits_lambda(self, pf: Dict, ctx: Dict, opp: Dict) -> float:
        """Hits allowed Poisson λ."""
        pf = pf or {}

        h9 = pf.get('f_season_h9', 9.0)
        expected_ip = self._estimate_pitcher_ip(pf)
        lam = (h9 / 9.0) * expected_ip

        # Opponent OBP adjustment
        opp_obp = opp.get('opp_team_obp', 0.318)
        league_obp = 0.318
        lam *= opp_obp / league_obp if league_obp > 0 else 1.0

        # Park hits factor
        lam *= ctx.get('ctx_park_hits_factor', 1.0)

        return max(lam, 1.0)

    def _pitcher_er_lambda(self, pf: Dict, ctx: Dict, opp: Dict) -> float:
        """Earned runs Poisson λ."""
        pf = pf or {}

        er9 = pf.get('f_season_er9', 4.20)
        expected_ip = self._estimate_pitcher_ip(pf)
        lam = (er9 / 9.0) * expected_ip

        # Park runs factor
        lam *= ctx.get('ctx_park_runs_factor', 1.0)

        # Opponent OPS adjustment
        opp_ops = opp.get('opp_team_ops', 0.730)
        league_ops = 0.730
        lam *= opp_ops / league_ops if league_ops > 0 else 1.0

        # Weather: wind out increases ER
        wind_effect = ctx.get('wind_effect_hr', 0.0)
        lam *= (1.0 + wind_effect * 0.5)

        return max(lam, 0.2)

    # =========================================================================
    # Batter prop distributions
    # =========================================================================

    def _batter_hits_lambda(self, bf: Dict, ctx: Dict, opp: Dict) -> float:
        """Hits Poisson λ."""
        bf = bf or {}

        pa = PA_BY_ORDER.get(bf.get('f_batting_order', 0), 3.8)
        avg = bf.get('f_season_avg', 0.250)

        # Platoon adjustment
        plat = bf.get('f_platoon_advantage', 0.0)
        avg_adj = avg + plat * 0.3  # Max ~3% platoon adjustment

        # Opposing pitcher difficulty
        difficulty = opp.get('opp_pitcher_difficulty', 0.5)
        pitcher_adj = 1.0 - (difficulty - 0.5) * 0.2  # ±10% based on matchup

        lam = pa * avg_adj * pitcher_adj

        # Blend with recent form
        l5_avg = bf.get('f_l5_hits_avg', lam)
        lam = 0.55 * l5_avg + 0.45 * lam

        # Park factor
        lam *= ctx.get('ctx_park_hits_factor', 1.0)

        return max(lam, 0.2)

    def _batter_tb_distribution(self, bf: Dict, ctx: Dict, opp: Dict) -> Tuple[float, float]:
        """Total bases Normal distribution."""
        bf = bf or {}

        pa = PA_BY_ORDER.get(bf.get('f_batting_order', 0), 3.8)
        slg = bf.get('f_season_slg', 0.400)

        # Expected TB = PA × SLG (rough approximation)
        mu_season = pa * slg

        # Blend with recent form
        l10_tb = bf.get('f_l10_total_bases_avg', mu_season)
        l5_tb  = bf.get('f_l5_total_bases_avg', mu_season)
        mu = 0.4 * l5_tb + 0.35 * l10_tb + 0.25 * mu_season

        # Pitcher difficulty (elite pitcher → fewer TB)
        difficulty = opp.get('opp_pitcher_difficulty', 0.5)
        mu *= (1.0 - (difficulty - 0.5) * 0.25)

        # Park HR factor (TB is correlated with HR)
        hr_factor = ctx.get('ctx_park_hr_factor', 1.0)
        mu *= (1.0 + (hr_factor - 1.0) * 0.4)  # Partial effect on TB

        # Weather
        mu *= (1.0 + ctx.get('wind_effect_hr', 0.0) * 0.3)

        sigma = max(mu * 0.6, 0.5)  # TB variance is roughly 60% of mean

        return max(mu, 0.1), sigma

    def _batter_hr_lambda(self, bf: Dict, ctx: Dict, opp: Dict) -> float:
        """Home run Poisson λ."""
        bf = bf or {}

        iso = bf.get('f_season_iso', 0.162)
        pa = PA_BY_ORDER.get(bf.get('f_batting_order', 0), 3.8)

        # Crude HR rate: ISO captures extra base hitting; HR ≈ 0.3 × ISO at league avg
        hr_rate_per_pa = iso * 0.35
        lam = pa * hr_rate_per_pa

        # Park factor — most impactful adjustment for HRs
        lam *= ctx.get('ctx_park_hr_factor', 1.0)

        # Altitude boost (Coors)
        from game_context_extractor import GameContextExtractor
        venue = ''  # Would need venue passed in; use altitude from ctx instead
        altitude = ctx.get('ctx_altitude', 0)
        if altitude > 500:
            lam *= 1.0 + (altitude - 500) / 500 * 0.01

        # Wind
        lam *= (1.0 + ctx.get('wind_effect_hr', 0.0))

        # Pitcher's HR/9 difficulty
        opp_hr9 = opp.get('opp_pitcher_hr9', 1.25)
        league_hr9 = 1.25
        lam *= opp_hr9 / league_hr9 if league_hr9 > 0 else 1.0

        # Platoon: power hitters are more susceptible to platoon effects
        plat = bf.get('f_platoon_advantage', 0.0)
        lam *= (1.0 + plat * 0.5)

        return max(lam, 0.01)

    def _batter_rbi_lambda(self, bf: Dict, ctx: Dict, opp: Dict) -> float:
        """RBI Poisson λ — most team-context-dependent."""
        bf = bf or {}

        # RBI roughly correlates with batting order, OPS, and team scoring
        order = bf.get('f_batting_order', 5)
        ops = bf.get('f_season_slg', 0.400) + bf.get('f_season_obp', 0.320)

        # Higher in lineup (3-5 = cleanup spots) → more RBI opportunities
        order_multiplier = {1: 0.7, 2: 0.85, 3: 1.2, 4: 1.3, 5: 1.1,
                            6: 0.9, 7: 0.8, 8: 0.7, 9: 0.6, 0: 0.9}
        mult = order_multiplier.get(order, 0.9)

        # Base RBI rate ≈ 0.6 × OPS × order_mult (rough empirical estimate)
        lam = ops * 0.35 * mult

        # Team scoring environment
        team_runs = opp.get('opp_team_recent_scoring', 4.5)
        lam *= team_runs / 4.5

        # Recent form
        l5_rbi = bf.get('f_l5_rbis_avg', lam)
        lam = 0.5 * l5_rbi + 0.5 * lam

        return max(lam, 0.2)

    def _batter_runs_lambda(self, bf: Dict, ctx: Dict, opp: Dict) -> float:
        """Runs scored Poisson λ — batting order position is key."""
        bf = bf or {}

        order = bf.get('f_batting_order', 5)
        obp = bf.get('f_season_obp', 0.320)
        pa = PA_BY_ORDER.get(order, 3.8)

        # Leadoff hitters score more runs due to position + PA
        order_run_mult = {1: 1.4, 2: 1.2, 3: 1.1, 4: 1.0, 5: 0.9,
                          6: 0.85, 7: 0.8, 8: 0.75, 9: 0.7, 0: 0.9}
        mult = order_run_mult.get(order, 0.9)

        # Base: OBP × PA × team scoring efficiency
        lam = obp * pa * mult * 0.5  # ~50% of times on base leads to run

        # Team scoring environment
        game_total = ctx.get('ctx_game_total', 9.0)
        lam *= game_total / LEAGUE_AVG_TOTAL

        return max(lam, 0.2)

    def _batter_sb_probability(self, bf: Dict) -> float:
        """Stolen base Bernoulli probability (for O0.5)."""
        bf = bf or {}

        # Use recent form rate as primary signal
        l10_rate = bf.get('f_l10_stolen_bases_rate', None)
        l5_rate = bf.get('f_l5_stolen_bases_rate', None)

        if l10_rate is not None and l5_rate is not None:
            p = 0.55 * l5_rate + 0.45 * l10_rate
        elif l10_rate is not None:
            p = l10_rate
        else:
            # Very low base rate — most games end with 0 SBs per player
            p = 0.15

        return max(0.05, min(0.85, p))

    def _batter_walk_probability(self, bf: Dict, opp: Dict) -> float:
        """Walk Bernoulli probability (for O0.5)."""
        bf = bf or {}

        bb_pct = bf.get('f_season_bb_pct', 0.085)
        pa = PA_BY_ORDER.get(bf.get('f_batting_order', 0), 3.8)

        # P(at least 1 walk) = 1 - P(0 walks) = 1 - (1-bb_pct)^PA
        opp_bb9 = opp.get('opp_pitcher_bb9', 3.2)
        pitcher_bb_adj = opp_bb9 / 3.2 if opp_bb9 > 0 else 1.0

        effective_bb_pct = bb_pct * pitcher_bb_adj
        p_at_least_one = 1.0 - (1.0 - effective_bb_pct) ** pa

        return max(0.10, min(0.85, p_at_least_one))

    def _batter_k_probability(self, bf: Dict, opp: Dict) -> float:
        """Batter strikeout Bernoulli probability (for O0.5)."""
        bf = bf or {}

        k_pct = bf.get('f_season_k_pct', 0.230)
        pa = PA_BY_ORDER.get(bf.get('f_batting_order', 0), 3.8)

        # Pitcher adjustment: high-K pitcher increases batter K probability
        opp_k9 = opp.get('opp_pitcher_k9', 8.5)
        k_adj = opp_k9 / 8.5

        # Platoon: batters K more vs same-handed pitchers
        plat = bf.get('f_platoon_advantage', 0.0)
        if plat < 0:  # Unfavorable platoon = more Ks
            k_adj *= 1.1

        effective_k_pct = k_pct * k_adj
        p_at_least_one = 1.0 - (1.0 - effective_k_pct) ** pa

        return max(0.20, min(0.95, p_at_least_one))

    def _batter_k_distribution(self, bf: Dict, opp: Dict) -> Tuple[float, float]:
        """Batter strikeout Normal distribution (for O1.5+)."""
        bf = bf or {}

        k_pct = bf.get('f_season_k_pct', 0.230)
        pa = PA_BY_ORDER.get(bf.get('f_batting_order', 0), 3.8)
        opp_k9 = opp.get('opp_pitcher_k9', 8.5)
        k_adj = opp_k9 / 8.5

        mu = k_pct * k_adj * pa
        sigma = max(math.sqrt(mu * (1 - k_pct)), 0.5)  # Binomial variance

        return max(mu, 0.3), sigma

    def _batter_hrr_distribution(self, bf: Dict, ctx: Dict, opp: Dict) -> Tuple[float, float]:
        """HRR (hits + runs + RBIs) Normal distribution."""
        mu_h   = self._batter_hits_lambda(bf, ctx, opp)
        mu_r   = self._batter_runs_lambda(bf, ctx, opp)
        mu_rbi = self._batter_rbi_lambda(bf, ctx, opp)

        mu = mu_h + mu_r + mu_rbi

        # Recent form blend
        l5_hrr = bf.get('f_l5_hrr_avg', None) if bf else None
        if l5_hrr is not None:
            mu = 0.55 * l5_hrr + 0.45 * mu

        # Sigma: roughly 70% of mean (HRR has high variance from component correlation)
        sigma = max(mu * 0.70, 0.8)

        return max(mu, 0.3), sigma

    # =========================================================================
    # Utilities
    # =========================================================================

    def _estimate_pitcher_ip(self, pf: Dict) -> float:
        """Estimate expected innings pitched from pitcher efficiency features."""
        pf = pf or {}
        avg_outs = pf.get('f_l5_avg_outs', 15.0)
        return max(avg_outs / 3.0, 1.0)

    def _opp_k_adjustment(self, opp: Dict) -> float:
        """
        Adjust K expectation based on opposing team's strikeout rate.

        Teams that K more = better matchup for pitcher K props.
        Returns multiplicative factor.
        """
        opp_k_pct = opp.get('opp_team_k_pct', 0.230)
        league_k_pct = 0.230
        adj = opp_k_pct / league_k_pct if league_k_pct > 0 else 1.0
        # Cap adjustment at ±20%
        return max(0.80, min(1.20, adj))

    def _get_expected_value(self, prop_type: str, pf: Dict, bf: Dict,
                             ctx: Dict, opp: Dict) -> Optional[float]:
        """Return the model's point estimate for the prop stat."""
        pf = pf or {}
        bf = bf or {}
        ctx = ctx or {}
        opp = opp or {}

        try:
            if prop_type == 'strikeouts':
                mu, _ = self._pitcher_k_distribution(pf, ctx, opp)
                return mu
            elif prop_type == 'outs_recorded':
                mu, _ = self._pitcher_outs_distribution(pf, ctx, opp)
                return mu
            elif prop_type == 'pitcher_walks':
                return self._pitcher_walks_lambda(pf, ctx, opp)
            elif prop_type == 'hits':
                return self._batter_hits_lambda(bf, ctx, opp)
            elif prop_type == 'total_bases':
                mu, _ = self._batter_tb_distribution(bf, ctx, opp)
                return mu
            elif prop_type == 'home_runs':
                return self._batter_hr_lambda(bf, ctx, opp)
            elif prop_type == 'hrr':
                mu, _ = self._batter_hrr_distribution(bf, ctx, opp)
                return mu
        except Exception:
            pass

        return None

    # =========================================================================
    # Distribution probability functions
    # =========================================================================

    @staticmethod
    def _normal_prob_over(line: float, mu: float, sigma: float) -> float:
        """
        P(X > line) for Normal(μ, σ).

        Uses the complementary error function (erfc) for precision.
        """
        if sigma <= 0:
            return 1.0 if mu > line else 0.0

        z = (line - mu) / sigma
        # P(X > line) = 1 - Φ(z) = Φ(-z) = 0.5 * erfc(z / sqrt(2))
        prob = 0.5 * math.erfc(z / math.sqrt(2))
        return max(0.001, min(0.999, prob))

    @staticmethod
    def _poisson_prob_over(line: float, lam: float) -> float:
        """
        P(X > line) for Poisson(λ).

        For PrizePicks lines like 3.5, 4.5 (non-integer):
          P(X > 3.5) = P(X >= 4) = 1 - P(X <= 3)
        For integer lines, use strict greater-than.

        Uses cumulative Poisson calculation.
        """
        if lam <= 0:
            return 0.001

        # Threshold: smallest integer strictly above the line
        threshold = math.floor(line) + 1  # e.g., line=3.5 → threshold=4

        # P(X <= threshold - 1) = sum P(X=k) for k=0..threshold-1
        prob_under = 0.0
        log_lam = math.log(lam)
        log_k_fact = 0.0  # log(0!) = 0

        for k in range(threshold):
            log_prob = k * log_lam - lam - log_k_fact
            prob_under += math.exp(log_prob)
            if k > 0:
                log_k_fact += math.log(k + 1)
            else:
                log_k_fact = 0.0

        prob_over = max(0.001, min(0.999, 1.0 - prob_under))
        return prob_over
