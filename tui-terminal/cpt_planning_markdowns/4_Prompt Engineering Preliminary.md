This is a high-performance build. To get this "Bloomberg for Props" terminal running on your curved ultra-wide, we’ll break the implementation into four modular prompts. 

Feed these into **Claude-3.5-Sonnet** or **Gemini 1.5 Pro/Flash** in order. Each prompt is designed to produce a "working piece" of the terminal that integrates with the others via your **Turso/SQLite** database.

---

### **Prompt 1: The Foundation (Turso Schema & Rust Ingester)**
**Goal:** Build the "Headless Sidecar" in Rust that keeps lines current without overloading the system.

> **Prompt for CLI:**
> "I am building a sports prop terminal. Write a Rust backend service using `tokio`, `reqwest`, `serde`, and `sqlx` (for Turso/libSQL). 
> 
> 1. **Database Schema:** Define a `props` table with fields for `player_id`, `name`, `stat_type` (e.g., NBA_POINTS), `prizepicks_line`, `underdog_line`, `kalshi_price`, `ml_confidence`, and `last_updated`. 
> 2. **Kalshi Integration:** Implement a WebSocket client using Kalshi V2 API (`/trade-api/v2/markets/orderbooks`) to fetch real-time price deltas.
> 3. **REST Polling:** Implement an async polling loop for PrizePicks and Underdog Fantasy. Use `ETag` and `If-Modified-Since` headers to avoid redundant JSON parsing and rate limits.
> 4. **Normalization:** Map all three API responses into a single 'UnifiedProp' struct and UPSERT them into the local Turso/SQLite database every time a line changes.
> 5. **Safety:** Implement a 30-second jittered interval for REST calls and exponential backoff for the Kalshi WebSocket reconnection."

---

### **Prompt 2: The UI Layout (Python Textual - Ultra-Wide)**
**Goal:** Create the terminal interface optimized for a curved monitor, featuring the "Pure Picker" ticker.

> **Prompt for CLI:**
> "Use the Python `Textual` library to build a multi-pane TUI for an ultra-wide monitor. 
> 
> 1. **Layout Grid:** Create a three-column layout:
>    - **Left (20%):** 'Context Wing' (Static widget for Gemini news).
>    - **Center (60%):** 'Main Floor' (A `DataTable` displaying the unified props from the Turso DB).
>    - **Right (20%):** 'Watchlist' (A list of selected plays).
> 2. **The Ticker:** Build a custom `Ticker` widget at the very bottom. It should scroll horizontally at 60 FPS, pulling the latest 'Significant Line Moves' from the database (e.g., 'Jokic line moved +1.5 on UD').
> 3. **Reactive Updates:** The `DataTable` must refresh its content every 1 second by querying the local SQLite file without blocking the UI thread.
> 4. **Styling:** Use a high-contrast 'Bloomberg' aesthetic—dark background, green text for value, red for line drops, and amber for volatile markets."

---

### **Prompt 3: The Intelligence Layer (Gemini/XAI Context)**
**Goal:** Connect the terminal to the Gemini API to search for injuries and lineup changes based on line movement.

> **Prompt for CLI:**
> "Write a Python service that monitors my Turso `props` database for 'Volatility Triggers.' 
> 
> 1. **Trigger Logic:** If a player's line moves by more than 10% on Kalshi or 1.0 points on PrizePicks within 15 minutes, flag that player.
> 2. **Gemini Search:** For flagged players, use the Gemini API (google-generativeai SDK) with the `Google Search_retrieval` tool. 
> 3. **Prompt:** 'Search for the latest news on [Player Name]. Why is their betting line moving? Check for injuries, resting, or coach comments. Summarize in 15 words or less.'
> 4. **Output:** Write the summary into a `news_context` table in the database so the Textual UI can display it in the 'Context Wing' sidebar instantly."

---

### **Prompt 4: The Top Display "Heatmap" (Visual Alerts)**
**Goal:** Build the secondary dashboard for your top-mounted screen to give you heads-up alerts.

> **Prompt for CLI:**
> "Create a secondary, lightweight Python Textual application for a top-mounted monitor. 
> 
> 1. **Visualization:** Instead of data tables, this should be a high-visibility 'Heatmap.' Divide the screen into a grid of 'tiles' (e.g., NBA, NHL, NFL).
> 2. **Logic:** Color the tiles based on 'Global Value.' If my ML models find a high-confidence discrepancy between Kalshi and PrizePicks, make that league tile flash bright Green.
> 3. **Minimalism:** No small text—just large player names and the percentage of value. This is intended to be seen from 5 feet away while focusing on the main curved monitor."

---

### **The "Man Cave" Setup Checklist**

| Component | Tech | Role |
| :--- | :--- | :--- |
| **Ingester** | Rust | High-speed data fetching (The Engine). |
| **Terminal** | Python (Textual) | The main ultra-wide display (The Command). |
| **Intel** | Gemini API | Real-world news and injury context (The Advisor). |
| **Storage** | Turso (libSQL) | The glue that connects Rust to Python (The Ledger). |

### **One Pro Tip for the Curved Setup:**
Since you mentioned the curved monitor can be "frustrating," use **Textual's CSS** to add significant `padding` to the far edges. On a gigantic curve, looking at the extreme corners for data causes neck strain—keep the "active" betting grid in the center 50% and put your "slow" data (like the 24-hour news feed) on the outer edges. 

**Ready to start the Rust build, or do you want to refine the DB schema for your specific ML model inputs first?**