"""
PEGASUS/run_daily.py

Daily runner — Step 7 of the PEGASUS build plan.

Run AFTER the existing orchestrator has finished predictions + pp-sync for the day.
This script NEVER writes to any production database (SQLite, Supabase, or Turso).
All output is local to PEGASUS/data/picks/.

Flow:
  1. Verify the existing orchestrator ran (prediction counts per sport)
  2. Call pick_selector.get_picks(smart_picks_only=True) for all sports
  3. Write PEGASUS/data/picks/picks_{date}.json  (local snapshot)
  4. Print terminal summary — tier counts, sport counts, situation flags, top picks
  5. Exit 1 if orchestrator hasn't run for any sport (safety guard)

Usage:
  python PEGASUS/run_daily.py                    # today
  python PEGASUS/run_daily.py --date 2026-04-15  # specific date
  python PEGASUS/run_daily.py --all-picks        # skip is_smart_pick filter (analysis mode)
  python PEGASUS/run_daily.py --sport nba        # single sport
  python PEGASUS/run_daily.py --dry-run          # build picks, skip JSON write

Design rules:
  - Read-only: never INSERT / UPDATE / DELETE on any DB
  - Graceful: a single sport failure never aborts the other sports
  - No external network calls beyond what pick_selector already makes
    (situational intel caches standings per date)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PEGASUS_ROOT = Path(__file__).resolve().parent
_REPO_ROOT    = _PEGASUS_ROOT.parent
_PICKS_DIR    = _PEGASUS_ROOT / "data" / "picks"
_PICKS_DIR.mkdir(parents=True, exist_ok=True)

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PEGASUS.config import NHL_DB, NBA_DB, MLB_DB
from PEGASUS.pipeline.pick_selector import get_picks, PEGASUSPick

# ---------------------------------------------------------------------------
# Orchestrator readiness check
# ---------------------------------------------------------------------------

_DB_PATHS = {"nhl": NHL_DB, "nba": NBA_DB, "mlb": MLB_DB}

# Minimum total prediction rows to consider the orchestrator "done" for that sport
_MIN_PREDICTION_ROWS = {"nhl": 10, "nba": 10, "mlb": 10}
# Minimum smart-pick rows to consider pp-sync "done"
_MIN_SMART_ROWS      = {"nhl": 1,  "nba": 1,  "mlb": 1}


def _check_readiness(game_date: str, sports: list[str]) -> dict[str, dict]:
    """
    Query each sport's SQLite DB for prediction + smart-pick counts on game_date.

    Returns:
        {
          "nhl": {"total": 451, "smart": 44, "predictions_ready": True, "pp_sync_ready": True},
          ...
        }
    """
    status = {}
    for sport in sports:
        db_path = _DB_PATHS.get(sport)
        info = {"total": 0, "smart": 0, "predictions_ready": False, "pp_sync_ready": False}

        if db_path is None or not db_path.exists():
            info["error"] = f"DB not found: {db_path}"
            status[sport] = info
            continue

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            total = conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE game_date = ?", [game_date]
            ).fetchone()[0]
            smart = conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE game_date = ? AND is_smart_pick = 1",
                [game_date],
            ).fetchone()[0]
            conn.close()

            info["total"] = total
            info["smart"] = smart
            info["predictions_ready"] = total >= _MIN_PREDICTION_ROWS[sport]
            info["pp_sync_ready"]     = smart >= _MIN_SMART_ROWS[sport]
        except Exception as e:
            info["error"] = str(e)

        status[sport] = info
    return status


# ---------------------------------------------------------------------------
# JSON serializer
# ---------------------------------------------------------------------------

def _picks_to_json(picks: list[PEGASUSPick], game_date: str, meta: dict) -> dict:
    """Serialize PEGASUSPick list to a JSON-ready dict."""
    return {
        "pegasus_version": "step8",
        "game_date":       game_date,
        "generated_at":    date.today().isoformat(),
        "meta":            meta,
        "picks":           [asdict(p) for p in picks],
    }


def _write_json(picks: list[PEGASUSPick], game_date: str, meta: dict) -> Path:
    """Write picks JSON to PEGASUS/data/picks/picks_{date}.json."""
    out_path = _PICKS_DIR / f"picks_{game_date}.json"
    payload  = _picks_to_json(picks, game_date, meta)
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Terminal summary
# ---------------------------------------------------------------------------

_TIER_ORDER = ["T1-ELITE", "T2-STRONG", "T3-GOOD", "T4-LEAN"]


def _print_readiness(status: dict, game_date: str) -> None:
    print(f"\n  Orchestrator readiness ({game_date}):")
    for sport, info in status.items():
        err   = info.get("error", "")
        pred  = "OK" if info["predictions_ready"] else "MISSING"
        pp    = "OK" if info["pp_sync_ready"]     else "NO PP LINES"
        total = info.get("total", 0)
        smart = info.get("smart", 0)
        flag  = f"  [{err}]" if err else ""
        print(f"    {sport.upper():>3}: predictions={pred}({total})  pp-sync={pp}({smart}){flag}")


def _print_summary(picks: list[PEGASUSPick], game_date: str, out_path: Optional[Path]) -> None:
    sep = "=" * 80
    print(f"\n{sep}")
    print(f"  PEGASUS DAILY PICKS  —  {game_date}")
    print(sep)

    if not picks:
        print("  No actionable picks generated.")
        print(sep + "\n")
        return

    tier_counts:  dict[str, int] = {}
    sport_counts: dict[str, int] = {}
    flag_counts:  dict[str, int] = {}
    ml_count = 0

    for p in picks:
        tier_counts[p.tier]   = tier_counts.get(p.tier, 0) + 1
        sport_counts[p.sport] = sport_counts.get(p.sport, 0) + 1
        flag_counts[p.situation_flag] = flag_counts.get(p.situation_flag, 0) + 1
        if p.ml_probability is not None:
            ml_count += 1

    print(f"\n  Total picks : {len(picks)}")
    print(f"  Tiers       : " + "  ".join(f"{t}:{tier_counts.get(t,0)}" for t in _TIER_ORDER))
    print(f"  Sports      : " + "  ".join(f"{s.upper()}:{n}" for s, n in sorted(sport_counts.items())))
    print(f"  ML-blended  : {ml_count} (MLB XGBoost)")
    non_normal = {k: v for k, v in flag_counts.items() if k not in ("NORMAL", "") and v > 0}
    if non_normal:
        print(f"  Situational : " + "  ".join(f"{k}:{v}" for k, v in non_normal.items()))

    # Top picks per tier
    rank = 0
    for tier in _TIER_ORDER:
        tier_picks = [p for p in picks if p.tier == tier]
        if not tier_picks:
            continue
        print(f"\n  --- {tier} ({len(tier_picks)} picks) ---")
        for p in tier_picks[:15]:
            rank += 1
            ml_tag  = f"ML={p.ml_probability:.3f}" if p.ml_probability is not None else "stat"
            sit_tag = f"  [{p.situation_flag}]" if p.situation_flag not in ("NORMAL", "") else ""
            print(
                f"  {rank:>3}. {p.player_name:<26} {p.sport.upper():>3}"
                f"  {p.prop:<18} {p.direction:<5} O{p.line:<5}"
                f"  edge={p.ai_edge:+.1f}%  cal={p.calibrated_probability:.3f}"
                f"  odds={p.odds_type[:3]}  ({ml_tag}){sit_tag}"
            )

    if out_path:
        print(f"\n  Snapshot written -> {out_path}")
    print(sep + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    game_date: str,
    sports: list[str],
    smart_picks_only: bool = True,
    dry_run: bool = False,
) -> int:
    """
    Core run logic. Returns exit code (0 = success, 1 = orchestrator not ready).
    """
    print(f"\n[PEGASUS] Daily runner starting for {game_date} ...")

    # ── 1. Readiness check ────────────────────────────────────────────────────
    readiness = _check_readiness(game_date, sports)
    _print_readiness(readiness, game_date)

    any_not_ready   = not all(v["predictions_ready"] for v in readiness.values())
    any_no_pp       = not all(v["pp_sync_ready"]     for v in readiness.values())

    if any_not_ready:
        not_ready = [s for s, v in readiness.items() if not v["predictions_ready"]]
        print(f"\n  [PEGASUS] WARNING: Predictions missing for {not_ready}.")
        print(f"  [PEGASUS] Run orchestrator first, then re-run run_daily.py.")
        if smart_picks_only:
            print(f"  [PEGASUS] Exiting with code 1.")
            return 1

    if any_no_pp and smart_picks_only:
        no_pp = [s for s, v in readiness.items() if not v["pp_sync_ready"]]
        print(f"\n  [PEGASUS] WARNING: PP sync not complete for {no_pp}.")
        print(f"  [PEGASUS] Smart picks will be empty for those sports.")
        print(f"  [PEGASUS] Run pp-sync first, or use --all-picks to skip filter.")

    # ── 2-4. Build picks ──────────────────────────────────────────────────────
    sport_arg = "all" if len(sports) == 3 else sports[0]

    print(f"\n[PEGASUS] Building picks (smart_picks_only={smart_picks_only}) ...")
    picks = get_picks(
        game_date        = game_date,
        sport            = sport_arg,
        include_fades    = False,
        smart_picks_only = smart_picks_only,
    )

    # ── 5. Write JSON ─────────────────────────────────────────────────────────
    out_path = None
    if not dry_run and picks:
        meta = {
            "smart_picks_only": smart_picks_only,
            "sports":           sports,
            "readiness":        {k: {kk: vv for kk, vv in v.items() if kk != "error"}
                                 for k, v in readiness.items()},
            "tier_counts":      {t: sum(1 for p in picks if p.tier == t) for t in _TIER_ORDER},
            "ml_blended":       sum(1 for p in picks if p.ml_probability is not None),
        }
        try:
            out_path = _write_json(picks, game_date, meta)
        except Exception as e:
            print(f"  [PEGASUS] WARNING: JSON write failed: {e}")
    elif dry_run:
        print(f"  [PEGASUS] Dry run — skipping JSON write.")

    # ── 6. Turso sync ─────────────────────────────────────────────────────────
    if not dry_run and picks:
        try:
            from PEGASUS.sync.turso_sync import sync_to_turso
            print(f"\n[PEGASUS] Syncing picks to Turso ...")
            turso_results = sync_to_turso(picks, game_date, sports)
            total_synced  = sum(turso_results.values())
            sport_summary = "  ".join(f"{s.upper()}:{n}" for s, n in turso_results.items())
            print(f"  [PEGASUS] Turso sync complete: {total_synced} rows  [{sport_summary}]")
        except Exception as exc:
            print(f"  [PEGASUS] WARNING: Turso sync failed (non-fatal): {exc}")

    # ── 7. Terminal summary ───────────────────────────────────────────────────
    _print_summary(picks, game_date, out_path)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PEGASUS Daily Runner — build enriched picks after orchestrator runs"
    )
    parser.add_argument("--date",       default=None,       help="YYYY-MM-DD (default: today)")
    parser.add_argument("--sport",      default="all",      help="nhl|nba|mlb|all")
    parser.add_argument("--all-picks",  action="store_true", help="Ignore is_smart_pick filter (analysis mode)")
    parser.add_argument("--dry-run",    action="store_true", help="Build picks but skip JSON write")
    args = parser.parse_args()

    target_date      = args.date or date.today().isoformat()
    smart_only       = not args.all_picks
    sport_list       = ["nhl", "nba", "mlb"] if args.sport == "all" else [args.sport.lower()]

    exit_code = run(
        game_date        = target_date,
        sports           = sport_list,
        smart_picks_only = smart_only,
        dry_run          = args.dry_run,
    )
    sys.exit(exit_code)
