Building a **TUI (Terminal User Interface)** with a scrolling ticker and a grid layout is the ultimate setup for a man-cave command center. It gives you that high-stakes trading floor vibe while being functionally superior for spotting line discrepancies.

Since you're using **Python** for the ML and **Rust** for performance, here is the finalized technical blueprint.

### 1. The Terminal Layout (Python + Textual)
You can use the **Textual** library to build this. It supports CSS-like styling, making it easy to create a "Bloomberg-lite" aesthetic.

* **The Header:** Current Bankroll, Active Bets, and a **Scrolling Ticker** (using a `Static` widget with a timer that offsets the text).
* **The Main Grid:** A `DataTable` widget. You can set it to auto-refresh every time your database updates.
* **The Sidebar:** A dedicated `Container` for the **Gemini Context Feed**. When you highlight a row in the grid, the sidebar automatically triggers an API call to Gemini to search for "Player + Injury News."



### 2. The Data Pipeline (Rust + Turso)
To keep the lines current without melting your CPU:

1.  **Rust Sidecar:** Write a small Rust binary using `tokio` (for async) and `reqwest`.
2.  **Kalshi V2:** Use the new `/trade-api/v2/markets/orderbooks` endpoint for Kalshi. It’s highly efficient and returns up to 100 markets in a single request.
3.  **Local-First Storage:** Use **Turso**. Your Rust service writes to the local SQLite file. Your Python UI reads from the same file.
    * *Why:* This eliminates the lag of sending data over a network between your backend and frontend.

### 3. The "Pure Picker" Scrolling Ticker
In Textual, you can implement the ticker by creating a custom widget:
```python
from textual.widgets import Static
from itertools import cycle

class Ticker(Static):
    def on_mount(self):
        self.msg_cycle = cycle(["Jokic O 25.5 (PP)", "Murray U 18.5 (UD)", "LeBron O 7.5 AST (Kalshi)"])
        self.set_interval(2.0, self.update_ticker)

    def update_ticker(self):
        self.update(next(self.msg_cycle))
```

### 4. Intelligence Integration (Gemini/XAI)
Since you’re on the free tier for Gemini, you’ll want to be strategic to avoid rate limits:
* **Trigger-Based:** Only send a prompt when a "Big Move" happens (e.g., a line moves by >1.0 point or >10% on Kalshi).
* **Prompt Strategy:** > "Analyze current NBA news for [Player Name]. Summarize any injury reports or lineup changes in 20 words. Source: Real-time search."
* **Display:** Inject this summary directly into your Textual side panel.

### 5. Strategy for Underdog (UD) Multi-Legs
While you can't "one-click" a parlay easily, your Python terminal can generate a **QR Code** or a **Deep Link** in the side panel. 
* Your terminal identifies the "Perfect Parlay" based on ML.
* It displays a QR code.
* You scan it with your phone, and it opens the UD app with those players pre-selected (if the app's URL scheme allows) or simply gives you the "Cheat Sheet" to copy over in seconds.

---

### Implementation Priority
1.  **Rust Ingester:** Get the PrizePicks and Kalshi data landing in a local `props.db` file.
2.  **Basic TUI:** Build a simple Textual table that reads from `props.db`.
3.  **The Sidebar:** Wire up the Gemini API to search based on the "Player Name" of the row you currently have selected in the terminal.

How many monitors are you planning to run this on? If it's a multi-monitor setup, we can actually design the TUI to span across them with different "panes" for different leagues.