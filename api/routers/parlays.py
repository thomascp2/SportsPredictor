"""
Parlay Calculator Router
========================
Endpoints for calculating parlay EV with goblin/standard/demon support.
"""

from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from api.services.parlay_calculator import (
    calculate_parlay,
    find_optimal_parlay,
    PAYOUTS,
    LEG_VALUES,
    BREAK_EVEN_RATES,
)

router = APIRouter()


class ParlayPick(BaseModel):
    """Single pick in a parlay."""
    player_name: Optional[str] = Field(None, description="Player name (optional)")
    prop_type: Optional[str] = Field(None, description="Prop type (optional)")
    line: Optional[float] = Field(None, description="Line value (optional)")
    prediction: Optional[str] = Field(None, description="OVER or UNDER (optional)")
    probability: float = Field(..., ge=0.0, le=1.0, description="Win probability (0-1)")
    odds_type: str = Field('standard', description="goblin, standard, or demon")


class ParlayRequest(BaseModel):
    """Request body for parlay calculation."""
    picks: List[ParlayPick] = Field(..., min_length=2, max_length=10)


@router.post("/calculate")
async def calculate_parlay_ev(request: ParlayRequest):
    """
    Calculate expected value for a parlay.

    Send picks with probabilities and odds types, get back:
    - Combined probability
    - Payout multiplier (interpolated for fractional legs)
    - Expected value
    - Break-even comparison
    - Recommendation

    Example request:
    ```json
    {
        "picks": [
            {"probability": 0.72, "odds_type": "standard"},
            {"probability": 0.68, "odds_type": "goblin"}
        ]
    }
    ```
    """
    picks_data = [
        {
            'player_name': p.player_name,
            'prop_type': p.prop_type,
            'line': p.line,
            'prediction': p.prediction,
            'probability': p.probability,
            'odds_type': p.odds_type,
        }
        for p in request.picks
    ]

    result = calculate_parlay(picks_data)
    return result


@router.get("/reference")
async def parlay_reference():
    """
    Get parlay payout reference table.

    Returns payout multipliers, leg values, and break-even rates.
    """
    return {
        "success": True,
        "payouts": {
            "description": "Payout multiplier by total leg value",
            "table": {str(k): f"{v}x" for k, v in PAYOUTS.items()},
            "note": "Fractional legs are interpolated (e.g., 3.5 legs ≈ 7.5x)"
        },
        "leg_values": {
            "description": "How much each odds type counts toward total legs",
            "goblin": "0.5 legs (easier line, lower payout)",
            "standard": "1.0 legs (normal)",
            "demon": "1.5 legs (harder line, higher payout)",
        },
        "break_even_rates": {
            "description": "Win rate needed per pick to break even",
            "goblin": "76% (4 goblins = 2 legs = 3x payout)",
            "standard": "56% (4 standards = 4 legs = 10x payout)",
            "demon": "45% (4 demons = 6 legs = 25x payout)",
        },
        "examples": [
            {
                "scenario": "4 standard picks at 70% each",
                "legs": 4.0,
                "payout": "10x",
                "combined_prob": "24.01%",
                "ev": "+140.1%",
            },
            {
                "scenario": "2 goblin + 2 standard at 70% each",
                "legs": 3.0,
                "payout": "5x",
                "combined_prob": "24.01%",
                "ev": "+20.1%",
            },
            {
                "scenario": "4 demon picks at 60% each",
                "legs": 6.0,
                "payout": "25x",
                "combined_prob": "12.96%",
                "ev": "+224.0%",
            },
        ]
    }


@router.get("/quick")
async def quick_calculate(
    probs: str = Query(..., description="Comma-separated probabilities (e.g., '0.72,0.68,0.65')"),
    types: Optional[str] = Query(None, description="Comma-separated odds types (default: all standard)"),
):
    """
    Quick parlay calculation via query params.

    Example: /api/parlays/quick?probs=0.72,0.68,0.65&types=standard,goblin,standard
    """
    try:
        prob_list = [float(p.strip()) for p in probs.split(',')]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid probability format")

    if len(prob_list) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 picks")

    if types:
        type_list = [t.strip().lower() for t in types.split(',')]
        if len(type_list) != len(prob_list):
            raise HTTPException(
                status_code=400,
                detail=f"Number of types ({len(type_list)}) must match probabilities ({len(prob_list)})"
            )
    else:
        type_list = ['standard'] * len(prob_list)

    picks = [
        {'probability': prob, 'odds_type': odds_type}
        for prob, odds_type in zip(prob_list, type_list)
    ]

    return calculate_parlay(picks)


@router.get("/simulate")
async def simulate_parlays(
    base_prob: float = Query(0.65, description="Base probability per pick"),
    odds_type: str = Query('standard', description="Odds type for all picks"),
    max_legs: int = Query(6, description="Maximum legs to simulate"),
):
    """
    Simulate parlays from 2 to max_legs with same probability.

    Useful for visualizing how EV changes with parlay size.
    """
    results = []

    for legs in range(2, max_legs + 1):
        picks = [{'probability': base_prob, 'odds_type': odds_type}] * legs
        result = calculate_parlay(picks)
        results.append({
            'legs': legs,
            'total_leg_value': result['total_leg_value'],
            'combined_probability': result['combined_probability_pct'],
            'payout': result['payout_multiplier'],
            'ev_percentage': result['ev_percentage'],
            'is_positive_ev': result['is_positive_ev'],
        })

    return {
        "success": True,
        "base_probability": base_prob,
        "odds_type": odds_type,
        "simulations": results,
    }
