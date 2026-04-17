"""
PEGASUS Calibration Audit
=========================
The math checkpoint. Nothing ships until this passes.

Checks per sport:
  A. Always-UNDER Baseline  — informational: overall accuracy vs naive (not the gate)
  B. Reliability Diagram     — are probabilities well-calibrated?
  C. Tier Performance        — do higher tiers actually outperform?
  D. Brier Score             — calibration quality vs naive baseline
  E. OVER/UNDER Directional  — surface UNDER bias explicitly
  F. Profitability Matrix    — THE GATE: per (direction × odds_type), T1-T3 picks only,
                               hit rate vs break-even. This is the seal-of-approval check.

Run:
  python PEGASUS/calibration/audit.py
  python PEGASUS/calibration/audit.py --sport nhl
  python PEGASUS/calibration/audit.py --sport nba
  python PEGASUS/calibration/audit.py --sport mlb
"""

import argparse
import json
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path

# Make config importable when run from repo root or PEGASUS dir
_here = Path(__file__).resolve().parent
_pegasus_root = _here.parent
_repo_root = _pegasus_root.parent
if str(_pegasus_root) not in sys.path:
    sys.path.insert(0, str(_pegasus_root))
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from config import (
    NHL_DB, NBA_DB, MLB_DB,
    CALIBRATION_TABLES_DIR, REPORTS_DIR,
    MIN_REAL_EDGE, MIN_SAMPLE_N, MIN_BUCKET_N,
    BREAK_EVEN, TIER_THRESHOLDS,
    SPORTS,
)

# Tiers that count as "approved" picks we surface to consumers
APPROVED_TIERS = {"T1-ELITE", "T2-STRONG", "T3-GOOD"}
# Minimum edge above break-even for a (direction, odds_type) combo to earn the seal
MIN_COMBO_EDGE = 0.03   # 3 percentage points
# Minimum n of approved-tier picks in this combo to draw conclusions
MIN_COMBO_N = 30


# ── DB connectors ─────────────────────────────────────────────────────────────

DB_PATHS = {
    "nhl": NHL_DB,
    "nba": NBA_DB,
    "mlb": MLB_DB,
}


def _connect(sport: str) -> sqlite3.Connection:
    path = DB_PATHS[sport]
    if not path.exists():
        raise FileNotFoundError(f"{sport} database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ── Schema note ───────────────────────────────────────────────────────────────
# NHL prediction_outcomes:
#   prediction_id → predictions.id
#   outcome       = HIT / MISS
#   prediction    = OVER / UNDER  (direction the model chose)
#   odds_type     = standard / goblin / demon
#   confidence_tier (on outcomes row)
#   (probability lives on predictions table as predicted_probability on outcomes OR join to predictions.probability)
#
# NBA prediction_outcomes: same join pattern; probability lives on predictions.probability
# MLB prediction_outcomes: same
#
# For NHL, outcomes table has predicted_probability already. For NBA/MLB we join to predictions.
# To keep logic uniform, we always join predictions → prediction_outcomes.


_JOIN_SQL = {
    # Common SQL template for each sport
    # Returns: probability, direction (OVER/UNDER), outcome (HIT/MISS), odds_type, tier
    "nhl": """
        SELECT
            p.probability,
            o.prediction    AS direction,
            o.outcome,
            COALESCE(o.odds_type, 'standard') AS odds_type,
            COALESCE(o.confidence_tier, p.confidence_tier) AS tier
        FROM predictions p
        JOIN prediction_outcomes o ON p.id = o.prediction_id
        WHERE o.outcome IN ('HIT','MISS')
          AND p.probability IS NOT NULL
    """,
    "nba": """
        SELECT
            p.probability,
            o.prediction    AS direction,
            o.outcome,
            COALESCE(o.odds_type, 'standard') AS odds_type,
            p.ai_tier       AS tier
        FROM predictions p
        JOIN prediction_outcomes o ON p.id = o.prediction_id
        WHERE o.outcome IN ('HIT','MISS')
          AND p.probability IS NOT NULL
    """,
    "mlb": """
        SELECT
            p.probability,
            o.prediction    AS direction,
            o.outcome,
            COALESCE(o.odds_type, 'standard') AS odds_type,
            p.confidence_tier AS tier
        FROM predictions p
        JOIN prediction_outcomes o ON p.id = o.prediction_id
        WHERE o.outcome IN ('HIT','MISS')
          AND p.probability IS NOT NULL
    """,
}


def _load_graded(sport: str) -> list[dict]:
    """Return all graded predictions as a list of dicts."""
    conn = _connect(sport)
    try:
        rows = conn.execute(_JOIN_SQL[sport]).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Wilson score confidence interval ─────────────────────────────────────────

def _wilson_ci(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score CI. Returns (lower, upper) as fractions."""
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


# ── Check A: Always-UNDER Baseline ───────────────────────────────────────────

def check_always_under(rows: list[dict]) -> dict:
    """
    Compare our accuracy vs. a naive 'always predict UNDER' strategy.
    real_edge = our_accuracy - always_under_accuracy
    Gate: real_edge > 3% on n > 1,000 samples.
    """
    n = len(rows)
    if n == 0:
        return {"n": 0, "pass": False, "error": "No graded predictions"}

    our_hits   = sum(1 for r in rows if r["outcome"] == "HIT")
    under_hits = sum(1 for r in rows if r["direction"] == "UNDER")

    our_accuracy          = our_hits / n
    always_under_accuracy = under_hits / n
    real_edge             = our_accuracy - always_under_accuracy

    passed = (real_edge > MIN_REAL_EDGE) and (n >= MIN_SAMPLE_N)
    under_prediction_rate = sum(1 for r in rows if r["direction"] == "UNDER") / n

    return {
        "n":                      n,
        "our_accuracy":           round(our_accuracy, 4),
        "always_under_accuracy":  round(always_under_accuracy, 4),
        "real_edge":              round(real_edge, 4),
        "under_prediction_rate":  round(under_prediction_rate, 4),
        "pass":                   passed,
        "verdict": (
            f"PASS — real edge +{real_edge*100:.1f}pp over always-UNDER baseline"
            if passed else
            f"FAIL — real edge only +{real_edge*100:.1f}pp (need >{MIN_REAL_EDGE*100:.0f}pp on n>={MIN_SAMPLE_N:,})"
        ),
    }


# ── Check B: Reliability Diagram ─────────────────────────────────────────────

def check_reliability(rows: list[dict]) -> dict:
    """
    Bucket predictions by probability decile. For each bucket, compute actual hit rate.
    Well-calibrated: model says 70% → hits ~70%.
    Returns buckets list + max_deviation + calibration_table (for lookup use).
    """
    # Build buckets: 0.0–0.1, 0.1–0.2, … 0.9–1.0
    buckets: dict[float, list[int]] = {}
    for low in [i / 10 for i in range(10)]:
        buckets[round(low, 1)] = []

    for r in rows:
        p = r["probability"]
        if p is None:
            continue
        bucket_key = round(min(int(p * 10) / 10, 0.9), 1)
        buckets[bucket_key].append(1 if r["outcome"] == "HIT" else 0)

    results = []
    calibration_table = {}
    max_deviation = 0.0

    for low in sorted(buckets):
        outcomes = buckets[low]
        n = len(outcomes)
        if n < MIN_BUCKET_N:
            continue
        hits = sum(outcomes)
        actual_rate = hits / n
        bucket_mid = round(low + 0.05, 2)
        deviation = abs(actual_rate - bucket_mid)
        if deviation > max_deviation:
            max_deviation = deviation
        lo_ci, hi_ci = _wilson_ci(hits, n)
        entry = {
            "bucket_low":    round(low, 1),
            "bucket_mid":    bucket_mid,
            "n":             n,
            "hits":          hits,
            "actual_rate":   round(actual_rate, 4),
            "wilson_lo":     round(lo_ci, 4),
            "wilson_hi":     round(hi_ci, 4),
            "deviation":     round(deviation, 4),
        }
        results.append(entry)
        # Calibration table: bucket_mid → actual_rate (used by edge_calculator)
        calibration_table[str(bucket_mid)] = round(actual_rate, 4)

    # Compute mean absolute calibration error (MACE)
    mace = round(sum(r["deviation"] for r in results) / len(results), 4) if results else 0.0

    return {
        "buckets":           results,
        "calibration_table": calibration_table,
        "max_deviation":     round(max_deviation, 4),
        "mace":              mace,
        "verdict": (
            f"Well-calibrated (MACE={mace:.3f}, max_dev={max_deviation:.3f})"
            if mace < 0.10 else
            f"Poorly calibrated (MACE={mace:.3f}) — apply calibration discount"
        ),
    }


# ── Check C: Tier Performance ────────────────────────────────────────────────

def check_tiers(rows: list[dict]) -> dict:
    """
    For each confidence tier, compute hit rate + 95% CI.
    T1 must outperform T4 meaningfully to justify the tier system.
    """
    tier_order = ["T1-ELITE", "T2-STRONG", "T3-GOOD", "T4-LEAN", "T5-FADE"]
    tier_data: dict[str, list[int]] = {t: [] for t in tier_order}
    other: list[int] = []

    for r in rows:
        tier = r.get("tier") or ""
        outcomes_list = tier_data.get(tier, other)
        outcomes_list.append(1 if r["outcome"] == "HIT" else 0)

    results = []
    for tier in tier_order:
        outcomes_list = tier_data[tier]
        n = len(outcomes_list)
        if n == 0:
            continue
        hits = sum(outcomes_list)
        rate = hits / n
        lo, hi = _wilson_ci(hits, n)
        results.append({
            "tier":       tier,
            "n":          n,
            "hit_rate":   round(rate, 4),
            "wilson_lo":  round(lo, 4),
            "wilson_hi":  round(hi, 4),
        })

    # Verdict: T1 hit_rate > T4 hit_rate (outside CI overlap)?
    t1 = next((r for r in results if r["tier"] == "T1-ELITE"), None)
    t4 = next((r for r in results if r["tier"] == "T4-LEAN"), None)
    if t1 and t4:
        meaningful = t1["wilson_lo"] > t4["wilson_hi"]
        verdict = (
            f"PASS — T1-ELITE ({t1['hit_rate']*100:.1f}%) meaningfully beats T4-LEAN ({t4['hit_rate']*100:.1f}%)"
            if meaningful else
            f"WARN — T1 and T4 CI overlap — tier system may be decorative"
        )
    elif not t1:
        verdict = "WARN — No T1-ELITE predictions found (tier system not in use?)"
    else:
        verdict = "SKIP — Insufficient T4 data for comparison"

    return {"tiers": results, "verdict": verdict}


# ── Check D: Brier Score ─────────────────────────────────────────────────────

def check_brier(rows: list[dict]) -> dict:
    """
    Brier score: mean((probability - actual_binary)^2). Lower = better.
    Compare vs naive always-UNDER model Brier.
    """
    if not rows:
        return {"brier": None, "brier_naive": None, "verdict": "No data"}

    n = len(rows)
    our_brier = 0.0
    naive_brier = 0.0

    # Naive: always predicts UNDER at probability=1.0 (direction=UNDER, prob=1.0)
    # But we compute it more correctly:
    # naive always-UNDER: predicted prob = 1.0 for UNDER, 0.0 for OVER
    # actual binary = 1 if HIT else 0
    for r in rows:
        actual_binary = 1 if r["outcome"] == "HIT" else 0
        p = r["probability"]
        our_brier += (p - actual_binary) ** 2
        # Naive: if prediction is UNDER, naive p=1.0; else naive p=0.0
        # But naive predicts UNDER for everything, so prob=1.0 for all.
        # Actual binary = 1 if UNDER was correct (outcome==HIT for this prediction)
        # However, the naive model never uses "our" direction — it always says UNDER.
        # So naive "hit" = 1 if actual was UNDER (regardless of what model predicted)
        actual_was_under = 1 if r["direction"] == "UNDER" and r["outcome"] == "HIT" else (
            1 if r["direction"] == "OVER" and r["outcome"] == "MISS" else 0
        )
        # Simplification: naive always picks UNDER. It HIT if actual < line.
        # We don't have actual_value here, only outcome + direction.
        # Proxy: naive is correct when direction==UNDER and outcome==HIT, or direction==OVER and outcome==MISS
        naive_brier += (1.0 - actual_was_under) ** 2

    our_brier /= n
    naive_brier /= n

    skill_score = 1 - (our_brier / naive_brier) if naive_brier > 0 else 0.0

    return {
        "n":           n,
        "brier":       round(our_brier, 4),
        "brier_naive": round(naive_brier, 4),
        "brier_skill": round(skill_score, 4),
        "verdict": (
            f"PASS — Brier={our_brier:.4f} beats naive {naive_brier:.4f} (skill={skill_score:.3f})"
            if our_brier < naive_brier else
            f"FAIL — Brier={our_brier:.4f} worse than naive {naive_brier:.4f} (skill={skill_score:.3f})"
        ),
    }


# ── Check E: OVER/UNDER Directional Split ────────────────────────────────────

def check_directional(rows: list[dict]) -> dict:
    """
    How often does the model predict OVER vs UNDER, and what are the actual hit rates per direction?
    Also breaks down by odds_type.
    """
    direction_stats: dict[str, dict] = {}
    odds_type_stats: dict[str, dict] = {}

    for r in rows:
        direction = r.get("direction", "UNKNOWN")
        odds_type = r.get("odds_type", "standard") or "standard"
        hit = 1 if r["outcome"] == "HIT" else 0

        for key, container in [(direction, direction_stats), (odds_type, odds_type_stats)]:
            if key not in container:
                container[key] = {"hits": 0, "total": 0}
            container[key]["hits"] += hit
            container[key]["total"] += 1

    n = len(rows)

    def _summarize(container: dict) -> list[dict]:
        out = []
        for k, v in sorted(container.items()):
            total = v["total"]
            hits  = v["hits"]
            rate  = hits / total if total else 0.0
            lo, hi = _wilson_ci(hits, total)
            out.append({
                "key":        k,
                "n":          total,
                "pct_of_all": round(total / n, 4) if n else 0.0,
                "hit_rate":   round(rate, 4),
                "wilson_lo":  round(lo, 4),
                "wilson_hi":  round(hi, 4),
            })
        return out

    direction_summary = _summarize(direction_stats)
    odds_type_summary = _summarize(odds_type_stats)

    under_pct = next((d["pct_of_all"] for d in direction_summary if d["key"] == "UNDER"), 0.0)
    verdict = (
        f"WARN — {under_pct*100:.0f}% of predictions are UNDER — extreme UNDER bias"
        if under_pct > 0.75 else
        f"OK — UNDER prediction rate {under_pct*100:.0f}% (acceptable)"
    )

    return {
        "by_direction":  direction_summary,
        "by_odds_type":  odds_type_summary,
        "verdict":       verdict,
    }


# ── Check F: Profitability Matrix (THE GATE) ─────────────────────────────────

def check_profitability_matrix(rows: list[dict]) -> dict:
    """
    For each (direction × odds_type) combination, compute hit rate for T1-T3 picks only
    and compare to break-even for that odds_type.

    This is the seal-of-approval check. A combo earns APPROVED when:
      - n_approved_tier >= MIN_COMBO_N (30 picks with sufficient sample)
      - hit_rate > break_even + MIN_COMBO_EDGE (proves real edge, not noise)

    We do NOT require every combo to pass — OVERs on goblins may simply be unviable
    and that's a correct, honest result. The output tells us exactly which combos
    to surface to consumers.
    """
    DIRECTIONS  = ["OVER", "UNDER"]
    ODDS_TYPES  = ["standard", "goblin", "demon"]

    # Collect per-tier hit data for each cell
    # cell_key = (direction, odds_type)
    # tier_key = tier string or "__all_approved__" for T1-T3 aggregate
    cells: dict[tuple, dict[str, list[int]]] = {}
    for d in DIRECTIONS:
        for o in ODDS_TYPES:
            cells[(d, o)] = {tier: [] for tier in ["T1-ELITE","T2-STRONG","T3-GOOD","T4-LEAN","T5-FADE","__other__"]}

    for r in rows:
        direction = r.get("direction") or "UNKNOWN"
        odds_type = (r.get("odds_type") or "standard").lower()
        tier      = r.get("tier") or "__other__"
        hit       = 1 if r["outcome"] == "HIT" else 0

        if direction not in DIRECTIONS:
            continue
        if odds_type not in ODDS_TYPES:
            odds_type = "standard"

        tier_key = tier if tier in cells[(direction, odds_type)] else "__other__"
        cells[(direction, odds_type)][tier_key].append(hit)

    results = []
    approved_combos = []

    for direction in DIRECTIONS:
        for odds_type in ODDS_TYPES:
            cell = cells[(direction, odds_type)]
            break_even = BREAK_EVEN[odds_type]

            # Aggregate T1-T3 (the only picks we surface)
            approved_outcomes = (
                cell["T1-ELITE"] + cell["T2-STRONG"] + cell["T3-GOOD"]
            )
            n_approved = len(approved_outcomes)
            n_total    = sum(len(v) for v in cell.values())

            # Per-tier breakdown
            tier_breakdown = []
            for tier_name in ["T1-ELITE", "T2-STRONG", "T3-GOOD", "T4-LEAN", "T5-FADE"]:
                t_outcomes = cell[tier_name]
                t_n = len(t_outcomes)
                if t_n == 0:
                    continue
                t_hits = sum(t_outcomes)
                t_rate = t_hits / t_n
                t_lo, t_hi = _wilson_ci(t_hits, t_n)
                t_edge = t_rate - break_even
                tier_breakdown.append({
                    "tier":        tier_name,
                    "n":           t_n,
                    "hit_rate":    round(t_rate, 4),
                    "wilson_lo":   round(t_lo, 4),
                    "wilson_hi":   round(t_hi, 4),
                    "edge_vs_be":  round(t_edge, 4),
                    "profitable":  t_rate > break_even,
                })

            if n_approved == 0:
                status  = "NO_DATA"
                verdict = f"No T1-T3 picks found — combo not active"
                entry = {
                    "direction":    direction,
                    "odds_type":    odds_type,
                    "break_even":   break_even,
                    "n_total":      n_total,
                    "n_approved":   0,
                    "hit_rate":     None,
                    "edge_vs_be":   None,
                    "status":       status,
                    "verdict":      verdict,
                    "tier_detail":  tier_breakdown,
                }
                results.append(entry)
                continue

            hits   = sum(approved_outcomes)
            rate   = hits / n_approved
            lo, hi = _wilson_ci(hits, n_approved)
            edge   = rate - break_even

            if n_approved < MIN_COMBO_N:
                status = "INSUFFICIENT_DATA"
                verdict = (
                    f"Only {n_approved} T1-T3 picks — need {MIN_COMBO_N}+ for confidence "
                    f"(hit_rate={rate*100:.1f}%, edge={edge*100:+.1f}pp vs break-even {break_even*100:.1f}%)"
                )
            elif rate > break_even + MIN_COMBO_EDGE:
                status = "APPROVED"
                verdict = (
                    f"APPROVED — hit_rate={rate*100:.1f}% (CI [{lo*100:.1f}%–{hi*100:.1f}%]) "
                    f"vs break-even {break_even*100:.1f}% → edge={edge*100:+.1f}pp on {n_approved:,} T1-T3 picks"
                )
                approved_combos.append((direction, odds_type))
            elif rate > break_even:
                status = "MARGINAL"
                verdict = (
                    f"MARGINAL — hit_rate={rate*100:.1f}% just clears break-even {break_even*100:.1f}% "
                    f"(edge={edge*100:+.1f}pp) — monitor, do not promote"
                )
            else:
                status = "BLOCKED"
                verdict = (
                    f"BLOCKED — hit_rate={rate*100:.1f}% BELOW break-even {break_even*100:.1f}% "
                    f"(edge={edge*100:+.1f}pp) — suppress this combo from consumer output"
                )

            entry = {
                "direction":    direction,
                "odds_type":    odds_type,
                "break_even":   break_even,
                "n_total":      n_total,
                "n_approved":   n_approved,
                "hit_rate":     round(rate, 4),
                "wilson_lo":    round(lo, 4),
                "wilson_hi":    round(hi, 4),
                "edge_vs_be":   round(edge, 4),
                "status":       status,
                "verdict":      verdict,
                "tier_detail":  tier_breakdown,
            }
            results.append(entry)

    # Gate: at least one combo is APPROVED
    gate_passed = len(approved_combos) > 0

    return {
        "matrix":          results,
        "approved_combos": approved_combos,
        "gate_passed":     gate_passed,
        "verdict": (
            f"GATE PASS — {len(approved_combos)} combo(s) approved for consumer output: "
            + ", ".join(f"{d}/{o}" for d, o in approved_combos)
            if gate_passed else
            "GATE FAIL — no (direction × odds_type) combo clears break-even at T1-T3 level"
        ),
    }


# ── Full audit for one sport ──────────────────────────────────────────────────

def run_sport_audit(sport: str, save_tables: bool = True) -> dict:
    """Run all 5 checks for one sport. Returns full result dict."""
    print(f"\n{'='*60}")
    print(f"  CALIBRATION AUDIT — {sport.upper()}")
    print(f"{'='*60}")

    try:
        rows = _load_graded(sport)
    except FileNotFoundError as exc:
        print(f"  ERROR: {exc}")
        return {"sport": sport, "error": str(exc), "pass": False}

    if len(rows) < MIN_SAMPLE_N:
        msg = f"Only {len(rows):,} graded predictions (minimum {MIN_SAMPLE_N:,}) — skipping audit"
        print(f"  SKIP: {msg}")
        return {"sport": sport, "skip": msg, "n": len(rows), "pass": None}

    print(f"  Loaded {len(rows):,} graded predictions")

    # Run all checks
    a = check_always_under(rows)
    b = check_reliability(rows)
    c = check_tiers(rows)
    d = check_brier(rows)
    e = check_directional(rows)

    # ── Terminal output ───────────────────────────────────────────────────────
    print(f"\n  [A] Always-UNDER Baseline")
    print(f"      Our accuracy:          {a['our_accuracy']*100:.2f}%")
    print(f"      Always-UNDER accuracy: {a['always_under_accuracy']*100:.2f}%")
    print(f"      Real edge:             {a['real_edge']*100:+.2f}pp")
    print(f"      UNDER predict rate:    {a['under_prediction_rate']*100:.1f}%")
    print(f"      Verdict: {a['verdict']}")

    print(f"\n  [B] Reliability Diagram (buckets with n>={MIN_BUCKET_N})")
    print(f"      {'Bucket':>8}  {'n':>6}  {'Model%':>7}  {'Actual%':>8}  {'Dev':>6}")
    for bkt in b["buckets"]:
        print(f"      {bkt['bucket_low']*100:>6.0f}%+  {bkt['n']:>6,}  "
              f"{bkt['bucket_mid']*100:>6.1f}%  {bkt['actual_rate']*100:>7.1f}%  "
              f"{bkt['deviation']*100:>5.1f}pp")
    print(f"      MACE: {b['mace']*100:.2f}pp | Max dev: {b['max_deviation']*100:.2f}pp")
    print(f"      Verdict: {b['verdict']}")

    print(f"\n  [C] Tier Performance")
    print(f"      {'Tier':>12}  {'n':>6}  {'HitRate':>8}  {'CI':>18}")
    for t in c["tiers"]:
        print(f"      {t['tier']:>12}  {t['n']:>6,}  {t['hit_rate']*100:>7.1f}%  "
              f"  [{t['wilson_lo']*100:.1f}%–{t['wilson_hi']*100:.1f}%]")
    print(f"      Verdict: {c['verdict']}")

    print(f"\n  [D] Brier Score")
    print(f"      Our Brier:   {d['brier']}")
    print(f"      Naive Brier: {d['brier_naive']}")
    print(f"      Skill score: {d['brier_skill']}")
    print(f"      Verdict: {d['verdict']}")

    print(f"\n  [E] OVER/UNDER Directional Split")
    for item in e["by_direction"]:
        print(f"      {item['key']:>8}: n={item['n']:>6,}  ({item['pct_of_all']*100:.0f}% of all)  "
              f"hit_rate={item['hit_rate']*100:.1f}%  [{item['wilson_lo']*100:.1f}%–{item['wilson_hi']*100:.1f}%]")
    print(f"      By odds type:")
    for item in e["by_odds_type"]:
        print(f"        {item['key']:>10}: n={item['n']:>6,}  hit_rate={item['hit_rate']*100:.1f}%")
    print(f"      Verdict: {e['verdict']}")

    # Run Check F last — it is THE gate
    f = check_profitability_matrix(rows)

    print(f"\n  [F] Profitability Matrix — (direction x odds_type), T1-T3 picks only")
    print(f"      {'Combo':>16}  {'n_T1-T3':>8}  {'HitRate':>8}  {'BreakEven':>10}  {'Edge':>7}  {'Status':>18}")
    for cell in f["matrix"]:
        d_str  = cell["direction"]
        o_str  = cell["odds_type"]
        combo  = f"{d_str}/{o_str}"
        status = cell["status"]
        if cell["n_approved"] == 0:
            print(f"      {combo:>16}  {'—':>8}  {'—':>8}  {cell['break_even']*100:>9.1f}%  {'—':>7}  {status:>18}")
        else:
            hr  = cell["hit_rate"] or 0
            edg = cell["edge_vs_be"] or 0
            print(f"      {combo:>16}  {cell['n_approved']:>8,}  {hr*100:>7.1f}%  "
                  f"{cell['break_even']*100:>9.1f}%  {edg*100:>+6.1f}pp  {status:>18}")

        # Show per-tier breakdown for non-empty combos
        for td in cell.get("tier_detail", []):
            prof = "+" if td["profitable"] else "-"
            print(f"      {'':>16}    {td['tier']:>12}  n={td['n']:>6,}  "
                  f"hit={td['hit_rate']*100:.1f}%  [{td['wilson_lo']*100:.1f}%–{td['wilson_hi']*100:.1f}%]  "
                  f"edge={td['edge_vs_be']*100:+.1f}pp  [{prof}]")

    print(f"\n      {f['verdict']}")

    # ── Overall gate: Check F, not Check A ───────────────────────────────────
    overall_pass = f["gate_passed"]
    print(f"\n  OVERALL: {'PASS' if overall_pass else 'FAIL'} "
          f"(gate: at least 1 approved (direction x odds_type) combo with T1-T3 picks)")
    print(f"  [A] always-UNDER baseline ({a['real_edge']*100:+.1f}pp) is informational only")

    result = {
        "sport":                   sport,
        "n":                       len(rows),
        "pass":                    overall_pass,
        "approved_combos":         f["approved_combos"],
        "check_a_baseline":        a,
        "check_b_reliability":     b,
        "check_c_tiers":           c,
        "check_d_brier":           d,
        "check_e_directional":     e,
        "check_f_profitability":   f,
        "audit_date":              str(date.today()),
    }

    # ── Save outputs ──────────────────────────────────────────────────────────
    if save_tables:
        today = date.today().isoformat()

        # Calibration lookup table (used by edge_calculator.py)
        # Also embed approved_combos so edge_calculator knows what to surface
        cal_path = CALIBRATION_TABLES_DIR / f"{sport}.json"
        CALIBRATION_TABLES_DIR.mkdir(parents=True, exist_ok=True)
        cal_table = {
            "sport":             sport,
            "built_date":        today,
            "n":                 len(rows),
            "calibration_table": b["calibration_table"],
            "always_under_rate": a["always_under_accuracy"],
            "our_accuracy":      a["our_accuracy"],
            "real_edge_vs_naive": a["real_edge"],
            "approved_combos":   f["approved_combos"],
        }
        cal_path.write_text(json.dumps(cal_table, indent=2))
        print(f"\n  Saved calibration table: {cal_path}")

        # Full report
        report_path = REPORTS_DIR / f"calibration_{sport}_{today}.json"
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2))
        print(f"  Saved full report:       {report_path}")

    return result


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PEGASUS Calibration Audit")
    parser.add_argument(
        "--sport",
        choices=SPORTS,
        default=None,
        help="Run audit for one sport only (default: all sports)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Skip writing calibration tables and reports to disk",
    )
    args = parser.parse_args()

    sports_to_run = [args.sport] if args.sport else SPORTS
    results = {}

    for sport in sports_to_run:
        results[sport] = run_sport_audit(sport, save_tables=not args.no_save)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  AUDIT SUMMARY — Profitability Gate (Check F)")
    print(f"{'='*60}")
    all_pass = True
    for sport, r in results.items():
        if r.get("skip"):
            status = f"SKIP ({r['n']:,} samples)"
        elif r.get("error"):
            status = f"ERROR — {r['error']}"
        elif r.get("pass"):
            approved = r.get("approved_combos", [])
            combos   = ", ".join(f"{d}/{o}" for d, o in approved) if approved else "none"
            status   = f"PASS  n={r['n']:,}  approved: {combos}"
        else:
            approved = r.get("approved_combos", [])
            status   = f"FAIL  n={r['n']:,}  no approved combos"
            all_pass = False

        print(f"  {sport.upper():>4}: {status}")

    print(f"\n  Gate: {'ALL PASS — proceed to Steps 3-9' if all_pass else 'ONE OR MORE FAILED — diagnose before shipping'}")
    print()


if __name__ == "__main__":
    main()
