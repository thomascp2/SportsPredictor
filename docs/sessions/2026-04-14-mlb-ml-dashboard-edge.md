# MLB ML Dashboard — Line Type + Edge (2026-04-14)

## What was added

`dashboards/cloud_dashboard.py` → `_render_mlb_ml_comparison()`

### Two new columns

| Column | Source | Meaning |
|---|---|---|
| **Line Type** | `mlb/database/mlb_predictions.db predictions.odds_type` | `standard` / `goblin` / `demon` — pulled from the stat model row that matches player+prop+line. Orange for goblin, purple for demon. Defaults to `standard` if no stat match. |
| **ML Edge** | Computed: `(ML P(Over) − break_even[odds_type]) × 100` | How far above/below break-even the ML probability sits, in percentage points. Green ≥ 0, bold green ≥ +10, red < 0. |

### Existing "Line" column
The **Line** column is the **prop line value** (e.g. `0.5`, `1.5`, `2.5` for hits) — the numeric threshold a player must exceed for an OVER to hit. It comes from `PROP_LINES` dict in the dashboard, not from PrizePicks directly. These are the standard lines the ML models were evaluated against.

### Break-even table (matches smart_pick_selector.py / supabase_sync.py)
| Line Type | Break-even |
|---|---|
| standard | 52.4% (110/210) |
| goblin   | 76.2% (320/420) |
| demon    | 45.5% (100/220) |

## Data flow
1. Stat model SQL now selects `COALESCE(odds_type, 'standard') AS odds_type`
2. Row-builder looks up `odds_type` from the stat match (defaults `standard` if no match)
3. `break_even = _BREAK_EVEN[odds_type]`
4. `ml_edge = (ml_p_over − break_even) × 100`
5. Styled: edge green/red, line type orange/purple

## Limitation
`Line Type` is only populated when a stat model row matches (same player + prop + line). If the ML model covers a line the stat model didn't predict, `odds_type` defaults to `standard` and edge uses the standard break-even.
