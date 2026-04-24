"""
PrizePicks Business Rules Validator
====================================
Single source of truth for what combinations are actually possible on PrizePicks.
Call validate_before_write() before inserting any prediction or outcome record.
Call validate_outcome() before inserting any graded result.

PrizePicks rules (as of 2026):
  - DEMON lines: OVER only. No UNDER demon picks exist on the platform.
  - GOBLIN lines: OVER only. No UNDER goblin picks exist on the platform.
  - STANDARD lines: both OVER and UNDER available.
  - A player who did NOT play (actual_value is None or 0 on a non-zero line):
      should be VOID/DNP, not HIT or MISS.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


ODDS_TYPE_DIRECTION_RULES: dict[str, set[str]] = {
    "demon":    {"over"},
    "goblin":   {"over"},
    "standard": {"over", "under"},
}

VALID_OUTCOMES = {"HIT", "MISS", "PUSH", "VOID", "DNP"}


@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.valid


def validate_prediction(odds_type: str, direction: str) -> ValidationResult:
    """Return (valid, reason). Call before writing a prediction record."""
    ot = (odds_type or "standard").lower().strip()
    d  = (direction or "").lower().strip()

    allowed = ODDS_TYPE_DIRECTION_RULES.get(ot)
    if allowed is None:
        return ValidationResult(False, f"Unknown odds_type '{odds_type}'. Must be demon|goblin|standard.")

    if d not in allowed:
        return ValidationResult(
            False,
            f"Impossible combination: {odds_type.upper()} + {direction.upper()}. "
            f"{odds_type.upper()} lines on PrizePicks are {'/'.join(s.upper() for s in allowed)} only."
        )

    return ValidationResult(True)


def validate_outcome(
    odds_type: str,
    direction: str,
    actual_value: Optional[float],
    line_score: float,
    proposed_outcome: str,
) -> ValidationResult:
    """
    Validate a graded outcome before writing to prediction_outcomes.
    Returns (valid, reason).

    Catches:
      1. Impossible odds_type + direction combos
      2. DNP players being counted as HIT/MISS instead of VOID
      3. Logically impossible grades (OVER HIT but actual < line)
    """
    pred_check = validate_prediction(odds_type, direction)
    if not pred_check:
        return pred_check

    d = (direction or "").lower().strip()
    outcome = (proposed_outcome or "").upper().strip()

    # DNP check: actual_value is None means player didn't play (no stats recorded).
    # actual_value == 0 is a real zero-stat game (e.g. 0 points, 0 shots) and grades normally.
    if actual_value is None:
        if outcome in ("HIT", "MISS"):
            return ValidationResult(
                False,
                f"Player recorded actual_value=None (DNP). "
                f"Outcome must be VOID or DNP, not {outcome}."
            )
        return ValidationResult(True)

    # Logic check: can't HIT an OVER if actual is below line
    if outcome == "HIT" and d == "over" and actual_value < line_score:
        return ValidationResult(
            False,
            f"Impossible OVER HIT: actual={actual_value} < line={line_score}."
        )

    # Logic check: can't MISS an OVER if actual is above line
    if outcome == "MISS" and d == "over" and actual_value > line_score:
        return ValidationResult(
            False,
            f"Impossible OVER MISS: actual={actual_value} > line={line_score}."
        )

    # Logic check: can't HIT an UNDER if actual is above line
    if outcome == "HIT" and d == "under" and actual_value > line_score:
        return ValidationResult(
            False,
            f"Impossible UNDER HIT: actual={actual_value} > line={line_score}."
        )

    # Logic check: can't MISS an UNDER if actual is below line
    if outcome == "MISS" and d == "under" and actual_value < line_score:
        return ValidationResult(
            False,
            f"Impossible UNDER MISS: actual={actual_value} < line={line_score}."
        )

    return ValidationResult(True)


def correct_outcome(
    odds_type: str,
    direction: str,
    actual_value: Optional[float],
    line_score: float,
) -> str:
    """
    Given a real actual_value, compute the correct outcome string.
    Returns: 'HIT' | 'MISS' | 'PUSH' | 'VOID'
    """
    pred_check = validate_prediction(odds_type, direction)
    if not pred_check:
        return "VOID"

    if actual_value is None:
        return "VOID"

    d = (direction or "").lower().strip()

    if actual_value == line_score:
        return "PUSH"

    if d == "over":
        return "HIT" if actual_value > line_score else "MISS"

    if d == "under":
        return "HIT" if actual_value < line_score else "MISS"

    return "VOID"


# ---------------------------------------------------------------------------
# Quick sanity check — run directly to test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        ("demon",    "UNDER", None,  5.5, "HIT"),   # impossible combo
        ("goblin",   "UNDER", 3.0,   2.5, "HIT"),   # impossible combo
        ("standard", "OVER",  0,    15.5, "HIT"),   # DNP counted as HIT
        ("standard", "OVER",  20.0, 15.5, "MISS"),  # logic impossible
        ("standard", "UNDER", 20.0, 15.5, "HIT"),   # logic impossible
        ("standard", "OVER",  20.0, 15.5, "HIT"),   # valid
        ("standard", "UNDER", 10.0, 15.5, "HIT"),   # valid
        ("demon",    "OVER",  20.0, 18.5, "HIT"),   # valid
    ]

    print("PP Rules Validator — Test Suite")
    print("-" * 60)
    all_pass = True
    for ot, d, av, line, outcome in tests:
        result = validate_outcome(ot, d, av, line, outcome)
        corrected = correct_outcome(ot, d, av, line)
        status = "BLOCKED" if not result else "ALLOWED"
        print(f"  [{status}] {ot}+{d} actual={av} line={line} outcome={outcome}")
        if not result:
            print(f"           Reason: {result.reason}")
            print(f"           Corrected: {corrected}")
    print("-" * 60)
