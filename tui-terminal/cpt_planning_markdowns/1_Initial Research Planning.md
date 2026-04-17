This is a high-level engineering project that shifts from simple "tracking" to a sophisticated **Arbitrage and Analysis Terminal**. Since you're aiming for a "Command Center" rather than a bot, the focus should be on **Data Information Density** and **Contextual Intelligence**.

Here is the blueprint for your "Prop-Bloomberg" terminal.

### 1. The High-Level Architecture
To keep the system snappy without overloading the APIs, you should separate the **Data Fetcher** from the **UI/Logic** layer using a "Local-First" database.



* **Ingestion Engine (Rust):** A headless service that stays alive 24/7. It polls PrizePicks/Underdog and maintains a persistent WebSocket connection to Kalshi. 
* **Intelligence Layer (Python + Gemini):** A service that watches the database for new lines. When a line appears, it triggers a Gemini API call to check for recent news (e.g., "Is Giannis actually playing?").
* **The Terminal UI (Python + Textual):** This is your "Man Cave" display. It reads from the local DB every 500ms. Since it’s reading from local disk (SQLite/Turso), it’s effectively instant.

---

### 2. The Research: API Strategy (2026 Status)

| Service | Protocol | Access Strategy |
| :--- | :--- | :--- |
| **Kalshi** | **WebSocket (V2)** | Use the `/trade-api/v2/markets/orderbooks` endpoint. It’s the most stable and allows you to see market depth, which is great for seeing where the "sharp" money is moving. |
| **Underdog** | **REST (JSON)** | UD uses a `projections` endpoint. Use Rust to mimic a mobile header. In 2026, UD has tightened rate limits, so you must use **Cache-Control** and **ETags**. If the ETag hasn't changed, don't re-parse the JSON. |
| **PrizePicks** | **REST (JSON)** | Use the `projections?league_id=...` endpoint. Since you already have this wired up, keep it, but move the fetcher to Rust to reduce the memory footprint of your Python ML models. |
| **Context (News)** | **Gemini API** | Use the **Search Tool** in the Gemini API. You don't need a sports-specific API for injuries; Gemini can browse the latest beat-writer tweets or Rotowire updates faster and summarize the *impact* on the prop. |

---

### 3. The Tech Stack & Storage
For the database, **Turso (libSQL)** is your best bet. 
* **Why:** It is built on SQLite, so your local terminal reads from a file on your NVMe drive (sub-millisecond latency). 
* **Sync:** If you want to check your "terminal" on your phone while away, Turso handles the background replication to the cloud automatically.

**Rust (Back-end) Implementation:**
Use `tokio` for concurrency and `sqlx` to write to the database.
```rust
// Conceptual logic for the Rust Watcher
async fn watch_kalshi_ws() {
    let mut socket = connect_to_kalshi().await;
    while let Some(msg) = socket.next().await {
        let update = parse_kalshi_depth(msg);
        db::upsert_prop(update).await; // Writes to local Turso/SQLite
    }
}
```

---

### 4. The "Intelligence" Feature (Injury & Real-World Context)
Since you’re using the Gemini API, you can add a "Context Column" to your terminal. 
* **The Flow:** When Underdog moves a line for *Nikola Jokic* from 25.5 to 27.5 points, your Python script triggers a Gemini prompt:
    > "Search for latest news on Nikola Jokic. Is there a teammate injury or coaching change causing this 2-point line move?"
* **The Output:** The terminal flashes a **yellow warning icon** next to the line with a tooltip: *"Teammate Jamal Murray ruled out 5 mins ago; volume expected to increase."*

---

### 5. Implementation Plan: A 3-Phase Build

**Phase 1: The Unified Ingester (Rust)**
* Write a single Rust binary that fetches from all three. 
* **Normalization:** Map everything to a single struct. 
    * *PrizePicks:* Points = 25.5
    * *Underdog:* Points = 25.5
    * *Kalshi:* "Will Jokic score > 25.5?" = $0.62$ (62 cents)
* Store these in a `current_lines` table in Turso.

**Phase 2: The "Bloomberg" UI (Python + Textual)**
* Use the **Textual** library. It allows you to build CSS-styled terminal apps.
* Create a "Comparison Grid." 
    * **Row:** Player Name | Stat | PP Line | UD Line | Kalshi Price | ML Model Confidence.
* Highlight rows where there is a "discrepancy" (e.g., PP has it at 10.5, UD has it at 11.5).

**Phase 3: The Gemini Context Engine**
* Add a side-panel in your UI that displays a live feed of "Contextual Flags."
* Use Gemini to cross-reference your ML model's prediction with real-time news. If your model says "Over" but Gemini finds a "Player playing through illness" report, it de-ranks the play.

### A Quick Design Question:
For the display in your "man cave," do you prefer a **"Live Ticker"** style (horizontal scrolling of the best plays) or a **"Grid/Table"** style where you can see 50+ props at once? The TUI (Terminal User Interface) approach makes it easy to do either, but a grid is usually better for spotting discrepancies.