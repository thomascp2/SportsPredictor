"""
shared/daily_audit.py — Daily system health audit

Reads all sport databases, computes prediction counts + ROI + win-rate,
detects anomalies, posts a Discord embed, and saves a JSON log.

Run manually:
    python shared/daily_audit.py
    python shared/daily_audit.py --date 2026-04-01

Wired into orchestrator at ~7 AM (after all sports have graded).
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent

DB_PATHS = {
    "NHL":  ROOT / "nhl"  / "database" / "nhl_predictions_v2.db",
    "NBA":  ROOT / "nba"  / "database" / "nba_predictions.db",
    "MLB":  ROOT / "mlb"  / "database" / "mlb_predictions.db",
    "GOLF": ROOT / "golf" / "database" / "golf_predictions.db",
}

ORCHESTRATOR_STATE = ROOT / "data" / "orchestrator_state.json"
AUDIT_LOG_DIR      = ROOT / "data" / "audit_logs"

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")

# ---------------------------------------------------------------------------
# Thresholds for anomaly detection
# ---------------------------------------------------------------------------
MIN_WIN_RATE     = 0.52   # flag if daily win-rate drops below this
MIN_PREDICTIONS  = 5      # flag if fewer than this many predictions were graded today
MAX_CONSEC_FAIL  = 2      # flag if consecutive_failures >= this


# ---------------------------------------------------------------------------
# Per-sport queries
# ---------------------------------------------------------------------------

def _query_sport(db_path: Path, target_date: str) -> dict:
    """Return stats dict for one sport on target_date. Returns empty dict on error."""
    if not db_path.exists():
        return {"error": f"DB not found: {db_path}"}

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Total predictions ever generated
        cur.execute("SELECT COUNT(*) FROM predictions")
        total_predictions = cur.fetchone()[0]

        # Today graded
        cur.execute(
            "SELECT COUNT(*) FROM prediction_outcomes WHERE game_date = ?",
            (target_date,),
        )
        graded_today = cur.fetchone()[0]

        # Today hit/miss (exclude VOID/PUSH)
        cur.execute(
            """SELECT
                   SUM(CASE WHEN outcome='HIT'  THEN 1 ELSE 0 END) as hits,
                   SUM(CASE WHEN outcome='MISS' THEN 1 ELSE 0 END) as misses
               FROM prediction_outcomes
               WHERE game_date = ? AND outcome IN ('HIT','MISS')""",
            (target_date,),
        )
        row = cur.fetchone()
        hits   = row["hits"]   or 0
        misses = row["misses"] or 0
        scored = hits + misses

        # Today profit (only if column exists)
        try:
            cur.execute(
                "SELECT SUM(profit) FROM prediction_outcomes WHERE game_date = ?",
                (target_date,),
            )
            daily_profit = cur.fetchone()[0] or 0.0
        except Exception:
            daily_profit = None

        # All-time profit
        try:
            cur.execute("SELECT SUM(profit) FROM prediction_outcomes WHERE profit IS NOT NULL")
            all_time_profit = cur.fetchone()[0] or 0.0
        except Exception:
            all_time_profit = None

        # All-time graded (for ROI denominator)
        cur.execute(
            "SELECT COUNT(*) FROM prediction_outcomes WHERE outcome IN ('HIT','MISS')"
        )
        all_time_graded = cur.fetchone()[0]

        conn.close()

        win_rate = hits / scored if scored > 0 else None

        return {
            "total_predictions":  total_predictions,
            "graded_today":       graded_today,
            "hits_today":         hits,
            "misses_today":       misses,
            "win_rate_today":     win_rate,
            "daily_profit":       daily_profit,
            "all_time_graded":    all_time_graded,
            "all_time_profit":    all_time_profit,
        }

    except Exception as exc:
        return {"error": str(exc)}


def _load_orchestrator_state() -> dict:
    try:
        with open(ORCHESTRATOR_STATE) as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def _detect_anomalies(sport: str, stats: dict, orch_state: dict) -> list:
    anomalies = []

    if "error" in stats:
        anomalies.append(f"DB error: {stats['error']}")
        return anomalies

    wr = stats.get("win_rate_today")
    if stats["graded_today"] >= MIN_PREDICTIONS:
        if wr is not None and wr < MIN_WIN_RATE:
            anomalies.append(
                f"Win rate {wr:.1%} below threshold ({MIN_WIN_RATE:.0%})"
            )
    elif stats["graded_today"] == 0:
        anomalies.append("0 predictions graded today")
    else:
        anomalies.append(
            f"Low graded count: {stats['graded_today']} (< {MIN_PREDICTIONS})"
        )

    cf = orch_state.get(sport.lower(), {}).get("consecutive_failures", 0)
    if cf >= MAX_CONSEC_FAIL:
        anomalies.append(f"consecutive_failures = {cf}")

    return anomalies


# ---------------------------------------------------------------------------
# Discord embed
# ---------------------------------------------------------------------------

def _sport_emoji(sport: str) -> str:
    return {"NHL": "[NHL]", "NBA": "[NBA]", "MLB": "[MLB]", "GOLF": "[GOLF]"}.get(sport, f"[{sport}]")


def _build_embed(target_date: str, report: dict) -> dict:
    """Build a Discord embed payload."""

    fields = []
    total_daily_profit = 0.0
    profit_available   = True

    for sport, stats in report["sports"].items():
        anomalies = stats.get("anomalies", [])
        alert_marker = " !" if anomalies else ""

        if "error" in stats:
            value = f"DB error: {stats['error']}"
        else:
            wr    = stats.get("win_rate_today")
            wr_s  = f"{wr:.1%}" if wr is not None else "n/a"
            hits  = stats.get("hits_today", 0)
            total = stats.get("graded_today", 0)
            dp    = stats.get("daily_profit")

            if dp is not None:
                total_daily_profit += dp
                profit_s = f"${dp:+.2f}"
            else:
                profit_s = "n/a"
                profit_available = False

            value = (
                f"Graded: {hits}/{total} | WR: {wr_s} | P&L: {profit_s}\n"
                f"All-time: {stats.get('all_time_graded', 0):,} graded | "
                f"Predictions: {stats.get('total_predictions', 0):,}"
            )

            if anomalies:
                value += "\n**Alerts:** " + " | ".join(anomalies)

        fields.append({
            "name": f"{_sport_emoji(sport)} {sport}{alert_marker}",
            "value": value,
            "inline": False,
        })

    has_alerts = any(stats.get("anomalies") for stats in report["sports"].values())
    color = 0xFF4444 if has_alerts else 0x00CC66

    profit_summary = f"${total_daily_profit:+.2f}" if profit_available else "see above"

    embed = {
        "title": f"Daily Audit - {target_date}",
        "description": (
            f"Total daily P&L: **{profit_summary}**  |  "
            f"{'ALERTS DETECTED' if has_alerts else 'All systems normal'}"
        ),
        "color": color,
        "fields": fields,
        "footer": {"text": f"Generated {datetime.now().strftime('%H:%M CST')}"},
    }
    return {"embeds": [embed]}


def _post_discord(payload: dict) -> bool:
    if not DISCORD_WEBHOOK:
        print("[AUDIT] No DISCORD_WEBHOOK_URL set — skipping Discord post")
        return False
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        return r.status_code in (200, 204)
    except Exception as exc:
        print(f"[AUDIT] Discord post failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_audit(target_date: str = None) -> dict:
    if target_date is None:
        # Default: grade yesterday's games (today's grading is for yesterday's games)
        target_date = (date.today() - timedelta(days=1)).isoformat()

    print(f"\n{'='*60}")
    print(f"[AUDIT] Daily audit for {target_date}")
    print(f"{'='*60}")

    orch_state = _load_orchestrator_state()

    report = {
        "date":      target_date,
        "generated": datetime.now().isoformat(),
        "sports":    {},
    }

    for sport, db_path in DB_PATHS.items():
        stats = _query_sport(db_path, target_date)
        stats["anomalies"] = _detect_anomalies(sport, stats, orch_state)
        report["sports"][sport] = stats

        wr_s = f"{stats['win_rate_today']:.1%}" if stats.get("win_rate_today") is not None else "n/a"
        dp_s = f"${stats['daily_profit']:+.2f}" if stats.get("daily_profit") is not None else "n/a"
        alerts = f"  ALERTS: {stats['anomalies']}" if stats.get("anomalies") else ""
        print(
            f"  {sport:4s}  graded={stats.get('graded_today',0):3d}  "
            f"wr={wr_s}  P&L={dp_s}{alerts}"
        )

    # Save JSON log
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = AUDIT_LOG_DIR / f"audit_{target_date}.json"
    with open(log_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[AUDIT] Saved log: {log_path}")

    # Post to Discord
    payload = _build_embed(target_date, report)
    sent = _post_discord(payload)
    if sent:
        print("[AUDIT] Discord embed posted")

    return report


if __name__ == "__main__":
    audit_date = sys.argv[1] if len(sys.argv) > 1 else None
    run_audit(audit_date)
