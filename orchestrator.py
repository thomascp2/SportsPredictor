#!/usr/bin/env python3
"""
Sports Prediction Project Orchestrator (NHL, NBA & MLB)
========================================================

Master controller for managing NHL, NBA, and MLB prediction systems.
Runs continuously (or via scheduler) and manages all operations.

MISSION: Build prediction juggernauts for both NHL and NBA through systematic
         data collection and continuous improvement, ultimately training
         world-class ML models for each sport.

Key Responsibilities:
- Execute daily prediction pipeline (fetch -> generate -> grade -> verify)
- Monitor data quality and feature health (ML readiness focus)
- Detect and diagnose issues automatically
- Track progress toward ML training goals (10,000+ predictions per sport)
- Optimize system performance based on results
- Send status updates and alerts

Usage:
    python sports_orchestrator.py --sport nhl --mode test
    python sports_orchestrator.py --sport nba --mode test
    python sports_orchestrator.py --sport nhl --mode once --operation prediction
    python sports_orchestrator.py --sport nba --mode once --operation grading
    python sports_orchestrator.py --sport nhl --mode continuous
    python sports_orchestrator.py --sport all --mode test  # Test both sports
"""

import asyncio
import os
import sys
import time
import json
import sqlite3
import subprocess
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# ── Encoding guard ───────────────────────────────────────────────────��────────
# Windows defaults to cp1252 which can't encode accented player names (e.g.
# Porzingis, Jokic, Doncic).  Force UTF-8 on stdout/stderr for this process
# AND set PYTHONIOENCODING so every subprocess we spawn inherits it.
os.environ.setdefault('PYTHONIOENCODING', 'utf-8:replace')
os.environ.setdefault('PYTHONUTF8', '1')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
# ─────────────────────────────────────────────────────────────────────────────

# Optional: schedule library for continuous mode
try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False
    print("NOTE: 'schedule' not installed. Continuous mode unavailable. Run: pip install schedule")

# Claude API removed - was expensive and not providing value
CLAUDE_AVAILABLE = False

# Optional: requests for API health checks and Discord notifications
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("NOTE: 'requests' not installed. API health checks and Discord unavailable. Run: pip install requests")

# Discord webhook from environment
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

# Optional: PrizePicks integration
try:
    sys.path.insert(0, str(Path(__file__).parent / "shared"))
    from prizepicks_client import PrizePicksIngestion, PrizePicksDatabase
    PRIZEPICKS_AVAILABLE = True
except ImportError:
    PRIZEPICKS_AVAILABLE = False
    print("NOTE: prizepicks_client not found. PrizePicks integration unavailable.")

# Optional: NBA schedule check (game-day awareness)
try:
    sys.path.insert(0, str(Path(__file__).parent / "nba" / "scripts"))
    from nba_config import nba_has_games
    NBA_SCHEDULE_AVAILABLE = True
except ImportError:
    NBA_SCHEDULE_AVAILABLE = False

# Optional: MLB schedule check (game-day awareness)
try:
    sys.path.insert(0, str(Path(__file__).parent / "mlb" / "scripts"))
    from mlb_config import mlb_has_games
    MLB_SCHEDULE_AVAILABLE = True
except ImportError:
    MLB_SCHEDULE_AVAILABLE = False

# Optional: ML Training integration
try:
    sys.path.insert(0, str(Path(__file__).parent / "ml_training"))
    from production_predictor import ProductionPredictor
    from model_manager import ModelRegistry
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("NOTE: ML training modules not found. ML predictions unavailable.")

# Optional: API Health Monitor & Self-Healing
try:
    sys.path.insert(0, str(Path(__file__).parent / "shared"))
    from api_health_monitor import APIHealthMonitor
    API_MONITOR_AVAILABLE = True
except ImportError:
    API_MONITOR_AVAILABLE = False
    print("NOTE: API health monitor not found. Self-healing unavailable.")

# Optional: Supabase Sync (FreePicks cloud sync)
try:
    from sync.supabase_sync import SupabaseSync
    SUPABASE_SYNC_AVAILABLE = True
except ImportError:
    SUPABASE_SYNC_AVAILABLE = False
    print("NOTE: Supabase sync not available. Cloud sync disabled.")

# Optional: Turso Sync (redundant cloud sync)
try:
    from sync.turso_sync import sync_predictions as _turso_sync_predictions
    from sync.turso_sync import sync_smart_picks as _turso_sync_smart_picks
    from sync.turso_sync import sync_grading as _turso_sync_grading
    TURSO_SYNC_AVAILABLE = True
except ImportError:
    TURSO_SYNC_AVAILABLE = False

# Optional: Pre-game intel (Grok injury/availability sweep)
try:
    sys.path.insert(0, str(Path(__file__).parent / "shared"))
    from pregame_intel import PreGameIntel
    PREGAME_INTEL_AVAILABLE = True
except ImportError:
    PREGAME_INTEL_AVAILABLE = False


# ============================================================================
# SPORT-SPECIFIC CONFIGURATION
# ============================================================================

class SportConfig:
    """Configuration for a specific sport"""

    def __init__(self, sport: str):
        self.sport = sport.upper()
        self.root = Path(__file__).parent

        if self.sport == "NHL":
            self._init_nhl()
        elif self.sport == "NBA":
            self._init_nba()
        elif self.sport == "MLB":
            self._init_mlb()
        elif self.sport == "GOLF":
            self._init_golf()
        else:
            raise ValueError(f"Unknown sport: {sport}. Use 'nhl', 'nba', 'mlb', or 'golf'")

    def _init_nhl(self):
        """Initialize NHL-specific configuration"""
        self.project_root = self.root / "nhl"
        self.db_path = self.project_root / "database" / "nhl_predictions_v2.db"

        # Scripts
        self.prediction_script = "scripts/generate_predictions_daily_V6.py"  # V6: PP line driven
        self.grading_script = "scripts/v2_auto_grade_yesterday_v3_RELIABLE.py"
        self.schedule_script = "scripts/fetch_game_schedule_FINAL.py"

        # Timing (CST)
        self.grading_time = "03:00"      # 3 AM - grade yesterday's games (west coast games finish ~1 AM CST)
        self.retrain_time = "03:30"      # 3:30 AM Sunday - weekly ML retrain (after grading, ensures fresh data)
        self.prizepicks_time = "03:30"   # 3:30 AM - fetch PrizePicks lines (early pass before predictions)
        self.prediction_time = "04:00"   # 4 AM - generate today's predictions
        self.pp_sync_time = "13:00"      # 1 PM - afternoon PP re-sync (full slate posted by now, refresh smart picks)
        self.pp_sync_time_evening = "09:15"  # 9:15 AM - mid-morning PP sync (after game preds post, catches all new lines)
        self.top_picks_time = "14:00"    # 2 PM - post top picks to Discord (after afternoon sync)
        self.hits_blocks_time = "11:00"  # 11 AM - Claude-generated hits/blocks picks (after lineups post)

        # Full-game prediction pipeline
        self.team_stats_time = "02:30"      # 2:30 AM - update team stats + Elo (after games end)
        self.game_prediction_time = "09:00"  # 9:00 AM - generate game predictions (early lines posted by 9 AM)
        self.game_grading_time = "03:15"     # 3:15 AM - grade yesterday's game predictions

        # ML Training Goals - UPDATED: 7.5k for faster launch (Jan 30, 2026)
        self.ml_training_target_per_prop = 7500
        self.ml_training_min_new_preds = 500   # Weekly retrain trigger (new predictions since last train)
        self.ml_training_start_date = "2026-01-30"

        # Prop types and lines (11 combos total — hits/blocks added Mar 8, 2026)
        self.prop_lines = {
            'points': [0.5, 1.5],
            'shots': [1.5, 2.5, 3.5],
            'hits': [0.5, 1.5, 2.5, 3.5],          # New — data collection phase
            'blocked_shots': [0.5, 1.5],            # New — data collection phase
        }
        self.total_prop_combos = sum(len(lines) for lines in self.prop_lines.values())  # 11

        # Data Quality Thresholds
        self.min_feature_completeness = 0.95
        self.min_probability_variety = 50
        self.min_opponent_feature_rate = 0.90
        self.opponent_feature_lookback_days = 14  # Only check last 14 days for opp features
        self.min_daily_predictions = 400
        self.max_daily_predictions = 600

        # Performance Thresholds (NHL: UNDER is much stronger)
        self.target_under_accuracy = 0.70
        self.target_over_accuracy = 0.55

        # API Health Check URL
        self.api_health_url = "https://api-web.nhle.com/v1/schedule/now"

        # Display (using text for Windows compatibility)
        self.emoji = "[NHL]"
        self.full_name = "NHL Hockey"

        # Discord webhook for NHL channel
        self.discord_picks_webhook = os.getenv('NHL_DISCORD_WEBHOOK',
            "https://discord.com/api/webhooks/YOUR_NHL_CHANNEL_WEBHOOK_HERE")

    def _init_nba(self):
        """Initialize NBA-specific configuration"""
        self.project_root = self.root / "nba"
        self.db_path = self.project_root / "database" / "nba_predictions.db"

        # Scripts
        self.prediction_script = "scripts/generate_predictions_daily_V6.py"  # V6: PP line driven
        self.grading_script = "scripts/auto_grade_multi_api_FIXED.py"
        self.schedule_script = None  # NBA uses API directly in prediction script

        # Timing (CST)
        self.grading_time = "05:00"      # 5 AM - grade yesterday first
        self.retrain_time = "05:30"      # 5:30 AM Sunday - weekly ML retrain (after grading, ensures fresh data)
        self.prizepicks_time = "05:30"   # 5:30 AM - fetch PrizePicks lines (early pass before predictions)
        self.prediction_time = "06:00"   # 6 AM - generate today's predictions
        self.pp_sync_time = "12:30"      # 12:30 PM - afternoon PP re-sync (full slate posted by now, refresh smart picks)
        self.pp_sync_time_evening = "10:15"  # 10:15 AM - mid-morning PP sync (after MLB game preds, fresh lines before afternoon)
        self.top_picks_time = "14:20"    # 2:20 PM - post top picks to Discord (after afternoon sync, staggered from NHL)

        # Full-game prediction pipeline
        self.team_stats_time = "04:30"       # 4:30 AM - update team stats + Elo (after late games)
        self.game_prediction_time = "09:30"  # 9:30 AM - generate game predictions (before market moves)
        self.game_grading_time = "05:15"     # 5:15 AM - grade yesterday's game predictions

        # ML Training Goals - UPDATED: 7.5k for faster launch (Jan 27, 2026)
        self.ml_training_target_per_prop = 7500
        self.ml_training_min_new_preds = 500   # Weekly retrain trigger (new predictions since last train)
        self.ml_training_start_date = "2026-01-27"

        # Prop types and lines (14 combos total from CORE_PROPS)
        self.prop_lines = {
            'points': [15.5, 20.5, 25.5],
            'rebounds': [7.5, 10.5],
            'assists': [5.5, 7.5],
            'threes': [2.5],
            'stocks': [2.5],
            'pra': [30.5, 35.5, 40.5],
            'minutes': [28.5, 32.5]
        }
        self.total_prop_combos = sum(len(lines) for lines in self.prop_lines.values())  # 14

        # Data Quality Thresholds
        self.min_feature_completeness = 0.95
        self.min_probability_variety = 50
        self.min_opponent_feature_rate = 0.90
        self.opponent_feature_lookback_days = 14  # Only check last 14 days for opp features
        self.min_daily_predictions = 200
        self.max_daily_predictions = 500

        # Performance Thresholds
        self.target_under_accuracy = 0.65
        self.target_over_accuracy = 0.55

        # API Health Check URL (ESPN is more reliable)
        self.api_health_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

        # Display (using text for Windows compatibility)
        self.emoji = "[NBA]"
        self.full_name = "NBA Basketball"

        # Discord webhook for NBA channel (create webhook in Discord: Server Settings > Integrations > Webhooks)
        # Replace with your 'nba' channel webhook URL
        self.discord_picks_webhook = os.getenv('NBA_DISCORD_WEBHOOK',
            "https://discord.com/api/webhooks/YOUR_NBA_CHANNEL_WEBHOOK_HERE")

    def _init_mlb(self):
        """Initialize MLB-specific configuration"""
        self.project_root = self.root / "mlb"
        self.db_path = self.project_root / "database" / "mlb_predictions.db"

        # Scripts
        self.prediction_script = "scripts/generate_predictions_daily.py"
        self.grading_script = "scripts/auto_grade_daily.py"
        self.schedule_script = "scripts/fetch_game_schedule.py"

        # Timing (CST)
        # West coast night games finish ~midnight CST; grade at 8am to be safe
        self.grading_time = "08:00"      # 8 AM - grade yesterday's games
        self.retrain_time = "08:30"      # 8:30 AM Sunday - weekly ML retrain
        self.prizepicks_time = "08:30"   # 8:30 AM - fetch PrizePicks lines
        self.prediction_time = "10:00"   # 10 AM - some games start 11 AM CST; lineups post ~10am CST
        self.feature_store_time = "10:30"  # 10:30 AM - MLB feature store + ML predictions (decoupled)
        self.pp_sync_time = "15:00"      # 3 PM - refresh lines for evening games
        self.pp_sync_time_evening = "10:45"  # 10:45 AM - mid-morning PP sync (after feature store, before afternoon)
        self.top_picks_time = "16:00"    # 4 PM - post Discord picks

        # Full-game prediction pipeline
        self.team_stats_time = "07:30"       # 7:30 AM - update team stats + Elo
        self.game_prediction_time = "09:45"  # 9:45 AM - generate game predictions (after team stats settle)
        self.game_grading_time = "08:15"     # 8:15 AM - grade yesterday's game predictions

        # ML Training Goals — sourced from mlb_config.py for single source of truth
        from mlb.scripts.mlb_config import (
            ML_TRAINING_TARGET_PER_PROP   as _MLB_TARGET,
            ML_TRAINING_MIN_SAMPLES       as _MLB_MIN_SAMPLES,
            ML_TRAINING_MIN_NEW_PREDICTIONS as _MLB_MIN_NEW,
        )
        self.ml_training_target_per_prop    = _MLB_TARGET       # 7,500
        self.ml_training_min_samples        = _MLB_MIN_SAMPLES  # 500 (Year 1)
        self.ml_training_min_new_preds      = _MLB_MIN_NEW      # 250 (shorter season)
        # First full season ends Oct 2026; first model training eligible early 2027
        self.ml_training_start_date = "2027-03-01"

        # Prop types and lines (30 combos total from CORE_PROPS)
        self.prop_lines = {
            'strikeouts':        [3.5, 4.5, 5.5, 6.5, 7.5],
            'outs_recorded':     [12.5, 15.5, 17.5],
            'pitcher_walks':     [1.5, 2.5],
            'hits_allowed':      [3.5, 5.5],
            'earned_runs':       [0.5, 1.5, 2.5],
            'hits':              [0.5, 1.5],
            'total_bases':       [1.5, 2.5],
            'home_runs':         [0.5],
            'rbis':              [0.5, 1.5],
            'runs':              [0.5],
            'stolen_bases':      [0.5],
            'walks':             [0.5],
            'batter_strikeouts': [0.5, 1.5],
            'hrr':               [1.5, 2.5, 3.5],
        }
        self.total_prop_combos = sum(len(lines) for lines in self.prop_lines.values())  # 30

        # Data Quality Thresholds
        # MLB allows more missing data: TBD starters, unposted lineups are common
        self.min_feature_completeness = 0.90
        self.min_probability_variety = 40
        self.min_opponent_feature_rate = 0.85
        self.opponent_feature_lookback_days = 14
        self.min_daily_predictions = 100   # ~30 pitchers + batters on partial slate
        self.max_daily_predictions = 500

        # Performance Thresholds
        self.target_under_accuracy = 0.60
        self.target_over_accuracy = 0.55

        # API Health Check URL
        self.api_health_url = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&gameType=R"

        # Display
        self.emoji = "[MLB]"
        self.full_name = "MLB Baseball"

        # Discord webhook for MLB channel
        self.discord_picks_webhook = os.getenv('MLB_DISCORD_WEBHOOK', '')

        # SZLN ML refresh (weekly — lines change slowly)
        self.szln_refresh_time = "09:00"   # 9 AM Monday

    def _init_golf(self):
        """Initialize Golf-specific configuration"""
        self.project_root = self.root / "golf"
        self.db_path = self.project_root / "database" / "golf_predictions.db"

        # Scripts
        self.prediction_script = "scripts/generate_predictions_daily.py"
        self.grading_script = "scripts/auto_grade_daily.py"
        self.schedule_script = None  # Golf: tournament detection is handled inside generate_predictions_daily.py

        # Timing (CST)
        # PGA Tour rounds finish Thu/Fri/Sat/Sun evenings; all results posted by 2 AM CST
        self.grading_time = "02:00"      # 2 AM — grade previous round scores (results posted within hours of round end)
        self.retrain_time = "07:00"      # 7 AM Sunday — weekly ML retrain (after predictions, before MLB morning block)
        self.prizepicks_time = "02:15"   # 2:15 AM — fetch PrizePicks golf lines (early pass before predictions)
        self.prediction_time = "04:15"   # 4:15 AM — generate predictions (ready well before 6 AM)
        self.pp_sync_time = "06:30"      # 6:30 AM — early PP sync (after predictions, before MLB morning block; all rounds start by 1 PM)
        self.pp_sync_time_evening = "08:45"  # 8:45 AM — mid-morning PP sync (catches any remaining lines before first tee)
        self.top_picks_time = "13:30"    # 1:30 PM — post Discord picks (after both syncs, staggered from NHL 1 PM)

        # No full-game pipeline for golf (individual/tournament sport)
        self.team_stats_time = None
        self.game_prediction_time = None
        self.game_grading_time = None

        # ML Training Goals
        # Golf has ~46 events/season × 5 seasons × ~100 players × ~3.5 rounds = ~80k rows
        # → should reach 7,500 per prop/line combo well within backfill
        self.ml_training_target_per_prop = 7500
        self.ml_training_min_new_preds = 200    # Fewer per week than daily sports
        self.ml_training_start_date = "2025-06-01"   # After first full season of live predictions

        # Prop types and lines (4 combos total)
        self.prop_lines = {
            'round_score': [68.5, 70.5, 72.5],  # 3 combos
            'make_cut':    [0.5],                # 1 combo
        }
        self.total_prop_combos = sum(len(lines) for lines in self.prop_lines.values())  # 4

        # Data Quality Thresholds
        # Golf has more missing data (not all players have full stat coverage)
        self.min_feature_completeness = 0.80
        self.min_probability_variety = 20    # Smaller daily volume than team sports
        self.min_opponent_feature_rate = 0.0  # Not applicable to golf
        self.opponent_feature_lookback_days = 0
        self.min_daily_predictions = 50    # ~100–400 predictions per tournament day
        self.max_daily_predictions = 2000  # Large field × multiple props

        # Performance Thresholds
        self.target_under_accuracy = 0.60
        self.target_over_accuracy = 0.55

        # API Health Check URL (ESPN golf scoreboard)
        self.api_health_url = "https://site.api.espn.com/apis/site/v2/sports/golf/leaderboard?league=pga"

        # Display
        self.emoji = "[GOLF]"
        self.full_name = "PGA Tour Golf"

        # Discord webhook for Golf channel
        self.discord_picks_webhook = os.getenv('GOLF_DISCORD_WEBHOOK', '')


class GlobalConfig:
    """Global configuration shared across sports"""

    # Health Check
    HEALTH_CHECK_INTERVAL_MINUTES = 60

    # Error Handling
    MAX_CONSECUTIVE_FAILURES = 3
    RETRY_DELAY_SECONDS = 300
    CALIBRATION_DRIFT_THRESHOLD = 0.05

    # Paths
    ROOT = Path(__file__).parent
    LOGS_DIR = ROOT / "logs"
    BACKUPS_DIR = ROOT / "backups"
    STATE_FILE = ROOT / "data" / "orchestrator_state.json"


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class PipelineResult:
    """Result from a pipeline execution"""
    success: bool
    timestamp: str
    sport: str
    operation: str
    details: Dict
    errors: List[str]
    warnings: List[str]


@dataclass
class HealthStatus:
    """System health metrics"""
    timestamp: str
    sport: str
    database_accessible: bool
    api_responsive: bool
    predictions_count: int
    graded_count: int
    feature_completeness: float
    probability_variety: int
    opponent_feature_rate: float
    recent_errors: List[str]
    ml_readiness_score: float  # 0-100


@dataclass
class MLReadinessReport:
    """Comprehensive ML training readiness assessment"""
    sport: str
    total_predictions: int
    predictions_per_prop: Dict[str, int]  # e.g., {"points_0.5": 1234, "shots_2.5": 5678}
    min_prop_count: int  # The bottleneck - lowest count across all prop/lines
    min_prop_name: str   # Which prop/line is the bottleneck
    target_per_prop: int
    predictions_with_features: int
    predictions_with_opponent_features: int
    unique_probabilities: int
    feature_completeness: float
    opponent_feature_rate: float  # Only for last N days
    data_quality_score: float  # 0-100
    estimated_training_date: str
    days_until_training: int
    readiness_percentage: float  # 0-100 (based on bottleneck prop)
    blocking_issues: List[str]
    recommendations: List[str]


# ============================================================================
# ORCHESTRATOR
# ============================================================================

class SportsOrchestrator:
    """
    Master controller for NHL and NBA prediction systems

    This class manages the entire lifecycle of prediction systems,
    from data collection to ML training preparation. It executes tasks
    and monitors health.
    """

    def __init__(self, sport: str):
        """Initialize orchestrator for a specific sport"""
        self.config = SportConfig(sport)
        self.global_config = GlobalConfig()
        self.state = self._load_state()

        # Claude API removed - was expensive and not providing value
        self.claude = None
        self.claude_enabled = False

        # Initialize API Health Monitor
        if API_MONITOR_AVAILABLE:
            self.api_monitor = APIHealthMonitor()
            self.api_monitor_enabled = True
        else:
            self.api_monitor = None
            self.api_monitor_enabled = False

        # Ensure directories exist
        self.global_config.LOGS_DIR.mkdir(exist_ok=True)
        self.global_config.BACKUPS_DIR.mkdir(exist_ok=True)

        # Initialize state tracking for this sport
        sport_key = self.config.sport.lower()
        if sport_key not in self.state:
            self.state[sport_key] = {
                'started_at': datetime.now().isoformat(),
                'last_prediction_gen': None,
                'last_grading': None,
                'last_health_check': None,
                'consecutive_failures': 0,
                'total_runs': 0,
                'ml_training_started': False
            }

        print(f"\n{self.config.emoji} {self.config.full_name} Orchestrator initialized")
        print(f"   API Monitor: {'Enabled' if self.api_monitor_enabled else 'Disabled'}")
        print(f"   ML Target: {self.config.ml_training_target_per_prop:,} per prop/line ({self.config.total_prop_combos} combos)")
        print(f"   Current predictions: {self._count_predictions():,}")
        print(f"   Database: {self.config.db_path}")
        print()

    # ========================================================================
    # CORE EXECUTION METHODS
    # ========================================================================

    def run_daily_prediction_pipeline(self) -> PipelineResult:
        """
        Execute the full daily prediction pipeline

        Steps:
        1. Fetch game schedule for today (if applicable)
        2. Generate predictions for all games
        3. Verify predictions saved correctly
        4. Assess data quality

        Returns:
            PipelineResult with execution details
        """
        print("=" * 80)
        print(f"{self.config.emoji} DAILY PREDICTION PIPELINE - {self.config.sport}")
        print("=" * 80)
        print()

        target_date = datetime.now().strftime('%Y-%m-%d')
        errors = []
        warnings = []
        details = {}
        sport_key = self.config.sport.lower()

        try:
            # NBA: skip entire pipeline when no games scheduled
            if self.config.sport == "NBA" and NBA_SCHEDULE_AVAILABLE:
                has_games, game_count = nba_has_games(target_date)
                if not has_games:
                    print(f"[SKIP] No NBA games on {target_date} - skipping prediction pipeline")
                    print("       (All-Star break or off day)")
                    print()
                    return PipelineResult(
                        success=True,
                        timestamp=datetime.now().isoformat(),
                        sport=self.config.sport,
                        operation="prediction",
                        details={'skipped_schedule': True, 'game_count': 0},
                        errors=[],
                        warnings=["No games scheduled - intentional skip"]
                    )

            # MLB: skip entire pipeline when outside regular season
            if self.config.sport == "MLB" and MLB_SCHEDULE_AVAILABLE:
                if not mlb_has_games(target_date):
                    print(f"[SKIP] No MLB games on {target_date} - outside regular season")
                    print()
                    return PipelineResult(
                        success=True,
                        timestamp=datetime.now().isoformat(),
                        sport=self.config.sport,
                        operation="prediction",
                        details={'skipped_schedule': True, 'game_count': 0},
                        errors=[],
                        warnings=["Outside MLB regular season - intentional skip"]
                    )

            step = 1

            # Step 1: Fetch schedule (NHL only)
            if self.config.schedule_script:
                print(f"[{step}/4] Fetching game schedule for {target_date}...")
                schedule_result = self._run_script(
                    self.config.schedule_script,
                    [target_date]
                )

                if not schedule_result['success']:
                    errors.append(f"Schedule fetch failed: {schedule_result.get('error')}")
                    details['schedule_fetch'] = schedule_result
                else:
                    details['schedule_fetch'] = {'success': True}
                    print(f"   Schedule fetched")
                step += 1

            # Step 1.5: Pre-game intel sweep (Grok — injury/availability/goalie)
            # Runs once, cached to disk. Prediction scripts read the cache during
            # player loop and skip OUT players automatically.
            if PREGAME_INTEL_AVAILABLE and os.getenv('XAI_API_KEY'):
                try:
                    _intel = PreGameIntel()
                    # matchups=[] — module will auto-pull from games DB
                    _intel.fetch(sport_key, target_date, matchups=[])
                    _intel.fetch_betting_context(sport_key, target_date, matchups=[])
                    details['pregame_intel'] = {'success': True}
                    notes = _intel.get_notes(sport_key, target_date)
                    if notes:
                        print(f'   Intel: {notes[0]}')
                    # Post combined intel embed to sport channel
                    try:
                        from pregame_intel import post_intel_to_discord
                        sport_webhook = getattr(self.config, 'discord_picks_webhook', '')
                        if sport_webhook and 'YOUR_' not in sport_webhook:
                            post_intel_to_discord(sport_key, target_date, sport_webhook)
                    except Exception:
                        pass
                except Exception as e:
                    details['pregame_intel'] = {'success': False, 'error': str(e)}
                    warnings.append(f'Pre-game intel failed (non-fatal): {e}')

            # Step 2: Generate predictions
            print(f"[{step}/4] Generating predictions...")

            # Build args based on sport
            args = [target_date]
            if self.config.sport == "NHL":
                args.append('--force')

            prediction_result = self._run_script(
                self.config.prediction_script,
                args
            )

            if not prediction_result['success']:
                errors.append(f"Prediction generation failed: {prediction_result.get('error')}")
                details['prediction_gen'] = prediction_result
                if prediction_result.get('error'):
                    print(f"   ERROR: {prediction_result.get('error')[:300]}")
            else:
                details['prediction_gen'] = prediction_result
                # Verify we actually got predictions — exit 0 doesn't mean rows were written
                try:
                    conn = sqlite3.connect(str(self.config.db_path))
                    cur = conn.cursor()
                    cur.execute('SELECT COUNT(*) FROM predictions WHERE game_date = ?', (target_date,))
                    pred_count = cur.fetchone()[0]
                    conn.close()
                except Exception:
                    pred_count = -1

                if pred_count == 0:
                    errors.append(
                        f"Prediction script exited 0 but 0 predictions found in DB for {target_date}. "
                        f"Check stderr: {prediction_result.get('output', '')[-300:]}"
                    )
                    print(f"   ERROR: Script succeeded but 0 predictions in DB — pipeline failure")
                    self._send_discord_alert(
                        f"{self.config.emoji} PREDICTION FAILURE {target_date}",
                        f"Script exited OK but **0 predictions** were saved to the database.\n"
                        f"Top-20 Discord picks will not fire.\n"
                        f"Run manually: `python {self.config.prediction_script} {target_date} --force`"
                    )
                else:
                    print(f"   Predictions generated ({pred_count:,} rows)")
                    # Direction sanity check — alert if any competitive prop is >85% one way
                    self.check_prediction_direction_sanity(target_date)
            step += 1

            # Step 3: Verify predictions
            print(f"[{step}/4] Verifying data quality...")
            verification = self._verify_predictions(target_date)
            details['verification'] = verification

            if verification.get('issues'):
                for issue in verification['issues']:
                    warnings.append(issue)
                print(f"   {len(verification['issues'])} warnings detected")
            else:
                print(f"   All quality checks passed")
            step += 1

            # Step 4: Assess ML readiness
            print(f"[{step}/4] Assessing ML readiness...")
            ml_readiness = self._assess_ml_readiness()
            details['ml_readiness'] = asdict(ml_readiness)
            print(f"   ML Readiness: {ml_readiness.readiness_percentage:.1f}%")
            print(f"   Progress: {ml_readiness.min_prop_count:,}/{self.config.ml_training_target_per_prop:,} (bottleneck: {ml_readiness.min_prop_name})")

            # Update state
            self.state[sport_key]['last_prediction_gen'] = datetime.now().isoformat()
            self.state[sport_key]['total_runs'] += 1
            if not errors:
                self.state[sport_key]['consecutive_failures'] = 0
            else:
                self.state[sport_key]['consecutive_failures'] += 1
            self._save_state()

            success = len(errors) == 0

            # Send Discord notification
            self.send_prediction_notification(target_date, details)

            # Post smart picks to Discord channel (if configured)
            if success:
                self._post_smart_picks_to_discord(target_date)

            # Sync predictions to Supabase (FreePicks cloud)
            if success and SUPABASE_SYNC_AVAILABLE:
                try:
                    print(f"\n[SYNC] Syncing predictions to Supabase...")
                    syncer = SupabaseSync()
                    sync_result = syncer.sync_predictions(self.config.sport.lower(), target_date)
                    smart_sync = syncer.sync_smart_picks(self.config.sport.lower(), target_date)
                    # Fix odds_type labels (goblin/demon rows written as 'standard' by sync_predictions)
                    odds_sync = syncer.sync_odds_types(self.config.sport.lower(), target_date)
                    # Populate game_time from PP start_time so dashboard shows tip-off times
                    time_sync = syncer.sync_game_times(self.config.sport.lower(), target_date)
                    details['supabase_sync'] = {
                        'predictions': sync_result,
                        'smart_picks': smart_sync,
                        'odds_types': odds_sync,
                        'game_times': time_sync,
                    }
                    print(f"[SYNC] Complete: {sync_result.get('synced', 0)} predictions, "
                          f"{smart_sync.get('synced', 0)} smart picks, "
                          f"{odds_sync.get('updated', 0)} odds corrections, "
                          f"{time_sync.get('updated', 0)} game times")
                except Exception as e:
                    warnings.append(f"Supabase sync failed: {str(e)}")
                    print(f"[SYNC ERROR] {e}")

            # Turso redundant sync (runs after Supabase, non-blocking)
            if success and TURSO_SYNC_AVAILABLE:
                try:
                    print(f"\n[TURSO] Syncing predictions to Turso...")
                    asyncio.run(_turso_sync_predictions(self.config.sport.lower(), target_date))
                    asyncio.run(_turso_sync_smart_picks(self.config.sport.lower(), target_date))
                    print(f"[TURSO] Sync complete.")
                except Exception as e:
                    warnings.append(f"Turso sync failed (non-fatal): {str(e)}")
                    print(f"[TURSO ERROR] {e}")

            return PipelineResult(
                success=success,
                timestamp=datetime.now().isoformat(),
                sport=self.config.sport,
                operation='daily_prediction_pipeline',
                details=details,
                errors=errors,
                warnings=warnings
            )

        except Exception as e:
            error_msg = f"Pipeline crashed: {str(e)}"
            errors.append(error_msg)
            self._log_error(traceback.format_exc(), "PIPELINE_CRASH")

            return PipelineResult(
                success=False,
                timestamp=datetime.now().isoformat(),
                sport=self.config.sport,
                operation='daily_prediction_pipeline',
                details=details,
                errors=errors,
                warnings=warnings
            )

    def run_daily_grading(self) -> PipelineResult:
        """
        Grade yesterday's predictions

        Steps:
        1. Grade all predictions from yesterday
        2. Calculate accuracy metrics
        3. Check for calibration drift

        Returns:
            PipelineResult with grading details
        """
        print("=" * 80)
        print(f"{self.config.emoji} DAILY GRADING PIPELINE - {self.config.sport}")
        print("=" * 80)
        print()

        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        errors = []
        warnings = []
        details = {}
        sport_key = self.config.sport.lower()

        try:
            # Step 0: API Health Check (for NBA only, with auto-healing)
            if self.config.sport == "NBA" and self.api_monitor_enabled:
                print(f"[0/4] Running API health check...")
                api_health = self._check_and_heal_apis(yesterday)
                details['api_health'] = api_health

                if api_health.get('healed'):
                    warnings.append(f"API auto-healed: {api_health.get('healed_apis')}")
                    print(f"   APIs auto-healed: {', '.join(api_health.get('healed_apis', []))}")
                elif api_health.get('all_healthy'):
                    print(f"   All APIs healthy")
                else:
                    print(f"   Health check complete")

            # Step 1: Run grading script
            step_num = 1 if self.config.sport == "NHL" else 1
            total_steps = 3 if self.config.sport == "NHL" else 4
            print(f"[{step_num}/{total_steps}] Grading predictions for {yesterday}...")
            grading_result = self._run_script(
                self.config.grading_script,
                [yesterday]
            )

            if not grading_result['success']:
                errors.append(f"Grading failed: {grading_result.get('error')}")
                details['grading'] = grading_result
                # Show error output for debugging
                if grading_result.get('error'):
                    print(f"   ERROR: {grading_result.get('error')[:300]}")
            else:
                details['grading'] = grading_result
                print(f"   Grading complete")

            # Step 2: Calculate accuracy metrics
            step_num = 2 if self.config.sport == "NHL" else 2
            total_steps = 3 if self.config.sport == "NHL" else 4
            print(f"[{step_num}/{total_steps}] Calculating performance metrics...")
            metrics = self._calculate_accuracy_metrics(yesterday)
            details['metrics'] = metrics

            # Check for concerning patterns
            if metrics.get('under_accuracy', 0) < self.config.target_under_accuracy:
                warnings.append(f"UNDER accuracy below target: {metrics['under_accuracy']:.1%}")

            if metrics.get('over_accuracy', 0) < self.config.target_over_accuracy:
                warnings.append(f"OVER accuracy below target: {metrics['over_accuracy']:.1%}")

            print(f"   UNDER: {metrics.get('under_accuracy', 0):.1%}")
            print(f"   OVER: {metrics.get('over_accuracy', 0):.1%}")

            # Step 3: Check calibration
            step_num = 3 if self.config.sport == "NHL" else 3
            total_steps = 3 if self.config.sport == "NHL" else 4
            print(f"[{step_num}/{total_steps}] Checking calibration drift...")
            calibration = self._check_calibration_drift()
            details['calibration'] = calibration

            if calibration.get('drift', 0) > self.global_config.CALIBRATION_DRIFT_THRESHOLD:
                warnings.append(f"Calibration drift detected: {calibration['drift']:.1%}")
                print(f"   Drift: {calibration['drift']:.1%}")
            else:
                print(f"   Calibration stable")

            # MLB ML grading — run after stat grading so hitter/pitcher labels are fresh
            # Uses the same decoupled _run_feature_store_cmd helper; non-fatal.
            if self.config.sport == "MLB":
                print(f"\n[MLB ML] Grading ML predictions for {yesterday}...")
                ml_grade_result = self._run_feature_store_cmd(
                    ['-m', 'ml.grade', '--date', yesterday],
                    f'ml.grade {yesterday}'
                )
                if ml_grade_result['success']:
                    print(f"[MLB ML] ml.grade OK")
                else:
                    err = (ml_grade_result.get('error') or '')[:200]
                    print(f"[MLB ML] ml.grade FAILED (non-fatal): {err}")

            # Update state
            self.state[sport_key]['last_grading'] = datetime.now().isoformat()
            self._save_state()

            success = len(errors) == 0

            # Send Discord notification
            self.send_grading_notification(yesterday, details)

            # Sync grading results to Supabase + trigger user pick grading
            # Run sync even if grading had non-fatal errors — partial results are
            # better than no results in Supabase.
            if SUPABASE_SYNC_AVAILABLE:
                try:
                    print(f"\n[SYNC] Syncing grading results to Supabase...")
                    syncer = SupabaseSync()
                    grading_sync = syncer.sync_grading(self.config.sport.lower(), yesterday)
                    user_grading = syncer.trigger_user_grading(yesterday, self.config.sport)
                    details['supabase_sync'] = {
                        'grading': grading_sync,
                        'user_grading': user_grading,
                    }
                    synced_count = grading_sync.get('synced', 0)
                    print(f"[SYNC] Grading sync complete: {synced_count} results")
                    if synced_count == 0:
                        self._send_discord_alert(
                            f"{self.config.emoji} GRADING SYNC WARNING {yesterday}",
                            f"Grading ran but **0 results synced to Supabase**.\n"
                            f"Mobile app will show stale data. Check sync logs."
                        )

                    # Turso redundant grading sync
                    if TURSO_SYNC_AVAILABLE:
                        try:
                            asyncio.run(_turso_sync_grading(self.config.sport.lower(), yesterday))
                        except Exception as te:
                            print(f"[TURSO ERROR] Grading sync failed (non-fatal): {te}")
                except Exception as e:
                    warnings.append(f"Supabase grading sync failed: {str(e)}")
                    print(f"[SYNC ERROR] {e}")
                    self._send_discord_alert(
                        f"{self.config.emoji} GRADING SYNC FAILED {yesterday}",
                        f"Supabase sync threw an exception after grading:\n`{str(e)[:300]}`\n"
                        f"Mobile app will show stale/ungraded data."
                    )

            return PipelineResult(
                success=success,
                timestamp=datetime.now().isoformat(),
                sport=self.config.sport,
                operation='daily_grading',
                details=details,
                errors=errors,
                warnings=warnings
            )

        except Exception as e:
            error_msg = f"Grading crashed: {str(e)}"
            errors.append(error_msg)
            self._log_error(traceback.format_exc(), "GRADING_CRASH")

            return PipelineResult(
                success=False,
                timestamp=datetime.now().isoformat(),
                sport=self.config.sport,
                operation='daily_grading',
                details=details,
                errors=errors,
                warnings=warnings
            )

    def run_health_check(self) -> HealthStatus:
        """
        Comprehensive system health check

        Checks:
        - Database accessibility
        - API health
        - Data quality metrics
        - Feature completeness
        - Recent errors
        - ML readiness

        Returns:
            HealthStatus object
        """
        print(f"\n{self.config.emoji} Running {self.config.sport} health check...")
        sport_key = self.config.sport.lower()

        try:
            # Database check
            db_ok = self._check_database_health()

            # API check
            api_ok = self._check_api_health()

            # Count predictions
            total_preds = self._count_predictions()
            graded_preds = self._count_graded_predictions()

            # Data quality
            feature_completeness = self._check_feature_completeness()
            prob_variety = self._check_probability_variety()
            opp_feature_rate = self._check_opponent_feature_rate()

            # Recent errors
            recent_errors = self._get_recent_errors(hours=24)

            # Calculate ML readiness score
            ml_score = self._calculate_ml_readiness_score(
                total_preds,
                feature_completeness,
                opp_feature_rate,
                prob_variety
            )

            health = HealthStatus(
                timestamp=datetime.now().isoformat(),
                sport=self.config.sport,
                database_accessible=db_ok,
                api_responsive=api_ok,
                predictions_count=total_preds,
                graded_count=graded_preds,
                feature_completeness=feature_completeness,
                probability_variety=prob_variety,
                opponent_feature_rate=opp_feature_rate,
                recent_errors=recent_errors,
                ml_readiness_score=ml_score
            )

            # Update state
            self.state[sport_key]['last_health_check'] = datetime.now().isoformat()
            self._save_state()

            # Log health status
            status = "HEALTHY" if db_ok and api_ok and not recent_errors else "ISSUES DETECTED"
            print(f"   Status: {status}")
            print(f"   Database: {'OK' if db_ok else 'FAIL'}")
            print(f"   API: {'OK' if api_ok else 'FAIL'}")
            print(f"   Predictions: {total_preds:,}")
            print(f"   Graded: {graded_preds:,}")
            print(f"   Feature Completeness: {feature_completeness:.1%}")
            print(f"   ML Readiness: {ml_score:.1f}/100")

            return health

        except Exception as e:
            self._log_error(traceback.format_exc(), "HEALTH_CHECK_ERROR")

            return HealthStatus(
                timestamp=datetime.now().isoformat(),
                sport=self.config.sport,
                database_accessible=False,
                api_responsive=False,
                predictions_count=0,
                graded_count=0,
                feature_completeness=0.0,
                probability_variety=0,
                opponent_feature_rate=0.0,
                recent_errors=[str(e)],
                ml_readiness_score=0.0
            )

    # ========================================================================
    # ML READINESS ASSESSMENT
    # ========================================================================

    def _assess_ml_readiness(self) -> MLReadinessReport:
        """
        Comprehensive assessment of ML training readiness

        This is THE MOST IMPORTANT function - it ensures we're on track
        to build prediction juggernauts by monitoring data quality
        and feature health.

        Key: We need 10k predictions PER PROP TYPE PER LINE.
        ML readiness is based on the BOTTLENECK (lowest count prop/line).

        Returns:
            MLReadinessReport with detailed assessment
        """
        db_path = str(self.config.db_path)
        target_per_prop = self.config.ml_training_target_per_prop

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Total predictions
            cursor.execute('SELECT COUNT(*) FROM predictions')
            total_preds = cursor.fetchone()[0]

            # Count predictions per prop type per line
            predictions_per_prop = {}
            for prop_type, lines in self.config.prop_lines.items():
                for line in lines:
                    key = f"{prop_type}_{line}"
                    cursor.execute(
                        'SELECT COUNT(*) FROM predictions WHERE prop_type = ? AND line = ?',
                        (prop_type, line)
                    )
                    predictions_per_prop[key] = cursor.fetchone()[0]

            # Find the bottleneck (minimum count)
            if predictions_per_prop:
                min_prop_name = min(predictions_per_prop, key=predictions_per_prop.get)
                min_prop_count = predictions_per_prop[min_prop_name]
            else:
                min_prop_name = "unknown"
                min_prop_count = 0

            # Check schema to determine how features are stored
            cursor.execute('PRAGMA table_info(predictions)')
            columns = [col[1] for col in cursor.fetchall()]
            has_features_json = 'features_json' in columns
            has_f_columns = any(col.startswith('f_') for col in columns)

            # Predictions with features
            if has_features_json:
                cursor.execute('SELECT COUNT(*) FROM predictions WHERE features_json IS NOT NULL')
                with_features = cursor.fetchone()[0]
            elif has_f_columns:
                f_cols = [col for col in columns if col.startswith('f_')]
                if f_cols:
                    cursor.execute(f'SELECT COUNT(*) FROM predictions WHERE {f_cols[0]} IS NOT NULL')
                    with_features = cursor.fetchone()[0]
                else:
                    with_features = 0
            else:
                with_features = 0

            # Check opponent features - ONLY for last N days
            lookback_days = self.config.opponent_feature_lookback_days
            cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

            if has_features_json:
                # NHL schema: count predictions with 'opp_' in features_json for recent predictions
                # Use SQL LIKE instead of sampling for accuracy
                cursor.execute(
                    '''SELECT COUNT(*) FROM predictions
                       WHERE features_json IS NOT NULL
                       AND game_date >= ?
                       AND features_json LIKE "%opp_%"''',
                    (cutoff_date,)
                )
                recent_with_opp = cursor.fetchone()[0]

                cursor.execute(
                    'SELECT COUNT(*) FROM predictions WHERE features_json IS NOT NULL AND game_date >= ?',
                    (cutoff_date,)
                )
                recent_total = cursor.fetchone()[0]

                if recent_total > 0:
                    opp_rate = recent_with_opp / recent_total
                    with_opp_total = recent_with_opp
                else:
                    opp_rate = 0.0
                    with_opp_total = 0
            elif has_f_columns:
                # NBA: check for opp_ columns or use feature completeness
                opp_cols = [col for col in columns if 'opp_' in col.lower()]
                if opp_cols:
                    cursor.execute(f'SELECT COUNT(*) FROM predictions WHERE {opp_cols[0]} IS NOT NULL AND game_date >= ?', (cutoff_date,))
                    recent_with_opp = cursor.fetchone()[0]
                    cursor.execute('SELECT COUNT(*) FROM predictions WHERE game_date >= ?', (cutoff_date,))
                    recent_total = cursor.fetchone()[0]
                    opp_rate = recent_with_opp / recent_total if recent_total > 0 else 0.0
                    with_opp_total = int(with_features * opp_rate)
                else:
                    # NBA doesn't have explicit opp columns - use feature rate as proxy
                    opp_rate = with_features / total_preds if total_preds > 0 else 0.0
                    with_opp_total = with_features
            else:
                opp_rate = 0.0
                with_opp_total = 0

            # Unique probabilities
            cursor.execute('SELECT COUNT(DISTINCT ROUND(probability, 3)) FROM predictions')
            unique_probs = cursor.fetchone()[0]

            conn.close()

        except Exception as e:
            # Return empty report if database fails
            return MLReadinessReport(
                sport=self.config.sport,
                total_predictions=0,
                predictions_per_prop={},
                min_prop_count=0,
                min_prop_name="unknown",
                target_per_prop=target_per_prop,
                predictions_with_features=0,
                predictions_with_opponent_features=0,
                unique_probabilities=0,
                feature_completeness=0.0,
                opponent_feature_rate=0.0,
                data_quality_score=0.0,
                estimated_training_date="Unknown",
                days_until_training=999,
                readiness_percentage=0.0,
                blocking_issues=[f"Database error: {str(e)}"],
                recommendations=["Fix database connection"]
            )

        # Calculate metrics
        feature_completeness = with_features / total_preds if total_preds > 0 else 0.0

        # Data quality score (0-100)
        quality_score = (
            (feature_completeness * 40) +
            (min(opp_rate, 1.0) * 30) +
            (min(unique_probs / 100, 1.0) * 30)
        )

        # Progress toward ML training - based on BOTTLENECK prop/line
        progress = min_prop_count / target_per_prop if target_per_prop > 0 else 0
        readiness_pct = min(progress * 100, 100.0)

        # Estimate training date
        try:
            target_date = datetime.strptime(self.config.ml_training_start_date, '%Y-%m-%d')
            days_until = (target_date - datetime.now()).days
        except:
            target_date = datetime.now() + timedelta(days=30)
            days_until = 30

        # Blocking issues
        blocking_issues = []

        # Check each prop/line combo
        props_below_target = []
        for prop_key, count in predictions_per_prop.items():
            if count < target_per_prop:
                remaining = target_per_prop - count
                props_below_target.append(f"{prop_key}: {count:,} ({remaining:,} needed)")

        if props_below_target:
            blocking_issues.append(
                f"Props below {target_per_prop:,} target:\n      " + "\n      ".join(props_below_target)
            )

        if feature_completeness < self.config.min_feature_completeness:
            blocking_issues.append(
                f"Feature completeness: {feature_completeness:.1%} (need {self.config.min_feature_completeness:.0%})"
            )

        if opp_rate < self.config.min_opponent_feature_rate:
            blocking_issues.append(
                f"Opponent features (last {lookback_days}d): {opp_rate:.1%} (need {self.config.min_opponent_feature_rate:.0%})"
            )

        if unique_probs < self.config.min_probability_variety:
            blocking_issues.append(
                f"Probability variety: {unique_probs} unique (need {self.config.min_probability_variety})"
            )

        # Recommendations
        recommendations = []
        if feature_completeness < 1.0:
            recommendations.append("Investigate why some predictions lack features")

        if opp_rate < 0.95:
            recommendations.append(f"Check opponent feature extraction (only {opp_rate:.0%} in last {lookback_days} days)")

        if min_prop_count < target_per_prop:
            recommendations.append(f"Focus on collecting more {min_prop_name} predictions (bottleneck)")

        if quality_score < 80:
            recommendations.append("Improve data quality before ML training")

        all_props_ready = all(count >= target_per_prop for count in predictions_per_prop.values())
        if all_props_ready and opp_rate >= self.config.min_opponent_feature_rate:
            recommendations.append(f"READY FOR ML TRAINING! All {self.config.sport} requirements met.")

        return MLReadinessReport(
            sport=self.config.sport,
            total_predictions=total_preds,
            predictions_per_prop=predictions_per_prop,
            min_prop_count=min_prop_count,
            min_prop_name=min_prop_name,
            target_per_prop=target_per_prop,
            predictions_with_features=with_features,
            predictions_with_opponent_features=with_opp_total,
            unique_probabilities=unique_probs,
            feature_completeness=feature_completeness,
            opponent_feature_rate=opp_rate,
            data_quality_score=quality_score,
            estimated_training_date=target_date.strftime('%Y-%m-%d'),
            days_until_training=days_until,
            readiness_percentage=readiness_pct,
            blocking_issues=blocking_issues,
            recommendations=recommendations
        )

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _run_script(self, script_name: str, args: List[str] = None) -> Dict:
        """Run a Python script and capture result"""
        try:
            script_path = self.config.project_root / script_name
            cmd = [sys.executable, str(script_path)]
            if args:
                cmd.extend(args)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=300,  # 5 minute timeout
                cwd=str(self.config.project_root)
            )

            # Parse output for key metrics
            output = result.stdout

            # Always log stdout + stderr to a daily pipeline log file
            try:
                log_dir = Path(__file__).parent / "logs"
                log_dir.mkdir(exist_ok=True)
                log_file = log_dir / f"pipeline_{self.config.sport.lower()}_{datetime.now().strftime('%Y%m%d')}.log"
                with open(log_file, 'a', encoding='utf-8') as lf:
                    lf.write(f"\n{'='*60}\n")
                    lf.write(f"[{datetime.now().strftime('%H:%M:%S')}] {script_name} {' '.join(args or [])}\n")
                    lf.write(f"Exit code: {result.returncode}\n")
                    if output:
                        lf.write("STDOUT:\n" + output + "\n")
                    if result.stderr:
                        lf.write("STDERR:\n" + result.stderr + "\n")
            except Exception:
                pass  # Never let logging crash the orchestrator

            return {
                'success': result.returncode == 0,
                'output': output,
                'error': result.stderr if result.returncode != 0 else result.stderr or None
            }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Script timed out after 5 minutes'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def run_mlb_feature_store(self) -> None:
        """
        Standalone scheduled task: run mlb_feature_store pipeline + ML predictions.

        Scheduled at 10:20 AM — 20 minutes after the stat model prediction (10:00 AM).
        Runs independently so a slow or erroring stat model cannot block it.

        Steps:
          1. run_daily.py --date <today>   (Statcast ingest + rolling features + labels)
          2. ml.predict_to_db --date <today>  (write XGBoost ML predictions to DuckDB)

        Both steps are non-fatal — failures are Discord-alerted but never raise.
        """
        if self.config.sport != "MLB":
            return

        target_date = datetime.now().strftime('%Y-%m-%d')
        print(f"\n[MLB FS] Starting feature store pipeline for {target_date}")

        # Step 1: Statcast ingest + feature computation
        fs_result = self._run_feature_store_cmd(
            ['run_daily.py', '--date', target_date],
            f'run_daily {target_date}'
        )

        if not fs_result['success']:
            err = (fs_result.get('error') or '')[:300]
            print(f"[MLB FS] run_daily FAILED: {err}")
            self._send_discord_alert(
                f"[MLB] Feature Store Warning {target_date}",
                f"run_daily.py failed — ML predictions may be stale.\n```{err}```"
            )
            return

        print(f"[MLB FS] run_daily OK")

        # Step 2: Write ML predictions to DuckDB
        ml_result = self._run_feature_store_cmd(
            ['-m', 'ml.predict_to_db', '--date', target_date],
            f'ml.predict_to_db {target_date}'
        )

        if not ml_result['success']:
            err = (ml_result.get('error') or '')[:300]
            print(f"[MLB FS] predict_to_db FAILED: {err}")
            self._send_discord_alert(
                f"[MLB] ML Predictions Warning {target_date}",
                f"ml.predict_to_db failed — dashboard ML column will be empty.\n```{err}```"
            )
            return

        # Count rows written and report
        try:
            import duckdb as _ddb
            from pathlib import Path as _P
            duck_path = _P(__file__).parent / 'mlb_feature_store' / 'data' / 'mlb.duckdb'
            _dc = _ddb.connect(str(duck_path), read_only=True)
            count = _dc.execute(
                f"SELECT COUNT(*) FROM ml_predictions WHERE game_date = '{target_date}'"
            ).fetchone()[0]
            _dc.close()
            print(f"[MLB FS] ML predictions written: {count} rows for {target_date}")
            self._send_discord_alert(
                f"[MLB] ML Predictions Ready {target_date}",
                f"{count} XGBoost predictions written to DuckDB for {target_date}. Dashboard ML column is live."
            )
        except Exception:
            print(f"[MLB FS] predict_to_db OK (could not verify row count)")

    def _run_feature_store_cmd(self, module_args: List[str], step_name: str) -> Dict:
        """
        Run a command in the mlb_feature_store directory.
        Used for: run_daily.py, python -m ml.predict_to_db, python -m ml.grade.

        Always non-fatal — failures are logged as warnings, never block the
        main pipeline.

        module_args examples:
            ['run_daily.py', '--date', '2026-04-13']
            ['-m', 'ml.predict_to_db', '--date', '2026-04-13']
            ['-m', 'ml.grade', '--date', '2026-04-13']
        """
        fs_dir = Path(__file__).parent / "mlb_feature_store"
        if not fs_dir.exists():
            return {'success': False, 'error': 'mlb_feature_store/ not found'}
        try:
            cmd = [sys.executable] + module_args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=600,  # 10 min — Statcast download can be slow on first run of the day
                cwd=str(fs_dir),
            )
            # Append to daily pipeline log
            try:
                log_dir = Path(__file__).parent / "logs"
                log_dir.mkdir(exist_ok=True)
                log_file = log_dir / f"pipeline_mlb_{datetime.now().strftime('%Y%m%d')}.log"
                with open(log_file, 'a', encoding='utf-8') as lf:
                    lf.write(f"\n{'='*60}\n")
                    lf.write(f"[{datetime.now().strftime('%H:%M:%S')}] feature_store: {step_name}\n")
                    lf.write(f"Exit code: {result.returncode}\n")
                    if result.stdout:
                        lf.write("STDOUT:\n" + result.stdout + "\n")
                    if result.stderr:
                        lf.write("STDERR:\n" + result.stderr[-500:] + "\n")
            except Exception:
                pass
            return {
                'success': result.returncode == 0,
                'output': result.stdout,
                'error': result.stderr if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': f'{step_name} timed out after 5 minutes'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _count_predictions(self) -> int:
        """Count total predictions in database"""
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM predictions')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def _count_graded_predictions(self) -> int:
        """Count graded predictions"""
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM prediction_outcomes')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def _verify_predictions(self, date: str) -> Dict:
        """Verify predictions for a date"""
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) FROM predictions WHERE game_date = ?', (date,))
            count = cursor.fetchone()[0]

            cursor.execute('''
                SELECT COUNT(*) FROM predictions
                WHERE game_date = ? AND features_json IS NOT NULL
            ''', (date,))
            with_features = cursor.fetchone()[0]

            cursor.execute('''
                SELECT COUNT(DISTINCT ROUND(probability, 3))
                FROM predictions WHERE game_date = ?
            ''', (date,))
            unique_probs = cursor.fetchone()[0]

            conn.close()

            issues = []
            if count < self.config.min_daily_predictions:
                issues.append(f"Low prediction count: {count} (expected {self.config.min_daily_predictions}+)")

            if count > self.config.max_daily_predictions:
                issues.append(f"High prediction count: {count} (expected <{self.config.max_daily_predictions})")

            if count > 0 and with_features < count * 0.95:
                issues.append(f"Missing features: {with_features}/{count}")

            if unique_probs < 30:
                issues.append(f"Low probability variety: {unique_probs} unique values")

            return {
                'count': count,
                'with_features': with_features,
                'unique_probs': unique_probs,
                'issues': issues
            }
        except Exception as e:
            return {
                'count': 0,
                'with_features': 0,
                'unique_probs': 0,
                'issues': [f"Verification failed: {str(e)}"]
            }

    def _calculate_accuracy_metrics(self, date: str) -> Dict:
        """Calculate accuracy metrics for a date"""
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()

            # Overall accuracy
            cursor.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
                FROM prediction_outcomes
                WHERE game_date = ?
            ''', (date,))

            row = cursor.fetchone()
            total = row[0] if row else 0
            hits = row[1] if row else 0

            # UNDER accuracy
            cursor.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
                FROM prediction_outcomes
                WHERE game_date = ? AND prediction = 'UNDER'
            ''', (date,))

            row = cursor.fetchone()
            under_total = row[0] if row else 0
            under_hits = row[1] if row else 0

            # OVER accuracy
            cursor.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
                FROM prediction_outcomes
                WHERE game_date = ? AND prediction = 'OVER'
            ''', (date,))

            row = cursor.fetchone()
            over_total = row[0] if row else 0
            over_hits = row[1] if row else 0

            conn.close()

            return {
                'overall_accuracy': hits / total if total > 0 else 0,
                'under_accuracy': under_hits / under_total if under_total > 0 else 0,
                'over_accuracy': over_hits / over_total if over_total > 0 else 0,
                'total': total,
                'hits': hits
            }
        except:
            return {
                'overall_accuracy': 0,
                'under_accuracy': 0,
                'over_accuracy': 0,
                'total': 0,
                'hits': 0
            }

    def _check_feature_completeness(self) -> float:
        """Check what % of predictions have features"""
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) FROM predictions')
            total = cursor.fetchone()[0]

            # Check schema to determine how features are stored
            cursor.execute('PRAGMA table_info(predictions)')
            columns = [col[1] for col in cursor.fetchall()]

            if 'features_json' in columns:
                cursor.execute('SELECT COUNT(*) FROM predictions WHERE features_json IS NOT NULL')
                with_features = cursor.fetchone()[0]
            else:
                # NBA schema: check f_* columns
                f_cols = [col for col in columns if col.startswith('f_')]
                if f_cols:
                    cursor.execute(f'SELECT COUNT(*) FROM predictions WHERE {f_cols[0]} IS NOT NULL')
                    with_features = cursor.fetchone()[0]
                else:
                    with_features = 0

            conn.close()

            return with_features / total if total > 0 else 0.0
        except:
            return 0.0

    def _check_probability_variety(self) -> int:
        """Check number of unique probability values"""
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(DISTINCT ROUND(probability, 3)) FROM predictions')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def _check_opponent_feature_rate(self) -> float:
        """Check what % of recent predictions have opponent features (last N days)"""
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()

            # Check schema
            cursor.execute('PRAGMA table_info(predictions)')
            columns = [col[1] for col in cursor.fetchall()]

            lookback_days = self.config.opponent_feature_lookback_days
            cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

            if 'features_json' in columns:
                # NHL schema: count with SQL LIKE for accuracy
                cursor.execute(
                    '''SELECT COUNT(*) FROM predictions
                       WHERE features_json IS NOT NULL
                       AND game_date >= ?
                       AND features_json LIKE "%opp_%"''',
                    (cutoff_date,)
                )
                with_opp = cursor.fetchone()[0]

                cursor.execute(
                    'SELECT COUNT(*) FROM predictions WHERE features_json IS NOT NULL AND game_date >= ?',
                    (cutoff_date,)
                )
                total = cursor.fetchone()[0]
                conn.close()

                return with_opp / total if total > 0 else 0.0
            else:
                # NBA schema: check for opp_ columns or assume feature completeness = opponent rate
                opp_cols = [col for col in columns if 'opp_' in col.lower()]
                if opp_cols:
                    cursor.execute(f'SELECT COUNT(*) FROM predictions WHERE {opp_cols[0]} IS NOT NULL AND game_date >= ?', (cutoff_date,))
                    with_opp = cursor.fetchone()[0]
                    cursor.execute('SELECT COUNT(*) FROM predictions WHERE game_date >= ?', (cutoff_date,))
                    total = cursor.fetchone()[0]
                    conn.close()
                    return with_opp / total if total > 0 else 0.0
                else:
                    # NBA doesn't have explicit opponent columns - return feature completeness
                    conn.close()
                    return self._check_feature_completeness()
        except:
            return 0.0

    def _check_database_health(self) -> bool:
        """Check if database is accessible"""
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            conn.close()
            return True
        except:
            return False

    def _check_api_health(self) -> bool:
        """Check if sport API is responsive"""
        if not REQUESTS_AVAILABLE:
            return True  # Assume OK if requests not available

        try:
            response = requests.get(self.config.api_health_url, timeout=5)
            return response.status_code == 200
        except:
            return False

    def _check_calibration_drift(self) -> Dict:
        """Check for calibration drift in recent predictions"""
        # Placeholder - would implement actual calibration analysis
        return {'drift': 0.02}

    def _calculate_ml_readiness_score(
        self,
        total_preds: int,
        feature_completeness: float,
        opp_feature_rate: float,
        prob_variety: int
    ) -> float:
        """Calculate overall ML readiness score (0-100)"""

        # Volume score (0-40 points)
        volume_score = min(total_preds / (self.config.ml_training_target_per_prop * self.config.total_prop_combos), 1.0) * 40

        # Quality score (0-60 points)
        quality_score = (
            (feature_completeness * 20) +  # Features present
            (opp_feature_rate * 20) +       # Opponent features present
            (min(prob_variety / 100, 1.0) * 20)  # Probability variety
        )

        return volume_score + quality_score

    def _get_recent_errors(self, hours: int = 24) -> List[str]:
        """Get recent errors from logs"""
        # Placeholder - would parse error logs
        return []

    def _check_and_heal_apis(self, test_date: str) -> Dict:
        """
        Check API health and auto-heal if needed.

        This runs before grading to ensure APIs are working correctly.
        If an API fails validation, attempts to auto-heal the script.

        Returns:
            Dict with health check results and healing status
        """
        if not self.api_monitor_enabled:
            return {'skipped': True, 'reason': 'API monitor not enabled'}

        result = {
            'all_healthy': True,
            'healed': False,
            'healed_apis': [],
            'failed_apis': [],
            'checks': {}
        }

        # Only run for NBA (ESPN API)
        if self.config.sport != "NBA":
            return {'skipped': True, 'reason': 'Only runs for NBA'}

        try:
            # Check ESPN NBA APIs
            scoreboard_check = self.api_monitor.validate_espn_nba_scoreboard(test_date)
            result['checks']['espn_nba_scoreboard'] = {
                'valid': scoreboard_check.is_valid,
                'differences': scoreboard_check.differences
            }

            if not scoreboard_check.is_valid:
                result['all_healthy'] = False
                result['failed_apis'].append('espn_nba_scoreboard')

                # Attempt auto-heal
                print(f"   [WARN] ESPN Scoreboard API validation failed")
                print(f"         Attempting auto-heal...")

                heal_result = self.api_monitor.self_heal_api_script(
                    'espn_nba_scoreboard',
                    scoreboard_check,
                    self.config.project_root / "scripts" / "espn_nba_api.py"
                )

                if heal_result.success:
                    result['healed'] = True
                    result['healed_apis'].append('espn_nba_scoreboard')
                    print(f"   [OK] Auto-healed ESPN Scoreboard API")
                else:
                    print(f"   [FAIL] Auto-heal failed: {heal_result.fix_description[:100]}")

            # Check ESPN NBA Summary API
            if scoreboard_check.raw_response_sample and 'events' in scoreboard_check.raw_response_sample:
                events = scoreboard_check.raw_response_sample.get('events', [])
                if events:
                    game_id = events[0]['id']
                    summary_check = self.api_monitor.validate_espn_nba_summary(game_id)
                    result['checks']['espn_nba_summary'] = {
                        'valid': summary_check.is_valid,
                        'differences': summary_check.differences
                    }

                    if not summary_check.is_valid:
                        result['all_healthy'] = False
                        result['failed_apis'].append('espn_nba_summary')

                        # Attempt auto-heal
                        print(f"   [WARN] ESPN Summary API validation failed")
                        print(f"         Attempting auto-heal...")

                        heal_result = self.api_monitor.self_heal_api_script(
                            'espn_nba_summary',
                            summary_check,
                            self.config.project_root / "scripts" / "espn_nba_api.py"
                        )

                        if heal_result.success:
                            result['healed'] = True
                            result['healed_apis'].append('espn_nba_summary')
                            print(f"   [OK] Auto-healed ESPN Summary API")
                        else:
                            print(f"   [FAIL] Auto-heal failed: {heal_result.fix_description[:100]}")

            return result

        except Exception as e:
            error_msg = f"API health check error: {str(e)}"
            self._log_error(traceback.format_exc(), "API_HEALTH_CHECK_ERROR")
            return {
                'all_healthy': False,
                'healed': False,
                'error': error_msg
            }

    def _log_error(self, error_text: str, error_type: str):
        """Log error to file"""
        log_file = self.global_config.LOGS_DIR / f"orchestrator_errors_{self.config.sport.lower()}_{datetime.now().strftime('%Y%m%d')}.log"
        try:
            with open(log_file, 'a') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"[{error_type}] {datetime.now().isoformat()}\n")
                f.write(error_text)
                f.write(f"\n{'='*80}\n")
        except:
            pass

    # ========================================================================
    # PREDICTION DIRECTION SANITY CHECK
    # ========================================================================

    def check_prediction_direction_sanity(self, game_date: str) -> list:
        """
        After prediction generation, check that no competitive prop is >85% in one
        direction.  Competitive props = those where historical majority is <70%.

        Fires a Discord alert (sport channel) if any prop is lopsided so that a stat
        model bug is caught the same night it happens, not 30 days later.

        Returns list of warning strings (empty = all clear).
        Only runs for NHL and NBA — MLB props have different structure.
        """
        if self.config.sport not in ('NHL', 'NBA'):
            return []
        if not REQUESTS_AVAILABLE:
            return []

        # Lines that are EXPECTED to be extreme — skip to avoid false alerts
        KNOWN_EXTREME = {
            ('points', 1.5), ('points', 2.5),
            ('shots', 3.5), ('shots', 4.5),
            ('hits', 2.5), ('blocked_shots', 1.5),
        }

        try:
            conn = sqlite3.connect(str(self.config.db_path))
            rows = conn.execute("""
                SELECT prop_type, line,
                       COUNT(*) as n,
                       ROUND(AVG(CASE WHEN prediction='OVER' THEN 1.0 ELSE 0.0 END), 3) as over_pct
                FROM predictions
                WHERE game_date = ?
                GROUP BY prop_type, line
                HAVING n >= 10
                ORDER BY prop_type, line
            """, (game_date,)).fetchall()
            conn.close()
        except Exception as e:
            self._log_error(f"Direction sanity check DB error: {e}", "SANITY_CHECK")
            return []

        warnings = []
        for prop_type, line, n, over_pct in rows:
            if (prop_type, line) in KNOWN_EXTREME:
                continue
            under_pct = 1.0 - over_pct
            if over_pct > 0.85 or under_pct > 0.85:
                dominant = "OVER" if over_pct > 0.85 else "UNDER"
                dominant_pct = over_pct if dominant == "OVER" else under_pct
                msg = (f"[SANITY ALERT] {self.config.sport} {prop_type} {line}: "
                       f"{dominant_pct:.0%} predicted {dominant} ({n} predictions). "
                       f"Expected <85%. Possible stat model bug.")
                warnings.append(msg)
                print(f"   !! DIRECTION SANITY: {msg}")

        if warnings:
            webhook = getattr(self.config, 'discord_picks_webhook', '') or DISCORD_WEBHOOK_URL
            if webhook and 'YOUR_' not in webhook:
                text = "\n".join(warnings)
                text += "\nInvestigate before these reach users."
                try:
                    requests.post(webhook, json={"content": f"```{text}```"}, timeout=10)
                except Exception:
                    pass
        else:
            print(f"   Direction sanity: OK (no prop >85% in one direction)")

        return warnings

    # ========================================================================
    # WEEKLY ML SHADOW AUDIT
    # ========================================================================

    def run_weekly_ml_audit(self):
        """
        Weekly shadow audit of NHL ML models via PEGASUS/pipeline/nhl_ml_reader.py.
        Scheduled every Sunday after grading completes.
        Posts verdict + per-prop summary to Discord.
        Auto-sets USE_ML=False in generate_predictions_daily_V6.py if audit FAILS
        and the season is active (i.e. USE_ML is currently True).
        NHL only — extend when NBA ML is reactivated.
        """
        if self.config.sport != 'NHL':
            return

        print(f"\n[PEGASUS] WEEKLY NHL ML SHADOW AUDIT")

        pegasus_pipeline = self.global_config.ROOT / "PEGASUS" / "pipeline"
        if not pegasus_pipeline.exists():
            print(f"   [SKIP] PEGASUS pipeline dir not found: {pegasus_pipeline}")
            return

        try:
            import importlib.util, sys as _sys
            spec = importlib.util.spec_from_file_location(
                "nhl_ml_reader", pegasus_pipeline / "nhl_ml_reader.py"
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            results = mod.audit_nhl_models(lookback_days=14)
        except Exception as e:
            self._log_error(f"Weekly ML audit failed to run: {e}", "ML_AUDIT")
            print(f"   [ERROR] Audit exception: {e}")
            return

        summary = results.get('summary', {})
        verdict = "PASS" if summary.get('overall_pass') else "FAIL"
        n_pass  = summary.get('n_props_pass', 0)
        n_fail  = summary.get('n_props_fail', 0)
        rec     = summary.get('recommendation', '')

        lines = [
            f"[WEEKLY ML AUDIT] NHL -- {verdict}",
            f"Props: {n_pass} passing / {n_fail} failing",
            f"Action: {rec}",
        ]
        for prop_str in summary.get('failing_props', []):
            lines.append(f"  FAIL: {prop_str}")

        # Auto-disable ML if audit fails and USE_ML is currently True
        v6_path = self.global_config.ROOT / "nhl" / "scripts" / "generate_predictions_daily_V6.py"
        use_ml_active = False
        if v6_path.exists():
            content = v6_path.read_text(encoding='utf-8')
            use_ml_active = 'USE_ML = True' in content

        if verdict == "FAIL" and use_ml_active:
            try:
                new_content = content.replace('USE_ML = True', 'USE_ML = False')
                v6_path.write_text(new_content, encoding='utf-8')
                lines.append("!! AUTO-DISABLED ML: USE_ML set to False in V6. Re-enable after investigation.")
                print(f"   [AUTO-FIX] USE_ML set to False in generate_predictions_daily_V6.py")
            except Exception as e:
                lines.append(f"!! Audit FAIL but could not auto-disable ML: {e}")

        message = "\n".join(lines)
        print(f"   Verdict: {verdict} | {n_pass} pass / {n_fail} fail")

        webhook = getattr(self.config, 'discord_picks_webhook', '') or DISCORD_WEBHOOK_URL
        if webhook and 'YOUR_' not in webhook and REQUESTS_AVAILABLE:
            try:
                requests.post(webhook, json={"content": f"```{message}```"}, timeout=10)
            except Exception:
                pass

    # ========================================================================
    # DISCORD NOTIFICATIONS
    # ========================================================================

    def _send_discord_notification(self, message: str):
        """Send a message to Discord webhook"""
        if not DISCORD_WEBHOOK_URL or not REQUESTS_AVAILABLE:
            return False

        try:
            payload = {"content": message}
            response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            return response.status_code == 204
        except Exception as e:
            self._log_error(f"Discord notification failed: {e}", "DISCORD_ERROR")
            return False

    def _is_prizepicks_eligible(self, prop_type: str, line: float, prediction: str) -> bool:
        """
        Check if a prediction is eligible for PrizePicks betting.

        PrizePicks constraints (general rules - player/matchup dependent):

        NHL:
        - Points 0.5: OVER and UNDER allowed
        - Points 1.5: OVER only (can't bet UNDER 1.5 points)
        - Shots 1.5: OVER only
        - Shots 2.5: OVER and UNDER allowed
        - Shots 3.5: OVER only

        NBA:
        - Most lines allow both, but very low lines may be OVER only

        TODO: Build PrizePicks line ingestion script for accurate daily lines
        """
        prop_type = prop_type.lower()
        prediction = prediction.upper()

        if self.config.sport == "NHL":
            # Points constraints
            if prop_type == 'points':
                if line == 1.5 and prediction == 'UNDER':
                    return False  # Can't bet UNDER 1.5 points
            # Shots constraints
            elif prop_type == 'shots':
                if line == 1.5 and prediction == 'UNDER':
                    return False  # OVER only on 1.5 shots
                if line == 3.5 and prediction == 'UNDER':
                    return False  # OVER only on 3.5 shots

        elif self.config.sport == "NBA":
            # NBA generally more flexible, but filter very low unders
            if line <= 5.5 and prediction == 'UNDER':
                # Be cautious with very low UNDER bets
                pass  # Allow for now, revisit with PrizePicks data

        return True

    def _get_top_picks(self, date: str, n: int = 3) -> List[Dict]:
        """
        Get top N picks for a date that are eligible for PrizePicks.

        Criteria:
        - Must be PrizePicks eligible (filtered by line/prediction rules)
        - Highest probability predictions
        - Preference for UNDER (historically better hit rate)
        - Avoid duplicate players

        Returns list of dicts with pick details.

        NOTE: For accurate PrizePicks lines, a daily line ingestion script
        should be built to scrape/fetch actual available lines.
        """
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()

            # Get more predictions to filter through
            query = '''
                SELECT
                    player_name,
                    prop_type,
                    line,
                    prediction,
                    probability,
                    team,
                    opponent
                FROM predictions
                WHERE game_date = ?
                ORDER BY
                    CASE WHEN prediction = 'UNDER' THEN 0 ELSE 1 END,
                    probability DESC
                LIMIT ?
            '''

            cursor.execute(query, (date, n * 10))  # Get extra to filter
            rows = cursor.fetchall()
            conn.close()

            picks = []
            seen_players = set()

            for row in rows:
                player = row[0]
                prop_type = row[1]
                line = row[2]
                prediction = row[3]
                probability = row[4]

                # Skip if not PrizePicks eligible
                if not self._is_prizepicks_eligible(prop_type, line, prediction):
                    continue

                # Avoid duplicate players in top picks
                if player in seen_players:
                    continue
                seen_players.add(player)

                pick = {
                    'player': player,
                    'prop': prop_type,
                    'line': line,
                    'prediction': prediction,
                    'probability': probability,
                    'team': row[5] if len(row) > 5 else 'N/A',
                    'opponent': row[6] if len(row) > 6 else 'N/A',
                }

                picks.append(pick)
                if len(picks) >= n:
                    break

            return picks

        except Exception as e:
            self._log_error(f"Error getting top picks: {e}", "TOP_PICKS_ERROR")
            return []

    def _format_top_picks_message(self, picks: List[Dict]) -> str:
        """Format top picks for Discord message"""
        if not picks:
            return ""

        msg = "\n**TOP PICKS:**\n"
        for i, pick in enumerate(picks, 1):
            prob_pct = pick['probability'] * 100 if pick['probability'] <= 1 else pick['probability']
            msg += f"{i}. **{pick['player']}** ({pick['team']})\n"
            msg += f"   {pick['prop'].upper()} {pick['prediction']} {pick['line']} @ {prob_pct:.0f}%\n"
            msg += f"   vs {pick['opponent']}\n"

        return msg

    def send_prediction_notification(self, date: str, details: Dict):
        """Send Discord notification for prediction pipeline"""
        sport = self.config.sport
        emoji = self.config.emoji

        # Get prediction count
        count = details.get('verification', {}).get('count', 0)

        # Get ML readiness info
        ml = details.get('ml_readiness', {})
        min_prop = ml.get('min_prop_name', 'N/A')
        min_count = ml.get('min_prop_count', 0)
        target = ml.get('target_per_prop', 10000)

        # Get verification details
        verification = details.get('verification', {})
        unique_probs = verification.get('unique_probs', 0)

        message = f"""
{emoji} **{sport} PREDICTIONS - {date}**

**Generated:** {count} predictions
**Probability Variety:** {unique_probs} unique values
**ML Progress:** {min_count:,}/{target:,} ({min_prop})
"""

        self._send_discord_notification(message)

    def send_grading_notification(self, date: str, details: Dict):
        """Send Discord notification for grading pipeline"""
        sport = self.config.sport
        emoji = self.config.emoji

        metrics = details.get('metrics', {})
        total = metrics.get('total', 0)
        hits = metrics.get('hits', 0)
        overall = metrics.get('overall_accuracy', 0) * 100
        under = metrics.get('under_accuracy', 0) * 100
        over = metrics.get('over_accuracy', 0) * 100

        message = f"""
{emoji} **{sport} GRADING - {date}**

**Results:** {hits}/{total} ({overall:.1f}%)
**UNDER:** {under:.1f}%
**OVER:** {over:.1f}%
"""

        self._send_discord_notification(message)

    def _post_smart_picks_to_discord(self, game_date: str):
        """Post smart picks to sport-specific Discord channel after predictions"""
        try:
            # Check if webhook is configured (not the placeholder)
            webhook_url = getattr(self.config, 'discord_picks_webhook', '')
            if not webhook_url or 'YOUR_' in webhook_url:
                print(f"   [SKIP] Smart picks Discord not configured for {self.config.sport}")
                return

            # Import and run smart pick selector
            from smart_pick_selector import SmartPickSelector

            selector = SmartPickSelector(self.config.sport.lower())
            picks = selector.get_smart_picks(
                game_date=game_date,
                min_edge=5.0,
                min_prob=0.55,
                odds_types=['standard', 'goblin'],
                refresh_lines=True  # Fetch fresh PP lines
            )

            if not picks:
                print(f"   [INFO] No high-edge picks found for {game_date}")
                return

            # Generate Discord message
            message = selector.generate_discord_message(picks, game_date)

            # Post to sport-specific channel
            response = requests.post(
                webhook_url,
                json={"content": message},
                timeout=10
            )

            if response.status_code == 204:
                print(f"   [OK] Posted {len(picks)} smart picks to Discord!")
            else:
                print(f"   [WARN] Discord returned status {response.status_code}")

        except ImportError:
            print(f"   [SKIP] smart_pick_selector not available")
        except Exception as e:
            print(f"   [WARN] Failed to post smart picks: {e}")

    def _fetch_top_picks(self, today: str, direction: str = None) -> list:
        """
        Fetch top 20 picks for today, sport-aware.

        NBA: individual f_* columns (f_l5_success_rate, f_current_streak, etc.)
        NHL: features stored as JSON blob (success_rate_l5, current_streak)

        Args:
            today: Date string YYYY-MM-DD
            direction: Optional 'OVER' or 'UNDER' to filter to one direction only.
                       None returns the best pick per player regardless of direction.

        Returns list of dicts with keys: player, team, opp, prop, line,
        direction, prob, ha_str, l5_rate, streak
        """
        conn = sqlite3.connect(str(self.config.db_path))
        cursor = conn.cursor()

        if self.config.sport == "NBA":
            # NBA has individual feature columns — filter and sort in SQL
            dir_clause = f"AND prediction = '{direction}'" if direction else ""
            cursor.execute(f"""
                SELECT player_name, team, opponent, prop_type, line, prediction,
                       probability, home_away,
                       f_l5_success_rate, f_current_streak
                FROM predictions
                WHERE game_date = ?
                  AND f_insufficient_data = 0
                  AND f_games_played >= 5
                  AND probability BETWEEN 0.56 AND 0.95
                  {dir_clause}
                GROUP BY player_name
                HAVING probability = MAX(probability)
                ORDER BY
                    probability DESC,
                    f_l5_success_rate DESC,
                    ABS(f_current_streak) DESC
                LIMIT 20
            """, (today,))
            raw = cursor.fetchall()
            conn.close()

            picks = []
            for player, team, opp, prop, line, pred_dir, prob, ha, l5_rate, streak in raw:
                ha_str = "vs" if ha == "H" else "@"
                picks.append(dict(player=player, team=team, opp=opp, prop=prop,
                                  line=line, direction=pred_dir, prob=prob,
                                  ha_str=ha_str, l5_rate=l5_rate or 0, streak=streak or 0))
            return picks

        else:
            # NHL: features stored in features_json — fetch candidate rows, parse in Python
            dir_clause = f"AND prediction = '{direction}'" if direction else ""
            cursor.execute(f"""
                SELECT player_name, team, opponent, prop_type, line, prediction,
                       probability, features_json
                FROM predictions
                WHERE game_date = ?
                  AND probability BETWEEN 0.56 AND 0.95
                  {dir_clause}
                ORDER BY probability DESC
            """, (today,))
            raw = cursor.fetchall()
            conn.close()

            # Best pick per player (highest prob in band), parse features from JSON
            seen_players = {}
            for player, team, opp, prop, line, pred_dir, prob, feat_json in raw:
                if player in seen_players:
                    continue  # already have best pick (rows are prob DESC)
                try:
                    features = json.loads(feat_json) if feat_json else {}
                except Exception:
                    features = {}

                games_played = features.get('games_played', 0)
                if games_played < 5:
                    continue  # not enough history

                l5_rate = features.get('success_rate_l5', 0) or 0
                streak = features.get('current_streak', 0) or 0
                is_home = features.get('is_home', 0)
                ha_str = "vs" if is_home else "@"

                seen_players[player] = dict(player=player, team=team, opp=opp,
                                            prop=prop, line=line, direction=pred_dir,
                                            prob=prob, ha_str=ha_str,
                                            l5_rate=l5_rate, streak=streak)

            # Sort: prob desc, then l5 desc, then streak desc; take top 20
            picks = sorted(seen_players.values(),
                           key=lambda p: (-p['prob'], -p['l5_rate'], -abs(p['streak'])))
            return picks[:20]

    def _format_pick_line(self, i: int, pick: dict) -> str:
        """Format a single pick as a Discord line."""
        conf = int(pick['prob'] * 100)
        arrow = "OVER" if pick['direction'] == "OVER" else "UNDER"
        # L5% is directional: OVER pick → OVER rate, UNDER pick → UNDER rate
        l5_pct = int((pick['l5_rate'] if pick['direction'] == "OVER"
                      else 1.0 - pick['l5_rate']) * 100)
        streak_abs = abs(pick['streak'])
        streak_str = f" {int(streak_abs)}x streak" if streak_abs >= 2 else ""
        prop_str = pick['prop'].upper().replace('_', ' ')
        return (
            f"`{i:2d}.` **{pick['player']}** ({pick['team']} {pick['ha_str']} {pick['opp']})  "
            f"{arrow} {pick['line']} {prop_str}  "
            f"— {conf}% model | L5: {l5_pct}%{streak_str}"
        )

    def _post_picks_to_discord(self, label: str, picks: list, today: str) -> bool:
        """Build and post a picks message. Returns True on success."""
        sport = self.config.sport
        pick_lines = [self._format_pick_line(i, p) for i, p in enumerate(picks, 1)]
        header = (
            f"**{sport} {label} — {today}**\n"
            f"Ranked by model confidence edge\n"
            f"{'='*44}\n"
        )
        message = header + "\n".join(pick_lines)
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=10
        )
        return response.status_code == 204

    def run_top_picks_notification(self):
        """
        Post top picks for today to Discord.

        NBA: one message — top 20 picks (all directions, best pick per player).
        NHL: two messages —
             1. top 20 overall picks (best per player, any direction)
             2. top 20 OVER picks (best OVER per player)

        Runs daily at 6:15 CST. Sends a Discord warning if no picks qualify.
        """
        if not REQUESTS_AVAILABLE or not DISCORD_WEBHOOK_URL:
            print(f"{self.config.emoji} [SKIP] Top picks: Discord webhook not configured")
            return

        today = datetime.now().strftime('%Y-%m-%d')

        try:
            # --- Top 20 all directions ---
            picks = self._fetch_top_picks(today)

            if not picks:
                print(f"{self.config.emoji} [WARN] Top picks: no qualifying predictions for {today}")
                self._send_discord_alert(
                    f"{self.config.emoji} NO PICKS — {today}",
                    f"Prediction pipeline ran but no picks passed the confidence filter "
                    f"(prob 0.56-0.95, games_played >= 5).\n"
                    f"Check if predictions exist: run `python {self.config.prediction_script} {today}`"
                )
                return

            ok = self._post_picks_to_discord("TOP 20 PICKS", picks, today)
            if ok:
                print(f"{self.config.emoji} [OK] Posted top {len(picks)} picks to Discord")
            else:
                print(f"{self.config.emoji} [WARN] Discord post returned non-204")

            # --- NHL only: additional top 20 OVERs message ---
            if self.config.sport == "NHL":
                over_picks = self._fetch_top_picks(today, direction="OVER")
                if over_picks:
                    ok2 = self._post_picks_to_discord("TOP 20 OVERS", over_picks, today)
                    if ok2:
                        print(f"{self.config.emoji} [OK] Posted top {len(over_picks)} OVER picks to Discord")
                    else:
                        print(f"{self.config.emoji} [WARN] OVER picks Discord post returned non-204")
                else:
                    print(f"{self.config.emoji} [INFO] No NHL OVER picks in confidence band for {today}")

        except Exception as e:
            print(f"{self.config.emoji} [WARN] Top picks notification failed: {e}")

    def _send_discord_alert(self, title: str, body: str):
        """Send a plain-text alert to Discord. Used for pipeline failures and warnings."""
        if not REQUESTS_AVAILABLE or not DISCORD_WEBHOOK_URL:
            return
        try:
            message = f"**{title}**\n{body}"
            requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        except Exception:
            pass  # Never let an alert crash the orchestrator

    def _load_state(self) -> Dict:
        """Load orchestrator state from file"""
        if self.global_config.STATE_FILE.exists():
            try:
                with open(self.global_config.STATE_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_state(self):
        """Save orchestrator state to file"""
        try:
            with open(self.global_config.STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except:
            pass

    # ========================================================================
    # PRIZEPICKS INTEGRATION
    # ========================================================================

    def run_prizepicks_ingestion(self) -> Dict:
        """
        Fetch current PrizePicks lines for this sport.

        Should run before prediction generation to have accurate lines.

        Returns:
            Dict with ingestion results
        """
        if not PRIZEPICKS_AVAILABLE:
            print(f"{self.config.emoji} PrizePicks integration not available")
            return {'success': False, 'error': 'Module not installed'}

        # NBA: skip ingestion when no games scheduled
        if self.config.sport == "NBA" and NBA_SCHEDULE_AVAILABLE:
            target_date = datetime.now().strftime('%Y-%m-%d')
            has_games, game_count = nba_has_games(target_date)
            if not has_games:
                print(f"\n{self.config.emoji} [SKIP] No NBA games on {target_date} - skipping PrizePicks ingestion")
                return {'success': True, 'skipped_schedule': True, 'game_count': 0}

        # MLB: skip ingestion when outside regular season
        if self.config.sport == "MLB" and MLB_SCHEDULE_AVAILABLE:
            target_date = datetime.now().strftime('%Y-%m-%d')
            if not mlb_has_games(target_date):
                print(f"\n{self.config.emoji} [SKIP] Outside MLB season on {target_date} - skipping PrizePicks ingestion")
                return {'success': True, 'skipped_schedule': True, 'game_count': 0}

        print(f"\n{self.config.emoji} PRIZEPICKS LINE INGESTION")
        print("=" * 60)

        try:
            ingestion = PrizePicksIngestion()
            results = ingestion.run_ingestion([self.config.sport])

            sport_result = results['sports'].get(self.config.sport, {})

            if sport_result.get('lines_saved', 0) > 0:
                print(f"[OK] Saved {sport_result['lines_saved']} {self.config.sport} lines")
                return {'success': True, **sport_result}
            else:
                print(f"[WARN] No lines available for {self.config.sport}")
                return {'success': False, 'error': 'No lines available'}

        except Exception as e:
            print(f"[ERROR] PrizePicks ingestion failed: {e}")
            self._log_error(traceback.format_exc(), "PRIZEPICKS_ERROR")
            return {'success': False, 'error': str(e)}

    def run_pp_sync(self, target_date: str = None) -> Dict:
        """
        Afternoon PP re-sync: fetch fresh PrizePicks lines and update smart picks in Supabase.

        Does NOT re-run the prediction script or write new rows to SQLite.
        Safe to run multiple times per day — all steps are upserts.

        Steps:
          1. Fetch fresh PrizePicks lines from API
          2. Re-sync existing SQLite predictions to Supabase (upsert)
          3. Re-match smart picks against new lines
          4. Correct odds_type labels (goblin/demon)
          5. Populate game_time fields

        Designed for the afternoon run when the full PP slate is available.
        """
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')

        print(f"\n[PP-SYNC] Afternoon PP re-sync for {self.config.sport} on {target_date}")

        # Step 1: fetch fresh lines
        ingest_result = self.run_prizepicks_ingestion()
        if not ingest_result.get('success'):
            print(f"[PP-SYNC] Line fetch failed — aborting sync")
            return {'success': False, 'error': 'PP ingestion failed'}

        # Step 1b: NHL hits/blocked_shots prediction refresh.
        # PP posts hits/blocked_shots lines several hours after the morning prediction run
        # (hits ~1 PM, blocked_shots ~5 PM CST) so the 4 AM predictions were generated
        # without those lines — resulting in wrong players (roster fallback instead of PP players).
        # Now that fresh lines are available, re-run V6 --force to regenerate predictions
        # for the correct PP-targeted players (physical grinders for hits, D-men for blocks).
        if self.config.sport == 'NHL' and hasattr(self.config, 'prediction_script'):
            try:
                pp_db = Path(__file__).parent / 'shared' / 'prizepicks_lines.db'
                hb_count = 0
                if pp_db.exists():
                    import sqlite3 as _sqlite3
                    _conn = _sqlite3.connect(str(pp_db))
                    hb_count = _conn.execute(
                        "SELECT COUNT(*) FROM prizepicks_lines "
                        "WHERE league='NHL' AND prop_type IN ('hits','blocked_shots') "
                        "AND fetch_date=?", (target_date,)
                    ).fetchone()[0]
                    _conn.close()
                if hb_count > 0:
                    print(f"[PP-SYNC] NHL hits/blocked_shots lines available ({hb_count} rows) — "
                          f"refreshing predictions with --force to pick up correct PP players")
                    refresh_result = self._run_script(self.config.prediction_script, [target_date, '--force'])
                    if refresh_result.get('success'):
                        print(f"[PP-SYNC] Prediction refresh complete")
                    else:
                        print(f"[PP-SYNC] Prediction refresh failed (non-fatal): "
                              f"{refresh_result.get('error', '')[:200]}")
                else:
                    print(f"[PP-SYNC] No NHL hits/blocked_shots lines yet — skipping prediction refresh")
            except Exception as _hb_err:
                print(f"[PP-SYNC] Hits/blocks refresh check failed (non-fatal): {_hb_err}")

        if not SUPABASE_SYNC_AVAILABLE:
            print(f"[PP-SYNC] Supabase not available — lines fetched but not synced")
            return {'success': True, 'note': 'lines fetched, supabase unavailable'}

        try:
            syncer = SupabaseSync()

            # Step 2: upsert existing predictions (safe to repeat, no new SQLite rows)
            sync_result = syncer.sync_predictions(self.config.sport.lower(), target_date)

            # Step 3: re-match smart picks against fresh lines
            smart_sync = syncer.sync_smart_picks(self.config.sport.lower(), target_date)

            # Step 4: correct goblin/demon odds_type labels
            odds_sync = syncer.sync_odds_types(self.config.sport.lower(), target_date)

            # Step 5: refresh game_time fields
            time_sync = syncer.sync_game_times(self.config.sport.lower(), target_date)

            print(f"[PP-SYNC] Complete: {sync_result.get('synced', 0)} predictions, "
                  f"{smart_sync.get('synced', 0)} smart picks, "
                  f"{odds_sync.get('updated', 0)} odds corrections, "
                  f"{time_sync.get('updated', 0)} game times")

            # Turso redundant sync (non-blocking)
            if TURSO_SYNC_AVAILABLE:
                try:
                    asyncio.run(_turso_sync_predictions(self.config.sport.lower(), target_date))
                    asyncio.run(_turso_sync_smart_picks(self.config.sport.lower(), target_date))
                except Exception as te:
                    print(f"[TURSO ERROR] pp-sync Turso failed (non-fatal): {te}")

            return {
                'success': True,
                'predictions': sync_result.get('synced', 0),
                'smart_picks': smart_sync.get('synced', 0),
                'odds_corrections': odds_sync.get('updated', 0),
                'game_times': time_sync.get('updated', 0),
            }

        except Exception as e:
            print(f"[PP-SYNC ERROR] {e}")
            self._log_error(traceback.format_exc(), "PP_SYNC_ERROR")
            return {'success': False, 'error': str(e)}

    def get_prizepicks_filtered_picks(self, date: str, n: int = 5) -> List[Dict]:
        """
        Get top picks that are actually available on PrizePicks.

        Filters predictions against actual PrizePicks lines.

        Args:
            date: Game date
            n: Number of picks to return

        Returns:
            List of picks with PrizePicks line confirmation
        """
        if not PRIZEPICKS_AVAILABLE:
            # Fall back to standard picks
            return self._get_top_picks(date, n)

        try:
            pp_db = PrizePicksDatabase(str(self.global_config.ROOT / "data" / "prizepicks_lines.db"))

            # Get our predictions
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()

            cursor.execute('''
                SELECT player_name, prop_type, line, prediction, probability, team, opponent
                FROM predictions
                WHERE game_date = ?
                ORDER BY
                    CASE WHEN prediction = 'UNDER' THEN 0 ELSE 1 END,
                    probability DESC
                LIMIT ?
            ''', (date, n * 20))  # Get extra to filter

            rows = cursor.fetchall()
            conn.close()

            picks = []
            seen_players = set()

            for row in rows:
                player = row[0]
                prop_type = row[1]
                our_line = row[2]
                prediction = row[3]
                probability = row[4]

                # Skip duplicate players
                if player in seen_players:
                    continue

                # Check PrizePicks eligibility first
                if not self._is_prizepicks_eligible(prop_type, our_line, prediction):
                    continue

                # Check if line is available on PrizePicks
                pp_line = pp_db.get_player_line(player, prop_type, date)

                if pp_line:
                    # Line available - check if it matches our line
                    line_match = abs(pp_line['line'] - our_line) < 0.5

                    pick = {
                        'player': player,
                        'prop': prop_type,
                        'line': our_line,
                        'prediction': prediction,
                        'probability': probability,
                        'team': row[5] if len(row) > 5 else 'N/A',
                        'opponent': row[6] if len(row) > 6 else 'N/A',
                        'pp_available': True,
                        'pp_line': pp_line['line'],
                        'line_match': line_match,
                    }

                    seen_players.add(player)
                    picks.append(pick)

                    if len(picks) >= n:
                        break

            return picks

        except Exception as e:
            print(f"[WARN] PrizePicks filtering failed: {e}")
            return self._get_top_picks(date, n)

    # ========================================================================
    # ML TRAINING INTEGRATION
    # ========================================================================

    def check_ml_training_readiness(self) -> Dict:
        """
        Check if we're ready to train ML models.

        Returns dict with readiness status for each prop/line.
        """
        readiness = {
            'sport': self.config.sport,
            'ready_props': [],
            'not_ready_props': [],
            'overall_ready': False
        }

        conn = sqlite3.connect(str(self.config.db_path))
        cursor = conn.cursor()

        for prop_type, lines in self.config.prop_lines.items():
            for line in lines:
                # Count graded predictions
                cursor.execute('''
                    SELECT COUNT(*)
                    FROM predictions p
                    JOIN prediction_outcomes po ON p.id = po.prediction_id
                    WHERE p.prop_type = ? AND p.line = ?
                ''', (prop_type, line))

                count = cursor.fetchone()[0]
                target = self.config.ml_training_target_per_prop

                prop_key = f"{prop_type}_{line}"

                if count >= target:
                    readiness['ready_props'].append({
                        'prop': prop_key,
                        'count': count,
                        'target': target
                    })
                else:
                    readiness['not_ready_props'].append({
                        'prop': prop_key,
                        'count': count,
                        'target': target,
                        'needed': target - count
                    })

        conn.close()

        # Overall ready if all props are ready
        readiness['overall_ready'] = len(readiness['not_ready_props']) == 0

        return readiness

    def trigger_ml_training(self, prop_type: str = None, line: float = None) -> Dict:
        """
        Trigger ML model training.

        Args:
            prop_type: Specific prop type to train (or None for all ready)
            line: Specific line to train (or None for all ready)

        Returns:
            Training results
        """
        if not ML_AVAILABLE:
            return {'success': False, 'error': 'ML modules not available'}

        print(f"\n{self.config.emoji} ML TRAINING TRIGGER")
        print("=" * 60)

        readiness = self.check_ml_training_readiness()

        if prop_type and line:
            # Train specific model
            props_to_train = [{'prop': f"{prop_type}_{line}"}]
        elif readiness['overall_ready']:
            # Train all ready props
            props_to_train = readiness['ready_props']
        else:
            print("[WARN] Not all props ready for training")
            print("Ready props:", [p['prop'] for p in readiness['ready_props']])
            print("Not ready:", [p['prop'] for p in readiness['not_ready_props']])

            # Train only ready props
            props_to_train = readiness['ready_props']

        if not props_to_train:
            return {'success': False, 'error': 'No props ready for training'}

        results = []

        for prop_info in props_to_train:
            prop_parts = prop_info['prop'].split('_')
            p_type = prop_parts[0]
            p_line = float(prop_parts[1])

            print(f"\nTraining: {self.config.sport} {p_type} @ {p_line}")

            try:
                # Run training script
                result = subprocess.run(
                    [
                        sys.executable,
                        str(self.global_config.ROOT / "ml_training" / "train_models.py"),
                        '--sport', self.config.sport.lower(),
                        '--prop', p_type,
                        '--line', str(p_line)
                    ],
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                if result.returncode == 0:
                    results.append({
                        'prop': prop_info['prop'],
                        'success': True,
                        'output': result.stdout[-500:] if result.stdout else ''
                    })
                    print(f"   [OK] Training complete")
                else:
                    results.append({
                        'prop': prop_info['prop'],
                        'success': False,
                        'error': result.stderr[-500:] if result.stderr else 'Unknown error'
                    })
                    print(f"   [FAIL] Training failed")

            except Exception as e:
                results.append({
                    'prop': prop_info['prop'],
                    'success': False,
                    'error': str(e)
                })

        success_count = sum(1 for r in results if r['success'])
        print(f"\n[SUMMARY] Trained {success_count}/{len(results)} models")

        # Send Discord notification
        self._send_ml_training_notification(results)

        return {
            'success': success_count > 0,
            'results': results,
            'total': len(results),
            'successful': success_count
        }

    def _send_ml_training_notification(self, results: List[Dict]):
        """Send Discord notification for ML training results (on-demand / manual trigger)."""
        sport = self.config.sport
        emoji = self.config.emoji
        success_count = sum(1 for r in results if r['success'])
        today = datetime.now().strftime('%a %b %-d')

        message = f"{emoji} **{sport} ML TRAINING — {today}**\n\n"
        message += f"**{success_count}/{len(results)} models trained**\n"
        for r in results:
            status = "OK" if r['success'] else "FAIL"
            message += f"  [{status}] {r['prop']}\n"

        self._send_discord_notification(message)

    # ── Weekly auto-retrain ────────────────────────────────────────────────────

    def _get_last_train_date(self) -> Optional[str]:
        """Return YYYY-MM-DD of the most recently trained model in the registry."""
        registry = (self.global_config.ROOT / "ml_training" / "model_registry"
                    / self.config.sport.lower())
        if not registry.exists():
            return None
        latest_date = None
        for prop_dir in registry.iterdir():
            latest_file = prop_dir / "latest.txt"
            if not latest_file.exists():
                continue
            version = latest_file.read_text().strip()
            meta_path = prop_dir / version / "metadata.json"
            if not meta_path.exists():
                continue
            trained_at = json.loads(meta_path.read_text()).get("trained_at", "")[:10]
            if trained_at > (latest_date or ""):
                latest_date = trained_at
        return latest_date

    def _count_new_predictions_since(self, date_str: str) -> int:
        """Count predictions with game_date > date_str in the sport's DB."""
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM predictions WHERE game_date > ?", (date_str,))
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def run_weekly_ml_retrain(self):
        """
        Weekly ML retrain — runs every Sunday before grading.
        Skips if fewer than MIN_NEW new predictions exist since the last train.
        Threshold is sport-specific (MLB has fewer games per season than NBA/NHL).
        Sends a snug Discord notification with per-model accuracy deltas.
        
        STRATEGIC FREEZE (2026-04-11):
        NBA and NHL retraining is frozen for the remainder of the season
        to avoid late-season variance and tanking noise.
        """
        sport = self.config.sport
        emoji = self.config.emoji
        
        if sport in ['nba', 'nhl']:
            print(f"\n{emoji} [FREEZE] {sport.upper()} retraining is frozen for the remainder of the season.")
            return

        # Use sport-specific threshold if configured, otherwise fall back to 500
        MIN_NEW = getattr(self.config, 'ml_training_min_new_preds', 500)

        print(f"\n{emoji} WEEKLY ML RETRAIN CHECK — {sport}")

        last_train = self._get_last_train_date()
        if last_train is None:
            print("   No existing models found — skipping auto-retrain")
            return

        new_count = self._count_new_predictions_since(last_train)
        print(f"   Last trained: {last_train}  |  New predictions: {new_count:,}")

        if new_count < MIN_NEW:
            print(f"   [SKIP] Need {MIN_NEW:,} new predictions, only have {new_count:,}")
            return

        print(f"   [GO] Retraining all {sport} models ({new_count:,} new predictions)...")

        try:
            result = subprocess.run(
                [sys.executable,
                 str(self.global_config.ROOT / "ml_training" / "train_models.py"),
                 "--sport", self.config.sport.lower(), "--all"],
                capture_output=True, text=True, timeout=1800
            )
            success = result.returncode == 0
            if not success:
                self._log_error(f"Weekly retrain failed:\n{result.stderr[-1000:]}", "ML_RETRAIN")
        except Exception as e:
            success = False
            self._log_error(f"Weekly retrain exception: {e}", "ML_RETRAIN")

        self._send_weekly_retrain_notification(new_count, last_train, success)

    def _send_weekly_retrain_notification(self, new_count: int, last_train: str, success: bool):
        """Discord notification for the weekly retrain — shows per-model accuracy deltas."""
        sport = self.config.sport
        emoji = self.config.emoji
        today = datetime.now().strftime("%a %b %-d")

        if not success:
            msg = (f"{emoji} **{sport} ML RETRAIN FAILED — {today}**\n"
                   f"Check `logs/orchestrator_errors_{sport.lower()}_{datetime.now().strftime('%Y%m%d')}.log`")
            self._send_discord_notification(msg)
            return

        # Read updated model stats and compare with previous versions
        registry = (self.global_config.ROOT / "ml_training" / "model_registry"
                    / sport.lower())
        today_tag = datetime.now().strftime("%Y%m%d")  # e.g. "20260309"

        updated, deltas = [], []
        for prop_dir in sorted(registry.iterdir()):
            latest_file = prop_dir / "latest.txt"
            if not latest_file.exists():
                continue
            latest = latest_file.read_text().strip()
            if today_tag not in latest:
                continue  # Not updated this run
            meta_path = prop_dir / latest / "metadata.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            new_acc = meta["test_accuracy"]

            # Find previous version's accuracy
            versions = sorted(
                [d.name for d in prop_dir.iterdir() if d.is_dir() and d.name.startswith("v")],
                reverse=True
            )
            prev_acc = None
            for v in versions:
                if v == latest:
                    continue
                prev_meta = prop_dir / v / "metadata.json"
                if prev_meta.exists():
                    prev_acc = json.loads(prev_meta.read_text()).get("test_accuracy")
                    break

            delta = (new_acc - prev_acc) if prev_acc is not None else None
            updated.append((prop_dir.name, new_acc, delta))
            if delta is not None:
                deltas.append(delta)

        total = len(updated)
        avg_delta = sum(deltas) / len(deltas) if deltas else None
        avg_str = (f" | avg {'+' if avg_delta >= 0 else ''}{avg_delta * 100:.1f}% acc"
                   if avg_delta is not None else "")

        msg = (f"{emoji} **{sport} ML RETRAIN — {today}**\n\n"
               f"**{total} models updated** | {new_count:,} new preds since {last_train}{avg_str}\n")

        if updated:
            by_delta = sorted(updated, key=lambda x: (x[2] or 0), reverse=True)
            improved = [(n, a, d) for n, a, d in by_delta if d is not None and d > 0.001]
            degraded = [(n, a, d) for n, a, d in by_delta if d is not None and d < -0.001]

            if improved:
                msg += "\n**Top gains:**\n"
                for name, acc, d in improved[:3]:
                    msg += f"  {name}: {acc*100:.1f}% (+{d*100:.1f}%)\n"
            if degraded:
                msg += "\n**Degraded:**\n"
                for name, acc, d in degraded[:3]:
                    msg += f"  {name}: {acc*100:.1f}% ({d*100:.1f}%)\n"

        self._send_discord_notification(msg)

    def get_ml_predictions(self, date: str) -> Dict:
        """
        Get ML-enhanced predictions for a date.

        Uses trained ML models where available, falls back to statistical.

        Returns:
            Dict with ML prediction stats
        """
        if not ML_AVAILABLE:
            return {'ml_available': False, 'error': 'ML modules not available'}

        try:
            registry_dir = str(self.global_config.ROOT / "ml_training" / "model_registry")
            predictor = ProductionPredictor(registry_dir)

            # Check which models are available
            available_models = []
            for prop_type, lines in self.config.prop_lines.items():
                for line in lines:
                    if predictor.is_model_available(self.config.sport, prop_type, line):
                        stats = predictor.get_model_stats(self.config.sport, prop_type, line)
                        available_models.append({
                            'prop': f"{prop_type}_{line}",
                            'version': stats.get('version'),
                            'test_accuracy': stats.get('test_accuracy')
                        })

            return {
                'ml_available': len(available_models) > 0,
                'available_models': available_models,
                'total_props': sum(len(lines) for lines in self.config.prop_lines.values())
            }

        except Exception as e:
            return {'ml_available': False, 'error': str(e)}

    # ========================================================================
    # SCHEDULER INTERFACE
    # ========================================================================

    def schedule_tasks(self):
        """
        Set up scheduled tasks for this sport

        This configures when each operation runs:
        - Grading: At sport-specific grading time
        - PrizePicks: 30 min before predictions
        - Predictions: At sport-specific prediction time
        - Every hour: Health check
        """
        if not SCHEDULE_AVAILABLE:
            print("ERROR: 'schedule' package not installed. Cannot run continuous mode.")
            return False

        # Daily grading (first thing)
        schedule.every().day.at(self.config.grading_time).do(
            self.run_daily_grading
        )

        # Daily PrizePicks ingestion (early pass, before predictions)
        if PRIZEPICKS_AVAILABLE:
            schedule.every().day.at(self.config.prizepicks_time).do(
                self.run_prizepicks_ingestion
            )

        # MLB feature store + ML predictions (decoupled from stat model — own time slot)
        if self.config.sport == "MLB" and hasattr(self.config, 'feature_store_time'):
            schedule.every().day.at(self.config.feature_store_time).do(
                self.run_mlb_feature_store
            )

        # Daily prediction generation
        schedule.every().day.at(self.config.prediction_time).do(
            self.run_daily_prediction_pipeline
        )

        # Afternoon PP re-sync (full slate available by early afternoon)
        if PRIZEPICKS_AVAILABLE:
            schedule.every().day.at(self.config.pp_sync_time).do(
                self.run_pp_sync
            )

        # Evening PP re-sync (catches late line additions before primetime)
        if PRIZEPICKS_AVAILABLE and hasattr(self.config, 'pp_sync_time_evening'):
            schedule.every().day.at(self.config.pp_sync_time_evening).do(
                self.run_pp_sync
            )

        # Daily top 20 picks notification (after afternoon sync)
        schedule.every().day.at(self.config.top_picks_time).do(
            self.run_top_picks_notification
        )

        # Hourly health checks
        schedule.every(self.global_config.HEALTH_CHECK_INTERVAL_MINUTES).minutes.do(
            self.run_health_check
        )

        # Weekly ML retrain (Sunday only, before grading)
        schedule.every().sunday.at(self.config.retrain_time).do(
            self.run_weekly_ml_retrain
        )

        # Weekly ML shadow audit (NHL only — Sunday after grading, ~1h after retrain_time)
        if self.config.sport == 'NHL':
            audit_h, audit_m = divmod(
                int(self.config.retrain_time.split(':')[0]) * 60
                + int(self.config.retrain_time.split(':')[1]) + 60,
                60
            )
            audit_time = f"{audit_h:02d}:{audit_m:02d}"
            schedule.every().sunday.at(audit_time).do(self.run_weekly_ml_audit)

        # Daily team stats + Elo update (all sports — runs before game predictions)
        schedule.every().day.at(self.config.team_stats_time).do(
            self.run_team_stats_update
        )

        # Daily game predictions (all sports — after team stats update)
        if hasattr(self.config, 'game_prediction_time'):
            schedule.every().day.at(self.config.game_prediction_time).do(
                self.run_game_prediction_pipeline
            )

        # Daily game grading (all sports — grade yesterday's game predictions)
        if hasattr(self.config, 'game_grading_time'):
            schedule.every().day.at(self.config.game_grading_time).do(
                self.run_game_grading
            )

        # Daily NHL hits & blocks picks (NHL only — standalone Claude API call)
        if self.config.sport == "NHL" and hasattr(self.config, 'hits_blocks_time'):
            schedule.every().day.at(self.config.hits_blocks_time).do(
                self.run_nhl_hits_blocks
            )
            # Startup catch-up: if we're past the scheduled time and today's picks
            # are missing (e.g. orchestrator restarted after 11 AM), run immediately.
            self._catchup_hits_blocks()

        # Startup catch-up for the main prediction pipeline (P6):
        # If the orchestrator restarts after prediction_time and today's DB is empty, run now.
        self._catchup_main_pipeline()

        # Weekly SZLN ML refresh (MLB only — season-long lines change slowly)
        if self.config.sport == "MLB" and hasattr(self.config, 'szln_refresh_time'):
            schedule.every().monday.at(self.config.szln_refresh_time).do(
                self.run_szln_ml_refresh
            )

        print(f"{self.config.emoji} Scheduled {self.config.sport} tasks:")
        print(f"   Grading: Daily at {self.config.grading_time}")
        if PRIZEPICKS_AVAILABLE:
            print(f"   PrizePicks: Daily at {self.config.prizepicks_time}")
        print(f"   Predictions: Daily at {self.config.prediction_time}")
        print(f"   Top 20 picks: Daily at {self.config.top_picks_time}")
        if PRIZEPICKS_AVAILABLE and hasattr(self.config, 'pp_sync_time_evening'):
            print(f"   PP evening sync: Daily at {self.config.pp_sync_time_evening}")
        print(f"   Health checks: Every {self.global_config.HEALTH_CHECK_INTERVAL_MINUTES} minutes")
        print(f"   Team Stats: Daily at {self.config.team_stats_time}")
        if hasattr(self.config, 'game_prediction_time'):
            print(f"   Game Predictions: Daily at {self.config.game_prediction_time}")
        if hasattr(self.config, 'game_grading_time'):
            print(f"   Game Grading: Daily at {self.config.game_grading_time}")
        print(f"   ML retrain: Sundays at {self.config.retrain_time} (500+ new preds required)")
        if self.config.sport == 'NHL':
            _rh = int(self.config.retrain_time.split(':')[0])
            _rm = int(self.config.retrain_time.split(':')[1])
            _ah, _am = divmod(_rh * 60 + _rm + 60, 60)
            print(f"   ML shadow audit: Sundays at {_ah:02d}:{_am:02d} (PEGASUS audit, NHL only)")
        if self.config.sport == "NHL" and hasattr(self.config, 'hits_blocks_time'):
            print(f"   Hits & Blocks: Daily at {self.config.hits_blocks_time} (Claude API)")
        if self.config.sport == "MLB" and hasattr(self.config, 'szln_refresh_time'):
            print(f"   SZLN ML refresh: Mondays at {self.config.szln_refresh_time}")
        print()

        return True

    def run_forever(self):
        """
        Run orchestrator continuously

        This is the main loop that keeps the orchestrator running 24/7.
        It executes scheduled tasks and monitors for issues.
        """
        if not SCHEDULE_AVAILABLE:
            print("ERROR: 'schedule' package not installed. Run: pip install schedule")
            return

        print(f"{self.config.emoji} Starting {self.config.sport} orchestrator in continuous mode...")
        print("   Press Ctrl+C to stop")
        print()

        if not self.schedule_tasks():
            return

        # Catch-up: if game_prediction_time already passed today and no predictions exist, run now
        if hasattr(self.config, 'game_prediction_time') and self.config.game_prediction_time:
            now = datetime.now()
            sched_h, sched_m = map(int, self.config.game_prediction_time.split(':'))
            sched_dt = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
            today_str = now.strftime('%Y-%m-%d')
            if now > sched_dt:
                # Check if game predictions already exist for today
                try:
                    conn = sqlite3.connect(str(self.config.db_path))
                    count = conn.execute(
                        'SELECT count(*) FROM game_predictions WHERE game_date = ?', (today_str,)
                    ).fetchone()[0]
                    conn.close()
                    if count == 0:
                        print(f"{self.config.emoji} [CATCH-UP] Game prediction window passed "
                              f"({self.config.game_prediction_time}) with no predictions — running now...")
                        self.run_game_prediction_pipeline()
                except Exception as e:
                    print(f"{self.config.emoji} [CATCH-UP] Could not check game_predictions: {e}")

        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute

        except KeyboardInterrupt:
            print(f"\n{self.config.emoji} {self.config.sport} orchestrator stopped by user")
            self._save_state()

    # ── Full-Game Prediction Pipeline Methods ────────────────────────────────

    def run_team_stats_update(self) -> Dict:
        """
        Update team rolling stats and Elo ratings from game results.
        Runs daily before game predictions. All sports.
        """
        sport = self.config.sport.lower()
        print(f"\n[TEAM STATS] Updating {self.config.sport} team stats and Elo ratings...")

        results = {"success": True, "team_stats": False, "elo": False}

        # 1. Team stats collector
        try:
            sys.path.insert(0, str(self.config.project_root / "scripts"))
            from team_stats_collector import run as ts_run
            ts_run()
            results["team_stats"] = True
            print(f"[TEAM STATS] {self.config.sport} team stats updated")
        except Exception as e:
            print(f"[TEAM STATS] {self.config.sport} team stats failed: {e}")
            results["success"] = False
        finally:
            # Clean up sys.path
            try:
                sys.path.remove(str(self.config.project_root / "scripts"))
            except ValueError:
                pass

        # 2. Elo ratings update
        try:
            sys.path.insert(0, str(Path(__file__).parent / "shared"))
            from elo_engine import EloEngine
            elo = EloEngine(sport=sport)
            elo.process_games_from_db(str(self.config.db_path))
            elo.save()
            results["elo"] = True
            print(f"[ELO] {self.config.sport} Elo ratings updated ({elo.games_processed} games)")
        except Exception as e:
            print(f"[ELO] {self.config.sport} Elo update failed: {e}")
        finally:
            try:
                sys.path.remove(str(Path(__file__).parent / "shared"))
            except ValueError:
                pass

        return results

    def run_game_prediction_pipeline(self) -> Dict:
        """
        Generate full-game predictions (moneyline, spread, total).
        Runs daily after team stats update. Uses Elo + team stats + ML models.
        Scripts: {sport}/scripts/generate_game_predictions.py
        """
        sport = self.config.sport.lower()
        print(f"\n[GAME PRED] {self.config.sport} game prediction pipeline...")

        try:
            script_path = self.config.project_root / "scripts" / "generate_game_predictions.py"
            if not script_path.exists():
                print(f"[GAME PRED] Script not found: {script_path}")
                return {"success": False, "error": "script not found"}

            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True, text=True, timeout=300,
                cwd=str(self.config.project_root)
            )

            if result.returncode == 0:
                print(f"[GAME PRED] {self.config.sport} game predictions generated")
                return {"success": True}
            else:
                print(f"[GAME PRED] Failed: {result.stderr[:500]}")
                return {"success": False, "error": result.stderr[:500]}

        except Exception as e:
            print(f"[GAME PRED] Error: {e}")
            return {"success": False, "error": str(e)}

    def run_game_grading(self) -> Dict:
        """
        Grade yesterday's full-game predictions against final scores.
        Scripts: {sport}/scripts/grade_game_predictions.py
        """
        sport = self.config.sport.lower()
        print(f"\n[GAME GRADE] {self.config.sport} game grading pipeline...")

        try:
            script_path = self.config.project_root / "scripts" / "grade_game_predictions.py"
            if not script_path.exists():
                print(f"[GAME GRADE] Script not found: {script_path}")
                return {"success": False, "error": "script not found"}

            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True, text=True, timeout=300,
                cwd=str(self.config.project_root)
            )

            if result.returncode == 0:
                print(f"[GAME GRADE] {self.config.sport} game predictions graded")
                return {"success": True}
            else:
                print(f"[GAME GRADE] Failed: {result.stderr[:500]}")
                return {"success": False, "error": result.stderr[:500]}

        except Exception as e:
            print(f"[GAME GRADE] Error: {e}")
            return {"success": False, "error": str(e)}

    def _catchup_main_pipeline(self):
        """
        If the orchestrator starts after the scheduled prediction_time and today's
        prop predictions are missing (count=0 in SQLite), run the full prediction
        pipeline immediately so overnight downtime doesn't silently skip the day.

        Pattern mirrors _catchup_hits_blocks — check time, check DB, run if needed.
        """
        now = datetime.now()
        sched_h, sched_m = map(int, self.config.prediction_time.split(':'))
        sched_mins = sched_h * 60 + sched_m
        now_mins = now.hour * 60 + now.minute
        if now_mins < sched_mins:
            return  # haven't reached scheduled time yet — normal schedule will handle it

        today = now.strftime('%Y-%m-%d')
        try:
            conn = sqlite3.connect(str(self.config.db_path))
            count = conn.execute(
                'SELECT COUNT(*) FROM predictions WHERE game_date = ?', (today,)
            ).fetchone()[0]
            conn.close()
            if count > 0:
                return  # already ran today
        except Exception as e:
            print(f"{self.config.emoji} [CATCH-UP] Could not check predictions DB: {e}")
            return  # don't run blind if we can't verify

        print(f"{self.config.emoji} [CATCH-UP] Startup after prediction window "
              f"({self.config.prediction_time}) with 0 predictions for {today} — running now...")
        self.run_daily_prediction_pipeline()

    def _catchup_hits_blocks(self):
        """
        If the orchestrator starts after the hits_blocks_time (e.g. 11 AM) and
        today's picks haven't been generated yet, run them immediately so a late
        restart doesn't silently skip the day.
        """
        from datetime import datetime as _dt
        now = _dt.now()
        sched_h, sched_m = map(int, self.config.hits_blocks_time.split(":"))
        sched_mins = sched_h * 60 + sched_m
        now_mins = now.hour * 60 + now.minute
        if now_mins < sched_mins:
            return  # haven't reached scheduled time yet — normal schedule will handle it

        # Check if today's picks are already saved
        today = now.strftime("%Y-%m-%d")
        try:
            import sqlite3 as _sql
            db_path = self.root / "nhl" / "database" / "hits_blocks.db"
            if db_path.exists():
                conn = _sql.connect(str(db_path))
                row = conn.execute(
                    "SELECT 1 FROM daily_picks WHERE run_date = ? LIMIT 1", (today,)
                ).fetchone()
                conn.close()
                if row:
                    return  # already ran today
        except Exception:
            pass  # if we can't check, attempt the run anyway

        print(f"[H+B] Startup catch-up: past {self.config.hits_blocks_time} with no picks for {today} — running now")
        self.run_nhl_hits_blocks()

    def run_nhl_hits_blocks(self) -> Dict:
        """
        Generate NHL daily hits & blocked shots picks via Claude API.

        Standalone — no dependency on the main NHL prediction pipeline.
        Runs at 11am CST (after lineups post) for NHL only.
        Output saved to nhl/database/hits_blocks.db and surfaced in dashboard.
        """
        if self.config.sport != "NHL":
            return {"success": True, "skipped": True, "reason": "non-nhl sport"}

        print(f"\n[H+B] Generating NHL hits & blocks picks via Claude...")
        try:
            scripts_dir = self.root / "nhl" / "scripts"
            sys.path.insert(0, str(scripts_dir))
            from daily_hits_blocks import run as hb_run

            # Post to Discord if webhook is configured
            post_discord = bool(os.getenv("NHL_HITS_BLOCKS_WEBHOOK") or
                                os.getenv("DISCORD_WEBHOOK_URL"))

            result = hb_run(post_discord=post_discord)
            if result.get("no_games"):
                print("[H+B] No NHL games tonight — skipped")
            elif result.get("skipped"):
                print("[H+B] Already ran today — skipped (use --force to override)")
            else:
                n_tok = result.get("prompt_tokens", 0) + result.get("completion_tokens", 0)
                print(f"[H+B] Picks saved ({n_tok} tokens used)")

            # Always sync to Supabase so the dashboard is current — idempotent upsert,
            # safe to run whether picks were just generated or already existed today.
            if not result.get("no_games"):
                try:
                    sys.path.insert(0, str(self.root / "shared"))
                    from supabase_local_sync import sync_hits_blocks
                    sr = sync_hits_blocks(verbose=False)
                    print(f"[H+B] Supabase sync: {sr.get('synced', 0)} rows synced")
                except Exception as _se:
                    print(f"[H+B] Supabase sync skipped: {_se}")
            return result
        except ImportError as e:
            print(f"[H+B] daily_hits_blocks.py not available: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            import traceback as _tb
            print(f"[H+B ERROR] {e}")
            self._log_error(_tb.format_exc(), "HITS_BLOCKS_ERROR")
            return {"success": False, "error": str(e)}

    def run_szln_ml_refresh(self) -> Dict:
        """
        Refresh MLB Season-Long (SZLN) ML predictions.

        Only meaningful for MLB — fetches live PrizePicks SZLN lines and runs
        the career-stat ML model to produce OVER/UNDER probabilities. Results
        are saved to the season_prop_ml_picks table and surfaced in the dashboard.

        Scheduled: weekly (Monday 9am) for MLB only.
        Can also be triggered manually via --operation szln.
        """
        if self.config.sport != "MLB":
            print(f"[SZLN] SZLN ML refresh is MLB-only — skipping for {self.config.sport}")
            return {'success': True, 'skipped': True, 'reason': 'non-mlb sport'}

        print(f"\n[SZLN] Starting MLB SZLN ML refresh...")
        try:
            scripts_dir = self.root / "mlb" / "scripts"
            sys.path.insert(0, str(scripts_dir))
            from season_props_ml import run_szln_predictions
            result = run_szln_predictions()
            n_picks = result.get('saved', 0)
            n_lines = result.get('lines_fetched', 0)
            print(f"[SZLN] Complete — {n_lines} lines fetched, {n_picks} picks saved")
            # Push to Supabase so Streamlit Cloud dashboard sees updated SZLN picks
            try:
                sys.path.insert(0, str(self.root / "shared"))
                from supabase_local_sync import sync_szln_picks, sync_season_projections
                r1 = sync_szln_picks(verbose=False)
                r2 = sync_season_projections(verbose=False)
                print(f"[SZLN] Supabase sync: {r1.get('synced', 0)} SZLN picks, "
                      f"{r2.get('synced', 0)} season projections synced")
            except Exception as _se:
                print(f"[SZLN] Supabase sync skipped: {_se}")
            return {'success': True, 'picks_saved': n_picks, 'lines_fetched': n_lines}
        except ImportError as e:
            print(f"[SZLN] season_props_ml.py not available: {e}")
            return {'success': False, 'error': str(e)}
        except Exception as e:
            import traceback as _tb
            print(f"[SZLN ERROR] {e}")
            self._log_error(_tb.format_exc(), "SZLN_ERROR")
            return {'success': False, 'error': str(e)}

    def run_once(self, operation: str = 'all'):
        """
        Run specific operation once (for testing/manual execution)

        Args:
            operation: 'prediction', 'grading', 'health', 'prizepicks',
                       'ml-check', 'ml-train', 'pp-sync', 'szln',
                       'team-stats', 'game-prediction', 'game-grading', 'game-all',
                       'hits-blocks', or 'all'
        """
        if operation in ['prizepicks', 'all']:
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} PrizePicks Ingestion")
            print("="*80)
            result = self.run_prizepicks_ingestion()
            print(f"\nResult: {'SUCCESS' if result.get('success') else 'FAILED'}")

        if operation in ['prediction', 'all']:
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} Prediction Pipeline")
            print("="*80)
            result = self.run_daily_prediction_pipeline()
            print(f"\nResult: {'SUCCESS' if result.success else 'FAILED'}")

        if operation in ['grading', 'all']:
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} Grading Pipeline")
            print("="*80)
            result = self.run_daily_grading()
            print(f"\nResult: {'SUCCESS' if result.success else 'FAILED'}")

        if operation in ['health', 'all']:
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} Health Check")
            print("="*80)
            health = self.run_health_check()
            print(f"\nML Readiness: {health.ml_readiness_score:.1f}/100")

        if operation in ['ml-check', 'all']:
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} ML Training Readiness Check")
            print("="*80)
            readiness = self.check_ml_training_readiness()
            print(f"\nOverall Ready: {readiness['overall_ready']}")
            print(f"Ready Props: {len(readiness['ready_props'])}")
            print(f"Not Ready: {len(readiness['not_ready_props'])}")

            if readiness['not_ready_props']:
                print("\nProps needing more data:")
                for p in readiness['not_ready_props']:
                    print(f"   {p['prop']}: {p['count']}/{p['target']} ({p['needed']} needed)")

        if operation == 'ml-train':
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} ML Training")
            print("="*80)
            result = self.trigger_ml_training()
            print(f"\nResult: {result['successful']}/{result['total']} models trained")

        if operation == 'pp-sync':
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} PP Afternoon Re-Sync")
            print("="*80)
            result = self.run_pp_sync()
            print(f"\nResult: {'SUCCESS' if result.get('success') else 'FAILED'}")

        if operation in ['team-stats', 'game-all']:
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} Team Stats + Elo Update")
            print("="*80)
            result = self.run_team_stats_update()
            print(f"\nResult: Team stats={'OK' if result.get('team_stats') else 'SKIP'}, "
                  f"Elo={'OK' if result.get('elo') else 'SKIP'}")

        if operation in ['game-prediction', 'game-all', 'all']:
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} Game Prediction Pipeline")
            print("="*80)
            result = self.run_game_prediction_pipeline()
            print(f"\nResult: {'SUCCESS' if result.get('success') else 'FAILED'}")

        if operation in ['game-grading', 'game-all']:
            print("\n" + "="*80)
            print(f"{self.config.emoji} RUNNING: {self.config.sport} Game Grading Pipeline")
            print("="*80)
            result = self.run_game_grading()
            print(f"\nResult: {'SUCCESS' if result.get('success') else 'FAILED'}")

        if operation in ['hits-blocks']:
            if self.config.sport == "NHL":
                print("\n" + "="*80)
                print(f"{self.config.emoji} RUNNING: NHL Hits & Blocks Picks (Claude API)")
                print("="*80)
                result = self.run_nhl_hits_blocks()
                print(f"\nResult: {'SUCCESS' if result.get('success') else 'FAILED'}")

        if operation in ['szln', 'all']:
            if self.config.sport == "MLB":
                print("\n" + "="*80)
                print(f"{self.config.emoji} RUNNING: MLB SZLN Season-Long ML Predictions")
                print("="*80)
                result = self.run_szln_ml_refresh()
                print(f"\nResult: {'SUCCESS' if result.get('success') else 'FAILED'}")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def print_banner():
    """Print the orchestrator banner"""
    print()
    print("=" * 70)
    print("  SPORTS PREDICTION ORCHESTRATOR")
    print("  NHL, NBA & MLB Prediction System Manager")
    print("=" * 70)
    print()


def run_all_sports_continuous(sports: list):
    """
    Run multiple sports in continuous mode with a single scheduler.

    This combines all sport schedules into one event loop.
    """
    if not SCHEDULE_AVAILABLE:
        print("ERROR: 'schedule' package not installed. Run: pip install schedule")
        return

    print("=" * 70)
    print("  CONTINUOUS MODE - ALL SPORTS")
    print("=" * 70)
    print()

    orchestrators = {}

    # Initialize all orchestrators and set up their schedules
    for sport in sports:
        try:
            orchestrator = SportsOrchestrator(sport)
            orchestrators[sport] = orchestrator

            # Schedule tasks for this sport
            schedule.every().day.at(orchestrator.config.grading_time).do(
                orchestrator.run_daily_grading
            )

            if PRIZEPICKS_AVAILABLE:
                schedule.every().day.at(orchestrator.config.prizepicks_time).do(
                    orchestrator.run_prizepicks_ingestion
                )

            schedule.every().day.at(orchestrator.config.prediction_time).do(
                orchestrator.run_daily_prediction_pipeline
            )

            if PRIZEPICKS_AVAILABLE:
                schedule.every().day.at(orchestrator.config.pp_sync_time).do(
                    orchestrator.run_pp_sync
                )

            if PRIZEPICKS_AVAILABLE and hasattr(orchestrator.config, 'pp_sync_time_evening'):
                schedule.every().day.at(orchestrator.config.pp_sync_time_evening).do(
                    orchestrator.run_pp_sync
                )

            # MLB feature store + ML predictions (decoupled — must be registered here
            # because run_all_sports_continuous bypasses schedule_tasks())
            if (sport.upper() == "MLB"
                    and hasattr(orchestrator.config, 'feature_store_time')):
                schedule.every().day.at(orchestrator.config.feature_store_time).do(
                    orchestrator.run_mlb_feature_store
                )

            # Game predictions (moneyline/spread/total for dashboard Game Lines tab)
            if (hasattr(orchestrator.config, 'game_prediction_time')
                    and orchestrator.config.game_prediction_time):
                schedule.every().day.at(orchestrator.config.game_prediction_time).do(
                    orchestrator.run_game_prediction_pipeline
                )

            if (hasattr(orchestrator.config, 'game_grading_time')
                    and orchestrator.config.game_grading_time):
                schedule.every().day.at(orchestrator.config.game_grading_time).do(
                    orchestrator.run_game_grading
                )

            print(f"{orchestrator.config.emoji} {sport.upper()} scheduled:")
            print(f"   Grading: {orchestrator.config.grading_time}")
            if PRIZEPICKS_AVAILABLE:
                print(f"   PP early fetch: {orchestrator.config.prizepicks_time}")
            print(f"   Predictions: {orchestrator.config.prediction_time}")
            if sport.upper() == "MLB" and hasattr(orchestrator.config, 'feature_store_time'):
                print(f"   MLB feature store + ML: {orchestrator.config.feature_store_time}")
            if PRIZEPICKS_AVAILABLE:
                print(f"   PP afternoon sync: {orchestrator.config.pp_sync_time}")
            if PRIZEPICKS_AVAILABLE and hasattr(orchestrator.config, 'pp_sync_time_evening'):
                print(f"   PP evening sync:   {orchestrator.config.pp_sync_time_evening}")
            if (hasattr(orchestrator.config, 'game_prediction_time')
                    and orchestrator.config.game_prediction_time):
                print(f"   Game Predictions: {orchestrator.config.game_prediction_time}")
            print()

        except Exception as e:
            print(f"ERROR initializing {sport}: {e}")
            continue

    # Set up shared health checks (every 60 minutes)
    def run_all_health_checks():
        for sport, orch in orchestrators.items():
            orch.run_health_check()

    schedule.every(60).minutes.do(run_all_health_checks)
    print(f"Health checks: Every 60 minutes (all sports)")

    # Daily audit — runs at 09:00 AM after all sports have finished grading
    _audit_path = Path(__file__).parent / "daily_audit.py"
    if _audit_path.exists():
        def _run_daily_audit():
            subprocess.run(
                [sys.executable, str(_audit_path)],
                cwd=str(Path(__file__).parent),
            )
        schedule.every().day.at("09:00").do(_run_daily_audit)
        print("Daily audit: 09:00 AM (all sports DB health + Discord report)")
    else:
        print("NOTE: daily_audit.py not found — audit skipped")
    print()

    print("=" * 70)
    print("  SCHEDULER RUNNING - Press Ctrl+C to stop")
    print("=" * 70)
    print()

    # Catch-up: for each sport, if game_prediction_time already passed today
    # and no predictions exist yet, run immediately before entering the loop.
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    for sport, orchestrator in orchestrators.items():
        if not (hasattr(orchestrator.config, 'game_prediction_time')
                and orchestrator.config.game_prediction_time):
            continue
        try:
            sched_h, sched_m = map(int, orchestrator.config.game_prediction_time.split(':'))
            sched_dt = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
            if now > sched_dt:
                conn = sqlite3.connect(str(orchestrator.config.db_path))
                count = conn.execute(
                    'SELECT count(*) FROM game_predictions WHERE game_date = ?', (today_str,)
                ).fetchone()[0]
                conn.close()
                if count == 0:
                    print(f"{orchestrator.config.emoji} [CATCH-UP] Game predictions missing "
                          f"for {today_str} — running now...")
                    orchestrator.run_game_prediction_pipeline()
        except Exception as e:
            print(f"[CATCH-UP] {sport}: {e}")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        print("\nOrchestrator stopped by user")
        for orch in orchestrators.values():
            orch._save_state()


def main():
    """Main entry point for orchestrator"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Sports Prediction Orchestrator (NHL & NBA)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sports_orchestrator.py --sport nhl --mode test
  python sports_orchestrator.py --sport nba --mode test
  python sports_orchestrator.py --sport nhl --mode once --operation prediction
  python sports_orchestrator.py --sport nba --mode once --operation grading
  python sports_orchestrator.py --sport nhl --mode once --operation prizepicks
  python sports_orchestrator.py --sport nhl --mode once --operation ml-check
  python sports_orchestrator.py --sport nhl --mode once --operation ml-train
  python sports_orchestrator.py --sport nhl --mode continuous
  python sports_orchestrator.py --sport all --mode test
        """
    )
    parser.add_argument(
        '--sport',
        choices=['nhl', 'nba', 'mlb', 'golf', 'all'],
        required=True,
        help='Sport to manage (nhl, nba, mlb, golf, or all)'
    )
    parser.add_argument(
        '--mode',
        choices=['continuous', 'once', 'test'],
        default='test',
        help='Execution mode (default: test)'
    )
    parser.add_argument(
        '--operation',
        choices=['prediction', 'grading', 'health', 'prizepicks', 'pp-sync',
                 'ml-check', 'ml-train', 'hits-blocks', 'szln',
                 'team-stats', 'game-prediction', 'game-grading', 'game-all',
                 'all'],
        default='all',
        help='Operation to run for once/test modes (default: all)'
    )

    args = parser.parse_args()

    print_banner()

    # Determine which sports to run
    sports = ['nhl', 'nba', 'mlb', 'golf'] if args.sport == 'all' else [args.sport]

    # Special handling for continuous mode with multiple sports
    if args.mode == 'continuous' and len(sports) > 1:
        run_all_sports_continuous(sports)
        return

    for sport in sports:
        print(f"\n{'='*70}")
        print(f"  Processing: {sport.upper()}")
        print(f"{'='*70}")

        try:
            # Initialize orchestrator
            orchestrator = SportsOrchestrator(sport)

            if args.mode == 'continuous':
                # Run forever (production mode)
                orchestrator.run_forever()

            elif args.mode == 'once':
                # Run once (manual execution)
                orchestrator.run_once(args.operation)

            elif args.mode == 'test':
                # Test mode - just check health and ML readiness
                print(f"\n{'='*60}")
                print(f"TEST MODE - {sport.upper()}")
                print(f"{'='*60}\n")

                health = orchestrator.run_health_check()
                print()
                ml_readiness = orchestrator._assess_ml_readiness()

                print(f"\n{orchestrator.config.emoji} ML READINESS REPORT - {sport.upper()}:")
                print(f"   Total Predictions: {ml_readiness.total_predictions:,}")
                print(f"   Target per Prop/Line: {ml_readiness.target_per_prop:,}")
                print(f"   Bottleneck: {ml_readiness.min_prop_name} ({ml_readiness.min_prop_count:,})")
                print(f"   ML Readiness: {ml_readiness.readiness_percentage:.1f}%")

                # Show per-prop breakdown
                print(f"\n   Predictions by Prop/Line:")
                for prop_key, count in sorted(ml_readiness.predictions_per_prop.items()):
                    pct = (count / ml_readiness.target_per_prop) * 100
                    status = "OK" if count >= ml_readiness.target_per_prop else f"{ml_readiness.target_per_prop - count:,} needed"
                    print(f"      {prop_key}: {count:,} ({pct:.0f}%) - {status}")

                print(f"\n   Data Quality:")
                print(f"      Feature Completeness: {ml_readiness.feature_completeness:.1%}")
                print(f"      Opponent Features (14d): {ml_readiness.opponent_feature_rate:.1%}")
                print(f"      Probability Variety: {ml_readiness.unique_probabilities}")
                print(f"      Quality Score: {ml_readiness.data_quality_score:.1f}/100")

                if ml_readiness.blocking_issues:
                    print("\n   Blocking Issues:")
                    for issue in ml_readiness.blocking_issues:
                        for line in issue.split('\n'):
                            print(f"   - {line}")

                if ml_readiness.recommendations:
                    print("\n   Recommendations:")
                    for rec in ml_readiness.recommendations:
                        print(f"   - {rec}")

        except Exception as e:
            print(f"\nERROR initializing {sport.upper()} orchestrator: {str(e)}")
            traceback.print_exc()
            continue

    print(f"\n{'='*70}")
    print("  Orchestrator complete")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
