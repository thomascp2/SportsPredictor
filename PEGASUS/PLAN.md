# PEGASUS — Execution Plan
**Last updated: 2026-04-15**
**Codename: PEGASUS**
**Mission: Build a Rithmm-caliber sports prediction app — NHL, NBA, MLB — with honest math, situational intelligence, and daily pick delivery.**

---

## Foundational Architecture Decision

**The existing SportsPredictor orchestrator is the data collection layer. Do not touch it.**

The daily data flow stays exactly as-is:
```
orchestrator.py (existing, running)
  → nhl/nba/mlb grading + prediction scripts
  → SQLite databases (nhl_predictions_v2.db, nba_predictions.db, mlb/*.db)
  → mlb_feature_store/data/mlb.duckdb (XGBoost ML predictions)
  → Supabase daily_props (existing)
```

PEGASUS is built as a **parallel, read-only consumer** of those same databases. It produces a *better* output layer on top of the same raw data:

```
PEGASUS/ (new — build here, nothing leaves this dir until launch)
  calibration/       → audit scripts, reliability diagrams, baseline tests
  situational/       → playoff/stakes intelligence engine
  pipeline/          → calibrated pick selector, ML blend, edge calculator
  sync/              → Supabase upsert (writes to Supabase, reads nothing else from prod)
  api/               → FastAPI endpoints (future)
  run_daily.py       → PEGASUS daily runner (called manually or via separate bat)
```

**The handoff point**: When PEGASUS is validated and ready to ship, we flip the Supabase sync from `sync/supabase_sync.py` (old) to `PEGASUS/sync/supabase_sync.py` (new). The orchestrator data collection never changes. Only the pick-delivery layer swaps.

**Read-only contract**: PEGASUS scripts open all existing SQLite/DuckDB files with `check_same_thread=False` and `read_only=True` where supported. Never `INSERT`, `UPDATE`, or `DELETE` against existing databases. Only write to Supabase and to PEGASUS-local files.

---

## Step-by-Step Execution Plan

---

### STEP 1 — Project Scaffold
**Status**: Not started | **Risk**: None | **Blocking**: Nothing can proceed without this

Create the PEGASUS directory structure:
```
PEGASUS/
  calibration/
    __init__.py
    audit.py             # reliability diagrams, always-UNDER baseline, Brier score
    report.py            # formats + saves JSON reports
  situational/
    __init__.py
    intel.py             # standings fetch, game stakes scoring, star player logic
    flags.py             # enum: HIGH_STAKES, DEAD_RUBBER, REDUCED_STAKES, USAGE_BOOST, NORMAL
  pipeline/
    __init__.py
    pick_selector.py     # calibrated smart pick builder (reads existing DBs, read-only)
    mlb_ml_reader.py     # reads mlb_feature_store DuckDB, blends XGBoost + stat probs
    nhl_ml_reader.py     # reads ml_training/model_registry/nhl/, applies 60/40 blend
    edge_calculator.py   # true edge: calibrated_prob - break_even[odds_type]
  sync/
    __init__.py
    supabase_sync.py     # PEGASUS version — writes PEGASUS picks to Supabase
  api/
    __init__.py          # FastAPI (Phase 7, not yet)
  data/
    calibration_tables/  # JSON calibration lookup tables per sport
    reports/             # output from audit.py
  config.py              # paths to existing DBs, Supabase keys, break-even constants
  run_daily.py           # PEGASUS daily runner
  requirements.txt       # local requirements (read from root requirements.txt as base)
  README.md              # how to run PEGASUS standalone
```

**Deliverable**: Scaffold with empty modules, `config.py` wired to existing DB paths, `requirements.txt`.

---

### STEP 2 — Calibration Audit (Phase 0a + 0c)
**Status**: Not started | **Risk**: Results may be bad — that's the point | **Blocking**: Steps 3-9

**This is the math checkpoint. Nothing ships until this passes.**

Build `PEGASUS/calibration/audit.py`. It reads from the existing SQLite databases (read-only) and produces an honest scorecard.

#### What it computes (per sport):

**A. Always-UNDER Baseline Test**
```python
# For every graded prediction:
always_under_accuracy = COUNT(actual_outcome == UNDER) / COUNT(*)
our_accuracy = COUNT(prediction == actual_outcome) / COUNT(*)
real_edge = our_accuracy - always_under_accuracy
```
Threshold: `real_edge > 3%` on `n > 1,000` samples.
If real_edge < 3%: our model is mostly predicting "always bet the way everyone bets." This is a root-cause problem that must be fixed before anything else.

**B. Reliability Diagram (Calibration Plot)**
Bucket all graded predictions by probability decile (0–10%, 10–20%, … 90–100%). For each bucket, compute actual hit rate. A well-calibrated model's points fall near the diagonal (model says 70% → hits ~70%). Over-confidence = points below diagonal.
```sql
SELECT
  ROUND(probability / 0.1) * 0.1 AS prob_bucket,
  COUNT(*) AS n,
  1.0 * SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) / COUNT(*) AS actual_hit_rate
FROM predictions p
JOIN prediction_outcomes o ON p.id = o.prediction_id
WHERE probability IS NOT NULL
GROUP BY prob_bucket HAVING n >= 30 ORDER BY prob_bucket;
```
Save bucket → actual_hit_rate mapping to `data/calibration_tables/{sport}.json`. This becomes the lookup table used by `edge_calculator.py`.

**C. Tier Performance Validation**
For each confidence tier (T1-ELITE through T5-FADE): hit rate + 95% confidence interval using Wilson score. T1 must meaningfully outperform T4 or the tier system is decorative.

**D. Brier Score**
`brier = mean((probability - actual_binary_outcome)^2)`. Lower = better calibrated. Compare our model vs. naive always-UNDER model.

**E. OVER/UNDER Directional Split**
How often does the model predict OVER vs UNDER per sport? Compare to actual hit rates per direction. Surfaces the UNDER bias risk explicitly.

#### Output
```
PEGASUS/data/reports/calibration_nhl_2026-04-15.json
PEGASUS/data/reports/calibration_nba_2026-04-15.json
PEGASUS/data/reports/calibration_mlb_2026-04-15.json
```
Terminal: print full calibration table + pass/fail verdict per check.

#### Database schema notes
- NHL `predictions`: `probability` column, joined to `prediction_outcomes` on `prediction_id`. Outcome column: `outcome` (HIT/MISS). Prediction direction: `prediction` (OVER/UNDER).
- NBA: same join pattern, `prediction` column for direction.
- MLB: statistical predictions in `mlb/database/`, different schema — check `mlb_config.py` for DB_PATH.

#### The gate
If `real_edge < 3%` for any sport: **do not proceed to Supabase sync or mobile**. Instead, diagnose root cause:
- Is the statistical model genuinely not adding edge? → Reconsider probability generation in `statistical_predictions_v2.py`
- Is the UNDER prediction rate too high (>75%)? → Examine `PROBABILITY_CAP` and direction logic
- Are calibration buckets badly off-diagonal? → Apply calibration discount before surfacing probabilities

This step is intentionally slow and honest. It is the foundation everything else is built on.

---

### STEP 3 — Situational Intelligence Engine (Phase 3.5)
**Status**: Spec exists (`docs/plans/situational_intelligence_layer.md`) | **Priority**: URGENT — playoffs live NOW | **Risk**: Low — advisory overlay only, never modifies DB

**Core concept**: The model treats every game identically. Reality: a star player in an NBA elimination game plays 40+ minutes. A star on a clinched NHL team coasts at 18 minutes. The model has no idea. PEGASUS does.

This is an **advisory overlay** — it NEVER modifies existing prediction probabilities or writes to existing SQLite databases. It adds 3 fields to the PEGASUS pick output:
- `situation_flag`: HIGH_STAKES | DEAD_RUBBER | REDUCED_STAKES | USAGE_BOOST | NORMAL
- `situation_modifier`: float (-0.15 to +0.05) — shown as a display warning, never written to core prob
- `situation_notes`: human-readable string ("LAL fighting for 4-seed, Kawhi expected full minutes")

#### How stakes are detected

**NBA (current: April, playoff push + play-in)**
Data source: ESPN standings API (already wired in `shared/fetch_game_odds.py`). Pull today's standings → for each team with a game today, compute:

| Standing position | Games remaining | Stakes level |
|---|---|---|
| Eliminated from playoffs | Any | DEAD_RUBBER (0.05) |
| 3+ games below play-in with < 5 games left | < 5 | DEAD_RUBBER (0.10) |
| Play-in zone (9-10 seed), seed moveable | < 8 | HIGH_STAKES (0.85) |
| Seeding battle (2 vs 3, 4 vs 5 etc.), < 4 game gap | < 6 | HIGH_STAKES (0.80) |
| Playoffs clinched, seed fully locked | Any | REDUCED_STAKES (0.20) |
| Already in actual playoff series (round 1+) | N/A | HIGH_STAKES (1.00) |
| Win-or-go-home game (play-in or elimination) | N/A | HIGH_STAKES (1.00) + USAGE_BOOST for stars |

**NHL (current: April, regular season ends ~April 18, playoffs start ~April 21)**
Data source: NHL API (`api-web.nhle.com/v1/standings/now` — already used in grading scripts).

| Position | Stakes |
|---|---|
| Eliminated from playoff contention | DEAD_RUBBER |
| Wild card race, < 3 points back with < 5 games left | HIGH_STAKES |
| Division leader/clinched | REDUCED_STAKES |
| Playoff series in progress | HIGH_STAKES (1.00) |
| Win-or-go-home (game 7) | HIGH_STAKES (1.00) + USAGE_BOOST |

**MLB (current: April, regular season start)**
April is the opposite of playoff pressure — all teams have full hope, no one is eliminated. Stakes are NORMAL for all teams until approximately July. No situational flags needed for MLB until late August. Skip for now, build placeholder.

#### Star player detection (USAGE_BOOST)
In HIGH_STAKES/elimination games: identify the top-2 minute leaders on each team (by season average) and flag them with `USAGE_BOOST`. In must-win games:
- NBA stars typically go from 32 min average → 38+ min → props that assume 32 min baseline are UNDER
- NHL stars (e.g., top-line centers) get extra TOI → shots/points props understated

Logic:
```python
def get_usage_boost_players(team, game_stakes_score):
    if game_stakes_score < 0.75:
        return []
    # query player_game_logs for this team's top-minutes players last 10 games
    # return their player_ids flagged for USAGE_BOOST
```

#### Output format (added to SmartPick dataclass in PEGASUS)
```python
@dataclass
class PEGASUSPick:
    # ... all existing fields ...
    situation_flag: str          # "HIGH_STAKES" | "DEAD_RUBBER" | etc.
    situation_modifier: float    # -0.15 to +0.05 (display only)
    situation_notes: str         # "Team X fighting for 4-seed, 2 games left"
    usage_boost: bool            # True if star player in must-win spot
```

#### Key rule: advisory only
The `situation_modifier` changes what the *user sees* (a warning badge, a boost indicator) but it does NOT change the underlying `probability`, `ai_edge`, or `tier` stored anywhere. This preserves database integrity and makes the system reversible.

#### Implementation files
```
PEGASUS/situational/intel.py      # core logic: standings fetch, stakes scoring
PEGASUS/situational/flags.py      # enum definitions + modifier lookup
PEGASUS/pipeline/pick_selector.py # calls intel.py, attaches flags to picks
```

Read the existing spec at `docs/plans/situational_intelligence_layer.md` before implementing — 665 lines of detail that should not be ignored.

---

### STEP 3 ADDENDUM — Layer 2: Minutes Deviation Signal
**Status**: Spec locked (Session 3) | **Build at**: Step 6 (pick_selector.py) | **File**: `PEGASUS/2027/intel.py` has full implementation for reference

**The problem Layer 1 alone doesn't solve**: Standings tell you *where* a team is. They don't tell you whether the coach has already *changed their behaviour*. A bubble team 3 games back with 12 left hasn't been flagged by Layer 1 yet — but their star has been averaging 38 minutes over the last 5 games vs. a 32-minute season average. The coach already made the decision. The data shows it.

**The signal**:
```python
deviation = avg_minutes_last_5 - avg_minutes_season

deviation >= +4  → coach leaning on this player hard → elevate motivation score
deviation <= -4  → load management / rest mode → reduce motivation score
```

**Sport mapping**:
- NBA: `minutes_played` column in `player_game_logs`
- NHL: `toi` column (time on ice, stored in minutes)
- MLB: `pa` (plate appearances) — proxy for "played a full game vs. got a rest day"

**Blending logic** (in `pick_selector.py` at Step 6):
```python
# Layer 1 (standings)
base_motivation = _nba_motivation_score(team_info)   # or NHL/MLB equivalent

# Layer 2 (minutes deviation from player_game_logs — already in our DB, no API call)
deviation = get_minutes_deviation(player_name, team, sport)

# Blend: standings is primary signal, deviation nudges it (capped at ±0.15)
blended_motivation = _apply_deviation_to_motivation(base_motivation, deviation)

# Final flag from blended score
flag, modifier = flag_from_motivation(blended_motivation, injury_status)
```

**MLB note**: Pitcher rotation is FIXED (every 5 days) — Layer 2 has no effect on starting pitcher props and should be skipped for them. For position players, the PA deviation is the key signal: during playoff hunt, rest days disappear. A player going from 3.5 PA/game to 4.2 PA/game is being played through fatigue.

**Discussion point for Step 6 build session**: Should the deviation gate be per-player (query individually in `get_situation()`) or pre-computed as a team batch (query all starters once per team per day)? The batch approach is more efficient for a team of 8-10 starters but requires a slightly different call structure. `PEGASUS/2027/intel.py` has both implementations (`get_minutes_deviation()` for individual, `get_team_minutes_deviation_summary()` for batch).

---

### STEP 4 — NHL ML Audit
**Status**: Models exist (v20260325_003, LogisticRegression, 13 props) but NEVER ACTIVATED | **Risk**: Models may be bad — need to verify before any blend

**Critical context**: The user believed NHL was running the 60/40 ML/stat blend since initial training. It was not. `v2_config.py` reads `MODEL_TYPE = "statistical_only"` today. The models were trained but never activated in production. This was either intentional (waiting for a data volume gate) or an oversight. Either way, we need to audit before doing anything with them.

#### Audit steps (in PEGASUS — do not touch existing orchestrator)

Build `PEGASUS/pipeline/nhl_ml_reader.py` with an audit function:

1. **Load latest metadata** for each prop/line in `ml_training/model_registry/nhl/`:
   - Model type, training samples, feature count, training date
   - Any stored accuracy/Brier metrics in `metadata.json`
   
2. **Temporal validation**: Load the existing NHL SQLite (`nhl_predictions_v2.db`), find all predictions from after the model training date (post-March 25, 2026). Compare what the statistical model predicted vs. what the ML model would predict. Are they materially different?

3. **Shadow mode run**: For a sample of recent games (last 30 days of graded predictions), run each feature vector through the saved `.joblib` model and record what probability it would have output. Compare to: (a) what the statistical model output, (b) what actually happened.

4. **Three-Check verdict**:
   - Does NHL LR beat always-UNDER baseline by >3%?
   - Does feature importance look sane (no single feature >70%)?
   - Are probabilities reasonably calibrated?

5. **Decision gate**:
   - PASS: Activate 60/40 blend in PEGASUS pick_selector.py (NOT in existing orchestrator)
   - FAIL: Leave as statistical-only in PEGASUS too; plan a retrain for Oct/Nov 2026

This audit runs independently inside PEGASUS and does not touch `v2_config.py` in the existing system.

---

### STEP 5 — MLB XGBoost Integration (Phase 4a)
**Status**: mlb_feature_store wired to orchestrator, NOT to pick pipeline | **Risk**: Low — additive only

Close the gap: mlb_feature_store XGBoost predictions exist in `data/mlb.duckdb` (`ml_predictions` table) but never reach Supabase or the mobile app. PEGASUS is where this gets fixed.

Build `PEGASUS/pipeline/mlb_ml_reader.py`:
```python
def get_today_mlb_ml_predictions(game_date: str) -> dict:
    """
    Read ml_predictions from mlb_feature_store DuckDB.
    Returns: {(player_name, prop): {predicted_value, p_over, line}} 
    Excludes home_runs (model is worse than naive — documented).
    """
    db_path = ROOT / "mlb_feature_store" / "data" / "mlb.duckdb"
    conn = duckdb.connect(str(db_path), read_only=True)
    ...
```

Blend logic in `pick_selector.py`:
- For hits, total_bases, strikeouts, walks, outs_recorded: `final_prob = 0.6 * ml_p_over + 0.4 * stat_prob`
- For home_runs, all other MLB props: `final_prob = stat_prob`
- If DuckDB unavailable or player not in ml_predictions: fall back to `stat_prob` silently

The blend ratio (60/40) mirrors the NHL HybridPredictionEngine approach. Start here; adjust after 2 weeks of live data comparison.

---

### STEP 6 — PEGASUS Pick Selector (Core Pipeline)
**Status**: Not started | **Risk**: Medium — lots of moving parts

Build `PEGASUS/pipeline/pick_selector.py`. This is the heart of PEGASUS.

It reads from:
- Existing SQLite predictions tables (read-only) — today's generated picks
- `data/calibration_tables/{sport}.json` — built in Step 2
- `ml_predictions` DuckDB (MLB) — built in Step 5
- `ml_training/model_registry/nhl/` — if NHL audit passed in Step 4
- Situational intel engine — built in Step 3

It outputs `PEGASUSPick` objects:
```python
@dataclass
class PEGASUSPick:
    player_name: str
    team: str
    sport: str
    prop: str
    line: float
    direction: str                  # OVER / UNDER
    odds_type: str                  # standard / goblin / demon
    
    # Probabilities
    raw_stat_probability: float     # what the statistical model said
    ml_probability: float           # what the ML model said (None if not available)
    blended_probability: float      # the final blended probability
    calibrated_probability: float   # blended_prob adjusted via calibration table
    
    # Edge
    break_even: float               # 0.5238 std / 0.7619 goblin / 0.4545 demon
    ai_edge: float                  # (calibrated_prob - break_even) * 100
    vs_naive_edge: float            # calibrated_prob - always_under_rate (sport-level)
    
    # Tier (based on edge, not raw probability)
    tier: str                       # T1-ELITE, T2-STRONG, T3-GOOD, T4-LEAN, T5-FADE
    
    # Situational
    situation_flag: str
    situation_modifier: float
    situation_notes: str
    usage_boost: bool
    
    # Metadata
    game_date: str
    game_time: str
    implied_probability: float      # from sportsbook (None until Phase 1b)
    true_ev: float                  # (calibrated_prob * decimal_odds) - 1 (None until Phase 1b)
```

Tier assignment uses edge (same logic as existing smart_pick_selector.py, already correct):
- T1-ELITE: edge >= +19%
- T2-STRONG: edge >= +14%
- T3-GOOD: edge >= +9%
- T4-LEAN: edge >= 0%
- T5-FADE: edge < 0% (suppressed from output by default)

---

### STEP 7 — PEGASUS Daily Runner
**Status**: Not started | **Risk**: Low if Steps 1-6 complete

Build `PEGASUS/run_daily.py`. This is the PEGASUS orchestrator — it runs AFTER the existing orchestrator has done its work for the day.

```
run_daily.py flow:
  1. Verify existing orchestrator has run today (check prediction counts in SQLite)
  2. Load calibration tables (built once in Step 2, reused daily)
  3. Fetch today's situational context (standings, game stakes)
  4. For each sport:
     a. Read today's statistical predictions from SQLite (read-only)
     b. Blend with ML predictions (MLB: DuckDB, NHL: .joblib if audit passed)
     c. Apply calibration discount
     d. Attach situational flags
     e. Build PEGASUSPick objects
  5. Filter: keep T1-T4, drop T5
  6. Output to:
     a. PEGASUS/data/picks_{date}.json  (local snapshot, never to prod DBs)
     b. PEGASUS/sync/supabase_sync.py   (to Supabase — when sync is built)
     c. Terminal summary (counts, tier breakdown, any situation flags)
```

Schedule: Run manually at first. When validated, add to `start_orchestrator.bat` as a second process, timed 30 minutes after existing orchestrator prediction step completes.

---

### STEP 8 — PEGASUS Turso Sync (Phase 2)
**Status**: Not started | **Primary target: Turso. Supabase is secondary/legacy.**

**Architecture context (as of 2026-04-15):**
- `sync/turso_sync.py` already exists and handles predictions, smart-picks, grading for NHL/NBA/MLB/Golf
- Each sport has its own Turso database (`TURSO_NHL_URL/TOKEN`, `TURSO_NBA_URL/TOKEN`, `TURSO_MLB_URL/TOKEN`)
- Orchestrator calls Turso sync after predictions, pp-sync, and grading (wired at lines ~783, ~951, ~2476)
- 772k rows migrated to Turso as of April 6, 2026
- **Known issue**: MLB Turso smart-picks has a silent failure — low priority but must be investigated before PEGASUS MLB sync is trusted
- Supabase still holds: `daily_props`, `user_picks`, `profiles`, `user_bets`, points/gamification — user-facing app layer
- Mobile app currently reads from Supabase `daily_props` — Turso mobile integration was "next" as of Apr 6

**PEGASUS sync target:**
PEGASUS writes picks to **Turso** (not Supabase), matching the pattern in `sync/turso_sync.py`. New PEGASUS columns (calibrated_probability, situation_flag, vs_naive_edge etc.) are added to the Turso predictions/smart-picks tables — not to Supabase.

**Decision needed at Step 8 time**: Does the mobile app need to move off `daily_props` (Supabase) to read from Turso, or do we maintain a Turso→Supabase bridge for the mobile layer? This is the Turso mobile integration that was pending as of Apr 6.

**PEGASUS Turso sync** (`PEGASUS/sync/turso_sync.py`):
- Based on `sync/turso_sync.py` pattern (libsql_client, async, per-sport config)
- Upsert on (player_name, prop, game_date, sport)
- Writes PEGASUS-enriched columns alongside existing prediction fields
- Non-fatal: failure logs to Discord, does not abort daily runner
- Per-sport Turso credentials from environment: `TURSO_{SPORT}_URL` + `TURSO_{SPORT}_TOKEN`

**Supabase**: PEGASUS does not write to Supabase directly. Supabase continues to receive data from the existing `sync/supabase_sync.py` for user-facing features (picks, profiles, gamification). PEGASUS does not touch those tables.

---

### STEP 9 — Odds Integration (Phase 1a + 1b)
**Status**: Not started | **Decision needed**: When to start paying for The Odds API

#### 1a. PrizePicks MLB Extension
The existing `shared/prizepicks_client.py` handles NHL and NBA. Extend to MLB (league_id=2). But this work happens inside PEGASUS — create `PEGASUS/pipeline/prizepicks_client.py` as a copy + extension. Do not modify the existing shared client.

#### 1b. Sportsbook Odds (The Odds API)
Start with the free tier (500 req/month). Integrate `implied_probability` into PEGASUS picks. Enables displaying "Model: 72% | Sportsbook: 54% | Edge: +18%" — the core Rithmm-style display.

When The Odds API is wired, `implied_probability` and `true_ev` columns in `daily_props` stop being NULL.

---

### STEP 10 — API + Mobile (Phase 2 + 3)
**Status**: Future | **Gate**: Steps 1-9 must be solid first

Build FastAPI endpoints inside `PEGASUS/api/` that serve the new enriched pick data. Mobile app update: design system (`mobile/src/theme/index.ts`), pick card redesign with tier colors and edge display, performance screen with calibration chart.

This step is last because mobile changes are visible to users — only ship when the underlying math (Steps 1-8) is validated.

---

### STEP 11 — Game Lines ML (Phase 5)
**Status**: Future | **Gate**: Steps 1-10 solid + full 2026 season data

Moneyline / spread / total predictions per sport. Separate sub-pipeline inside PEGASUS (`PEGASUS/game_lines/`). Feature engineering: team-level stats (Corsi/PDO for NHL, ORtg/DRtg for NBA, FIP/xFIP for MLB starters). Separate training, separate grading, separate prediction tables. Do not mix with player props.

---

## Priority Order (RIGHT NOW)

Given that NBA playoffs are live and NHL playoff push is in final week:

```
TODAY / THIS SESSION:
  Step 1   → Scaffold PEGASUS directory structure + config.py

NEXT SESSION:
  Step 2   → Calibration audit (must check our math — this is the foundation)

AFTER CALIBRATION:
  Step 3   → Situational Intelligence (NBA + NHL — URGENT while playoffs active)
  Step 4   → NHL ML Audit (models exist, never used — verify before activating)
  Step 5   → MLB XGBoost gap closure
  Step 6   → PEGASUS Pick Selector
  Step 7   → PEGASUS Daily Runner
  Step 8   → Supabase Sync
  Step 9   → Odds Integration
  Step 10  → API + Mobile
  Step 11  → Game Lines
```

**Why calibration before situational?** We need to know if our base numbers are real before we layer situational intelligence on top. If the statistical model has near-zero real edge, situational intelligence would be decorating a broken foundation. The calibration audit takes one session and answers this definitively.

---

## Cross-Session Bookmarking Protocol

Every time a context window ends mid-plan, create a bookmark file:
```
PEGASUS/bookmarks/
  bookmark-01.md    ← Session 1 (this session): scaffold + planning done
  bookmark-02.md    ← Session 2: calibration audit (fill in when done)
  bookmark-03.md    ← etc.
```

Each bookmark records:
- What was completed
- What files were created/modified
- Exact next step to execute when context resets
- Any decisions still outstanding

---

## Non-Negotiable Rules

1. **Never write to existing SQLite databases from PEGASUS scripts.** Read-only.
2. **Never modify `orchestrator.py`, `nhl/`, `nba/`, `mlb/`, `shared/`, or `sync/` during PEGASUS development.** If PEGASUS needs something from `shared/`, copy it into PEGASUS and adapt it.
3. **Every new probability shown to users must be calibrated** (backed by empirical hit rate data, not raw model output).
4. **Situational modifiers are display-only.** They never touch stored probabilities.
5. **Home runs ML model is permanently excluded from PEGASUS picks** — XGBoost home_runs model is worse than naive. Use statistical model only.
6. **No NBA ML until LR retrain.** The 471 existing NBA models (v20260315_001) are the bad ones. Leave them alone. NBA runs statistical-only in PEGASUS until a clean LR retrain is done (Oct 2026 or sooner if calibration audit gives us a green light for earlier retrain).

---

## Open Decisions (answer before starting each step)

| Step | Decision needed |
|---|---|
| Step 2 | NHL `predictions` table: confirm exact column name for `probability` (check schema) |
| Step 3 | How to handle no-standings data days (off-season, API down)? Default to NORMAL. |
| Step 4 | If NHL ML audit fails, do we retrain now (mid-season) or wait for Oct? |
| Step 7 | What time should PEGASUS daily runner execute relative to existing orchestrator? |
| Step 8 | Confirm Supabase migration is safe to run while orchestrator is syncing (add columns only — non-destructive) |
| Step 9 | When to upgrade from free to Developer tier on The Odds API ($49/month)? |
| Step 10 | Does the mobile app need new Supabase column types to render badges/flags, or is TEXT sufficient? |
