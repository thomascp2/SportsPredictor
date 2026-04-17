This is a massive undertaking, but essentially you're describing a **Real-Time Quantitative Trading System** for sports. In the industry, this is often called a "Live Probabilistic State Engine." Since we are "pinning" this for now, here is your comprehensive **2026 SportsPredictor Blueprint**.

---

### I. The "2026 Factor": The ABS Challenge Variable
The Automated Ball-Strike (ABS) review system is the biggest "uncertainty" in 2026. Your model must treat **Challenges Remaining** as a finite resource, much like a bullpen’s health.

* **The Rules (Current 2026):** Each team starts with **2 challenges**. They retain the challenge if successful. In extra innings, they get **+1** if they have none left.
* **The Probability Shift:** A challenge is a "probability multiplier." 
    * **High Leverage:** A challenge on a strike-three call with the bases loaded in the 8th inning is worth $\approx 0.15$ to $0.20$ in Win Probability (WP).
    * **Strategic Depletion:** If a team burns both challenges by the 3rd inning, their "True WP" should take a slight hit because they no longer have a safety net against human error in the 9th.
* **The "Vibe" vs. The Data:** You don't need to manually input the umpire's vibe. You track the **Umpire Overturn Rate**. If an umpire has a 12% overturn rate today (vs. the 6% league average), your model should widen its "Uncertainty Band" on every borderline pitch.

---

### II. The Core Architecture: Markov State Machine
To track a game "to the second" without heavy ML, you use a **Markov Chain Model**. 

1.  **The States (25 Total):** A baseball game exists in one of 25 states at any time (8 base-runner combinations $\times$ 3 out counts + 1 end-of-inning state).
2.  **The Transitions:** Every pitch or out is a "transition." 
3.  **The Weights:** Instead of generic averages, you weight the transitions using:
    * **Lineup Leverage:** Is Ohtani (Top of lineup) or the #9 hitter up?
    * **Pitcher Fatigue:** Monitor **Velocity Decay**. If a starter's fastball drops **1.5 MPH** below his game-start average, his "HR Probability" spikes before he even gives one up.
    * **Bullpen Depth:** Does the opponent have their closer available? If he's pitched 3 days in a row, the "9th inning win probability" for a 1-run lead should be lower than market price.

---

### III. Technical & Cost Breakdown

| Component | Recommendation | Estimated Cost (2026) |
| :--- | :--- | :--- |
| **Data Feed** | **Tank01 (via RapidAPI)** | **$10–$100/mo** (Affordable, 2026-ready) |
| **Server** | **DigitalOcean Droplet (4GB RAM)** | **$24/mo** |
| **Logic Engine** | **Python (for speed of dev) or Go** | **Free** (Your time) |
| **Database** | **Redis (In-Memory)** | **Free** (Open Source) |
| **Frontend** | **Next.js Dashboard** | **Free** (Vercel) |

**Total Hobbyist Cost:** ~**$35–$125/month**. This avoids the $2,000/mo enterprise trap while maintaining "Hobby-Pro" latency.

---

### IV. The "Human-First" Dashboard Requirements
Since this is for a human bettor first, your dashboard shouldn't just show numbers; it should show **Opportunity**.

* **Market Delta:** Show the difference between your model’s probability and the Live Odds (e.g., *Model: 65% | DraftKings: 58% | Value: +7%*).
* **The "Challenge Alarm":** A visual indicator of how many challenges are left. If a team is out of challenges, highlight their pitcher's "Red Zone"—where they are vulnerable to a missed call.
* **Weather Alerts:** Integrate a live wind/density feed. A 10mph gust at Wrigley can turn a 40% flyout state into a 90% HR state instantly.

---

### V. Final Critique: The "Edge"
**The Hard Truth:** Sportsbooks already use similar models. To find an edge, you aren't looking for "who will win"—you are looking for **Market Hysteria**. 
* **The Strategy:** When a star pitcher gives up 2 runs in the 1st inning, the public panics and the odds overcorrect. Your model, seeing the "True Math" (Lineup strength + Pitch count), stays calm. That "Panic Gap" is where the money is.

**Recommendation:** Pin this for now. When you're ready to start, the first step is fetching a **historical 2025/2026 Play-by-Play CSV** and running your logic against "past" games to see if your probability curves match the actual outcomes.

Does this cover everything you were envisioning for the "SportsPredictor" expansion?