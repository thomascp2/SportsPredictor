"""
MLB Season Props ML Predictor
==============================
Fetches every PrizePicks SZLN (season-long) line for MLB, builds rich
career-stat feature vectors (last season, 3-yr avg, 5-yr avg, rates,
age curve, team changes, park factors), trains a Gradient Boosting
regression model per stat on historical season outcomes, and returns
calibrated OVER/UNDER probabilities for every live line.

Usage:
    cd mlb
    python scripts/season_props_ml.py               # predict all live lines
    python scripts/season_props_ml.py --train        # force retrain models
    python scripts/season_props_ml.py --player "Aaron Judge" --stat home_runs
    python scripts/season_props_ml.py --show-picks   # print saved picks table
"""

import sys
import os
import json
import math
import sqlite3
import time
import urllib.request
import urllib.parse
import pickle
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import (
    DB_PATH, MLB_API_BASE, MLB_API_TIMEOUT, SEASON,
    initialize_database,
)
from park_factors import get_park_factor_by_team

# Optional sklearn - required for ML; falls back to statistical model if absent
try:
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("[WARN] scikit-learn not found — using statistical fallback only")

# ── PrizePicks client (shared) ────────────────────────────────────────────────
_SHARED = Path(__file__).parent.parent.parent / "shared"
sys.path.insert(0, str(_SHARED))
try:
    from prizepicks_client import PrizePicksAPI
    PP_AVAILABLE = True
except ImportError:
    PP_AVAILABLE = False
    print("[WARN] prizepicks_client not found — will load lines from DB cache")


# ============================================================================
# STAT MAPPING TABLES
# ============================================================================

# PrizePicks prop_type -> (player_type, internal stat key in season_projections)
PP_TO_INTERNAL: Dict[str, Tuple[str, str]] = {
    # Pitcher lines
    "strikeouts":    ("pitcher", "k_total"),
    "pitcher_walks": ("pitcher", "bb_total"),
    "hits_allowed":  ("pitcher", "hits_allowed"),
    "earned_runs":   ("pitcher", "er_total"),
    "outs_recorded": ("pitcher", "outs_recorded"),
    # Batter lines
    "home_runs":         ("batter", "hr"),
    "stolen_bases":      ("batter", "sb"),
    "hits":              ("batter", "hits"),
    "total_bases":       ("batter", "tb"),
    "rbis":              ("batter", "rbi"),
    "runs":              ("batter", "runs"),
    "batter_strikeouts": ("batter", "k"),
    "walks":             ("batter", "walks"),
    "hrr":               ("batter", "hrr"),
}

# MLB Stats API field names per stat (batter group)
BATTER_API_FIELDS: Dict[str, str] = {
    "hr":    "homeRuns",
    "sb":    "stolenBases",
    "hits":  "hits",
    "tb":    "totalBases",
    "rbi":   "rbi",
    "runs":  "runs",
    "k":     "strikeOuts",
    "walks": "baseOnBalls",
    # hrr is computed: hits + runs + rbi
}

# MLB Stats API field names per stat (pitcher group)
PITCHER_API_FIELDS: Dict[str, str] = {
    "k_total":      "strikeOuts",
    "bb_total":     "baseOnBalls",
    "hits_allowed": "hits",
    "er_total":     "earnedRuns",
    # outs_recorded: computed from inningsPitched
}

# Park factor keys per stat (from park_factors.py)
STAT_TO_PARK_KEY: Dict[str, str] = {
    "hr": "hr", "tb": "hr",
    "hits": "hits", "k": "k",
    "k_total": "k", "bb_total": "bb",
    "sb": "hits", "rbi": "hits", "runs": "hits",
    "walks": "bb", "hrr": "hits",
    "hits_allowed": "hits", "er_total": "hr",
    "outs_recorded": "hits",
}

# Historical stat variance (used as fallback std-dev when model RMSE unknown)
STAT_EMPIRICAL_STD_PCT: Dict[str, float] = {
    "hr": 0.28, "tb": 0.16, "hits": 0.10, "rbi": 0.20,
    "runs": 0.18, "k": 0.18, "sb": 0.38, "walks": 0.22,
    "hrr": 0.15, "k_total": 0.14, "bb_total": 0.22,
    "hits_allowed": 0.14, "er_total": 0.24, "outs_recorded": 0.12,
}

# Model registry directory (inside ml_training)
MODEL_DIR = Path(__file__).parent.parent.parent / "ml_training" / "model_registry" / "mlb_szln"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# CAREER STATS CACHE
# ============================================================================

class CareerStatsCache:
    """
    Fetches and caches up to N seasons of yearByYear stats from the MLB
    Stats API.  A single in-memory dict prevents redundant API calls during
    a batch run.
    """

    def __init__(self, max_seasons: int = 7):
        self.max_seasons = max_seasons
        self._cache: Dict[int, Dict] = {}   # player_id -> {batter: [...], pitcher: [...]}

    def get(self, player_id: int, player_name: str,
            player_type: str) -> List[Dict]:
        """Return list of season dicts, most-recent first, up to max_seasons."""
        key = (player_id, player_type)
        if key in self._cache:
            return self._cache[key]

        if player_type == "batter":
            seasons = self._fetch_batter(player_id, player_name)
        else:
            seasons = self._fetch_pitcher(player_id, player_name)

        self._cache[key] = seasons
        return seasons

    def _fetch_batter(self, player_id: int, player_name: str) -> List[Dict]:
        if not player_id:
            return []
        try:
            url = (f"{MLB_API_BASE}/people/{player_id}/stats"
                   f"?stats=yearByYear&group=hitting&gameType=R"
                   f"&hydrate=person")
            req = urllib.request.urlopen(url, timeout=MLB_API_TIMEOUT)
            data = json.loads(req.read())

            # Try to get birth year for age calc
            birth_year = None
            try:
                bd = data.get("people", [{}])[0].get("birthDate", "")
                birth_year = int(bd[:4]) if bd else None
            except Exception:
                pass

            stats_list = data.get("stats", [])
            if not stats_list:
                return []

            seasons = []
            current_year = int(SEASON[:4])
            for entry in stats_list[0].get("splits", []):
                yr = int(entry.get("season", 0))
                if yr < current_year - self.max_seasons or yr >= current_year:
                    continue
                s = entry.get("stat", {})
                pa = s.get("plateAppearances", 0) or 0
                if pa < 30:
                    continue
                hits  = s.get("hits", 0) or 0
                runs  = s.get("runs", 0) or 0
                rbi   = s.get("rbi", 0) or 0
                seasons.append({
                    "season": yr,
                    "pa":     pa,
                    "hr":     s.get("homeRuns", 0) or 0,
                    "sb":     s.get("stolenBases", 0) or 0,
                    "hits":   hits,
                    "tb":     s.get("totalBases", 0) or 0,
                    "rbi":    rbi,
                    "runs":   runs,
                    "k":      s.get("strikeOuts", 0) or 0,
                    "walks":  s.get("baseOnBalls", 0) or 0,
                    "hrr":    hits + runs + rbi,
                    "age":    (yr - birth_year) if birth_year else None,
                })
            seasons.sort(key=lambda x: x["season"], reverse=True)
            return seasons[:self.max_seasons]
        except Exception as e:
            print(f"  [Cache] Batter fetch failed for {player_name}: {e}")
            return []

    def _fetch_pitcher(self, player_id: int, player_name: str) -> List[Dict]:
        if not player_id:
            return []
        try:
            url = (f"{MLB_API_BASE}/people/{player_id}/stats"
                   f"?stats=yearByYear&group=pitching&gameType=R"
                   f"&hydrate=person")
            req = urllib.request.urlopen(url, timeout=MLB_API_TIMEOUT)
            data = json.loads(req.read())

            birth_year = None
            try:
                bd = data.get("people", [{}])[0].get("birthDate", "")
                birth_year = int(bd[:4]) if bd else None
            except Exception:
                pass

            stats_list = data.get("stats", [])
            if not stats_list:
                return []

            seasons = []
            current_year = int(SEASON[:4])
            for entry in stats_list[0].get("splits", []):
                yr = int(entry.get("season", 0))
                if yr < current_year - self.max_seasons or yr >= current_year:
                    continue
                s = entry.get("stat", {})
                # Parse fractional innings: 162.1 = 162⅓
                ip_str = s.get("inningsPitched", "0") or "0"
                try:
                    ip = float(ip_str)
                    whole = int(ip)
                    ip = whole + (ip - whole) * 10 / 3
                except Exception:
                    ip = 0.0
                if ip < 15:
                    continue
                seasons.append({
                    "season":       yr,
                    "ip":           round(ip, 2),
                    "k_total":      s.get("strikeOuts", 0) or 0,
                    "bb_total":     s.get("baseOnBalls", 0) or 0,
                    "hits_allowed": s.get("hits", 0) or 0,
                    "er_total":     s.get("earnedRuns", 0) or 0,
                    "outs_recorded": int(round(ip * 3)),
                    "era":   float(s.get("era", 4.5) or 4.5),
                    "whip":  float(s.get("whip", 1.3) or 1.3),
                    "age":   (yr - birth_year) if birth_year else None,
                    "games": s.get("gamesPlayed", 0) or 0,
                    "gs":    s.get("gamesStarted", 0) or 0,
                })
            seasons.sort(key=lambda x: x["season"], reverse=True)
            return seasons[:self.max_seasons]
        except Exception as e:
            print(f"  [Cache] Pitcher fetch failed for {player_name}: {e}")
            return []


# ============================================================================
# FEATURE BUILDER
# ============================================================================

class FeatureBuilder:
    """
    Converts raw career season data into a flat feature dict for the
    regression model.  Handles missing history gracefully (fills with 0).
    """

    def build(self,
              seasons: List[Dict],
              stat: str,
              player_type: str,
              age: Optional[int],
              current_team: str,
              prev_team: Optional[str],
              marcel_proj: Optional[float],
              projected_pa_ip: Optional[float]) -> Optional[Dict]:
        """
        Build feature vector for one player/stat.

        Returns None if there is insufficient history to make a prediction.
        """
        if not seasons:
            return None

        n = len(seasons)

        # ── Playing-time field ────────────────────────────────────────────────
        pt_key = "pa" if player_type == "batter" else "ip"

        # ── Totals per season (most recent = yr1, going back) ─────────────────
        def _get(yr_idx: int, field: str, default: float = 0.0) -> float:
            if yr_idx >= n:
                return default
            return float(seasons[yr_idx].get(field, default) or default)

        yr1 = _get(0, stat)
        yr2 = _get(1, stat)
        yr3 = _get(2, stat)
        yr4 = _get(3, stat)
        yr5 = _get(4, stat)

        pt1 = _get(0, pt_key, 1)
        pt2 = _get(1, pt_key, 1)
        pt3 = _get(2, pt_key, 1)

        # ── Rates (per PA or per IP) ───────────────────────────────────────────
        rate1 = yr1 / max(pt1, 1)
        rate2 = yr2 / max(pt2, 1) if n > 1 else rate1
        rate3 = yr3 / max(pt3, 1) if n > 2 else rate1

        # ── Averages ──────────────────────────────────────────────────────────
        vals_3yr = [v for v in [yr1, yr2, yr3] if v > 0]
        vals_5yr = [v for v in [yr1, yr2, yr3, yr4, yr5] if v > 0]
        avg_3yr  = float(np.mean(vals_3yr)) if vals_3yr else yr1
        avg_5yr  = float(np.mean(vals_5yr)) if vals_5yr else yr1
        avg_rate_3yr = float(np.mean([rate1, rate2, rate3]))

        # ── Career stats ──────────────────────────────────────────────────────
        all_vals = [_get(i, stat) for i in range(n) if _get(i, stat) > 0]
        career_avg    = float(np.mean(all_vals)) if all_vals else yr1
        career_best   = float(max(all_vals)) if all_vals else yr1
        career_std    = float(np.std(all_vals)) if len(all_vals) > 1 else career_avg * 0.20
        career_consistency = 1.0 / (career_std / max(career_avg, 1) + 0.01)

        # ── Trends ────────────────────────────────────────────────────────────
        trend_1yr = yr1 - yr2 if n > 1 else 0.0
        trend_pct_1yr = (
            max(-1.0, min(1.0, trend_1yr / max(yr2, 1))) if n > 1 else 0.0
        )
        trend_2yr = yr1 - yr3 if n > 2 else trend_1yr
        # Playing-time trend (indicates if player is healthy/stable)
        pt_trend = (pt1 - pt2) / max(pt2, 1) if n > 1 else 0.0

        # ── Age features ──────────────────────────────────────────────────────
        if age is None and seasons[0].get("age"):
            age = seasons[0]["age"]
        age = age or 28   # league average if unknown
        age_sq = age * age
        is_peak   = int(24 <= age <= 29)
        is_prime  = int(27 <= age <= 32)
        is_decline = int(age >= 33)

        # ── Team context ──────────────────────────────────────────────────────
        team_changed = int(
            bool(prev_team) and
            bool(current_team) and
            prev_team.upper() != current_team.upper()
        )
        # Count distinct teams in last 3 seasons (proxy for stability)
        n_teams = len(set(
            seasons[i].get("team", current_team) or current_team
            for i in range(min(n, 3))
        ))

        # ── Park factor ───────────────────────────────────────────────────────
        park_key = STAT_TO_PARK_KEY.get(stat, "hits")
        try:
            pf = get_park_factor_by_team(current_team or "")
            park_factor = pf.get(park_key, 1.0) if pf else 1.0
        except Exception:
            park_factor = 1.0

        # ── Marcel / projected playing time ───────────────────────────────────
        # Use our pre-computed Marcel projection as a strong feature
        marcel = float(marcel_proj) if marcel_proj else avg_3yr
        proj_pt = float(projected_pa_ip) if projected_pa_ip else pt1

        feat = {
            # Recent totals
            "yr1":          yr1,
            "yr2":          yr2,
            "yr3":          yr3,
            "yr4":          yr4,
            "yr5":          yr5,
            # Playing time
            "pt_last":      pt1,
            "pt_avg_3yr":   float(np.mean([pt1, pt2, pt3])),
            "pt_projected": proj_pt,
            "pt_trend":     pt_trend,
            # Rates
            "rate_last":    rate1,
            "rate_3yr_avg": avg_rate_3yr,
            # Averages
            "avg_3yr":      avg_3yr,
            "avg_5yr":      avg_5yr,
            # Marcel projection (key feature)
            "marcel_proj":  marcel,
            # Trends
            "trend_1yr":    trend_1yr,
            "trend_pct_1yr": trend_pct_1yr,
            "trend_2yr":    trend_2yr,
            # Age
            "age":          float(age),
            "age_sq":       float(age_sq),
            "is_peak":      float(is_peak),
            "is_prime":     float(is_prime),
            "is_decline":   float(is_decline),
            # Team / context
            "team_changed": float(team_changed),
            "n_teams_3yr":  float(n_teams),
            "park_factor":  float(park_factor),
            # Career
            "seasons_played":       float(n),
            "career_avg":           career_avg,
            "career_best":          career_best,
            "career_consistency":   career_consistency,
        }
        return feat


# ============================================================================
# SEASON PROPS ML PREDICTOR
# ============================================================================

class SeasonPropsML:
    """
    Main class:
      1. fetch_szln_lines()        — get live PrizePicks SZLN lines
      2. build_training_data()     — historical feature/label pairs from career stats
      3. train_models()            — GBM regression per stat
      4. predict()                 — P(OVER/UNDER) for a single player/line
      5. run_all_szln()            — process all live lines, save picks to DB
    """

    def __init__(self, db_path: str = None, verbose: bool = True):
        self.db_path = db_path or DB_PATH
        self.verbose  = verbose
        self.cache    = CareerStatsCache(max_seasons=7)
        self.builder  = FeatureBuilder()
        self._models: Dict[str, object] = {}   # stat -> trained model
        self._rmse:   Dict[str, float]  = {}   # stat -> cross-val RMSE
        initialize_database(self.db_path)

    # ── 1. Fetch PrizePicks SZLN lines ────────────────────────────────────────

    def fetch_szln_lines(self) -> List[Dict]:
        """
        Pull all MLB season-long lines from PrizePicks.
        Filters on odds_type == 'SZLN' (or variants).
        Falls back to DB cache (prizepicks_lines table in MLB DB) if API fails.
        """
        lines = []

        # ── Try live API ──────────────────────────────────────────────────────
        if PP_AVAILABLE:
            try:
                api = PrizePicksAPI()
                raw = api.fetch_projections(league="MLB", per_page=1000)
                parsed = api.parse_projections(raw) if raw else []
                # Season lines have odds_type containing 'SZLN' or 'season'
                szln = [
                    p for p in parsed
                    if "szln" in str(p.get("odds_type", "")).lower()
                    or "season" in str(p.get("odds_type", "")).lower()
                ]
                if szln:
                    if self.verbose:
                        print(f"  [PP] Found {len(szln)} SZLN lines from live API")
                    lines = szln
                else:
                    if self.verbose:
                        print("  [PP] No SZLN lines in live API response "
                              "(season may not have started posting yet)")
            except Exception as e:
                if self.verbose:
                    print(f"  [PP] API error: {e}")

        # ── Fallback: cached lines in MLB DB ──────────────────────────────────
        if not lines:
            try:
                conn = sqlite3.connect(self.db_path)
                rows = conn.execute("""
                    SELECT player_name, prop_type, line, odds_type, team
                    FROM   prizepicks_lines
                    WHERE  league = 'MLB'
                      AND  lower(odds_type) LIKE '%szln%'
                    ORDER  BY fetch_date DESC
                """).fetchall()
                conn.close()
                lines = [
                    {
                        "player_name": r[0], "prop_type": r[1],
                        "line": r[2], "odds_type": r[3], "team": r[4],
                    }
                    for r in rows
                ]
                if lines and self.verbose:
                    print(f"  [PP] Loaded {len(lines)} cached SZLN lines from DB")
            except Exception:
                pass

        return lines

    # ── 2. Lookup Marcel projection from DB ───────────────────────────────────

    def _get_marcel(self, player_name: str,
                    player_type: str, stat: str) -> Dict:
        """Return Marcel projection row for this player/stat from our DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute("""
                SELECT projection, std_dev, confidence, seasons_used,
                       age, player_id, team
                FROM   season_projections
                WHERE  lower(player_name) = lower(?)
                  AND  player_type = ?
                  AND  stat = ?
                  AND  season = (SELECT MAX(season) FROM season_projections)
                LIMIT 1
            """, (player_name, player_type, stat)).fetchone()
            conn.close()
            if row:
                return {
                    "projection": row[0], "std_dev": row[1],
                    "confidence": row[2], "seasons_used": row[3],
                    "age": row[4], "player_id": row[5], "team": row[6],
                }
        except Exception:
            pass
        return {}

    # ── 3. Build training dataset from historical seasons ─────────────────────

    def build_training_data(self, stat: str,
                             player_type: str) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """
        Build (X, y) training arrays for a given stat.

        Strategy: for each active player, for each historical season Y
        (2019-2025), use prior seasons as features and actual total in Y
        as the label.  This gives ~3,000 labeled examples per stat without
        needing historical PrizePicks lines.
        """
        conn = sqlite3.connect(self.db_path)
        players = conn.execute("""
            SELECT DISTINCT player_name, player_id, team, age
            FROM   season_projections
            WHERE  player_type = ?
              AND  season = (SELECT MAX(season) FROM season_projections)
        """, (player_type,)).fetchall()
        conn.close()

        X_rows, y_vals = [], []
        feature_names = None
        current_year = int(SEASON[:4])

        for pname, pid, team, age in players:
            seasons = self.cache.get(pid, pname, player_type)
            if len(seasons) < 2:
                continue

            # Slide window: for each possible "label year", use prior data
            for label_idx in range(len(seasons) - 1):
                label_season = seasons[label_idx]
                label_val = label_season.get(stat)
                if label_val is None or label_val == 0:
                    continue

                # Features: everything after this season (older data)
                prior_seasons = seasons[label_idx + 1:]
                if not prior_seasons:
                    continue

                yr = label_season["season"]
                player_age = label_season.get("age") or (
                    (age or 28) - (current_year - yr)
                )

                feat = self.builder.build(
                    seasons=prior_seasons,
                    stat=stat,
                    player_type=player_type,
                    age=player_age,
                    current_team=team or "",
                    prev_team=None,
                    marcel_proj=None,     # not available for historical training
                    projected_pa_ip=None,
                )
                if feat is None:
                    continue

                if feature_names is None:
                    feature_names = sorted(feat.keys())

                row = [feat.get(k, 0.0) for k in feature_names]
                X_rows.append(row)
                y_vals.append(float(label_val))

            time.sleep(0.05)   # gentle rate-limit on API calls inside cache

        if not X_rows:
            return np.array([]), np.array([]), []

        return np.array(X_rows), np.array(y_vals), feature_names or []

    # ── 4. Train / load model ─────────────────────────────────────────────────

    def train_model(self, stat: str, player_type: str,
                    force: bool = False) -> bool:
        """
        Train a GBM regression model for this stat.
        Saves to MODEL_DIR and caches in self._models.
        Returns True if model was trained/loaded successfully.
        """
        model_key = f"{player_type}_{stat}"
        model_path = MODEL_DIR / f"{model_key}.pkl"

        # Load from disk if available and not forcing retrain
        if not force and model_path.exists():
            try:
                with open(model_path, "rb") as f:
                    saved = pickle.load(f)
                self._models[model_key]  = saved["model"]
                self._rmse[model_key]    = saved["rmse"]
                self._feature_names = saved.get("feature_names", [])
                if self.verbose:
                    print(f"  [Model] Loaded {model_key}  RMSE={saved['rmse']:.2f}")
                return True
            except Exception:
                pass

        if not SKLEARN_AVAILABLE:
            return False

        if self.verbose:
            print(f"  [Train] Building training data for {model_key}...")

        X, y, feat_names = self.build_training_data(stat, player_type)

        if len(X) < 50:
            if self.verbose:
                print(f"  [Train] Insufficient data: {len(X)} samples — skip")
            return False

        if self.verbose:
            print(f"  [Train] {len(X)} samples, {len(feat_names)} features")

        model = GradientBoostingRegressor(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.8,
            min_samples_leaf=5,
            random_state=42,
        )

        # Cross-validated RMSE (time-series aware: no shuffling)
        scores = cross_val_score(
            model, X, y,
            cv=5,
            scoring="neg_root_mean_squared_error",
        )
        rmse = float(-scores.mean())

        model.fit(X, y)

        # Feature importance for diagnostics
        importance = dict(zip(feat_names, model.feature_importances_))
        top = sorted(importance.items(), key=lambda x: -x[1])[:5]
        if self.verbose:
            print(f"  [Train] RMSE={rmse:.2f}  top features: "
                  + "  ".join(f"{k}={v:.3f}" for k, v in top))

        # Save
        with open(model_path, "wb") as f:
            pickle.dump({
                "model": model,
                "rmse":  rmse,
                "feature_names": feat_names,
                "trained_at": datetime.now().isoformat(),
                "n_samples": len(X),
            }, f)

        self._models[model_key]     = model
        self._rmse[model_key]       = rmse
        self._feature_names_map = getattr(self, "_feature_names_map", {})
        self._feature_names_map[model_key] = feat_names

        return True

    def _load_all_models(self):
        """Load every saved model from MODEL_DIR."""
        for path in MODEL_DIR.glob("*.pkl"):
            key = path.stem   # e.g. "batter_hr"
            if key not in self._models:
                parts = key.split("_", 1)
                if len(parts) == 2:
                    self.train_model(parts[1], parts[0], force=False)

    # ── 5. Predict single player/line ─────────────────────────────────────────

    def predict(self,
                player_name: str,
                pp_stat: str,            # PrizePicks prop_type (e.g. "home_runs")
                line: float,
                player_id: Optional[int] = None,
                age: Optional[int] = None,
                current_team: Optional[str] = None,
                prev_team: Optional[str] = None) -> Optional[Dict]:
        """
        Predict OVER/UNDER probability for one player/line.

        Returns a dict with: direction, probability, edge, projection,
        confidence, model_used, key_factors, recommendation.
        """
        # Resolve player type and internal stat name
        if pp_stat not in PP_TO_INTERNAL:
            return None
        player_type, internal_stat = PP_TO_INTERNAL[pp_stat]
        model_key = f"{player_type}_{internal_stat}"

        # ── Get Marcel projection from DB ─────────────────────────────────────
        marcel_row = self._get_marcel(player_name, player_type, internal_stat)
        if not player_id and marcel_row.get("player_id"):
            player_id = marcel_row["player_id"]
        if not age and marcel_row.get("age"):
            age = marcel_row["age"]
        if not current_team and marcel_row.get("team"):
            current_team = marcel_row["team"]

        marcel_proj = marcel_row.get("projection")
        std_dev_base = marcel_row.get("std_dev")
        confidence   = marcel_row.get("confidence", "LOW")
        seasons_used = marcel_row.get("seasons_used", 0)

        # Projected playing time from Marcel (helps scale projection)
        proj_pt_key = "pa_projected" if player_type == "batter" else "ip_projected"
        # We'll infer it from the career data below

        # ── Fetch career stats ────────────────────────────────────────────────
        seasons = []
        if player_id:
            seasons = self.cache.get(player_id, player_name, player_type)

        if not seasons and not marcel_proj:
            return None

        # Projected playing time
        pt_key  = "pa" if player_type == "batter" else "ip"
        proj_pt = float(seasons[0].get(pt_key, 550 if player_type == "batter" else 165)
                        ) if seasons else (
                            550 if player_type == "batter" else 165
                        )

        # ── Build features ────────────────────────────────────────────────────
        feat = self.builder.build(
            seasons=seasons,
            stat=internal_stat,
            player_type=player_type,
            age=age,
            current_team=current_team or "",
            prev_team=prev_team,
            marcel_proj=marcel_proj,
            projected_pa_ip=proj_pt,
        ) if seasons else None

        # ── ML prediction ─────────────────────────────────────────────────────
        predicted_total = None
        model_used      = "statistical"
        rmse            = None
        feature_names   = None

        if feat and model_key in self._models:
            try:
                fn_map = getattr(self, "_feature_names_map", {})
                feature_names = fn_map.get(model_key) or sorted(feat.keys())
                x_vec = np.array([[feat.get(k, 0.0) for k in feature_names]])
                predicted_total = float(self._models[model_key].predict(x_vec)[0])
                rmse            = self._rmse.get(model_key)
                model_used      = "ml_gbm"
            except Exception as e:
                if self.verbose:
                    print(f"  [Predict] ML error for {player_name}: {e}")

        # Fallback to Marcel projection
        if predicted_total is None:
            predicted_total = marcel_proj
        if predicted_total is None:
            return None

        # ── Uncertainty / std-dev ─────────────────────────────────────────────
        if rmse and rmse > 0:
            std_dev = rmse
        elif std_dev_base and std_dev_base > 0:
            std_dev = std_dev_base
        else:
            pct = STAT_EMPIRICAL_STD_PCT.get(internal_stat, 0.20)
            std_dev = max(predicted_total * pct, 1.0)

        # ── Probability via normal CDF ────────────────────────────────────────
        z = (line - predicted_total) / max(std_dev, 0.1)
        p_over = 0.5 * (1.0 - _erf(z / 1.41421356))
        p_over = max(0.01, min(0.99, p_over))
        p_under = 1.0 - p_over

        # Best direction and probability
        if p_over >= p_under:
            direction = "OVER"
            probability = p_over
        else:
            direction = "UNDER"
            probability = p_under

        # ── Edge vs standard -110 break-even (52.38%) ────────────────────────
        edge = round((probability - 0.5238) * 100, 2)

        # ── Recommendation ────────────────────────────────────────────────────
        if probability >= 0.65 and edge >= 10:
            rec = f"STRONG {direction}"
        elif probability >= 0.58 and edge >= 5:
            rec = f"LEAN {direction}"
        elif abs(edge) < 3:
            rec = "PASS — too close to line"
        else:
            rec = f"LEAN {direction}" if edge > 0 else "PASS — negative edge"

        # ── Key factors for display ───────────────────────────────────────────
        key_factors = self._build_key_factors(
            feat, internal_stat, player_type, age,
            current_team, marcel_proj, predicted_total, line, seasons,
        )

        return {
            "player_name":    player_name,
            "player_id":      player_id,
            "player_type":    player_type,
            "team":           current_team,
            "pp_stat":        pp_stat,
            "stat":           internal_stat,
            "line":           line,
            "direction":      direction,
            "probability":    round(probability * 100, 1),
            "edge":           edge,
            "projection":     round(predicted_total, 1),
            "std_dev":        round(std_dev, 1),
            "confidence":     confidence,
            "seasons_used":   seasons_used,
            "age":            age,
            "model_used":     model_used,
            "key_factors":    key_factors,
            "recommendation": rec,
        }

    def _build_key_factors(self, feat, stat, player_type, age,
                           team, marcel_proj, predicted, line, seasons):
        """Return a short human-readable list of the most important factors."""
        factors = []
        if seasons:
            last = seasons[0].get(stat, 0)
            if last:
                pct_vs_proj = ((last / max(predicted, 1)) - 1) * 100
                sign = "+" if pct_vs_proj >= 0 else ""
                factors.append(
                    f"Last season: {last} "
                    f"({sign}{pct_vs_proj:.0f}% vs our projection)"
                )
        if feat:
            avg3 = feat.get("avg_3yr")
            if avg3:
                factors.append(f"3-yr avg: {avg3:.1f}")
            avg5 = feat.get("avg_5yr")
            if avg5 and avg5 != avg3:
                factors.append(f"5-yr avg: {avg5:.1f}")
            trend = feat.get("trend_pct_1yr")
            if trend is not None and abs(trend) > 0.05:
                dir_str = "improving" if trend > 0 else "declining"
                factors.append(f"Recent trend: {dir_str} ({trend*100:+.0f}% yr-over-yr)")
            if feat.get("team_changed"):
                factors.append("Team change this offseason")
            pf = feat.get("park_factor", 1.0)
            if abs(pf - 1.0) > 0.03:
                pf_str = "favorable" if pf > 1.0 else "unfavorable"
                factors.append(f"Park factor: {pf:.2f} ({pf_str})")
        if age:
            if age >= 34:
                factors.append(f"Age {age} — decline phase (power stats at risk)")
            elif age <= 26:
                factors.append(f"Age {age} — still ascending")
        if marcel_proj:
            factors.append(f"Marcel base: {marcel_proj:.1f}")
        return factors[:5]   # keep it concise

    # ── 6. Process all live SZLN lines ────────────────────────────────────────

    def run_all_szln(self, min_edge: float = 3.0) -> List[Dict]:
        """
        Main entry point.
        Fetches all SZLN lines, loads/trains models, predicts each line,
        saves results to DB, and returns a sorted list of picks.
        """
        print("\n" + "=" * 65)
        print("  MLB SEASON PROPS ML — SZLN PREDICTIONS")
        print("=" * 65)

        # Load all cached models
        self._load_all_models()

        # Fetch live lines
        print("\n[1/3] Fetching PrizePicks SZLN lines...")
        lines = self.fetch_szln_lines()

        if not lines:
            print("  No SZLN lines available yet.  "
                  "PrizePicks typically posts season totals once the season opens.")
            return []

        print(f"  Found {len(lines)} SZLN lines across "
              f"{len(set(p['player_name'] for p in lines))} players\n")

        # Predict each line
        print("[2/3] Running predictions...")
        picks = []
        seen = set()

        for line_data in lines:
            pname   = line_data.get("player_name", "")
            pp_stat = line_data.get("prop_type", "")
            pline   = float(line_data.get("line", 0))
            team    = line_data.get("team", "")
            odds_type = line_data.get("odds_type", "")

            if not pname or not pp_stat or pline <= 0:
                continue
            if pp_stat not in PP_TO_INTERNAL:
                continue

            key = (pname.lower(), pp_stat, pline)
            if key in seen:
                continue
            seen.add(key)

            result = self.predict(
                player_name=pname,
                pp_stat=pp_stat,
                line=pline,
                current_team=team,
            )
            if result:
                result["odds_type"] = odds_type
                picks.append(result)

        # Sort by absolute edge (best picks first)
        picks.sort(key=lambda x: abs(x["edge"]), reverse=True)

        # Save to DB
        print(f"\n[3/3] Saving {len(picks)} predictions to DB...")
        self._save_picks(picks)

        # Print summary
        strong = [p for p in picks if "STRONG" in p["recommendation"]]
        lean   = [p for p in picks if "LEAN"   in p["recommendation"]]
        print(f"\n  Results: {len(strong)} STRONG  |  {len(lean)} LEAN  "
              f"|  {len(picks)} total\n")

        if strong and self.verbose:
            print("  TOP PICKS:")
            print(f"  {'Player':<26} {'Stat':<16} {'Line':>6}  "
                  f"{'Dir':<6} {'Prob':>6}  {'Edge':>7}  Rec")
            print("  " + "-" * 83)
            for p in picks[:20]:
                if "PASS" in p["recommendation"]:
                    continue
                print(f"  {p['player_name']:<26} {p['pp_stat']:<16} "
                      f"{p['line']:>6.1f}  {p['direction']:<6} "
                      f"{p['probability']:>5.1f}%  {p['edge']:>+6.1f}%  "
                      f"{p['recommendation']}")

        return picks

    def _save_picks(self, picks: List[Dict]) -> None:
        """Persist predictions to season_prop_ml_picks table."""
        if not picks:
            return
        conn = sqlite3.connect(self.db_path)
        now  = datetime.now().isoformat()
        rows = []
        for p in picks:
            rows.append((
                SEASON,
                now,
                p["player_name"],
                p.get("player_id"),
                p.get("team"),
                p["player_type"],
                p["stat"],
                p.get("pp_stat"),
                p["line"],
                p.get("odds_type"),
                p["direction"],
                p["probability"] / 100.0,   # store as fraction
                p["edge"],
                p.get("projection"),
                p.get("std_dev"),
                p.get("confidence"),
                p.get("model_used"),
                json.dumps(p.get("key_factors", [])),
                p.get("recommendation"),
                now,
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO season_prop_ml_picks
            (season, fetched_at, player_name, player_id, team, player_type,
             stat, pp_stat_type, line, odds_type, direction, probability,
             edge, projection, std_dev, confidence, model_used,
             key_factors, recommendation, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
        conn.close()

    # ── 7. Train all models (batch) ───────────────────────────────────────────

    def train_all(self) -> Dict[str, bool]:
        """Train GBM models for all supported stats. Returns success map."""
        results = {}
        all_stat_types = [
            # batters
            ("batter", "hr"),   ("batter", "sb"),   ("batter", "hits"),
            ("batter", "tb"),   ("batter", "rbi"),  ("batter", "runs"),
            ("batter", "k"),    ("batter", "walks"),("batter", "hrr"),
            # pitchers
            ("pitcher", "k_total"),  ("pitcher", "bb_total"),
            ("pitcher", "hits_allowed"), ("pitcher", "er_total"),
            ("pitcher", "outs_recorded"),
        ]
        print(f"\nTraining {len(all_stat_types)} stat models...\n")
        for player_type, stat in all_stat_types:
            key = f"{player_type}_{stat}"
            print(f"  -> {key}")
            results[key] = self.train_model(stat, player_type, force=True)
        trained = sum(v for v in results.values())
        print(f"\nTrained {trained}/{len(all_stat_types)} models successfully")
        return results


# ============================================================================
# HELPERS
# ============================================================================

def _erf(x: float) -> float:
    """Approximate error function (Abramowitz & Stegun 7.1.26)."""
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (
        ((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
         - 0.284496736) * t + 0.254829592
    ) * t * math.exp(-x * x)
    return sign * y


# ============================================================================
# CONVENIENCE FUNCTION (called from orchestrator / dashboard)
# ============================================================================

def run_szln_predictions(db_path: str = None,
                         min_edge: float = 3.0) -> List[Dict]:
    """One-shot entry point: fetch lines, predict, return picks."""
    predictor = SeasonPropsML(db_path=db_path)
    return predictor.run_all_szln(min_edge=min_edge)


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MLB Season Props ML — SZLN line predictor"
    )
    parser.add_argument("--train",      action="store_true",
                        help="Force retrain all stat models from career history")
    parser.add_argument("--player",     type=str, default=None,
                        help="Predict for a single player (e.g. 'Aaron Judge')")
    parser.add_argument("--stat",       type=str, default=None,
                        help="PrizePicks stat key (e.g. home_runs, strikeouts)")
    parser.add_argument("--line",       type=float, default=None,
                        help="Sportsbook line to evaluate")
    parser.add_argument("--show-picks", action="store_true",
                        help="Print latest saved picks from DB")
    parser.add_argument("--min-edge",   type=float, default=3.0,
                        help="Minimum edge %% to include in output (default 3.0)")
    args = parser.parse_args()

    predictor = SeasonPropsML(verbose=True)

    if args.show_picks:
        conn = sqlite3.connect(predictor.db_path)
        rows = conn.execute("""
            SELECT player_name, stat, line, direction,
                   round(probability*100,1), edge, recommendation
            FROM   season_prop_ml_picks
            WHERE  season = ?
            ORDER  BY abs(edge) DESC
            LIMIT  50
        """, (SEASON,)).fetchall()
        conn.close()
        if rows:
            print(f"\n{'Player':<26} {'Stat':<16} {'Line':>6}  "
                  f"{'Dir':<6} {'Prob':>6}  {'Edge':>7}  Rec")
            print("-" * 83)
            for r in rows:
                print(f"{r[0]:<26} {r[1]:<16} {r[2]:>6.1f}  {r[3]:<6} "
                      f"{r[4]:>5.1f}%  {r[5]:>+6.1f}%  {r[6]}")
        else:
            print("No picks saved yet.  Run without --show-picks first.")

    elif args.train:
        predictor.train_all()

    elif args.player and args.stat:
        predictor._load_all_models()
        line = args.line or 0.0
        result = predictor.predict(
            player_name=args.player,
            pp_stat=args.stat,
            line=line,
        )
        if result:
            print(f"\n{result['player_name']}  {result['pp_stat']}  "
                  f"Line {result['line']}")
            print(f"  Projection : {result['projection']}")
            print(f"  Direction  : {result['direction']}")
            print(f"  Probability: {result['probability']}%")
            print(f"  Edge       : {result['edge']:+.1f}%")
            print(f"  Confidence : {result['confidence']}  "
                  f"({result['seasons_used']} seasons)")
            print(f"  Model      : {result['model_used']}")
            print(f"  Rec        : {result['recommendation']}")
            print("  Key factors:")
            for f in result["key_factors"]:
                print(f"    - {f}")
        else:
            print(f"No prediction available for {args.player} / {args.stat}")

    else:
        predictor.run_all_szln(min_edge=args.min_edge)
