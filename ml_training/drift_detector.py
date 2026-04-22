"""
ml_training/drift_detector.py

Kolmogorov-Smirnov drift detector for the ML v2 pipeline.

Detects when recent prediction probability distributions diverge from
the training distribution — an early warning that a model is becoming
unreliable before it shows up as a hit-rate collapse.

Two-layer detection:
  1. KS test on model output probabilities (are recent probs from same distribution?)
  2. SHAP feature importance report (which features are driving the drift?)

Runs daily after grading completes. Does NOT automatically retrain — it flags
for human review and sends a Discord alert.

Usage:
    from ml_training.drift_detector import DriftDetector

    detector = DriftDetector()
    report = detector.check("nba", "points", 24.5)
    # → {"drifted": True, "ks_stat": 0.21, "p_value": 0.03, "top_drifting": [...]}

    # Run all props for a sport:
    reports = detector.check_all("nba")
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date as _date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import stats as scipy_stats

try:
    import shap as _shap
    _SHAP_AVAILABLE = True
except ImportError:
    _SHAP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ML_DIR      = Path(__file__).resolve().parent
_LOGS_DIR    = _ML_DIR / "drift_logs"
_LOGS_DIR.mkdir(exist_ok=True)

_REPO_ROOT   = _ML_DIR.parent

_DB_PATHS = {
    "nhl": _REPO_ROOT / "nhl"  / "database" / "nhl_predictions_v2.db",
    "nba": _REPO_ROOT / "nba"  / "database" / "nba_predictions.db",
    "mlb": _REPO_ROOT / "mlb"  / "database" / "mlb_predictions.db",
}

# ---------------------------------------------------------------------------
# Discord alerting
# ---------------------------------------------------------------------------

def _send_discord_alert(webhook_url: str, message: str) -> None:
    try:
        import requests
        requests.post(webhook_url, json={"content": message}, timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DriftDetector:
    """
    KS-test based drift detector for ML prediction distributions.

    Compares recent model output probabilities against the training-time
    distribution stored in model metadata. If the KS p-value drops below
    p_threshold (default 0.05), drift is declared and a SHAP report is generated.
    """

    def __init__(
        self,
        registry_dir: str | Path = None,
        p_threshold: float = 0.05,
        window: int = 100,
        discord_webhook: str = None,
    ):
        """
        Args:
            registry_dir: Path to ml_training/model_registry/
            p_threshold:  KS test p-value below which drift is declared
            window:       Number of recent predictions to compare
            discord_webhook: Optional Discord webhook URL for alerts
        """
        self.p_threshold   = p_threshold
        self.window        = window
        self.discord_url   = discord_webhook or os.getenv("DISCORD_WEBHOOK_URL", "")

        if registry_dir:
            self.registry_dir = Path(registry_dir)
        else:
            self.registry_dir = _ML_DIR / "model_registry"

        try:
            from ml_training.production_predictor import ProductionPredictor
            self._predictor = ProductionPredictor(str(self.registry_dir))
        except ImportError:
            try:
                from production_predictor import ProductionPredictor
                self._predictor = ProductionPredictor(str(self.registry_dir))
            except ImportError:
                self._predictor = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        sport: str,
        prop_type: str,
        line: float = None,
        run_shap: bool = True,
    ) -> dict:
        """
        Run KS drift test for a specific sport/prop/line.

        Returns a drift report dict:
        {
            "sport":         "nba",
            "prop_type":     "points",
            "line":          24.5,
            "checked_at":    "2026-04-22T...",
            "drifted":       bool,
            "ks_stat":       float,
            "p_value":       float,
            "sample_size":   int,
            "training_size": int,
            "top_drifting":  list of feature names (empty if no SHAP or no drift),
            "mean_prob_recent":   float,
            "mean_prob_training": float,
            "message":       str,
        }
        """
        sport_lower = sport.lower()
        report = {
            "sport":         sport_lower,
            "prop_type":     prop_type,
            "line":          line,
            "checked_at":    datetime.utcnow().isoformat(),
            "drifted":       False,
            "ks_stat":       None,
            "p_value":       None,
            "sample_size":   0,
            "training_size": 0,
            "top_drifting":  [],
            "mean_prob_recent":   None,
            "mean_prob_training": None,
            "message":       "OK",
        }

        # Load training distribution from model metadata
        training_dist = self._load_training_distribution(sport_lower, prop_type, line)
        if training_dist is None or len(training_dist) < 20:
            report["message"] = "Insufficient training distribution data in metadata"
            return report

        # Load recent predictions from SQLite
        recent_probs = self._load_recent_predictions(sport_lower, prop_type, line)
        if len(recent_probs) < 20:
            report["message"] = f"Insufficient recent data (need 20+, have {len(recent_probs)})"
            return report

        report["sample_size"]   = len(recent_probs)
        report["training_size"] = len(training_dist)
        report["mean_prob_recent"]   = round(float(np.mean(recent_probs)), 4)
        report["mean_prob_training"] = round(float(np.mean(training_dist)), 4)

        # KS test
        ks_stat, p_value = scipy_stats.ks_2samp(recent_probs, training_dist)
        report["ks_stat"] = round(float(ks_stat), 4)
        report["p_value"] = round(float(p_value), 4)

        if p_value < self.p_threshold:
            report["drifted"] = True
            report["message"] = (
                f"DRIFT DETECTED: KS={ks_stat:.3f}, p={p_value:.4f} "
                f"(mean recent={report['mean_prob_recent']:.3f} vs "
                f"training={report['mean_prob_training']:.3f})"
            )

            # SHAP report
            if run_shap and _SHAP_AVAILABLE and self._predictor is not None:
                top_features = self._run_shap_report(sport_lower, prop_type, line)
                report["top_drifting"] = top_features

            # Persist log
            self._write_log(report)

            # Discord alert
            if self.discord_url:
                self._alert(sport_lower, prop_type, line, report)

        return report

    def check_all(self, sport: str, run_shap: bool = True) -> list[dict]:
        """
        Run drift check on all prop/line combos for a sport.

        Iterates through available models in the registry.
        Returns list of reports (one per prop/line).
        """
        sport_lower = sport.lower()
        registry_sport_dir = self.registry_dir / sport_lower
        if not registry_sport_dir.exists():
            return []

        reports = []
        for prop_dir in sorted(registry_sport_dir.iterdir()):
            if not prop_dir.is_dir():
                continue

            # Parse prop_type and line from directory name (e.g., "points_24_5")
            prop_type, line = self._parse_prop_dir(prop_dir.name)
            report = self.check(sport_lower, prop_type, line, run_shap=run_shap)
            reports.append(report)

        return reports

    def summary(self, sport: str, days: int = 7) -> dict:
        """
        Read recent drift logs and return a summary.

        Returns:
            {
                "sport": "nba",
                "period_days": 7,
                "total_checks": int,
                "drift_events": int,
                "props_drifted": list of prop names,
            }
        """
        sport_lower = sport.lower()
        cutoff = (_date.today() - timedelta(days=days)).isoformat()

        drift_events = []
        total = 0

        for log_file in _LOGS_DIR.glob(f"{sport_lower}_*.json"):
            try:
                log = json.loads(log_file.read_text())
                if isinstance(log, list):
                    for entry in log:
                        if entry.get("checked_at", "")[:10] >= cutoff:
                            total += 1
                            if entry.get("drifted"):
                                drift_events.append(entry.get("prop_type", "?"))
                elif isinstance(log, dict):
                    if log.get("checked_at", "")[:10] >= cutoff:
                        total += 1
                        if log.get("drifted"):
                            drift_events.append(log.get("prop_type", "?"))
            except (json.JSONDecodeError, KeyError):
                continue

        return {
            "sport":         sport_lower,
            "period_days":   days,
            "total_checks":  total,
            "drift_events":  len(drift_events),
            "props_drifted": list(set(drift_events)),
        }

    # ------------------------------------------------------------------
    # Training distribution loader
    # ------------------------------------------------------------------

    def _load_training_distribution(
        self, sport: str, prop_type: str, line: float = None
    ) -> Optional[list[float]]:
        """
        Load the stored prediction probability distribution from model metadata.

        Model metadata stores `prediction_distribution` as:
            {"pct_over": 0.52, "pct_under": 0.48}
        and sometimes a `training_prob_samples` list if we start persisting it.

        For now, we reconstruct a synthetic distribution from:
          - pct_over / pct_under (gives the distribution shape)
          - test accuracy / roc_auc (constrains calibration)
        """
        if self._predictor is None:
            return None

        try:
            stats = self._predictor.get_model_stats(sport, prop_type, line or 0.0)
        except Exception:
            return None

        if not stats or "metadata" not in str(type(stats)):
            # get_model_stats returns a dict with metadata info
            pass

        # Try to load metadata directly
        registry_dir = self.registry_dir / sport
        if line is not None:
            line_str = str(line).replace(".", "_")
            prop_dir = registry_dir / f"{prop_type}_{line_str}"
        else:
            # Find first matching dir
            prop_dir = None
            if registry_dir.exists():
                for d in registry_dir.iterdir():
                    if d.name.startswith(prop_type):
                        prop_dir = d
                        break

        if prop_dir is None or not prop_dir.exists():
            return None

        # Load latest version metadata
        latest_ptr = prop_dir / "latest.txt"
        if not latest_ptr.exists():
            return None

        version = latest_ptr.read_text().strip()
        meta_path = prop_dir / version / "metadata.json"
        if not meta_path.exists():
            return None

        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, ValueError):
            return None

        # Reconstruct distribution from metadata
        pct_over = meta.get("prediction_distribution", {}).get("pct_over")
        n_train  = meta.get("training_samples", 500)

        if pct_over is None:
            # Fall back to test accuracy as a proxy
            pct_over = meta.get("test_accuracy", 0.55)

        # Generate synthetic Beta distribution matching the training stats
        # This approximates the shape of the training probability distribution
        rng = np.random.default_rng(42)  # deterministic seed
        n_synthetic = min(n_train, 2000)

        # Beta(a, b) with mean = pct_over, variance roughly matching calibrated output
        # mean = a/(a+b), so with spread=0.15: a ~ pct_over/0.02, b ~ (1-pct_over)/0.02
        concentration = 20.0  # controls tightness of the distribution
        a = pct_over * concentration
        b = (1.0 - pct_over) * concentration
        a = max(0.5, a)
        b = max(0.5, b)

        synthetic = rng.beta(a, b, size=n_synthetic).tolist()
        return synthetic

    # ------------------------------------------------------------------
    # Recent predictions loader
    # ------------------------------------------------------------------

    def _load_recent_predictions(
        self, sport: str, prop_type: str, line: float = None
    ) -> list[float]:
        """
        Load recent model prediction probabilities from SQLite.

        Looks for the `ml_prob_over` stored in predictions or a dedicated
        ml_v2_predictions table. Falls back to directional probability.
        """
        db_path = _DB_PATHS.get(sport)
        if db_path is None or not db_path.exists():
            return []

        cutoff = (_date.today() - timedelta(days=self.window)).isoformat()

        try:
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.row_factory = sqlite3.Row

            # Try ml_v2_predictions table first (Phase 6)
            try:
                rows = conn.execute("""
                    SELECT model_prob FROM ml_v2_predictions
                    WHERE prop_type = ?
                      AND game_date >= ?
                      AND model_prob IS NOT NULL
                    ORDER BY game_date DESC
                    LIMIT ?
                """, (prop_type, cutoff, self.window)).fetchall()

                if rows:
                    conn.close()
                    return [float(r["model_prob"]) for r in rows]
            except sqlite3.OperationalError:
                pass  # table doesn't exist yet

            # Fall back to predictions table with probability column
            # Different schemas: NHL/MLB use features_json, NBA uses f_ columns
            try:
                where_clause = "prop_type = ? AND game_date >= ? AND probability IS NOT NULL"
                params: list = [prop_type, cutoff]
                if line is not None:
                    where_clause += " AND ABS(line - ?) < 0.26"
                    params.append(line)

                rows = conn.execute(f"""
                    SELECT probability, prediction FROM predictions
                    WHERE {where_clause}
                    ORDER BY game_date DESC
                    LIMIT ?
                """, params + [self.window]).fetchall()

                probs = []
                for r in rows:
                    p = float(r["probability"])
                    # Convert directional confidence back to prob_over
                    if r["prediction"] == "UNDER":
                        p = 1.0 - p
                    probs.append(p)

                conn.close()
                return probs
            except sqlite3.OperationalError:
                pass

            conn.close()
        except Exception:
            pass

        return []

    # ------------------------------------------------------------------
    # SHAP report
    # ------------------------------------------------------------------

    def _run_shap_report(
        self, sport: str, prop_type: str, line: float = None
    ) -> list[str]:
        """
        Run SHAP analysis to identify which features are driving drift.

        Returns list of top-3 feature names ranked by absolute SHAP value change.
        Empty list if SHAP unavailable or model can't be loaded.
        """
        if not _SHAP_AVAILABLE or self._predictor is None:
            return []

        try:
            cached = self._predictor._get_cached_model(sport, prop_type, line or 0.0)
            model    = cached.get("model")
            scaler   = cached.get("scaler")
            metadata = cached.get("metadata")

            if model is None or scaler is None:
                return []

            # Load recent raw features from DB
            feature_matrix = self._load_recent_features(sport, prop_type, line, metadata)
            if feature_matrix is None or len(feature_matrix) < 5:
                return []

            feature_matrix_scaled = scaler.transform(feature_matrix)

            # Use TreeExplainer for XGBoost/RF; LinearExplainer for LR
            model_type = getattr(metadata, "model_type", "xgboost")
            try:
                if model_type in ("xgboost", "random_forest", "gradient_boosting"):
                    explainer = _shap.TreeExplainer(model)
                else:
                    explainer = _shap.LinearExplainer(model, feature_matrix_scaled)

                shap_values = explainer.shap_values(feature_matrix_scaled)
                if isinstance(shap_values, list):
                    shap_values = shap_values[1]  # class 1 (OVER) for binary classifiers

                mean_abs_shap = np.abs(shap_values).mean(axis=0)
                feature_names = getattr(metadata, "feature_names", []) or []

                if len(feature_names) == len(mean_abs_shap):
                    ranked = sorted(
                        zip(feature_names, mean_abs_shap),
                        key=lambda x: -x[1],
                    )
                    return [name for name, _ in ranked[:3]]

            except Exception:
                pass

        except Exception:
            pass

        return []

    def _load_recent_features(self, sport, prop_type, line, metadata) -> Optional[np.ndarray]:
        """Load recent feature vectors for SHAP analysis."""
        db_path = _DB_PATHS.get(sport)
        if db_path is None or not db_path.exists():
            return None

        cutoff = (_date.today() - timedelta(days=30)).isoformat()
        feature_names = getattr(metadata, "feature_names", []) or []
        if not feature_names:
            return None

        try:
            conn = sqlite3.connect(str(db_path), timeout=10)

            if sport == "nba":
                # NBA stores features as individual columns
                cols = [f for f in feature_names if f in self._get_nba_columns(conn)]
                if not cols:
                    conn.close()
                    return None
                query = f"SELECT {', '.join(cols)} FROM predictions WHERE prop_type=? AND game_date>=? LIMIT 100"
                rows = conn.execute(query, (prop_type, cutoff)).fetchall()
                conn.close()
                if not rows:
                    return None
                return np.array([[r[i] for i in range(len(cols))] for r in rows], dtype=float)
            else:
                # NHL/MLB: features stored as JSON
                rows = conn.execute("""
                    SELECT features_json FROM predictions
                    WHERE prop_type=? AND game_date>=? AND features_json IS NOT NULL
                    LIMIT 100
                """, (prop_type, cutoff)).fetchall()
                conn.close()
                if not rows:
                    return None

                vectors = []
                for row in rows:
                    try:
                        feat = json.loads(row[0]) if row[0] else {}
                        vec = [feat.get(f, feat.get(f.lstrip("f_"), 0.0)) for f in feature_names]
                        vectors.append(vec)
                    except (json.JSONDecodeError, TypeError):
                        continue
                return np.array(vectors, dtype=float) if vectors else None

        except Exception:
            return None

    def _get_nba_columns(self, conn) -> set:
        try:
            rows = conn.execute("PRAGMA table_info(predictions)").fetchall()
            return {r[1] for r in rows}
        except Exception:
            return set()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_prop_dir(self, dir_name: str) -> tuple[str, Optional[float]]:
        """Parse "points_24_5" → ("points", 24.5)"""
        parts = dir_name.rsplit("_", 2)
        if len(parts) >= 3:
            try:
                line = float(f"{parts[-2]}.{parts[-1]}")
                prop_type = "_".join(parts[:-2])
                return prop_type, line
            except ValueError:
                pass
        if len(parts) >= 2:
            try:
                line = float(parts[-1])
                prop_type = "_".join(parts[:-1])
                return prop_type, line
            except ValueError:
                pass
        return dir_name, None

    def _write_log(self, report: dict) -> None:
        sport = report.get("sport", "unknown")
        today = _date.today().isoformat()
        log_path = _LOGS_DIR / f"{sport}_{today}.json"

        existing: list[dict] = []
        if log_path.exists():
            try:
                existing = json.loads(log_path.read_text())
                if not isinstance(existing, list):
                    existing = [existing]
            except (json.JSONDecodeError, ValueError):
                existing = []

        existing.append(report)
        log_path.write_text(json.dumps(existing, indent=2))

    def _alert(self, sport: str, prop_type: str, line: float, report: dict) -> None:
        line_str = f" @ {line}" if line else ""
        shap_str = ""
        if report.get("top_drifting"):
            shap_str = f"\nTop drifting features: {', '.join(report['top_drifting'])}"

        msg = (
            f"DRIFT ALERT [{sport.upper()}] {prop_type}{line_str}\n"
            f"KS stat: {report['ks_stat']:.3f}  p-value: {report['p_value']:.4f}\n"
            f"Recent mean prob: {report['mean_prob_recent']:.3f}  "
            f"Training mean: {report['mean_prob_training']:.3f}"
            f"{shap_str}\n"
            f"Action: Run manual audit before next retrain."
        )
        _send_discord_alert(self.discord_url, msg)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse

    parser = argparse.ArgumentParser(description="KS Drift Detector — ML v2")
    sub = parser.add_subparsers(dest="cmd")

    check_cmd = sub.add_parser("check", help="Check drift for a sport/prop")
    check_cmd.add_argument("sport",     choices=["nba", "nhl", "mlb"])
    check_cmd.add_argument("prop_type", help="e.g. points")
    check_cmd.add_argument("--line",    type=float, default=None)
    check_cmd.add_argument("--no-shap", action="store_true")

    all_cmd = sub.add_parser("check-all", help="Check all props for a sport")
    all_cmd.add_argument("sport", choices=["nba", "nhl", "mlb"])
    all_cmd.add_argument("--no-shap", action="store_true")

    sum_cmd = sub.add_parser("summary", help="Drift summary for recent days")
    sum_cmd.add_argument("sport",  choices=["nba", "nhl", "mlb"])
    sum_cmd.add_argument("--days", type=int, default=7)

    args = parser.parse_args()
    detector = DriftDetector()

    if args.cmd == "check":
        report = detector.check(args.sport, args.prop_type, args.line, run_shap=not args.no_shap)
        print(f"\n{report['message']}")
        print(f"  KS={report['ks_stat']}  p={report['p_value']}  "
              f"n={report['sample_size']}  training_n={report['training_size']}")
        if report["top_drifting"]:
            print(f"  Top drifting: {', '.join(report['top_drifting'])}")

    elif args.cmd == "check-all":
        reports = detector.check_all(args.sport, run_shap=not args.no_shap)
        drifted = [r for r in reports if r["drifted"]]
        print(f"\n{args.sport.upper()}: {len(drifted)}/{len(reports)} props drifted")
        for r in drifted:
            line_str = f" @ {r['line']}" if r["line"] else ""
            print(f"  DRIFT: {r['prop_type']}{line_str}  KS={r['ks_stat']}  p={r['p_value']}")

    elif args.cmd == "summary":
        s = detector.summary(args.sport, args.days)
        print(f"\n{s['sport'].upper()} drift summary (last {s['period_days']} days):")
        print(f"  Checks: {s['total_checks']}  Drift events: {s['drift_events']}")
        if s["props_drifted"]:
            print(f"  Props with drift: {', '.join(s['props_drifted'])}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _main()
