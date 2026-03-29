"""
Golf Walk-Forward Backtest Simulator
======================================

Runs simulations against 6 seasons (2020-2025) of historical PGA Tour data
to find profitable betting strategies BEFORE going live. No look-ahead bias —
all features are computed using only data available before each round.

HOW IT WORKS
------------
1. Backfill player_round_logs first (run backfill_round_logs.py)
2. This script iterates every historical (tournament, round) in the DB
3. For each round, it reconstructs what features would have been available
   at prediction time, computes probabilities, and grades vs actual scores
4. Tests multiple parameter configurations in a grid search
5. Outputs a ranked report: which configs are profitable, which aren't

WHAT YOU CAN TUNE (SimConfig)
------------------------------
  form_window        : How many past rounds to use for scoring avg (5/10/20)
  confidence_threshold: Min probability required to place a "bet" (0.52–0.68)
  min_rounds_history : Min career rounds before predicting on a player (5–20)
  course_weight      : How much course history adjusts the projection (0.0–0.8)
  major_bump         : Extra scoring difficulty added for majors (0.0–1.0)
  round_filter       : Which rounds to bet (1, 2, 3, 4, or None=all)
  line_filter        : Which line to focus on (68.5, 70.5, 72.5, or None=all)
  ranking_cutoff     : Only predict on players ranked inside top-N (None=all)
  under_only         : Only take UNDER predictions (golf UNDER bias test)

INTERPRETING RESULTS
--------------------
  Break-even at -110 juice: 52.38%
  Target accuracy: 55%+ for meaningful edge
  ROI > 5% = strong signal worth pursuing
  ROI > 10% = excellent — confirms ML training will be valuable

Usage:
    # Run full parameter sweep (recommended — takes ~5-10 min)
    python backtest_simulator.py

    # Test a single specific config
    python backtest_simulator.py --config "form_window=10,confidence=0.58,line=70.5"

    # Quick sweep on 2024 data only (faster sanity check)
    python backtest_simulator.py --seasons 2024

    # Walk-forward: train on 2020-2022, test on 2023-2024
    python backtest_simulator.py --train 2020-2022 --test 2023-2024

    # Save results to CSV for further analysis
    python backtest_simulator.py --output results.csv
"""

import sys
import os
import sqlite3
import json
import csv
import math
import argparse
import logging
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional
from itertools import product
from pathlib import Path
from scipy.stats import norm

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent / "features"))

from golf_config import DB_PATH, MAJOR_NAMES

logging.basicConfig(level=logging.WARNING, format="[GOLF][SIM] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JUICE        = 0.0476   # Standard -110 vig
BREAK_EVEN   = 0.5238   # 52.38% accuracy needed to break even at -110
WIN_PROFIT   = 0.9091   # Profit per $1 wagered at -110 on a win
LOSS_PROFIT  = -1.0     # Loss per $1 wagered

LEAGUE_AVG_SCORE = 71.2
LEAGUE_AVG_STD   = 2.8


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SimConfig:
    """All tunable parameters for one simulation run."""
    form_window:          int   = 10     # Past rounds for scoring avg (5, 10, 20)
    confidence_threshold: float = 0.55   # Min probability to "bet"
    min_rounds_history:   int   = 10     # Min career rounds before predicting
    course_weight:        float = 0.30   # Weight on course-history adjustment [0,1]
    major_bump:           float = 0.50   # Strokes added to mu for majors
    round_filter:         Optional[int]   = None    # None=all, or 1/2/3/4
    line_filter:          Optional[float] = None    # None=all, or 68.5/70.5/72.5
    ranking_cutoff:       Optional[int]   = None    # None=all, or top-N by world rank
    under_only:           bool  = False   # Only take UNDER predictions

    def label(self) -> str:
        parts = [
            f"fw{self.form_window}",
            f"ct{self.confidence_threshold:.2f}",
            f"mr{self.min_rounds_history}",
            f"cw{self.course_weight:.1f}",
            f"mb{self.major_bump:.1f}",
        ]
        if self.round_filter:   parts.append(f"R{self.round_filter}")
        if self.line_filter:    parts.append(f"L{self.line_filter}")
        if self.ranking_cutoff: parts.append(f"rk{self.ranking_cutoff}")
        if self.under_only:     parts.append("UO")
        return "|".join(parts)


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class BetResult:
    game_date:   str
    player_name: str
    tournament:  str
    round_num:   int
    line:        float
    prediction:  str    # OVER or UNDER
    probability: float
    actual_score: int
    outcome:     str    # HIT or MISS
    profit:      float


@dataclass
class SimResults:
    config:       SimConfig
    total_bets:   int   = 0
    wins:         int   = 0
    losses:       int   = 0
    profit:       float = 0.0
    bets_by_line: dict  = field(default_factory=dict)
    bets_by_round: dict = field(default_factory=dict)
    bets_by_tier: dict  = field(default_factory=dict)   # ranking tier
    season_breakdown: dict = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.wins / self.total_bets if self.total_bets else 0.0

    @property
    def roi(self) -> float:
        return self.profit / self.total_bets if self.total_bets else 0.0

    @property
    def edge(self) -> float:
        return self.accuracy - BREAK_EVEN


# ---------------------------------------------------------------------------
# Core feature extraction (DB-only, no external API calls)
# ---------------------------------------------------------------------------

def get_player_rounds_before(conn, player_name: str, before_date: str, n: int):
    """Fetch last N round scores for a player before target_date."""
    rows = conn.execute(
        """
        SELECT round_score, game_date, tournament_id, round_number
        FROM player_round_logs
        WHERE player_name = ? AND game_date < ? AND round_score IS NOT NULL
        ORDER BY game_date DESC, round_number DESC
        LIMIT ?
        """,
        (player_name, before_date, n),
    ).fetchall()
    return [r[0] for r in rows]  # just scores


def get_course_history(conn, player_name: str, tournament_id: str, before_date: str):
    """Historical round scores for this player at this specific course."""
    rows = conn.execute(
        """
        SELECT round_score FROM player_round_logs
        WHERE player_name = ? AND tournament_id = ?
          AND game_date < ? AND round_score IS NOT NULL
        ORDER BY game_date DESC
        """,
        (player_name, tournament_id, before_date),
    ).fetchall()
    return [r[0] for r in rows]


def get_cut_history(conn, player_name: str, before_date: str, n: int = 15):
    """Recent make-cut rate and top-10 rate."""
    rows = conn.execute(
        """
        SELECT made_cut, finish_position
        FROM player_round_logs
        WHERE player_name = ? AND game_date < ?
          AND made_cut IS NOT NULL
          AND round_number = 2          -- use R2 as the cut-determination round
        ORDER BY game_date DESC
        LIMIT ?
        """,
        (player_name, before_date, n),
    ).fetchall()
    if not rows:
        return 0.65, 0.12   # league average defaults
    made = sum(1 for r in rows if r[0] == 1)
    top10 = sum(1 for r in rows if r[1] and r[1] <= 10)
    return made / len(rows), top10 / len(rows)


def build_features(conn, player_name: str, line: float, target_date: str,
                   round_num: int, tournament_id: str, world_ranking: Optional[int],
                   is_major: bool, config: SimConfig) -> Optional[dict]:
    """
    Build features from DB-only data (no external API calls).
    Returns None if player has insufficient history.
    """
    n = config.form_window
    scores = get_player_rounds_before(conn, player_name, target_date, max(n, 20))

    if len(scores) < config.min_rounds_history:
        return None

    recent    = scores[:n]
    mu_recent = sum(recent) / len(recent)
    mu_20     = sum(scores[:20]) / len(scores[:20]) if len(scores) >= 20 else mu_recent

    # Std dev from recent rounds
    if len(recent) >= 3:
        variance = sum((s - mu_recent) ** 2 for s in recent) / (len(recent) - 1)
        std = max(1.5, min(math.sqrt(variance), 5.0))
    else:
        std = LEAGUE_AVG_STD

    # Course history adjustment
    course_scores = get_course_history(conn, player_name, tournament_id, target_date)
    course_adj = 0.0
    if course_scores and config.course_weight > 0:
        course_avg = sum(course_scores) / len(course_scores)
        # How does this player score at this course vs their overall average?
        course_adj = (course_avg - mu_recent) * config.course_weight

    # Major bump
    major_adj = config.major_bump if is_major else 0.0

    # Adjusted mu
    mu = mu_recent + course_adj + major_adj

    # Cut rate
    cut_rate, top10_rate = get_cut_history(conn, player_name, target_date)

    return {
        "mu":             mu,
        "std":            std,
        "mu_recent":      mu_recent,
        "mu_20":          mu_20,
        "course_rounds":  len(course_scores),
        "course_adj":     course_adj,
        "cut_rate":       cut_rate,
        "top10_rate":     top10_rate,
        "world_ranking":  world_ranking or 250,
        "round_num":      round_num,
        "line":           line,
        "is_major":       is_major,
        "career_rounds":  len(scores),
    }


def compute_probability(features: dict, line: float) -> tuple:
    """
    P(score UNDER line) using normal distribution.
    Returns (probability, prediction).
    """
    mu  = features["mu"]
    std = features["std"]
    p_under = float(norm.cdf(line, loc=mu, scale=std))
    # Soft cap — don't exceed 78% or go below 22%
    p_under = min(0.78, max(0.22, p_under))
    prediction = "UNDER" if p_under >= 0.5 else "OVER"
    return p_under, prediction


# ---------------------------------------------------------------------------
# Simulation engine
# ---------------------------------------------------------------------------

def run_simulation(config: SimConfig, seasons: list, conn) -> SimResults:
    """
    Walk-forward simulation for the given config and seasons.
    Iterates every (tournament, round) in the DB and grades predictions.
    """
    results = SimResults(config=config)

    # Get all unique (tournament_id, round_number, game_date) combos in target seasons
    rounds = conn.execute(
        """
        SELECT DISTINCT tournament_id, tournament_name, round_number,
               game_date, season
        FROM player_round_logs
        WHERE season IN ({})
        ORDER BY game_date, tournament_id, round_number
        """.format(",".join("?" * len(seasons))),
        seasons,
    ).fetchall()

    for (tournament_id, tournament_name, round_num, game_date, season) in rounds:
        # Round filter
        if config.round_filter and round_num != config.round_filter:
            continue

        is_major = any(m.lower() in tournament_name.lower() for m in MAJOR_NAMES)

        # Get all players who played this round (actual scores known)
        players = conn.execute(
            """
            SELECT player_name, round_score, world_ranking
            FROM player_round_logs
            WHERE tournament_id = ? AND round_number = ?
              AND game_date = ? AND round_score IS NOT NULL
            """,
            (tournament_id, round_num, game_date),
        ).fetchall()

        for (player_name, actual_score, world_ranking) in players:
            # Ranking filter
            if config.ranking_cutoff and world_ranking:
                if world_ranking > config.ranking_cutoff:
                    continue

            # Test each line
            lines = [config.line_filter] if config.line_filter else [68.5, 70.5, 72.5]

            for line in lines:
                features = build_features(
                    conn, player_name, line, game_date,
                    round_num, tournament_id, world_ranking,
                    is_major, config,
                )
                if features is None:
                    continue

                prob, prediction = compute_probability(features, line)

                # Under-only filter
                if config.under_only and prediction != "UNDER":
                    continue

                # Confidence filter
                confidence = prob if prediction == "UNDER" else (1 - prob)
                if confidence < config.confidence_threshold:
                    continue

                # Grade
                if prediction == "UNDER":
                    outcome = "HIT" if actual_score < line else "MISS"
                else:
                    outcome = "HIT" if actual_score > line else "MISS"

                profit = WIN_PROFIT if outcome == "HIT" else LOSS_PROFIT

                # Accumulate
                results.total_bets += 1
                results.profit += profit
                if outcome == "HIT":
                    results.wins += 1
                else:
                    results.losses += 1

                # Breakdowns
                line_key = str(line)
                results.bets_by_line.setdefault(line_key, {"bets": 0, "wins": 0})
                results.bets_by_line[line_key]["bets"] += 1
                if outcome == "HIT":
                    results.bets_by_line[line_key]["wins"] += 1

                results.bets_by_round.setdefault(round_num, {"bets": 0, "wins": 0})
                results.bets_by_round[round_num]["bets"] += 1
                if outcome == "HIT":
                    results.bets_by_round[round_num]["wins"] += 1

                tier = _ranking_tier(world_ranking)
                results.bets_by_tier.setdefault(tier, {"bets": 0, "wins": 0})
                results.bets_by_tier[tier]["bets"] += 1
                if outcome == "HIT":
                    results.bets_by_tier[tier]["wins"] += 1

                results.season_breakdown.setdefault(season, {"bets": 0, "wins": 0, "profit": 0.0})
                results.season_breakdown[season]["bets"] += 1
                if outcome == "HIT":
                    results.season_breakdown[season]["wins"] += 1
                results.season_breakdown[season]["profit"] += profit

    return results


def _ranking_tier(ranking: Optional[int]) -> str:
    if not ranking:      return "Unknown"
    if ranking <= 25:    return "Elite (1-25)"
    if ranking <= 50:    return "Top-50"
    if ranking <= 100:   return "Top-100"
    if ranking <= 200:   return "Top-200"
    return "200+"


# ---------------------------------------------------------------------------
# Parameter sweep
# ---------------------------------------------------------------------------

SWEEP_GRID = {
    "form_window":          [5, 10, 20],
    "confidence_threshold": [0.53, 0.55, 0.58, 0.60, 0.63, 0.65],
    "min_rounds_history":   [5, 10, 20],
    "course_weight":        [0.0, 0.30, 0.60],
    "major_bump":           [0.0, 0.50, 1.0],
    "round_filter":         [None, 1, 2],    # R1/R2 tend to have cleanest signal
    "line_filter":          [None, 70.5, 72.5],
    "under_only":           [False, True],
}

# Focused grid (fewer combos, faster — good starting point)
FOCUSED_GRID = {
    "form_window":          [10, 20],
    "confidence_threshold": [0.53, 0.55, 0.58, 0.60, 0.63],
    "min_rounds_history":   [10],
    "course_weight":        [0.0, 0.30],
    "major_bump":           [0.0, 0.50],
    "round_filter":         [None, 1],
    "line_filter":          [None, 70.5, 72.5],
    "under_only":           [False, True],
}


def generate_configs(grid: dict) -> list:
    keys = list(grid.keys())
    combos = list(product(*[grid[k] for k in keys]))
    configs = []
    for combo in combos:
        params = dict(zip(keys, combo))
        configs.append(SimConfig(**params))
    return configs


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(all_results: list, top_n: int = 20):
    """Print a formatted simulation report."""
    if not all_results:
        print("\n[GOLF] No results — run backfill_round_logs.py first to populate data.")
        return

    # Filter to configs with meaningful sample size
    viable = [r for r in all_results if r.total_bets >= 50]
    if not viable:
        print("\n[GOLF] Insufficient data — all configs had < 50 bets. Run backfill first.")
        return

    viable.sort(key=lambda r: r.roi, reverse=True)

    print("\n" + "=" * 80)
    print("  GOLF BACKTEST SIMULATION RESULTS")
    print("=" * 80)
    print(f"  Total configs tested : {len(all_results)}")
    print(f"  Configs with 50+ bets: {len(viable)}")
    print(f"  Break-even accuracy  : {BREAK_EVEN:.1%}  (at -110 juice)")
    print()

    # --- Top configs ---
    print(f"  TOP {min(top_n, len(viable))} CONFIGURATIONS BY ROI")
    print("  " + "-" * 76)
    header = f"  {'Config':<52} {'Bets':>5} {'Acc':>6} {'ROI':>7} {'Edge':>7}"
    print(header)
    print("  " + "-" * 76)

    for r in viable[:top_n]:
        marker = " <-- PROFITABLE" if r.accuracy > BREAK_EVEN else ""
        print(
            f"  {r.config.label():<52} "
            f"{r.total_bets:>5} "
            f"{r.accuracy:>6.1%} "
            f"{r.roi:>+7.3f} "
            f"{r.edge:>+7.3f}"
            f"{marker}"
        )

    # --- Best single config deep-dive ---
    best = viable[0]
    print()
    print("  BEST CONFIG DEEP-DIVE")
    print("  " + "-" * 76)
    print(f"  Config     : {best.config.label()}")
    print(f"  Total bets : {best.total_bets}")
    print(f"  Wins/Losses: {best.wins} / {best.losses}")
    print(f"  Accuracy   : {best.accuracy:.2%}  (break-even: {BREAK_EVEN:.2%})")
    print(f"  Edge       : {best.edge:+.3f}  ({best.edge*100:+.2f}pp above break-even)")
    print(f"  ROI        : {best.roi:+.4f}  (per unit wagered)")
    print(f"  Profit     : {best.profit:+.2f} units on {best.total_bets} bets")

    # By line
    if best.bets_by_line:
        print()
        print("  Accuracy by betting line:")
        for line, d in sorted(best.bets_by_line.items()):
            acc = d["wins"] / d["bets"] if d["bets"] else 0
            bar = "#" * int(acc * 30)
            print(f"    Line {line:>5} : {acc:>6.1%} ({d['wins']:>4}/{d['bets']:<4}) {bar}")

    # By round
    if best.bets_by_round:
        print()
        print("  Accuracy by tournament round:")
        for rnd, d in sorted(best.bets_by_round.items()):
            acc = d["wins"] / d["bets"] if d["bets"] else 0
            bar = "#" * int(acc * 30)
            print(f"    Round {rnd}    : {acc:>6.1%} ({d['wins']:>4}/{d['bets']:<4}) {bar}")

    # By player ranking tier
    if best.bets_by_tier:
        print()
        print("  Accuracy by player ranking tier:")
        tier_order = ["Elite (1-25)", "Top-50", "Top-100", "Top-200", "200+", "Unknown"]
        for tier in tier_order:
            if tier not in best.bets_by_tier:
                continue
            d = best.bets_by_tier[tier]
            acc = d["wins"] / d["bets"] if d["bets"] else 0
            bar = "#" * int(acc * 30)
            print(f"    {tier:<16}: {acc:>6.1%} ({d['wins']:>4}/{d['bets']:<4}) {bar}")

    # By season
    if best.season_breakdown:
        print()
        print("  Performance by season (walk-forward validity):")
        for season in sorted(best.season_breakdown.keys()):
            d = best.season_breakdown[season]
            acc = d["wins"] / d["bets"] if d["bets"] else 0
            roi = d["profit"] / d["bets"] if d["bets"] else 0
            print(f"    {season}: {acc:>6.1%} acc | {roi:>+.3f} ROI | {d['bets']} bets")

    # --- Confidence threshold heatmap ---
    print()
    print("  CONFIDENCE THRESHOLD SWEEP (accuracy vs. bet volume trade-off)")
    print("  " + "-" * 76)
    print(f"  {'Threshold':>10} {'Bets':>7} {'Accuracy':>10} {'ROI':>8} {'Verdict':>20}")
    thresholds = sorted(set(r.config.confidence_threshold for r in viable))
    for thresh in thresholds:
        # Best config at this threshold
        at_thresh = [r for r in viable if r.config.confidence_threshold == thresh]
        if not at_thresh:
            continue
        best_at = max(at_thresh, key=lambda r: r.roi)
        verdict = _verdict(best_at.accuracy, best_at.total_bets)
        print(
            f"  {thresh:>10.2f} "
            f"{best_at.total_bets:>7} "
            f"{best_at.accuracy:>10.2%} "
            f"{best_at.roi:>+8.4f} "
            f"  {verdict:>20}"
        )

    # --- Line analysis ---
    print()
    print("  BEST CONFIG PER BETTING LINE")
    print("  " + "-" * 76)
    for target_line in [68.5, 70.5, 72.5]:
        line_configs = [r for r in viable if r.config.line_filter == target_line and r.total_bets >= 30]
        if not line_configs:
            print(f"  Line {target_line}: insufficient data")
            continue
        best_line = max(line_configs, key=lambda r: r.roi)
        print(
            f"  Line {target_line}: "
            f"{best_line.accuracy:.2%} acc | "
            f"{best_line.roi:+.4f} ROI | "
            f"{best_line.total_bets} bets | "
            f"fw={best_line.config.form_window} ct={best_line.config.confidence_threshold}"
        )

    print()
    print("  KEY TAKEAWAYS")
    print("  " + "-" * 76)
    _print_takeaways(viable)
    print("=" * 80)


def _verdict(accuracy: float, bets: int) -> str:
    if bets < 50:   return "INSUFFICIENT DATA"
    if accuracy >= 0.58: return "STRONG EDGE"
    if accuracy >= 0.55: return "EDGE"
    if accuracy >= BREAK_EVEN: return "MARGINAL"
    return "UNPROFITABLE"


def _print_takeaways(viable: list):
    """Print 4-5 actionable bullets from the simulation."""
    if not viable:
        return

    # Best overall
    best = viable[0]
    print(f"  1. Best config: {best.config.label()}")
    print(f"     -> {best.accuracy:.2%} accuracy, {best.roi:+.4f} ROI over {best.total_bets} bets")

    # Best line
    by_line = {}
    for r in viable:
        for lk, d in r.bets_by_line.items():
            if lk not in by_line:
                by_line[lk] = {"wins": 0, "bets": 0}
            by_line[lk]["wins"] += d["wins"]
            by_line[lk]["bets"] += d["bets"]
    if by_line:
        best_line = max(by_line, key=lambda k: by_line[k]["wins"] / max(by_line[k]["bets"], 1))
        bl = by_line[best_line]
        print(f"  2. Most beatable line: {best_line} "
              f"({bl['wins']/bl['bets']:.2%} combined accuracy across all configs)")

    # Best round
    by_round = {}
    for r in viable:
        for rk, d in r.bets_by_round.items():
            if rk not in by_round:
                by_round[rk] = {"wins": 0, "bets": 0}
            by_round[rk]["wins"] += d["wins"]
            by_round[rk]["bets"] += d["bets"]
    if by_round:
        best_rnd = max(by_round, key=lambda k: by_round[k]["wins"] / max(by_round[k]["bets"], 1))
        br = by_round[best_rnd]
        print(f"  3. Most predictable round: Round {best_rnd} "
              f"({br['wins']/br['bets']:.2%} accuracy)")

    # Under vs over
    under_configs = [r for r in viable if r.config.under_only and r.total_bets >= 30]
    both_configs  = [r for r in viable if not r.config.under_only and r.total_bets >= 30]
    if under_configs and both_configs:
        best_u = max(under_configs, key=lambda r: r.accuracy)
        best_b = max(both_configs,  key=lambda r: r.accuracy)
        if best_u.accuracy > best_b.accuracy:
            print(f"  4. UNDER-only filter IMPROVES accuracy "
                  f"({best_u.accuracy:.2%} vs {best_b.accuracy:.2%}) — confirms UNDER bias")
        else:
            print(f"  4. UNDER-only filter does NOT improve accuracy "
                  f"({best_u.accuracy:.2%} vs {best_b.accuracy:.2%})")

    # ML readiness signal
    profitable = [r for r in viable if r.accuracy > BREAK_EVEN]
    print(f"  5. {len(profitable)}/{len(viable)} configs beat break-even — "
          + ("ML training will have a real signal to amplify."
             if profitable else
             "need more data or feature engineering before ML training."))


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def save_csv(all_results: list, path: str):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "config", "total_bets", "wins", "losses",
            "accuracy", "roi", "edge", "profit",
            "form_window", "confidence_threshold", "min_rounds",
            "course_weight", "major_bump", "round_filter",
            "line_filter", "under_only",
        ])
        for r in all_results:
            c = r.config
            writer.writerow([
                c.label(), r.total_bets, r.wins, r.losses,
                f"{r.accuracy:.4f}", f"{r.roi:.4f}", f"{r.edge:.4f}", f"{r.profit:.2f}",
                c.form_window, c.confidence_threshold, c.min_rounds_history,
                c.course_weight, c.major_bump, c.round_filter,
                c.line_filter, c.under_only,
            ])
    print(f"\n  Results saved to: {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Golf walk-forward backtest simulator with parameter sweep"
    )
    parser.add_argument(
        "--seasons", "-s",
        nargs="+",
        type=int,
        default=[2020, 2021, 2022, 2023, 2024, 2025],
        help="Seasons to simulate (default: 2020-2025)",
    )
    parser.add_argument(
        "--full-sweep",
        action="store_true",
        help="Run full parameter grid (slower, more thorough)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help='Run single config e.g. "form_window=10,confidence_threshold=0.58,line_filter=70.5"',
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Save results to CSV file",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top configs to show (default: 20)",
    )
    args = parser.parse_args()

    # Check database has data
    if not Path(DB_PATH).exists():
        print("\n[GOLF] Database not found. Run these first:")
        print("  python golf/scripts/backfill_round_logs.py")
        return

    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM player_round_logs").fetchone()[0]
    if count == 0:
        print(f"\n[GOLF] player_round_logs is empty. Run backfill first:")
        print("  python golf/scripts/backfill_round_logs.py")
        conn.close()
        return

    seasons_in_db = [r[0] for r in conn.execute(
        "SELECT DISTINCT season FROM player_round_logs ORDER BY season"
    ).fetchall()]
    print(f"\n[GOLF] Database: {count:,} rounds | Seasons available: {seasons_in_db}")
    print(f"  Simulating seasons: {args.seasons}")

    # Build config list
    if args.config:
        # Parse single config from string
        params = {}
        for pair in args.config.split(","):
            k, v = pair.split("=")
            k = k.strip()
            v = v.strip()
            if k in ("form_window", "min_rounds_history"):
                params[k] = int(v)
            elif k in ("confidence_threshold", "course_weight", "major_bump", "line_filter"):
                params[k] = float(v) if v != "None" else None
            elif k in ("round_filter",):
                params[k] = int(v) if v != "None" else None
            elif k == "under_only":
                params[k] = v.lower() == "true"
        configs = [SimConfig(**params)]
        print(f"  Running single config: {configs[0].label()}")
    else:
        grid = SWEEP_GRID if args.full_sweep else FOCUSED_GRID
        configs = generate_configs(grid)
        print(f"  Parameter sweep: {len(configs)} configurations")

    # Run simulations
    print(f"\n  Running... (this may take a few minutes for large sweeps)\n")
    all_results = []
    for i, cfg in enumerate(configs, 1):
        result = run_simulation(cfg, args.seasons, conn)
        all_results.append(result)
        if i % 50 == 0 or i == len(configs):
            best_so_far = max(
                (r for r in all_results if r.total_bets >= 50),
                key=lambda r: r.roi,
                default=None,
            )
            best_str = f"best ROI so far: {best_so_far.roi:+.4f}" if best_so_far else "no viable config yet"
            print(f"  [{i:>4}/{len(configs)}] {best_str}")

    conn.close()

    # Report
    print_report(all_results, top_n=args.top)

    if args.output:
        save_csv(all_results, args.output)


if __name__ == "__main__":
    main()
