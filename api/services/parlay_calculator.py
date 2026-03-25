"""
Parlay Calculator Service
=========================
EV calculations for multi-leg parlays with goblin/standard/demon support.
"""

from typing import List, Dict, Any
from api.config import PAYOUTS, LEG_VALUES, BREAK_EVEN_RATES


def get_leg_value(odds_type: str) -> float:
    """Get leg value for an odds type."""
    return LEG_VALUES.get(odds_type.lower(), 1.0)


def calculate_total_leg_value(picks: List[Dict]) -> float:
    """
    Calculate total leg value for a parlay.
    Goblin = 0.5, Standard = 1.0, Demon = 1.5
    """
    return sum(get_leg_value(p.get('odds_type', 'standard')) for p in picks)


def calculate_combined_probability(picks: List[Dict]) -> float:
    """
    Calculate combined probability for a parlay.
    Combined = P1 * P2 * P3 * ... * Pn
    """
    prob = 1.0
    for pick in picks:
        prob *= pick.get('probability', 0.5)
    return prob


def interpolate_payout(total_legs: float) -> float:
    """
    Get payout multiplier based on total leg value.
    Interpolates between defined payouts for fractional legs.

    Examples:
        2.0 legs -> 3x
        3.0 legs -> 5x
        3.5 legs -> 7.5x (interpolated)
        4.0 legs -> 10x
    """
    # Clamp to valid range
    clamped = max(2.0, min(6.0, total_legs))

    # Find surrounding defined payouts
    floor_legs = int(clamped)
    ceil_legs = floor_legs + 1

    # Handle exact matches
    if clamped == floor_legs:
        return PAYOUTS.get(floor_legs, 3.0)

    # Linear interpolation
    floor_payout = PAYOUTS.get(floor_legs, 3.0)
    ceil_payout = PAYOUTS.get(ceil_legs, floor_payout)

    fraction = clamped - floor_legs
    return floor_payout + (ceil_payout - floor_payout) * fraction


def calculate_expected_value(combined_prob: float, payout: float) -> float:
    """
    Calculate Expected Value for a parlay.
    EV = (Combined Probability * Payout) - 1

    Returns:
        float: EV as decimal (e.g., 0.5 = +50% EV)
    """
    return (combined_prob * payout) - 1


def calculate_break_even_probability(payout: float) -> float:
    """
    Calculate break-even probability for a given payout.
    Break-even = 1 / Payout
    """
    if payout <= 0:
        return 1.0
    return 1.0 / payout


def get_recommendation(ev_percentage: float) -> str:
    """Get recommendation based on EV percentage."""
    if ev_percentage >= 30:
        return "STRONG_BET"
    elif ev_percentage >= 10:
        return "GOOD_BET"
    elif ev_percentage >= 0:
        return "MARGINAL"
    else:
        return "AVOID"


def calculate_parlay(picks: List[Dict]) -> Dict[str, Any]:
    """
    Full parlay calculation with all metrics.

    Args:
        picks: List of dicts with 'probability' and 'odds_type' keys

    Returns:
        Dict with all parlay metrics
    """
    if len(picks) < 2:
        return {
            "success": False,
            "error": "Parlay requires at least 2 picks",
            "legs": len(picks)
        }

    # Core calculations
    total_leg_value = calculate_total_leg_value(picks)
    combined_probability = calculate_combined_probability(picks)
    payout_multiplier = interpolate_payout(total_leg_value)
    expected_value = calculate_expected_value(combined_probability, payout_multiplier)
    break_even_probability = calculate_break_even_probability(payout_multiplier)

    # Derived metrics
    ev_percentage = expected_value * 100
    is_positive_ev = expected_value > 0
    edge_over_break_even = combined_probability - break_even_probability
    recommendation = get_recommendation(ev_percentage)

    # Find weakest link (lowest probability pick)
    min_prob = min(p.get('probability', 0.5) for p in picks)
    weakest_index = next(
        i for i, p in enumerate(picks)
        if p.get('probability', 0.5) == min_prob
    )

    # Build response
    return {
        "success": True,
        "legs": len(picks),
        "total_leg_value": round(total_leg_value, 2),
        "combined_probability": round(combined_probability, 4),
        "combined_probability_pct": round(combined_probability * 100, 2),
        "payout_multiplier": round(payout_multiplier, 2),
        "expected_value": round(expected_value, 4),
        "ev_percentage": round(ev_percentage, 2),
        "is_positive_ev": is_positive_ev,
        "break_even_probability": round(break_even_probability, 4),
        "break_even_probability_pct": round(break_even_probability * 100, 2),
        "edge_over_break_even": round(edge_over_break_even, 4),
        "edge_over_break_even_pct": round(edge_over_break_even * 100, 2),
        "recommendation": recommendation,
        "weakest_link_index": weakest_index,
        "picks_detail": [
            {
                "index": i,
                "probability": p.get('probability', 0.5),
                "odds_type": p.get('odds_type', 'standard'),
                "leg_value": get_leg_value(p.get('odds_type', 'standard')),
                "is_weakest_link": i == weakest_index,
            }
            for i, p in enumerate(picks)
        ]
    }


def find_optimal_parlay(
    available_picks: List[Dict],
    target_legs: int,
    strategy: str = "balanced"
) -> Dict[str, Any]:
    """
    Find optimal parlay combination from available picks.

    Strategies:
        - max_ev: Maximize expected value
        - max_prob: Maximize win probability
        - balanced: Balance between EV and probability
    """
    if len(available_picks) < target_legs:
        return {
            "success": False,
            "error": f"Not enough picks available ({len(available_picks)} < {target_legs})"
        }

    # Sort picks by probability for greedy selection
    sorted_picks = sorted(
        available_picks,
        key=lambda p: p.get('probability', 0.5),
        reverse=True
    )

    if strategy == "max_prob":
        # Take highest probability picks
        selected = sorted_picks[:target_legs]
    elif strategy == "max_ev":
        # Take picks with best EV contribution
        # (higher probability AND favorable odds type)
        scored_picks = []
        for p in available_picks:
            prob = p.get('probability', 0.5)
            leg_val = get_leg_value(p.get('odds_type', 'standard'))
            # Score: probability weighted by inverse leg value
            # (demon picks with high prob are valuable)
            score = prob * (1 / leg_val) if leg_val > 0 else prob
            scored_picks.append((score, p))
        scored_picks.sort(reverse=True)
        selected = [p for _, p in scored_picks[:target_legs]]
    else:
        # Balanced: mix of high prob and good leg values
        selected = sorted_picks[:target_legs]

    # Calculate parlay for selected picks
    result = calculate_parlay(selected)
    result["strategy"] = strategy
    result["selected_picks"] = selected

    return result
