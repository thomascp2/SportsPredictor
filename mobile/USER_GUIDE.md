# SportsPredictor Mobile App - User Guide

## Overview

SportsPredictor is a mobile app that provides AI-powered sports betting predictions for NBA and NHL games. The app features live scoreboards, smart picks with probability calculations, a visual parlay builder with EV (Expected Value) calculations, and comprehensive performance tracking.

---

## Features

### 1. Live Scores Tab
View real-time scores for NBA and NHL games.

- **Toggle between sports** using the NBA/NHL selector at the top
- **Live games** show a pulsing red "LIVE" indicator
- **Scheduled games** show the start time
- **Final games** show "FINAL" with the final score
- **Auto-refresh** every 30 seconds

### 2. Smart Picks Tab
Today's AI-generated predictions with PrizePicks lines.

Each pick card shows:
- **Player name** and matchup (Team vs Opponent)
- **Prop type** (e.g., Points, Rebounds, Shots)
- **Prediction** (OVER/UNDER) with the line
- **Probability** - our model's confidence (displayed as percentage and visual bar)
- **Edge** - advantage over break-even point
- **Tier badge** - confidence level:
  - **T1** (Gold): Elite picks, 75%+ probability
  - **T2** (Green): Strong picks, 70-75%
  - **T3** (Blue): Good picks, 65-70%
  - **T4** (Orange): Lean picks, 55-65%
  - **T5** (Red): Fade/avoid, below 55%
- **Odds type badge** - Goblin (easier), Standard, or Demon (harder)
- **"+ Parlay" button** - tap to add pick to your parlay

### 3. Parlay Builder Tab
Build and analyze parlays with real-time EV calculations.

**Your Parlay Slip:**
- Shows all picks you've added
- Tap **G/S/D** buttons to change odds type (Goblin/Standard/Demon)
- Shows leg value for each pick (Goblin=0.5L, Standard=1L, Demon=1.5L)
- Tap **X** to remove a pick
- Tap **Clear All** to start over

**EV Calculator:**
- **Total Legs** - sum of leg values
- **Payout** - multiplier based on total legs
- **Win Probability** - combined probability of all picks hitting
- **EV Percentage** - Expected Value (positive = profitable long-term)
- **Recommendation** - EXCELLENT VALUE, STRONG VALUE, GOOD VALUE, SLIGHT VALUE, MARGINAL, or AVOID

**Payout Reference:**
| Legs | Payout |
|------|--------|
| 2    | 3x     |
| 3    | 5x     |
| 4    | 10x    |
| 5    | 20x    |
| 6    | 25x    |

**Leg Values:**
- **Goblin** = 0.5 legs (easier line, lower payout)
- **Standard** = 1.0 legs (normal)
- **Demon** = 1.5 legs (harder line, higher payout)

### 4. Stats Tab (Performance)
Track system accuracy over time.

- **Overall Accuracy** - total hit rate across all predictions
- **OVER/UNDER breakdown** - separate accuracy for each prediction type
- **By Prop Type** - accuracy broken down by prop (Points, Rebounds, Shots, etc.)
- **By Confidence Tier** - accuracy for each tier level (NHL only)
- **Recent Days** - daily accuracy trend for the last 7-14 days

### 5. Search Tab
Find any player's prediction history.

- Enter at least 2 characters to search
- Results show:
  - Player name
  - Sport (NBA/NHL badge)
  - Total predictions made
  - Overall accuracy percentage
  - Last game date

---

## Understanding the Math

### Expected Value (EV)
EV measures the long-term profitability of a bet.

```
EV = (Win Probability × Payout) - 1
```

- **Positive EV (+)** = Profitable long-term
- **Negative EV (-)** = Unprofitable long-term

**Example:**
- 4 picks at 70% each = 24% combined probability
- 4 standard legs = 10x payout
- EV = (0.24 × 10) - 1 = **+140%** (Excellent!)

### Break-Even Probability
The minimum win rate needed to break even:

```
Break-Even = 1 / Payout
```

| Legs | Payout | Break-Even |
|------|--------|------------|
| 2    | 3x     | 33.3%      |
| 3    | 5x     | 20.0%      |
| 4    | 10x    | 10.0%      |
| 5    | 20x    | 5.0%       |
| 6    | 25x    | 4.0%       |

### Edge
Edge = Your probability - Break-even probability

A positive edge means you have an advantage.

---

## Tips for Success

1. **Focus on T1/T2 picks** - These have the highest probability and historically best accuracy
2. **Check the edge** - Higher edge = more value
3. **Mix goblin picks** - Adding goblins reduces total legs while keeping probability high
4. **Target +30% EV or higher** - This is considered strong value
5. **UNDER picks historically outperform** - Our models show ~74% UNDER accuracy vs ~57% OVER for NHL
6. **Check game times** - Make sure games haven't started before placing picks

---

## Troubleshooting

### "Network Error" on all screens
- Make sure the API server is running (see Quick Start Guide)
- Check that your phone and PC are on the same WiFi network
- Verify the API URL in `mobile/src/utils/constants.ts` matches your PC's IP

### Scores not updating
- Pull down to refresh
- Check if API server is still running
- Try switching sports and back

### Picks not loading
- Picks are only available on game days
- Try pulling down to refresh
- Check API server logs for errors

### App crashes on load
- Close and reopen Expo Go
- Try `npx expo start --clear` to clear cache
- Check for JavaScript errors in the Expo terminal

---

## Version History

- **v1.0.0** (January 2026) - Initial release
  - Live NBA/NHL scoreboards
  - Smart picks with tier system
  - Visual parlay builder with EV calculations
  - Performance tracking dashboard
  - Player search functionality
