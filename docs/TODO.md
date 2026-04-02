# SportsPredictor — Active TODO List
_Last updated: 2026-04-01_

## Status Legend
- ✅ Done
- 🔄 In Progress
- ⬜ Pending

---

## ✅ Completed (This Session)

| # | Task | Notes |
|---|------|-------|
| 1 | **Git sync + golf branch merge** | 12 commits merged to master, all stale branches deleted, GitHub clean |
| 2 | **Project cleanup ~750MB+** | Deleted: old NHL/NBA backups, superseded DB files, 59 auto-generated API backups, all `__pycache__`, root junk files (`nul`, `0`, `python`) |

---

## 🔧 Next Up — Fixes & Gaps

| # | Task | Why It Matters |
|---|------|----------------|
| 3 | **Fix goalie_stats population** | Always 0 rows — NHL predictions use goalie matchup as a feature but it's never populated |
| 4 | **Wire MLB game_prediction_outcomes grading** | 0 rows today — can't calculate MLB game bet P&L at all |
| 5 | **Fix prop_bets tracking** | Only 1 row in scoreboard/bets.db — true ROI is unknown, `bets_import.csv` template exists but nothing is wired |
| 6 | **Populate model_versions table** | Always empty — no historical model performance tracking; needed for retrain decisions |

---

## 📊 Quality & Accuracy

| # | Task | Why It Matters |
|---|------|----------------|
| 7 | **Pick quality audit** | Way too many predictions generated; need to find the signal in the noise — audit hit rates by tier, prop type, odds_type, and line |
| 8 | **Fix EV math** | `ai_edge` column not accurate against actual PrizePicks payout rules; break-even math needs validation |
| 9 | **Fix dead pick filtering** | Still predicting on lines that are gone from PrizePicks by game time — waste, noise |
| 10 | **Improve DNP filtering** | Scratched/OUT players occasionally sneak through — use pre-game intel more aggressively |

---

## 🚀 Features & Monetization

| # | Task | Why It Matters |
|---|------|----------------|
| 11 | **Game lines model training (NHL + MLB)** | Game prediction data exists, models not trained; adds a wider audience/moat |
| 12 | **Production best picks selector** | Tight filter surfacing only the highest-confidence picks for selling the system |
| 13 | **Parlay EV calculator** | Reliable R/R math for 2–6 leg PP parlays; needed for monetization page |
| 14 | **AI advisor chatbot (daily_props)** | Text-to-SQL chatbot over Supabase daily_props — answers plain English questions about EV, hit rates, lineup construction |

---

## 📝 Notes

- **PrizePicks business rules**: must stay within PP terms of service for any monetization; no scraping player data beyond what's needed for predictions
- **MLB season in progress** — prioritize MLB fixes now, hockey ends ~Apr 18
- **NHL hits/blocked_shots**: ~30 game days left this season, unlikely to hit 3k minimum for ML training; data collection only
- **Golf**: data collection phase, backfill complete, no ML training until next season
- **3 worktrees still locked** (`competent-payne`, `naughty-montalcini`, `nice-shtern`) — delete manually when other sessions close
