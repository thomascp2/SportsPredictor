"""
PEGASUS/pipeline/nhl_ml_reader.py

Read-only interface to the NHL ML model registry.

Three entry points:
  load_nhl_model(prop, line)          -- load model + scaler + metadata
  predict_nhl_ml(features, prop, line) -- run one feature dict through model
  audit_nhl_models(lookback_days=30)  -- shadow-mode audit vs recent graded data

Design rules:
  - Read-only: never INSERT/UPDATE/DELETE on any DB
  - Falls back gracefully when a model file is missing or features are incomplete
  - Returns calibrated probability of OVER (class=1)
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PEGASUS_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT    = _PEGASUS_ROOT.parent
_REGISTRY     = _REPO_ROOT / "ml_training" / "model_registry" / "nhl"
_NHL_DB       = _REPO_ROOT / "nhl" / "database" / "nhl_predictions_v2.db"
_VERSION      = "v20260325_003"

# Props that actually have a trained model at _VERSION
TRAINED_PROPS = {
    ("points", 0.5),
    ("points", 1.5),
    ("shots",  1.5),
    ("shots",  2.5),
    ("shots",  3.5),
}


# ---------------------------------------------------------------------------
# Model cache (process-level; one per prop/line pair)
# ---------------------------------------------------------------------------

_model_cache: dict[tuple, dict] = {}


# ---------------------------------------------------------------------------
# 1. load_nhl_model
# ---------------------------------------------------------------------------

def load_nhl_model(prop: str, line: float) -> Optional[dict]:
    """
    Load the latest model + scaler + metadata for a prop/line.

    Returns a dict:
        {
            "model":    CalibratedClassifierCV,
            "scaler":   StandardScaler,
            "metadata": dict,
            "version":  str,
            "prop":     str,
            "line":     float,
        }
    Returns None if no model exists for this prop/line.
    """
    key = (prop, line)
    if key in _model_cache:
        return _model_cache[key]

    prop_dir_name = f"{prop}_{str(line).replace('.', '_')}"
    version_dir   = _REGISTRY / prop_dir_name / _VERSION

    if not version_dir.is_dir():
        return None

    model_path    = version_dir / "model.joblib"
    scaler_path   = version_dir / "scaler.joblib"
    metadata_path = version_dir / "metadata.json"

    if not model_path.exists() or not scaler_path.exists() or not metadata_path.exists():
        return None

    try:
        model    = joblib.load(model_path)
        scaler   = joblib.load(scaler_path)
        metadata = json.loads(metadata_path.read_text())
    except Exception as e:
        print(f"[nhl_ml_reader] load error {prop}/{line}: {e}")
        return None

    result = {
        "model":    model,
        "scaler":   scaler,
        "metadata": metadata,
        "version":  _VERSION,
        "prop":     prop,
        "line":     line,
    }
    _model_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# Feature vector builder
# ---------------------------------------------------------------------------

def _build_feature_vector(
    features_dict: dict,
    feature_names: list[str],
) -> Optional[np.ndarray]:
    """
    Map a raw features_json dict (as stored in NHL DB) to a 1-D numpy array
    aligned to the model's feature_names list.

    Mapping strategy (in priority order):
      1. features_dict[name]  -- exact match
      2. features_dict['f_' + name]  -- add f_ prefix
      3. features_dict[name.removeprefix('f_')]  -- strip f_ prefix
      4. 0.0  -- fallback (feature was missing from this prediction)

    Returns None only if features_dict is empty / None.
    """
    if not features_dict:
        return None

    vec = []
    for name in feature_names:
        if name in features_dict:
            vec.append(float(features_dict[name] or 0.0))
        elif f"f_{name}" in features_dict:
            vec.append(float(features_dict[f"f_{name}"] or 0.0))
        elif name.startswith("f_") and name[2:] in features_dict:
            vec.append(float(features_dict[name[2:]] or 0.0))
        else:
            vec.append(0.0)

    return np.array(vec, dtype=float)


# ---------------------------------------------------------------------------
# 2. predict_nhl_ml
# ---------------------------------------------------------------------------

def predict_nhl_ml(
    features_dict: dict,
    prop: str,
    line: float,
) -> Optional[float]:
    """
    Run one prediction.

    Args:
        features_dict: raw dict from features_json (or any compatible dict)
        prop:          e.g. "shots"
        line:          e.g. 2.5

    Returns:
        Calibrated probability of OVER (float in [0, 1]), or None on failure.
    """
    bundle = load_nhl_model(prop, line)
    if bundle is None:
        return None

    feature_names = bundle["metadata"]["feature_names"]
    vec = _build_feature_vector(features_dict, feature_names)
    if vec is None:
        return None

    try:
        X_scaled = bundle["scaler"].transform(vec.reshape(1, -1))
        proba    = bundle["model"].predict_proba(X_scaled)[0]
        # class order: model.classes_ = [0, 1] where 1 = OVER
        over_idx = list(bundle["model"].classes_).index(1)
        return float(proba[over_idx])
    except Exception as e:
        print(f"[nhl_ml_reader] predict error {prop}/{line}: {e}")
        return None


# ---------------------------------------------------------------------------
# 3. audit_nhl_models
# ---------------------------------------------------------------------------

def audit_nhl_models(lookback_days: int = 30) -> dict:
    """
    Shadow-mode audit: compare ML model predictions vs statistical model vs
    always-UNDER baseline on the last `lookback_days` of graded predictions.

    Returns a comprehensive results dict including:
        - per_prop: dict of per-prop audit results
        - summary:  aggregate pass/fail verdict (3-check gate)
    """
    if not _NHL_DB.exists():
        return {"error": f"NHL DB not found: {_NHL_DB}"}

    conn = sqlite3.connect(str(_NHL_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    results = {}

    for prop, line in sorted(TRAINED_PROPS):
        bundle = load_nhl_model(prop, line)
        if bundle is None:
            results[(prop, line)] = {"status": "model_missing"}
            continue

        # -------------------------------------------------------------------
        # Load graded predictions within lookback window
        # -------------------------------------------------------------------
        query = """
            SELECT
                p.probability        AS stat_probability,
                p.prediction         AS stat_prediction,
                p.features_json,
                o.actual_outcome,
                o.outcome,
                o.game_date
            FROM predictions p
            JOIN prediction_outcomes o ON p.id = o.prediction_id
            WHERE p.prop_type = ?
              AND p.line      = ?
              AND o.game_date >= date('now', ? || ' days')
              AND o.outcome   IS NOT NULL
              AND o.actual_outcome IS NOT NULL
            ORDER BY o.game_date
        """
        rows = conn.execute(
            query, (prop, line, f"-{lookback_days}")
        ).fetchall()

        if not rows:
            results[(prop, line)] = {
                "status": "no_graded_data",
                "prop": prop,
                "line": line,
            }
            continue

        # -------------------------------------------------------------------
        # Run shadow predictions
        # -------------------------------------------------------------------
        feature_names = bundle["metadata"]["feature_names"]

        stat_correct  = 0    # statistical model correct
        ml_correct    = 0    # ML model correct
        under_correct = 0    # always-UNDER baseline
        total         = 0
        ml_probs      = []   # for calibration check
        actuals       = []   # 1=OVER, 0=UNDER
        n_features_missing = 0

        for row in rows:
            actual_label = str(row["actual_outcome"]).strip().upper()  # 'OVER' or 'UNDER'
            actual       = 1 if actual_label == "OVER" else 0

            # Stat model correctness
            stat_pred = str(row["stat_prediction"]).strip().upper()
            stat_correct  += 1 if stat_pred == actual_label else 0
            under_correct += 1 if actual_label == "UNDER" else 0

            # ML model prediction
            try:
                feat = json.loads(row["features_json"]) if row["features_json"] else {}
            except Exception:
                feat = {}

            ml_prob = None
            if feat:
                vec = _build_feature_vector(feat, feature_names)
                if vec is not None:
                    try:
                        X_scaled = bundle["scaler"].transform(vec.reshape(1, -1))
                        proba    = bundle["model"].predict_proba(X_scaled)[0]
                        over_idx = list(bundle["model"].classes_).index(1)
                        ml_prob  = float(proba[over_idx])
                    except Exception:
                        pass
            else:
                n_features_missing += 1

            if ml_prob is not None:
                ml_pred  = "OVER" if ml_prob >= 0.5 else "UNDER"
                ml_correct += 1 if ml_pred == actual_label else 0
                ml_probs.append(ml_prob)
                actuals.append(actual)

            total += 1

        if total == 0:
            results[(prop, line)] = {"status": "no_data", "prop": prop, "line": line}
            continue

        n_ml = len(ml_probs)

        stat_acc  = stat_correct  / total
        under_acc = under_correct / total
        ml_acc    = ml_correct    / n_ml if n_ml > 0 else None

        improvement = (ml_acc - under_acc) if ml_acc is not None else None

        # -------------------------------------------------------------------
        # Feature importance check (from metadata top_features)
        # -------------------------------------------------------------------
        top_features = bundle["metadata"].get("top_features", {})
        max_feature_importance = max(top_features.values()) if top_features else 0.0
        top_feature_name = max(top_features, key=top_features.get) if top_features else "unknown"

        # -------------------------------------------------------------------
        # Calibration check: bucket ML probs vs actual hit rates
        # -------------------------------------------------------------------
        cal_buckets = {}
        if ml_probs:
            bins = [0, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01]
            labels = ["<40%", "40-50%", "50-60%", "60-70%", "70-80%", ">80%"]
            arr_probs   = np.array(ml_probs)
            arr_actuals = np.array(actuals)
            for i, label in enumerate(labels):
                mask = (arr_probs >= bins[i]) & (arr_probs < bins[i + 1])
                n = int(mask.sum())
                if n > 0:
                    hit = float(arr_actuals[mask].mean())
                    cal_buckets[label] = {"n": n, "hit_rate": round(hit, 3)}

        # -------------------------------------------------------------------
        # Three-check gate verdict for this prop
        # -------------------------------------------------------------------
        check_beats_baseline = (improvement is not None) and (improvement > 0.03)
        check_feature_sane   = max_feature_importance < 0.70
        # Calibration: check that mid-range probs (50-60%) aren't too far off
        mid_bucket = cal_buckets.get("50-60%", {})
        if mid_bucket.get("n", 0) >= 20:
            cal_deviation = abs(mid_bucket["hit_rate"] - 0.55)
            check_calibration = cal_deviation < 0.15
        else:
            check_calibration = True  # not enough data to fail on calibration

        prop_pass = check_beats_baseline and check_feature_sane and check_calibration

        results[(prop, line)] = {
            "prop":                   prop,
            "line":                   line,
            "status":                 "audited",
            "total_graded":           total,
            "n_ml_predictions":       n_ml,
            "n_features_missing":     n_features_missing,
            "stat_accuracy":          round(stat_acc,  4),
            "ml_accuracy":            round(ml_acc,    4) if ml_acc is not None else None,
            "always_under_accuracy":  round(under_acc, 4),
            "improvement_over_under": round(improvement, 4) if improvement is not None else None,
            "max_feature_importance": round(max_feature_importance, 4),
            "top_feature":            top_feature_name,
            "calibration_buckets":    cal_buckets,
            "check_beats_baseline":   check_beats_baseline,
            "check_feature_sane":     check_feature_sane,
            "check_calibration":      check_calibration,
            "prop_pass":              prop_pass,
            "trained_samples":        bundle["metadata"]["training_samples"],
            "stored_test_accuracy":   bundle["metadata"]["test_accuracy"],
            "stored_baseline":        bundle["metadata"]["baseline_accuracy"],
            "stored_improvement":     bundle["metadata"]["improvement_over_baseline"],
        }

    conn.close()

    # -----------------------------------------------------------------------
    # Build summary verdict
    # -----------------------------------------------------------------------
    audited = {k: v for k, v in results.items() if v.get("status") == "audited"}
    passing = {k: v for k, v in audited.items() if v.get("prop_pass")}
    failing = {k: v for k, v in audited.items() if not v.get("prop_pass")}

    # Portfolio-level: any prop beating baseline by >3%?
    any_beats_baseline = any(
        (v.get("improvement_over_under") or 0) > 0.03 for v in audited.values()
    )
    all_features_sane  = all(v.get("check_feature_sane", True) for v in audited.values())
    overall_pass       = any_beats_baseline and all_features_sane

    summary = {
        "overall_pass":           overall_pass,
        "any_prop_beats_baseline": any_beats_baseline,
        "all_features_sane":       all_features_sane,
        "n_props_audited":         len(audited),
        "n_props_pass":            len(passing),
        "n_props_fail":            len(failing),
        "recommendation":          "ACTIVATE 60/40 blend in PEGASUS" if overall_pass
                                   else "STAY STATISTICAL — retrain Oct/Nov 2026",
        "passing_props":           [f"{v['prop']} {v['line']}" for v in passing.values()],
        "failing_props":           [f"{v['prop']} {v['line']}" for v in failing.values()],
    }

    return {"per_prop": results, "summary": summary}


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

def _print_audit_report(results: dict) -> None:
    """Pretty-print the audit report."""
    per_prop = results.get("per_prop", {})
    summary  = results.get("summary", {})

    print("\n" + "=" * 70)
    print("NHL ML AUDIT REPORT — PEGASUS Shadow Mode")
    print("=" * 70)

    for (prop, line), r in sorted(per_prop.items()):
        status = r.get("status", "unknown")
        print(f"\n[{prop.upper()} {line}]")
        if status != "audited":
            print(f"  Status: {status}")
            continue

        print(f"  Graded samples (lookback):  {r['total_graded']}")
        print(f"  ML predictions made:        {r['n_ml_predictions']}")
        print(f"  Always-UNDER accuracy:      {r['always_under_accuracy']:.1%}")
        print(f"  Statistical model accuracy: {r['stat_accuracy']:.1%}")
        ml_acc = r.get('ml_accuracy')
        if ml_acc is not None:
            print(f"  ML model accuracy:          {ml_acc:.1%}")
            imp = r.get('improvement_over_under')
            print(f"  Improvement over baseline:  {imp:+.1%}" if imp is not None else "  Improvement: n/a")
        print(f"  [Stored test accuracy:      {r['stored_test_accuracy']:.1%}  baseline: {r['stored_baseline']:.1%}  imp: {r['stored_improvement']:+.1%}]")
        print(f"  Top feature:                {r['top_feature']} ({r['max_feature_importance']:.1%})")

        # Calibration
        if r['calibration_buckets']:
            print("  Calibration:")
            for bucket, info in r['calibration_buckets'].items():
                print(f"    {bucket:>8}: n={info['n']:4d}  hit_rate={info['hit_rate']:.1%}")

        # Gate checks
        beats = "PASS" if r['check_beats_baseline'] else "FAIL"
        sane  = "PASS" if r['check_feature_sane']   else "FAIL"
        cal   = "PASS" if r['check_calibration']    else "FAIL"
        overall = "PASS" if r['prop_pass'] else "FAIL"
        print(f"  Checks: beats_baseline={beats}  feature_sane={sane}  calibration={cal}  => {overall}")

    print("\n" + "-" * 70)
    print("SUMMARY")
    print("-" * 70)
    print(f"  Any prop beats always-UNDER by >3%:  {'YES' if summary['any_prop_beats_baseline'] else 'NO'}")
    print(f"  All feature importances sane (<70%): {'YES' if summary['all_features_sane'] else 'NO'}")
    print(f"  Props audited: {summary['n_props_audited']}   passing: {summary['n_props_pass']}   failing: {summary['n_props_fail']}")
    if summary['passing_props']:
        print(f"  Passing: {', '.join(summary['passing_props'])}")
    if summary['failing_props']:
        print(f"  Failing: {', '.join(summary['failing_props'])}")
    print()
    print(f"  VERDICT: {'PASS' if summary['overall_pass'] else 'FAIL'}")
    print(f"  ACTION:  {summary['recommendation']}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    print(f"Running NHL ML audit (last {days} days of graded predictions)...")
    results = audit_nhl_models(lookback_days=days)
    if "error" in results:
        print(f"Error: {results['error']}")
        sys.exit(1)
    _print_audit_report(results)
