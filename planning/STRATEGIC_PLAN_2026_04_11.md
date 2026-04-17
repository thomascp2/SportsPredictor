# Strategic Plan & Audit Synthesis (April 11, 2026)

## 1. Executive Summary
This document synthesizes the audit findings from the NHL/NBA season and outlines the "NHL Secret Sauce" porting strategy for MLB and NFL. The goal is to move from "High-Variance Event Betting" to "High-Volume Usage Betting," replicating the stable 68%+ ROI seen in the NHL.

---

## 2. Audit Findings: "The Volume vs. Variance Split"

### **NHL: The "Golden Boy" (68% ROI)**
*   **The Win:** Success is driven by "Volume Props" (Shots on Goal, Hits, Blocked Shots).
*   **The Secret:** These stats are tied to Time on Ice (TOI) and player role rather than game outcome. If a player is on the ice, they are generating volume.
*   **Hit Rates:** Shots (67%), Hits (74%), Blocks (71%).

### **NBA: The "Sketchy Child" (~58% Recent)**
*   **The Problem:** High-variance "Combo" props (Pts+Rebs, Rebs+Asts) and "Defensive" props (Steals, Turnovers) are underperforming (51-55%). 
*   **The Solution:** Focus on "Blue Chip" props (Points, Assists, Rebounds, PRA) which maintain 70-78% hit rates.
*   **Strategic Shift:** Freeze retraining during late-season "tanking" and "load management" windows to preserve model integrity.

### **MLB: The "Data Mine" Phase**
*   **Status:** ~1,465 batter samples, ~473 pitcher samples.
*   **Action:** Delay training until **May 25, 2026**. Early-season weather and pitcher ramps create too much noise.

---

## 3. The "NHL Secret Sauce" Porting Guide

To replicate the NHL's success in other sports, we will implement the following features:

### **MLB (Matchup Quality focus)**
*   **Opponent Lineup Friction:** Calculate K% and Total Base allowance of the *entire* opposing lineup, not just the starter.
*   **Fatigue Signal:** "Day After Night" (DAN) flags for travel/sleep-deprived batters.
*   **Usage Focus:** Prioritize Batter Hits, Total Bases, and Pitcher Strikeouts (Volume) over Wins or Earned Runs (Variance).

### **NFL (Usage Share focus)**
*   **Target Share Momentum:** Weight the "Last 3 Weeks" of Target Share and Red Zone Looks heavily.
*   **Usage Rule:** Focus on Receptions and Targets (Volume) over Touchdowns (High Variance).
*   **Training:** Wait for Weeks 1-4 data mining; train Week 5.

---

## 4. Implementation Log (Completed April 12)

### **Infrastructure & ROI**
*   [x] **Profit Tracking:** Standardized PrizePicks payout math across all sports.
*   [x] **Daily Audit:** `daily_audit.py` automated and scheduled for 9:00 AM.
*   [x] **CLV Capture:** Closing lines now captured during game grading.

### **NHL "Secret Sauce" Port**
*   [x] **MLB Fatigue Signal:** Added `f_rest_days` and `f_is_day_after_night` (DAN) using game-start heuristics.
*   [x] **MLB Matchup Friction:** Added team-level strikeout and base allowance features to pitcher matchups.

### **NBA After Action Review (AAR)**
*   [x] **Tier Validation:** Confirmed T1-ELITE (64.6%) significantly outperforms T2/T3 (54%).
*   [x] **Prop Identification:** Core Volume props (PTS, REB, AST) are the stable drivers; combos (PRA) are high-variance.
*   [x] **Action:** Decision to prioritize T1-ELITE and Core Volume for the 2026-27 season opener.

---

## 5. Next Steps

### **Phase 2: The Port (High Priority)**
*   [ ] Implement "Matchup Quality" feature extractors for MLB.
*   [ ] Build "Usage-Weighted" feature set for NFL.
*   [ ] Conduct deep-dive NBA After Action Review (AAR) on prop-type profitability.

### **Phase 3: Game Line Evolution (Oct 2026)**
*   [ ] Scale MLB Game Line data to 1,500+ games for mid-season ML training.
*   [ ] Align cross-sport `prediction_outcomes` schemas for macro-trend analysis.
