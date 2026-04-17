# PEGASUS Bookmark -- Session 13 (End-of-Session)
**Date: 2026-04-15 | Steps 1-10 COMPLETE + MLB Game Context LIVE | Step 11 Split (11a=Jun 2026, 11b=Oct 2026)**

---

## What Was Done in Session 13

| Sub-step | File(s) | Summary |
|---|---|---|
| MLB Game Context | `PEGASUS/pipeline/mlb_game_context.py` | NEW -- park factors (32 stadiums), wind advisory, game total advisory |
| pick_selector wiring | `PEGASUS/pipeline/pick_selector.py` | New `game_context_flag` + `game_context_notes` fields on PEGASUSPick; `_get_game_context()` called for all MLB picks |
| Turso sync | `PEGASUS/sync/turso_sync.py` | Added `game_context_flag` + `game_context_notes` columns to DDL + upsert |
| Expo fix | `mobile/app.json` | Slug changed from `freepicks` to `freepicks-sportspredictor` to prevent slug collision with old app |

---

## MLB Game Context -- Full Details

### File: `PEGASUS/pipeline/mlb_game_context.py`

**Data sources (read-only):**
- `mlb/database/mlb_predictions.db` -- `game_context` table (live weather + game totals)
- Static park factor table (baked in code -- no DB dependency)

**game_context table status (as of 2026-04-15):**
- 273 rows | 22 dates | collecting since 2026-03-25
- 15 games/day during full slate | avg 12.4 games/day overall
- Captures: venue, home/away starters, game_total (Vegas O/U), temperature, wind_speed, wind_direction, conditions, day_night

**Today's games (2026-04-15) -- flag examples:**

| Game | Venue | O/U | Wind | Flag fired |
|---|---|---|---|---|
| NYY vs LAA | Yankee Stadium | 10.5 | 6mph L-R | HIGH_TOTAL |
| PIT vs WSH | PNC Park | 9.5 | 7mph Out | HIGH_TOTAL |
| CIN vs SF | Great American Ball Park | 9.5 | 7mph R-L | HIGH_TOTAL |
| ATH vs TEX | Sutter Health Park | 9.5 | 5mph Calm | HIGH_TOTAL |
| MIL vs TOR | American Family Field | 7.5 | Dome | LOW_TOTAL |
| CWS vs TB | Rate Field | 8.0 | 9mph In | (no HR game today) |

**Today's flag distribution across 168 smart picks:**
- HIGH_TOTAL: 41 picks
- HITTER_PARK: 2 picks
- NEUTRAL: 125 picks

### Park Factor Table (32 stadiums)

Factors represent multi-year park-adjusted run environment (Baseball Reference 3-year avg through 2025).

**HR-friendly (hr_factor >= 1.10):**
- Coors Field: hr=1.35, hit=1.14 (extreme -- all props boosted)
- Great American Ball Park: hr=1.22
- Citizens Bank Park: hr=1.18
- Yankee Stadium: hr=1.17
- Globe Life Field: hr=1.10 (retractable dome)
- Truist Park: hr=1.10

**Pitcher parks / HR-suppressing (hr_factor <= 0.88):**
- Oracle Park (SF): hr=0.76, hit=0.94 (most extreme suppressor)
- Petco Park (SD): hr=0.83, hit=0.95
- Dodger Stadium / UNIQLO Field: hr=0.88
- loanDepot park (MIA): hr=0.85, dome
- Comerica Park (DET): hr=0.87

**Hit-friendly (hit_factor >= 1.08):**
- Coors Field: 1.14
- Fenway Park: 1.10

### Flag Logic Summary

```
HR prop:
  HR_BOOST  if (park hr_factor >= 1.05 AND outbound wind >= 8mph)
         OR (park hr_factor >= 1.15, no wind needed)
  HR_SUPPRESS if (wind blowing IN >= 8mph AND park hr_factor <= 1.05)
           OR (park hr_factor <= 0.85)

hits / total_bases:
  HITTER_PARK  if park hit_factor >= 1.08
  PITCHER_PARK if park hit_factor <= 0.93

strikeouts / outs_recorded:
  PITCHER_PARK if park k_factor >= 1.04

All props (fallback):
  HIGH_TOTAL if game O/U >= 9.5
  LOW_TOTAL  if game O/U <= 7.0

Dome parks: wind irrelevant, park factor still applies
```

### Caveats / Known Limitations
1. `opposing_pitcher_hand` column in player_game_logs is 100% empty -- never populated. Batter handedness splits not possible with current data.
2. game_context has 273 rows (since Mar 25). Not enough for ML training yet -- advisory flags only.
3. BAL vs AZ today has game_total=None (not yet posted) -- correctly returns NEUTRAL.
4. Park name changes (Minute Maid -> Daikin Park, Dodger Stadium -> UNIQLO Field) handled via direct table entries + partial match fallback.

---

## Expo App Fix

**Problem:** `npx expo start` from `mobile/` opened a DIFFERENT FreePicks app (older project). Caused by slug collision -- Expo Go matches projects by slug, and the old project also used `slug: "freepicks"`.

**Fix:** `mobile/app.json` slug changed from `"freepicks"` to `"freepicks-sportspredictor"`.

**Run command (first time after fix):**
```
cd C:\Users\thoma\SportsPredictor\mobile
npx expo start --clear
```
The `--clear` flushes Metro bundler cache. After that, `npx expo start` alone is fine.

If Expo Go still shows the old app: open Expo Go on phone, long-press the old FreePicks project, tap "Remove project", then re-scan.

---

## Step 11 -- Revised Plan (SPLIT into 11a and 11b)

The original Step 11 was one monolithic "Game Lines ML" task gated until Oct 2026. Now split:

### Step 11a -- MLB Game Context ML (Target: June 2026)

**Why sooner:** MLB game_context table has been collecting since Mar 25. By June 1 we'll have ~700 rows with outcomes. Enough to build a simple model or validate advisory flag accuracy.

**Calendar:**
- **May 15, 2026**: game_context reaches ~450 rows. Run accuracy check: do HIGH_TOTAL games actually produce more counting stats? Do HR_SUPPRESS games actually suppress HR? Validate advisory flags empirically.
- **June 1, 2026**: ~700 rows. Build Step 11a XGBoost if validation shows game_total and park factor are predictive. Target: `game_context_score` feature that adjusts the advisory from a binary flag to a continuous modifier (0.8-1.2x).
- **October 1, 2026**: ~2,500 rows (full season). Full refit with complete 2026 season.

**What Step 11a builds:**
- XGBoost model: inputs = game_total, park_hr_factor, wind_speed, wind_out_bool, temperature, home_away
- Output: P(stat > line) adjustment factor per prop type
- Calibrate with temporal 4-way split (same as MLB player props)
- Integrate as `game_context_score` in pick_selector -- replaces binary flag with continuous modifier
- PEGASUS shadow audit required before activating as a probability modifier

**Note:** Step 11a advisory flags (current implementation) are ALREADY LIVE. The June milestone upgrades them from static rules to data-driven scores.

### Step 11b -- NBA/NHL Game Lines ML (Target: October 2026)

**Why Oct 2026:** NBA and NHL game_context collection started in March 2026 (late in the season). Need full 2026-27 season data.

**Calendar:**
- **April 18, 2026**: NHL regular season ends. ~30 game-days of NHL context data collected this season.
- **April 19, 2026**: NHL playoffs begin. HIGH_STAKES already fires via situational intel -- no change needed.
- **Mid-June 2026**: NBA Finals end. NBA/NHL playoff context not useful for prop ML (small/unusual sample).
- **October 7, 2026** (approx): NHL/NBA 2026-27 seasons begin.
- **October 2026 (same week as NHL/NBA retrain):**
  - Retrain NHL player prop models (stat_v2.2_asym clean data -- 6,400+ per combo)
  - Retrain NBA player prop models (full 2025-26 season clean data)
  - Begin collecting NBA/NHL game_context for 2026-27
- **April 2027**: ~1,200 NBA game_context rows, ~1,000 NHL rows. Train Step 11b.

**What Step 11b builds:**
- XGBoost for NBA: inputs = game pace (Vegas total), back-to-back flag, home/away, rest days
- XGBoost for NHL: inputs = game total (puck line), back-to-back, home ice, travel
- Same advisory pattern as Step 11a: `game_context_flag` + eventual `game_context_score`
- PEGASUS shadow audit required before activating

---

## Calendar Summary (put these on the calendar)

| Date | Action | Priority |
|---|---|---|
| **Apr 18, 2026** | NHL regular season ends. Confirm USE_ML=False holds for playoffs. | Done passively |
| **Apr 19, 2026** | NHL playoffs begin. HIGH_STAKES situational intel auto-fires. | Watch |
| **May 15, 2026** | game_context ~450 rows. **Validate Step 11a advisory flag accuracy.** | HIGH |
| **Jun 1, 2026** | game_context ~700 rows. **Build Step 11a XGBoost if validation passes.** | HIGH |
| **Mid-Jun 2026** | NBA Finals + NHL Stanley Cup end. All situational intel normalizes. | Watch |
| **Oct 7, 2026** | NHL/NBA seasons open. **Trigger Oct retrain (NHL + NBA player props).** | CRITICAL |
| **Oct 2026** | Collect first NBA/NHL game_context for 2026-27. Plant seed for Step 11b. | Medium |
| **Apr 2027** | ~1,200 NBA + 1,000 NHL game_context rows. **Build Step 11b.** | Future |

---

## Open Issues (updated Session 13)

| # | Issue | Severity | Status |
|---|---|---|---|
| 1 | `minutes_played` bug in intel.py | Low | Fixed Session 11 |
| 2 | `pegasus_picks` Turso missing implied_probability/true_ev columns | Med | Run ALTER TABLE if needed |
| 3 | DK rate-limit on 3-sport runs | Low | Non-fatal, existing |
| 4 | NHL hits/blocked_shots not generating | Low | Next season |
| 5 | MLB Turso smart-picks silent failure (production) | Low | Investigate when relevant |
| 6 | shots 2.5/3.5 OVER suppression guard (Oct 2026) | Med | Planned for Oct retrain prep |
| 7 | shots 0.5 data-starved (117 samples) | Low | Stat-only permanently |
| 8 | Expo slug collision | Fixed | Slug changed to freepicks-sportspredictor |
| 9 | `opposing_pitcher_hand` empty -- handedness splits not possible | Low | Would need ESPN/Statcast enrichment |
| 10 | BAL vs AZ game_total=None today (not yet posted at pipeline time) | Low | Returns NEUTRAL gracefully |
| 11 | game_context Turso columns need ALTER TABLE on existing table | Med | Add game_context_flag/notes if sync errors |

### Turso migration note (Issue #11)
If the `pegasus_picks` Turso table was created before Session 13, run on Turso console:
```sql
ALTER TABLE pegasus_picks ADD COLUMN game_context_flag TEXT DEFAULT 'NEUTRAL';
ALTER TABLE pegasus_picks ADD COLUMN game_context_notes TEXT DEFAULT '';
```

---

## Prompt for Session 14 Agent

```
I'm continuing work on PEGASUS -- a parallel read-only prediction system built on top
of the existing SportsPredictor orchestrator. PEGASUS lives entirely in PEGASUS/ and
never modifies existing files outside that directory (Rule 2).

Steps 1-10 are COMPLETE. Session 11: mobile wiring. Session 12: NHL counterfactual analysis.
Session 13: MLB game context advisory (park factors, wind, game total) + Expo slug fix.

Start by reading:
1. PEGASUS/bookmarks/bookmark-13.md -- current state + calendar plan
2. PEGASUS/bookmarks/comprehensive_summary.md -- full project context

Step 11 is now SPLIT:
  11a: MLB Game Context ML -- target June 1, 2026 (validate flags May 15)
  11b: NBA/NHL Game Lines ML -- target April 2027

Recommended work for this session (discuss with user):

A. Step 11a validation prep -- write PEGASUS/analytics/validate_game_context.py
   Query graded prediction_outcomes for MLB picks where game_context_flag was HIGH_TOTAL,
   HR_BOOST, HR_SUPPRESS, HITTER_PARK. Compare hit rates vs NEUTRAL baseline.
   Need: game_context data + prediction_outcomes joined on game_date + team.

B. DK validation -- run run_daily.py on an active MLB game day (afternoon) and verify
   implied_probability is populating from DraftKings. Check a few actual DK lines.

C. End-to-end smoke test -- start FastAPI (uvicorn PEGASUS.api.main:app --port 8600),
   hit /picks/today?sport=mlb&min_tier=T2-STRONG, verify game_context_flag fields appear
   in the JSON response.

D. Pitching enrichment -- populate opposing_pitcher_hand in player_game_logs using
   Baseball Reference or ESPN pitcher bios. Would unlock batter vs LHP/RHP splits.
   IRON RULE: any write to mlb/ DB must use the existing grading script pattern,
   not ad-hoc inserts. Consider a PEGASUS-side enrichment cache instead.

Do NOT touch: orchestrator.py, sync/, shared/, nba/, nhl/ scripts (read-only for analysis).
PEGASUS Iron Rule: all new files in PEGASUS/ only. Exceptions: mobile/src/ is allowed.
Run FastAPI from REPO ROOT: uvicorn PEGASUS.api.main:app --port 8600 --reload
```
