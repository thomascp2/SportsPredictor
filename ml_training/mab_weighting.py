"""
ml_training/mab_weighting.py

Multi-Armed Bandit (Thompson Sampling) for dynamic model weight assignment.

Instead of the hardcoded 60/40 ML/stat blend, this module tracks each model's
win/loss record over a rolling 7-game window and samples blend weights from
Beta distributions — models that have been more accurate recently get higher weight.

Thompson Sampling:
  Each model has a Beta(alpha, beta) distribution.
  alpha = wins (correct predictions), beta = losses.
  At inference time, sample one weight per model from its Beta distribution.
  Normalize to sum to 1. This naturally explores weaker models while
  exploiting stronger ones — no manual tuning required.

State persistence:
  ml_training/mab_state/{sport}_{prop_key}.json
  Survives process restarts. Updated once per day after grading.

Initial weights (cold start prior):
  XGB: alpha=4, beta=2  (implied ~67% win rate — our best model)
  RF:  alpha=3, beta=2  (implied ~60%)
  LR:  alpha=2, beta=2  (implied ~50% — most conservative)
  stat: alpha=2, beta=3  (implied ~40% — statistical is weakest, ML should dominate)

Usage:
    from ml_training.mab_weighting import ThompsonSamplingMAB

    mab = ThompsonSamplingMAB()

    # Sample weights for today's inference
    weights = mab.sample_weights("nba", "points", ["xgb", "rf", "lr", "stat"])
    # → {"xgb": 0.48, "rf": 0.31, "lr": 0.14, "stat": 0.07}

    # After grading: update based on who was right
    mab.update("nba", "points", "xgb", correct=True)
    mab.update("nba", "points", "rf", correct=False)
    mab.save()
"""

from __future__ import annotations

import json
import os
from datetime import date as _date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ML_DIR     = Path(__file__).resolve().parent
_STATE_DIR  = _ML_DIR / "mab_state"
_STATE_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cold-start Beta priors: (alpha, beta)
# Reflect our prior belief about each model's win rate before any live data.
_COLD_START_PRIORS = {
    "xgb":  (4, 2),   # ~67% implied — XGBoost is primary model
    "rf":   (3, 2),   # ~60% implied — solid secondary
    "lr":   (2, 2),   # ~50% implied — linear baseline
    "stat": (2, 3),   # ~40% implied — statistical least reliable alone
}

_ROLLING_WINDOW_DAYS = 7
_DECAY_FACTOR        = 0.9    # wins/losses older than window discounted by this factor
_MIN_ALPHA           = 1      # never let alpha drop below 1 (Beta stays defined)
_MIN_BETA            = 1      # same for beta


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ThompsonSamplingMAB:
    """
    Multi-Armed Bandit with Thompson Sampling for ML model weight assignment.

    State is keyed by (sport, prop_key) where prop_key = "{prop_type}_{line_bucket}".
    Line bucket is omitted for sport-level tracking (use prop_type alone).
    """

    def __init__(self, state_dir: str | Path = None):
        self.state_dir = Path(state_dir) if state_dir else _STATE_DIR
        self.state_dir.mkdir(exist_ok=True)
        self._state: dict[str, dict] = {}   # {sport_prop_key: {model: {alpha, beta, history}}}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sample_weights(
        self,
        sport: str,
        prop_type: str,
        models: list[str],
        line: float = None,
        n_samples: int = 1000,
    ) -> dict[str, float]:
        """
        Sample normalized weights from each model's Beta distribution.

        High-performing models (high alpha relative to beta) will tend to
        receive higher weight. The stochastic nature ensures continued
        exploration — a model on a cold streak still gets some allocation.

        Args:
            sport: 'nba', 'nhl', 'mlb'
            prop_type: 'points', 'shots', etc.
            models: list of model names, e.g. ['xgb', 'rf', 'lr', 'stat']
            line: optional line value for prop-line-specific tracking
            n_samples: number of Beta samples to average (reduces variance)

        Returns:
            dict of model → weight, summing to 1.0
        """
        state = self._load_state(sport, prop_type, line)
        weights = {}

        for model in models:
            alpha, beta = self._get_params(state, model)
            # Average n_samples draws for stable weight (single draw too noisy)
            samples = np.random.beta(alpha, beta, size=n_samples)
            weights[model] = float(np.mean(samples))

        # Normalize
        total = sum(weights.values())
        if total > 0:
            weights = {m: round(w / total, 4) for m, w in weights.items()}

        return weights

    def update(
        self,
        sport: str,
        prop_type: str,
        model: str,
        correct: bool,
        line: float = None,
        game_date: str = None,
    ) -> None:
        """
        Update a model's win/loss record after grading.

        Call this once per graded prediction, per model that contributed.

        Args:
            sport: 'nba', 'nhl', 'mlb'
            prop_type: 'points', 'shots', etc.
            model: model name ('xgb', 'rf', 'lr', 'stat')
            correct: True if model's prediction was correct
            line: optional line for prop-line-specific tracking
            game_date: date of game (defaults to today)
        """
        key = self._make_key(sport, prop_type, line)
        if key not in self._state:
            self._state[key] = self._load_raw(sport, prop_type, line)

        state = self._state[key]
        if model not in state:
            state[model] = self._make_model_entry(model)

        entry = state[model]
        game_date = game_date or _date.today().isoformat()

        # Update Beta params
        if correct:
            entry["alpha"] += 1
            entry["wins"]  += 1
        else:
            entry["beta"]  += 1
            entry["losses"] += 1

        # Record to history for rolling window
        entry["history"].append({
            "date":    game_date,
            "correct": correct,
        })

        # Trim history to rolling window + buffer
        cutoff = (datetime.strptime(game_date, "%Y-%m-%d") - timedelta(days=_ROLLING_WINDOW_DAYS + 3)).date().isoformat()
        entry["history"] = [h for h in entry["history"] if h["date"] >= cutoff]

    def apply_decay(self, sport: str, prop_type: str, line: float = None) -> None:
        """
        Apply time decay to wins/losses outside the rolling window.

        Reduces the influence of results older than ROLLING_WINDOW_DAYS.
        Call this daily before updating with new grades.
        """
        key = self._make_key(sport, prop_type, line)
        if key not in self._state:
            return

        state = self._state[key]
        today = _date.today()
        cutoff = (today - timedelta(days=_ROLLING_WINDOW_DAYS)).isoformat()

        for model, entry in state.items():
            recent_wins   = sum(1 for h in entry["history"] if h["date"] >= cutoff and h["correct"])
            recent_losses = sum(1 for h in entry["history"] if h["date"] >= cutoff and not h["correct"])

            # Decay the portion outside the window
            stale_alpha = entry["alpha"] - recent_wins
            stale_beta  = entry["beta"]  - recent_losses

            # Apply decay: reduce stale parameters
            decayed_alpha = recent_wins  + max(0.0, stale_alpha * _DECAY_FACTOR)
            decayed_beta  = recent_losses + max(0.0, stale_beta * _DECAY_FACTOR)

            prior_alpha, prior_beta = _COLD_START_PRIORS.get(model, (2, 2))
            entry["alpha"] = max(_MIN_ALPHA, int(decayed_alpha) + prior_alpha)
            entry["beta"]  = max(_MIN_BETA,  int(decayed_beta)  + prior_beta)

    def save(self) -> None:
        """Persist all in-memory state to disk."""
        for key, state in self._state.items():
            sport, prop_key = key.split("|", 1)
            path = self.state_dir / f"{sport}_{prop_key}.json"
            path.write_text(json.dumps(state, indent=2))

    def get_model_stats(self, sport: str, prop_type: str, line: float = None) -> dict:
        """
        Return current win rates and implied probabilities for all models.
        Useful for monitoring and the drift detector.
        """
        state = self._load_state(sport, prop_type, line)
        stats = {}

        for model in _COLD_START_PRIORS:
            alpha, beta = self._get_params(state, model)
            total = alpha + beta
            # Beta distribution mean = alpha / (alpha + beta)
            implied_win_rate = alpha / total
            stats[model] = {
                "alpha":            alpha,
                "beta":             beta,
                "implied_win_rate": round(implied_win_rate, 4),
                "total_graded":     state.get(model, {}).get("wins", 0)
                                    + state.get(model, {}).get("losses", 0),
            }

        return stats

    def reset(self, sport: str, prop_type: str, line: float = None) -> None:
        """Reset a prop back to cold-start priors. Use when starting a new season."""
        key = self._make_key(sport, prop_type, line)
        self._state[key] = {}
        path = self._state_path(sport, prop_type, line)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_key(self, sport: str, prop_type: str, line: float = None) -> str:
        prop_key = self._make_prop_key(prop_type, line)
        return f"{sport.lower()}|{prop_key}"

    def _make_prop_key(self, prop_type: str, line: float = None) -> str:
        if line is not None:
            # Round line to 1 decimal to avoid float key fragmentation
            return f"{prop_type}_{round(line, 1)}"
        return prop_type

    def _state_path(self, sport: str, prop_type: str, line: float = None) -> Path:
        prop_key = self._make_prop_key(prop_type, line)
        return self.state_dir / f"{sport.lower()}_{prop_key}.json"

    def _load_state(self, sport: str, prop_type: str, line: float = None) -> dict:
        key = self._make_key(sport, prop_type, line)
        if key not in self._state:
            self._state[key] = self._load_raw(sport, prop_type, line)
        return self._state[key]

    def _load_raw(self, sport: str, prop_type: str, line: float = None) -> dict:
        path = self._state_path(sport, prop_type, line)
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        return {}

    def _get_params(self, state: dict, model: str) -> tuple[int, int]:
        """Get (alpha, beta) for a model, initializing from cold-start prior if missing."""
        if model not in state:
            return _COLD_START_PRIORS.get(model, (2, 2))

        entry = state[model]
        prior_alpha, prior_beta = _COLD_START_PRIORS.get(model, (2, 2))

        alpha = max(_MIN_ALPHA, entry.get("alpha", prior_alpha))
        beta  = max(_MIN_BETA,  entry.get("beta",  prior_beta))
        return alpha, beta

    def _make_model_entry(self, model: str) -> dict:
        alpha, beta = _COLD_START_PRIORS.get(model, (2, 2))
        return {
            "alpha":   alpha,
            "beta":    beta,
            "wins":    0,
            "losses":  0,
            "history": [],
        }


# ---------------------------------------------------------------------------
# Convenience: batch update from grading results
# ---------------------------------------------------------------------------

def update_from_grading(
    mab: ThompsonSamplingMAB,
    grading_results: list[dict],
    sport: str,
) -> None:
    """
    Update MAB state from a batch of graded predictions.

    grading_results: list of dicts with keys:
        - prop_type: str
        - line: float
        - actual_outcome: 'OVER' or 'UNDER'
        - model_predictions: dict of model_name → predicted_direction ('OVER'/'UNDER')
        - game_date: str (YYYY-MM-DD)

    Typically called once per day after run_grading completes.
    """
    for result in grading_results:
        prop_type = result.get("prop_type", "")
        line      = result.get("line")
        actual    = result.get("actual_outcome", "").upper()
        game_date = result.get("game_date", _date.today().isoformat())
        model_preds = result.get("model_predictions", {})

        for model, predicted in model_preds.items():
            correct = predicted.upper() == actual
            mab.update(sport, prop_type, model, correct, line, game_date)

    mab.save()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse

    parser = argparse.ArgumentParser(description="Thompson Sampling MAB — model weight manager")
    sub = parser.add_subparsers(dest="cmd")

    # Show current weights
    weights_cmd = sub.add_parser("weights", help="Show current sampled weights")
    weights_cmd.add_argument("sport",     choices=["nba", "nhl", "mlb"])
    weights_cmd.add_argument("prop_type", help="Prop type (e.g. points)")

    # Show stats
    stats_cmd = sub.add_parser("stats", help="Show model win rates")
    stats_cmd.add_argument("sport",     choices=["nba", "nhl", "mlb"])
    stats_cmd.add_argument("prop_type", help="Prop type")

    # Simulate
    sim_cmd = sub.add_parser("simulate", help="Simulate N updates and show weight drift")
    sim_cmd.add_argument("sport",     choices=["nba", "nhl", "mlb"])
    sim_cmd.add_argument("prop_type")
    sim_cmd.add_argument("--n",       type=int, default=50)
    sim_cmd.add_argument("--xgb-wr",  type=float, default=0.65, dest="xgb_wr")

    args = parser.parse_args()
    mab = ThompsonSamplingMAB()

    if args.cmd == "weights":
        models = ["xgb", "rf", "lr", "stat"]
        weights = mab.sample_weights(args.sport, args.prop_type, models)
        print(f"\nSampled weights for {args.sport.upper()} {args.prop_type}:")
        for model, w in sorted(weights.items(), key=lambda x: -x[1]):
            bar = "#" * int(w * 40)
            print(f"  {model:6s}  {w:.3f}  {bar}")

    elif args.cmd == "stats":
        stats = mab.get_model_stats(args.sport, args.prop_type)
        print(f"\nModel stats for {args.sport.upper()} {args.prop_type}:")
        print(f"  {'Model':6s}  {'Alpha':>6}  {'Beta':>6}  {'Win Rate':>9}  {'Graded':>7}")
        for model, s in stats.items():
            print(f"  {model:6s}  {s['alpha']:>6}  {s['beta']:>6}  "
                  f"{s['implied_win_rate']:>8.1%}  {s['total_graded']:>7}")

    elif args.cmd == "simulate":
        models = ["xgb", "rf", "lr", "stat"]
        win_rates = {"xgb": args.xgb_wr, "rf": 0.58, "lr": 0.52, "stat": 0.48}

        print(f"\nSimulating {args.n} updates (XGB win rate = {args.xgb_wr:.0%})...")
        rng = np.random.default_rng(42)

        for i in range(args.n):
            for model in models:
                correct = rng.random() < win_rates[model]
                mab.update(args.sport, args.prop_type, model, bool(correct))

        weights = mab.sample_weights(args.sport, args.prop_type, models)
        print(f"\nResulting weights after {args.n} updates:")
        for model, w in sorted(weights.items(), key=lambda x: -x[1]):
            bar = "#" * int(w * 40)
            print(f"  {model:6s}  {w:.3f}  {bar}")

        stats = mab.get_model_stats(args.sport, args.prop_type)
        print(f"\nImplied win rates:")
        for model, s in stats.items():
            print(f"  {model:6s}  {s['implied_win_rate']:.1%}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _main()
