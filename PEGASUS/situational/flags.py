"""
PEGASUS Situational Intelligence — Flag Definitions

SituationFlag enum + modifier lookup table.

Advisory only: modifiers are NEVER written to the database or applied to
probability / ai_edge / tier. They ride alongside pick output as display
context for the user or Lineup Simulator agent.
"""

from enum import Enum
from typing import Tuple


# ── Flag enum ────────────────────────────────────────────────────────────────

class SituationFlag(str, Enum):
    """
    Situational context flags attached to picks.

    Values are plain strings so they serialize cleanly to JSON/dict without
    extra handling.
    """
    HIGH_STAKES    = "HIGH_STAKES"     # Elimination / bubble — stars play hard
    DEAD_RUBBER    = "DEAD_RUBBER"     # Seed locked / coasting — star minutes down
    REDUCED_STAKES = "REDUCED_STAKES"  # Clinched but seed still moveable — moderate risk
    USAGE_BOOST    = "USAGE_BOOST"     # Star(s) OUT → player absorbs usage
    ELIMINATED     = "ELIMINATED"      # Mathematically out — full rest mode
    NORMAL         = "NORMAL"          # Regular stakes — back the model


# ── Modifier table ───────────────────────────────────────────────────────────
# modifier is an advisory float (-0.15 to +0.10) representing how the
# situation should bias the display confidence.
# Negative = fade (model overstates prop given rest/reduced minutes).
# Positive = boost (model understates prop given urgency / extra minutes).

# Structure:  (SituationFlag, injury_status) -> modifier
# injury_status values: 'OUT', 'DOUBTFUL', 'QUESTIONABLE', 'GTD', 'ACTIVE'
# 'ACTIVE' is the default — player confirmed healthy / no report.

MODIFIER_TABLE: dict[Tuple[SituationFlag, str], float] = {
    # DEAD_RUBBER — player on a seed-locked or coasting team
    (SituationFlag.DEAD_RUBBER, "OUT"):          -0.15,
    (SituationFlag.DEAD_RUBBER, "DOUBTFUL"):     -0.15,
    (SituationFlag.DEAD_RUBBER, "QUESTIONABLE"): -0.10,
    (SituationFlag.DEAD_RUBBER, "GTD"):          -0.08,
    (SituationFlag.DEAD_RUBBER, "ACTIVE"):       -0.06,

    # ELIMINATED — mathematically out, full load-management mode
    (SituationFlag.ELIMINATED, "OUT"):           -0.15,
    (SituationFlag.ELIMINATED, "DOUBTFUL"):      -0.15,
    (SituationFlag.ELIMINATED, "QUESTIONABLE"):  -0.12,
    (SituationFlag.ELIMINATED, "GTD"):           -0.10,
    (SituationFlag.ELIMINATED, "ACTIVE"):        -0.10,

    # REDUCED_STAKES — playoffs clinched, seed still fluid
    (SituationFlag.REDUCED_STAKES, "OUT"):           -0.05,
    (SituationFlag.REDUCED_STAKES, "DOUBTFUL"):      -0.05,
    (SituationFlag.REDUCED_STAKES, "QUESTIONABLE"):  -0.04,
    (SituationFlag.REDUCED_STAKES, "GTD"):           -0.03,
    (SituationFlag.REDUCED_STAKES, "ACTIVE"):        -0.03,

    # HIGH_STAKES — bubble, play-in, elimination game, playoff series
    (SituationFlag.HIGH_STAKES, "OUT"):           0.0,   # Star is actually out — no boost
    (SituationFlag.HIGH_STAKES, "DOUBTFUL"):      0.0,
    (SituationFlag.HIGH_STAKES, "QUESTIONABLE"):  +0.05, # GTD on must-win = likely plays
    (SituationFlag.HIGH_STAKES, "GTD"):           +0.05,
    (SituationFlag.HIGH_STAKES, "ACTIVE"):        +0.03,

    # USAGE_BOOST — beneficiary of a star absence
    (SituationFlag.USAGE_BOOST, "OUT"):           0.0,   # The boosted player shouldn't be out
    (SituationFlag.USAGE_BOOST, "DOUBTFUL"):      0.0,
    (SituationFlag.USAGE_BOOST, "QUESTIONABLE"):  +0.05,
    (SituationFlag.USAGE_BOOST, "GTD"):           +0.07,
    (SituationFlag.USAGE_BOOST, "ACTIVE"):        +0.10,

    # NORMAL — standard game, back the model
    (SituationFlag.NORMAL, "OUT"):           0.0,
    (SituationFlag.NORMAL, "DOUBTFUL"):      0.0,
    (SituationFlag.NORMAL, "QUESTIONABLE"):  0.0,
    (SituationFlag.NORMAL, "GTD"):           0.0,
    (SituationFlag.NORMAL, "ACTIVE"):        0.0,
}


def get_modifier(flag: SituationFlag, injury_status: str = "ACTIVE") -> float:
    """
    Return the advisory modifier for a (flag, injury_status) pair.

    Falls back to ACTIVE modifier if the specific injury_status is not in
    the table (e.g. an unexpected value from the API).

    Args:
        flag:           SituationFlag value
        injury_status:  Player status string — 'OUT', 'DOUBTFUL', 'QUESTIONABLE',
                        'GTD', 'ACTIVE'

    Returns:
        Advisory modifier float. NEVER apply to probability or ai_edge.
    """
    key = (flag, injury_status.upper() if injury_status else "ACTIVE")
    if key in MODIFIER_TABLE:
        return MODIFIER_TABLE[key]
    # Fallback: use ACTIVE row for this flag
    fallback = (flag, "ACTIVE")
    return MODIFIER_TABLE.get(fallback, 0.0)


def flag_from_motivation(motivation_score: float, injury_status: str = "ACTIVE") -> Tuple[SituationFlag, float]:
    """
    Derive (SituationFlag, modifier) from a team motivation_score + player injury status.

    motivation_score bands (from situational_intelligence_layer.md spec):
        0.00–0.15  → ELIMINATED
        0.15–0.25  → DEAD_RUBBER (seed locked)
        0.25–0.50  → REDUCED_STAKES
        0.50–0.65  → NORMAL
        0.65–0.85  → NORMAL (actively competing, regular stakes)
        0.85–1.00  → HIGH_STAKES (bubble / must-win)

    Args:
        motivation_score: 0.0 (no motivation) → 1.0 (maximum urgency)
        injury_status:    Player status string

    Returns:
        (SituationFlag, modifier)
    """
    if motivation_score <= 0.15:
        flag = SituationFlag.ELIMINATED
    elif motivation_score <= 0.25:
        flag = SituationFlag.DEAD_RUBBER
    elif motivation_score <= 0.50:
        flag = SituationFlag.REDUCED_STAKES
    elif motivation_score >= 0.85:
        flag = SituationFlag.HIGH_STAKES
    else:
        flag = SituationFlag.NORMAL

    modifier = get_modifier(flag, injury_status)
    return flag, modifier
