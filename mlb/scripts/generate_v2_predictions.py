"""
MLB V2 Daily Prediction Generator
===================================

BMA prediction pipeline. Runs stat model + XGBoost via Thompson Sampling MAB
to produce calibrated P(OVER) with 95% CI for each player/prop.

Writes to:
  - predictions          (backward-compat: grading, smart picks)
  - ml_v2_predictions    (V2 BMA output: prob_over + CI + weights)

CI method:
  - BMA (stat + XGBoost): N=500 Monte Carlo samples of Beta weight vectors
  - Stat-only: Beta(p * N_eff, (1-p) * N_eff) where N_eff = alpha+beta from
    the stat MAB arm. Starts wide at cold start (~N_eff=10), narrows as graded
    data accumulates. No zero-width CIs — every row reflects real uncertainty.

Usage:
    python generate_v2_predictions.py 2026-04-25
    python generate_v2_predictions.py  # defaults to today
    python generate_v2_predictions.py 2026-04-25 --coverage  # print coverage report
"""

import sys
import json
import sqlite3
import shutil
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'features'))

_HLSS = Path(__file__).resolve().parents[2] / "hlss"
sys.path.insert(0, str(_HLSS))

from mlb_config import (
    DB_PATH, BACKUPS_DIR, CORE_PROPS, PITCHER_PROPS, BATTER_PROPS,
    get_player_type, get_db_connection, initialize_database,
    mlb_has_games, is_over_only_line, MODEL_TYPE, get_line_type,
)
from fetch_game_schedule import GameScheduleFetcher
from statistical_predictions import MLBStatisticalEngine
from pitcher_feature_extractor import PitcherFeatureExtractor
from batter_feature_extractor import BatterFeatureExtractor
from opponent_feature_extractor import OpponentFeatureExtractor
from game_context_extractor import GameContextExtractor

try:
    from ml_training.mab_weighting import ThompsonSamplingMAB, _COLD_START_PRIORS
    MAB_AVAILABLE = True
except ImportError:
    MAB_AVAILABLE = False
    _COLD_START_PRIORS = {'stat': (6, 4), 'xgb': (7, 3)}
    print("[V2] WARNING: ml_training.mab_weighting not found — using cold-start priors")

# V2 DATA BOUNDARY: This system starts accumulating from 2026-04-25 forward.
# ml_v2.db contains no V1 predictions or outcomes.
# player_game_logs copied from V1 for stat model feature extraction only.
# MAB state initialized from cold-start priors — no V1 grading history.

# Break-even values — keep in sync with smart_pick_selector.py + supabase_sync.py
_BREAK_EVEN = {
    'standard': 0.5238,
    'goblin':   0.7619,
    'demon':    0.4545,
}

# Models actively producing predictions. MAB only samples from these arms.
# Add 'rf' and 'lr' here once their models are trained and predict_to_db writes them.
ACTIVE_MODELS = ['stat', 'xgb']

_DUCKDB_PATH = Path(__file__).resolve().parents[2] / "mlb_feature_store" / "data" / "mlb.duckdb"
_DUCKDB_TO_STAT_PROP = {"walks": "pitcher_walks"}
_N_BOOTSTRAP = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    n = unicodedata.normalize("NFKD", str(name))
    return "".join(c for c in n if not unicodedata.combining(c)).lower().strip()


def _p_over(predicted_mean: float, line: float) -> Optional[float]:
    """P(actual > line) via Poisson CDF."""
    try:
        from scipy.stats import poisson
        if predicted_mean <= 0:
            return 0.0
        return float(1.0 - poisson.cdf(int(line), mu=predicted_mean))
    except ImportError:
        return None


def _load_xgb_lookup(target_date: str) -> Dict[Tuple[str, str], float]:
    """
    Load XGBoost DuckDB predictions for target_date into a (norm_name, prop) lookup.
    Returns {} if DuckDB unavailable or no rows for the date.
    """
    if not _DUCKDB_PATH.exists():
        print(f"[V2-XGB] DuckDB not found at {_DUCKDB_PATH}")
        return {}
    try:
        import duckdb
    except ImportError:
        print("[V2-XGB] duckdb not installed")
        return {}

    try:
        duck = duckdb.connect(str(_DUCKDB_PATH), read_only=True)
        preds_df = duck.execute(
            "SELECT player_name, prop, predicted_value FROM ml_predictions WHERE game_date = ?",
            [target_date],
        ).fetchdf()

        if preds_df.empty:
            print(f"[V2-XGB] No DuckDB predictions for {target_date} — all rows will be stat-only")
            duck.close()
            return {}

        try:
            aliases = duck.execute("SELECT fs_name, canonical_name FROM name_aliases").fetchdf()
            alias_map = dict(zip(aliases["fs_name"], aliases["canonical_name"]))
        except Exception:
            alias_map = {}

        duck.close()

        lookup: Dict[Tuple[str, str], float] = {}
        for _, row in preds_df.iterrows():
            fs_name = row["player_name"] or ""
            canonical = alias_map.get(fs_name, fs_name)
            stat_prop = _DUCKDB_TO_STAT_PROP.get(row["prop"], row["prop"])
            lookup[(_norm(canonical), stat_prop)] = float(row["predicted_value"])

        print(f"[V2-XGB] Loaded {len(lookup)} XGBoost predictions for {target_date}")
        return lookup

    except Exception as e:
        print(f"[V2-XGB] Failed to load DuckDB: {e}")
        return {}


def _bootstrap_ci(
    stat_prob: float,
    xgb_prob: Optional[float],
    alpha_stat: int,
    beta_stat: int,
    alpha_xgb: int,
    beta_xgb: int,
    n: int = _N_BOOTSTRAP,
) -> Tuple[float, float, float, float]:
    """
    Bootstrap CI for BMA prob_over.

    BMA mode (both models available):
        Sample N weight pairs from Beta(alpha_stat, beta_stat) and
        Beta(alpha_xgb, beta_xgb). Normalize each pair. CI = 2.5/97.5 percentiles
        of the N weighted combinations. Width reflects model-weighting uncertainty.

    Stat-only mode (xgb unavailable):
        Model the stat model's calibration uncertainty using its own Beta parameters.
        N_eff = alpha_stat + beta_stat (grows as graded data accumulates).
        Sample prob_over from Beta(p * N_eff, (1-p) * N_eff).
        Cold start (N_eff=10): wide CI — honest uncertainty for uncalibrated model.
        After 100+ graded rows: N_eff ~70+, CI narrows to reflect real accuracy.
        No zero-width CIs — every row is an honest uncertainty interval.

    Returns (bma_mean, ci_lower, ci_upper, prob_std).
    """
    if xgb_prob is not None:
        w_stat = np.random.beta(alpha_stat, beta_stat, size=n)
        w_xgb  = np.random.beta(alpha_xgb, beta_xgb, size=n)
        total  = w_stat + w_xgb
        w_stat_n = w_stat / total
        w_xgb_n  = w_xgb  / total
        samples  = w_stat_n * stat_prob + w_xgb_n * xgb_prob
    else:
        # Calibration uncertainty: N_eff reflects how much data backs this estimate
        n_eff   = alpha_stat + beta_stat
        a_shape = max(0.5, stat_prob * n_eff)
        b_shape = max(0.5, (1.0 - stat_prob) * n_eff)
        samples = np.random.beta(a_shape, b_shape, size=n)

    bma_mean = float(np.mean(samples))
    ci_lower = float(np.percentile(samples, 2.5))
    ci_upper = float(np.percentile(samples, 97.5))
    prob_std = float(np.std(samples))
    return round(bma_mean, 4), round(ci_lower, 4), round(ci_upper, 4), round(prob_std, 4)


# ---------------------------------------------------------------------------
# Main predictor
# ---------------------------------------------------------------------------

class MLBv2DailyPredictor:
    """
    Full MLB prediction pipeline writing to both predictions and ml_v2_predictions.
    Replaces generate_predictions_daily.py.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        initialize_database(self.db_path)

        self.schedule_fetcher = GameScheduleFetcher(self.db_path)
        self.stat_engine      = MLBStatisticalEngine()
        self.pitcher_feats    = PitcherFeatureExtractor(self.db_path)
        self.batter_feats     = BatterFeatureExtractor(self.db_path)
        self.opponent_feats   = OpponentFeatureExtractor(self.db_path)
        self.context_feats    = GameContextExtractor(self.db_path)

        self.mab = ThompsonSamplingMAB() if MAB_AVAILABLE else None

        # Populated at start of generate_predictions()
        self._xgb_lookup: Dict[Tuple[str, str], float] = {}

        # Coverage tracking: {player_name: 'bma' | 'stat_only'}
        self._coverage: Dict[str, str] = {}

    def generate_predictions(self, target_date: str, print_coverage: bool = False) -> Dict:
        print(f"\n{'='*60}")
        print(f"[MLB-V2] Generating predictions for {target_date}")
        print(f"{'='*60}")

        if not mlb_has_games(target_date):
            print(f"[MLB-V2] No games expected on {target_date}")
            return {'status': 'no_games', 'predictions': 0}

        self._xgb_lookup = _load_xgb_lookup(target_date)
        self._coverage.clear()
        _ensure_v2_table(self.db_path)

        batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        games = self.schedule_fetcher.fetch_and_save(target_date)
        if not games:
            print(f"[MLB-V2] No games found for {target_date}")
            return {'status': 'no_games', 'predictions': 0}

        print(f"[MLB-V2] Processing {len(games)} games...")

        predictions_saved = v2_saved = skipped_tbd = skipped_data = errors = 0
        conn = get_db_connection(self.db_path)

        try:
            for game in games:
                if game.status == 'postponed':
                    continue

                ctx_features = self.context_feats.extract(
                    game_id=str(game.game_id),
                    home_team=game.home_team,
                    away_team=game.away_team,
                    venue=game.venue,
                    day_night=game.day_night,
                )

                print(f"\n[MLB-V2] {game.away_team} @ {game.home_team}")

                for side, pitcher_name, pitcher_id, team, opponent in [
                    ('home', game.home_starter, game.home_starter_id, game.home_team, game.away_team),
                    ('away', game.away_starter, game.away_starter_id, game.away_team, game.home_team),
                ]:
                    if not pitcher_name or pitcher_name == 'TBD':
                        skipped_tbd += 1
                        continue
                    s, sk, e, v = self._generate_pitcher_predictions(
                        conn, pitcher_name, pitcher_id, team, opponent, side,
                        game, ctx_features, batch_id, target_date,
                    )
                    predictions_saved += s; skipped_data += sk; errors += e; v2_saved += v

                home_lineup = game.home_lineup or []
                away_lineup = game.away_lineup or []

                for side, lineup, team, opponent, starter_name, starter_id in [
                    ('home', home_lineup, game.home_team, game.away_team, game.away_starter, game.away_starter_id),
                    ('away', away_lineup, game.away_team, game.home_team, game.home_starter, game.home_starter_id),
                ]:
                    if not lineup:
                        lineup = self._get_proxy_lineup(conn, team, target_date, side,
                                                         str(game.game_id), game.venue, opponent)
                    for batter_info in lineup:
                        s, sk, e, v = self._generate_batter_predictions(
                            conn, batter_info, team, opponent, side,
                            starter_name, starter_id,
                            game, ctx_features, batch_id, target_date,
                        )
                        predictions_saved += s; skipped_data += sk; errors += e; v2_saved += v

            conn.commit()

        except Exception as e:
            print(f"[MLB-V2] Critical error: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

        n_bma       = sum(1 for v in self._coverage.values() if v == 'bma')
        n_stat_only = sum(1 for v in self._coverage.values() if v == 'stat_only')
        n_players   = len(self._coverage)
        xgb_pct     = f"{round(n_bma / n_players * 100)}%" if n_players else "0%"

        summary = {
            'status':          'success',
            'date':            target_date,
            'batch_id':        batch_id,
            'predictions':     predictions_saved,
            'v2_predictions':  v2_saved,
            'players_bma':     n_bma,
            'players_stat_only': n_stat_only,
            'xgb_coverage_pct': xgb_pct,
            'games':           len(games),
            'skipped_tbd':     skipped_tbd,
            'skipped_data':    skipped_data,
            'errors':          errors,
        }

        print(f"\n[MLB-V2] Summary:")
        print(f"  predictions table rows : {predictions_saved}")
        print(f"  ml_v2_predictions rows : {v2_saved}")
        print(f"  players w/ BMA (stat+xgb): {n_bma} / {n_players} ({xgb_pct})")
        print(f"  players stat-only          : {n_stat_only} / {n_players}")
        print(f"  errors: {errors}")

        if print_coverage:
            _print_coverage_report(self._coverage, target_date)

        return summary

    # -------------------------------------------------------------------------
    # Pitcher predictions
    # -------------------------------------------------------------------------

    def _generate_pitcher_predictions(
        self, conn, pitcher_name, pitcher_id, team, opponent, home_away,
        game, ctx_features, batch_id, target_date,
    ) -> Tuple[int, int, int, int]:
        saved = skipped = errors = v2_saved = 0

        print(f"  [P] {pitcher_name} ({team} vs {opponent})")

        pf = self.pitcher_feats.extract(
            player_name=pitcher_name, team=team, target_date=target_date,
            home_away=home_away, player_id=pitcher_id,
        )
        if pf.get('f_insufficient_data') == 1 and pf.get('f_starts_counted', 0) == 0:
            skipped += 5
            return saved, skipped, errors, v2_saved

        opp_features = self.opponent_feats.extract_team_offense(
            opponent_team=opponent, target_date=target_date, pitcher_hand='R',
        )

        for prop_type, lines in CORE_PROPS.items():
            if prop_type not in PITCHER_PROPS:
                continue
            for line in lines:
                try:
                    pred = self.stat_engine.predict(
                        player_name=pitcher_name, prop_type=prop_type, line=line,
                        pitcher_features=pf, context_features=ctx_features,
                        opponent_features=opp_features,
                    )
                    if not pred:
                        continue
                    if pred['prediction'] == 'UNDER' and is_over_only_line(prop_type, line):
                        continue

                    odds_type = get_line_type(prop_type, line)
                    self._save_prediction(conn, pred, target_date, str(game.game_id),
                                          team, opponent, home_away, 'pitcher', batch_id, odds_type)
                    saved += 1

                    v2_saved += self._save_v2_prediction(
                        conn, pred, target_date, team, prop_type, line, odds_type,
                    )
                except Exception as e:
                    print(f"     Error: {pitcher_name} {prop_type} {line}: {e}")
                    errors += 1

        return saved, skipped, errors, v2_saved

    # -------------------------------------------------------------------------
    # Batter predictions
    # -------------------------------------------------------------------------

    def _generate_batter_predictions(
        self, conn, batter_info, team, opponent, home_away,
        starter_name, starter_id, game, ctx_features, batch_id, target_date,
    ) -> Tuple[int, int, int, int]:
        saved = skipped = errors = v2_saved = 0

        player_name   = batter_info.get('name') or batter_info.get('player_name', '')
        player_id     = batter_info.get('id') or batter_info.get('player_id')
        batting_order = batter_info.get('batting_order', 5) or 5

        if not player_name:
            return saved, skipped, errors, v2_saved

        opp_features = self.opponent_feats.extract_pitcher_matchup(
            pitcher_name=starter_name or 'TBD', pitcher_id=starter_id,
            target_date=target_date, batter_hand='R',
            pitcher_is_home=(home_away == 'away'),
        )

        for prop_type, lines in CORE_PROPS.items():
            if prop_type not in BATTER_PROPS:
                continue
            for line in lines:
                try:
                    bf = self.batter_feats.extract(
                        player_name=player_name, team=team, prop_type=prop_type,
                        line=line, target_date=target_date,
                        opposing_pitcher_hand='R', home_away=home_away,
                        batting_order=batting_order,
                    )
                    if bf.get('f_insufficient_data') == 1 and bf.get('f_games_played', 0) == 0:
                        skipped += 1
                        continue

                    pred = self.stat_engine.predict(
                        player_name=player_name, prop_type=prop_type, line=line,
                        batter_features=bf, context_features=ctx_features,
                        opponent_features=opp_features,
                    )
                    if not pred:
                        continue
                    if pred['prediction'] == 'UNDER' and is_over_only_line(prop_type, line):
                        continue

                    odds_type = get_line_type(prop_type, line)
                    self._save_prediction(conn, pred, target_date, str(game.game_id),
                                          team, opponent, home_away, 'batter', batch_id, odds_type)
                    saved += 1

                    v2_saved += self._save_v2_prediction(
                        conn, pred, target_date, team, prop_type, line, odds_type,
                    )
                except Exception as e:
                    print(f"     Error: {player_name} {prop_type} {line}: {e}")
                    errors += 1

        return saved, skipped, errors, v2_saved

    # -------------------------------------------------------------------------
    # BMA computation + V2 write
    # -------------------------------------------------------------------------

    def _save_v2_prediction(
        self, conn, pred: Dict, game_date: str, team: str,
        prop_type: str, line: float, odds_type: str,
    ) -> int:
        """Compute BMA and write one row to ml_v2_predictions. Returns 1 on success."""
        player_name = pred['player_name']
        direction   = pred['prediction']   # 'OVER' or 'UNDER'
        stat_prob   = pred['probability']  # P(predicted direction)
        stat_prob_over = stat_prob if direction == 'OVER' else 1.0 - stat_prob

        # XGBoost P(OVER) from DuckDB
        xgb_raw = self._xgb_lookup.get((_norm(player_name), prop_type))
        xgb_prob_over = _p_over(xgb_raw, line) if xgb_raw is not None else None

        # MAB params — always load from actual MAB state (never hardcode cold start here)
        if self.mab is not None:
            mab_state = self.mab._load_state('mlb', prop_type, line)
            alpha_stat, beta_stat = self.mab._get_params(mab_state, 'stat')
            alpha_xgb,  beta_xgb  = self.mab._get_params(mab_state, 'xgb')
        else:
            alpha_stat, beta_stat = _COLD_START_PRIORS.get('stat', (6, 4))
            alpha_xgb,  beta_xgb  = _COLD_START_PRIORS.get('xgb',  (7, 3))

        bma_mean, ci_lower, ci_upper, prob_std = _bootstrap_ci(
            stat_prob_over, xgb_prob_over,
            alpha_stat, beta_stat, alpha_xgb, beta_xgb,
        )

        # MAB weights for recording — what fraction each model contributed
        if self.mab is not None and xgb_prob_over is not None:
            weights = self.mab.sample_weights('mlb', prop_type, ['stat', 'xgb'], line=line)
            w_stat  = weights.get('stat', 0.5)
            w_xgb   = weights.get('xgb',  0.5)
        elif xgb_prob_over is not None:
            # MAB unavailable but XGBoost present: equal weights
            w_stat, w_xgb = 0.5, 0.5
        else:
            w_stat, w_xgb = 1.0, 0.0

        model_prob    = bma_mean if direction == 'OVER' else 1.0 - bma_mean
        pp_break_even = _BREAK_EVEN.get(odds_type, _BREAK_EVEN['standard'])
        pp_edge       = round(model_prob - pp_break_even, 4)

        if prob_std < 0.05:
            confidence = 'HIGH'
        elif prob_std < 0.10:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'

        component_probs = json.dumps({
            'stat': round(stat_prob_over, 4),
            'xgb':  round(xgb_prob_over, 4) if xgb_prob_over is not None else None,
        })
        mab_weights = json.dumps({'stat': round(w_stat, 4), 'xgb': round(w_xgb, 4)})

        # Track coverage once per player
        mode = 'bma' if xgb_prob_over is not None else 'stat_only'
        self._coverage[player_name] = mode

        try:
            conn.execute('''
                INSERT OR REPLACE INTO ml_v2_predictions (
                    game_date, player_name, team, prop_type, line,
                    prediction, model_prob, prob_over, prob_std,
                    ci_lower, ci_upper, model_confidence,
                    component_probs, mab_weights,
                    market_implied, true_edge,
                    pp_edge, pp_break_even, odds_type,
                    drift_flagged, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                game_date, player_name, team, prop_type, line,
                direction,
                round(model_prob, 4), bma_mean, prob_std,
                ci_lower, ci_upper, confidence,
                component_probs, mab_weights,
                None, None,
                pp_edge, pp_break_even, odds_type,
                0, datetime.now().isoformat(),
            ))
            return 1
        except Exception as e:
            print(f"     [V2] Write failed {player_name} {prop_type} {line}: {e}")
            return 0

    # -------------------------------------------------------------------------
    # Standard predictions table write
    # -------------------------------------------------------------------------

    def _save_prediction(self, conn, pred, game_date, game_id, team, opponent,
                          home_away, player_type, batch_id, odds_type='standard') -> None:
        conn.execute('''
            INSERT INTO predictions (
                game_date, game_id, player_name, team, opponent,
                home_away, player_type, prop_type, line,
                prediction, probability, confidence_tier, expected_value,
                features_json, model_version, prediction_batch_id, created_at,
                odds_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            game_date, game_id,
            pred['player_name'], team, opponent, home_away, player_type,
            pred['prop_type'], pred['line'],
            pred['prediction'], pred['probability'],
            pred['confidence_tier'], pred.get('expected_value'),
            json.dumps(pred.get('features', {})),
            pred.get('model_version', ''),
            batch_id, datetime.now().isoformat(),
            odds_type,
        ))

    # -------------------------------------------------------------------------
    # Proxy lineup
    # -------------------------------------------------------------------------

    def _get_proxy_lineup(self, conn, team, target_date, home_away,
                           game_id, venue, opponent) -> List[Dict]:
        cursor = conn.execute('''
            SELECT player_name, AVG(COALESCE(batting_order, 5)) as avg_order, COUNT(*) as games
            FROM player_game_logs
            WHERE team = ? AND player_type = 'batter' AND game_date < ?
            GROUP BY player_name HAVING COUNT(*) >= 3
            ORDER BY avg_order ASC, games DESC LIMIT 9
        ''', (team, target_date))
        return [
            {'name': row['player_name'], 'id': None, 'batting_order': i, 'lineup_confirmed': False}
            for i, row in enumerate(cursor.fetchall(), start=1)
        ]


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def _print_coverage_report(coverage: Dict[str, str], target_date: str) -> None:
    bma_players       = sorted(p for p, v in coverage.items() if v == 'bma')
    stat_only_players = sorted(p for p, v in coverage.items() if v == 'stat_only')

    print(f"\n{'='*60}")
    print(f"[V2] XGBoost Coverage Report — {target_date}")
    print(f"{'='*60}")
    print(f"\nBMA (stat + XGBoost) — {len(bma_players)} players:")
    for p in bma_players:
        print(f"  + {p}")
    print(f"\nStat-only (not in Statcast DuckDB) — {len(stat_only_players)} players:")
    for p in stat_only_players:
        print(f"  - {p}")
    print(f"\nTotal: {len(bma_players)} BMA / {len(stat_only_players)} stat-only "
          f"({round(len(bma_players) / max(len(coverage), 1) * 100)}% XGBoost coverage)\n")


def coverage_report_from_db(db_path: str = None, date: str = None) -> None:
    """
    Print XGBoost coverage breakdown from an already-populated ml_v2_predictions table.
    Useful for auditing past runs.
    """
    db_path    = db_path or DB_PATH
    date       = date or datetime.now().strftime('%Y-%m-%d')

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute('''
            SELECT player_name, component_probs
            FROM ml_v2_predictions
            WHERE game_date = ?
        ''', (date,)).fetchall()

    if not rows:
        print(f"[V2] No ml_v2_predictions rows for {date}")
        return

    coverage = {}
    for player_name, comp_json in rows:
        try:
            comp = json.loads(comp_json or '{}')
            mode = 'bma' if comp.get('xgb') is not None else 'stat_only'
        except Exception:
            mode = 'stat_only'
        coverage[player_name] = mode

    _print_coverage_report(coverage, date)


# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------

def _ensure_v2_table(db_path: str) -> None:
    """Create ml_v2_predictions if it doesn't exist yet."""
    ddl = """
    CREATE TABLE IF NOT EXISTS ml_v2_predictions (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        game_date        DATE    NOT NULL,
        player_name      TEXT    NOT NULL,
        team             TEXT,
        prop_type        TEXT    NOT NULL,
        line             REAL    NOT NULL,
        prediction       TEXT,
        model_prob       REAL,
        prob_over        REAL,
        prob_std         REAL,
        ci_lower         REAL,
        ci_upper         REAL,
        model_confidence TEXT,
        component_probs  TEXT,
        mab_weights      TEXT,
        market_implied   REAL,
        true_edge        REAL,
        pp_edge          REAL,
        pp_break_even    REAL,
        odds_type        TEXT,
        drift_flagged    INTEGER DEFAULT 0,
        created_at       TEXT,
        UNIQUE(game_date, player_name, prop_type, line)
    )
    """
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute(ddl)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_v2_date ON ml_v2_predictions (game_date)")
        conn.commit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default=datetime.now().strftime('%Y-%m-%d'))
    parser.add_argument('--coverage', action='store_true',
                        help='Print per-player XGBoost coverage report after run')
    parser.add_argument('--coverage-only', metavar='DATE',
                        help='Print coverage report from existing DB rows, no new predictions')
    args = parser.parse_args()

    if args.coverage_only:
        coverage_report_from_db(date=args.coverage_only)
        return 0

    target_date = args.date
    print(f"[MLB-V2] Starting pipeline for {target_date}")

    db_path = DB_PATH
    if Path(db_path).exists():
        Path(BACKUPS_DIR).mkdir(parents=True, exist_ok=True)
        ts     = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = str(Path(BACKUPS_DIR) / f"mlb_predictions_{ts}.db")
        try:
            shutil.copy2(db_path, backup)
            print(f"[MLB-V2] DB backed up to {backup}")
        except Exception as e:
            print(f"[MLB-V2] Backup failed: {e}")

    predictor = MLBv2DailyPredictor()
    summary   = predictor.generate_predictions(target_date, print_coverage=args.coverage)

    print(f"\n[MLB-V2] Done: {summary}")
    return 0 if summary.get('status') == 'success' else 1


if __name__ == '__main__':
    sys.exit(main())
