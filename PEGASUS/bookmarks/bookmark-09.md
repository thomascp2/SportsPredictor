# PEGASUS Bookmark — Session 9
**Date: 2026-04-15**

---

## Completed This Session

- [x] `PEGASUS/pipeline/prizepicks_client.py` — Step 9a (in-memory PP line fetcher)
- [x] `PEGASUS/pipeline/odds_client.py` — Step 9b (The Odds API client + math utilities)
- [x] `PEGASUS/pipeline/pick_selector.py` — added `implied_probability` + `true_ev` to PEGASUSPick
- [x] `PEGASUS/sync/turso_sync.py` — added `implied_probability` + `true_ev` columns
- [x] `PEGASUS/bookmarks/bookmark-09.md` (this file)
- [x] `PEGASUS/bookmarks/comprehensive_summary.md` — updated

No production files modified. Rule 2 intact.

---

## Files Created / Modified This Session

```
PEGASUS/pipeline/prizepicks_client.py  (NEW — Step 9a)
PEGASUS/pipeline/odds_client.py        (NEW — Step 9b)
PEGASUS/pipeline/pick_selector.py      (MODIFIED — implied_probability + true_ev fields)
PEGASUS/sync/turso_sync.py             (MODIFIED — two new columns)
PEGASUS/bookmarks/bookmark-09.md       (NEW — this)
PEGASUS/bookmarks/comprehensive_summary.md (UPDATED)
```

---

## prizepicks_client.py Architecture

### Purpose
Live PP line fetcher for PEGASUS. No SQLite dependency. Pure in-memory cache per process.

### Key API
```python
from PEGASUS.pipeline.prizepicks_client import get_lines, get_all_lines, match_pick, detect_line_movement

# Fetch for one sport (cached per session)
lines = get_lines("nba", "2026-04-15")   # dict[norm_key, PPLine]

# All three sports merged
all_lines = get_all_lines("2026-04-15")

# Match a PEGASUSPick to a live PP line (handles name normalization + initials)
pp_line = match_pick(pick, lines)

# Detect if PP moved the line since orchestrator ran pp-sync
delta = detect_line_movement(pick, lines)  # +0.5 = line moved up
```

### PPLine dataclass
```python
PPLine(player_name, prop, line, odds_type, sport, start_time, raw_stat_type, is_promo)
```

### Key design choices
- Name normalization: strips diacritics, lowercases, collapses whitespace
- Initial abbreviation matching: "A. Fox" → "Adam Fox" (same logic as discord_bot)
- Dual endpoints: partner-api → api fallback (same as production)
- Rate limiting: 2s between requests, 3 retries per endpoint

---

## odds_client.py Architecture

### Purpose
The Odds API integration. Math utilities are always available (no key needed).
Game-level data uses free tier. Player prop implied probability requires paid plan.

### Math utilities (no key required)
```python
from PEGASUS.pipeline.odds_client import american_to_implied, implied_to_american, remove_vig, true_ev_from_prob

american_to_implied(-110)        # → 0.5238
american_to_implied(+130)        # → 0.4348
remove_vig(-110, -110)           # → (0.5, 0.5) fair probs
true_ev_from_prob(0.72, 0.54)   # → 0.333 (+33.3% edge vs market)
```

### Odds API call budget (monthly)
See "Odds API Call Budget" section below.

### Player prop implied probability (paid tier)
```python
from PEGASUS.pipeline.odds_client import get_implied_probability
impl = get_implied_probability("Kawhi Leonard", "pts_asts", "nba", "2026-04-15", "UNDER")
# → 0.54 if available, None if no key / free tier / player not found
```

### ODDS_API_KEY env var
Add to `.env` or `start_orchestrator.bat`. When not set, everything returns None gracefully.

---

## Odds API Call Budget

| Use case                     | Calls/day | Calls/month |
|------------------------------|-----------|-------------|
| Game totals (free tier)      | 3         | 90          |
| Event list (1 per sport/day) | 3         | 90          |
| Player prop odds (per game)  | ~27       | ~810        |
| **Total w/ player props**    | **~33**   | **~900+**   |

**Free tier (500 req/month):** Sufficient for game totals only. Player props will exhaust quota.

**Recommendation: Starter plan (~$10/month, 400 req/day / ~12k/month)**
- Covers all three sports × all games × player props with room to spare
- The Odds API: https://the-odds-api.com/pricing

**To activate player props:** 
1. Get Starter plan API key
2. Set `ODDS_API_KEY=<key>` in `.env` / `start_orchestrator.bat`
3. `implied_probability` will auto-populate on PEGASUSPick; Turso `pegasus_picks` table already has the column

---

## PEGASUSPick Changes

### New fields
```python
implied_probability: Optional[float] = None   # from sportsbook (None until paid API key)
true_ev:             float            # computed: (calibrated_prob / break_even) - 1
usage_boost:         bool             # computed: situation_flag == "USAGE_BOOST"
```

### true_ev examples
- calibrated_prob=0.85, break_even=0.5238 (std) → true_ev = +0.622 (+62.2%)
- calibrated_prob=0.72, break_even=0.5238 → true_ev = +0.374 (+37.4%)
- calibrated_prob=0.55, break_even=0.5238 → true_ev = +0.050 (+5.0%)

### Display formula (once implied_probability is live)
```
Model: {calibrated_prob:.0%} | Book: {implied_probability:.0%} | Edge: {ai_edge:+.1f}%
```

---

## turso_sync.py Changes

Added two columns to `pegasus_picks` table DDL and upsert:
- `implied_probability REAL` — null until Odds API paid plan active
- `true_ev REAL` — computed from calibrated_prob / break_even - 1

Since turso_sync uses `INSERT OR REPLACE`, the DDL change will NOT auto-migrate
existing rows on Turso. First sync after this change may fail if the table was
already created without these columns. Fix: drop and recreate the Turso table
(or add columns manually via Turso console: `ALTER TABLE pegasus_picks ADD COLUMN implied_probability REAL`).

---

## Known Issues (carried forward)

1. `no such column: minutes_played` — USAGE_BOOST in NBA situational intel. Pre-existing.
2. Unicode `→` renders as `?` on Windows cp1252 — cosmetic only.
3. MLB Turso smart-picks silent failure (production, not PEGASUS) — carry to future investigation.
4. `pegasus_picks` Turso table schema change (added implied_probability + true_ev) — may need
   manual ALTER TABLE on Turso if table was already created by Step 8 sync.

---

## Exact Next Step (start of Session 10)

**Step 10: API + Mobile**

```
1. FastAPI endpoints in PEGASUS/api/ serving enriched pick data
2. Mobile pick card redesign: tier colors, edge display, calibrated vs raw prob
3. Performance screen with calibration chart
```

Read first in Session 10:
1. `PEGASUS/bookmarks/bookmark-09.md` (this file)
2. `PEGASUS/bookmarks/comprehensive_summary.md`
3. `PEGASUS/PLAN.md` Step 10 section
4. `mobile/src/` — current screen structure

Gate: Steps 1-9 must be validated before mobile changes ship to users.

---

## Prompt for Session 10 Agent

```
I'm continuing work on PEGASUS — a parallel read-only prediction system built on top
of the existing SportsPredictor orchestrator. PEGASUS lives entirely in PEGASUS/ and
never modifies existing files outside that directory (Rule 2).

Start by reading:
1. PEGASUS/bookmarks/bookmark-09.md — session 9 results + exact next steps
2. PEGASUS/bookmarks/comprehensive_summary.md — full project context
3. PEGASUS/PLAN.md Step 10 section
4. mobile/src/ directory structure

Steps 1-9 complete. Today's task is Step 10: API + Mobile.

Build PEGASUS/api/ FastAPI endpoints, then design the mobile pick card update.

Do NOT touch: orchestrator.py, sync/turso_sync.py, shared/*, or any file outside PEGASUS/
(except mobile/src/ changes which are explicitly in scope for Step 10).
```
