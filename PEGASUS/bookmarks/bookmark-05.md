# PEGASUS Bookmark — Session 5
**Date: 2026-04-15**

---

## Completed This Session

- [x] Step 5: `PEGASUS/pipeline/mlb_ml_reader.py` — DuckDB reader + probability converter + CLI

---

## Files Created / Modified This Session

**PEGASUS (read-only analysis):**
```
PEGASUS/pipeline/mlb_ml_reader.py
PEGASUS/bookmarks/bookmark-05.md
```

No production files modified (Rule 2 intact).

---

## MLB ML Reader — Architecture Notes

### DuckDB Schema Discovery
`mlb_feature_store/data/mlb.duckdb` → `ml_predictions` table:
- Columns: `player_id, player_name, game_date, prop, predicted_value, model_version, created_at, actual_value, graded_at`
- `predicted_value` = XGBoost **regression output** (expected count), NOT a probability
- No `p_over` column, no `line` column
- 5,754 total rows; 921 rows for 2026-04-15 (3 None player_name rows filtered)

Props in DB:
| prop | n (today) | blend type |
|------|-----------|------------|
| hits | 280 | BLEND (60/40) |
| total_bases | 280 | BLEND (60/40) |
| home_runs | 280 | STAT_ONLY (Rule 5) |
| strikeouts | 27 | BLEND (60/40) |
| outs_recorded | 27 | BLEND (60/40) |
| walks | 27 | BLEND (60/40) |

### Design Decision: predicted_value → p_over conversion
Since DuckDB only stores regression means, `compute_ml_p_over(predicted_value, line, prop)` converts
them to P(stat > line) using the same distribution logic as `mlb/scripts/statistical_predictions.py`:
- **Poisson CDF**: hits, total_bases, home_runs, walks (count props)
- **Normal CDF**: strikeouts (sigma=1.8), outs_recorded (sigma=2.5) (approximately continuous)

Sigmas are fixed league-average estimates. They could be calibrated later with graded data.

### Validation Results (2026-04-15)
- Aaron Judge hits: predicted=1.66, P(>0.5)=0.810 — sensible
- Aaron Civale strikeouts: predicted=5.71, P(>4.5)=0.749 — sensible
- Aaron Civale outs_recorded: predicted=16.37, P(>17.5)=0.325 — sensible (17.5 outs = ~5.8 IP is a high bar)
- Aaron Judge home_runs: predicted=0.43, P(>0.5)=0.347 — stat-only, not blended

### Blend Logic (for pick_selector.py)
```python
# In pick_selector, for each MLB prop:
ml_data = get_today_mlb_ml_predictions(game_date)
key = (player_name, prop)

if key in ml_data and prop in BLEND_PROPS:
    pv = ml_data[key]['predicted_value']
    ml_p_over = compute_ml_p_over(pv, pp_line, prop)
    if ml_p_over is not None:
        final_prob = 0.60 * ml_p_over + 0.40 * stat_prob
    else:
        final_prob = stat_prob  # fallback
else:
    final_prob = stat_prob  # home_runs or unknown prop: stat-only
```

### Graceful Degradation
- DuckDB not found → return {}
- duckdb not installed → return {}
- Any query error → return {}
- Player not in ml_data → pick_selector uses stat_prob silently
- compute_ml_p_over for unknown prop → return None → pick_selector uses stat_prob

---

## Exact Next Step (start of Session 6)

**Step 6: PEGASUS Pick Selector**

Build `PEGASUS/pipeline/pick_selector.py`.

This is the heart of PEGASUS — it reads from all sources and outputs `PEGASUSPick` objects.

Read first:
1. `PEGASUS/PLAN.md` Step 6 section (lines ~320–380)
2. `shared/smart_pick_selector.py` — existing pick selector to understand current logic
3. `PEGASUS/pipeline/mlb_ml_reader.py` — just built; pick_selector uses this for MLB blend
4. `PEGASUS/pipeline/nhl_ml_reader.py` — NHL reader (FAIL verdict, stay statistical)
5. `PEGASUS/pipeline/situational/intel.py` — situational flags from Step 3

Sources pick_selector reads from (all read-only):
- Existing SQLite predictions (NHL/NBA/MLB) — today's generated picks
- `data/calibration_tables/{sport}.json` — built in Step 2
- `mlb_ml_reader.py` — MLB 60/40 blend (just built)
- NHL models: FAIL verdict → stay statistical
- `situational/intel.py` — flags from Step 3

Output: `PEGASUSPick` dataclass objects (see PLAN.md Step 6 spec for fields).
