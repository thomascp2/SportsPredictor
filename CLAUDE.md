# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **dual-sport prediction system** for NHL and NBA prop bets. The system is currently in **data collection phase** (Learning Mode) building toward ML training with 10,000+ predictions per sport. Each sport operates independently with its own prediction pipeline, grading system, and database.

**Mission**: Build prediction juggernauts through systematic data collection, then train world-class ML models.

## Core Architecture

### Orchestrator Pattern (orchestrator.py)

The orchestrator is the **master controller** that manages both sports. It runs scheduled tasks, monitors health, and handles errors. Key operations:

- **Prediction Pipeline**: Fetch schedule → Generate predictions → Verify data quality
- **Grading Pipeline**: Grade yesterday's predictions → Calculate metrics → Check calibration
- **ML Readiness Tracking**: Monitor progress toward 10k predictions per prop/line combo

The orchestrator uses **sport-specific configurations** (SportConfig class) where NHL and NBA have different:
- Database paths
- Grading scripts
- Scheduled times (NHL: 2am/8am CST, NBA: 9am/10am CST)
- Prop types and lines (NHL: points/shots, NBA: 14 different prop types)

### Dual Database Architecture

Each sport has its own SQLite database with different schemas:

**NHL** (`nhl/database/nhl_predictions_v2.db`):
- More comprehensive schema with rolling stats, team stats, goalie stats
- Features stored as JSON in `predictions.features_json`
- Prediction column: `prediction` (OVER/UNDER)
- Grading column in outcomes: `predicted_outcome`

**NBA** (`nba/database/nba_predictions.db`):
- Simpler schema focused on core functionality
- Features stored as individual `f_*` columns
- Prediction column: `prediction` (OVER/UNDER)
- Grading column in outcomes: `prediction`

**Critical**: Always check which sport's database you're working with - column names differ!

### API Self-Healing System

The system includes **automatic API repair** using Claude (added Dec 2025). When external APIs change structure:

1. `api_health_monitor.py` validates API responses against known schemas
2. Detects structural changes (missing/extra keys in JSON)
3. Uses Claude API to analyze broken code and generate fixes
4. Creates backup → Applies fix → Validates it works
5. Integrated into NBA grading pipeline (Step 0/4)

See `API_SELF_HEALING_GUIDE.md` for details.

### Sport-Specific Scripts

Each sport (`nhl/` and `nba/` directories) contains:

- **`scripts/`**: All prediction and grading scripts
  - `generate_predictions_daily*.py`: Main prediction generation
  - `auto_grade*.py`: Grading yesterday's predictions
  - `*_config.py`: Sport-specific configuration (ALWAYS import from here)
  - Data fetchers, statistical models, feature engineering

- **`database/`**: SQLite database for that sport

- **`backups/`**: Automatic database backups created before grading/prediction runs

**Key Principle**: Sports share NO code except via `shared/` directory. This prevents cross-contamination.

## Common Commands

### Orchestrator Operations

```bash
# Run predictions for today
python orchestrator.py --sport nhl --mode once --operation prediction
python orchestrator.py --sport nba --mode once --operation prediction

# Grade yesterday's predictions
python orchestrator.py --sport nhl --mode once --operation grading
python orchestrator.py --sport nba --mode once --operation grading

# Full pipeline test (prediction + grading + health + ML check)
python orchestrator.py --sport nhl --mode once --operation all
python orchestrator.py --sport nba --mode test

# Continuous mode (production - runs scheduled tasks 24/7)
python orchestrator.py --sport all --mode continuous
```

### Direct Script Usage

When you need to run scripts for **specific dates** (orchestrator only grades "yesterday"):

```bash
# NHL prediction for specific date
cd nhl
python scripts/generate_predictions_daily_V5.py 2025-12-15 --force

# NHL grading for specific date
cd nhl
python scripts/v2_auto_grade_yesterday_v3_RELIABLE.py 2025-12-15

# NBA prediction for specific date
cd nba
python scripts/generate_predictions_daily.py 2025-12-15

# NBA grading for specific date
cd nba
python scripts/auto_grade_multi_api_FIXED.py 2025-12-15
```

### Database Operations

```bash
# Check NHL prediction counts
python -c "import sqlite3; conn = sqlite3.connect('nhl/database/nhl_predictions_v2.db'); cursor = conn.cursor(); cursor.execute('SELECT COUNT(*) FROM predictions'); print(f'NHL predictions: {cursor.fetchone()[0]:,}'); conn.close()"

# Check NBA grading status for date
python -c "import sqlite3; conn = sqlite3.connect('nba/database/nba_predictions.db'); cursor = conn.cursor(); cursor.execute('SELECT COUNT(*), SUM(CASE WHEN outcome=\"HIT\" THEN 1 ELSE 0 END) FROM prediction_outcomes WHERE game_date=\"2025-12-15\"'); row = cursor.fetchone(); print(f'Graded: {row[0]}, Hits: {row[1]}, Accuracy: {row[1]*100/row[0]:.1f}%' if row[0] > 0 else 'No grades'); conn.close()"

# View ML readiness for NHL (progress to 10k per prop)
python orchestrator.py --sport nhl --mode test
```

### API Health Monitoring

```bash
# Check all APIs
python test_api_monitor.py --check

# Manually heal broken API script
python test_api_monitor.py --heal nba/scripts/espn_nba_api.py --api espn_nba_summary
```

## Key Implementation Details

### ML Training Readiness

The system tracks progress toward **10,000 predictions per prop/line combination** before ML training:

- **NHL**: 5 prop/line combos (points: 0.5/1.5, shots: 1.5/2.5/3.5)
- **NBA**: 14 prop/line combos (points: 15.5/20.5/25.5, rebounds: 7.5/10.5, etc.)

**Bottleneck tracking**: ML readiness is based on the LOWEST count across all prop/line combos. Check with `orchestrator.py --mode test`.

### Grading Pipeline Critical Details

**NHL Grading**:
- Uses NHL official API: `api-web.nhle.com`
- Fetches game data by game_id from schedule
- Column name in predictions: `prediction`
- Column name in outcomes: `predicted_outcome` (note the difference!)
- Auto-creates database backup before grading

**NBA Grading**:
- Multi-API with fallback: ESPN (primary) → NBA Stats API (fallback)
- ESPN API changed structure Dec 2025: players now at `data['boxscore']['players']`
- Self-healing system detects and fixes API changes automatically
- Column name in both predictions and outcomes: `prediction`

### Feature Engineering

**NHL** uses JSON-stored features:
```python
features_json = {
    'f_last5_avg_points': 0.8,
    'opp_points_allowed_L5': 1.2,  # Opponent defensive stats
    ...
}
```

**NBA** uses individual columns:
```python
f_last5_avg_points = 0.8
f_opp_points_allowed_L5 = 1.2
```

**Important**: Opponent features (`opp_*`) are critical for ML training. Orchestrator monitors opponent feature rate in last 14 days.

### Configuration System

Each sport has a central config file that MUST be imported:

```python
# NHL scripts
from v2_config import DB_PATH, LEARNING_MODE, PROBABILITY_CAP

# NBA scripts
from nba_config import DB_PATH, LEARNING_MODE, CORE_PROPS
```

**Never hardcode paths or settings** - always use config.

### Error Handling & Logging

- Orchestrator logs errors to `logs/orchestrator_errors_{sport}_{date}.log`
- Claude analysis logs to `logs/claude_analysis_{sport}_{date}.log`
- Database backups to `{sport}/backups/` with timestamp
- API validation history to `data/api_schemas/validation_history.jsonl`

## Critical Workflows

### Adding a New Prop Type (NBA)

1. Add to `nba_config.py` CORE_PROPS dict
2. Update feature engineering in prediction script
3. Update `_get_stat_value()` in grading script to map prop to actual stat
4. Orchestrator will automatically track it for ML readiness

### Fixing a Broken Grading Script

1. Check recent logs: `logs/orchestrator_errors_{sport}_{date}.log`
2. Test grading script directly with specific date
3. If API issue, check `data/api_schemas/validation_history.jsonl`
4. For NBA APIs, self-healing may have already attempted a fix
5. Check backups directory for pre-error database state

### Preparing for ML Training

When a sport reaches 10k predictions per prop/line:

1. Verify readiness: `python orchestrator.py --sport {sport} --mode once --operation ml-check`
2. Check data quality (feature completeness, opponent features, probability variety)
3. Trigger training: `python orchestrator.py --sport {sport} --mode once --operation ml-train`
4. Models stored in `ml_training/model_registry/`

## Environment Variables

Required:
- `ANTHROPIC_API_KEY`: For Claude analysis and self-healing (strip newlines!)

Optional:
- `DISCORD_WEBHOOK_URL`: For notifications

## Database Schema Notes

**NHL predictions table** has these unique columns:
- `features_json`: TEXT (JSON blob of all features)
- `confidence_tier`: TEXT (T1-ELITE, T2-STRONG, T3-GOOD, T4-LEAN, T5-FADE)
- `expected_value`: REAL
- `reasoning`: TEXT

**NBA predictions table** has:
- Individual `f_*` columns for each feature (50+ columns)
- No confidence tier or reasoning columns
- Simpler structure for faster queries

**Both** have:
- `predictions` table: Generated predictions
- `prediction_outcomes` table: Graded results (outcome = HIT/MISS)
- `player_game_logs` table: Historical player performance data

## Performance Targets

**NHL**:
- UNDER: 70%+ accuracy (strong edge)
- OVER: 55%+ accuracy
- Current: 67.9% overall (74.4% UNDER, 54.6% OVER)

**NBA**:
- UNDER: 65%+ accuracy
- OVER: 55%+ accuracy
- Current: 80.0% overall (84.2% UNDER, 61.2% OVER)

## Windows-Specific Notes

This codebase runs on Windows (Git Bash environment):
- Use forward slashes in paths: `/c/Users/...`
- Some emoji characters cause encoding errors - use `[NBA]` instead of 🏀
- PowerShell commands differ from bash - prefer Git Bash

## What NOT to Do

- Don't manually edit databases - always use scripts
- Don't skip backups when modifying grading/prediction scripts
- Don't assume NHL and NBA have identical database schemas
- Don't commit API keys or sensitive data
- Don't run grading before games finish (check game status)
- Don't mix NHL and NBA code paths
