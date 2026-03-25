# Edge Calculator & Parlay Builder

## Overview

The edge calculator compares our model predictions against PrizePicks lines to identify value plays and build optimal parlays.

## Usage

### Parlay Builder (Overs Only)
```bash
python shared/edge_calculator.py --sport nhl --parlay --overs-only
python shared/edge_calculator.py --sport nba --parlay --overs-only
```

### All Plays (Including Unders)
```bash
python shared/edge_calculator.py --sport nhl --parlay
```

### Best Plays (Top Edge)
```bash
python shared/edge_calculator.py --sport nhl --best --min-edge 10
```

### Export to CSV
```bash
python shared/edge_calculator.py --sport nhl --csv
```

## Key Concepts

### Edge Calculation
```
Edge = Our Probability - Break-Even Probability (50%)
```

For standard PrizePicks picks (no juice), break-even is 50%. 

Example: If we predict 75% probability of OVER, edge = 75% - 50% = +25%

### Confidence Tiers
| Tier | Probability | Description |
|------|-------------|-------------|
| T1-ELITE | 75%+ | Anchor legs - high probability |
| T2-STRONG | 70-75% | Core legs - balanced |
| T3-GOOD | 65-70% | Value legs - solid edge |
| T4-LEAN | 55-65% | Risk legs - use sparingly |
| T5-FADE | <55% | Avoid |

### Parlay Building Strategy

**4-Leg Parlay:**
- 1x T1-ELITE (anchor)
- 2x T2-STRONG (core)
- 1x T3-GOOD (value)

**6-Leg Parlay:**
- 2x T1-ELITE
- 2x T2-STRONG
- 2x T3-GOOD

**Tips:**
- Mix prop types (don't stack all shots)
- Spread across different games
- Focus on OVERS for parlays (use `--overs-only`)

## PrizePicks Integration

### Fetch Fresh Lines
```bash
python shared/prizepicks_client.py --sport nhl
python shared/prizepicks_client.py --sport nba
```

Lines are stored in `shared/prizepicks_lines.db` and matched to predictions by:
- Player name (fuzzy matching)
- Prop type (exact match)
- Line value (within 0.5 tolerance)

### League IDs (Updated Jan 2026)
- NHL: 8
- NBA: 7
- NFL: 9
- CBB: 20
- CFB: 15

## Output Example

```
================================================================================
  NHL PARLAY BUILDER - 2026-01-17 (OVERS ONLY)
================================================================================
  Total Available Picks: 264

  SHOTS (183 plays available)
  ----------------------------------------------------------------------------
  Player               Line              Prob     Edge   Tier
  J. Hughes            OVER 1.5        90.8%   +40.8%   T1-ELITE
  K. Kaprizov          OVER 1.5        90.8%   +40.8%   T1-ELITE
  A. Matthews          OVER 1.5        90.8%   +40.8%   T1-ELITE

  POINTS (81 plays available)
  ----------------------------------------------------------------------------
  Player               Line              Prob     Edge   Tier
  C. McDavid           OVER 0.5        88.1%   +38.1%   T1-ELITE
  M. Stone             OVER 0.5        73.1%   +23.1%   T2-STRONG
```

## Files

- `shared/edge_calculator.py` - Main edge calculation and reports
- `shared/prizepicks_client.py` - PrizePicks API client
- `shared/prizepicks_lines.db` - Stored PrizePicks lines
