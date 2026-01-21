# Friday ML Session Agenda

## 1. NBA ML Exploration
- Review current prediction accuracy (80.9% overall)
- Analyze which prop types perform best/worst
- Identify features with highest predictive value
- Discuss training approach once we hit 10k predictions

## 2. Sports Model Template
- Extract common patterns from NBA/NHL pipelines
- Design reusable components:
  - Data collection pipeline
  - Feature engineering framework
  - Prediction generation
  - Grading/validation system
  - API self-healing pattern
- Document template for future sports (MLB, NFL, etc.)

## 3. Flight Delay/Cancellation Model (Brainstorm)

### Potential Features
- **Weather**: Current conditions, forecasts, historical patterns
- **Airport**: Size, typical congestion, known issues, hub vs regional
- **Region**: Geographic factors, seasonal patterns
- **Aircraft**: Model type, age, maintenance history
- **Time**: Day of week, time of day, holiday proximity
- **Airline**: Historical on-time performance, fleet age

### Data Sources to Research
- FAA flight data
- Weather APIs (NOAA, OpenWeather)
- Aircraft registration databases
- Historical delay/cancellation records

### Model Considerations
- Binary classification (on-time vs delayed) or multi-class (on-time/delayed/cancelled)
- Time-series component for real-time predictions
- Feature importance for explainability

---
*For Saturday commute discussion*
