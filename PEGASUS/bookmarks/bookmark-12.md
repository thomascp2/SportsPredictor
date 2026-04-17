# PEGASUS Bookmark — Session 12 (End-of-Session)
**Date: 2026-04-15 | Steps 1–10 COMPLETE | Step 11 Gated (Oct 2026)**

---

## What Was Done in Session 12

Pure analysis session — no code written. Two deep-dive investigations:

1. **Counterfactual Analysis** — Would the NHL stat model (stat_v2.2_asym) have been profitable if ensemble_ml60 had never been deployed?
2. **Data Usability** — How much clean NHL training data exists for the Oct 2026 retrain?

---

## Session 12 Findings

### 1. COUNTERFACTUAL ANALYSIS — stat_v2.2_asym in isolation

**Query**: prediction_outcomes JOIN predictions WHERE model_version = 'statistical_v2.2_asym'
**Total graded**: 33,356 rows

#### Overall Performance

| Metric | Value |
|---|---|
| Overall hit rate | **69.0%** |
| Always-UNDER baseline (this window) | **64.0%** |
| Net edge vs baseline | **+5.0pp** |
| UNDER accuracy | **74.8%** (22,234 picks) |
| OVER accuracy | **57.4%** (11,122 picks) |

> Note: always-UNDER baseline in this window is 64.0%, NOT the previously-cited 69.2%. The 69.2% figure was from all data including different date ranges/seasons. The clean window (Nov 2025 – Jan 2026) had a lower natural under rate.

#### By Prop + Line (key PP combos, standard break-even = 52.38%)

| Prop | Line | Direction | N | Hit% | Edge | Profitable? |
|---|---|---|---|---|---|---|
| points | 0.5 | OVER | 3,261 | 54.7% | +2.3pp | YES (marginal) |
| points | 0.5 | UNDER | 3,337 | 56.3% | +3.9pp | YES |
| points | 1.5 | OVER | 114 | 27.2% | -25.2pp | **NO** (n=114, ignore) |
| points | 1.5 | UNDER | 6,312 | 84.3% | **+31.9pp** | **ELITE** |
| shots | 1.5 | OVER | 5,191 | 63.3% | **+10.9pp** | **YES** |
| shots | 1.5 | UNDER | 1,407 | 54.8% | +2.4pp | YES (marginal) |
| shots | 2.5 | OVER | 1,914 | 49.3% | -3.1pp | **NO** |
| shots | 2.5 | UNDER | 4,684 | 69.9% | **+17.5pp** | **STRONG** |
| shots | 3.5 | OVER | 385 | 39.0% | -13.4pp | **NO** |
| shots | 3.5 | UNDER | 6,213 | 82.4% | **+30.0pp** | **ELITE** |

#### Counterfactual Verdict

**YES, the stat model was profitable.** If USE_ML had been False all season:
- Strong UNDER edges on points 1.5, shots 2.5, shots 3.5 — all elite (+17 to +32pp)
- shots 1.5 OVER was genuinely profitable at +10.9pp
- **Problem areas**: shots 2.5 OVER (-3.1pp), shots 3.5 OVER (-13.4pp) — model consistently wrong on high-line OVERs
- points 0.5 is borderline — barely beats break-even either direction

**Key insight**: The stat model correctly skews UNDER on high shot lines. The OVER predictions on shots 2.5+ were weak. For Oct 2026 retrain, consider an OVER suppression guard for shots 2.5/3.5 (similar to the NBA threes OVER guard).

#### Our UNDER picks vs Always-UNDER baseline (key lines)

| Prop | Line | Our UNDER% | Always UNDER% | Delta |
|---|---|---|---|---|
| points | 0.5 | 56.3% | 50.9% | **+5.4pp** |
| points | 1.5 | 84.3% | 84.1% | +0.2pp |
| shots | 1.5 | 54.8% | 40.5% | **+14.3pp** |
| shots | 2.5 | 69.9% | 64.3% | **+5.6pp** |
| shots | 3.5 | 82.4% | 81.2% | +1.2pp |

The model adds meaningful alpha on shots 1.5 UNDER (+14.3pp) and points 0.5 UNDER (+5.4pp). On high lines (1.5/3.5), always-UNDER is already near the model's accuracy.

---

### 2. DATA USABILITY FOR OCT 2026 RETRAIN

#### Model Version Timeline
| Version | Date Range | Rows |
|---|---|---|
| statistical_v2 | Oct 15 – Nov 11, 2025 | 2,252 |
| statistical_v2.1 | Nov 12 – 16, 2025 | 3,456 |
| statistical_v2.1_fixed | Nov 17–18, 2025 | 1,340 |
| statistical_v2.1_opp | Nov 19, 2025 | 384 |
| **statistical_v2.2_asym** | **Nov 20, 2025 – Apr 15, 2026** | **34,712** |
| ensemble_ml60 | Jan 14 – Apr 15, 2026 | 22,454 (EXCLUDED from retrain) |
| statistical_v2.2_count_prop | Mar 15 – Apr 15, 2026 | 6,087 |

#### Clean Data for Main Prop/Line Combos (stat_v2.2_asym only, graded)

| Prop/Line | Clean Graded | Data Window | Retrain Status |
|---|---|---|---|
| points 0.5 | **6,598** | Nov 2025 – Jan 2026 | READY (2.2x target) |
| points 1.5 | **6,426** | Nov 2025 – Jan 2026 | READY (2.1x target) |
| shots 1.5 | **6,598** | Nov 2025 – Jan 2026 | READY (2.2x target) |
| shots 2.5 | **6,598** | Nov 2025 – Jan 2026 | READY (2.2x target) |
| shots 3.5 | **6,598** | Nov 2025 – Jan 2026 | READY (2.2x target) |
| shots 0.5 | 117 | Jan 2026 – present | STARVED (3.9% of target) |

**All 5 main PP prop/line combos exceed the 3,000 sample minimum — well above target.**

The clean window is Nov 20, 2025 → Jan 15, 2026 (~2 months). ensemble_ml60 took over main lines on Jan 14, 2026. The exclusion filter added in Session 11 (`train_models.py` excludes `ensemble_ml60`) is correct.

#### Retrain Action Plan for Oct 2026

1. **Use stat_v2.2_asym only** — already wired via exclusion filter in train_models.py
2. **Add OVER suppression guards** for shots 2.5 OVER, shots 3.5 OVER (both historically losers)
3. **shots 0.5 is a no-go** — only 117 clean samples, won't reach 3k before Oct 2026 retrain. Exclude from ML; keep stat-only.
4. **Data quality note**: 6,400 samples across 2 calendar months — model will need to generalize across full season; test for Jan-bias.
5. **Seasonal continuity**: Oct 2026 retrain will add 2026-27 season data starting Oct 2026. Combined with clean 2025-26 window → more robust.

---

## Architecture / Files Unchanged This Session

No code written this session. Reads were SQLite query-only (read-only).

Session 11 mobile integration (completed last session):
- `mobile/src/types/pegasus.ts` — PEGASUSPick interface
- `mobile/src/services/pegasus.ts` — fetch + adaptPegasusPickToSmartPick()
- `mobile/src/utils/constants.ts` — PEGASUS_API_URL (port 8600)
- `mobile/src/services/api.ts` — SmartPick extended with 7 PEGASUS optional fields
- `mobile/src/components/picks/PickCard.tsx` — situation pill, Book row, True EV badge

---

## Open Issues (updated)

| # | Issue | Severity | Action |
|---|---|---|---|
| 1 | `no such column: minutes_played` NBA intel USAGE_BOOST | Low | Fixed in intel.py (Session 11) |
| 2 | `pegasus_picks` Turso may need `implied_probability`/`true_ev` columns | Med | Run `ALTER TABLE pegasus_picks ADD COLUMN ...` on Turso console if sync fails |
| 3 | DK rate-limit on consecutive sport fetches | Low | Non-fatal. 3s interval mitigates. |
| 4 | NHL hits/blocked_shots not generating (V6 scope) | Low | Next season |
| 5 | MLB Turso smart-picks silent failure (production) | Low | Investigate when relevant |
| 6 | shots 2.5 OVER / shots 3.5 OVER are losing picks historically | Med | Add suppression guard in Oct 2026 retrain prep (similar to NBA threes OVER guard) |
| 7 | shots 0.5 data-starved (117 samples) | Low | No ML for shots 0.5; keep stat-only forever or threshold at 2k |

---

## Step 11 — Game Lines ML (GATED — Oct 2026)

Unchanged. Requires full 2026 season game-level data (pace, totals, back-to-backs).

---

## Agenda for Session 13

**Highest-value next steps:**

1. **DK Validation**: Wait for an active NBA playoff game day with DK lines open. Run `run_daily.py` and verify `implied_probability` is populating on picks from the JSON snapshot. Cross-check a few DK odds against the actual sportsbook line.

2. **End-to-end smoke test**: Full pipeline run with PEGASUS FastAPI live — start FastAPI on port 8600, hit `/picks/{today}?sport=nba&min_tier=T2-STRONG`, verify the mobile app (or curl) returns PEGASUS-enriched picks.

3. **Oct 2026 retrain prep (plant the seed)**: Write `PEGASUS/docs/nhl_retrain_oct2026.md` capturing the shots 2.5/3.5 OVER suppression recommendations and clean data window notes from this session. Better to document now while fresh.

4. **Step 11 kickoff** (Oct 2026): Add game-level features (pace, O/U totals, back-to-back flags) to PEGASUS pick pipeline.

---

## Prompt for Session 13 Agent

```
I'm continuing work on PEGASUS — a parallel read-only prediction system built on top
of the existing SportsPredictor orchestrator. PEGASUS lives entirely in PEGASUS/ and
never modifies existing files outside that directory (Rule 2).

Steps 1-10 are COMPLETE. Mobile wiring (PEGASUS Option B) completed in Session 11.
Session 12 was pure analysis (counterfactual + data usability). No code written.

Start by reading:
1. PEGASUS/bookmarks/bookmark-12.md — current state + findings
2. PEGASUS/bookmarks/comprehensive_summary.md — full project context

Step 11 (Game Lines ML) is GATED until Oct 2026.

Recommended work for this session (pick one or discuss with user):

A. DK odds validation — run run_daily.py on an active NBA playoff game day
   and verify implied_probability is populating. Examine the JSON snapshot output.

B. End-to-end smoke test — start FastAPI on port 8600, call /picks/{today},
   verify PEGASUS-enriched pick fields (calibrated_probability, true_ev, etc.).

C. Write PEGASUS/docs/nhl_retrain_oct2026.md — document shots OVER suppression
   recommendations and clean data window findings from Session 12 analysis.

D. Any maintenance from open issues list in bookmark-12.md.

Do NOT touch: orchestrator.py, sync/, shared/, nba/, nhl/ scripts (read-only for analysis).
PEGASUS Iron Rule: all new files in PEGASUS/ only. Exception: mobile/src/ is allowed.
```
