# Sports Prediction System

Professional NHL and NBA prediction system with statistical models and ML training pipeline.

## Features

- **Automated Daily Predictions** for NHL and NBA player props
- **ML + Statistical Ensemble** - 60% ML, 40% Statistical hybrid predictions
- **PrizePicks Integration** - Real-time line comparison and edge calculation
- **Parlay Builder** - Identifies best OVER plays for parlay construction
- **Auto-Grading** - Grades predictions against actual results
- **24/7 Orchestrator** - Handles all scheduled tasks automatically

## Current Performance

### NHL
- Overall Accuracy: 67.9%
- UNDER: 74.4% | OVER: 54.6%

### NBA
- Overall Accuracy: 80.0%
- UNDER: 84.2% | OVER: 61.2%

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run in continuous mode (production - runs 24/7)
python orchestrator.py --sport all --mode continuous
```

## Daily Usage

### Get Today's Best Parlay Picks
```bash
# NHL Overs (for parlays)
python shared/edge_calculator.py --sport nhl --parlay --overs-only

# NBA Overs (for parlays)
python shared/edge_calculator.py --sport nba --parlay --overs-only
```

### Fetch Fresh PrizePicks Lines
```bash
python shared/prizepicks_client.py --sport nhl
python shared/prizepicks_client.py --sport nba
```

### Retrain ML Models (Monthly)
```bash
python ml_training/train_models.py --sport nhl --all
```

## Documentation

See the `docs/` directory:
- [Quick Start Guide](docs/QUICKSTART.md)
- [ML Training System](docs/ML_TRAINING.md)
- [Edge Calculator & Parlay Builder](docs/EDGE_CALCULATOR.md)

## Project Structure

```
SportsPredictor/
├── orchestrator.py       # Main orchestrator
├── nhl/                  # NHL prediction system
├── nba/                  # NBA prediction system
├── shared/               # Shared utilities
├── ml_training/          # ML training pipeline
├── dashboards/           # Dashboards and visualizations
└── docs/                 # Documentation
```

## License

Private Project
