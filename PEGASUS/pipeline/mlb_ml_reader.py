"""
PEGASUS/pipeline/mlb_ml_reader.py

Read-only interface to the MLB XGBoost predictions stored in mlb_feature_store DuckDB.

The DuckDB `ml_predictions` table stores a regression output (`predicted_value`) — the
XGBoost model's expected count for a player/prop on a given date.  It does NOT store
probabilities or PP lines.  Two functions are provided:

  get_today_mlb_ml_predictions(game_date)
      Fetch all XGBoost predictions for a date.
      Returns: {(player_name, prop): {"predicted_value": float, "p_over": None, "line": None}}
      p_over and line are always None here — the pick_selector fills them by calling
      compute_ml_p_over() once the PP line is known.

  compute_ml_p_over(predicted_value, line, prop)
      Convert a regression mean to P(stat > line) using the same distribution logic
      as mlb/scripts/statistical_predictions.py:
        - Poisson CDF: hits, total_bases, home_runs, walks
        - Normal CDF:  strikeouts (sigma ~1.8), outs_recorded (sigma ~2.5)
      Returns float in [0.001, 0.999] or None on failure.

Blend logic (implemented in pick_selector.py, documented here for reference):
  BLEND_PROPS:   props where final_prob = 0.60 * ml_p_over + 0.40 * stat_prob
  STAT_ONLY_PROPS: props where final_prob = stat_prob (ML excluded)

  Rule 5 from PLAN.md: home_runs uses stat_prob only — the XGBoost model
  is worse than naive for home_runs.  It is excluded from BLEND_PROPS even
  though it exists in the DB.

Design rules:
  - Read-only: never INSERT / UPDATE / DELETE on any DB
  - Graceful degradation: if DuckDB is unavailable, the table is missing, or a
    player is absent, return {} / None — never raise
  - Mirrors nhl_ml_reader.py structure for consistency
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PEGASUS_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT    = _PEGASUS_ROOT.parent
_DUCKDB_PATH  = _REPO_ROOT / "mlb_feature_store" / "data" / "mlb.duckdb"

# ---------------------------------------------------------------------------
# Blend configuration (used by pick_selector.py)
# ---------------------------------------------------------------------------

# Props that receive the 60/40 ML/stat blend
BLEND_PROPS: frozenset[str] = frozenset({
    "hits",
    "total_bases",
    "strikeouts",
    "walks",
    "outs_recorded",
})

# Props that are stat-only (ML excluded).
# home_runs is in the DB but Rule 5 excludes it — model is worse than naive.
STAT_ONLY_PROPS: frozenset[str] = frozenset({
    "home_runs",
})

# Blend weights
ML_WEIGHT   = 0.60
STAT_WEIGHT = 0.40

# Distribution type per prop (used by compute_ml_p_over)
# "poisson" or "normal"
_PROP_DISTRIBUTION: dict[str, str] = {
    "hits":          "poisson",
    "total_bases":   "poisson",
    "home_runs":     "poisson",   # excluded from blend but formula still works
    "walks":         "poisson",
    "strikeouts":    "normal",
    "outs_recorded": "normal",
}

# Fixed sigma estimates for Normal-distribution props.
# These are conservative league-average std estimates.
# strikeouts: pitcher Ks per start, std ~1.8 (range: 2-12 Ks, mostly 4-9)
# outs_recorded: pitcher outs, std ~2.5 (range: 9-27 outs, mostly 12-21)
_NORMAL_SIGMA: dict[str, float] = {
    "strikeouts":    1.8,
    "outs_recorded": 2.5,
}


# ---------------------------------------------------------------------------
# 1.  get_today_mlb_ml_predictions
# ---------------------------------------------------------------------------

def get_today_mlb_ml_predictions(game_date: str) -> dict:
    """
    Fetch XGBoost regression predictions from mlb_feature_store DuckDB.

    Args:
        game_date: ISO date string, e.g. "2026-04-15"

    Returns:
        {
            (player_name, prop): {
                "predicted_value": float,   # XGBoost regression mean (expected count)
                "p_over":          None,    # filled later by compute_ml_p_over()
                "line":            None,    # filled later by pick_selector from PP data
            },
            ...
        }
        Empty dict {} if DuckDB is unavailable, table missing, or no rows for date.
    """
    if not _DUCKDB_PATH.exists():
        # DB not found — silent degradation
        return {}

    try:
        import duckdb  # imported here so the module loads even without duckdb installed
    except ImportError:
        return {}

    result: dict = {}

    try:
        conn = duckdb.connect(str(_DUCKDB_PATH), read_only=True)
        try:
            rows = conn.execute(
                """
                SELECT player_name, prop, predicted_value
                FROM   ml_predictions
                WHERE  game_date = ?
                  AND  predicted_value IS NOT NULL
                  AND  player_name IS NOT NULL
                ORDER  BY player_name, prop
                """,
                [game_date],
            ).fetchall()
        finally:
            conn.close()

        for player_name, prop, predicted_value in rows:
            key = (player_name, prop)
            result[key] = {
                "predicted_value": float(predicted_value),
                "p_over":          None,
                "line":            None,
            }

    except Exception as e:
        # Any DB error → silent degradation; pick_selector falls back to stat_prob
        print(f"[mlb_ml_reader] DuckDB read error for {game_date}: {e}")
        return {}

    return result


# ---------------------------------------------------------------------------
# 2.  compute_ml_p_over
# ---------------------------------------------------------------------------

def compute_ml_p_over(
    predicted_value: float,
    line: float,
    prop: str,
) -> Optional[float]:
    """
    Convert an XGBoost regression mean to P(stat > line).

    Uses the same distribution logic as mlb/scripts/statistical_predictions.py:
      - Poisson CDF for count props (hits, total_bases, home_runs, walks)
      - Normal CDF for approximately-continuous props (strikeouts, outs_recorded)

    Args:
        predicted_value: XGBoost regression output (expected stat count)
        line:            PrizePicks line, e.g. 0.5, 1.5, 4.5
        prop:            prop name, e.g. "hits", "strikeouts"

    Returns:
        Float in [0.001, 0.999], or None if prop is unknown / inputs invalid.
    """
    if predicted_value is None or line is None or prop not in _PROP_DISTRIBUTION:
        return None

    dist = _PROP_DISTRIBUTION[prop]

    try:
        if dist == "poisson":
            return _poisson_prob_over(line, predicted_value)
        else:  # "normal"
            sigma = _NORMAL_SIGMA.get(prop, 2.0)
            return _normal_prob_over(line, predicted_value, sigma)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Distribution helpers (mirrors statistical_predictions.py exactly)
# ---------------------------------------------------------------------------

def _poisson_prob_over(line: float, lam: float) -> float:
    """P(X > line) for Poisson(lambda=lam)."""
    if lam <= 0:
        return 0.001

    threshold = math.floor(line) + 1  # smallest integer strictly above line

    prob_under = 0.0
    log_lam = math.log(lam)
    log_k_fact = 0.0

    for k in range(threshold):
        log_prob = k * log_lam - lam - log_k_fact
        prob_under += math.exp(log_prob)
        if k > 0:
            log_k_fact += math.log(k + 1)
        else:
            log_k_fact = 0.0

    return max(0.001, min(0.999, 1.0 - prob_under))


def _normal_prob_over(line: float, mu: float, sigma: float) -> float:
    """P(X > line) for Normal(mu, sigma)."""
    if sigma <= 0:
        return 1.0 if mu > line else 0.0

    z = (line - mu) / sigma
    prob = 0.5 * math.erfc(z / math.sqrt(2))
    return max(0.001, min(0.999, prob))


# ---------------------------------------------------------------------------
# CLI validation runner
# ---------------------------------------------------------------------------

def _print_validation_report(game_date: str) -> None:
    """Quick validation: fetch today's predictions and spot-check them."""
    print(f"\nMLB ML Reader — Validation ({game_date})")
    print("=" * 60)

    data = get_today_mlb_ml_predictions(game_date)

    if not data:
        print("  No data returned (DB missing or no rows for date).")
        return

    # Count by prop
    prop_counts: dict[str, int] = {}
    for (player, prop), _ in data.items():
        prop_counts[prop] = prop_counts.get(prop, 0) + 1

    print(f"  Total player/prop rows: {len(data)}")
    print("  Rows by prop:")
    for prop, n in sorted(prop_counts.items()):
        blend = "BLEND" if prop in BLEND_PROPS else ("STAT_ONLY" if prop in STAT_ONLY_PROPS else "unknown")
        print(f"    {prop:<20} n={n:<5} [{blend}]")

    # Spot-check: for a sample prop, show predicted_value and compute p_over at a typical line
    SAMPLE_LINES: dict[str, float] = {
        "hits":          0.5,
        "total_bases":   1.5,
        "strikeouts":    4.5,
        "walks":         0.5,
        "outs_recorded": 17.5,
        "home_runs":     0.5,
    }

    print("\n  Sample picks (first player per prop, p_over at typical line):")
    seen_props: set[str] = set()
    for (player, prop), info in sorted(data.items(), key=lambda x: (x[0][1], x[0][0] or "")):
        if prop in seen_props:
            continue
        seen_props.add(prop)

        pv   = info["predicted_value"]
        line = SAMPLE_LINES.get(prop, 1.5)
        p_over = compute_ml_p_over(pv, line, prop)
        blend_flag = "BLEND" if prop in BLEND_PROPS else "STAT_ONLY"

        print(f"    {player:<25} {prop:<20} predicted_value={pv:.4f}  "
              f"p_over(line={line})={p_over:.3f}  [{blend_flag}]")

    print("\n  Blend logic reminder:")
    print(f"    BLEND_PROPS ({ML_WEIGHT:.0%} ML + {STAT_WEIGHT:.0%} stat): {sorted(BLEND_PROPS)}")
    print(f"    STAT_ONLY_PROPS: {sorted(STAT_ONLY_PROPS)}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else "2026-04-15"
    _print_validation_report(date_arg)
