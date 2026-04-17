"""
PEGASUS/pipeline/pick_selector.py

Core pick builder — Step 6 of the PEGASUS build plan.

Reads statistical predictions from each sport's SQLite database (read-only),
blends with ML predictions where applicable, applies calibration correction,
attaches situational flags, and returns PEGASUSPick objects ranked by edge.

Design rules:
  - Read-only: never INSERT / UPDATE / DELETE on any DB
  - All three SQLite databases (NHL, NBA, MLB) accessed with URI read-only mode
  - Situational intel is advisory — it never modifies calibrated_probability,
    ai_edge, or tier
  - T5-FADE picks are built but filtered from default output
  - Graceful on any individual pick failure — log and skip, never abort the run

Sources:
  NHL → nhl/database/nhl_predictions_v2.db   (stat-only — ML FAIL from Step 4)
  NBA → nba/database/nba_predictions.db      (stat-only — LEARNING_MODE=True)
  MLB → mlb/database/mlb_predictions.db      (60/40 ML/stat for BLEND_PROPS)
         + mlb_feature_store/data/mlb.duckdb  (XGBoost regression outputs)

Calibration:
  PEGASUS/data/calibration_tables/{sport}.json — built in Step 1
  Bucket: bucket_low = round(min(int(prob * 10) / 10, 0.9), 1)
          bucket_mid = bucket_low + 0.05
          calibrated_prob = cal_table.get(str(bucket_mid), raw_prob)

Blend logic for MLB:
  stat_prob      = probability column from SQLite (P(direction), ≥ 0.5)
  ml_p_over      = compute_ml_p_over(predicted_value, line, prop)
  ml_p_direction = ml_p_over if direction==OVER else (1 - ml_p_over)
  blended        = 0.60 * ml_p_direction + 0.40 * stat_prob
  (Falls back to stat_prob if player missing from DuckDB or prop not in BLEND_PROPS)

Edge:
  break_even = 0.5238 (std) / 0.7619 (goblin) / 0.4545 (demon)
  ai_edge    = (calibrated_prob - break_even) * 100

Tier:
  T1-ELITE:  ai_edge ≥ +19%
  T2-STRONG: ai_edge ≥ +14%
  T3-GOOD:   ai_edge ≥  +9%
  T4-LEAN:   ai_edge ≥   0%
  T5-FADE:   ai_edge <   0%  (excluded from default output)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths & imports
# ---------------------------------------------------------------------------

_PEGASUS_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT    = _PEGASUS_ROOT.parent

# Make PEGASUS importable when run from repo root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PEGASUS.config import (
    NHL_DB, NBA_DB, MLB_DB,
    CALIBRATION_TABLES_DIR,
    BREAK_EVEN, TIER_THRESHOLDS,
)

# DraftKings odds — optional; non-fatal if module errors or API down
try:
    from PEGASUS.pipeline.draftkings_odds import get_dk_props, get_implied_prob as _dk_implied_prob
    _DK_AVAILABLE = True
except ImportError:
    _DK_AVAILABLE = False
    get_dk_props = lambda *a, **k: {}          # type: ignore
    _dk_implied_prob = lambda *a, **k: None    # type: ignore

from PEGASUS.pipeline.mlb_ml_reader import (
    get_today_mlb_ml_predictions,
    compute_ml_p_over,
    BLEND_PROPS,
    STAT_ONLY_PROPS,
    ML_WEIGHT,
    STAT_WEIGHT,
)

# Situational intel — optional import (may fail if requests not installed)
try:
    from PEGASUS.situational.intel import get_situation
    _SITUATIONAL_AVAILABLE = True
except ImportError:
    _SITUATIONAL_AVAILABLE = False

# MLB game context — optional import (park factors, wind, game total)
try:
    from PEGASUS.pipeline.mlb_game_context import get_game_context as _get_game_context
    _GAME_CONTEXT_AVAILABLE = True
except ImportError:
    _GAME_CONTEXT_AVAILABLE = False
    _get_game_context = lambda *a, **k: ("NEUTRAL", "")  # type: ignore

# ---------------------------------------------------------------------------
# PEGASUSPick dataclass
# ---------------------------------------------------------------------------

@dataclass
class PEGASUSPick:
    """
    A single enriched pick produced by the PEGASUS pipeline.

    Fields:
      raw_stat_probability  — probability stored in SQLite predictions table
      ml_probability        — ml_p_direction used in blend (None if stat-only)
      blended_probability   — after ML blend (= raw_stat_prob if no ML used)
      calibrated_probability — blended_prob → calibration table lookup
      ai_edge               — (calibrated_prob - break_even) * 100 (ppt)
      vs_naive_edge         — calibrated_prob - always_under_rate
      tier                  — T1-ELITE..T5-FADE
      situation_*           — advisory only, NEVER applied to probability/edge
    """
    player_name:            str
    team:                   str
    sport:                  str           # nhl / nba / mlb
    prop:                   str
    line:                   float
    direction:              str           # OVER / UNDER
    odds_type:              str           # standard / goblin / demon

    # Probabilities
    raw_stat_probability:   float
    ml_probability:         Optional[float]
    blended_probability:    float
    calibrated_probability: float

    # Edge
    break_even:             float
    ai_edge:                float         # in percentage points
    vs_naive_edge:          float

    # Tier
    tier:                   str

    # Situational (advisory only)
    situation_flag:         str
    situation_modifier:     float
    situation_notes:        str

    # Metadata
    game_date:              str
    model_version:          str
    source_prediction_id:   int

    # Sportsbook context (from The Odds API — None until paid plan active)
    implied_probability:    Optional[float] = None   # fair (vig-removed) prob from sportsbook

    # MLB game context (park factor, wind, game total — advisory only)
    game_context_flag:      str = "NEUTRAL"
    game_context_notes:     str = ""

    # Derived fields (computed in __post_init__)
    usage_boost: bool  = field(init=False)
    true_ev:     float = field(init=False)   # (calibrated_prob / break_even) - 1

    def __post_init__(self):
        self.usage_boost = (self.situation_flag == "USAGE_BOOST")
        # true_ev: expected return per unit staked relative to break-even
        # e.g. calibrated=0.85, break_even=0.5238 → true_ev = 0.622 (+62.2%)
        self.true_ev = round(
            (self.calibrated_probability / self.break_even) - 1.0, 4
        ) if self.break_even > 0 else 0.0


# ---------------------------------------------------------------------------
# Calibration table loading and lookup
# ---------------------------------------------------------------------------

_cal_cache: dict[str, dict] = {}


def _load_calibration(sport: str) -> dict:
    """
    Load calibration table for a sport.

    Returns:
        {
            "calibration_table": {"0.55": 0.5279, ...},
            "always_under_rate": 0.6923,
        }
    Returns {} if file missing.
    """
    if sport in _cal_cache:
        return _cal_cache[sport]

    path = CALIBRATION_TABLES_DIR / f"{sport}.json"
    if not path.exists():
        print(f"[pick_selector] WARNING: calibration table missing for {sport}: {path}")
        _cal_cache[sport] = {}
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _cal_cache[sport] = data
        return data
    except Exception as e:
        print(f"[pick_selector] ERROR loading calibration for {sport}: {e}")
        _cal_cache[sport] = {}
        return {}


def _calibrate(prob: float, cal_table: dict) -> float:
    """
    Look up a probability in the calibration table.

    Bucket logic (mirrors calibration/audit.py exactly):
      bucket_low = round(min(int(prob * 10) / 10, 0.9), 1)
      bucket_mid = round(bucket_low + 0.05, 2)

    Falls back to raw prob if bucket not in table.
    """
    bucket_low = round(min(int(prob * 10) / 10, 0.9), 1)
    bucket_mid = round(bucket_low + 0.05, 2)
    return cal_table.get(str(bucket_mid), prob)


# ---------------------------------------------------------------------------
# Tier assignment
# ---------------------------------------------------------------------------

def _tier_from_edge(edge: float) -> str:
    """Map edge (ppt) to tier string."""
    if edge >= TIER_THRESHOLDS["T1-ELITE"]:
        return "T1-ELITE"
    if edge >= TIER_THRESHOLDS["T2-STRONG"]:
        return "T2-STRONG"
    if edge >= TIER_THRESHOLDS["T3-GOOD"]:
        return "T3-GOOD"
    if edge >= TIER_THRESHOLDS["T4-LEAN"]:
        return "T4-LEAN"
    return "T5-FADE"


# ---------------------------------------------------------------------------
# Break-even lookup
# ---------------------------------------------------------------------------

def _break_even(odds_type: str) -> float:
    """Return break-even probability for an odds type."""
    return BREAK_EVEN.get((odds_type or "standard").lower(), BREAK_EVEN["standard"])


# ---------------------------------------------------------------------------
# SQLite readers (read-only)
# ---------------------------------------------------------------------------

_DB_SQL: dict[str, str] = {
    "nhl": """
        SELECT
            p.id            AS source_prediction_id,
            p.player_name,
            p.team,
            p.opponent,
            p.prop_type     AS prop,
            p.line,
            p.prediction    AS direction,
            p.probability,
            COALESCE(p.odds_type, 'standard') AS odds_type,
            p.model_version,
            p.game_date
        FROM predictions p
        WHERE p.game_date = ?
          AND p.probability IS NOT NULL
          AND p.player_name IS NOT NULL
        ORDER BY p.probability DESC
    """,
    "nba": """
        SELECT
            p.id            AS source_prediction_id,
            p.player_name,
            p.team,
            p.opponent,
            p.prop_type     AS prop,
            p.line,
            p.prediction    AS direction,
            p.probability,
            COALESCE(p.odds_type, 'standard') AS odds_type,
            p.model_version,
            p.game_date
        FROM predictions p
        WHERE p.game_date = ?
          AND p.probability IS NOT NULL
          AND p.player_name IS NOT NULL
        ORDER BY p.probability DESC
    """,
    "mlb": """
        SELECT
            p.id            AS source_prediction_id,
            p.player_name,
            p.team,
            p.opponent,
            p.prop_type     AS prop,
            p.line,
            p.prediction    AS direction,
            p.probability,
            COALESCE(p.odds_type, 'standard') AS odds_type,
            p.model_version,
            p.game_date
        FROM predictions p
        WHERE p.game_date = ?
          AND p.probability IS NOT NULL
          AND p.player_name IS NOT NULL
        ORDER BY p.probability DESC
    """,
}

_DB_PATHS = {"nhl": NHL_DB, "nba": NBA_DB, "mlb": MLB_DB}

# smart_picks_only variants — only PP-matched lines (is_smart_pick = 1)
# Reduces NHL 451→44, NBA 1045→165, MLB 2702→198 for a typical day
_DB_SQL_SMART: dict[str, str] = {
    sport: sql.replace(
        "          AND p.player_name IS NOT NULL",
        "          AND p.player_name IS NOT NULL\n          AND p.is_smart_pick = 1",
    )
    for sport, sql in _DB_SQL.items()
}


def _read_predictions(sport: str, game_date: str, smart_picks_only: bool = False) -> list[dict]:
    """
    Read today's predictions from the sport's SQLite DB.

    Args:
        smart_picks_only: If True, filter to is_smart_pick=1 (PP-matched lines).
                          Default False returns all predictions for the date.

    Returns list of dicts. Empty list if DB missing or no predictions.
    """
    db_path = _DB_PATHS.get(sport)
    if db_path is None or not db_path.exists():
        print(f"[pick_selector] {sport.upper()} DB not found: {db_path}")
        return []

    sql_map = _DB_SQL_SMART if smart_picks_only else _DB_SQL
    sql = sql_map.get(sport)
    if sql is None:
        return []

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(sql, [game_date]).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as e:
        print(f"[pick_selector] Error reading {sport.upper()} predictions: {e}")
        return []


# ---------------------------------------------------------------------------
# Situational intel cache
# ---------------------------------------------------------------------------

_situation_cache: dict[tuple, tuple] = {}


def _get_situation(team: str, sport: str, game_date: str, player_name: str) -> tuple:
    """
    Return (flag_str, modifier, notes) for a player/team.

    Caches at team level — one standings call per team per run.
    Returns ("NORMAL", 0.0, "") on any failure or if intel unavailable.
    """
    cache_key = (team, sport, game_date)
    if cache_key in _situation_cache:
        return _situation_cache[cache_key]

    if not _SITUATIONAL_AVAILABLE:
        result = ("NORMAL", 0.0, "")
        _situation_cache[cache_key] = result
        return result

    try:
        flag, modifier, notes = get_situation(
            team=team,
            sport=sport,
            game_date=game_date,
            injury_status="ACTIVE",
            player_name=player_name,
        )
        # Extract .value so we get "NORMAL" not "SituationFlag.NORMAL"
        flag_str = flag.value if hasattr(flag, "value") else str(flag)
        result = (flag_str, float(modifier), str(notes))
    except Exception as exc:
        print(f"[pick_selector] Situational intel failed ({sport} {team}): {exc}")
        result = ("NORMAL", 0.0, "")

    _situation_cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# Single pick builder
# ---------------------------------------------------------------------------

def _build_pick(
    row: dict,
    sport: str,
    cal_data: dict,
    always_under_rate: float,
    ml_data: dict,       # {(player_name, prop): {"predicted_value": float}}
    game_date: str,
    dk_data: dict,       # {(norm_name, prop): {over_odds, under_odds, line}} — may be {}
) -> Optional[PEGASUSPick]:
    """
    Build one PEGASUSPick from a SQLite prediction row.

    Returns None if the pick cannot be built (missing data, invalid probability).
    """
    try:
        player_name   = row["player_name"]
        team          = row.get("team") or "UNK"
        prop          = row["prop"]
        line          = float(row["line"])
        direction     = (row["direction"] or "OVER").upper().strip()
        raw_stat_prob = float(row["probability"])
        odds_type     = (row.get("odds_type") or "standard").lower().strip()
        model_version = row.get("model_version") or "unknown"
        pred_id       = int(row.get("source_prediction_id") or 0)

        # Sanity check
        if not (0.0 < raw_stat_prob < 1.0):
            return None
        if direction not in ("OVER", "UNDER"):
            return None

        # ── MLB: blend with XGBoost if prop is eligible ─────────────────────
        ml_probability   = None
        blended_prob     = raw_stat_prob

        if sport == "mlb" and prop not in STAT_ONLY_PROPS:
            ml_key = (player_name, prop)
            ml_entry = ml_data.get(ml_key)
            if ml_entry and prop in BLEND_PROPS:
                pv = ml_entry.get("predicted_value")
                if pv is not None:
                    ml_p_over = compute_ml_p_over(pv, line, prop)
                    if ml_p_over is not None:
                        # Convert ML P(OVER) to P(direction)
                        ml_p_direction = ml_p_over if direction == "OVER" else (1.0 - ml_p_over)
                        ml_probability = round(ml_p_direction, 6)
                        blended_prob   = ML_WEIGHT * ml_p_direction + STAT_WEIGHT * raw_stat_prob

        # Clamp blended probability to valid range
        blended_prob = max(0.001, min(0.999, blended_prob))

        # ── Calibration ───────────────────────────────────────────────────────
        cal_table = cal_data.get("calibration_table", {})
        calibrated_prob = _calibrate(blended_prob, cal_table) if cal_table else blended_prob
        calibrated_prob = max(0.001, min(0.999, calibrated_prob))

        # ── Edge & tier ───────────────────────────────────────────────────────
        be          = _break_even(odds_type)
        ai_edge     = round((calibrated_prob - be) * 100, 2)
        vs_naive    = round(calibrated_prob - always_under_rate, 4)
        tier        = _tier_from_edge(ai_edge)

        # ── Situational intel (advisory, per team) ────────────────────────────
        flag_str, modifier, notes = _get_situation(team, sport, game_date, player_name)

        # ── MLB game context (park factor, wind, game total) ──────────────────
        game_ctx_flag  = "NEUTRAL"
        game_ctx_notes = ""
        if sport == "mlb" and _GAME_CONTEXT_AVAILABLE:
            opponent = row.get("opponent") or ""
            game_ctx_flag, game_ctx_notes = _get_game_context(
                player_name=player_name,
                prop=prop,
                game_date=game_date,
                opponent=opponent,
            )

        # ── DraftKings implied probability (optional enrichment) ──────────────
        implied_prob: Optional[float] = None
        if dk_data:
            from PEGASUS.pipeline.odds_client import remove_vig
            import unicodedata as _ud

            def _norm_dk(n: str) -> str:
                nfkd = _ud.normalize("NFKD", n)
                s = "".join(c for c in nfkd if _ud.category(c) != "Mn")
                return " ".join(s.lower().split())

            dk_key = (_norm_dk(player_name), prop)
            dk_info = dk_data.get(dk_key)
            if dk_info:
                try:
                    fair_over, fair_under = remove_vig(dk_info["over_odds"], dk_info["under_odds"])
                    implied_prob = round(
                        fair_over if direction == "OVER" else fair_under, 4
                    )
                except Exception:
                    implied_prob = None

        return PEGASUSPick(
            player_name             = player_name,
            team                    = team,
            sport                   = sport,
            prop                    = prop,
            line                    = line,
            direction               = direction,
            odds_type               = odds_type,
            raw_stat_probability    = round(raw_stat_prob, 6),
            ml_probability          = round(ml_probability, 6) if ml_probability is not None else None,
            blended_probability     = round(blended_prob, 6),
            calibrated_probability  = round(calibrated_prob, 6),
            break_even              = be,
            ai_edge                 = ai_edge,
            vs_naive_edge           = vs_naive,
            tier                    = tier,
            situation_flag          = flag_str,
            situation_modifier      = modifier,
            situation_notes         = notes,
            game_date               = game_date,
            model_version           = model_version,
            source_prediction_id    = pred_id,
            implied_probability     = implied_prob,
            game_context_flag       = game_ctx_flag,
            game_context_notes      = game_ctx_notes,
        )

    except Exception as e:
        print(f"[pick_selector] Pick build error ({sport} {row.get('player_name')} "
              f"{row.get('prop')}): {e}")
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_picks(
    game_date: Optional[str] = None,
    sport: str = "all",
    include_fades: bool = False,
    min_tier: Optional[str] = None,
    smart_picks_only: bool = False,
) -> list[PEGASUSPick]:
    """
    Build PEGASUS picks for a date across one or all sports.

    Args:
        game_date:        YYYY-MM-DD (defaults to today)
        sport:            "nhl" | "nba" | "mlb" | "all"
        include_fades:    If True, include T5-FADE picks (edge < 0%)
        min_tier:         Optional minimum tier filter (e.g., "T3-GOOD")
        smart_picks_only: If True, only use PP-matched lines (is_smart_pick=1).
                          Recommended for daily production runs.

    Returns:
        List of PEGASUSPick objects, sorted by ai_edge descending.
    """
    if game_date is None:
        game_date = date.today().isoformat()

    sports = ["nhl", "nba", "mlb"] if sport == "all" else [sport.lower()]

    # Pre-load MLB ML predictions (one DuckDB read for the whole run)
    mlb_ml_data: dict = {}
    if "mlb" in sports:
        try:
            mlb_ml_data = get_today_mlb_ml_predictions(game_date)
        except Exception as e:
            print(f"[pick_selector] MLB ML data load failed: {e}")

    # Tier ordering for min_tier filter
    tier_order = {"T1-ELITE": 1, "T2-STRONG": 2, "T3-GOOD": 3, "T4-LEAN": 4, "T5-FADE": 5}
    min_tier_rank = tier_order.get(min_tier, 5) if min_tier else (5 if include_fades else 4)

    all_picks: list[PEGASUSPick] = []

    for sp in sports:
        # Load calibration data
        cal_data        = _load_calibration(sp)
        always_under    = float(cal_data.get("always_under_rate", 0.5))
        ml_data_for_sp  = mlb_ml_data if sp == "mlb" else {}

        # DraftKings implied odds — optional enrichment (non-fatal)
        dk_data_for_sp: dict = {}
        if _DK_AVAILABLE:
            try:
                dk_data_for_sp = get_dk_props(sp, game_date)
            except Exception as e:
                print(f"[pick_selector] DK odds load failed for {sp.upper()} (non-fatal): {e}")

        # Read predictions from SQLite
        rows = _read_predictions(sp, game_date, smart_picks_only=smart_picks_only)
        if not rows:
            print(f"[pick_selector] No {sp.upper()} predictions for {game_date}")
            continue

        n_built = 0
        n_skipped = 0
        for row in rows:
            pick = _build_pick(
                row=row,
                sport=sp,
                cal_data=cal_data,
                always_under_rate=always_under,
                ml_data=ml_data_for_sp,
                game_date=game_date,
                dk_data=dk_data_for_sp,
            )
            if pick is None:
                n_skipped += 1
                continue

            # Apply tier filter
            pick_rank = tier_order.get(pick.tier, 5)
            if pick_rank <= min_tier_rank:
                all_picks.append(pick)
                n_built += 1

        print(f"[pick_selector] {sp.upper()}: {n_built} picks built, {n_skipped} skipped "
              f"(raw rows: {len(rows)})")

    # Sort by edge descending
    all_picks.sort(key=lambda p: p.ai_edge, reverse=True)

    return all_picks


# ---------------------------------------------------------------------------
# CLI runner + pretty-print
# ---------------------------------------------------------------------------

def _format_pick(p: PEGASUSPick, rank: int) -> str:
    """Format a single pick for terminal output."""
    ml_tag   = f"ML={p.ml_probability:.3f}" if p.ml_probability is not None else "stat-only"
    sit_tag  = f" [{p.situation_flag}]" if p.situation_flag not in ("NORMAL", "") else ""
    fade_tag = " [FADE]" if p.tier == "T5-FADE" else ""

    return (
        f"  {rank:>3}. {p.tier:<12} "
        f"{p.player_name:<25} {p.sport.upper():>3} "
        f"{p.prop:<18} {p.direction:<5} {p.line:<5} "
        f"edge={p.ai_edge:+.1f}%  "
        f"cal={p.calibrated_probability:.3f}  "
        f"({ml_tag})"
        f"{sit_tag}{fade_tag}"
    )


def _print_summary(picks: list[PEGASUSPick], game_date: str) -> None:
    """Print a full summary report."""
    print(f"\n{'=' * 80}")
    print(f"PEGASUS PICKS — {game_date}")
    print(f"{'=' * 80}")

    if not picks:
        print("  No picks generated.")
        print("=" * 80 + "\n")
        return

    # Tier breakdown
    tier_counts: dict[str, int] = {}
    sport_counts: dict[str, int] = {}
    flag_counts:  dict[str, int] = {}
    ml_count = 0

    for p in picks:
        tier_counts[p.tier]   = tier_counts.get(p.tier, 0) + 1
        sport_counts[p.sport] = sport_counts.get(p.sport, 0) + 1
        flag_counts[p.situation_flag] = flag_counts.get(p.situation_flag, 0) + 1
        if p.ml_probability is not None:
            ml_count += 1

    print(f"\n  Total picks: {len(picks)}")
    print(f"  Tiers: " + "  ".join(f"{t}:{n}" for t, n in sorted(tier_counts.items())))
    print(f"  Sports: " + "  ".join(f"{s.upper()}:{n}" for s, n in sorted(sport_counts.items())))
    print(f"  ML-blended (MLB): {ml_count}")
    flags_display = {k: v for k, v in flag_counts.items() if k != "NORMAL" and v > 0}
    if flags_display:
        print(f"  Situational flags: " + "  ".join(f"{k}:{v}" for k, v in flags_display.items()))

    # Top picks by tier
    tier_order = ["T1-ELITE", "T2-STRONG", "T3-GOOD", "T4-LEAN", "T5-FADE"]
    rank = 0
    for tier in tier_order:
        tier_picks = [p for p in picks if p.tier == tier]
        if not tier_picks:
            continue
        print(f"\n  --- {tier} ({len(tier_picks)} picks) ---")
        for p in tier_picks[:20]:  # cap display at 20 per tier
            rank += 1
            print(_format_pick(p, rank))

    print(f"\n{'=' * 80}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PEGASUS Pick Selector")
    parser.add_argument("--date",  default=None,  help="YYYY-MM-DD (default: today)")
    parser.add_argument("--sport", default="all", help="nhl|nba|mlb|all")
    parser.add_argument("--fades", action="store_true", help="Include T5-FADE picks")
    parser.add_argument("--tier",  default=None,  help="Minimum tier filter (e.g. T3-GOOD)")
    parser.add_argument("--top",   type=int, default=None, help="Show only top N picks")
    parser.add_argument("--smart", action="store_true", help="Only PP-matched lines (is_smart_pick=1)")
    args = parser.parse_args()

    target_date = args.date or date.today().isoformat()
    print(f"\nBuilding PEGASUS picks for {target_date} ({args.sport.upper()})...")

    picks = get_picks(
        game_date        = target_date,
        sport            = args.sport,
        include_fades    = args.fades,
        min_tier         = args.tier,
        smart_picks_only = args.smart,
    )

    if args.top:
        picks = picks[: args.top]

    _print_summary(picks, target_date)
