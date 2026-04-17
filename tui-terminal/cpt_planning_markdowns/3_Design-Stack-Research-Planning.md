Since you’re rocking a gigantic curved ultra-wide with a second screen above, we can move away from the "cramped" terminal feel and go for a **Modular Command Center**. On a curved display, your "peripheral vision" is your greatest asset—you want the most volatile data (Kalshi and the Ticker) in the center and the context/news on the far wings.

Here is the final system design optimized for a single ultra-wide workstation.

---

### 1. The Ultra-Wide Layout (Textual + CSS)
Using **Textual's** CSS grid system, we can divide your curved monitor into "Zones."

| Zone | Content | Logic |
| :--- | :--- | :--- |
| **Far Left (20%)** | **Context Wing** | Live Gemini/XAI feed of injuries and beat-writer news. |
| **Center (60%)** | **The Grid** | Multi-source lines (PP vs. UD vs. Kalshi) + ML Confidence. |
| **Far Right (20%)** | **The Betslip / Watchlist** | Your "Command" area where you queue up plays for the day. |
| **Bottom (Full)** | **The "Pure Picker" Ticker** | 60 FPS scrolling marquee of live line-moves and Kalshi price shifts. |

---

### 2. High-Frequency Ingestion (The Rust "Sidecar")
Since you have a background in C and Rust, write a "Headless Ingester." This runs as a background service (`systemd` or just a terminal tab) and handles the "Dirty Work."

* **Concurrency:** Use `tokio` to manage three separate "tasks" (one per API).
* **Kalshi WebSocket:** Keep this connection open indefinitely. It's the only way to catch $0.05$ price swings in real-time.
* **Underdog/PrizePicks:** Use `reqwest` with a **Rate-Limiter crate** (like `governor`). 
    * *Pro Tip:* In 2026, these APIs often check for `User-Agent` consistency. Ensure your Rust bot uses the exact same headers as your manual browser/app sessions to avoid "shadow-banning" your data access.

---

### 3. The Database: Turso + Local Replicas
Because your display is high-resolution, your Python UI will be refreshing a *lot* of data.
* **The Setup:** Use **Turso** with a local SQLite replica.
* **The Benefit:** When the Rust sidecar writes a new price to the local DB, the Python TUI (using `watchfiles` or a simple timer) sees the file change and updates the UI instantly. **Zero network latency** for the UI render.

---

### 4. Integrating the Gemini API (The "Intelligence" Layer)
Since you’re on the free tier, don't waste tokens on every player. 
* **The Logic:** Set a "Volatility Threshold" in your Python code.
* **The Trigger:** If the Kalshi price for "NHL Over 0.5 Goals" moves from $0.40 \rightarrow 0.60$ in under 10 minutes, *then* trigger the Gemini API.
* **The Prompt:** > "Summarize why [Player]'s market is moving. Check for line-up changes or goalie swaps in the last 30 minutes. Keep it to 1 sentence."

---

### 5. Why the "Above Monitor" is your Secret Weapon
Since you have a large display sitting above your workstation, you should use it for **"Macro Monitoring."**
* **Workstation (Curved):** Deep-dive terminal, ML model outputs, and line-entry.
* **Top Display:** Full-screen **"Heatmap."** * Create a simple web-view or a second Textual instance that just shows colors: **Red** for lines moving against you, **Green** for value appearing. 
    * This allows you to be "heads down" in the data on the main screen, only looking up when the top display flashes a specific color.

### Recommended Tooling Recap:
* **Language:** Rust (Backend) + Python (ML/UI).
* **UI Framework:** [Textual](https://textual.textualize.io/) (Python).
* **Database:** [Turso](https://turso.tech/) (SQLite-based).
* **LLM:** Gemini API (Free Tier) via the `google-generativeai` Python SDK.

**Next Step Recommendation:** Start by writing the **Rust Normalizer**. It should take the JSON from PrizePicks, Underdog, and Kalshi and turn them into a single `Prop` struct. Once you have a unified stream of data hitting your local DB, building the UI is just "painting" with that data.

Does that layout sound like it would fill that curved monitor effectively, or do you want to reserve some screen real estate for the actual game streams?