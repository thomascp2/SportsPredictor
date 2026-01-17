# Quick Start Guide

## Daily Workflow

### 1. Start the Orchestrator (runs 24/7)
```bash
python orchestrator.py --sport all --mode continuous
```

This handles:
- NHL grading at 2:00 AM CST
- NHL PrizePicks fetch at 7:30 AM CST
- NHL predictions at 8:00 AM CST
- NBA grading at 9:00 AM CST
- NBA PrizePicks fetch at 9:30 AM CST
- NBA predictions at 10:00 AM CST

### 2. View Today's Best Plays
```bash
# NHL Overs for parlays
python shared/edge_calculator.py --sport nhl --parlay --overs-only

# NBA Overs for parlays
python shared/edge_calculator.py --sport nba --parlay --overs-only
```

### 3. Manual Operations (if needed)
```bash
# Fetch fresh PrizePicks lines
python shared/prizepicks_client.py --sport nhl
python shared/prizepicks_client.py --sport nba

# Generate predictions for specific date
cd nhl && python scripts/generate_predictions_daily_V5.py 2026-01-17
cd nba && python scripts/generate_predictions_daily.py 2026-01-17

# Grade specific date
cd nhl && python scripts/v2_auto_grade_yesterday_v3_RELIABLE.py 2026-01-16
cd nba && python scripts/auto_grade_multi_api_FIXED.py 2026-01-16
```

## Monthly: Retrain ML Models
```bash
python ml_training/train_models.py --sport nhl --all
```

## Check System Health
```bash
python orchestrator.py --sport all --mode test
```

## Key Commands Reference

| Task | Command |
|------|---------|
| Start orchestrator | `python orchestrator.py --sport all --mode continuous` |
| NHL parlay picks | `python shared/edge_calculator.py --sport nhl --parlay --overs-only` |
| NBA parlay picks | `python shared/edge_calculator.py --sport nba --parlay --overs-only` |
| Fetch PP lines | `python shared/prizepicks_client.py --sport nhl` |
| Retrain models | `python ml_training/train_models.py --sport nhl --all` |
| System health | `python orchestrator.py --sport all --mode test` |
