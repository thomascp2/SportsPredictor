# Alternative Models Research — TODO

## The Idea

Create multiple "bot clones" — same infrastructure, same pipeline, but each one uses **different feature sets** to find edges the market isn't pricing in. The standard model uses conventional stats. These alternatives hunt for unconventional, qualitative, and non-obvious signals.

---

## Research Tasks

### 1. Unconventional / Qualitative Features to Investigate

These are signals most models ignore. Research feasibility and data sources for each:

**Human / Psychological Factors:**
- [ ] Coach challenge/timeout tendencies in close games (aggressive vs conservative)
- [ ] Team chemistry indicators — new acquisitions vs long-tenured rosters
- [ ] "Revenge game" factor — team/player facing former team
- [ ] Lookahead/letdown spots — big game tomorrow, trap game today
- [ ] Post-blowout response — how teams bounce back after 20+ pt loss
- [ ] National TV game performance splits (players who show up vs shrink)
- [ ] Post-All-Star break performance patterns
- [ ] Day-after-travel-day performance (not just B2B, but long road trips day 4+)
- [ ] "Schedule loss" — 3rd game in 4 nights on the road against a rested team
- [ ] Emotional spot detection — after a big rival win, after clinching/elimination

**Referee/Umpire Signals:**
- [ ] Home plate umpire strike zone size (K rate, walk rate impact on totals)
- [ ] NBA ref foul tendencies — total fouls called per game, FT rate impact
- [ ] NHL ref penalty frequency — impacts PP/PK-heavy teams disproportionately
- [ ] Umpire/ref crew travel schedule (tired crews = more/fewer calls?)

**Environmental / Situational:**
- [ ] Barometric pressure changes (proven link to HR rates in baseball)
- [ ] Dew point / humidity effects on ball carry (MLB)
- [ ] Wind direction relative to batter orientation (already in park_factors, enhance it)
- [ ] Ice quality — early vs late season, back-to-back home games (NHL)
- [ ] Indoor arena temperature/humidity variance
- [ ] Time-of-day effects — noon games vs 7pm vs 10pm starts
- [ ] Day-of-week patterns (Tuesday NHL games = lower totals?)

**Roster / Lineup Depth:**
- [ ] Minutes concentration index — are starters playing 38+ min (fatigue risk)
- [ ] Bench unit net rating vs starters (depth score)
- [ ] Injury cascade effect — when Player A is out, how does Player B's production change
- [ ] Lineup combination tracking — certain 5-man units that are +15 or -10 per 100
- [ ] Starter vs backup goalie splits (NHL — this is huge)
- [ ] Bullpen usage in last 3 days (MLB — overworked pen = totals over)

**Market / Betting Signals:**
- [ ] Closing line value (CLV) — the #1 predictor of long-term profit per research
- [ ] Reverse line movement — line moves opposite to public betting %
- [ ] Steam moves — sudden sharp money causing rapid line changes
- [ ] Overnight line movement (Asian books open first)
- [ ] Opening line origination — which book set the opener, how far has it moved
- [ ] Total handle distribution — where the big money is going
- [ ] Prop-to-game correlation — if player props imply higher team totals than the posted total

**Advanced / Derived Metrics:**
- [ ] Pythagorean win expectation vs actual record (lucky vs unlucky teams regress)
- [ ] Strength of schedule (SOS) — weighted by recency
- [ ] Four factors analysis (NBA: eFG%, TOV%, ORB%, FT rate)
- [ ] Expected goals (xG) for NHL — shot quality over shot quantity
- [ ] DVOA/efficiency equivalent for each sport
- [ ] Pace-adjusted stats vs raw stats (huge for NBA totals)
- [ ] Clutch performance index — how team performs in close games vs blowouts

### 2. Bot Clone Variations to Build

Each clone uses the same pipeline but swaps in different feature sets:

- [ ] **Bot A: "The Quant"** — Pure numbers. Traditional stats + Elo + market data. No qualitative. This is our baseline.
- [ ] **Bot B: "The Situationist"** — Rest, travel, schedule spots, revenge games, lookahead/letdown, emotional factors. Minimal traditional stats.
- [ ] **Bot C: "The Contrarian"** — CLV, reverse line movement, public %, steam moves. Bets against the public when sharp signals align.
- [ ] **Bot D: "The Matchup Nerd"** — Lineup-specific data, goalie/pitcher matchups, pace differentials, four factors. Deep on the X's and O's.
- [ ] **Bot E: "The Weather Witch"** — (MLB-heavy) Weather, barometric pressure, altitude, wind, park factors, dome vs open. Environmental edge hunter.
- [ ] **Bot F: "The Kitchen Sink"** — Everything from all bots combined. Let XGBoost feature-select what matters.
- [ ] **Bot G: "The Ensemble"** — Meta-learner that takes predictions from Bots A-F as inputs and learns which bot to trust in which situations.

### 3. Comparison Framework

- [ ] Design A/B tracking system — all bots predict the same games, track independently
- [ ] Build comparison dashboard tab showing each bot's accuracy, ROI, and Brier score
- [ ] Identify "convergence plays" — games where 4+ bots agree (likely highest edge)
- [ ] Track feature importance across bots — which unconventional features actually matter
- [ ] Monthly variance analysis — which bots are consistent vs streaky

### 4. Data Sources to Research

- [ ] Pinnacle opening/closing lines (free historical data?)
- [ ] Action Network or similar for public betting % and line movement
- [ ] Basketball Reference / Hockey Reference for advanced splits
- [ ] Statcast / Baseball Savant for pitch-level and batted ball data
- [ ] Open-Meteo for barometric pressure, dew point (already integrated for temp/wind)
- [ ] NBA.com/stats for lineup combination data
- [ ] MoneyPuck for NHL expected goals (xG)
- [ ] Referee assignment data (NBA ref assignments posted day-of)

### 5. Academic Papers to Read

- [ ] "Beating the NFL Football Point Spread" — Boulier & Stoll (original ATS research)
- [ ] "Testing Market Efficiency in the NFL" — Dare & MacDonald
- [ ] "The Closing Line Value" — Pinnacle blog series (practical CLV implementation)
- [ ] "Rest and NBA Performance" — multiple papers on B2B effects
- [ ] "Home Court Advantage in the NBA" — Jamieson (2010)
- [ ] FiveThirtyEight Elo methodology documentation
- [ ] "Predicting MLB Game Outcomes" — various Kaggle competition write-ups
- [ ] Any Sloan Sports Analytics Conference papers on game prediction

---

## Priority Order

1. Build standard model first (Phase 1-4 of main plan) — **IN PROGRESS**
2. Research data availability for unconventional features
3. Build Bot B (Situationist) first — easiest unconventional data to collect
4. Build Bot C (Contrarian) — needs betting market data API
5. Build comparison framework
6. Iterate on remaining bots based on what data is actually available
7. Build Bot G (Ensemble) once we have 3+ bots generating predictions

## Notes

- Don't hardcode feature weights — let ML discover them from data
- Using expert research to choose WHICH features to include is smart (not overfitting)
- Overfitting = tuning weights to match your small dataset too closely
- The goal: find features the market underprices, not just replicate what Vegas already knows
- "Be the best like no one ever was" = find the signals others aren't looking at
