# PEGASUS Bookmark — Session 3
**Date: 2026-04-15**

---

## Completed This Session

- [x] Step 3: `PEGASUS/situational/flags.py` — SituationFlag enum + modifier lookup table
- [x] Step 3: `PEGASUS/situational/intel.py` — NBA/NHL/MLB standings fetch, stakes scoring, usage_boost detection
- [x] Step 3: `PEGASUS/situational/__init__.py` — public exports
- [x] Step 3 Addendum: `PEGASUS/PLAN.md` updated with Layer 2 minutes deviation spec (written to Step 3 Addendum section)
- [x] Step 3 Addendum: `PEGASUS/2027/intel.py` — 2027 edition with Layer 2 fully implemented
- [x] Live validation: NBA playoff flags correct, NHL end-of-season flags correct, MLB no-op correct

## Files Created This Session

```
PEGASUS/situational/flags.py
PEGASUS/situational/intel.py
PEGASUS/situational/__init__.py  (updated from empty)
PEGASUS/data/situational_cache/  (auto-created, add to .gitignore)
PEGASUS/2027/intel.py            (2027 edition — Layer 2 minutes deviation added)
PEGASUS/PLAN.md                  (Step 3 Addendum inserted)
```

---

## Design Decisions & Assumptions (full record)

### 1. Scope boundary: PEGASUS-native only
`docs/plans/situational_intelligence_layer.md` describes modifying `shared/pregame_intel.py`
and `shared/smart_pick_selector.py`. We did NOT do that. PEGASUS never touches files outside
PEGASUS/. The shared/ integration will be wired from `PEGASUS/pipeline/pick_selector.py`
(Step 6) via `from PEGASUS.situational import get_situation`.

### 2. No Grok dependency
The original spec used an LLM prompt to assess seeding stakes. Replaced with direct
ESPN/NHL API calls — deterministic, free, already used in the codebase.

### 3. NBA games_remaining=0 = playoffs in progress
When `games_remaining=0` and `clinched_playoffs=True` and `rank <= 8`, the NBA regular
season is over and the team is in a playoff series → `motivation=1.00` → `HIGH_STAKES`.
Play-in teams (rank 9-10) with `left=0` also get `1.00`.

### 4. NHL clinch indicators
- `"x"` = clinched playoff berth (seed moveable) → REDUCED_STAKES (0.45)
- `"y"` = clinched division (seed moveable within division) → REDUCED_STAKES (0.45)
- `"z"` / `"p"` = Presidents' Trophy / division 1 seed locked → DEAD_RUBBER (0.20)
- `"e"` = eliminated → ELIMINATED (0.10)

### 5. ESPN standings API: clincher is numeric, not string
ESPN returns `clincher` as `value=3.0`, `displayValue="z"`. Must read `displayValue`
from the full stats list, not from the `{name: value}` dict.

### 6. ESPN standings API: no gamesPlayed stat
`games_remaining = 82 - (wins + losses)`. Not from a gamesPlayed stat (doesn't exist).

### 7. games_remaining: None-guard for falsy 0
`int(0 or 10) = 10`. Fixed to: `left = int(left_raw if left_raw is not None else default)`.

### 8. Usage BOOST queries player_game_logs directly
`get_usage_boost_players()` runs `SELECT ... GROUP BY player_name ORDER BY avg_min DESC LIMIT 2`
against the sport's SQLite DB. Only fires at `motivation >= 0.75`.

### 9. Caching
File cache: `PEGASUS/data/situational_cache/{sport}_{date}_standings.json`
In-process: `_standings_cache` dict keyed by `(sport, date)`. One file per date — stale
the next day automatically.

### 10. MLB: no-op in 2026 (April = all teams have hope)
`_fetch_mlb_standings()` returns `{}`. All MLB picks → `NORMAL / 0.0 / ''`. No API calls.

### 11. 2027 file: Layer 2 — Minutes Deviation Signal
The `PEGASUS/2027/intel.py` adds a second signal layer on top of standings:
```python
deviation = avg_minutes_last_5 - avg_minutes_season
```
- `deviation >= +4` → coach leaning hard → nudge motivation UP toward HIGH_STAKES
- `deviation <= -4` → rest/load management → nudge motivation DOWN toward DEAD_RUBBER
- Nudge is capped at ±0.15 so standings remain the primary signal
- Implemented in `get_minutes_deviation()` (per-player) and `get_team_minutes_deviation_summary()` (batch)
- MLB uses plate appearances (PA) as the proxy column — detects rest-day elimination during playoff hunt
- Pitchers: skip Layer 2 entirely (rotation is fixed every 5 days regardless of stakes)

### 12. 2027 MLB stakes window
MLB standings signal is suppressed before the last ~35 games (~late August). Before that,
`_fetch_mlb_standings()` returns `{}` and all MLB flags default to NORMAL. This is correct:
in April/May, no team is realistically out of it. The gate is date-based, not standings-based.

---

## Live Validation Results (April 15, 2026)

### NBA — playoffs in progress
| Team | Motivation | Flag | Correct? |
|------|-----------|------|---------|
| LAL (4-seed, games_remaining=0) | 1.00 | HIGH_STAKES | Yes |
| GSW (10-seed play-in, left=0) | 1.00 | HIGH_STAKES | Yes |
| OKC (1-seed, games_remaining=0) | 1.00 | HIGH_STAKES | Yes |
| SAC (14-seed, eliminated) | 0.10 | ELIMINATED | Yes |
| MEM (13-seed, eliminated) | 0.10 | ELIMINATED | Yes |

### NHL — 1 game left in regular season
| Team | Motivation | Flag | Correct? |
|------|-----------|------|---------|
| BOS (clinched X, div-4) | 0.45 | REDUCED_STAKES | Yes |
| TOR (eliminated) | 0.10 | ELIMINATED | Yes |
| COL (Presidents' Trophy P, div-1) | 0.20 | DEAD_RUBBER | Yes |
| NSH (eliminated) | 0.10 | ELIMINATED | Yes |
| OTT (clinched X, div-5) | 0.45 | REDUCED_STAKES | Yes |

---

## Exact Next Step (start of Session 4)

**Step 4: NHL ML Audit**

### Read FIRST

1. `PEGASUS/PLAN.md` Step 4 section (lines ~224–251) — full audit spec
2. `ml_training/model_registry/nhl/` — list what models actually exist:
   - Version: v20260325_003, type: LogisticRegression, 13 prop/lines
   - Files per prop: `{prop}_{line}_model.joblib`, `{prop}_{line}_metadata.json`
   - May also have `{prop}_{line}_calibrator.joblib` (isotonic)
3. `ml_training/train_models.py` — understand feature vector format + output columns
4. Memory note: NHL models were TRAINED but NEVER ACTIVATED. `v2_config.py` has
   `MODEL_TYPE = "statistical_only"`. Verify this is still true before building.

### Build

`PEGASUS/pipeline/nhl_ml_reader.py` with:
```python
def load_nhl_model(prop: str, line: float) -> Optional[dict]:
    """Load model + calibrator for a prop/line. Returns None if missing."""

def predict_nhl_ml(player_features: dict, prop: str, line: float) -> Optional[float]:
    """Run features through model. Returns calibrated probability or None."""

def audit_nhl_models(lookback_days: int = 30) -> dict:
    """Shadow-mode audit: run models against recent graded predictions."""
```

### Decision gate after audit

- PASS (beats always-UNDER by >3%, no single feature >70%, calibration reasonable):
  → Activate 60/40 ML/stat blend in `PEGASUS/pipeline/pick_selector.py`
  → Do NOT touch `v2_config.py` in existing system
- FAIL:
  → Leave statistical-only in PEGASUS too
  → Note retrain target: Oct/Nov 2026

---

## Prompt for Session 4 Agent

```
I'm continuing work on PEGASUS — a parallel read-only prediction system built on top
of the existing SportsPredictor orchestrator. PEGASUS lives entirely in PEGASUS/ and
never modifies any existing files outside that directory.

Start by reading:
1. PEGASUS/bookmarks/bookmark-03.md — session 3 results + exact next steps
2. PEGASUS/PLAN.md Step 4 section (lines ~270–305 after the Step 3 Addendum insertion)

Steps 1, 2, and 3 are fully complete:
- Calibration audit ran, all 3 sports PASS (NHL, NBA, MLB)
- Situational intelligence engine built (flags.py + intel.py)
- 2027 edition built with Layer 2 minutes deviation signal
- PLAN.md Step 3 Addendum written

Today's task is Step 4: NHL ML Audit.

Key facts before writing any code:
- NHL ML models exist at ml_training/model_registry/nhl/ (v20260325_003, LR, 13 props)
- These models were TRAINED but NEVER ACTIVATED — v2_config.py has MODEL_TYPE="statistical_only"
- PEGASUS/pipeline/ directory already exists (created in Step 1) but is empty
- All SQLite DBs are READ-ONLY from PEGASUS scripts — never INSERT/UPDATE/DELETE

Build PEGASUS/pipeline/nhl_ml_reader.py with three functions:
1. load_nhl_model(prop, line) — load model + optional calibrator from registry
2. predict_nhl_ml(features_dict, prop, line) — run features, return calibrated probability
3. audit_nhl_models(lookback_days=30) — shadow-mode: compare ML vs statistical vs actual
   outcomes on last 30 days of graded predictions from nhl_predictions_v2.db

The audit must produce a pass/fail verdict per the three-check gate in PLAN.md Step 4:
- Does NHL LR beat always-UNDER baseline by >3%?
- Does feature importance look sane (no single feature >70%)?
- Are probabilities reasonably calibrated?

After the audit runs, report results and ask whether to proceed to Step 5 or flag issues.
```
