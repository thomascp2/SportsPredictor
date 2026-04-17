"""
PEGASUS Calibration Report Formatter
Reads existing calibration report JSONs and formats them for terminal display or returns as dict.
"""
import json
from pathlib import Path
from datetime import date

_here = Path(__file__).resolve().parent
_pegasus_root = _here.parent

from config import REPORTS_DIR, CALIBRATION_TABLES_DIR, SPORTS


def load_latest_report(sport: str) -> dict | None:
    """Load the most recently saved calibration report for a sport."""
    if not REPORTS_DIR.exists():
        return None
    pattern = f"calibration_{sport}_*.json"
    matches = sorted(REPORTS_DIR.glob(pattern))
    if not matches:
        return None
    return json.loads(matches[-1].read_text())


def load_calibration_table(sport: str) -> dict | None:
    """Load the calibration lookup table for a sport (used by edge_calculator)."""
    path = CALIBRATION_TABLES_DIR / f"{sport}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def print_summary():
    """Print a one-line summary of the latest calibration for each sport."""
    print("PEGASUS Calibration Status")
    print("-" * 50)
    for sport in SPORTS:
        report = load_latest_report(sport)
        if not report:
            print(f"  {sport.upper():>4}: No report found — run audit.py")
            continue
        if report.get("skip"):
            print(f"  {sport.upper():>4}: SKIP — {report['skip']}")
            continue
        a = report.get("check_a_baseline", {})
        status = "PASS" if report.get("pass") else "FAIL"
        edge = a.get("real_edge", 0) * 100
        n = report.get("n", 0)
        audit_date = report.get("audit_date", "?")
        print(f"  {sport.upper():>4}: {status}  real_edge={edge:+.1f}pp  n={n:,}  [{audit_date}]")


if __name__ == "__main__":
    print_summary()
