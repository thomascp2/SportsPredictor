# TODO: NBA Shows Only T1-ELITE Picks on Dashboard

**Observed:** Mar 4, 2026

## Symptom

The "Today's Picks" tab on the cloud dashboard shows NBA picks exclusively in the T1-ELITE
tier, even when all filters are cleared (min_prob=50%, min_edge=0%, all tiers selected).
NHL shows a healthy spread of T1–T3 picks under the same conditions.

## Data

Supabase `daily_props` for NBA on 2026-03-04 has the full tier spread:

| Tier | Count |
|------|-------|
| T1-ELITE (≥75%) | 373 |
| T2-STRONG (70–75%) | 101 |
| T3-GOOD (65–70%) | 116 |
| T4-LEAN (55–65%) | 297 |
| T5-FADE (<55%) | 113 |

So T2 and T3 picks exist in Supabase, but they don't surface in the dashboard.

## Likely Causes to Investigate

1. **ML model probability clustering** — NBA models (79–99% accuracy on test set) may
   output probabilities that cluster at the extremes (low for one direction, very high
   for the other). Once you filter to the `OVER` or `UNDER` direction the model favors,
   most picks are ≥75%. NHL models have lower accuracy (59–85%) and produce a wider spread.

2. **`fetch_picks` hard limit** — `.limit(200)` ordered by `ai_probability DESC` means
   we always pull the top 200 by probability. If there are 373 T1-ELITE picks, those 200
   slots are filled entirely with T1 picks before any T2/T3 can appear.

3. **`ai_edge` and `ai_probability` correlation** — Any positive edge filter also
   tends to select high-probability picks, compressing toward T1-ELITE.

## Suggested Fix

Option A: Increase the `.limit(200)` to `.limit(500)` or remove the hard cap and rely
on Supabase's pagination instead. This would allow T2/T3 picks to appear.

Option B: Change the sort order for NBA to something other than pure probability DESC —
e.g., sort by edge DESC, which would surface T2/T3 picks with strong edges.

Option C: Accept that NBA model confidence naturally skews T1. Add a note to the dashboard
UI explaining that NBA picks reflect higher model certainty than NHL.

## Priority

Low — data is correct, picks are usable. Visual parity with NHL is nice-to-have.
