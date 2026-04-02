"""
Centralized Pipeline Logger
============================
Provides consistent file + console logging for all prediction/grading scripts.

Usage:
    from pipeline_logger import get_logger
    logger = get_logger("nba_predictions", "nba")
    logger.info("Generated 45 predictions")
    logger.error("ESPN API failed", exc_info=True)
"""

import logging
import os
from datetime import datetime
from pathlib import Path

_LOG_ROOT = Path(__file__).parent.parent / "logs"

def get_logger(name: str, sport: str = "general") -> logging.Logger:
    """
    Get a logger that writes to both console and a daily log file.

    Args:
        name: Logger name (e.g., 'predictions', 'grading')
        sport: Sport subdirectory (e.g., 'nhl', 'nba', 'mlb')

    Returns:
        Configured logging.Logger instance
    """
    logger = logging.getLogger(f"sp.{sport}.{name}")

    # Don't add handlers if already configured
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler (INFO+)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console_fmt = logging.Formatter('[%(levelname)s] %(message)s')
    console.setFormatter(console_fmt)
    logger.addHandler(console)

    # File handler (DEBUG+)
    log_dir = _LOG_ROOT / sport
    log_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"{name}_{today}.log"

    file_handler = logging.FileHandler(str(log_file), encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    return logger


def cleanup_old_logs(days: int = 30):
    """Remove log files older than N days."""
    import glob
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=days)

    for log_file in _LOG_ROOT.rglob("*.log"):
        try:
            # Extract date from filename (name_YYYY-MM-DD.log)
            date_str = log_file.stem.split("_")[-1]
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                log_file.unlink()
        except (ValueError, IndexError):
            pass  # Skip files that don't match the naming pattern
