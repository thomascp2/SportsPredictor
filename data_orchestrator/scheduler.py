"""
data_orchestrator/scheduler.py

APScheduler-based orchestration for the Data Orchestrator Layer.

Schedule (all times UTC, maps to CST = UTC-5):
  ┌──────────────┬───────────────────────────────────────────────────────┐
  │ 08:00 UTC    │ Stats scrape: NBA/NHL/MLB box scores from yesterday   │
  │ (3 AM CST)   │                                                       │
  ├──────────────┼───────────────────────────────────────────────────────┤
  │ 14:00 UTC    │ Odds pull #1 — morning lines (9 AM CST)              │
  │ 20:00 UTC    │ Odds pull #2 — afternoon update (3 PM CST)           │
  │ 23:00 UTC    │ Odds pull #3 — evening lock (6 PM CST)               │
  └──────────────┴───────────────────────────────────────────────────────┘

Each job is independent and idempotent:
  - Stats scrape re-fetches if not already in DB for that date.
  - Odds pulls skip events already cached for today.
  - All errors are caught, logged, and the scheduler continues.

Usage:
    # Run as a standalone process:
    python -m data_orchestrator.scheduler

    # Or embed in another process:
    from data_orchestrator.scheduler import DataOrchestrator
    orch = DataOrchestrator()
    orch.start()           # starts background scheduler
    orch.run_stats_now()   # trigger immediately (testing)
    orch.run_odds_now()
"""

from __future__ import annotations

import logging
import signal
import sys
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import (
    ODDS_PULL_TIMES_UTC,
    STATS_HOUR_UTC,
    STATS_MINUTE_UTC,
)
from .fetchers import (
    fetch_mlb_boxscores,
    fetch_nba_boxscores,
    fetch_nhl_boxscores,
    _fetch_nhl_roster_all,
    seed_player_registry,
)
from .normalizer import NameNormalizer
from .odds_client import OddsClient
from .storage import DataStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DataOrchestrator
# ---------------------------------------------------------------------------

class DataOrchestrator:
    """
    Coordinates stats fetching, odds pulling, name normalization, and storage.

    The NHL roster is fetched once at startup (full name resolution).
    """

    def __init__(self):
        self.store      = DataStore()
        self.odds       = OddsClient(store=self.store)
        self.normalizer = NameNormalizer()
        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._nhl_id_map: dict[str, str] = {}    # player_id -> full_name

    # ------------------------------------------------------------------
    # Startup / shutdown
    # ------------------------------------------------------------------

    def start(self):
        """Start the background scheduler and register all jobs."""
        logger.info("[Orch] Initializing Data Orchestrator")

        # Pre-load NHL roster for full name resolution
        self._nhl_id_map = self.store.get_nhl_roster()
        if not self._nhl_id_map:
            logger.info("[Orch] NHL roster cache empty — fetching now")
            self._nhl_id_map = _fetch_nhl_roster_all(self.store)

        # Register jobs
        self._scheduler.add_job(
            self._job_stats,
            trigger=CronTrigger(hour=STATS_HOUR_UTC, minute=STATS_MINUTE_UTC),
            id="stats_scrape",
            name="Daily stats scrape (3 AM CST)",
            max_instances=1,
            misfire_grace_time=1800,    # allow up to 30 min late start
        )

        for hour, minute in ODDS_PULL_TIMES_UTC:
            job_id = f"odds_pull_{hour:02d}{minute:02d}"
            self._scheduler.add_job(
                self._job_odds,
                trigger=CronTrigger(hour=hour, minute=minute),
                id=job_id,
                name=f"Odds pull at {hour:02d}:{minute:02d} UTC",
                max_instances=1,
                misfire_grace_time=600,
            )

        self._scheduler.start()
        logger.info("[Orch] Scheduler started — jobs registered:")
        for job in self._scheduler.get_jobs():
            logger.info(f"  {job.name} | next: {job.next_run_time}")

    def stop(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("[Orch] Scheduler stopped")

    # ------------------------------------------------------------------
    # Manual triggers (for testing / one-shot runs)
    # ------------------------------------------------------------------

    def seed_registry(self) -> dict[str, int]:
        """
        Seed the player_registry with all active NBA/NHL/MLB players.
        Run once at startup or whenever rosters change significantly.
        After seeding, the normalizer can match any active player name.
        """
        logger.info("[Orch] Seeding player registry from league sources")
        counts = seed_player_registry(self.store)
        # Load into normalizer immediately
        for sport in ("NBA", "NHL", "MLB"):
            names = self.store.get_registry_names(sport)
            if names:
                self.normalizer.load_stats_names(sport, names)
                logger.info(f"[Orch] Normalizer loaded {len(names)} {sport} names from registry")
        return counts

    def _load_normalizer_from_registry(self):
        """Load canonical names into the normalizer from the player_registry."""
        for sport in ("NBA", "NHL", "MLB"):
            names = self.store.get_registry_names(sport)
            if names:
                self.normalizer.load_stats_names(sport, names)

    def _ensure_nhl_roster(self):
        """Load NHL roster cache if not yet populated (lazy init for one-shot runs)."""
        if not self._nhl_id_map:
            self._nhl_id_map = self.store.get_nhl_roster()
        if not self._nhl_id_map:
            logger.info("[Orch] NHL roster cache empty — fetching now")
            self._nhl_id_map = _fetch_nhl_roster_all(self.store)

    def run_stats_now(self, game_date: str = None):
        """Run stats scrape immediately for a given date (default: yesterday)."""
        self._ensure_nhl_roster()
        self._job_stats(game_date=game_date)

    def run_odds_now(self, fetch_date: str = None):
        """Run odds pull immediately."""
        self._job_odds(fetch_date=fetch_date)

    def run_all_now(self, game_date: str = None, fetch_date: str = None):
        """Run stats then odds immediately (for testing full pipeline)."""
        logger.info("[Orch] Running full pipeline now")
        self._job_stats(game_date=game_date)
        self._job_odds(fetch_date=fetch_date)

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def _job_stats(self, game_date: str = None):
        """Fetch yesterday's box scores for all sports and write to SQLite."""
        from datetime import date, timedelta
        game_date = game_date or (date.today() - timedelta(days=1)).isoformat()

        logger.info(f"[Stats] Starting box score fetch for {game_date}")
        total_written = 0

        # NBA
        try:
            df = fetch_nba_boxscores(game_date)
            n  = self.store.upsert_stats(df)
            logger.info(f"[Stats] NBA: {n} rows written")
            total_written += n
            if not df.empty:
                self.normalizer.load_stats_names("NBA", df["player_name"].tolist())
        except Exception as exc:
            logger.error(f"[Stats] NBA fetch failed: {exc}", exc_info=True)

        # NHL
        try:
            df = fetch_nhl_boxscores(
                game_date, store=self.store, _id_to_name=self._nhl_id_map
            )
            n  = self.store.upsert_stats(df)
            logger.info(f"[Stats] NHL: {n} rows written")
            total_written += n
            if not df.empty:
                self.normalizer.load_stats_names("NHL", df["player_name"].tolist())
        except Exception as exc:
            logger.error(f"[Stats] NHL fetch failed: {exc}", exc_info=True)

        # MLB
        try:
            df = fetch_mlb_boxscores(game_date)
            n  = self.store.upsert_stats(df)
            logger.info(f"[Stats] MLB: {n} rows written")
            total_written += n
            if not df.empty:
                self.normalizer.load_stats_names("MLB", df["player_name"].tolist())
        except Exception as exc:
            logger.error(f"[Stats] MLB fetch failed: {exc}", exc_info=True)

        logger.info(f"[Stats] Done. {total_written} total rows written for {game_date}")
        return total_written

    def _job_odds(self, fetch_date: str = None):
        """Pull player prop lines from The Odds API for all sports."""
        fetch_date = fetch_date or datetime.utcnow().date().isoformat()

        logger.info(f"[Odds] Starting odds pull for {fetch_date}")
        total_written = 0

        for sport in ("NBA", "NHL", "MLB"):
            try:
                df = self.odds.fetch_props(sport, fetch_date)
                if not df.empty:
                    logger.info(f"[Odds] {sport}: {len(df)} lines fetched")
                    total_written += len(df)
            except Exception as exc:
                logger.error(f"[Odds] {sport} fetch failed: {exc}", exc_info=True)

        budget_used = self.store.requests_used_today()
        logger.info(
            f"[Odds] Done. {total_written} prop lines stored. "
            f"API budget: {budget_used} requests used today."
        )
        return total_written

    # ------------------------------------------------------------------
    # ML-ready output
    # ------------------------------------------------------------------

    def get_ml_ready(self, game_date: str, sport: str = None) -> "pd.DataFrame":
        """
        Return a merged stats+odds DataFrame ready for XGBoost/Bayesian ingestion.

        Applies name normalization before the join so players without a prop line
        still appear (left join, NULL for odds columns).

        Args:
            game_date: 'YYYY-MM-DD' — date of games (stats side)
            sport:     Optional — 'NBA', 'NHL', or 'MLB'. None = all sports.

        Returns:
            DataFrame with both actual outcomes and opening prop lines.
        """
        return self.store.get_merged_picks(game_date, sport)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _setup_logging():
    from .config import LOG_DIR
    import os

    log_file = LOG_DIR / f"orchestrator_{datetime.utcnow().date().isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(log_file)),
        ],
    )


def main():
    """
    Start the Data Orchestrator in continuous mode.

    Usage:
        python -m data_orchestrator.scheduler             # continuous
        python -m data_orchestrator.scheduler --now       # run once and exit
        python -m data_orchestrator.scheduler --date 2026-04-21  # specific date
    """
    import argparse

    parser = argparse.ArgumentParser(description="Data Orchestrator — prop betting data pipeline")
    parser.add_argument("--now",  action="store_true", help="Run full pipeline immediately and exit")
    parser.add_argument("--stats-only",    action="store_true", help="Run only stats scrape")
    parser.add_argument("--odds-only",     action="store_true", help="Run only odds pull")
    parser.add_argument("--seed-registry", action="store_true", help="Seed player registry (run once on first setup)")
    parser.add_argument("--verify-names",  action="store_true", help="Report name match rate for today's odds")
    parser.add_argument("--date",  default=None, help="Game date (YYYY-MM-DD) for manual run")
    parser.add_argument("--sport", default=None, help="Single sport: NBA, NHL, MLB")
    args = parser.parse_args()

    _setup_logging()

    orch = DataOrchestrator()

    if args.seed_registry:
        counts = orch.seed_registry()
        print(f"\n=== Player Registry Seeded ===")
        for sport, n in counts.items():
            print(f"  {sport}: {n} players")

    elif args.verify_names:
        orch._load_normalizer_from_registry()
        import sqlite3, pandas as pd
        conn = sqlite3.connect(str(orch.store.db_path))
        today = datetime.utcnow().date().isoformat()
        odds  = pd.read_sql(f'SELECT sport, player_name FROM odds_lines WHERE fetch_date="{today}"', conn)
        conn.close()

        print(f"\n=== Name Verification Report — {today} ===")
        all_matched, all_total = 0, 0
        for sport in ["NBA", "NHL", "MLB"]:
            names = odds[odds.sport==sport]["player_name"].unique().tolist()
            if not names:
                print(f"\n{sport}: no odds data today")
                continue
            unmatched = []
            for name in names:
                result = orch.normalizer.standardize(name, sport)
                if not result:
                    unmatched.append(name)
            matched = len(names) - len(unmatched)
            pct = round(matched / len(names) * 100, 1)
            all_matched += matched
            all_total   += len(names)
            print(f"\n{sport}: {matched}/{len(names)} matched ({pct}%)")
            if unmatched:
                print(f"  Unmatched names (need exception or roster update):")
                for n in sorted(unmatched):
                    print(f"    MISS  {n}")

        if all_total:
            total_pct = round(all_matched / all_total * 100, 1)
            print(f"\nOverall: {all_matched}/{all_total} matched ({total_pct}%)")

    elif args.now or args.stats_only or args.odds_only or args.date:
        # One-shot mode — load normalizer from registry first
        orch._load_normalizer_from_registry()

        if not args.odds_only:
            orch.run_stats_now(game_date=args.date)
        if not args.stats_only:
            orch.run_odds_now(fetch_date=args.date)

        if args.date:
            df = orch.get_ml_ready(args.date, args.sport)
            print(f"\n=== ML-ready output for {args.date} ===")
            print(df.to_string(index=False, max_rows=30))
            print(f"\n{len(df)} rows total")
    else:
        # Continuous mode — runs until Ctrl-C
        orch.start()
        logger.info("[Orch] Running continuously. Press Ctrl-C to stop.")

        def _shutdown(sig, frame):
            logger.info("[Orch] Shutting down...")
            orch.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        # Keep main thread alive
        import time
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
