# PEGASUS — Comprehensive Project Summary
**As of: 2026-04-15 | Sessions 1–13 Complete**

This document is the single source of truth for what PEGASUS is, what has been built, what every piece does, and what comes next. Read this at the start of any new session before touching any code.

---

## What PEGASUS Is

PEGASUS is a **parallel, read-only prediction system** built on top of the existing SportsPredictor orchestrator. It does NOT replace the orchestrator — it runs after it, reads its outputs, and produces a separate layer of enriched picks.

**Iron Rule (Rule 2):** PEGASUS never modifies files outside `PEGASUS/`. Every file, every import, every write happens inside this directory. The only two exceptions are the `orchestrator.py` additions from Session 5 (`check_prediction_direction_sanity()` and `run_weekly_ml_audit()`), which were already applied and must not be touched.

**Why it exists:** The existing smart pick selector selects based on raw probability vs. break-even. PEGASUS adds three things the current system lacks:
1. **Calibration correction**: raw stat model probabilities are systematically miscalibrated — PEGASUS adjusts them to actual hit rates
2. **ML blend**: for props where ML adds demonstrable value (MLB hits/TB/K/walks/outs), blend 60% ML + 40% statistical
3. **Situational intelligence**: flags dead-rubber/high-stakes/usage-boost context the ML model cannot see

---

## Directory Structure

```
PEGASUS/
├── PLAN.md                    — Full step-by-step build plan (Steps 1–10+)
├── PEGASUS.md                 — Original vision doc
├── README.md                  — Quick start
├── config.py                  — Paths, break-evens, tier thresholds
├── requirements.txt
│
├── pipeline/
│   ├── __init__.py
│   ├── nhl_ml_reader.py       — [STEP 4] NHL ML reader (FAIL verdict — stat-only)
│   ├── mlb_ml_reader.py       — [STEP 5] MLB XGBoost reader + p_over converter
│   ├── pick_selector.py       — [STEP 6] Core pick builder + [STEP 10] DK wiring
│   ├── prizepicks_client.py   — [STEP 9a] In-memory PP line fetcher (no SQLite)
│   ├── odds_client.py         — [STEP 9b] The Odds API client + math utilities
│   └── draftkings_odds.py     — [STEP 10a] DK sportsbook unofficial API + parser
│
├── calibration/
│   ├── __init__.py
│   ├── audit.py               — [STEP 1] Full calibration audit runner
│   └── report.py              — Audit report formatter
│
├── situational/
│   ├── __init__.py
│   ├── flags.py               — [STEP 3] SituationFlag enum + modifier table
│   └── intel.py               — [STEP 3] Live standings + stakes engine
│
├── api/
│   ├── __init__.py
│   └── main.py                — [STEP 10b/c] FastAPI port 8600 — Turso + snapshot
│
├── sync/
│   ├── __init__.py
│   └── turso_sync.py          — [STEP 8] PEGASUS Turso sync (pegasus_picks table)
│
├── 2027/
│   └── intel.py               — [STEP 3] 2027 edition placeholder
│
├── data/
│   ├── calibration_tables/    — JSON calibration tables (nhl.json, nba.json, mlb.json)
│   ├── picks/                 — Daily pick snapshots (STEP 7 output)
│   ├── reports/               — Calibration reports
│   └── situational_cache/     — Standings API cache (TTL: 1 per date)
│
├── docs/
│   ├── nhl_ml_post_mortem.md  — [STEP 4] Full NHL ML failure analysis + retrain spec
│   ├── mlb_training_guidance.md — [STEP 5] MLB training guidance
│   └── mobile-step10.md       — [STEP 10d] Mobile pick card design spec
│
└── bookmarks/
    ├── bookmark-01.md through bookmark-12.md
    ├── bookmark-13.md             — Session 13: MLB game context + Expo fix + Step 11 split plan
    └── comprehensive_summary.md  (this file)
```

---

## Step-by-Step Build History

### STEP 1 — Calibration Audit (COMPLETE)
**File:** `PEGASUS/calibration/audit.py`
**What it does:** Full 6-check calibration audit for NHL, NBA, MLB using graded prediction_outcomes.

Checks:
- A. Always-UNDER Baseline (real_edge gate)
- B. Reliability Diagram (probability buckets vs actual hit rates)
- C. Tier Performance (do higher tiers outperform?)
- D. Brier Score
- E. OVER/UNDER Directional (surface UNDER bias)
- F. Profitability Matrix — the gate: T1-T3 picks only, hit rate vs break-even per (direction × odds_type)

**Results (as of 2026-04-15):**

| Sport | n | Always-UNDER | Our Accuracy | Real Edge | Status |
|-------|---|-------------|--------------|-----------|--------|
| NHL | 61,976 | 69.2% | 67.4% | -1.8% | Calibration PASS — but stat model has bug |
| NBA | 147,163 | 59.0% | 68.3% | +9.3% | PASS |
| MLB | 18,835 | 59.5% | 66.8% | +7.3% | PASS |

**Calibration tables saved to:** `PEGASUS/data/calibration_tables/{sport}.json`

Key: `calibration_table` maps probability bucket midpoint (string) → actual hit rate.
Bucket logic: `bucket_low = round(min(int(prob * 10) / 10, 0.9), 1)`, `bucket_mid = bucket_low + 0.05`

---

### STEP 2 — Calibration Tables (COMPLETE, built as part of STEP 1)
**Files:** `PEGASUS/data/calibration_tables/{nhl,nba,mlb}.json`

Schema per file:
```json
{
  "sport": "nba",
  "built_date": "2026-04-15",
  "n": 147163,
  "calibration_table": {"0.55": 0.5519, "0.65": 0.5824, "0.75": 0.6392, ...},
  "always_under_rate": 0.5898,
  "our_accuracy": 0.6831,
  "real_edge_vs_naive": 0.0933,
  "approved_combos": [["OVER", "standard"], ["UNDER", "standard"]]
}
```

---

### STEP 3 — Situational Intelligence (COMPLETE)
**Files:** `PEGASUS/situational/flags.py`, `PEGASUS/situational/intel.py`

**What it does:** Fetches live standings (NBA: ESPN API, NHL: NHL API), assesses team motivation (playoff stakes, dead-rubber risk, seed position), and returns advisory flags.

Primary entry point:
```python
from PEGASUS.situational.intel import get_situation

flag, modifier, notes = get_situation(
    team="MIL",
    sport="nba",
    game_date="2026-04-15",
    injury_status="ACTIVE",
    player_name="Giannis Antetokounmpo",
)
```

Returns `(SituationFlag, modifier, notes_str)`. Modifier is advisory only — NEVER modifies probability, edge, or tier.

**Flags:**
- `HIGH_STAKES`: Bubble/elimination — stars play harder
- `DEAD_RUBBER`: Seed locked/coasting — reduced minutes expected
- `REDUCED_STAKES`: Clinched but seed moveable — moderate risk
- `USAGE_BOOST`: Star(s) out → player absorbs usage
- `ELIMINATED`: Mathematically out — full rest mode
- `NORMAL`: Regular stakes — back the model

**MLB:** Always returns NORMAL in April (too early in season for stakes logic).

Caching: Standings fetched once per (sport, date) — cached in `data/situational_cache/`.

---

### STEP 4 — NHL ML Audit (COMPLETE — FAIL verdict)
**File:** `PEGASUS/pipeline/nhl_ml_reader.py`

**What it does:** Shadow-mode audit of NHL logistic regression models (v20260325_003) against 30 days of graded predictions.

**Verdict: FAIL — NHL stays statistical-only in PEGASUS**

Per-prop shadow results:

| Prop/Line | Always-UNDER | ML Accuracy | Improvement | Verdict |
|-----------|-------------|-------------|-------------|---------|
| points 0.5 | 48.9% | 49.2% | +0.4% | FAIL |
| points 1.5 | 87.8% | 87.8% | -0.1% | FAIL |
| shots 1.5 | 43.4% | 44.2% | +0.9% | FAIL |
| shots 2.5 | 63.6% | 64.1% | +0.5% | FAIL |
| shots 3.5 | 86.8% | 86.8% | 0.0% | FAIL |

Root cause: Three independent failure modes — (1) stat model flip bug (100% UNDER on shots_1_5 when OVER wins 57%), (2) f_prob_over feedback loop, (3) broken test baseline. Full analysis in `PEGASUS/docs/nhl_ml_post_mortem.md`.

**Action:** `nhl_ml_reader.py` is kept as a skeleton for when NHL models are retrained (Oct 2026). NHL PEGASUS picks = statistical probability only.

---

### STEP 5 — MLB XGBoost Integration (COMPLETE)
**File:** `PEGASUS/pipeline/mlb_ml_reader.py`

**What it does:** Reads `ml_predictions` table from `mlb_feature_store/data/mlb.duckdb` and provides a probability converter for use in pick_selector.

**DuckDB schema discovered:**
```
ml_predictions: player_id, player_name, game_date, prop, predicted_value, model_version, created_at, actual_value, graded_at
```
`predicted_value` = continuous regression output (expected count). NOT a probability. No `p_over` or `line` column.

**Two functions:**

`get_today_mlb_ml_predictions(game_date)` → `{(player_name, prop): {"predicted_value": float, "p_over": None, "line": None}}`

`compute_ml_p_over(predicted_value, line, prop)` → P(stat > line) using:
- Poisson CDF: hits, total_bases, home_runs, walks
- Normal CDF: strikeouts (σ=1.8), outs_recorded (σ=2.5)

**Blend constants (exported for pick_selector):**
- `BLEND_PROPS` = {hits, total_bases, strikeouts, walks, outs_recorded}
- `STAT_ONLY_PROPS` = {home_runs} — Rule 5: model excluded permanently
- `ML_WEIGHT = 0.60`, `STAT_WEIGHT = 0.40`

**Validation (2026-04-15):** 921 rows, 6 props. Sample: Aaron Judge hits predicted_value=1.66, P(>0.5)=0.810. Sensible.

---

### STEP 6 — PEGASUS Pick Selector (COMPLETE)
**File:** `PEGASUS/pipeline/pick_selector.py`

Core pick builder. Reads all 3 SQLite DBs (read-only), applies ML blend (MLB only),
calibrates probabilities, attaches situational flags, returns `PEGASUSPick` dataclasses.
See Section "Step 6 Detail" below. Added `smart_picks_only` param in Step 7.

---

### STEP 7 — PEGASUS Daily Runner (COMPLETE)
**File:** `PEGASUS/run_daily.py`

Orchestrates the full daily PEGASUS pipeline. Run after existing orchestrator finishes.

Flow:
1. `_check_readiness()` — queries prediction + smart-pick counts per sport. Exits 1 if predictions missing.
2. `get_picks(smart_picks_only=True)` — PP-matched lines only (NHL 44, NBA 130, MLB 168 typical).
3. `_write_json()` — `PEGASUS/data/picks/picks_{date}.json` (local only, never to prod DBs).
4. `sync_to_turso()` — PEGASUS Turso sync (Step 8, non-fatal).
5. `_print_summary()` — tier counts, sport counts, situational flags, top 15 per tier.

Usage: `python PEGASUS/run_daily.py [--date YYYY-MM-DD] [--sport nhl|nba|mlb|all] [--all-picks] [--dry-run]`

Validated 2026-04-15: 342 picks (T1:112 T2:99 T3:13 T4:118), 11 ML-blended, situational flags firing correctly.

---

### STEP 8 — PEGASUS Turso Sync (COMPLETE)
**File:** `PEGASUS/sync/turso_sync.py`

Writes PEGASUS-enriched picks to per-sport Turso databases.

Key decisions:
- Writes to `pegasus_picks` table — separate from `predictions` table (no conflict with prod sync).
- `INSERT OR REPLACE` on `UNIQUE(player_name, prop, game_date, sport)` — re-runs overwrite stale data.
- Per-sport credentials: `TURSO_{SPORT}_URL` / `TURSO_{SPORT}_TOKEN` (same env vars as production).
- Table DDL is idempotent (`CREATE TABLE IF NOT EXISTS`) — runs before every sync.
- Non-fatal: all exceptions logged to console, never re-raised.
- Wired into `run_daily.py` as Step 6 (after JSON write, before terminal summary).

Public API:
```python
from PEGASUS.sync.turso_sync import sync_to_turso
results = sync_to_turso(picks, game_date, sports=["nhl","nba","mlb"])
# returns {"nhl": 44, "nba": 130, "mlb": 168}
```

Standalone CLI (reads from JSON snapshot):
```bash
python PEGASUS/sync/turso_sync.py --date 2026-04-15 [--sport nba]
```

---

### MLB Training Guidance (COMPLETE)
**File:** `PEGASUS/docs/mlb_training_guidance.md`

Comprehensive guide for MLB ML training incorporating every lesson from the NHL failure. Key rules:
1. Never use stat model output as a feature
2. Majority-class baseline (not stat model accuracy)
3. Walk-forward validation: 3+ windows, average improvement > 5%
4. Auto-skip degenerate lines (majority class ≥ 80%)
5. 4-way train/val/cal/test split for calibration
6. Feature importance gate: no single feature > 50%
7. PEGASUS shadow audit required before production activation

---

## Step 6 Detail — pick_selector.py

### Architecture

```
get_picks(game_date, sport="all") → List[PEGASUSPick]
    │
    ├── _load_calibration(sport)         → dict from calibration_tables JSON
    ├── get_today_mlb_ml_predictions()   → {(player, prop): {predicted_value}}
    ├── get_situation()                  → (flag, modifier, notes) per team
    │
    └── _read_predictions(sport, date)  → list of dicts from SQLite (READ-ONLY)
        │
        └── for each row:
            ├── stat_prob = row["probability"]         (P(direction), always ≥0.5)
            ├── MLB blend: 0.6*ml_p_direction + 0.4*stat_prob
            ├── calibrate via lookup in calibration_table
            ├── ai_edge = (calibrated_prob - break_even) * 100
            ├── tier_from_edge → T1-T4 (T5=FADE, filtered)
            ├── attach situational flag/modifier/notes
            └── → PEGASUSPick dataclass
```

### PEGASUSPick Fields

```python
@dataclass
class PEGASUSPick:
    player_name: str
    team: str
    sport: str
    prop: str
    line: float
    direction: str            # OVER / UNDER
    odds_type: str            # standard / goblin / demon

    raw_stat_probability: float    # probability column from SQLite
    ml_probability: Optional[float] # ml_p_direction used in blend (None if no ML)
    blended_probability: float     # 60/40 blend (or stat-only)
    calibrated_probability: float  # blended_prob → calibration table lookup

    break_even: float         # 0.5238 std / 0.7619 goblin / 0.4545 demon
    ai_edge: float            # (calibrated_prob - break_even) * 100
    vs_naive_edge: float      # calibrated_prob - always_under_rate

    tier: str                 # T1-ELITE..T5-FADE
    situation_flag: str
    situation_modifier: float
    situation_notes: str

    game_date: str
    model_version: str
    source_prediction_id: int
```

### Key Decisions

**Probability semantics:**
- All sports: `probability` column = P(direction), where direction = predicted OVER/UNDER. Always ≥ 0.5.
- For NBA (unique): `probability` is stored as P(OVER), so for UNDER picks probability < 0.5. The calibration table was built on raw probability (not P(direction)), so NBA cal table has buckets 0.05–0.95 rather than just 0.55–0.95.
- For calibration lookup: use raw stored probability (consistent with how cal table was built).

**MLB blend direction:**
```python
ml_p_over = compute_ml_p_over(pv, line, prop)
ml_p_direction = ml_p_over if direction == 'OVER' else (1.0 - ml_p_over)
blended = 0.60 * ml_p_direction + 0.40 * stat_prob
```

**NHL:** stat-only (ML FAIL verdict from STEP 4)
**NBA:** stat-only (LEARNING_MODE=True, no trained models)
**MLB:** 60/40 blend for BLEND_PROPS; stat-only for home_runs + any unknown prop

**Situational flag:** attached as advisory context, does NOT modify calibrated_probability, ai_edge, or tier. Display-only.

**T5-FADE suppression:** picks with ai_edge < 0% are built but filtered from default output. Caller can request `include_fades=True` for analysis.

---

## What Comes Next

### STEP 9 — Odds Integration (COMPLETE)
**Files:** `PEGASUS/pipeline/prizepicks_client.py`, `PEGASUS/pipeline/odds_client.py`

9a. **PrizePicks client** — in-memory PP line fetcher. No SQLite. Covers NHL/NBA/MLB.
    Key API: `get_lines(sport, date)`, `match_pick(pick, lines)`, `detect_line_movement(pick, lines)`.

9b. **The Odds API client** — math utilities (always available) + endpoint stubs.
    Math: `american_to_implied(-110)→0.5238`, `remove_vig(-110,-110)→(0.5,0.5)`, `true_ev_from_prob()`.
    Player prop implied prob: requires paid plan (free tier = game totals only, 90 calls/month).
    Call budget: game totals=90/month (free OK), player props=~900/month (need Starter ~$10/month).
    Env: `ODDS_API_KEY` — set to activate. Everything returns None gracefully if absent.

**PEGASUSPick additions:**
- `implied_probability: Optional[float]` — from sportsbook (None until paid API key)
- `true_ev: float` — computed: `(calibrated_prob / break_even) - 1` (e.g. +0.62 at 85% cal / std break-even)

**Turso:** `pegasus_picks` table now has `implied_probability` and `true_ev` columns.
Note: existing Turso table may need manual ALTER TABLE (see bookmark-09.md).

### STEP 10 — DraftKings Odds + FastAPI + Mobile Design (COMPLETE)
**Files:** `PEGASUS/pipeline/draftkings_odds.py`, `PEGASUS/api/main.py`, `PEGASUS/docs/mobile-step10.md`
Also: `PEGASUS/pipeline/pick_selector.py` updated to wire DK data.

**10a — DraftKings odds client:**
Fetches player prop American odds from DraftKings unofficial sportsbook API (no key, no registration).
Endpoint: `sportsbook-nash.draftkings.com/api/sportscontent/dkusoh/v1/leagues/{id}/categories/{id}`
League IDs: NBA=42648, NHL=42133, MLB=84240. Category IDs: NBA=1000074, NHL=1000096, MLB=1000045.
Parses `markets[]` + `selections[]` → `{(norm_player_name, prop): {over_odds, under_odds, line}}`.
Session cache per (sport, date). Non-fatal — returns `{}` on any error, timeout, or rate-limit.
Note: `draft-kings` PyPI package is DFS fantasy API, NOT sportsbook. Raw requests used instead.
Rate-limit gotcha: consecutive sport calls time out (3s `_MIN_INTERVAL` helps but not guaranteed).
Wired into `pick_selector.py`: `get_picks()` pre-loads DK per sport; `_build_pick()` sets `implied_probability` via `remove_vig()`.

**10b/10c — FastAPI server:**
Port 8600. Mobile reads from this, NOT from Supabase `daily_props`.
`GET /picks/{date}` — query params: sport, min_tier, direction, limit.
`GET /picks/{date}/{player_name}` — partial/case-insensitive player name match.
`GET /health` — last snapshot date + pick counts per sport.
Data: Tries Turso `pegasus_picks` first; falls back to JSON snapshot.
Run: `uvicorn PEGASUS.api.main:app --port 8600 --reload` (from repo root).
Swagger: `http://localhost:8600/docs`.

**10d — Mobile pick card design spec:**
Full TypeScript interface for PEGASUSPick. Tier badge colors (T1=gold, T2=silver, T3=bronze, T4=gray).
Edge bar 0–30%. Calibrated prob display ("Model: 85%"). Implied prob row when DK available.
Situation pills (HIGH_STAKES=red, DEAD_RUBBER=gray, ELIMINATED=gray, USAGE_BOOST=amber).
True EV display. Odds type chip (STD/GOB/DEM). Nullable contract for all new fields.
Full API integration guide (endpoint, response format, recommended query).

**Validation (2026-04-15):** All imports clean; 3 FastAPI routes confirmed; 342-pick snapshot loads; NBA T2+ filter → 74 picks.

### STEP 10 FOLLOW-UP — Mobile Wiring (Session 11, COMPLETE)
**Files (outside PEGASUS/ — allowed exception):**
- `mobile/src/types/pegasus.ts` — Full `PEGASUSPick` TypeScript interface matching the Python dataclass
- `mobile/src/services/pegasus.ts` — `fetchPegasusPicks()` + `adaptPegasusPickToSmartPick()` adapter
- `mobile/src/utils/constants.ts` — `PEGASUS_API_URL` = `http://localhost:8600` (port 8600)
- `mobile/src/services/api.ts` — `SmartPick` interface extended with 7 optional PEGASUS fields (`calibrated_probability`, `implied_probability`, `situation_flag`, `situation_notes`, `true_ev`, `model_version`, `pegasus_source`). `fetchSmartPicks()` waterfall: PEGASUS first → old FastAPI → Supabase
- `mobile/src/components/picks/PickCard.tsx` — situation pill, Book row, True EV badge, "CAL" label when `pegasus_source=true`

**Bug fixed (Session 11):**
`PEGASUS/situational/intel.py` NBA USAGE_BOOST path used `minutes_played` column which doesn't exist in the NBA game_logs schema. Corrected to `minutes`.

**NHL stat model fix (Session 11):**
Root cause confirmed: a Mar 17–18 code change renamed feature keys (`sog_l10` → `f_l10_avg`). ML models expected old names → 0.0 substitution → extreme z-score → 100% UNDER on all shots predictions. All predictions from Mar 17–Apr 15 carry `model_version='ensemble_ml60'` and are contaminated.
- Fix already in place: `USE_ML = False` in `nhl/scripts/generate_predictions_daily_V6.py`
- `ml_training/train_models.py` NHL query now excludes `model_version='ensemble_ml60'` to prevent contaminated labels poisoning Oct 2026 retrain

---

### SESSION 12 — Counterfactual Analysis + Data Usability (Analysis only, no code written)

#### Counterfactual: Was the NHL stat model profitable without ML?

Query: `prediction_outcomes JOIN predictions WHERE model_version = 'statistical_v2.2_asym'`
Total graded: 33,356 rows

| Metric | Value |
|---|---|
| Overall hit rate | **69.0%** |
| Always-UNDER baseline (this window) | **64.0%** |
| Net edge vs baseline | **+5.0pp** |
| UNDER accuracy | **74.8%** (22,234 picks) |
| OVER accuracy | **57.4%** (11,122 picks) |

> Note: the always-UNDER rate in the clean window is **64.0%**, not 69.2%. The 69.2% figure previously used was from all data including different seasons/windows.

**Profitable combos (standard break-even = 52.38%):**

| Prop | Line | Direction | N | Hit% | Edge |
|---|---|---|---|---|---|
| points | 1.5 | UNDER | 6,312 | 84.3% | **+31.9pp** |
| shots | 3.5 | UNDER | 6,213 | 82.4% | **+30.0pp** |
| shots | 2.5 | UNDER | 4,684 | 69.9% | **+17.5pp** |
| shots | 1.5 | OVER | 5,191 | 63.3% | **+10.9pp** |
| shots | 1.5 | UNDER | 1,407 | 54.8% | +2.4pp |
| points | 0.5 | UNDER | 3,337 | 56.3% | +3.9pp |
| points | 0.5 | OVER | 3,261 | 54.7% | +2.3pp |

**Losing combos (OVER suppression candidates — same treatment as NBA threes OVER guard):**

| Prop | Line | Direction | Hit% | Edge |
|---|---|---|---|---|
| shots | 3.5 | OVER | 39.0% | -13.4pp |
| shots | 2.5 | OVER | 49.3% | -3.1pp |
| points | 1.5 | OVER | 27.2% | -25.2pp (n=114, near-zero occurrence) |

**Verdict: YES, the stat model was profitable.** The problem was never the stat model — it was the ML override contaminating it with 100% UNDER outputs on shots lines from Mar 17 onward. If `USE_ML = False` had been in place all season, performance would have been strong.

#### Data Usability for Oct 2026 Retrain

| Prop/Line | Clean Graded | Data Window | Status |
|---|---|---|---|
| points 0.5 | 6,598 | Nov 2025 – Jan 2026 | READY (2.2x target) |
| points 1.5 | 6,426 | Nov 2025 – Jan 2026 | READY (2.1x target) |
| shots 1.5 | 6,598 | Nov 2025 – Jan 2026 | READY (2.2x target) |
| shots 2.5 | 6,598 | Nov 2025 – Jan 2026 | READY (2.2x target) |
| shots 3.5 | 6,598 | Nov 2025 – Jan 2026 | READY (2.2x target) |
| shots 0.5 | 117 | Jan 2026 – present | STARVED — stat-only permanently |

All 5 main PP combos exceed the 3,000-sample minimum. The clean window (Nov 2025 – Jan 2026) captures ~2 months of data before `ensemble_ml60` took over. The exclusion filter in `train_models.py` is already in place.

**Oct 2026 retrain action items (to implement when ready):**
1. Use `statistical_v2.2_asym` only — already wired via exclusion filter
2. Add OVER suppression guard for shots 2.5 OVER and shots 3.5 OVER
3. Exclude shots 0.5 from ML — stat-only forever (too few samples, likely trivial line)
4. Test for Jan-bias (all clean data concentrated Nov–Jan)
5. Combined with 2026-27 season data → robust multi-season training set

---

### SESSION 13 — MLB Game Context Advisory + Expo Fix (COMPLETE)

#### MLB Game Context (`PEGASUS/pipeline/mlb_game_context.py`)

New advisory layer for MLB picks. Advisory only — never modifies probability, edge, or tier.

**Data sources:**
- Static park factor table: 32 MLB stadiums with hr_factor, hit_factor, k_factor, is_dome
- Live: `mlb/database/mlb_predictions.db` game_context table (collecting since Mar 25, 2026)
  - game_context has 273 rows / 22 dates as of Apr 15 (~12.4 games/day)
  - Columns: venue, game_total, wind_speed, wind_direction, temperature, conditions

**Flags:**

| Flag | Trigger |
|---|---|
| HR_BOOST | HR prop + (park hr >= 1.05 + outbound wind >= 8mph) OR (park hr >= 1.15) |
| HR_SUPPRESS | HR prop + (inbound wind >= 8mph) OR (park hr <= 0.85) |
| HITTER_PARK | hits/total_bases + park hit_factor >= 1.08 |
| PITCHER_PARK | hits/TB/K + park hit_factor <= 0.93 or k_factor >= 1.04 |
| HIGH_TOTAL | Any prop + game O/U >= 9.5 |
| LOW_TOTAL | Any prop + game O/U <= 7.0 |
| NEUTRAL | No strong signal |

**Today's results (2026-04-15):** 168 MLB picks — 41 HIGH_TOTAL, 2 HITTER_PARK, 125 NEUTRAL

**Notable park factors:**
- Most extreme suppressor: Oracle Park SF (hr=0.76, hit=0.94)
- Most extreme booster: Coors Field (hr=1.35, hit=1.14)
- Domes (wind irrelevant): Globe Life, Chase Field, American Family, Minute Maid/Daikin, loanDepot, T-Mobile, Rogers Centre

**Wired into pick_selector.py:**
- Import guard: `try: from PEGASUS.pipeline.mlb_game_context import get_game_context`
- Called in `_build_pick()` for MLB only; uses `row["opponent"]` to look up game_context
- Two new `PEGASUSPick` fields: `game_context_flag: str = "NEUTRAL"`, `game_context_notes: str = ""`
- Turso sync DDL and upsert updated with the new columns

**Caveats:**
- `opposing_pitcher_hand` in player_game_logs is 100% empty — handedness splits unavailable
- game_context.game_total is occasionally None if odds not yet posted at pipeline run time
- Park name changes handled: "UNIQLO Field at Dodger Stadium", "Daikin Park" (was Minute Maid)

#### Expo Slug Fix

`mobile/app.json` slug changed: `"freepicks"` -> `"freepicks-sportspredictor"`
Run with `npx expo start --clear` first time. If old app still loads on device, open Expo Go, long-press old project, remove it.
**NOTE: Old app still loading as of end of Session 13. Needs device-side cache clear next session.**

---

### STEP 11 — Game Lines ML (SPLIT into 11a and 11b)

#### Step 11a — MLB Game Context ML (Target: June 2026)

**Status: Advisory flags LIVE (static rules). ML upgrade targeting June 1, 2026.**

game_context table growth projection (collecting ~12.4 games/day):
- May 15, 2026: ~450 rows — **validate advisory flag accuracy** (do HIGH_TOTAL games produce more counting stats?)
- June 1, 2026: ~700 rows — **build Step 11a XGBoost** if validation passes
- Oct 1, 2026: ~2,500 rows — full season refit

Step 11a XGBoost plan:
- Inputs: game_total, park_hr_factor, wind_speed, wind_out_bool, temperature, home_away
- Output: P(stat > line) continuous adjustment factor per prop type (replaces binary flags)
- Same 4-way temporal split as MLB player props
- PEGASUS shadow audit required before activating as a probability modifier

#### Step 11b — NBA/NHL Game Lines ML (Target: April 2027)

Requires full 2026-27 season of game-level data. NHL/NBA seasons start Oct 7, 2026.

NBA plan: XGBoost inputs = game pace (Vegas total), back-to-back flag, home/away, rest days
NHL plan: XGBoost inputs = game total, puck line, back-to-back, home ice, travel distance
Both: advisory `game_context_flag` first, then `game_context_score` modifier after shadow audit

#### Calendar (add to calendar)

| Date | Action |
|---|---|
| **May 15, 2026** | game_context ~450 rows — run Step 11a flag accuracy validation |
| **Jun 1, 2026** | game_context ~700 rows — build Step 11a XGBoost if validation passes |
| **Oct 7, 2026** | NHL/NBA seasons open — trigger Oct player prop retrains + begin Step 11b collection |
| **Oct 2026** | NHL retrain: exclude ensemble_ml60; add shots 2.5/3.5 OVER suppression guard |
| **Apr 2027** | ~1,200 NBA + ~1,000 NHL game_context rows — build Step 11b |

---

## Critical Constants (Do Not Change Without Updating Both Sides)

```python
# Break-evens — must match shared/smart_pick_selector.py
BREAK_EVEN = {
    "standard": 0.5238,  # -110 odds: 110/210
    "goblin":   0.7619,  # -320 odds: 320/420
    "demon":    0.4545,  # +100 odds: 100/220
}

# Tier thresholds (edge in percentage points above break_even)
TIER_THRESHOLDS = {
    "T1-ELITE":  19.0,
    "T2-STRONG": 14.0,
    "T3-GOOD":    9.0,
    "T4-LEAN":    0.0,
    # T5-FADE: edge < 0
}

# MLB blend weights
ML_WEIGHT   = 0.60
STAT_WEIGHT = 0.40
```

---

## Files NOT in PEGASUS (Production — Do Not Touch)

| File | Role | Last Touched |
|------|------|-------------|
| `orchestrator.py` | Master scheduler | Session 5 (+2 functions) — DONE |
| `shared/smart_pick_selector.py` | Production pick logic | No PEGASUS changes |
| `sync/supabase_sync.py` | Supabase sync | No PEGASUS changes |
| `sync/turso_sync.py` | Turso sync | No PEGASUS changes |
| `nhl/scripts/generate_predictions_daily_V6.py` | NHL prediction | Session 11 `USE_ML=False` confirmed |
| `ml_training/train_models.py` | ML training | Session 11: `ensemble_ml60` exclusion filter added |
| `ml_training/production_predictor.py` | ML blend layer | Session 4 fixes |

The orchestrator.py and production fixes from Session 4 are verified working. Do not re-touch them unless a new production bug requires it.

---

## Open Issues (as of Session 13)

1. ~~`no such column: minutes_played`~~ — **FIXED Session 11**
2. ~~Mobile integration~~ — **COMPLETE Session 11**
3. `pegasus_picks` Turso table may need manual migrations if created before Session 13:
   ```sql
   ALTER TABLE pegasus_picks ADD COLUMN implied_probability REAL;
   ALTER TABLE pegasus_picks ADD COLUMN true_ev REAL;
   ALTER TABLE pegasus_picks ADD COLUMN game_context_flag TEXT DEFAULT 'NEUTRAL';
   ALTER TABLE pegasus_picks ADD COLUMN game_context_notes TEXT DEFAULT '';
   ```
4. DK API rate-limit on consecutive sport fetches — non-fatal, existing.
5. NHL hits/blocked_shots not generating (V6 scope) — next season.
6. MLB Turso smart-picks silent failure (production, not PEGASUS) — low priority.
7. **shots 2.5/3.5 OVER suppression guard** — add before Oct 2026 NHL retrain.
8. **shots 0.5** — 117 clean samples; exclude from Oct 2026 ML training.
9. **FastAPI startup** — must run from repo root: `uvicorn PEGASUS.api.main:app --port 8600 --reload`
10. **`opposing_pitcher_hand` empty** — MLB player_game_logs column never populated. Handedness splits unavailable until data enrichment.
11. **Expo old app still loading** — slug changed to `freepicks-sportspredictor` but device cache still showing old app. Next session: clear Expo Go cache on device or add EAS projectId.

---

*Update this file at the start of each session with what changed.*
