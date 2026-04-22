# Session Log — 2026-04-21 (ML v2 Planning)

## What Happened

Full planning session for the ML v2 architecture overhaul. No code was written. Plan file created and approved.

**Plan file:** `C:\Users\thoma\.claude\plans\just-put-a-pin-stateless-ember.md`

---

## The Core Insight: Edge Is Wrong

Current edge formula:
```
edge = (model_probability - PP_break_even) * 100
```

This compares model probability to PrizePicks' payout structure — not the actual market. We have no idea if we're beating the sharp books.

New formula:
```
true_edge = model_probability - market_implied_probability
```
Where `market_implied_probability` comes from DraftKings player prop lines (free, unofficial API via `draft-kings` package — already installed v3.1.0).

---

## Approved Architecture (Parallel System)

Runs alongside existing system. Nothing on the dashboard or orchestrator is touched until we decide to promote.

### Build Order (resume here next session):
1. **Phase 1** — `shared/market_odds_client.py` (DraftKings odds fetcher, market edge calc)
2. **Phase 6** — `ml_v2_predictions` table schema (one per sport SQLite DB)
3. **Phase 4** — `ml_training/mab_weighting.py` (Thompson Sampling MAB)
4. **Phase 2** — `ml_training/production_predictor.py` extended (BMA distributions)
5. **Phase 3** — `ml_training/drift_detector.py` (KS test + SHAP)
6. **Phase 5** — `shared/teammate_features.py` (On/Off adjustments via BALLDONTLIE)

### Key Technical Decisions:
- `draft-kings` v3.1.0 already installed — ready to use
- BALLDONTLIE free tier needed for Phase 5 (lineup/injury data) — needs API key in `.env`
- MAB initial weights: 0.40 XGB / 0.30 RF / 0.20 LR / 0.10 stat
- MAB state persisted to `ml_training/mab_state/{sport}_{prop}.json`
- ml_v2 output goes to `ml_v2_predictions` table per sport DB (separate from `predictions`)
- No Turso sync for ml_v2 until promoted
- Discord comparison post can be the first "visible" output without dashboard changes

### What NOT To Touch:
- `dashboards/cloud_dashboard.py`
- `sync/turso_sync.py`
- Existing `*_predictions` tables
- Orchestrator continuous mode

---

## Pinned To-Do (Pre-Retrain Hygiene, Oct/Nov 2026)

These are separate from the v2 build — implement anytime:
- [ ] NBA training exclusion list: Jan 18–26 + Mar 15 windows in `train_models.py`
- [ ] Exponential recency decay: 0.5-decay weighting replacing uniform L5/L10
- [ ] Minutes/ice-time gating: regress toward 0.5 if projected_minutes < 25 (NBA) / TOI < 12 (NHL)
- [ ] MLB feature audit script: confirm no silent 0.0 defaults in `_prepare_features()`
- [ ] MLB per-prop sample gate: raise 500 → 1,500 min rows before training
- [ ] Goalie SV% feature for NHL shots prop

---

## System State (unchanged from last session)
- Dashboard live at share.streamlit.io — all 4 sports working
- All sports in statistical-only mode
- No code changed this session
