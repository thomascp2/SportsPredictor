# NHL ML Retrain Master Plan — 2026-27 Season
**Written: 2026-04-15 | Source: PEGASUS Session 4 Post-Mortem**

> **Why this document exists**: We ran a full shadow audit of the v20260325_003 NHL ML
> models in April 2026 and found they were actively corrupting live predictions. Every
> shot-over pick for active players was being predicted UNDER because of a feature naming
> bug and a broken ML model that should never have shipped. This doc is the complete
> specification for doing it right next season — so we can put our name on these picks.

---

## Part 1: What Went Wrong in 2025-26 (Don't Repeat This)

### The Short Version

The ML models were flipped on in production (`USE_ML = True`, line 70 of V6) while
simultaneously being broken in two separate ways. The result: every active shooter in the
NHL was being predicted UNDER on shots_1.5 with high confidence, even players averaging
3+ shots per game. Live picks were directionally wrong for 3+ weeks before the audit
caught it.

### Root Cause #1 — Feature Name Mismatch (The Technical Bug)

The stat model stores features using the `f_*` prefix convention:
```
f_l10_avg = 3.2  (player's last-10 average shots)
f_season_avg = 2.9
```

The ML model was trained on older data that used the unprefixed names:
```
sog_l10 = 3.2
sog_season = 2.9
```

When the ML model ran in production, it looked for `sog_l10` and found nothing.
`_prepare_features` defaulted it to **0.0**. So every player looked like they averaged
0 shots per game. Z-score = (1.5 - 0) / std = huge positive → P(OVER) near zero →
everyone predicted UNDER with confidence.

**Fixed 2026-04-15**: `_prepare_features` in `production_predictor.py` now tries
`f_{name}` and `name[2:]` fallbacks before defaulting to 0.0.

### Root Cause #2 — Corrupted Training Data Window

The stat model itself developed a bug around March 16, 2026 — independently of ML. It
started predicting 100% UNDER on shots_1.5 and points_0.5 even though OVER was winning
57% and 51% of the time respectively. The ML retrain happened March 25 — 9 days AFTER
the stat model broke.

That means the last 3 weeks of the 90-day training window contained corrupted
`f_prob_over` values. The ML model was trained on broken signal, then deployed against
broken signal. Nothing about it was clean.

### Root Cause #3 — Wrong Baseline in Training Evaluation

`train_models.py` was comparing ML accuracy to the statistical model's accuracy on the
test set — not to always-majority-class. When the stat model was broken during the test
period (45.4% accuracy on shots_1.5), the ML model at 57.9% looked like a +12.6%
improvement. 

The real baseline — always-OVER, since OVER wins 57% of shots_1.5 — would have been
57.0%. ML at 57.9% is +0.9%. Not worth shipping.

**Fixed 2026-04-15**: `train_models.py` now uses `max(OVER rate, UNDER rate)` as the
baseline. A model must beat always-majority-class, not a broken stat model.

### Root Cause #4 — f_prob_over as a Feature (The Feedback Loop)

Every NHL model included `f_prob_over` — the statistical model's own probability — as
one of its top features. This creates a circular dependency:

```
stat_model → f_prob_over → ML model → prediction
```

The ML model cannot generate alpha if its primary input is the stat model's own output.
When the stat model is wrong, the ML inherits and amplifies that wrongness. When the
stat model is right, the ML just confirms it. Either way, you're not adding information.

**Fixed 2026-04-15**: `f_prob_over` excluded from `get_feature_columns` in
`train_models.py`. ML must build signal from raw features only.

### Root Cause #5 — No Direction Sanity Check

Nobody noticed for 3+ weeks because there was no automated alert that fires when a
normally-competitive prop goes to 100% in one direction. shots_1.5 was 100% UNDER from
March 16 to April 15 with no alert.

**Not yet built** — this is Priority 1 before the 2026-27 season opens. See Part 4.

---

## Part 2: The Full October 2026 Retrain Protocol

### Step 0 — Confirm the Stat Model is Clean (Do This First, No Exceptions)

Before touching ML, verify the stat model is healthy. Run this query against the
NHL DB after a full week of predictions have been generated:

```python
import sqlite3
conn = sqlite3.connect('nhl/database/nhl_predictions_v2.db')
rows = conn.execute('''
    SELECT prop_type, line,
           ROUND(AVG(CASE WHEN prediction="OVER" THEN 1.0 ELSE 0.0 END), 3) as stat_over_pct,
           ROUND(AVG(CASE WHEN o.actual_outcome="OVER" THEN 1.0 ELSE 0.0 END), 3) as actual_over,
           COUNT(*) as n
    FROM predictions p
    JOIN prediction_outcomes o ON p.id = o.prediction_id
    WHERE o.game_date >= date("now", "-14 days")
      AND prop_type IN ("shots", "points")
      AND o.actual_outcome IS NOT NULL
    GROUP BY prop_type, line
    ORDER BY prop_type, line
''').fetchall()
for r in rows:
    gap = abs(r[2] - r[3])
    flag = " << INVESTIGATE" if gap > 0.25 else ""
    print(f"{r[0]} {r[1]}: stat_OVER={r[2]:.1%}  actual_OVER={r[3]:.1%}  gap={gap:.1%}{flag}")
```

**Gate**: No prop/line should have a gap > 25% between stat_over_pct and actual_over_pct.
If any do, the stat model has a bug. Fix it before training. Do not train on corrupted
signal.

Expected healthy values:
- `shots 1.5`: stat_OVER ~60-70%, actual_OVER ~55-60%
- `points 0.5`: stat_OVER ~45-60%, actual_OVER ~48-54%
- `hits 0.5`: stat_OVER ~45-55%, actual_OVER ~50-58%
- `blocked_shots 0.5`: stat_OVER ~35-50%, actual_OVER ~38-44%

---

### Step 1 — Data Minimum Requirements

Don't train until these thresholds are met. Check with:

```bash
python orchestrator.py --sport nhl --mode once --operation ml-check
```

| Prop / Line | Min Graded Rows | Reason |
|-------------|----------------|--------|
| shots 1.5   | 2,500          | Competitive line, enough variation to learn |
| shots 2.5   | 2,000          | Moderate skew, need sample depth |
| points 0.5  | 2,000          | Near-even split, learnable |
| hits 0.5    | 2,000          | New prop, near-even, physically predictable |
| blocked_shots 0.5 | 1,500     | Smaller player pool, more concentrated |

**Do not train** on these lines (degenerate — new code auto-skips them):
- points 1.5 (88% UNDER), shots 3.5+ (87%+ UNDER)
- hits 2.5 (85% UNDER), blocked_shots 1.5 (81% UNDER)
- Any line where majority class > 75% — the guard in `train_models.py` will skip these

---

### Step 2 — Feature Requirements

Every training row must have full opponent features. Verify coverage before training:

```python
import sqlite3, json
conn = sqlite3.connect('nhl/database/nhl_predictions_v2.db')
rows = conn.execute("""
    SELECT prop_type, line,
           COUNT(*) as total,
           SUM(CASE WHEN features_json LIKE '%f_opp_allowed_l10%' THEN 1 ELSE 0 END) as has_opp,
           ROUND(AVG(CASE WHEN features_json LIKE '%f_opp_allowed_l10%' THEN 1.0 ELSE 0.0 END)*100, 1) as opp_pct
    FROM predictions p
    JOIN prediction_outcomes o ON p.id = o.prediction_id
    WHERE o.actual_outcome IS NOT NULL
    GROUP BY prop_type, line
    ORDER BY prop_type, line
""").fetchall()
for r in rows:
    flag = " << LOW" if r[4] < 80 else ""
    print(f"{r[0]} {r[1]}: {r[4]:.0f}% have opp features ({r[2]:,} rows){flag}")
```

**Gate**: Each prop/line must have >85% opponent feature coverage. Rows without opponent
features train the model on incomplete data and should be excluded or backfilled.

---

### Step 3 — Tag and Exclude Corrupted Data

The predictions from March 16 – April 15, 2026 have corrupted `f_prob_over` values
(stat model was outputting 100% UNDER for shots/points while OVER was winning). These
rows are in the DB and WILL be included in training unless excluded.

Add a filter to the training data loader to exclude this window:

```python
# In ml_training/train_models.py, _load_nhl_data():
# Exclude known-corrupted stat model period
query = """
    SELECT ...
    FROM predictions p
    JOIN prediction_outcomes o ON p.id = o.prediction_id
    WHERE p.prop_type = ? AND p.line = ?
      AND NOT (o.game_date BETWEEN '2026-03-16' AND '2026-04-15')
    ORDER BY p.game_date
"""
```

Alternatively: only train on predictions generated with `USE_ML = False`
(model_version = 'statistical_v2.2_asym'), which filters out the ensemble period
automatically.

---

### Step 4 — Run the Retrain

```bash
# From SportsPredictor root
python ml_training/train_models.py --sport nhl --all
```

The fixed `train_models.py` will:
1. ✅ Skip degenerate lines (>75% majority class) automatically
2. ✅ Exclude `f_prob_over` from features automatically
3. ✅ Use always-majority-class as baseline
4. ✅ Deduplicate f_* vs unprefixed features
5. ✅ Apply 60/15/10/15 temporal split with no leakage
6. ✅ Calibrate on the held-out calibration set only

Watch for these warning signs in the output:
- `improvement_over_baseline < 0.03` on any line → model is not adding value, skip it
- Any single feature with importance > 50% → likely overfit, investigate
- Test accuracy < training accuracy by > 5% → overfitting

---

### Step 5 — Run the Shadow Audit Before Activating

**Do not set `USE_ML = True` until this passes.**

```bash
# From SportsPredictor root
python PEGASUS/pipeline/nhl_ml_reader.py 30
```

This runs the three-gate audit:
1. Does the model beat always-majority-class by >3% in the last 30 days?
2. Does feature importance look sane (no single feature >70%)?
3. Are probabilities calibrated (bucket hit rates within ±10% of predicted)?

**Only proceed to Step 6 if the audit returns PASS.**

If FAIL: do not activate ML. Leave `USE_ML = False`, note which lines failed and why,
plan a targeted fix. Do not activate a failing model "to see what happens" — we saw what
happens.

---

### Step 6 — Activate and Monitor for 2 Weeks

```python
# nhl/scripts/generate_predictions_daily_V6.py, line 70
USE_ML = True   # Only set this after Step 5 PASSES
```

After activating:
- Run the direction sanity check daily (see Part 4) for 14 days
- Run the shadow audit weekly: `python PEGASUS/pipeline/nhl_ml_reader.py 7`
- If weekly audit improvement drops below 0% at any point: flip `USE_ML = False`
  immediately. Do not wait for another 3-week accumulation of wrong picks.

---

## Part 3: Hits and Blocked Shots — Include From Day One

These props were added March 8, 2026 and have ~800-900 graded rows each going into the
off-season. They are physically-driven props and the stat model is behaving correctly
for them (no flip bug observed). They represent genuine edge because:

- **Hits**: Role-based and consistent. A physical fourth-liner who logs 14-16 minutes
  hits 3-4 times every game regardless of score. PrizePicks prices these based on
  season averages — they don't distinguish between a physical defensive forward and a
  skill winger with similar ice time. Game-script sensitivity (trailing teams hit more
  in desperation), opponent defensive structure, and situational context are all
  detectable and not in their price.

- **Blocked shots**: Defensive defensemen are machines. A D-man who blocks shots does
  it every night because of where he stands, not because of matchup luck. High-volume
  shooting opponents create more block opportunities. These patterns are stable and
  predictable at a level PP lines don't fully reflect.

### Data collection for 2026-27:

Start from **game 1 of the 2026-27 season**. Same priority as points and shots.

### ML training eligibility:

| Prop | Target training start | Min rows needed |
|------|----------------------|----------------|
| hits_0.5 | January 2027 | 2,000 graded |
| hits_1.5 | March 2027 (if data supports) | 2,000 graded |
| blocked_shots_0.5 | February 2027 | 1,500 graded |
| hits_2.5 | Skip — degenerate (85% UNDER) | N/A |
| blocked_shots_1.5 | Skip — degenerate (81% UNDER) | N/A |

### Feature additions needed:

Beyond the standard rolling averages, add before training:

- `f_physical_role` — binary: player averages >2.5 hits/game season (identifies
  physical players who are structurally consistent hitters)
- `f_avg_toi_vs_line` — ice time relative to line threshold (more ice = more
  opportunities to hit/block)
- `f_opp_shot_volume_l10` — opponent's recent shots-per-game (creates block opportunities)
- `f_is_defenseman` — position flag, critical for blocked shots model
- `f_trailing_game_pct_l10` — how often player's team was trailing in recent games
  (trailing teams ice physicality more, get more blocked shot situations)

---

## Part 4: The Self-Auditing System (Build Before Opening Night)

This is what was missing. The March 16 stat model bug ran silently for 30 days.
With this system in place, it would have fired a Discord alert the same night.

### Piece 1 — Direction Sanity Check (post-prediction hook)

Add to `orchestrator.py` after every prediction run. Fires a Discord alert if any
competitive prop goes lopsided:

```python
def check_prediction_direction_sanity(sport: str, game_date: str, db_path: str,
                                       webhook_url: str) -> list[str]:
    """
    After prediction generation, check that no competitive prop is > 85% in one direction.
    Competitive props = those where historical majority is < 70%.
    Returns list of warning strings; fires Discord alert if any found.
    """
    import sqlite3, requests
    from datetime import date

    # Lines that are EXPECTED to be extreme (skip these)
    KNOWN_EXTREME = {('points', 1.5), ('points', 2.5), ('shots', 3.5),
                     ('hits', 2.5), ('blocked_shots', 1.5)}

    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT prop_type, line,
               COUNT(*) as n,
               ROUND(AVG(CASE WHEN prediction='OVER' THEN 1.0 ELSE 0.0 END), 3) as over_pct
        FROM predictions
        WHERE game_date = ?
        GROUP BY prop_type, line
        HAVING n >= 10
        ORDER BY prop_type, line
    """, (game_date,)).fetchall()
    conn.close()

    warnings = []
    for prop_type, line, n, over_pct in rows:
        if (prop_type, line) in KNOWN_EXTREME:
            continue
        under_pct = 1 - over_pct
        if over_pct > 0.85 or under_pct > 0.85:
            dominant = "OVER" if over_pct > 0.85 else "UNDER"
            dominant_pct = over_pct if dominant == "OVER" else under_pct
            msg = (f"[SANITY ALERT] {sport.upper()} {prop_type} {line}: "
                   f"{dominant_pct:.0%} predicted {dominant} ({n} predictions). "
                   f"Expected <85%. Possible stat model bug — investigate before "
                   f"these reach users.")
            warnings.append(msg)

    if warnings and webhook_url:
        text = "\n".join(warnings)
        requests.post(webhook_url, json={"content": f"```{text}```"}, timeout=10)

    return warnings
```

Wire this into the orchestrator's prediction pipeline where it already posts pick counts
to Discord — run it immediately after the prediction batch completes.

---

### Piece 2 — Weekly ML Shadow Audit (Automated)

`PEGASUS/pipeline/nhl_ml_reader.py` already has `audit_nhl_models()`. Schedule this
to run every Sunday night after the grading cron, posting results to Discord:

```python
# In orchestrator.py, after Sunday grading completes:
def run_weekly_ml_audit(sport: str, webhook_url: str):
    """Run PEGASUS shadow audit and post verdict to Discord."""
    if sport != 'nhl':
        return  # Extend to NBA when NBA ML is reactivated

    import sys
    sys.path.insert(0, str(PEGASUS_PATH / 'pipeline'))
    from nhl_ml_reader import audit_nhl_models

    results = audit_nhl_models(lookback_days=14)
    summary = results.get('summary', {})

    verdict = "PASS" if summary.get('overall_pass') else "FAIL"
    rec = summary.get('recommendation', '')
    n_pass = summary.get('n_props_pass', 0)
    n_fail = summary.get('n_props_fail', 0)

    lines = [
        f"[WEEKLY ML AUDIT] NHL — {verdict}",
        f"Props: {n_pass} passing / {n_fail} failing",
        f"Action: {rec}",
    ]
    for prop_str in summary.get('failing_props', []):
        lines.append(f"  FAIL: {prop_str}")

    # Auto-disable ML if audit fails during active season
    if verdict == "FAIL" and USE_ML_FLAG_IS_TRUE:
        lines.append("!! AUTO-DISABLING ML: USE_ML set to False. Re-enable after investigation.")
        # Write USE_ML = False to config or set flag

    if webhook_url:
        requests.post(webhook_url, json={"content": "```" + "\n".join(lines) + "```"})
```

---

### Piece 3 — What to Do When an Alert Fires

**If the direction sanity check fires:**

1. Do not wait. Check immediately:
   ```bash
   python -c "
   import sqlite3
   conn = sqlite3.connect('nhl/database/nhl_predictions_v2.db')
   rows = conn.execute(\"SELECT player_name, prediction, probability FROM predictions WHERE prop_type='shots' AND line=1.5 AND game_date=date('now') LIMIT 10\").fetchall()
   for r in rows: print(r)
   "
   ```

2. If all predictions are in one direction for a normally-even prop:
   - Check `USE_ML` in `generate_predictions_daily_V6.py` — if True, set to False
   - Check the stat model: run the direction gap query from Step 0
   - Check recent changes to `statistical_predictions_v2.py` via `git log`

3. Set `USE_ML = False` as a precaution until root cause is identified

**If the weekly ML audit fails:**

1. Run the audit with verbose output: `python PEGASUS/pipeline/nhl_ml_reader.py 30`
2. Look at `improvement_over_under` for each prop — is it negative?
3. Look at calibration buckets — are mid-range predictions hitting wrong?
4. If improvement < 0 on any prop: that model is actively hurting picks, disable immediately
5. If improvement 0-3%: marginally useless, disable until retrain
6. Document findings in `PEGASUS/docs/`

---

## Part 5: The Philosophy — What "Our Stamp of Approval" Actually Means

The public has stat models. Every Twitter handicapper has a spreadsheet that computes
rolling averages. Charging for picks that come from the same math that's free online
is not a business — it's noise.

**The edge that justifies a premium product lives here:**

### Context the public can't see at scale

PP sets lines based on player averages. They cannot simultaneously evaluate back-to-back
fatigue, cross-timezone travel, seeding stakes, opponent defensive structure adjustments
for game script, and minutes deviation signals for 100 players on a Tuesday night. We can
— and PEGASUS is built for exactly this (situational intelligence engine is in Step 3).

A player averaging 3.0 shots per game on a normal night might average 1.8 shots on a
back-to-back after a cross-country flight against a defensive-style team with nothing to
play for in a deadrubber game. PP still has him at 2.5 shots. That's an edge.

### Player-specific deviation patterns

Some players are systematically underpriced in certain situations. A physical winger
who goes OVER his hit line 73% of the time when his team is trailing (desperation = more
physical play) but only 42% when leading. A defensive defenseman who blocks more shots
in tight games than in blowouts. These patterns exist, they're stable, and PP pricing
doesn't fully adjust for them.

ML is how you find these patterns at scale. But only if you train on:
1. Clean data from a correctly-functioning stat model
2. Features that capture CONTEXT, not just rolling averages that PP already has
3. An honest evaluation framework that measures real improvement over the true baseline

### What passes the bar

A model earns activation status (`USE_ML = True`) if and only if it:
- Beats always-majority-class by >5% in walk-forward validation (not just one test slice)
- Has calibrated probabilities (what we say is 65% actually hits ~65%)
- Passes the PEGASUS shadow audit on fresh out-of-sample data
- Has no single feature dominating >50% of importance (that's a model that learned one trick, not general patterns)

If it doesn't clear all four, it doesn't ship. We use the stat model, which is honest
about what it knows. A bad ML model is worse than no ML model — the March 2026 incident
proved this.

---

## Part 6: Key Files and Their Roles (2026-27 Reference)

| File | What It Does | Touch for |
|------|-------------|-----------|
| `nhl/scripts/generate_predictions_daily_V6.py` | Main prediction runner | Set `USE_ML` flag here — nowhere else |
| `nhl/scripts/statistical_predictions_v2.py` | Stat model engine | Fix prediction logic bugs here |
| `nhl/features/continuous_feature_extractor.py` | Shot features | Add new features here |
| `ml_training/train_models.py` | Train all models | Retrain process, methodology |
| `ml_training/production_predictor.py` | ML inference in production | Ensemble logic, degeneracy checks |
| `PEGASUS/pipeline/nhl_ml_reader.py` | Shadow audit tool | Run this before and after any ML change |
| `PEGASUS/docs/nhl_ml_post_mortem.md` | Full 2025-26 post-mortem | Reference for what went wrong |
| `PEGASUS/2027/NHL_RETRAIN_MASTERPLAN.md` | This file | The plan for doing it right |

---

## Summary Checklist — October 2026

```
PRE-TRAINING
[ ] Stat model direction sanity check passes (gap < 25% for all competitive lines)
[ ] Corrupted data window (Mar 16 - Apr 15 2026) excluded from training rows
[ ] Each competitive prop/line has 2,000+ graded rows
[ ] Opponent feature coverage > 85% for all training rows
[ ] Direction sanity check alert is wired into orchestrator (automated)
[ ] Weekly audit cron is scheduled

TRAINING RUN
[ ] python ml_training/train_models.py --sport nhl --all
[ ] Degenerate lines auto-skipped (check output for SKIP notices)
[ ] No model has improvement_over_baseline < 0 (if so, it will not ship anyway)
[ ] Feature list contains NO f_prob_over (check metadata.feature_names in output)
[ ] All lines include hits_0.5 and blocked_shots_0.5 if sample thresholds met

POST-TRAINING AUDIT
[ ] python PEGASUS/pipeline/nhl_ml_reader.py 30
[ ] All shipping props: PASS on 3-check gate (beats baseline >3%, features sane, calibrated)
[ ] No single feature with importance > 50%
[ ] Calibration buckets within 10% of predicted rate

ACTIVATION
[ ] Set USE_ML = True in generate_predictions_daily_V6.py
[ ] Monitor direction sanity check daily for 14 days
[ ] Run weekly audit for 4 weeks post-activation
[ ] If any weekly audit returns FAIL: USE_ML = False immediately, investigate
```
