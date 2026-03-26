# Hedge Bot — Real-Time Cross-Book Arbitrage & Line Trading System

## The Concept

Be the **"eye in the sky"** monitoring lines across every sportsbook simultaneously. When Book A has Team X at -3.5 (-110) and Book B has Team Y at +4.5 (-110), that's a guaranteed profit window — a **middle opportunity**. When lines move, the bot catches it before the market corrects.

This is NOT prediction — this is **sports line trading**. You're not betting on who wins. You're exploiting price discrepancies between books, the same way stock arbitrage works on Wall Street.

---

## How It Works

### Core Loop

```
Every 30 seconds:
  1. Pull lines from 20+ sportsbooks worldwide
  2. Compare all pairs for arbitrage opportunities
  3. Score each opportunity (guaranteed profit %, time window, risk)
  4. Alert user via Discord/push notification with EXACT bet amounts
  5. Track if window is still open, send "CLOSED" when it's gone
```

### Three Types of Opportunities

#### 1. Pure Arbitrage (Risk-Free)
Both sides of a bet are +EV when combined across two books.

```
Example:
  DraftKings:  Lakers ML  +150  (implied 40.0%)
  FanDuel:     Celtics ML -140  (implied 58.3%)
  Combined implied: 98.3% < 100%  →  1.7% GUARANTEED PROFIT

  Bet $100 on Lakers @ DK  →  win $250 total
  Bet $148 on Celtics @ FD →  win $253.71 total
  Total risked: $248
  Guaranteed return: $250-$253  →  $2-$5 profit NO MATTER WHAT
```

#### 2. Middle Opportunities (Low-Risk, High-Reward)
Spread discrepancy where you can win BOTH bets if the game lands in the middle.

```
Example:
  BetMGM:    Bills -3.5 (-110)
  Caesars:   Dolphins +4.5 (-110)

  If Bills win by exactly 4:
    Bills -3.5 COVERS  →  WIN
    Dolphins +4.5 COVERS  →  WIN
    BOTH BETS HIT  →  massive profit

  If any other score: one wins, one loses  →  small loss (~5% vig)
  Middle probability: ~8-12% depending on sport
  Expected value: POSITIVE even accounting for the vig on losing side
```

#### 3. Steam Chasing / Line Movement Trading
Catch a line BEFORE a book adjusts to match sharp money movement.

```
Example (time sequence):
  10:00 AM — All books have Patriots -3 (-110)
  10:02 AM — Pinnacle moves to Patriots -3.5 (-105)  [SHARP MONEY]
  10:02 AM — Bot detects: BetRivers STILL has Patriots -3 (-110)
  10:02 AM — ALERT: "BET Patriots -3 (-110) @ BetRivers — stale line"
  10:05 AM — BetRivers adjusts to -3.5  →  window closed

  You got the better number. Over thousands of bets, this prints money.
```

---

## Data Sources

### Primary: The Odds API (Already Integrated)
- 20+ US sportsbooks: DraftKings, FanDuel, BetMGM, Caesars, PointsBet, etc.
- 10+ international: Pinnacle, Bet365, William Hill, Betfair, etc.
- Supports: moneylines, spreads, totals, player props
- Free tier: 500 requests/month (need paid tier for real-time: $20-80/mo)
- Endpoint: `GET /v4/sports/{sport}/odds/?regions=us,eu,uk,au`

### Secondary: OddsJam / OddsShopper APIs
- Purpose-built for arbitrage detection
- Some have free tiers, premium at $50-100/mo
- Pre-calculated arb percentages

### Tertiary: Direct Book Scraping (Advanced)
- Some books have undocumented APIs (mobile apps use them)
- Betfair Exchange has official API (exchange = different odds structure)
- Asian books (Pinnacle, SBOBet) are sharpest — they move first

---

## Architecture

```
shared/hedge_bot/
    line_monitor.py          -- Polls odds APIs every 30-60 seconds
    arbitrage_scanner.py     -- Compares all book pairs for arb/middles
    opportunity_scorer.py    -- Ranks opportunities by profit %, confidence, time
    bet_calculator.py        -- Calculates exact bet amounts for optimal hedging
    alert_engine.py          -- Discord alerts with action details
    position_tracker.py      -- Track open positions, calculate P&L
    book_manager.py          -- Track which books user has accounts at

hedge_bot.db                 -- SQLite for opportunity history, P&L tracking
```

### Key Tables

```sql
opportunities:
    id, detected_at, sport, game, bet_type,
    book_a, line_a, odds_a,
    book_b, line_b, odds_b,
    arb_type (pure_arb | middle | steam),
    profit_pct REAL,
    optimal_bet_a REAL, optimal_bet_b REAL,
    window_seconds INTEGER,    -- How long the opportunity lasted
    status (open | closed | executed)

positions:
    id, opportunity_id, book, bet_side, line, odds, amount,
    result (pending | won | lost | push),
    pnl REAL

daily_pnl:
    date, opportunities_found, opportunities_executed,
    gross_profit, total_risked, roi_pct
```

---

## Alert Format (Discord)

```
--- ARBITRAGE ALERT ---

Type: PURE ARB (1.7% guaranteed)
Game: LAL vs BOS — tonight 7:30 PM ET

  Book A: DraftKings   — Lakers ML    +150
  Book B: FanDuel      — Celtics ML   -140

  Optimal bets ($500 bankroll):
    $200.00 on Lakers ML  @ DraftKings
    $296.30 on Celtics ML @ FanDuel
    Total risked: $496.30
    Guaranteed return: $500.00 - $504.55
    Guaranteed profit: $3.70 - $8.25

  Window detected: 12 seconds ago
  Historical avg window: 3-8 minutes

  ACT FAST — windows close quickly
---
```

```
--- MIDDLE ALERT ---

Type: SPREAD MIDDLE (3.2% middle probability)
Game: BUF vs MIA — Sunday 1:00 PM ET

  Leg 1: BetMGM     — Bills -2.5    (-110)
  Leg 2: Caesars     — Dolphins +3.5 (-108)

  If Bills win by exactly 3: BOTH BETS WIN (+$400 on $220 risk)
  If any other score: lose ~$10-12 (one wins, one loses)

  Expected value: +$5.80 per attempt
  Middle lands ~8% of the time in NFL
---
```

```
--- STEAM ALERT ---

Sharp money detected — STALE LINE available

  Pinnacle moved: Bucks -4.5 → Bucks -5.5 (2 min ago)
  STILL AVAILABLE: BetRivers has Bucks -4.5 (-110)

  Action: BET Bucks -4.5 @ BetRivers NOW
  Edge: ~2% CLV (getting a full point better than sharp price)

  Confidence: HIGH (Pinnacle origination = sharp signal)
---
```

---

## Bet Calculator Logic

### Pure Arbitrage

```python
def calculate_arb(odds_a, odds_b, bankroll):
    """
    odds in American format (+150, -140)
    Returns optimal bet sizes for guaranteed profit.
    """
    # Convert to decimal odds
    dec_a = american_to_decimal(odds_a)  # +150 → 2.50
    dec_b = american_to_decimal(odds_b)  # -140 → 1.714

    # Check if arb exists
    implied_total = (1/dec_a) + (1/dec_b)  # Must be < 1.0
    if implied_total >= 1.0:
        return None  # No arb

    profit_pct = (1 - implied_total) * 100  # e.g., 1.7%

    # Optimal bet sizing
    bet_a = bankroll / (dec_a * implied_total)
    bet_b = bankroll / (dec_b * implied_total)

    return {
        "profit_pct": profit_pct,
        "bet_a": round(bet_a, 2),
        "bet_b": round(bet_b, 2),
        "guaranteed_return": round(bet_a * dec_a, 2),
    }
```

### Middle Probability

```python
def middle_probability(spread_a, spread_b, sport):
    """
    Probability that the final margin lands between two spreads.
    Uses sport-specific standard deviations for margin of victory.
    """
    sport_stdev = {"nfl": 13.5, "nba": 11.8, "nhl": 2.4, "mlb": 3.8}
    stdev = sport_stdev.get(sport, 10)

    gap = abs(spread_a) - abs(spread_b)  # e.g., 4.5 - 3.5 = 1.0
    # Probability of landing in the 1-point middle
    # Using normal distribution CDF
    from scipy.stats import norm
    prob = norm.cdf(gap / stdev)  # Simplified
    return prob
```

---

## Realistic Expectations

### The Good
- Pure arb is **mathematically guaranteed profit** — no prediction needed
- Middles have **positive expected value** even when they don't hit
- Steam chasing is the **#1 strategy used by professional bettors**
- This is legal in all US states where sports betting is legal
- Cross-book monitoring at scale is a genuine competitive advantage

### The Challenges
- **Speed**: Arb windows last 30 seconds to 5 minutes. Need near-real-time data.
- **Limits**: Books limit/ban winning bettors. Need multiple accounts.
- **Vig erosion**: Small arbs (1-2%) get eaten by vig if not careful.
- **Capital**: Need bankroll spread across 5-10 books minimum.
- **Data cost**: Real-time odds from 20+ books = $50-200/month in API costs.

### The Numbers (Realistic)
- Pure arbs appear: 5-15 per day across all sports (US books)
- Average arb profit: 1-3% per opportunity
- Average middle profit: 0.5-1.5% per attempt (factoring in miss rate)
- Steam opportunities: 20-50 per day (but smaller individual edge)
- Monthly ROI on capital deployed: 3-8% (conservative estimate)
- Key insight: This scales with bankroll. $10k across 5 books = $300-800/month

---

## Phase Plan

### Phase A: MVP (Line Monitor + Arb Scanner)
- [ ] Poll The Odds API every 60 seconds for all active games
- [ ] Compare all book pairs for pure arb opportunities
- [ ] Calculate optimal bet sizes
- [ ] Discord alert when arb > 1%
- [ ] Track opportunity history in SQLite

### Phase B: Middles + Steam
- [ ] Detect spread/total discrepancies between books
- [ ] Calculate middle probability using sport-specific distributions
- [ ] Track line movement velocity (detect steam moves)
- [ ] Alert on stale lines (one book hasn't moved when others have)

### Phase C: Intelligence Layer
- [ ] Learn which books are slowest to adjust (best targets for steam)
- [ ] Track average window duration per book pair
- [ ] User's book portfolio: only alert for books they have accounts at
- [ ] Position management: track open positions, net exposure

### Phase D: Dashboard Tab
- [ ] "Hedge Bot" tab on dashboard showing live opportunities
- [ ] Historical P&L tracking with equity curve
- [ ] Book-by-book performance
- [ ] Heat map of which book pairs produce most arbs

---

## Integration Points

- Uses existing The Odds API integration (already have ODDS_API_KEY)
- Uses existing Discord webhook infrastructure
- Runs as separate process alongside orchestrator (doesn't interfere with picks)
- Dashboard tab alongside Game Lines and Props tabs
- Could eventually feed line movement data INTO prediction models (Bot C: The Contrarian)

---

## Legal Note

Sports arbitrage is 100% legal. Books don't like it (they may limit accounts), but
it is not illegal, not fraud, and not against any law. It's simply shopping for the
best price — the same thing consumers do with any product.

The key risk is account limiting/closing by individual books, not legal risk.
Mitigation: spread action across many books, don't hit the same arb at the same
book repeatedly, mix in recreational bets.
