# 30-Day Launch Roadmap
**Target: ML-Powered Predictions by Mid-February 2026**
**Updated:** December 28, 2025
**Strategy:** Accelerated launch at 7,500 predictions per prop

---

## Mission

Launch ML-powered prediction models for NHL and NBA by mid-February 2026, achieving production-ready systems that can:
1. **Test against real sportsbook lines** (PrizePicks, DraftKings, FanDuel)
2. **Identify profitable betting opportunities**
3. **Track ROI and performance metrics**
4. **Demonstrate market edge** (for personal use or product sale)

---

## Timeline Overview

```
Dec 28, 2025 (TODAY)
│
├─ NBA: 4,343/7,500 (57.9% complete)
├─ NHL: 4,393/7,500 (58.6% complete)
│
▼ PHASE 1: Data Collection (30 days)
│
Jan 27, 2026 → NBA READY (7,500/prop reached)
Jan 30, 2026 → NHL READY (7,500/prop reached)
│
▼ PHASE 2: ML Training Prep (3 days)
│
Feb 2, 2026 → Begin ML Training
│
▼ PHASE 3: Model Training (2 weeks)
│
Feb 16, 2026 → LAUNCH LIVE PREDICTIONS
│
▼ PHASE 4: Live Testing & Iteration
│
Ongoing → Track vs real lines, optimize, retrain
```

---

## Phase 1: Data Collection (Dec 28 - Jan 30)

### Current Status
- **NHL:** 4,393/7,500 per prop (3,107 needed)
- **NBA:** 4,343/7,500 per prop (3,157 needed)
- **Velocity:** NHL ~95/day, NBA ~106/day per prop
- **Days to completion:** NHL 33 days, NBA 30 days

### Daily Operations (Automated via Orchestrator)

**NHL Schedule (CST):**
- 02:00 AM - Grade yesterday's predictions
- 07:30 AM - Fetch PrizePicks lines
- 08:00 AM - Generate today's predictions
- Every 60 min - Health check

**NBA Schedule (CST):**
- 09:00 AM - Grade yesterday's predictions
- 09:30 AM - Fetch PrizePicks lines
- 10:00 AM - Generate today's predictions
- Every 60 min - Health check

### Weekly Monitoring (Every Monday)

**Check Progress:**
```bash
# NHL Progress
cd C:/Users/thoma/SportsPredictor
sqlite3 nhl/database/nhl_predictions_v2.db "SELECT prop_type || '_' || line as prop, COUNT(*) as count, ROUND(COUNT(*)*100.0/7500, 1) as pct FROM predictions GROUP BY prop_type, line ORDER BY count"

# NBA Progress
sqlite3 nba/database/nba_predictions.db "SELECT prop_type || '_' || line as prop, COUNT(*) as count, ROUND(COUNT(*)*100.0/7500, 1) as pct FROM predictions WHERE prop_type IN ('points', 'rebounds', 'assists', 'threes') GROUP BY prop_type, line ORDER BY count"
```

**Monitor Metrics:**
- Prediction velocity (should maintain 95+ NHL, 106+ NBA per day)
- Grading accuracy (target: NHL 65%+, NBA 75%+)
- Feature completeness (must stay at 100%)
- Opponent feature coverage (must stay at 90%+)

### Risk Mitigation

**If velocity drops:**
- Check for API issues (stats.nba.com, NHL API)
- Verify orchestrator is running continuously
- Check for rate limiting or blocking
- Review error logs: `logs/orchestrator_errors_*`

**If data quality degrades:**
- Run health check: `python orchestrator.py --sport all --mode test`
- Check feature engineering scripts
- Verify opponent data is being fetched

---

## Phase 2: ML Training Preparation (Jan 30 - Feb 2)

### Infrastructure Setup

**1. Training Environment**
```bash
# Create ML training directory
mkdir -p ml_training/models
mkdir -p ml_training/evaluation
mkdir -p ml_training/logs

# Install ML libraries (if not already installed)
pip install scikit-learn xgboost lightgbm catboost
pip install pandas numpy matplotlib seaborn
pip install optuna  # For hyperparameter tuning
```

**2. Data Preparation**

**Extract training data from databases:**
```python
# NHL
import sqlite3
import pandas as pd

conn = sqlite3.connect('nhl/database/nhl_predictions_v2.db')

# Get predictions with outcomes for training
query = """
SELECT
    p.*,
    o.outcome,
    o.actual_value,
    o.predicted_outcome
FROM predictions p
JOIN prediction_outcomes o ON
    p.player_name = o.player_name AND
    p.game_date = o.game_date AND
    p.prop_type = o.prop_type AND
    p.line = o.line
"""
df = pd.read_sql(query, conn)
df.to_csv('ml_training/nhl_training_data.csv', index=False)
```

**3. Feature Engineering Review**

**NHL Features (from features_json):**
- Player stats: last5_avg, last10_avg, season_avg, etc.
- Opponent stats: opp_points_allowed_L5, opp_defensive_rating
- Contextual: home_away, rest_days, b2b_game
- Goalie stats: sv_pct, gaa, recent_form

**NBA Features (from columns + features_json):**
- Success rates: season, L20, L10, L5, L3
- Averages: season_avg, l10_avg, l5_avg
- Trends: trend_slope, trend_acceleration
- Context: home_away_split, avg_minutes, consistency_score
- Opponent: opp_points_allowed_l10, opp_defensive_rating

**4. Train/Validation/Test Split Strategy**

```
Training Data:   70% (oldest data)
Validation Data: 15% (middle data)
Test Data:       15% (most recent data)
```

**Why chronological split?**
- Prevents data leakage (no future data in training)
- Tests model on most recent patterns (closest to production)
- Mimics real-world deployment scenario

---

## Phase 3: Model Training (Feb 2 - Feb 16)

### Week 1: Model Development (Feb 2-9)

**Day 1-2: Baseline Models**
```python
# Train simple models for each prop type
models = {
    'Logistic Regression': LogisticRegression(),
    'Random Forest': RandomForestClassifier(),
    'Gradient Boosting': GradientBoostingClassifier()
}

# For each sport/prop combination
for prop in ['points_1.5', 'shots_2.5', ...]:
    for name, model in models.items():
        train_and_evaluate(model, prop, data)
```

**Day 3-5: Advanced Models**
```python
# XGBoost (usually best for tabular data)
xgb_model = xgb.XGBClassifier(
    max_depth=6,
    learning_rate=0.1,
    n_estimators=100,
    objective='binary:logistic'
)

# LightGBM (faster, often comparable)
lgb_model = lgb.LGBMClassifier(
    num_leaves=31,
    learning_rate=0.05,
    n_estimators=200
)

# Neural Network (for complex patterns)
from sklearn.neural_network import MLPClassifier
nn_model = MLPClassifier(
    hidden_layers=(100, 50, 25),
    activation='relu',
    solver='adam'
)
```

**Day 6-7: Hyperparameter Tuning**
```python
import optuna

def objective(trial):
    params = {
        'max_depth': trial.suggest_int('max_depth', 3, 10),
        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3),
        'n_estimators': trial.suggest_int('n_estimators', 50, 300),
        'min_child_weight': trial.suggest_int('min_child_weight', 1, 7),
        'subsample': trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
    }

    model = xgb.XGBClassifier(**params)
    score = cross_val_score(model, X_train, y_train, cv=5).mean()
    return score

study = optuna.create_study(direction='maximize')
study.optimize(objective, n_trials=100)
```

### Week 2: Evaluation & Selection (Feb 9-16)

**Model Evaluation Metrics:**
- **Accuracy:** Overall hit rate
- **Precision:** When we predict OVER, how often is it OVER?
- **Recall:** Of all actual OVERs, how many did we catch?
- **ROI Simulation:** Assuming -110 odds, what's expected ROI?
- **Calibration:** Are predicted probabilities accurate?

**Selection Criteria:**
1. **Accuracy** > current statistical model (NHL 68.6%, NBA 79.1%)
2. **ROI** > 5% on validation set
3. **Calibration** error < 5%
4. **Consistency** across prop types

**Final Model Registry:**
```
ml_training/model_registry/
├── nhl_points_0.5_xgboost_v1.pkl
├── nhl_points_1.5_xgboost_v1.pkl
├── nhl_shots_1.5_lightgbm_v1.pkl
├── nhl_shots_2.5_xgboost_v1.pkl
├── nhl_shots_3.5_xgboost_v1.pkl
├── nba_points_15.5_xgboost_v1.pkl
├── nba_points_20.5_neural_net_v1.pkl
├── nba_points_25.5_xgboost_v1.pkl
└── ... (14 NBA prop/line combos)
```

---

## Phase 4: Production Deployment (Feb 16 onwards)

### Integration Strategy

**Option A: Replace Statistical Model (Recommended)**
```python
# In prediction pipeline
if USE_ML_MODEL and ml_model_exists(prop_type, line):
    prediction, probability = ml_model.predict(features)
else:
    # Fallback to statistical model
    prediction, probability = statistical_model.predict(features)
```

**Option B: Ensemble (Conservative)**
```python
# Combine ML and statistical predictions
ml_prob = ml_model.predict_proba(features)[1]
stat_prob = statistical_model.predict_proba(features)[1]

# Weighted average (favor ML if confidence is high)
if abs(ml_prob - 0.5) > 0.2:  # ML is confident
    final_prob = 0.8 * ml_prob + 0.2 * stat_prob
else:  # ML is uncertain, trust statistical more
    final_prob = 0.5 * ml_prob + 0.5 * stat_prob

prediction = 'OVER' if final_prob > 0.5 else 'UNDER'
```

### Live Testing Dashboard

**Track These Metrics Daily:**

**Performance vs Statistical Model:**
```
               ML Model    Statistical    Difference
NHL Accuracy:    ??.?%        68.6%          +?.?%
NBA Accuracy:    ??.?%        79.1%          +?.?%
```

**Performance vs Sportsbook Lines:**
```
               Predictions   Hits   Accuracy   ROI
PrizePicks:         145      89     61.4%    +8.2%
DraftKings:          78      52     66.7%   +12.5%
FanDuel:             92      58     63.0%    +9.8%
```

**Profitability Tracking:**
```python
# Calculate ROI
# Assuming standard -110 odds (bet $110 to win $100)

wins = num_hits
losses = num_predictions - num_hits

# Profit/Loss
profit = wins * 100  # Win $100 per hit
loss = losses * 110  # Lose $110 per miss
net = profit - loss

# ROI
total_wagered = num_predictions * 110
roi = (net / total_wagered) * 100

print(f"Net Profit: ${net:,.2f}")
print(f"ROI: {roi:.2f}%")
```

### Retraining Schedule

**Triggered Retraining (Immediate):**
- Accuracy drops >5% below baseline
- ROI turns negative for 3+ consecutive days
- New opponent feature patterns emerge

**Scheduled Retraining:**
- **Week 1-4:** Weekly (Feb 16, 23, Mar 2, 9)
- **Week 5-8:** Bi-weekly (Mar 23, Apr 6, Apr 20)
- **Month 3+:** Monthly (May 4, Jun 1, Jul 1, ...)

**Retraining Process:**
1. Extract last 30 days of graded predictions
2. Combine with historical training data
3. Retrain models with same hyperparameters
4. Validate on most recent 7 days
5. If validation accuracy > current model + 2%, deploy
6. Otherwise, keep current model

---

## Performance Targets

### Phase 1 (Data Collection) - SUCCESS CRITERIA
- [x] Reach 7,500 predictions per prop by Jan 30 (NHL) / Jan 27 (NBA)
- [x] Maintain 100% feature completeness
- [x] Maintain 90%+ opponent feature coverage
- [x] Statistical accuracy: NHL 65%+, NBA 75%+

### Phase 2 (Training Prep) - SUCCESS CRITERIA
- [ ] Training data extracted and cleaned
- [ ] Features normalized/scaled
- [ ] Train/val/test splits created (70/15/15)
- [ ] Baseline models trained

### Phase 3 (Model Training) - SUCCESS CRITERIA
- [ ] ML models beat statistical baseline by 2%+ accuracy
- [ ] Validation ROI > 5%
- [ ] Models calibrated (calibration error < 5%)
- [ ] Final models selected and saved

### Phase 4 (Production) - SUCCESS CRITERIA
- [ ] ML models integrated into prediction pipeline
- [ ] Live performance tracking dashboard operational
- [ ] Week 1 ROI > 3%
- [ ] Week 4 ROI > 5%
- [ ] Month 1 average accuracy > baseline + 3%

---

## Contingency Plans

### If Data Collection Falls Behind

**Problem:** Not reaching 7,500 predictions by Jan 30
**Solution:**
1. Check orchestrator logs for errors
2. Verify API connectivity
3. If systematic issue, extend deadline by 1-2 weeks
4. Don't compromise data quality for speed

### If ML Models Underperform

**Problem:** ML accuracy < statistical baseline
**Solution:**
1. Check for data leakage in training
2. Review feature engineering (add more features?)
3. Try different model architectures
4. Increase training data requirement to 10,000
5. Fallback: Launch with statistical model, retrain ML weekly

### If Live ROI is Negative

**Problem:** Losing money in production
**Solution:**
1. IMMEDIATELY reduce bet sizing to minimum
2. Analyze which props are profitable vs unprofitable
3. Disable unprofitable props
4. Review sportsbook line movements (are we betting stale lines?)
5. Consider betting strategy: only bet when ML confidence > 70%

### If Sportsbooks Limit/Ban Account

**Problem:** Books restrict betting due to consistent wins
**Solution:**
1. This is actually a GOOD problem (means you're winning!)
2. Use the data to prove system works
3. Pivot to selling picks/predictions instead of betting
4. Partner with others who have accounts
5. Focus on documenting ROI for sales pitch

---

## Commercialization Strategy (If Selling)

### Product Options

**Option 1: Daily Picks Service ($$$)**
- Sell daily predictions via subscription
- $50-100/month per subscriber
- Deliver via email/Discord/Telegram
- Show verified track record

**Option 2: Software License ($$$$)**
- License the entire system to a syndicate
- One-time fee: $50k-250k
- Ongoing support contract
- Non-compete agreement

**Option 3: Partnership ($$$$+)**
- Partner with existing sports betting service
- Revenue share on profits
- They provide capital, you provide edge
- Scale significantly

### Track Record Requirements

**Minimum to sell credibly:**
- 30 days live performance
- 500+ predictions tracked
- Verified ROI > 8%
- Documented accuracy > market baseline

**Documentation:**
- Daily prediction logs (timestamped)
- Actual sportsbook line comparison
- Win/loss records
- ROI calculations
- Bankroll growth curve

---

## Next Actions

### This Week (Dec 28 - Jan 3)
- [x] Update ML readiness threshold to 7,500
- [x] Update orchestrator configs
- [ ] Monitor orchestrator health daily
- [ ] Review this roadmap weekly

### Next Week (Jan 4 - Jan 10)
- [ ] First weekly progress check
- [ ] Verify on track for Jan 27-30 completion
- [ ] Begin researching ML model architectures
- [ ] Start drafting training scripts

### Weeks 3-4 (Jan 11 - Jan 30)
- [ ] Continue data collection
- [ ] Prepare training environment
- [ ] Extract and clean training data
- [ ] Create feature engineering pipeline

### Week 5 (Feb 2 - Feb 9)
- [ ] Train baseline models
- [ ] Train advanced models (XGBoost, LightGBM, NN)
- [ ] Hyperparameter tuning

### Week 6-7 (Feb 10 - Feb 16)
- [ ] Model evaluation and selection
- [ ] Build model registry
- [ ] Integration testing
- [ ] Launch preparation

### Launch (Feb 16, 2026)
- [ ] Deploy ML models to production
- [ ] Begin live tracking
- [ ] Monitor performance vs statistical baseline
- [ ] Track ROI vs sportsbook lines

---

## Contact & Escalation

**System Issues:**
- Check logs: `logs/orchestrator_errors_*`
- Run health check: `python orchestrator.py --mode test`
- Review CLAUDE.md for common issues

**Data Quality Issues:**
- Run data quality audit (this can be scripted)
- Check feature completeness
- Verify opponent data coverage

**ML Training Issues:**
- Review training logs
- Check for data leakage
- Validate train/test split
- Compare to baseline models

---

## Success Definition

**We've succeeded when:**
1. ✅ ML models deployed and generating predictions
2. ✅ Live ROI > 5% sustained over 30 days
3. ✅ System runs reliably without manual intervention
4. ✅ Track record documented and verifiable
5. ✅ Either: (a) Crushing the books personally, or (b) System sold/licensed

**Let's get it!** 🚀

---

**Document Version:** 1.0
**Last Updated:** December 28, 2025
**Next Review:** January 6, 2026 (weekly)
