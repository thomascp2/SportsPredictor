#!/usr/bin/env python3
"""
FreePicks Cloud Dashboard
=========================

Mobile-friendly monitoring dashboard backed by Supabase.
Reads from daily_props, model_performance, and daily_games tables.

Deploy to Streamlit Community Cloud:
  1. Push this repo to GitHub
  2. Go to share.streamlit.io → New app → select this file
  3. Add secrets: SUPABASE_URL and SUPABASE_KEY in the Streamlit Cloud UI

Run locally:
  streamlit run dashboards/cloud_dashboard.py
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from typing import Optional
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "shared"))
try:
    from project_config import BREAK_EVEN as _PROJECT_BREAK_EVEN
except ImportError:
    # Exact fractions — must stay in sync with gsd_module/shared/odds.py BREAK_EVEN_MAP.
    # standard: 110/210 = 0.52381 (NOT 0.56 — that was the pre-Mar-8-2026 bug value)
    # goblin:   320/420 = 0.76190
    # demon:    100/220 = 0.45455
    _PROJECT_BREAK_EVEN = {"standard": 110 / 210, "goblin": 320 / 420, "demon": 100 / 220}

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FreePicks Dashboard",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="collapsed",   # collapsed = better on mobile
)

st.markdown("""
<style>
    /* ── Google Fonts — JetBrains Mono ──────────────────────────────────────── */
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');

    /* ── Design tokens ───────────────────────────────────────────────────────── */
    :root {
        /* Surface / chrome */
        --bg-page:        #0d1117;
        --bg-card:        #161b22;
        --bg-card-hover:  #1c2128;
        --border:         #30363d;
        --border-subtle:  #21262d;

        /* Text */
        --text-primary:   #e6edf3;
        --text-secondary: #c9d1d9;
        --text-muted:     #8b949e;
        --text-dim:       #484f58;

        /* Semantic / status */
        --green:   #3fb950;
        --blue:    #58a6ff;
        --yellow:  #e3b341;
        --orange:  #f0883e;
        --red:     #f85149;
        --purple:  #bc8cff;

        /* Tier colours */
        --tier-prime:  #3fb950;
        --tier-sharp:  #58a6ff;
        --tier-lean:   #f0883e;
        --tier-pass:   #8b949e;

        /* Font — mono everywhere */
        --font-mono: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
        --lh:        1.45;
        --lh-tight:  1.25;
    }

    /* ── Global mono font ────────────────────────────────────────────────────── */
    /* Target text elements only — never structural div/span/[class*="css"]      */
    /* Applying line-height to every div breaks Streamlit's dropdown rendering   */
    html, body { font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace !important; }
    .stApp, .stMarkdown, .stMarkdown p,
    .stTextInput input, .stDateInput input,
    .stSelectbox [data-baseweb="select"] span,
    .stMultiSelect [data-baseweb="select"] span,
    button, label, p, li,
    [data-testid="stMetricValue"],
    [data-testid="stMetricLabel"],
    [data-testid="stMetricDelta"] {
        font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace !important;
    }

    /* ── Layout ──────────────────────────────────────────────────────────────── */
    .block-container { padding-top: 0.75rem; padding-bottom: 0.75rem; }

    /* ── Page title / caption ────────────────────────────────────────────────── */
    /* Use explicit hex — CSS vars don't always resolve in Streamlit's shadow DOM */
    h1 { font-size: 18px !important; font-weight: 700 !important;
         letter-spacing: 0.5px !important; text-transform: uppercase !important;
         color: #e6edf3 !important; }
    h2 { font-size: 15px !important; font-weight: 700 !important;
         letter-spacing: 0.4px !important; color: #e6edf3 !important; }
    /* Scope h3 to markdown only — global h3 rule was garbling Streamlit widget labels */
    .stMarkdown h3 { font-size: 13px !important; font-weight: 700 !important;
                     letter-spacing: 0.4px !important; text-transform: uppercase !important;
                     color: #8b949e !important; }
    .stCaption, [data-testid="stCaptionContainer"] p {
        font-size: 11px !important; color: #484f58 !important;
        letter-spacing: 0.3px !important;
    }

    /* ── Tabs ────────────────────────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0px;
        border-bottom: 1px solid var(--border);
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 11px !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.8px !important;
        padding: 6px 14px !important;
        border-radius: 0 !important;
        color: var(--text-muted) !important;
        border-bottom: 2px solid transparent !important;
        background: transparent !important;
    }
    .stTabs [aria-selected="true"] {
        color: var(--text-primary) !important;
        border-bottom: 2px solid var(--blue) !important;
    }

    /* ── Metrics ─────────────────────────────────────────────────────────────── */
    [data-testid="stMetricLabel"]  { font-size: 10px !important; text-transform: uppercase !important;
                                      letter-spacing: 0.6px !important; color: var(--text-dim) !important; }
    [data-testid="stMetricValue"]  { font-size: 20px !important; font-weight: 700 !important;
                                      color: var(--text-primary) !important; line-height: var(--lh-tight) !important; }
    [data-testid="stMetricDelta"]  { font-size: 11px !important; }

    /* ── Buttons ─────────────────────────────────────────────────────────────── */
    .stButton > button {
        font-size: 11px !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.6px !important;
        border-radius: 4px !important;
        border: 1px solid var(--border) !important;
        background: var(--bg-card) !important;
        color: var(--text-secondary) !important;
        padding: 4px 12px !important;
    }
    .stButton > button:hover {
        border-color: var(--blue) !important;
        color: var(--blue) !important;
    }

    /* ── Selectbox ───────────────────────────────────────────────────────────── */
    .stSelectbox [data-baseweb="select"] > div {
        font-size: 12px !important;
        border-radius: 4px !important;
        border-color: #30363d !important;
        background: #161b22 !important;
        min-height: 36px !important;
    }
    .stSelectbox [data-baseweb="select"] span {
        font-size: 12px !important;
        color: #c9d1d9 !important;
    }

    /* ── Date input — match selectbox exactly ────────────────────────────────── */
    [data-testid="stDateInput"] [data-baseweb="input"] {
        font-size: 12px !important;
        border-radius: 4px !important;
        border-color: #30363d !important;
        background: #161b22 !important;
        min-height: 36px !important;
    }
    [data-testid="stDateInput"] input {
        font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace !important;
        font-size: 12px !important;
        color: #c9d1d9 !important;
        padding: 0 8px !important;
    }
    /* Hide the calendar icon so date input is visually plain like a selectbox */
    [data-testid="stDateInput"] [data-baseweb="input"] svg { display: none !important; }

    /* ── Dataframes ──────────────────────────────────────────────────────────── */
    [data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th {
        font-size: 11px !important;
        line-height: var(--lh-tight) !important;
    }

    /* ── Progress bars ───────────────────────────────────────────────────────── */
    .stProgress > div > div { border-radius: 2px !important; }

    /* ── Divider ─────────────────────────────────────────────────────────────── */
    hr { border-color: var(--border-subtle) !important; margin: 10px 0 !important; }

    /* ── Expander ────────────────────────────────────────────────────────────── */
    .streamlit-expanderHeader {
        font-size: 11px !important; font-weight: 600 !important;
        text-transform: uppercase !important; letter-spacing: 0.5px !important;
        color: var(--text-muted) !important;
    }

    /* ── Info / error / warning boxes ───────────────────────────────────────── */
    .stAlert p { font-size: 12px !important; }

    /* ── Prop tier badge colours (class-based) ───────────────────────────────── */
    .tier-elite  { color: var(--green);  font-weight: 700; }
    .tier-strong { color: #69f0ae; }
    .tier-good   { color: var(--yellow); }
    .tier-lean   { color: var(--orange); }

    /* ── Game / prop card ────────────────────────────────────────────────────── */
    .gl-card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 4px;
        padding: 12px 16px;
        margin-bottom: 8px;
        font-size: 12px;
        line-height: var(--lh);
    }
    .gl-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
        padding-bottom: 6px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .gl-matchup {
        font-size: 13px;
        font-weight: 700;
        color: var(--text-primary);
        letter-spacing: 0.4px;
        text-transform: uppercase;
    }
    .gl-elo {
        font-size: 10px;
        color: var(--text-dim);
        margin-top: 2px;
        letter-spacing: 0.3px;
    }
    .gl-row {
        display: grid;
        grid-template-columns: 90px 1fr 60px 80px 70px;
        align-items: center;
        gap: 8px;
        padding: 4px 0;
        border-bottom: 1px solid var(--border-subtle);
    }
    .gl-row:last-child { border-bottom: none; }
    .gl-bet-type {
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.6px;
        color: var(--text-dim);
    }
    .gl-pick {
        font-weight: 600;
        color: var(--text-primary);
        font-size: 12px;
    }
    .gl-prob {
        text-align: right;
        color: var(--text-secondary);
        font-size: 12px;
        font-variant-numeric: tabular-nums;
    }
    .gl-bar-wrap { background: var(--border-subtle); border-radius: 2px; height: 5px; overflow: hidden; }
    .gl-bar-fill { height: 5px; border-radius: 2px; }
    .gl-edge-pos { color: var(--green);      font-size: 11px; font-weight: 700; text-align: right; }
    .gl-edge-neg { color: var(--red);        font-size: 11px; font-weight: 700; text-align: right; }
    .gl-edge-neu { color: var(--text-muted); font-size: 11px; text-align: right; }

    /* ── Tier badge pills ────────────────────────────────────────────────────── */
    .badge-PRIME  { background:#1a3a2a; color:var(--tier-prime); border:1px solid #2ea043; border-radius:3px; padding:1px 8px; font-size:10px; font-weight:700; letter-spacing:0.6px; }
    .badge-SHARP  { background:#1a2a3a; color:var(--tier-sharp); border:1px solid #388bfd; border-radius:3px; padding:1px 8px; font-size:10px; font-weight:700; letter-spacing:0.6px; }
    .badge-LEAN   { background:#3a2a1a; color:var(--tier-lean);  border:1px solid #d18616; border-radius:3px; padding:1px 8px; font-size:10px; font-weight:700; letter-spacing:0.6px; }
    .badge-PASS   { background:#222;    color:var(--tier-pass);  border:1px solid var(--text-dim); border-radius:3px; padding:1px 8px; font-size:10px; font-weight:700; letter-spacing:0.6px; }

    /* ── Terminal health monitor ─────────────────────────────────────────────── */
    .terminal-panel {
        background: var(--bg-page);
        border: 1px solid var(--border);
        border-radius: 4px;
        padding: 14px 18px;
        font-family: var(--font-mono);
        font-size: 12px;
        line-height: 1.7;
        color: var(--text-primary);
        margin-bottom: 10px;
    }
    .terminal-panel .t-sport  { color: var(--blue);     font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
    .terminal-panel .t-ok     { color: var(--green);    }
    .terminal-panel .t-warn   { color: var(--orange);   }
    .terminal-panel .t-err    { color: var(--red);      }
    .terminal-panel .t-dim    { color: var(--text-dim); }
    .terminal-panel .t-label  { color: var(--text-muted); }
    .terminal-panel .t-val    { color: var(--text-secondary); }
    .terminal-panel .t-sched  { color: #a5d6ff; }
    .terminal-refresh {
        font-size: 10px;
        color: var(--text-dim);
        text-align: right;
        letter-spacing: 0.4px;
        margin-bottom: 6px;
    }

    /* ── Perf table ──────────────────────────────────────────────────────────── */
    .perf-row {
        display: grid;
        grid-template-columns: 100px 70px 70px 90px 80px;
        gap: 0;
        padding: 5px 10px;
        border-bottom: 1px solid var(--border-subtle);
        font-size: 12px;
        align-items: center;
    }
    .perf-row:first-child { border-radius: 3px 3px 0 0; background: var(--bg-card-hover);
                             font-weight:700; font-size:10px; text-transform:uppercase;
                             letter-spacing:0.6px; color: var(--text-muted); }
    .perf-table { background: var(--bg-card); border:1px solid var(--border); border-radius:4px; overflow:hidden; margin-bottom:10px; }
</style>
""", unsafe_allow_html=True)


# ── Supabase client ───────────────────────────────────────────────────────────
@st.cache_resource
def get_supabase():
    try:
        from supabase import create_client
        # Streamlit Cloud: secrets set in UI
        # Local: falls back to env vars
        try:
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_KEY"]
        except Exception:
            import os
            url = os.getenv("SUPABASE_URL", "")
            key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            return None
        return create_client(url, key)
    except ImportError:
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fmt_time(ts):
    if not ts:
        return ""
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone as _tz
        s = str(ts).replace('Z', '+00:00')  # MLB API uses Z suffix; fromisoformat needs +00:00
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz.utc)
        ct = dt.astimezone(ZoneInfo("America/Chicago"))
        h = ct.hour % 12 or 12
        ampm = 'PM' if ct.hour >= 12 else 'AM'
        suffix = 'CDT' if ct.dst() and ct.dst().seconds else 'CST'
        return f"{h}:{ct.minute:02d} {ampm} {suffix}"
    except Exception:
        return ""


# ── Data fetchers ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_picks(sport: str, game_date: str, min_prob: float, min_edge: float,
                direction: Optional[str], tier_filter: list) -> pd.DataFrame:
    """
    Load today's smart picks directly from SQLite via SmartPickSelector (primary).
    Supabase is the fallback for Streamlit Cloud where local SQLite is unavailable.

    WHY SQLite is primary (verified 2026-04-06):
    - MLB has 0 is_smart_pick=True rows in Supabase (pp-sync never sets the flag for MLB),
      so Supabase-primary silently returns an empty picks list for every MLB game day.
    - Golf is entirely absent from Supabase (0 rows).
    - Supabase daily_props accumulates stale rows from superseded PP lines on upsert
      (unique key is game_date+player+prop+line, so old lines linger when PP adjusts),
      making Supabase counts inflate over time (~10-15% more rows than SQLite per day).
    - SmartPickSelector always reads the live SQLite prediction DB + today's PP lines,
      so it reflects the latest pp-sync output without stale accumulation.
    - Supabase free tier is ~85% full (~290k rows); SQLite stays local and doesn't count.

    Revert history: was briefly flipped to Supabase-primary on 2026-04-06; reverted
    same day after data audit showed MLB picks disappeared from the dashboard.
    """
    import sys
    from pathlib import Path
    root = Path(__file__).parent.parent
    sys.path.insert(0, str(root / "shared"))

    try:
        from smart_pick_selector import SmartPickSelector
        selector = SmartPickSelector(sport.lower())
        picks = selector.get_smart_picks(
            game_date=game_date,
            min_edge=min_edge,
            min_prob=min_prob,
            refresh_lines=False,  # use cached PP lines, don't re-fetch
        )
    except Exception:
        picks = None

    if not picks:
        # ── Supabase fallback (Streamlit Cloud — no local SQLite) ──────────────
        sb = get_supabase()
        if sb is None:
            return pd.DataFrame()
        try:
            r = (sb.table("daily_props")
                   .select("player_name,team,opponent,prop_type,line,odds_type,"
                           "ai_prediction,ai_probability,ai_edge,ai_tier,"
                           "ai_ev_4leg,game_time")
                   .eq("sport", sport)
                   .eq("game_date", game_date)
                   .eq("is_smart_pick", True)
                   .neq("status", "cancelled")
                   .lt("ai_probability", 0.95)
                   .gte("ai_edge", min_edge)
                   .gte("ai_probability", min_prob)
                   .execute())
            sb_rows = r.data or []
        except Exception:
            sb_rows = []
        if not sb_rows:
            return pd.DataFrame()
        rows = []
        for p in sb_rows:
            if direction and p.get("ai_prediction") != direction:
                continue
            tier = p.get("ai_tier") or "—"
            if tier_filter and tier not in tier_filter:
                continue
            rows.append({
                "player_name":    p.get("player_name", ""),
                "team":           p.get("team", ""),
                "opponent":       p.get("opponent", ""),
                "prop_type":      p.get("prop_type", ""),
                "line":           p.get("line", 0),
                "odds_type":      p.get("odds_type", "standard"),
                "ai_prediction":  p.get("ai_prediction", ""),
                "ai_probability": float(p.get("ai_probability") or 0),
                "ai_edge":        float(p.get("ai_edge") or 0),
                "ai_tier":        tier,
                "ai_ev_4leg":     p.get("ai_ev_4leg"),
                "game_time":      p.get("game_time"),
                "matchup":        f"{p.get('team','')} vs {p.get('opponent','')}",
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["Prob"]     = (df["ai_probability"] * 100).round(1).astype(str) + "%"
        df["Edge"]     = df["ai_edge"].round(1).apply(lambda x: f"+{x}%" if x >= 0 else f"{x}%")
        df["EV 4-leg"] = df["ai_ev_4leg"].apply(
            lambda x: f"+{x*100:.1f}%" if x and x > 0 else ("---" if not x else f"{x*100:.1f}%")
        )
        df["Line"]     = df["ai_prediction"] + " " + df["line"].astype(str)
        df["Prop"]     = df["prop_type"].str.upper().str.replace("_", " ")
        df["Matchup"]  = df["matchup"]
        df["Time"]     = df["game_time"].apply(_fmt_time)
        return df

    rows = []
    for p in picks:
        if direction and p.prediction != direction:
            continue
        if tier_filter and p.tier not in tier_filter:
            continue
        rows.append({
            "player_name": p.player_name,
            "team": p.team,
            "opponent": p.opponent,
            "prop_type": p.prop_type,
            "line": p.pp_line,
            "odds_type": p.pp_odds_type,
            "ai_prediction": p.prediction,
            "ai_probability": p.pp_probability,
            "ai_edge": p.edge,
            "ai_tier": p.tier,
            "ai_ev_4leg": p.ev_4leg,
            "game_time": None,   # not on SmartPick object; filled below from Supabase
            "matchup": f"{p.team} vs {p.opponent}",
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Enrich with game_time from prizepicks_lines.db keyed by team.
    # Same source sync_game_times() uses — no name-matching issues.
    try:
        import sqlite3 as _sqlite3
        pp_db = root / "shared" / "prizepicks_lines.db"
        pp_conn = _sqlite3.connect(str(pp_db))
        time_rows = pp_conn.execute('''
            SELECT team, MIN(start_time) as start_time
            FROM prizepicks_lines
            WHERE substr(start_time, 1, 10) = ?
              AND league = ?
              AND team NOT LIKE "%/%"
            GROUP BY team
        ''', [game_date, sport.upper()]).fetchall()
        pp_conn.close()
        team_times = {}
        for team, iso in time_rows:
            ts = iso[:19] + iso[23:] if iso and '.' in iso else iso
            if ts:
                team_times[team.upper()] = ts
        df["game_time"] = df["team"].apply(lambda t: team_times.get(str(t).upper()))
    except Exception:
        df["game_time"] = None  # don't fail picks display over missing game times

    df["Prob"]    = (df["ai_probability"] * 100).round(1).astype(str) + "%"
    df["Edge"]    = df["ai_edge"].round(1).apply(lambda x: f"+{x}%" if x >= 0 else f"{x}%")
    df["EV 4-leg"]= df["ai_ev_4leg"].apply(
        lambda x: f"+{x*100:.1f}%" if x and x > 0 else ("---" if not x else f"{x*100:.1f}%")
    )
    df["Line"]    = df["ai_prediction"] + " " + df["line"].astype(str)
    df["Prop"]    = df["prop_type"].str.upper().str.replace("_", " ")
    df["Matchup"] = df["matchup"]
    df["Time"]    = df["game_time"].apply(_fmt_time)
    return df


@st.cache_data(ttl=300)
def fetch_all_lines_for_players(
    sport: str,
    game_date: str,
    player_prop_pairs: tuple,   # tuple of (player_name, prop_type) — must be tuple for cache hashing
) -> pd.DataFrame:
    """Fetch ALL lines for qualifying player-prop combos (no edge/prob filter)."""
    sb = get_supabase()
    if sb is None or not player_prop_pairs:
        return pd.DataFrame()

    player_names = list({pair[0] for pair in player_prop_pairs})

    # Paginate — same pattern as fetch_recent_results()
    all_rows, page_size, offset = [], 1000, 0
    while True:
        r = (sb.table("daily_props")
               .select("player_name,prop_type,team,opponent,line,odds_type,"
                       "ai_prediction,ai_probability,ai_edge,game_time")
               .eq("sport", sport)
               .eq("game_date", game_date)
               .neq("status", "cancelled")
               .lt("ai_probability", 0.95)   # same noise-floor as fetch_picks
               .in_("player_name", player_names)
               .range(offset, offset + page_size - 1)
               .execute())
        batch = r.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # Post-filter: keep only prop_types that actually qualified
    # (prevents showing rebounds lines for a player who only qualified on points)
    valid = set(player_prop_pairs)
    df = df[df.apply(lambda r: (r["player_name"], r["prop_type"]) in valid, axis=1)].copy()

    df["Time"] = df["game_time"].apply(_fmt_time)
    df["Matchup"] = df["team"] + " vs " + df["opponent"]
    return df


# Break-even rates — sourced from shared/project_config.py
_BREAK_EVEN = _PROJECT_BREAK_EVEN
_ODDS_ABBREV = {"standard": "STD", "goblin": "GOB", "demon": "DEM"}


def render_line_cards(all_lines_df: pd.DataFrame, qualifying_df: pd.DataFrame):
    """
    Render each player-prop combo as a card row with colored pill badges per line.
    Groups by prop type. Players ordered by best qualifying edge descending.
    """
    qual_keys = set(zip(
        qualifying_df["player_name"],
        qualifying_df["prop_type"],
        qualifying_df["line"],
    ))

    # Player order: highest qualifying edge first
    best_edge = (qualifying_df.groupby("player_name")["ai_edge"]
                 .max().rename("_e").reset_index()
                 .sort_values("_e", ascending=False))
    player_order = best_edge["player_name"].tolist()

    df = all_lines_df.copy()
    props = sorted(df["prop_type"].unique())

    for prop in props:
        prop_df = df[df["prop_type"] == prop]
        # Players in edge order, then any extras not in qualifying list
        ordered = [p for p in player_order if p in prop_df["player_name"].values]
        ordered += [p for p in prop_df["player_name"].unique() if p not in ordered]

        n_rec = sum(
            1 for p in ordered
            for _, r in prop_df[prop_df["player_name"] == p].iterrows()
            if (p, prop, r["line"]) in qual_keys
        )
        label = prop.upper().replace("_", " ")
        with st.expander(f"{label}  —  {len(ordered)} players  ·  {n_rec} recommended", expanded=True):
            for player in ordered:
                prows = prop_df[prop_df["player_name"] == player].sort_values("line")
                if prows.empty:
                    continue
                r0 = prows.iloc[0]
                matchup = r0["Matchup"]
                time_str = r0["Time"]

                badges = []
                for _, r in prows.iterrows():
                    abbrev = _ODDS_ABBREV.get(r["odds_type"], "???")
                    prob = r["ai_probability"]
                    edge = r["ai_edge"]
                    edge_str = f"+{edge:.1f}%" if edge >= 0 else f"{edge:.1f}%"
                    text = f"{r['line']} {abbrev} · {r['ai_prediction']} {prob*100:.0f}% {edge_str}"

                    be = _BREAK_EVEN.get(r["odds_type"], 110 / 210)
                    is_rec = (player, prop, r["line"]) in qual_keys

                    if is_rec:
                        bg, fg, fw = "#1b4332", "#d1fae5", "bold"
                    elif prob >= be:
                        bg, fg, fw = "#14532d", "#bbf7d0", "normal"
                    else:
                        bg, fg, fw = "#3f1515", "#fca5a5", "normal"

                    badges.append(
                        f'<span style="background:{bg};color:{fg};font-weight:{fw};'
                        f'padding:3px 10px;border-radius:12px;font-size:12px;'
                        f'white-space:nowrap;display:inline-block">{text}</span>'
                    )

                badges_html = "&nbsp;".join(badges)
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:14px;'
                    f'padding:7px 2px;border-bottom:1px solid #2a2a2a;flex-wrap:wrap">'
                    f'<div style="min-width:150px;max-width:190px">'
                    f'<div style="font-size:13px;font-weight:600">{player}</div>'
                    f'<div style="font-size:11px;color:#888">{matchup}&nbsp;·&nbsp;{time_str}</div>'
                    f'</div>'
                    f'<div style="display:flex;gap:6px;flex-wrap:wrap">{badges_html}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


@st.cache_data(ttl=300)
def fetch_performance(sport: str) -> pd.DataFrame:
    sb = get_supabase()
    if sb is None:
        return pd.DataFrame()
    r = (sb.table("model_performance")
           .select("*")
           .eq("sport", sport)
           .order("game_date", desc=True)
           .limit(30)
           .execute())
    return pd.DataFrame(r.data) if r.data else pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_pnl_local(sport: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Read profit/outcome data directly from local SQLite prediction_outcomes.
    Used for the investor P&L section since Supabase daily_props lacks profit.
    Returns one row per graded prediction with columns:
        game_date, outcome, profit, ai_tier (if available)
    """
    import os as _os
    PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    db_map = {
        "NHL": _os.path.join(PROJECT_ROOT, "nhl", "database", "nhl_predictions_v2.db"),
        "NBA": _os.path.join(PROJECT_ROOT, "nba", "database", "nba_predictions.db"),
        "MLB": _os.path.join(PROJECT_ROOT, "mlb", "database", "mlb_predictions.db"),
        "GOLF": _os.path.join(PROJECT_ROOT, "golf", "database", "golf_predictions.db"),
    }
    db_path = db_map.get(sport.upper(), "")
    if not _os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path)
        # Try to join with predictions for tier; fall back if column missing
        try:
            df = pd.read_sql_query("""
                SELECT o.game_date, o.outcome, o.profit,
                       p.confidence_tier as ai_tier
                FROM prediction_outcomes o
                LEFT JOIN predictions p ON p.id = o.prediction_id
                WHERE o.game_date BETWEEN ? AND ?
                  AND o.outcome IN ('HIT','MISS')
                  AND o.profit IS NOT NULL
                ORDER BY o.game_date
            """, conn, params=(start_date, end_date))
        except Exception:
            df = pd.read_sql_query("""
                SELECT game_date, outcome, profit
                FROM prediction_outcomes
                WHERE game_date BETWEEN ? AND ?
                  AND outcome IN ('HIT','MISS')
                  AND profit IS NOT NULL
                ORDER BY game_date
            """, conn, params=(start_date, end_date))
            df["ai_tier"] = None
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_recent_results(sport: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch graded results between start_date and end_date (inclusive).
    Pages through all results to avoid the 1000-row Supabase default limit.
    """
    sb = get_supabase()
    if sb is None:
        return pd.DataFrame()

    all_rows = []
    page_size = 1000
    offset = 0

    while True:
        r = (sb.table("daily_props")
               .select("game_date,ai_prediction,ai_tier,result,ai_probability,prop_type,actual_value,odds_type")
               .eq("sport", sport)
               .eq("is_smart_pick", True)   # only picks that passed suppression + edge filter
               .gte("game_date", start_date)
               .lte("game_date", end_date)
               .not_.is_("result", "null")
               .gt("actual_value", 0)   # exclude DNP/ungraded rows (actual_value=0)
               .order("game_date", desc=False)
               .range(offset, offset + page_size - 1)
               .execute())
        batch = r.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


@st.cache_data(ttl=60)
def fetch_orchestrator_health() -> dict:
    """
    Read orchestrator state + local DB prediction counts for the health monitor.
    Cached for 60 seconds so the dashboard feels live without hammering disk.
    """
    import json as _json
    import sqlite3 as _sq
    from pathlib import Path as _Path

    root = _Path(__file__).parent.parent
    state_path = root / "data" / "orchestrator_state.json"

    # Load orchestrator state.json
    state = {}
    if state_path.exists():
        try:
            state = _json.loads(state_path.read_text())
        except Exception:
            pass

    # Sport metadata (schedules + db paths + config)
    SPORT_META = {
        "NHL": {
            "emoji": "🏒", "name": "NHL Hockey",
            "db": root / "nhl" / "database" / "nhl_predictions_v2.db",
            "pred_table": "predictions",
            "grading": "03:00", "pp_fetch": "03:30",
            "predictions": "04:00", "pp_sync": "13:00",
            "game_predictions": "09:00",
            "ml_combos": 11, "ml_target": 7500,
        },
        "NBA": {
            "emoji": "🏀", "name": "NBA Basketball",
            "db": root / "nba" / "database" / "nba_predictions.db",
            "pred_table": "predictions",
            "grading": "05:00", "pp_fetch": "05:30",
            "predictions": "06:00", "pp_sync": "12:30",
            "game_predictions": "09:30",
            "ml_combos": 14, "ml_target": 7500,
        },
        "MLB": {
            "emoji": "⚾", "name": "MLB Baseball",
            "db": root / "mlb" / "database" / "mlb_predictions.db",
            "pred_table": "predictions",
            "grading": "08:00", "pp_fetch": "08:30",
            "predictions": "12:00", "pp_sync": "15:00",
            "game_predictions": "09:45",
            "ml_combos": 30, "ml_target": 7500,
        },
        "GOLF": {
            "emoji": "⛳", "name": "PGA Tour Golf",
            "db": root / "golf" / "database" / "golf_predictions.db",
            "pred_table": "predictions",
            "grading": "08:00", "pp_fetch": "09:00",
            "predictions": "10:00", "pp_sync": "12:00",
            "game_predictions": None,
            "ml_combos": 4, "ml_target": 7500,
        },
    }

    result = {}
    for sport, meta in SPORT_META.items():
        s = state.get(sport.lower(), {})

        # Prediction count from local DB
        pred_count = 0
        try:
            conn = _sq.connect(str(meta["db"]))
            row = conn.execute(f"SELECT COUNT(*) FROM {meta['pred_table']}").fetchone()
            pred_count = row[0] if row else 0
            conn.close()
        except Exception:
            pass

        # Parse last-run timestamps
        def _fmt(ts):
            if not ts:
                return "—"
            try:
                dt = datetime.fromisoformat(ts)
                return dt.strftime("%b %d %H:%M")
            except Exception:
                return ts[:16]

        failures = s.get("consecutive_failures", 0)
        result[sport] = {
            "emoji": meta["emoji"],
            "name": meta["name"],
            "pred_count": pred_count,
            "ml_combos": meta["ml_combos"],
            "ml_target": meta["ml_target"],
            "started_at": _fmt(s.get("started_at")),
            "last_predict": _fmt(s.get("last_prediction_gen")),
            "last_grade": _fmt(s.get("last_grading")),
            "last_health": _fmt(s.get("last_health_check")),
            "total_runs": s.get("total_runs", 0),
            "consecutive_failures": failures,
            "ml_training_started": s.get("ml_training_started", False),
            "schedule": {
                "grading": meta["grading"],
                "pp_fetch": meta["pp_fetch"],
                "predictions": meta["predictions"],
                "pp_sync": meta["pp_sync"],
                "game_predictions": meta["game_predictions"],
            },
            "db_path": str(meta["db"]),
            "status": "ok" if failures == 0 else ("warn" if failures < 3 else "err"),
        }
    return result


@st.cache_data(ttl=3600)
def get_ml_model_info() -> dict:
    """Read model registry metadata from local filesystem. Cached 1 hour."""
    import json as _json
    from pathlib import Path as _Path
    root = _Path(__file__).parent.parent
    info = {}
    for sport in ["nba", "nhl", "mlb"]:
        registry = root / "ml_training" / "model_registry" / sport
        if not registry.exists():
            info[sport.upper()] = {"count": 0, "last_trained": "—", "avg_accuracy": None}
            continue
        last_trained, accs, count = None, [], 0
        for prop_dir in registry.iterdir():
            latest_file = prop_dir / "latest.txt"
            if not latest_file.exists():
                continue
            version = latest_file.read_text().strip()
            meta_path = prop_dir / version / "metadata.json"
            if not meta_path.exists():
                continue
            meta = _json.loads(meta_path.read_text())
            count += 1
            trained_at = meta.get("trained_at", "")[:10]
            if trained_at > (last_trained or ""):
                last_trained = trained_at
            accs.append(meta.get("test_accuracy", 0))
        info[sport.upper()] = {
            "count": count,
            "last_trained": last_trained or "—",
            "avg_accuracy": sum(accs) / len(accs) if accs else None,
        }
    return info


@st.cache_data(ttl=300)
def fetch_game_predictions(sport: str, game_date: str) -> pd.DataFrame:
    """Fetch game predictions from SQLite (local) for the Game Lines tab."""
    import sqlite3, os
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_map = {
        "NHL": os.path.join(PROJECT_ROOT, "nhl", "database", "nhl_predictions_v2.db"),
        "NBA": os.path.join(PROJECT_ROOT, "nba", "database", "nba_predictions.db"),
        "MLB": os.path.join(PROJECT_ROOT, "mlb", "database", "mlb_predictions.db"),
    }
    db_path = db_map.get(sport.upper(), "")
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path)
        try:
            df = pd.read_sql_query("""
                SELECT home_team, away_team, bet_type, bet_side, line,
                       prediction, probability, edge, confidence_tier,
                       odds_american, implied_probability,
                       model_type, home_elo, away_elo, elo_diff,
                       game_time
                FROM game_predictions
                WHERE game_date = ?
                ORDER BY game_time ASC, edge DESC
            """, conn, params=(game_date,))
        except Exception:
            # game_time column may not exist in older DBs
            df = pd.read_sql_query("""
                SELECT home_team, away_team, bet_type, bet_side, line,
                       prediction, probability, edge, confidence_tier,
                       odds_american, implied_probability,
                       model_type, home_elo, away_elo, elo_diff
                FROM game_predictions
                WHERE game_date = ?
                ORDER BY edge DESC
            """, conn, params=(game_date,))
            df["game_time"] = None
        conn.close()

        # PP abbreviations differ from our game_lines abbreviations for some NHL teams.
        # Expand lookup in both directions so either form matches.
        _PP_TO_STD = {'LA': 'LAK', 'NJ': 'NJD', 'SJ': 'SJS', 'TB': 'TBL'}
        _STD_TO_PP = {v: k for k, v in _PP_TO_STD.items()}

        # Enrich with game_time from prizepicks_lines.db (same source fetch_picks uses)
        try:
            pp_db = os.path.join(PROJECT_ROOT, "shared", "prizepicks_lines.db")
            if os.path.exists(pp_db):
                import sqlite3 as _sq2
                pp_conn = _sq2.connect(pp_db)
                time_rows = pp_conn.execute("""
                    SELECT team, MIN(start_time) as start_time
                    FROM prizepicks_lines
                    WHERE substr(start_time, 1, 10) = ?
                      AND league = ?
                      AND team NOT LIKE '%/%'
                    GROUP BY team
                """, [game_date, sport.upper()]).fetchall()
                pp_conn.close()
                # Build lookup with both PP and standard abbreviations as keys
                team_times = {}
                for row in time_rows:
                    if not row[1]:
                        continue
                    pp_abbr = row[0].upper()
                    team_times[pp_abbr] = row[1]
                    # Also register under the standard abbreviation if it differs
                    std_abbr = _PP_TO_STD.get(pp_abbr)
                    if std_abbr:
                        team_times[std_abbr] = row[1]
                if team_times:
                    df["game_time"] = df["home_team"].apply(
                        lambda t: team_times.get(str(t).upper())
                    )
        except Exception:
            pass  # game_time stays None — cards still render without it

        # MLB: PP has no MLB lines so no start_time from above. Fetch from MLB stats API.
        if sport.upper() == "MLB" and df["game_time"].isna().all():
            try:
                import requests as _req
                resp = _req.get(
                    f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={game_date}&hydrate=team",
                    timeout=5
                )
                if resp.status_code == 200:
                    mlb_times = {}  # home_team_abbr -> ISO game time string
                    for date_entry in resp.json().get("dates", []):
                        for game in date_entry.get("games", []):
                            home = game.get("teams", {}).get("home", {}).get("team", {})
                            abbr = home.get("abbreviation", "").upper()
                            gt = game.get("gameDate", "")  # UTC ISO: "2026-04-04T17:10:00Z"
                            if abbr and gt:
                                mlb_times[abbr] = gt
                    if mlb_times:
                        df["game_time"] = df["home_team"].apply(
                            lambda t: mlb_times.get(str(t).upper())
                        )
            except Exception:
                pass  # still no times — cards render without it

        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_game_outcomes(sport: str, days: int = 30) -> pd.DataFrame:
    """Fetch game prediction outcomes for performance tracking."""
    import sqlite3, os
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_map = {
        "NHL": os.path.join(PROJECT_ROOT, "nhl", "database", "nhl_predictions_v2.db"),
        "NBA": os.path.join(PROJECT_ROOT, "nba", "database", "nba_predictions.db"),
        "MLB": os.path.join(PROJECT_ROOT, "mlb", "database", "mlb_predictions.db"),
    }
    db_path = db_map.get(sport.upper(), "")
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("""
            SELECT game_date, bet_type, bet_side, confidence_tier,
                   prediction, outcome, profit, odds_american,
                   home_score, away_score, actual_margin, actual_total
            FROM game_prediction_outcomes
            WHERE graded_at >= date('now', ?)
              AND outcome IN ('HIT', 'MISS', 'PUSH')
            ORDER BY game_date DESC
        """, conn, params=(f"-{days} days",))
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_pipeline_status() -> dict:
    """Last prediction date + count per sport from daily_props."""
    sb = get_supabase()
    if sb is None:
        return {}
    status = {}
    for sport in ["NBA", "NHL", "MLB"]:
        r = (sb.table("daily_props")
               .select("game_date,status", count="exact")
               .eq("sport", sport)
               .order("game_date", desc=True)
               .limit(1)
               .execute())
        if r.data:
            last_date = r.data[0]["game_date"]
            r2 = (sb.table("daily_props")
                    .select("id", count="exact")
                    .eq("sport", sport)
                    .eq("game_date", last_date)
                    .execute())
            status[sport] = {"last_date": last_date, "count": r2.count or 0}
        else:
            status[sport] = {"last_date": "—", "count": 0}
    return status


@st.cache_data(ttl=3600)
def fetch_season_projections(stat_filter: str = None,
                              player_type: str = None,
                              team_filter: str = None,
                              min_confidence: str = 'LOW') -> pd.DataFrame:
    """Load MLB season projections from local SQLite season_projections table."""
    from pathlib import Path as _Path
    import sqlite3 as _sqlite3
    root = _Path(__file__).parent.parent
    db_path = root / 'mlb' / 'database' / 'mlb_predictions.db'
    _local_ok = db_path.exists()
    if not _local_ok:
        # ── Supabase fallback (Streamlit Cloud) ────────────────────────────────
        sb = get_supabase()
        if sb is None:
            return pd.DataFrame()
        try:
            r_season = (sb.table("mlb_season_projections")
                          .select("season").order("season", desc=True).limit(1).execute())
            if not r_season.data:
                return pd.DataFrame()
            latest_season = r_season.data[0]["season"]
            q = (sb.table("mlb_season_projections")
                   .select("player_name,team,player_type,stat,projection,"
                           "std_dev,confidence,seasons_used,age")
                   .eq("season", latest_season))
            if stat_filter and stat_filter != "All":
                q = q.eq("stat", stat_filter)
            if player_type and player_type != "All":
                q = q.eq("player_type", player_type.lower())
            if team_filter and team_filter != "All":
                q = q.eq("team", team_filter)
            r = q.order("projection", desc=True).execute()
            rows = r.data or []
        except Exception:
            rows = []
        if not rows:
            return pd.DataFrame()
        conf_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "VERY LOW": 0}
        min_conf_val = conf_order.get(min_confidence, 0)
        df = pd.DataFrame(rows)
        df["_conf_val"] = df["confidence"].map(conf_order).fillna(0)
        df = df[df["_conf_val"] >= min_conf_val].drop(columns=["_conf_val"])
        return df
    try:
        conn = _sqlite3.connect(str(db_path))
        query = '''
            SELECT player_name, team, player_type, stat, projection,
                   std_dev, confidence, seasons_used, age
            FROM season_projections
            WHERE season = (SELECT MAX(season) FROM season_projections)
        '''
        params = []
        if stat_filter and stat_filter != 'All':
            query += ' AND stat = ?'
            params.append(stat_filter)
        if player_type and player_type != 'All':
            query += ' AND player_type = ?'
            params.append(player_type.lower())
        if team_filter and team_filter != 'All':
            query += ' AND team = ?'
            params.append(team_filter)
        conf_order = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'VERY LOW': 0}
        min_conf_val = conf_order.get(min_confidence, 0)
        query += ' ORDER BY projection DESC'
        rows = conn.execute(query, params).fetchall()
        conn.close()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=[
            'player_name', 'team', 'player_type', 'stat',
            'projection', 'std_dev', 'confidence', 'seasons_used', 'age'
        ])
        # Filter by confidence
        df['_conf_val'] = df['confidence'].map(conf_order).fillna(0)
        df = df[df['_conf_val'] >= min_conf_val].drop(columns=['_conf_val'])
        return df
    except Exception as e:
        return pd.DataFrame()


@st.cache_data(ttl=1800)
def fetch_szln_picks(stat_filter: str = None,
                     direction_filter: str = None,
                     min_edge: float = 0.0,
                     player_type_filter: str = None) -> pd.DataFrame:
    """Load ML SZLN picks from season_prop_ml_picks table."""
    from pathlib import Path as _Path
    import sqlite3 as _sqlite3
    root = _Path(__file__).parent.parent
    db_path = root / 'mlb' / 'database' / 'mlb_predictions.db'
    _local_ok = db_path.exists()
    if not _local_ok:
        # ── Supabase fallback (Streamlit Cloud) ────────────────────────────────
        sb = get_supabase()
        if sb is None:
            return pd.DataFrame()
        try:
            q = (sb.table("mlb_szln_picks")
                   .select("player_name,team,player_type,stat,pp_stat_type,"
                           "line,direction,probability,edge,projection,std_dev,"
                           "confidence,model_used,recommendation,fetched_at"))
            if stat_filter and stat_filter != "All":
                q = q.eq("stat", stat_filter)
            if direction_filter and direction_filter != "All":
                q = q.eq("direction", direction_filter)
            if player_type_filter and player_type_filter != "All":
                q = q.eq("player_type", player_type_filter.lower())
            if min_edge and min_edge > 0:
                q = q.gte("edge", min_edge)
            r = q.order("edge", desc=True).execute()
            rows = r.data or []
        except Exception:
            rows = []
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
    try:
        conn = _sqlite3.connect(str(db_path))
        # Check table exists
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='season_prop_ml_picks'"
        ).fetchone()
        if not exists:
            conn.close()
            return pd.DataFrame()

        # Pull the single latest batch (max fetched_at) for current season
        latest_fetch = conn.execute(
            "SELECT MAX(fetched_at) FROM season_prop_ml_picks "
            "WHERE season = (SELECT MAX(season) FROM season_prop_ml_picks)"
        ).fetchone()[0]
        if not latest_fetch:
            conn.close()
            return pd.DataFrame()

        query = '''
            SELECT player_name, team, player_type, stat, pp_stat_type,
                   line, direction, probability, edge, projection, std_dev,
                   confidence, model_used, recommendation, fetched_at
            FROM season_prop_ml_picks
            WHERE fetched_at = ?
        '''
        params = [latest_fetch]
        if stat_filter and stat_filter != 'All':
            query += ' AND stat = ?'
            params.append(stat_filter)
        if direction_filter and direction_filter != 'All':
            query += ' AND direction = ?'
            params.append(direction_filter)
        if player_type_filter and player_type_filter != 'All':
            query += ' AND player_type = ?'
            params.append(player_type_filter.lower())
        if min_edge and min_edge > 0:
            query += ' AND edge >= ?'
            params.append(min_edge)
        query += ' ORDER BY edge DESC'
        rows = conn.execute(query, params).fetchall()
        conn.close()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=[
            'player_name', 'team', 'player_type', 'stat', 'pp_stat_type',
            'line', 'direction', 'probability', 'edge', 'projection', 'std_dev',
            'confidence', 'model_used', 'recommendation', 'fetched_at',
        ])
        return df
    except Exception:
        return pd.DataFrame()


def _evaluate_line(player_name: str, stat: str, line: float,
                   direction: str) -> Optional[dict]:
    """Evaluate a single sportsbook line against our season projection."""
    from pathlib import Path as _Path
    import sqlite3 as _sqlite3, math as _math
    root = _Path(__file__).parent.parent
    db_path = root / 'mlb' / 'database' / 'mlb_predictions.db'
    _local_ok = db_path.exists()
    if not _local_ok:
        # ── Supabase fallback (Streamlit Cloud) ────────────────────────────────
        sb = get_supabase()
        if sb is None:
            return None
        try:
            r = (sb.table("mlb_season_projections")
                   .select("projection,std_dev,confidence,seasons_used,age,team")
                   .ilike("player_name", f"%{player_name.strip()}%")
                   .eq("stat", stat)
                   .order("confidence", desc=True)
                   .limit(1)
                   .execute())
            row_data = r.data[0] if r.data else None
        except Exception:
            row_data = None
        if not row_data:
            return None
        proj     = row_data["projection"]
        std_dev  = row_data["std_dev"] or max(proj * 0.18, 1.0)
        conf     = row_data["confidence"]
        seasons  = row_data["seasons_used"]
        age      = row_data["age"]
        team     = row_data["team"]
        # --- shared probability calc (duplicated below for SQLite path) ---
        z = (line - proj) / std_dev
        def _erf(x):
            sign = 1 if x >= 0 else -1
            x = abs(x)
            t = 1.0 / (1.0 + 0.3275911 * x)
            y = 1.0 - (((((1.061405429*t - 1.453152027)*t) + 1.421413741)*t
                          - 0.284496736)*t + 0.254829592)*t*(_math.exp(-x*x))
            return sign * y
        p_over = 0.5 * (1 - _erf(z / 1.4142))
        prob = p_over if direction == "OVER" else (1 - p_over)
        edge = round((prob - 0.524) * 100, 2)
        if abs(edge) < 3:
            rec = "PASS — too close to line"
        elif prob >= 0.65:
            rec = f"STRONG {direction}"
        elif prob >= 0.57:
            rec = f"LEAN {direction}"
        else:
            rec = "PASS — edge insufficient"
        return {
            "player_name": player_name, "stat": stat, "line": line,
            "direction": direction, "projection": round(proj, 1),
            "probability": round(prob * 100, 1),
            "edge": edge, "recommendation": rec,
            "confidence": conf, "seasons_used": seasons,
            "age": age, "team": team,
        }
    try:
        conn = _sqlite3.connect(str(db_path))
        row = conn.execute('''
            SELECT projection, std_dev, confidence, seasons_used, age, team
            FROM season_projections
            WHERE lower(player_name) LIKE lower(?)
              AND stat = ?
              AND season = (SELECT MAX(season) FROM season_projections)
            ORDER BY confidence DESC LIMIT 1
        ''', (f'%{player_name.strip()}%', stat)).fetchone()
        conn.close()
        if not row:
            return None
        proj, std_dev, conf, seasons, age, team = row
        std_dev = std_dev or max(proj * 0.18, 1.0)
        # Normal CDF: P(X > line)
        z = (line - proj) / std_dev
        def erf(x):
            sign = 1 if x >= 0 else -1
            x = abs(x)
            t = 1.0 / (1.0 + 0.3275911 * x)
            y = 1.0 - (((((1.061405429*t - 1.453152027)*t) + 1.421413741)*t
                          - 0.284496736)*t + 0.254829592)*t*(_math.exp(-x*x))
            return sign * y
        p_over = 0.5 * (1 - erf(z / 1.4142))
        prob = p_over if direction == 'OVER' else (1 - p_over)
        edge = round((prob - 0.524) * 100, 2)
        if abs(edge) < 3:
            rec = 'PASS — too close to line'
        elif prob >= 0.65:
            rec = f'STRONG {direction}'
        elif prob >= 0.57:
            rec = f'LEAN {direction}'
        else:
            rec = 'PASS — edge insufficient'
        return {
            'player_name': player_name, 'stat': stat, 'line': line,
            'direction': direction, 'projection': round(proj, 1),
            'probability': round(prob * 100, 1),
            'edge': edge, 'recommendation': rec,
            'confidence': conf, 'seasons_used': seasons,
            'age': age, 'team': team,
        }
    except Exception:
        return None


@st.cache_data(ttl=900)
def fetch_hb_picks(run_date: str = None) -> dict:
    """Load NHL hits/blocks picks from hits_blocks.db for the given date (or latest)."""
    from pathlib import Path as _Path
    import sqlite3 as _sqlite3
    db_path = _Path(__file__).parent.parent / "nhl" / "database" / "hits_blocks.db"
    _local_ok = db_path.exists()
    if not _local_ok:
        # ── Supabase fallback (Streamlit Cloud) ────────────────────────────────
        sb = get_supabase()
        if sb is None:
            return {}
        try:
            q = (sb.table("nhl_hits_blocks_picks")
                   .select("run_date,generated_at,raw_output,model,"
                           "prompt_tokens,completion_tokens,games_count"))
            if run_date:
                q = q.eq("run_date", run_date)
            else:
                q = q.order("run_date", desc=True).limit(1)
            r = q.execute()
            row_data = r.data[0] if r.data else None
        except Exception:
            row_data = None
        if not row_data:
            return {}
        return row_data
    try:
        conn = _sqlite3.connect(str(db_path))
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_picks'"
        ).fetchone()
        if not exists:
            conn.close()
            return {}
        if run_date:
            row = conn.execute(
                "SELECT run_date, generated_at, raw_output, model, "
                "prompt_tokens, completion_tokens, games_count "
                "FROM daily_picks WHERE run_date = ?", (run_date,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT run_date, generated_at, raw_output, model, "
                "prompt_tokens, completion_tokens, games_count "
                "FROM daily_picks ORDER BY run_date DESC LIMIT 1"
            ).fetchone()
        conn.close()
        if not row:
            return {}
        keys = ["run_date", "generated_at", "raw_output", "model",
                "prompt_tokens", "completion_tokens", "games_count"]
        return dict(zip(keys, row))
    except Exception:
        return {}


@st.cache_data(ttl=900)
def fetch_hb_history(n: int = 14) -> list:
    """Return recent dates that have picks saved."""
    from pathlib import Path as _Path
    import sqlite3 as _sqlite3
    db_path = _Path(__file__).parent.parent / "nhl" / "database" / "hits_blocks.db"
    _local_ok = db_path.exists()
    if not _local_ok:
        # ── Supabase fallback (Streamlit Cloud) ────────────────────────────────
        sb = get_supabase()
        if sb is None:
            return []
        try:
            r = (sb.table("nhl_hits_blocks_picks")
                   .select("run_date")
                   .order("run_date", desc=True)
                   .limit(n)
                   .execute())
            return [row["run_date"] for row in (r.data or [])]
        except Exception:
            return []
    try:
        conn = _sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT run_date FROM daily_picks ORDER BY run_date DESC LIMIT ?", (n,)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


@st.cache_data(ttl=300)
def fetch_golf_predictions(game_date: str) -> pd.DataFrame:
    """Load golf predictions from local SQLite for a given date."""
    from pathlib import Path as _Path
    import sqlite3 as _sqlite3
    db_path = _Path(__file__).parent.parent / "golf" / "database" / "golf_predictions.db"
    if not db_path.exists():
        return pd.DataFrame()
    try:
        conn = _sqlite3.connect(str(db_path))
        rows = conn.execute('''
            SELECT p.id, p.player_name, p.tournament_name, p.prop_type, p.line,
                   p.prediction, p.probability, p.round_number,
                   o.outcome, o.actual_value
            FROM predictions p
            LEFT JOIN prediction_outcomes o ON o.prediction_id = p.id
            WHERE p.game_date = ?
            ORDER BY p.probability DESC
        ''', (game_date,)).fetchall()
        conn.close()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=[
            'id', 'player_name', 'tournament_name', 'prop_type', 'line',
            'prediction', 'probability', 'round_number', 'outcome', 'actual_value'
        ])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_golf_performance(days: int = 30) -> pd.DataFrame:
    """Load graded golf predictions for performance analysis."""
    from pathlib import Path as _Path
    import sqlite3 as _sqlite3
    from datetime import date as _date, timedelta as _td
    db_path = _Path(__file__).parent.parent / "golf" / "database" / "golf_predictions.db"
    if not db_path.exists():
        return pd.DataFrame()
    try:
        since = (_date.today() - _td(days=days)).isoformat()
        conn = _sqlite3.connect(str(db_path))
        rows = conn.execute('''
            SELECT p.game_date, p.player_name, p.tournament_name, p.prop_type, p.line,
                   p.prediction, p.probability, p.round_number,
                   o.outcome, o.actual_value
            FROM predictions p
            JOIN prediction_outcomes o ON o.prediction_id = p.id
            WHERE p.game_date >= ?
            ORDER BY p.game_date DESC
        ''', (since,)).fetchall()
        conn.close()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=[
            'game_date', 'player_name', 'tournament_name', 'prop_type', 'line',
            'prediction', 'probability', 'round_number', 'outcome', 'actual_value'
        ])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def fetch_golf_ml_readiness() -> dict:
    """Return graded count per prop/line combo for ML readiness tracking."""
    from pathlib import Path as _Path
    import sqlite3 as _sqlite3
    db_path = _Path(__file__).parent.parent / "golf" / "database" / "golf_predictions.db"
    if not db_path.exists():
        return {}
    try:
        conn = _sqlite3.connect(str(db_path))
        rows = conn.execute('''
            SELECT p.prop_type, p.line, COUNT(*) as cnt
            FROM prediction_outcomes o
            JOIN predictions p ON o.prediction_id = p.id
            GROUP BY p.prop_type, p.line
        ''').fetchall()
        total = conn.execute('SELECT COUNT(*) FROM predictions').fetchone()[0]
        graded = conn.execute('SELECT COUNT(*) FROM prediction_outcomes').fetchone()[0]
        conn.close()
        combos = {f"{r[0]}_{r[1]}": r[2] for r in rows}
        combos['_total_predictions'] = total
        combos['_total_graded'] = graded
        return combos
    except Exception:
        return {}


# ── Main app ──────────────────────────────────────────────────────────────────
def main():
    st.markdown(
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:16px;font-weight:700;'
        f'letter-spacing:1.5px;text-transform:uppercase;color:#e6edf3;padding:6px 0 0 0;">'
        f'FreePicks Dashboard</div>'
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#484f58;'
        f'letter-spacing:0.4px;margin-bottom:10px;">'
        f'Last refresh: {datetime.now().strftime("%b %d %Y  %H:%M")}</div>',
        unsafe_allow_html=True,
    )

    sb = get_supabase()
    if sb is None:
        st.error("Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY.")
        st.info("Local run: set env vars.  Streamlit Cloud: add in app Secrets UI.")
        return

    # ── Top-level tabs ────────────────────────────────────────────────────────
    tab_top, tab_picks, tab_games, tab_perf, tab_season, tab_hb, tab_golf, tab_statbot, tab_system = st.tabs(
        ["Top Plays", "Today's Picks", "Game Lines", "Performance",
         "MLB Season Props", "NHL Hits & Blocks", "Golf", "StatBot", "System"]
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 0 — TOP PLAYS  (default home screen)
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_top:
        tp_date = date.today().isoformat()
        st.markdown(
            f'<div style="font-size:13px;color:#8b949e;margin-bottom:16px;">'
            f'Best picks for <b style="color:#c9d1d9">{tp_date}</b> &nbsp;·&nbsp; '
            f'Top 6 per sport by edge &nbsp;·&nbsp; T1-ELITE and T2-STRONG only</div>',
            unsafe_allow_html=True,
        )

        _tp_tier_style = {
            "T1-ELITE":  "background:#1a3a2a;color:#3fb950;border:1px solid #2ea043;",
            "T2-STRONG": "background:#1a2a3a;color:#58a6ff;border:1px solid #388bfd;",
            "T3-GOOD":   "background:#3a2a1a;color:#f0883e;border:1px solid #d18616;",
        }
        _tp_base_badge = "border-radius:10px;padding:2px 9px;font-size:10px;font-weight:700;letter-spacing:0.5px;"

        def _render_top_plays(sport: str, accent: str):
            df_tp = fetch_picks(
                sport, tp_date,
                min_prob=0.0, min_edge=0.0,
                direction=None, tier_filter=[],
            )
            if df_tp.empty:
                st.caption(f"No {sport} picks available for today.")
                return

            # Keep only T1-ELITE and T2-STRONG; fall back to top-6 by edge if none qualify
            elite = df_tp[df_tp["ai_tier"].isin(["T1-ELITE", "T2-STRONG"])].copy() if "ai_tier" in df_tp.columns else pd.DataFrame()
            top_df = elite if not elite.empty else df_tp.copy()
            top_df = top_df.sort_values("ai_edge", ascending=False).head(6)

            for _, r in top_df.iterrows():
                player   = r.get("player_name", "")
                prop     = str(r.get("prop_type", "")).upper().replace("_", " ")
                line     = r.get("line", "")
                pred     = r.get("ai_prediction", "")
                prob     = float(r.get("ai_probability") or 0)
                edge     = float(r.get("ai_edge") or 0)
                odds_t   = str(r.get("odds_type", "standard")).lower()
                tier     = str(r.get("ai_tier", ""))
                matchup  = r.get("matchup", "")
                time_str = r.get("Time", "")

                prob_pct  = f"{prob*100:.1f}%"
                edge_sign = f"+{edge:.1f}%" if edge >= 0 else f"{edge:.1f}%"
                edge_col  = "#3fb950" if edge >= 0 else "#f85149"
                bar_w     = min(int(prob * 100), 100)
                bar_col   = "#3fb950" if prob >= 0.62 else ("#58a6ff" if prob >= 0.55 else "#f0883e")

                badge_s = _tp_tier_style.get(tier, "background:#222;color:#8b949e;border:1px solid #484f58;")
                badge_html = f'<span style="{badge_s}{_tp_base_badge}">{tier or "—"}</span>' if tier else ""

                odds_label = {"goblin": "GOBLIN", "demon": "DEMON"}.get(odds_t, "")
                odds_html  = (
                    f'<span style="background:#2a1a3a;color:#bc8cff;border:1px solid #7c3aed;'
                    f'{_tp_base_badge}margin-left:6px;">{odds_label}</span>'
                ) if odds_label else ""

                sub_line = f"{matchup}" + (f" · {time_str}" if time_str else "")

                card_html = f"""
<div style="background:#161b22;border:1px solid #30363d;border-radius:10px;
            padding:12px 16px;margin-bottom:8px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
    <div>
      <div style="font-size:14px;font-weight:700;color:#e6edf3;">{player}</div>
      <div style="font-size:11px;color:#8b949e;margin-top:2px;">{sub_line}</div>
    </div>
    <div style="display:flex;gap:4px;align-items:center;">{badge_html}{odds_html}</div>
  </div>
  <div style="display:flex;align-items:center;gap:10px;">
    <span style="font-size:13px;font-weight:600;color:#c9d1d9;min-width:80px;">
      {pred} {line} {prop}
    </span>
    <span style="font-size:13px;color:#c9d1d9;font-variant-numeric:tabular-nums;width:46px;text-align:right;">
      {prob_pct}
    </span>
    <div style="flex:1;background:#21262d;border-radius:4px;height:6px;overflow:hidden;">
      <div style="width:{bar_w}%;height:6px;background:{bar_col};border-radius:4px;"></div>
    </div>
    <span style="font-size:13px;font-weight:700;color:{edge_col};width:52px;text-align:right;">
      {edge_sign}
    </span>
  </div>
</div>"""
                st.markdown(card_html, unsafe_allow_html=True)

        nhl_col, nba_col = st.columns(2)
        with nhl_col:
            st.markdown('<div style="font-size:15px;font-weight:700;color:#58a6ff;margin-bottom:10px;">NHL</div>', unsafe_allow_html=True)
            _render_top_plays("NHL", "#58a6ff")
        with nba_col:
            st.markdown('<div style="font-size:15px;font-weight:700;color:#3fb950;margin-bottom:10px;">NBA</div>', unsafe_allow_html=True)
            _render_top_plays("NBA", "#3fb950")

        if st.button("Refresh Top Plays", key="tp_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1 — TODAY'S PICKS
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_picks:
        # Filters row (compact for mobile)
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        with c1:
            sport = st.selectbox("Sport", ["NBA", "NHL", "MLB"], label_visibility="collapsed")
        with c2:
            game_date = st.date_input("Date", value=date.today(),
                                      label_visibility="collapsed").isoformat()
        with c3:
            direction = st.selectbox("Direction", ["Both", "OVER", "UNDER"],
                                     label_visibility="collapsed")
            direction = None if direction == "Both" else direction
        with c4:
            if st.button("Refresh", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

        with st.expander("More filters", expanded=False):
            fc1, fc2 = st.columns(2)
            with fc1:
                min_prob = st.slider("Min probability %", 50, 90, 56) / 100
                min_edge = st.slider("Min edge %", 0, 30, 5)
            with fc2:
                all_tiers = ["T1-ELITE", "T2-STRONG", "T3-GOOD", "T4-LEAN"]
                tier_filter = st.multiselect("Tiers", all_tiers,
                                             default=["T1-ELITE", "T2-STRONG", "T3-GOOD"])

        df = fetch_picks(sport, game_date, min_prob, min_edge, direction, tier_filter)

        if df.empty:
            st.warning(f"No picks for {sport} on {game_date} with current filters.")
        else:
            # ── Prop / Player / Team checkboxes (populated from live data) ────────
            with st.expander("Filter by Props / Players / Teams", expanded=False):
                xc1, xc2, xc3 = st.columns([1, 1, 1])

                with xc1:
                    all_props = sorted(df["Prop"].unique().tolist())
                    prop_filter = st.multiselect(
                        "Props", all_props, default=all_props, key="prop_cb"
                    )

                with xc2:
                    player_search = st.text_input(
                        "Search player", value="", key="player_search",
                        placeholder="e.g. LeBron"
                    )

                with xc3:
                    # Extract unique teams from Matchup column (format: "AWAY @ HOME")
                    teams_raw = set()
                    for matchup in df["Matchup"].dropna().unique():
                        for t in str(matchup).replace(" @ ", "@").split("@"):
                            t = t.strip().split(" ")[0]  # grab team abbrev before any extra text
                            if t:
                                teams_raw.add(t)
                    all_teams = sorted(teams_raw)
                    team_filter = st.multiselect(
                        "Teams", all_teams, default=all_teams, key="team_cb"
                    )

            # Apply prop / player / team filters
            if prop_filter:
                df = df[df["Prop"].isin(prop_filter)]
            if player_search.strip():
                df = df[df["player_name"].str.contains(player_search.strip(), case=False, na=False)]
            if team_filter and len(team_filter) < len(all_teams):
                df = df[df["Matchup"].apply(
                    lambda m: any(t in str(m) for t in team_filter)
                )]

            if df.empty:
                st.warning("No picks match the current prop/player/team filters.")
                st.stop()

            # Summary metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Picks", len(df))
            m2.metric("T1-ELITE", len(df[df["ai_tier"] == "T1-ELITE"]))
            m3.metric("Avg Prob", f"{df['ai_probability'].mean()*100:.1f}%")
            m4.metric("Avg Edge", f"+{df['ai_edge'].mean():.1f}%")

            st.divider()

            # Inner tabs
            pt1, pt2, pt3, pt4 = st.tabs(["All Picks", "By Prop", "Parlay Builder", "Line Compare"])

            display_cols = ["player_name", "Matchup", "Time", "Prop", "Line",
                            "odds_type", "Prob", "Edge", "ai_tier", "EV 4-leg"]
            col_labels = {
                "player_name": "Player", "odds_type": "Type", "ai_tier": "Tier"
            }

            with pt1:
                sort_by = st.selectbox("Sort by",
                    ["Edge", "Probability", "Tier"], key="sort_all")
                sort_map = {"Edge": "ai_edge", "Probability": "ai_probability",
                            "Tier": "ai_tier"}
                df_sorted = df.sort_values(sort_map[sort_by],
                    ascending=(sort_by == "Tier"))
                st.dataframe(
                    df_sorted[display_cols].rename(columns=col_labels),
                    use_container_width=True, hide_index=True, height=420
                )

            with pt2:
                for prop in sorted(df["Prop"].unique()):
                    sub = df[df["Prop"] == prop].sort_values("ai_edge", ascending=False)
                    with st.expander(f"{prop}  ({len(sub)})", expanded=False):
                        st.dataframe(
                            sub[["player_name", "Line", "Prob", "Edge", "ai_tier"]]
                              .rename(columns={"player_name": "Player",
                                               "ai_tier": "Tier"}),
                            use_container_width=True, hide_index=True
                        )

            with pt3:
                st.markdown("**Select picks to build a parlay:**")
                payouts = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 25.0}
                st.info("Payouts: 2-leg 3x · 3-leg 5x · 4-leg 10x · 5-leg 20x · 6-leg 25x")

                top20 = df.sort_values("ai_edge", ascending=False).head(20)
                selected = []
                for _, row in top20.iterrows():
                    tier_icon = {"T1-ELITE": "🟢", "T2-STRONG": "🔵",
                                 "T3-GOOD": "🟡", "T4-LEAN": "🟠"}.get(row["ai_tier"], "⚪")
                    label = (f"{tier_icon} {row['player_name']}  "
                             f"{row['Line']} {row['Prop']}  "
                             f"({row['Prob']} | +{row['ai_edge']:.1f}%)")
                    if st.checkbox(label, key=f"p_{row.name}"):
                        selected.append(row)

                if selected:
                    st.divider()
                    combined = 1.0
                    for r in selected:
                        combined *= r["ai_probability"]
                    legs = len(selected)
                    payout = payouts.get(min(legs, 6), 25.0)
                    ev = combined * payout - 1

                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("Legs", legs)
                    mc2.metric("Parlay Prob", f"{combined*100:.2f}%")
                    mc3.metric("Payout", f"{payout}x")
                    mc4.metric("EV", f"{ev*100:+.1f}%")

                    if ev > 0:
                        st.success(f"Positive EV parlay! {ev*100:.1f}% edge.")
                    else:
                        st.warning("Negative EV — consider higher confidence picks.")

            with pt4:
                player_prop_pairs = tuple(sorted(set(zip(df["player_name"], df["prop_type"]))))

                with st.spinner("Loading all lines..."):
                    all_lines_df = fetch_all_lines_for_players(sport, game_date, player_prop_pairs)

                if all_lines_df.empty:
                    st.warning("No line data returned. Try refreshing.")
                else:
                    n_players = all_lines_df["player_name"].nunique()
                    n_lines   = len(all_lines_df)
                    # Legend inline with caption
                    st.markdown(
                        f"**{n_players} players · {n_lines} lines** &nbsp;&nbsp;"
                        "<span style='background:#1b4332;color:#d1fae5;padding:2px 8px;"
                        "border-radius:3px;font-size:11px'>Recommended</span>&nbsp;"
                        "<span style='background:#14532d;color:#bbf7d0;padding:2px 8px;"
                        "border-radius:3px;font-size:11px'>Above break-even</span>&nbsp;"
                        "<span style='background:#3f1515;color:#fca5a5;padding:2px 8px;"
                        "border-radius:3px;font-size:11px'>Below break-even</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown("")
                    render_line_cards(all_lines_df, df)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB — GAME LINES (Moneyline, Spread, Total predictions)
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_games:
        hdr1, hdr2, hdr3, hdr4 = st.columns([1, 1, 1, 1])
        with hdr1:
            gl_sport = st.selectbox("Sport", ["NHL", "NBA", "MLB"],
                                     key="gl_sport", label_visibility="collapsed")
        with hdr2:
            gl_date = st.date_input("Date", value=date.today(),
                                     key="gl_date", label_visibility="collapsed").isoformat()
        with hdr3:
            gl_tier = st.selectbox("Tier", ["All", "PRIME", "SHARP", "LEAN"],
                                    key="gl_tier", label_visibility="collapsed")
        with hdr4:
            if st.button("Refresh", key="gl_refresh", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

        gdf = fetch_game_predictions(gl_sport, gl_date)

        if gdf.empty:
            st.info(f"No game predictions for {gl_sport} on {gl_date}. "
                    f"Run: `python {gl_sport.lower()}/scripts/generate_game_predictions.py {gl_date}`")
        else:
            if gl_tier != "All":
                gdf = gdf[gdf["confidence_tier"] == gl_tier]

            # ── Summary bar ───────────────────────────────────────────────────
            games_count = len(gdf[["home_team", "away_team"]].drop_duplicates())
            prime_sharp_count = len(gdf[gdf["confidence_tier"].isin(["PRIME", "SHARP"])])
            avg_edge = gdf["edge"].mean() * 100 if not gdf.empty else 0
            # Avg prob: only the favorable side per bet (prob >= 0.50) — avoids
            # the complementary-pair cancellation that gives a flat 50%.
            fav = gdf[gdf["probability"] >= 0.50]
            avg_prob = fav["probability"].mean() * 100 if not fav.empty else 50.0

            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("Games", games_count)
            sm2.metric("PRIME + SHARP", prime_sharp_count)
            sm3.metric("Avg Probability", f"{avg_prob:.1f}%")
            sm4.metric("Avg Edge", f"{avg_edge:+.1f}%")

            st.divider()

            # ── Game cards — one card per matchup, all bet types together ────────
            # All styling is inline — Streamlit strips CSS class names with
            # uppercase letters (badge-PRIME etc.) and misparses multiline HTML.

            # Shared inline style constants
            _C = {
                "card":    "background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px 20px;margin-bottom:12px;",
                "header":  "display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #21262d;",
                "matchup": "font-size:17px;font-weight:700;color:#e6edf3;letter-spacing:0.3px;",
                "elo":     "font-size:12px;color:#8b949e;margin-top:3px;",
                "row":     "display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #21262d;",
                "row_last":"display:flex;align-items:center;gap:10px;padding:7px 0;",
                "label":   "width:110px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.6px;color:#8b949e;flex-shrink:0;",
                "pick":    "flex:1;font-size:14px;font-weight:600;color:#e6edf3;",
                "pct":     "width:52px;text-align:right;font-size:14px;color:#c9d1d9;font-variant-numeric:tabular-nums;",
                "bar_bg":  "flex:1;background:#21262d;border-radius:4px;height:7px;overflow:hidden;min-width:60px;",
                "badge": {
                    "PRIME": "background:#1a3a2a;color:#3fb950;border:1px solid #2ea043;border-radius:12px;padding:3px 12px;font-size:12px;font-weight:700;letter-spacing:0.5px;white-space:nowrap;",
                    "SHARP": "background:#1a2a3a;color:#58a6ff;border:1px solid #388bfd;border-radius:12px;padding:3px 12px;font-size:12px;font-weight:700;letter-spacing:0.5px;white-space:nowrap;",
                    "LEAN":  "background:#3a2a1a;color:#f0883e;border:1px solid #d18616;border-radius:12px;padding:3px 12px;font-size:12px;font-weight:700;letter-spacing:0.5px;white-space:nowrap;",
                    "PASS":  "background:#222;color:#8b949e;border:1px solid #484f58;border-radius:12px;padding:3px 12px;font-size:12px;font-weight:700;letter-spacing:0.5px;white-space:nowrap;",
                },
            }

            def _prob_color(prob):
                if prob >= 0.62: return "#3fb950"
                if prob >= 0.55: return "#58a6ff"
                if prob >= 0.50: return "#f0883e"
                return "#484f58"

            def _edge_color(edge):
                if edge > 0.02: return "#3fb950"
                if edge < -0.01: return "#f85149"
                return "#8b949e"

            def _render_game_cards(df):
                tier_order = {"PRIME": 0, "SHARP": 1, "LEAN": 2, "PASS": 3}

                # Build per-matchup game_time for sorting
                has_time = "game_time" in df.columns
                matchup_times = {}
                if has_time:
                    for (h, a), gd in df.groupby(["home_team", "away_team"]):
                        gt = gd["game_time"].dropna()
                        matchup_times[(h, a)] = gt.iloc[0] if len(gt) else "99:99:99"

                # Sort matchups by game_time ascending
                all_matchups = list(df.groupby(["home_team", "away_team"]).groups.keys())
                all_matchups.sort(key=lambda k: str(matchup_times.get(k, "99:99:99") or "99:99:99"))

                for (home, away) in all_matchups:
                    game_df = df[(df["home_team"] == home) & (df["away_team"] == away)]
                    best_tier = min(game_df["confidence_tier"].unique(),
                                    key=lambda t: tier_order.get(t, 9))
                    badge_style = _C["badge"].get(best_tier, _C["badge"]["PASS"])

                    h_elo = game_df["home_elo"].dropna()
                    a_elo = game_df["away_elo"].dropna()
                    elo_line = ""
                    if len(h_elo) and len(a_elo):
                        elo_line = f'<div style="{_C["elo"]}">Elo: {int(h_elo.iloc[0])} ({home}) vs {int(a_elo.iloc[0])} ({away})</div>'

                    # Game time in header
                    gt_raw = matchup_times.get((home, away)) if has_time else None
                    time_html = ""
                    if gt_raw and gt_raw != "99:99:99":
                        time_html = f'<div style="{_C["elo"]}">{_fmt_time(gt_raw)}</div>'

                    all_bets = game_df.to_dict("records")

                    # Derive spread for each team from the home-side row (negative = favorite)
                    home_spread_row = next((r for r in all_bets
                                           if r["bet_type"] == "spread" and r["bet_side"] == "home"), None)
                    if home_spread_row and home_spread_row.get("line") is not None:
                        h_sprd = home_spread_row["line"]   # e.g. -18.5 (home fav) or +2.5 (home dog)
                        a_sprd = -h_sprd
                        fav_color  = "#f0c040"  # gold for favorite (negative spread)
                        dog_color  = "#8b949e"  # muted for underdog
                        away_sprd_str = f"{a_sprd:.1f}"
                        home_sprd_str = f"{h_sprd:.1f}"
                        away_clr = fav_color if a_sprd < 0 else dog_color
                        home_clr = fav_color if h_sprd < 0 else dog_color
                        # Only show the spread next to the favorite (negative number)
                        away_label = (f'{away} <span style="color:{away_clr};font-size:13px;font-weight:500">{away_sprd_str}</span>'
                                      if a_sprd < 0 else away)
                        home_label = (f'{home} <span style="color:{home_clr};font-size:13px;font-weight:500">{home_sprd_str}</span>'
                                      if h_sprd < 0 else home)
                        matchup_html = (
                            f'<span style="color:{away_clr};font-weight:700">{away_label}</span>'
                            f'<span style="color:#8b949e"> @ </span>'
                            f'<span style="color:{home_clr};font-weight:700">{home_label}</span>'
                        )
                    else:
                        matchup_html = f'{away} @ {home}'

                    # One row per bet_type — keep the highest-probability side only
                    favorable_rows = []
                    for bt_key in ["moneyline", "spread", "total"]:
                        candidates = [r for r in all_bets if r["bet_type"] == bt_key]
                        if candidates:
                            favorable_rows.append(max(candidates, key=lambda r: r["probability"]))

                    row_parts = []
                    for i, r in enumerate(favorable_rows):
                        bt, bs, prob, edge, pred = r["bet_type"], r["bet_side"], r["probability"], r["edge"], r["prediction"]
                        if bt == "moneyline":
                            lbl = "MONEYLINE"
                            ml_team = home if bs == 'home' else away
                            ml_odds = r.get("odds_american")
                            pick = f"{ml_team} {int(ml_odds):+d}" if ml_odds is not None and ml_odds == ml_odds else ml_team
                        elif bt == "spread":
                            lv = f"{r['line']:+.1f}" if r["line"] is not None else "PK"
                            lbl = f"SPREAD {lv}"
                            # covers = the bet_side team when pred=WIN, the other team when pred=LOSE
                            cover_team = home if (bs == 'home') == (pred == 'WIN') else away
                            pick = f"{cover_team} covers"
                        else:
                            lv = f"{r['line']:.1f}" if r["line"] is not None else "—"
                            lbl = f"TOTAL {lv}"
                            pick = pred
                        pc = _prob_color(prob)
                        ec = _edge_color(edge)
                        row_style = _C["row_last"] if i == len(favorable_rows) - 1 else _C["row"]
                        bar_html = f'<div style="{_C["bar_bg"]}"><div style="width:{int(prob*100)}%;height:5px;background:{pc};border-radius:2px;"></div></div>'
                        row_parts.append(
                            f'<div style="{row_style}">'
                            f'<span style="{_C["label"]}">{lbl}</span>'
                            f'<span style="{_C["pick"]}">{pick}</span>'
                            f'<span style="{_C["pct"]}">{prob*100:.1f}%</span>'
                            f'{bar_html}'
                            f'<span style="width:52px;text-align:right;font-size:12px;font-weight:700;color:{ec};">{edge*100:+.1f}%</span>'
                            f'</div>'
                        )

                    card = (
                        f'<div style="{_C["card"]}">'
                        f'<div style="{_C["header"]}">'
                        f'<div><div style="{_C["matchup"]}">{matchup_html}</div>{time_html}{elo_line}</div>'
                        f'<span style="{badge_style}">{best_tier}</span>'
                        f'</div>'
                        + "".join(row_parts)
                        + '</div>'
                    )
                    st.markdown(card, unsafe_allow_html=True)

            _render_game_cards(gdf)

            # ── Performance section ────────────────────────────────────────────
            st.divider()
            st.subheader("Performance — Last 30 Days")
            odf = fetch_game_outcomes(gl_sport, 30)
            if odf.empty:
                st.caption("No graded outcomes yet.")
            else:
                hit_miss = odf[odf["outcome"].isin(["HIT", "MISS"])]
                if not hit_miss.empty:
                    total_bets = len(hit_miss)
                    total_hits = len(hit_miss[hit_miss["outcome"] == "HIT"])
                    overall_acc = total_hits / total_bets * 100

                    pm1, pm2, pm3, pm4 = st.columns(4)
                    pm1.metric("Overall", f"{overall_acc:.1f}%",
                               delta=f"{total_hits}/{total_bets} bets")
                    # Accuracy by bet type
                    for col, bt in zip([pm2, pm3, pm4],
                                       ["moneyline", "spread", "total"]):
                        sub = hit_miss[hit_miss["bet_type"] == bt]
                        if len(sub):
                            h = len(sub[sub["outcome"] == "HIT"])
                            col.metric(bt.title(), f"{h/len(sub)*100:.1f}%",
                                       delta=f"{h}/{len(sub)}")

                    # Tier breakdown — fully inline styles, no CSS classes
                    _badge_s = {
                        "PRIME": "background:#1a3a2a;color:#3fb950;border:1px solid #2ea043;border-radius:10px;padding:2px 10px;font-size:12px;font-weight:700;",
                        "SHARP": "background:#1a2a3a;color:#58a6ff;border:1px solid #388bfd;border-radius:10px;padding:2px 10px;font-size:12px;font-weight:700;",
                        "LEAN":  "background:#3a2a1a;color:#f0883e;border:1px solid #d18616;border-radius:10px;padding:2px 10px;font-size:12px;font-weight:700;",
                        "PASS":  "background:#222;color:#8b949e;border:1px solid #484f58;border-radius:10px;padding:2px 10px;font-size:12px;font-weight:700;",
                    }
                    _row_s   = "display:flex;align-items:center;gap:0;padding:8px 14px;border-bottom:1px solid #21262d;font-size:14px;"
                    _head_s  = "display:flex;align-items:center;gap:0;padding:7px 14px;background:#1c2128;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#8b949e;"
                    _col_w   = ["140px", "70px", "70px", "90px", "1fr"]

                    def _cell(content, idx, style="color:#c9d1d9;"):
                        w = _col_w[idx]
                        flex = f"flex:{w};" if w == "1fr" else f"width:{w};flex-shrink:0;"
                        return f'<span style="{flex}{style}">{content}</span>'

                    tier_rows = ""
                    for tier in ["PRIME", "SHARP", "LEAN", "PASS"]:
                        sub = hit_miss[hit_miss["confidence_tier"] == tier]
                        if len(sub) == 0:
                            continue
                        h = len(sub[sub["outcome"] == "HIT"])
                        acc = h / len(sub) * 100
                        bar_c = "#3fb950" if acc >= 55 else ("#f0883e" if acc >= 50 else "#f85149")
                        badge = f'<span style="{_badge_s[tier]}">{tier}</span>'
                        bar = f'<div style="flex:1;background:#21262d;border-radius:4px;height:7px;overflow:hidden;"><div style="width:{int(acc)}%;height:7px;background:{bar_c};border-radius:4px;"></div></div>'
                        tier_rows += (
                            f'<div style="{_row_s}">'
                            + _cell(badge, 0, "")
                            + _cell(str(len(sub)), 1)
                            + _cell(str(h), 2)
                            + _cell(f'{acc:.1f}%', 3, f"color:{bar_c};font-weight:700;")
                            + _cell(bar, 4, "")
                            + "</div>"
                        )

                    header = (
                        f'<div style="{_head_s}">'
                        + _cell("Tier", 0, "")
                        + _cell("Bets", 1, "")
                        + _cell("Hits", 2, "")
                        + _cell("Accuracy", 3, "")
                        + _cell("", 4, "")
                        + "</div>"
                    )
                    st.markdown(
                        f'<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden;margin-bottom:12px;">{header}{tier_rows}</div>',
                        unsafe_allow_html=True,
                    )

                    if "profit" in odf.columns and odf["profit"].notna().any():
                        st.metric("Net P&L (flat $100/bet)", f"${odf['profit'].sum():+,.0f}")

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB — PERFORMANCE
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_perf:
        pc1, pc2 = st.columns([1, 2])
        with pc1:
            ps = st.selectbox("Sport", ["NBA", "NHL", "MLB"], key="perf_sport")
        with pc2:
            # Date range slider — goes back to Nov 2024 (first data)
            earliest = date(2024, 11, 1)
            today = date.today()
            default_start = today - timedelta(days=30)
            date_range = st.slider(
                "Date range",
                min_value=earliest,
                max_value=today,
                value=(default_start, today),
                format="MMM D, YYYY",
                key="perf_date_range",
            )
            perf_start, perf_end = date_range[0].isoformat(), date_range[1].isoformat()

        results_df = fetch_recent_results(ps, perf_start, perf_end)
        pnl_df     = fetch_pnl_local(ps, perf_start, perf_end)
        days_shown = (date_range[1] - date_range[0]).days
        st.caption(f"Showing {days_shown}-day window ({perf_start} to {perf_end}). "
                   "DNP records (actual_value=0) excluded.")

        # ── Investor P&L Section ──────────────────────────────────────────────
        if not pnl_df.empty:
            st.subheader("Investor P&L Overview")
            st.caption("Flat $100/bet at standard -110 odds. HIT = +$90.91, MISS = -$100.00")

            total_bets   = len(pnl_df)
            total_hits   = (pnl_df["outcome"] == "HIT").sum()
            total_profit = pnl_df["profit"].sum()
            win_rate_pnl = total_hits / total_bets if total_bets else 0
            roi          = total_profit / (total_bets * 100) * 100 if total_bets else 0
            coin_flip_profit = (total_hits * 90.91) + ((total_bets - total_hits) * -100.0)

            iv1, iv2, iv3, iv4, iv5 = st.columns(5)
            iv1.metric("Total Bets",   f"{total_bets:,}")
            iv2.metric("Win Rate",     f"{win_rate_pnl:.1%}")
            iv3.metric("Net P&L",      f"${total_profit:+,.0f}")
            iv4.metric("ROI",          f"{roi:+.1f}%")
            iv5.metric("vs Coin-Flip", f"${total_profit - coin_flip_profit:+,.0f}")

            # Cumulative P&L chart
            daily_pnl = (pnl_df.groupby("game_date")["profit"]
                         .sum().reset_index().sort_values("game_date"))
            daily_pnl["Cumulative P&L ($)"] = daily_pnl["profit"].cumsum()
            daily_pnl["Coin Flip Baseline"] = (
                pnl_df.groupby("game_date").apply(
                    lambda g: (g["outcome"] == "HIT").sum() * 90.91
                    + (g["outcome"] == "MISS").sum() * -100.0
                ).cumsum().values
            ) if len(daily_pnl) == len(
                pnl_df.groupby("game_date")
            ) else 0
            chart_data = daily_pnl.rename(columns={"game_date": "Date"}).set_index("Date")[
                ["Cumulative P&L ($)"]
            ]
            st.line_chart(chart_data, height=250)

            # Kelly bankroll simulation
            with st.expander("Kelly Bankroll Simulation ($1,000 starting bank)"):
                if win_rate_pnl > 0:
                    # Kelly fraction at -110: f = (b*p - q) / b  where b = 10/11
                    b = 10 / 11
                    p = win_rate_pnl
                    q = 1 - p
                    kelly_f = max(0, (b * p - q) / b)
                    half_kelly = kelly_f / 2

                    bank = 1000.0
                    bank_history = [bank]
                    for _, row in pnl_df.sort_values("game_date").iterrows():
                        bet = bank * half_kelly
                        if row["outcome"] == "HIT":
                            bank += bet * (10 / 11)
                        else:
                            bank -= bet
                        bank_history.append(max(bank, 0))

                    final_bank = bank_history[-1]
                    st.metric("Final bankroll (half-Kelly)",  f"${final_bank:,.0f}",
                              delta=f"{(final_bank/1000 - 1)*100:+.1f}%")
                    st.caption(
                        f"Full Kelly fraction: {kelly_f:.1%}  |  "
                        f"Half-Kelly (used): {half_kelly:.1%} of bank per bet"
                    )
                    kelly_chart = pd.DataFrame({"Bankroll ($)": bank_history})
                    st.line_chart(kelly_chart, height=200)
                else:
                    st.info("Not enough data for Kelly simulation.")

            # Win rate by tier
            if pnl_df["ai_tier"].notna().any():
                st.markdown("**Win rate by tier**")
                tier_pnl = []
                for tier in ["T1-ELITE", "T2-STRONG", "T3-GOOD", "T4-LEAN"]:
                    sub = pnl_df[pnl_df["ai_tier"] == tier]
                    if len(sub) >= 5:
                        wr_t  = (sub["outcome"] == "HIT").mean()
                        pnl_t = sub["profit"].sum()
                        roi_t = pnl_t / (len(sub) * 100) * 100
                        tier_pnl.append({
                            "Tier": tier, "Bets": len(sub),
                            "Win Rate": f"{wr_t:.1%}",
                            "Net P&L": f"${pnl_t:+,.0f}",
                            "ROI": f"{roi_t:+.1f}%",
                        })
                if tier_pnl:
                    st.dataframe(pd.DataFrame(tier_pnl),
                                 use_container_width=True, hide_index=True)

            st.divider()

        if not results_df.empty:
            hits = results_df[results_df["result"] == "HIT"]
            total = len(results_df)
            acc = len(hits) / total * 100 if total else 0

            pm1, pm2, pm3, pm4 = st.columns(4)
            pm1.metric("Graded", total)
            pm2.metric("Accuracy", f"{acc:.1f}%")
            pm3.metric("Hits", len(hits))
            pm4.metric("Misses", total - len(hits))

            st.divider()

            # Accuracy by tier
            st.subheader("Accuracy by Tier")
            tier_stats = []
            for tier in ["T1-ELITE", "T2-STRONG", "T3-GOOD", "T4-LEAN"]:
                sub = results_df[results_df["ai_tier"] == tier]
                if len(sub) > 0:
                    t_hits = len(sub[sub["result"] == "HIT"])
                    tier_stats.append({
                        "Tier": tier,
                        "Picks": len(sub),
                        "Hits": t_hits,
                        "Accuracy": f"{t_hits/len(sub)*100:.1f}%"
                    })
            if tier_stats:
                st.dataframe(pd.DataFrame(tier_stats), use_container_width=True,
                             hide_index=True)

            st.divider()

            # Accuracy by prop type
            st.subheader("Accuracy by Prop")
            prop_stats = []
            for prop in sorted(results_df["prop_type"].unique()):
                sub = results_df[results_df["prop_type"] == prop]
                if len(sub) >= 5:
                    p_hits = len(sub[sub["result"] == "HIT"])
                    prop_stats.append({
                        "Prop": prop.upper().replace("_", " "),
                        "Picks": len(sub),
                        "Accuracy": f"{p_hits/len(sub)*100:.1f}%"
                    })
            if prop_stats:
                st.dataframe(
                    pd.DataFrame(prop_stats).sort_values("Accuracy", ascending=False),
                    use_container_width=True, hide_index=True
                )

            st.divider()

            # ── Hit Rate vs Model Probability (Calibration) ──────────────────
            st.subheader("Hit Rate vs Model Confidence (Calibration)")
            st.caption(
                "If models are well-calibrated, the hit rate should match the model probability. "
                "Large gaps indicate over- or under-confidence."
            )

            if "ai_probability" in results_df.columns:
                df_cal = results_df[results_df["ai_probability"].notna()].copy()
                df_cal["ai_probability"] = pd.to_numeric(df_cal["ai_probability"], errors="coerce")
                df_cal["hit"] = (df_cal["result"] == "HIT").astype(int)

                # Probability buckets
                def prob_bucket(p):
                    if p >= 0.85: return "85-95%"
                    elif p >= 0.80: return "80-85%"
                    elif p >= 0.75: return "75-80%"
                    elif p >= 0.70: return "70-75%"
                    elif p >= 0.65: return "65-70%"
                    elif p >= 0.60: return "60-65%"
                    else: return "<60%"

                bucket_order = ["85-95%","80-85%","75-80%","70-75%","65-70%","60-65%","<60%"]
                df_cal["bucket"] = df_cal["ai_probability"].apply(prob_bucket)

                cal_rows = []
                for bkt in bucket_order:
                    sub = df_cal[df_cal["bucket"] == bkt]
                    if len(sub) >= 10:
                        actual_hr = sub["hit"].mean() * 100
                        mid = sub["ai_probability"].mean() * 100
                        gap = actual_hr - mid
                        gap_str = f"+{gap:.1f}%" if gap > 0 else f"{gap:.1f}%"
                        cal_rows.append({
                            "Model says": bkt,
                            "n": len(sub),
                            "Avg model prob": f"{mid:.1f}%",
                            "Actual hit rate": f"{actual_hr:.1f}%",
                            "Gap": gap_str,
                        })

                if cal_rows:
                    st.dataframe(pd.DataFrame(cal_rows), use_container_width=True, hide_index=True)

                # Hit rate by OVER/UNDER direction
                if "ai_prediction" in results_df.columns:
                    st.markdown("**Hit rate by direction**")
                    dir_rows = []
                    for direction in ["OVER", "UNDER"]:
                        sub = df_cal[df_cal["ai_prediction"] == direction]
                        if len(sub) >= 5:
                            hr = sub["hit"].mean() * 100
                            avg_prob = sub["ai_probability"].mean() * 100
                            dir_rows.append({
                                "Direction": direction,
                                "n": len(sub),
                                "Avg model prob": f"{avg_prob:.1f}%",
                                "Actual hit rate": f"{hr:.1f}%",
                                "Gap": f"{hr - avg_prob:+.1f}%",
                            })
                    if dir_rows:
                        st.dataframe(pd.DataFrame(dir_rows), use_container_width=True, hide_index=True)

                # Hit rate by odds_type (standard / goblin / demon)
                if "odds_type" in results_df.columns and results_df["odds_type"].notna().any():
                    st.markdown("**Hit rate by line type**")
                    ot_rows = []
                    for ot in ["standard", "goblin", "demon"]:
                        sub = df_cal[df_cal["odds_type"] == ot]
                        if len(sub) >= 5:
                            hr = sub["hit"].mean() * 100
                            avg_prob = sub["ai_probability"].mean() * 100
                            be = _BREAK_EVEN.get(ot, 110 / 210) * 100
                            ot_rows.append({
                                "Line type": ot.capitalize(),
                                "n": len(sub),
                                "Break-even": f"{be:.0f}%",
                                "Avg model prob": f"{avg_prob:.1f}%",
                                "Actual hit rate": f"{hr:.1f}%",
                                "Profitable?": "YES" if hr >= be else "NO",
                            })
                    if ot_rows:
                        st.dataframe(pd.DataFrame(ot_rows), use_container_width=True, hide_index=True)

            st.divider()

            # Model performance history
            perf_df = fetch_performance(ps)
            if not perf_df.empty and "accuracy" in perf_df.columns:
                st.divider()
                st.subheader("Model Accuracy Over Time")
                chart_df = perf_df[["game_date", "accuracy"]].copy()
                chart_df["accuracy"] = (chart_df["accuracy"] * 100).round(1)
                chart_df = chart_df.rename(columns={
                    "game_date": "Date", "accuracy": "Accuracy %"
                }).sort_values("Date")
                st.line_chart(chart_df.set_index("Date"))
        else:
            st.info(f"No graded results for {ps} between {perf_start} and {perf_end}.")

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 3 — MLB SEASON PROPS
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_season:
        st.subheader("MLB Season Props — 2026 Projections")
        st.caption(
            "Marcel projections (3-year weighted avg + age curve + park factors). "
            "Run `python mlb/scripts/run_season_projections.py` to refresh."
        )

        # ── Confidence tier explanation ────────────────────────────────────────
        with st.expander("What does the Confidence rating mean?"):
            st.markdown("""
**Confidence reflects how many seasons of historical data were available** to build each player's projection — not model accuracy directly.

| Tier | Seasons of data | What it means |
|------|----------------|---------------|
| **HIGH** | 3 seasons (2023, 2024, 2025) | Most reliable. Marcel weighted avg uses all three years. Typical error range: **±10–18%** of projection. |
| **MEDIUM** | 2 seasons | Good signal, slightly wider range. Typical error range: **±18–28%** of projection. |
| **LOW** | 1 season only | Rookie, injury return, or recent call-up. Projection regresses heavily to league average. Error range: **±28–45%**. |
| **VERY LOW** | No historical data | Best-guess estimate based on league average only. Treat as highly speculative. |

**Example:** A HIGH confidence projection of 42 home runs has an implied range of roughly **34–50 HR** (±18%).
A LOW confidence 42 HR projection could reasonably land anywhere from **23–61 HR**.

**Other factors baked in:** Age curve (peak at 27; power stats decline 1.5%/yr after 30), park factor (home ballpark dimensions), and regression-to-mean (volatile stats like HR/SB regress ~30% toward league average).

> *Tip: Use HIGH confidence projections for sizable bets. MEDIUM is fine for smaller wagers with strong line value. LOW and VERY LOW are speculative — only play if the sportsbook line appears significantly mispriced.*
            """)

        # ── Filters ───────────────────────────────────────────────────────────
        BATTER_STATS = {
            'hr':    'Home Runs',
            'k':     'Strikeouts (B)',
            'tb':    'Total Bases',
            'rbi':   'RBIs',
            'runs':  'Runs Scored',
            'hits':  'Hits',
            'sb':    'Stolen Bases',
        }
        PITCHER_STATS = {
            'k_total':       'Strikeouts (P)',
            'bb_total':      'Walks (P)',
            'hits_allowed':  'Hits Allowed',
            'er_total':      'Earned Runs',
        }
        ALL_STATS = {**BATTER_STATS, **PITCHER_STATS}
        STAT_LABELS = {v: k for k, v in ALL_STATS.items()}
        stat_options = ['All'] + list(ALL_STATS.values())

        sf1, sf2, sf3, sf4, sf5 = st.columns([2, 1, 1, 1, 1])
        with sf1:
            stat_sel_label = st.selectbox("Stat", stat_options,
                                          key="sp_stat", label_visibility="collapsed")
            stat_sel = STAT_LABELS.get(stat_sel_label) if stat_sel_label != 'All' else None
        with sf2:
            ptype_sel = st.selectbox("Player type", ["All", "Batters", "Pitchers"],
                                     key="sp_ptype", label_visibility="collapsed")
            ptype_map = {"Batters": "batter", "Pitchers": "pitcher", "All": None}
            ptype_filter = ptype_map[ptype_sel]
        with sf3:
            conf_sel = st.selectbox("Min confidence", ["All", "MEDIUM+", "HIGH only"],
                                    key="sp_conf", label_visibility="collapsed")
            conf_map = {"All": "VERY LOW", "MEDIUM+": "MEDIUM", "HIGH only": "HIGH"}
            conf_filter = conf_map[conf_sel]
        with sf4:
            sort_col_outer = st.selectbox("Sort by", ["Projection", "Player", "Confidence"],
                                          key="sp_sort_outer", label_visibility="collapsed")
        with sf5:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Refresh", use_container_width=True, key="sp_refresh"):
                st.cache_data.clear()
                st.rerun()

        df_sp = fetch_season_projections(
            stat_filter=stat_sel,
            player_type=ptype_filter,
            team_filter=None,
            min_confidence=conf_filter,
        )

        if df_sp.empty:
            st.warning(
                "No season projections found. "
                "Run: `cd mlb && python scripts/run_season_projections.py`"
            )
        else:
            # ── Summary metrics ───────────────────────────────────────────────
            n_players  = df_sp['player_name'].nunique()
            n_pitchers = df_sp[df_sp['player_type'] == 'pitcher']['player_name'].nunique()
            n_batters  = df_sp[df_sp['player_type'] == 'batter']['player_name'].nunique()
            n_high     = df_sp[df_sp['confidence'] == 'HIGH']['player_name'].nunique()

            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("Players", n_players)
            sm2.metric("Batters", n_batters)
            sm3.metric("Pitchers", n_pitchers)
            sm4.metric("HIGH confidence", n_high)

            st.divider()

            # ── Inner tabs ────────────────────────────────────────────────────
            spt1, spt2, spt3 = st.tabs(["Rankings", "Line Evaluator", "PrizePicks SZLN ML"])

            with spt1:
                # Display table
                display_df = df_sp[['player_name', 'team', 'player_type', 'stat',
                                    'projection', 'confidence', 'seasons_used', 'age']].copy()
                display_df['stat_label'] = display_df['stat'].map(ALL_STATS).fillna(display_df['stat'])
                display_df = display_df.rename(columns={
                    'player_name': 'Player', 'team': 'Team',
                    'player_type': 'Type', 'stat_label': 'Stat',
                    'projection': 'Projection', 'confidence': 'Confidence',
                    'seasons_used': 'Seasons', 'age': 'Age',
                }).drop(columns=['stat'])

                # Map confidence to emoji badge so meaning is visible at a glance
                CONF_BADGE = {
                    'HIGH':     'HIGH (3 seasons)',
                    'MEDIUM':   'MED (2 seasons)',
                    'LOW':      'LOW (1 season)',
                    'VERY LOW': 'VERY LOW',
                }
                display_df['Confidence'] = display_df['Confidence'].map(
                    lambda c: CONF_BADGE.get(c, c)
                )

                asc = sort_col_outer == "Player"
                display_df = display_df.sort_values(sort_col_outer, ascending=asc)

                st.dataframe(display_df, use_container_width=True,
                             hide_index=True, height=500)

                total_rows = len(df_sp)
                st.caption(
                    f"{total_rows:,} stat projections across {n_players} players. "
                    "Confidence = seasons of historical data used (HIGH=3, MED=2, LOW=1)."
                )

            with spt2:
                st.markdown("**Enter a sportsbook line to get an instant edge calculation:**")
                st.caption("Works for any player in the projections table above.")

                le1, le2, le3, le4, le5 = st.columns([3, 2, 2, 1, 1])
                with le1:
                    le_player = st.text_input("Player name", key="le_player",
                                              placeholder="e.g. Aaron Judge")
                with le2:
                    le_stat_label = st.selectbox("Stat", list(ALL_STATS.values()),
                                                 key="le_stat")
                    le_stat = STAT_LABELS.get(le_stat_label, le_stat_label)
                with le3:
                    le_line = st.number_input("Sportsbook line", value=30.0,
                                              min_value=0.5, step=0.5, key="le_line")
                with le4:
                    le_dir = st.selectbox("Dir", ["OVER", "UNDER"], key="le_dir")
                with le5:
                    st.markdown("<br>", unsafe_allow_html=True)
                    evaluate = st.button("Evaluate", use_container_width=True, key="le_eval")

                if evaluate and le_player:
                    result = _evaluate_line(le_player, le_stat, le_line, le_dir)
                    if result is None:
                        st.warning(f"No projection found for '{le_player}' / {le_stat_label}. "
                                   "Check spelling or run the projections batch.")
                    else:
                        ec1, ec2, ec3, ec4 = st.columns(4)
                        ec1.metric("Projection", result['projection'])
                        ec2.metric("Model Prob", f"{result['probability']}%")
                        ec3.metric("Edge vs -110", f"{result['edge']:+.1f}%")
                        conf_label = {
                            'HIGH':   'HIGH (3 seasons)',
                            'MEDIUM': 'MEDIUM (2 seasons)',
                            'LOW':    'LOW (1 season)',
                        }.get(result['confidence'], result['confidence'])
                        ec4.metric("Confidence", conf_label)

                        color = "#1b4332" if result['edge'] > 5 else (
                                "#3f1515" if result['edge'] < -2 else "#2a2a2a")
                        st.markdown(
                            f'<div style="background:{color};padding:12px 18px;'
                            f'border-radius:8px;margin-top:8px">'
                            f'<b style="font-size:16px">{result["recommendation"]}</b>'
                            f'<span style="color:#aaa;font-size:12px;margin-left:12px">'
                            f'Age {result["age"] or "?"} · {result["team"]} · '
                            f'{result["seasons_used"]} seasons of data used</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                # Quick multi-eval: paste multiple lines
                st.divider()
                st.markdown("**Bulk evaluate — paste multiple lines:**")
                st.caption('One per line: `Player Name, stat_key, line, OVER/UNDER`  '
                           '(e.g. `Aaron Judge, hr, 42.5, OVER`)')

                bulk_input = st.text_area("Lines to evaluate", height=150,
                                          key="bulk_lines",
                                          placeholder="Aaron Judge, hr, 42.5, OVER\n"
                                                      "Gerrit Cole, k_total, 195.5, OVER\n"
                                                      "Ronald Acuna Jr, sb, 55.5, OVER")
                if st.button("Evaluate all", key="bulk_eval") and bulk_input.strip():
                    bulk_results = []
                    for line_str in bulk_input.strip().split('\n'):
                        parts = [p.strip() for p in line_str.split(',')]
                        if len(parts) < 4:
                            continue
                        pname_, stat_, line_, dir_ = parts[0], parts[1], parts[2], parts[3].upper()
                        try:
                            r = _evaluate_line(pname_, stat_, float(line_), dir_)
                            if r:
                                bulk_results.append(r)
                        except Exception:
                            pass

                    if bulk_results:
                        bulk_df = pd.DataFrame(bulk_results)[[
                            'player_name', 'stat', 'line', 'direction',
                            'projection', 'probability', 'edge', 'recommendation', 'confidence'
                        ]].rename(columns={
                            'player_name': 'Player', 'stat': 'Stat',
                            'line': 'Line', 'direction': 'Dir',
                            'projection': 'Proj', 'probability': 'Prob%',
                            'edge': 'Edge%', 'recommendation': 'Rec',
                            'confidence': 'Conf',
                        }).sort_values('Edge%', ascending=False)
                        st.dataframe(bulk_df, use_container_width=True, hide_index=True)
                    else:
                        st.warning("No matching projections found. Check player names and stat keys.")

            # ─────────────────────────────────────────────────────────────────
            with spt3:
                st.markdown("### PrizePicks SZLN — ML Predictions")
                st.caption(
                    "ML model compares our career-stat projections against live PrizePicks "
                    "season-long lines and returns calibrated OVER/UNDER probabilities. "
                    "Run `python mlb/scripts/season_props_ml.py` to refresh picks."
                )

                # ── Controls row ──────────────────────────────────────────────
                pp_c1, pp_c2, pp_c3, pp_c4, pp_c5 = st.columns([2, 1, 1, 1, 1])
                SZLN_STAT_LABELS = {
                    'All':           'All',
                    'k_total':       'Strikeouts (P)',
                    'bb_total':      'Walks (P)',
                    'hits_allowed':  'Hits Allowed (P)',
                    'er_total':      'Earned Runs (P)',
                    'outs_recorded': 'Outs Recorded (P)',
                    'hr':    'Home Runs',
                    'sb':    'Stolen Bases',
                    'hits':  'Hits',
                    'tb':    'Total Bases',
                    'rbi':   'RBIs',
                    'runs':  'Runs Scored',
                    'k':     'Strikeouts (B)',
                    'walks': 'Walks (B)',
                    'hrr':   'H+R+RBI',
                }
                SZLN_LABEL_TO_STAT = {v: k for k, v in SZLN_STAT_LABELS.items() if k != 'All'}

                with pp_c1:
                    pp_stat_label = st.selectbox(
                        "Stat", list(SZLN_STAT_LABELS.values()), key="pp_stat"
                    )
                    pp_stat_filter = SZLN_LABEL_TO_STAT.get(pp_stat_label)

                with pp_c2:
                    pp_dir = st.selectbox("Direction", ["All", "OVER", "UNDER"], key="pp_dir")
                    pp_dir_filter = None if pp_dir == "All" else pp_dir

                with pp_c3:
                    pp_ptype = st.selectbox("Type", ["All", "Batters", "Pitchers"], key="pp_ptype2")
                    pp_ptype_filter = {"Batters": "batter", "Pitchers": "pitcher"}.get(pp_ptype)

                with pp_c4:
                    pp_min_edge = st.number_input(
                        "Min edge %", value=3.0, min_value=0.0, step=1.0, key="pp_min_edge"
                    )

                with pp_c5:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("Refresh", use_container_width=True, key="pp_refresh"):
                        st.cache_data.clear()
                        st.rerun()

                df_szln = fetch_szln_picks(
                    stat_filter=pp_stat_filter,
                    direction_filter=pp_dir_filter,
                    min_edge=pp_min_edge,
                    player_type_filter=pp_ptype_filter,
                )

                if df_szln.empty:
                    st.info(
                        "No ML SZLN picks found. "
                        "Run: `cd mlb && python scripts/season_props_ml.py` to fetch lines and generate predictions.\n\n"
                        "First-time setup: `python scripts/season_props_ml.py --train` to build models."
                    )
                else:
                    # ── Summary metrics ───────────────────────────────────────
                    n_picks  = len(df_szln)
                    n_over   = (df_szln['direction'] == 'OVER').sum()
                    n_under  = (df_szln['direction'] == 'UNDER').sum()
                    avg_edge = df_szln['edge'].mean()

                    pm1, pm2, pm3, pm4 = st.columns(4)
                    pm1.metric("Total Picks", n_picks)
                    pm2.metric("OVER picks",  n_over)
                    pm3.metric("UNDER picks", n_under)
                    pm4.metric("Avg Edge vs -110", f"{avg_edge:+.1f}%")

                    st.divider()

                    # ── Direction breakdown tabs ───────────────────────────────
                    EDGE_COLOR = {True: "#1b4332", False: "#2a2a2a"}  # green if big edge

                    disp = df_szln[[
                        'player_name', 'team', 'player_type', 'stat',
                        'line', 'direction', 'probability', 'edge',
                        'projection', 'confidence', 'model_used', 'recommendation',
                    ]].copy()

                    disp['stat_label'] = disp['stat'].map(SZLN_STAT_LABELS).fillna(disp['stat'])
                    disp['probability'] = disp['probability'].round(1).astype(str) + '%'
                    disp['edge']        = disp['edge'].apply(lambda x: f"{x:+.1f}%")
                    disp['projection']  = disp['projection'].round(1)

                    # Direction emoji
                    disp['direction'] = disp['direction'].map(
                        lambda d: f"OVER" if d == 'OVER' else f"UNDER"
                    )

                    disp = disp.rename(columns={
                        'player_name': 'Player', 'team': 'Team',
                        'player_type': 'Type', 'stat_label': 'Stat',
                        'line': 'PP Line', 'direction': 'Dir',
                        'probability': 'Prob', 'edge': 'Edge',
                        'projection': 'Our Proj', 'confidence': 'Conf',
                        'model_used': 'Model', 'recommendation': 'Rec',
                    }).drop(columns=['stat'])

                    st.dataframe(disp, use_container_width=True, hide_index=True, height=480)

                    # ── Legend ────────────────────────────────────────────────
                    with st.expander("Column guide"):
                        st.markdown("""
| Column | Meaning |
|--------|---------|
| **PP Line** | The PrizePicks season-long prop line |
| **Dir** | Our ML model's recommended direction (OVER or UNDER) |
| **Prob** | Calibrated probability the actual total lands on our side |
| **Edge** | Prob − 52.4% (break-even at -110). Positive = profitable long-run |
| **Our Proj** | Marcel + ML model's season-total projection |
| **Conf** | Data quality: HIGH = 3+ seasons, MED = 2, LOW = 1 |
| **Model** | `ml` = Gradient Boosting model trained on career data; `stat` = statistical fallback |
                        """)

                    # Fetch timestamp
                    if 'fetched_at' in df_szln.columns:
                        latest = df_szln['fetched_at'].max()
                        st.caption(f"Lines fetched: {latest[:19] if latest else 'unknown'}")

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 4 — NHL HITS & BLOCKS
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_hb:
        st.subheader("NHL Daily Hits & Blocked Shots")
        st.caption(
            "8 highest-probability floor plays generated daily by Claude. "
            "Only locked-in TOI roles, zero-blowout games, and PrizePicks Flex eligible. "
            "Runs automatically each day at 11 AM CST after lineups post."
        )

        # ── Date selector + refresh ────────────────────────────────────────────
        hb_dates = fetch_hb_history(14)
        hb_c1, hb_c2 = st.columns([3, 1])

        with hb_c1:
            if hb_dates:
                date_choice = st.selectbox(
                    "View picks for date",
                    options=hb_dates,
                    index=0,
                    key="hb_date_sel",
                )
            else:
                date_choice = None
                st.info(
                    "No picks saved yet. "
                    "Run: `cd nhl && python scripts/daily_hits_blocks.py`\n\n"
                    "Requires `ANTHROPIC_API_KEY` environment variable."
                )

        with hb_c2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Refresh", use_container_width=True, key="hb_refresh"):
                st.cache_data.clear()
                st.rerun()

        if date_choice:
            picks = fetch_hb_picks(date_choice)
            if not picks:
                st.warning(f"No picks found for {date_choice}.")
            else:
                # ── Metadata strip ─────────────────────────────────────────────
                gen_time   = picks.get("generated_at", "")[:16]
                model      = picks.get("model", "unknown")
                p_tok      = picks.get("prompt_tokens", 0)
                c_tok      = picks.get("completion_tokens", 0)
                n_games    = picks.get("games_count", "?")
                odds_src   = picks.get("odds_source", "grok_search")
                odds_label = ("Real-time (The Odds API)"
                              if "odds-api" in odds_src
                              else "Grok live search")
                st.caption(
                    f"Generated {gen_time}  |  "
                    f"{n_games} games  |  "
                    f"Model: {model}  |  "
                    f"Lines: {odds_label}  |  "
                    f"Tokens: {p_tok:,}p + {c_tok:,}c"
                )
                st.divider()

                # ── Rendered picks ─────────────────────────────────────────────
                raw = picks.get("raw_output", "")
                if raw:
                    st.markdown(raw)
                else:
                    st.info("No output saved for this date.")

                st.divider()

                # ── Copy-friendly expander ─────────────────────────────────────
                with st.expander("Raw text (copy to Discord/Notes)"):
                    st.text_area(
                        "Raw output",
                        value=raw,
                        height=400,
                        key="hb_raw_text",
                        label_visibility="collapsed",
                    )

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB — GOLF (PGA Tour Round Score & Make Cut)
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_golf:
        st.subheader("PGA Tour — Round Score & Make Cut Predictions")
        st.caption(
            "Statistical model using player form, course history, and ranking. "
            "Predictions generated at 10 AM CST (Thu–Sun). "
            "Make-cut props: Rounds 1–2 only. Graded after each round completes at 8 AM CST."
        )

        # ── Controls row ──────────────────────────────────────────────────────
        gf_c1, gf_c2, gf_c3, gf_c4, gf_c5 = st.columns([2, 1, 1, 1, 1])
        with gf_c1:
            gf_date = st.date_input("Date", value=date.today(),
                                     key="gf_date",
                                     label_visibility="collapsed").isoformat()
        with gf_c2:
            gf_prop = st.selectbox("Prop", ["All", "round_score", "make_cut"],
                                    key="gf_prop", label_visibility="collapsed")
        with gf_c3:
            gf_dir = st.selectbox("Direction", ["Both", "OVER", "UNDER"],
                                   key="gf_dir", label_visibility="collapsed")
            gf_dir_val = None if gf_dir == "Both" else gf_dir
        with gf_c4:
            gf_min_prob = st.number_input("Min prob %", value=55, min_value=50,
                                           max_value=90, step=1, key="gf_min_prob")
        with gf_c5:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Refresh", use_container_width=True, key="gf_refresh"):
                st.cache_data.clear()
                st.rerun()

        gf_raw = fetch_golf_predictions(gf_date)

        if gf_raw.empty:
            st.info(
                f"No golf predictions for {gf_date}. "
                "Predictions run Thu–Sun during the PGA Tour season (Jan–Sept).\n\n"
                f"Run manually: `python orchestrator.py --sport golf --mode once --operation prediction`"
            )
        else:
            # ── Tournament banner ─────────────────────────────────────────────
            tournament = gf_raw['tournament_name'].iloc[0]
            round_num  = int(gf_raw['round_number'].iloc[0])
            total_preds = len(gf_raw)
            graded_mask = gf_raw['outcome'].notna()
            n_graded    = graded_mask.sum()

            bm1, bm2, bm3, bm4 = st.columns(4)
            bm1.metric("Tournament", tournament)
            bm2.metric("Round", f"Round {round_num}")
            bm3.metric("Predictions", f"{total_preds:,}")
            if n_graded > 0:
                n_hits = (gf_raw.loc[graded_mask, 'outcome'] == 'HIT').sum()
                bm4.metric("Graded", f"{n_hits}/{n_graded}",
                           delta=f"{n_hits/n_graded*100:.0f}% accuracy")
            else:
                bm4.metric("Graded", "Pending")

            st.divider()

            # Apply filters
            gf_df = gf_raw.copy()
            if gf_prop != "All":
                gf_df = gf_df[gf_df['prop_type'] == gf_prop]
            if gf_dir_val:
                gf_df = gf_df[gf_df['prediction'] == gf_dir_val]
            gf_df = gf_df[gf_df['probability'] >= gf_min_prob / 100]

            # ── Sub-tabs ──────────────────────────────────────────────────────
            gft1, gft2, gft3 = st.tabs(["Today's Picks", "Performance", "ML Readiness"])

            with gft1:
                if gf_df.empty:
                    st.warning("No picks match current filters.")
                else:
                    gf_df['Prob'] = (gf_df['probability'] * 100).round(1).astype(str) + "%"
                    gf_df['Prop'] = gf_df['prop_type'].str.replace("_", " ").str.title()
                    gf_df['Pick'] = gf_df['prediction'] + " " + gf_df['line'].astype(str)
                    gf_df['Result'] = gf_df['outcome'].fillna("—")
                    gf_df['Actual'] = gf_df['actual_value'].apply(
                        lambda v: str(v) if pd.notna(v) else "—"
                    )

                    # Summary
                    sf1, sf2, sf3 = st.columns(3)
                    sf1.metric("Showing", len(gf_df))
                    under_ct = (gf_df['prediction'] == 'UNDER').sum()
                    over_ct  = (gf_df['prediction'] == 'OVER').sum()
                    sf2.metric("UNDER", under_ct)
                    sf3.metric("OVER", over_ct)

                    disp_cols = ['player_name', 'Prop', 'Pick', 'Prob', 'Result', 'Actual']
                    col_labels = {'player_name': 'Player'}
                    st.dataframe(
                        gf_df[disp_cols].rename(columns=col_labels),
                        use_container_width=True,
                        hide_index=True,
                        height=500,
                    )

                    # Prop-level accordion
                    st.divider()
                    st.markdown("**By Prop Type**")
                    for prop in sorted(gf_df['prop_type'].unique()):
                        sub = gf_df[gf_df['prop_type'] == prop]
                        graded_sub = sub[sub['Result'] != '—']
                        acc_str = ""
                        if not graded_sub.empty:
                            hits = (graded_sub['Result'] == 'HIT').sum()
                            acc_str = f"  ·  {hits}/{len(graded_sub)} graded ({hits/len(graded_sub)*100:.0f}%)"
                        with st.expander(
                            f"{prop.replace('_', ' ').title()}  —  {len(sub)} picks{acc_str}",
                            expanded=False
                        ):
                            for line_val in sorted(sub['line'].unique()):
                                line_sub = sub[sub['line'] == line_val]
                                under = line_sub[line_sub['prediction'] == 'UNDER']
                                over  = line_sub[line_sub['prediction'] == 'OVER']
                                st.caption(
                                    f"Line {line_val}: "
                                    f"{len(under)} UNDER  ·  {len(over)} OVER"
                                )
                            st.dataframe(
                                sub[['player_name', 'Pick', 'Prob', 'Result', 'Actual']]
                                  .rename(columns={'player_name': 'Player'}),
                                use_container_width=True,
                                hide_index=True,
                            )

            with gft2:
                perf_days = st.slider("Days back", 7, 90, 30, key="gf_perf_days")
                gf_perf = fetch_golf_performance(perf_days)

                if gf_perf.empty:
                    st.info(
                        "No graded predictions yet. "
                        "Grading runs at 8 AM CST after each round completes.\n\n"
                        f"Run manually: `python orchestrator.py --sport golf --mode once --operation grading`"
                    )
                else:
                    total_g  = len(gf_perf)
                    total_h  = (gf_perf['outcome'] == 'HIT').sum()
                    overall  = total_h / total_g * 100

                    pm1, pm2, pm3, pm4 = st.columns(4)
                    pm1.metric("Graded", total_g)
                    pm2.metric("Accuracy", f"{overall:.1f}%")
                    pm3.metric("Hits", int(total_h))
                    pm4.metric("Misses", total_g - int(total_h))

                    st.divider()

                    # OVER vs UNDER
                    st.subheader("OVER vs UNDER Accuracy")
                    dir_stats = []
                    for direction in ['UNDER', 'OVER']:
                        sub = gf_perf[gf_perf['prediction'] == direction]
                        if len(sub) > 0:
                            h = (sub['outcome'] == 'HIT').sum()
                            dir_stats.append({
                                'Direction': direction,
                                'Picks': len(sub),
                                'Hits': int(h),
                                'Accuracy': f"{h/len(sub)*100:.1f}%",
                            })
                    if dir_stats:
                        st.dataframe(pd.DataFrame(dir_stats),
                                     use_container_width=True, hide_index=True)

                    st.divider()

                    # By prop + line
                    st.subheader("Accuracy by Prop / Line")
                    line_stats = []
                    for prop in sorted(gf_perf['prop_type'].unique()):
                        for line_val in sorted(gf_perf[gf_perf['prop_type'] == prop]['line'].unique()):
                            sub = gf_perf[(gf_perf['prop_type'] == prop) & (gf_perf['line'] == line_val)]
                            if len(sub) < 3:
                                continue
                            h = (sub['outcome'] == 'HIT').sum()
                            u_sub = sub[sub['prediction'] == 'UNDER']
                            o_sub = sub[sub['prediction'] == 'OVER']
                            u_acc = f"{(u_sub['outcome']=='HIT').sum()/len(u_sub)*100:.0f}%" if len(u_sub) else "—"
                            o_acc = f"{(o_sub['outcome']=='HIT').sum()/len(o_sub)*100:.0f}%" if len(o_sub) else "—"
                            line_stats.append({
                                'Prop': prop.replace('_', ' ').title(),
                                'Line': line_val,
                                'Picks': len(sub),
                                'Accuracy': f"{h/len(sub)*100:.1f}%",
                                'UNDER acc': u_acc,
                                'OVER acc': o_acc,
                            })
                    if line_stats:
                        st.dataframe(pd.DataFrame(line_stats),
                                     use_container_width=True, hide_index=True)
                    else:
                        st.caption("Not enough data yet (need 3+ graded per combo).")

                    st.divider()

                    # By tournament
                    st.subheader("By Tournament")
                    tourn_stats = []
                    for t in gf_perf['tournament_name'].unique():
                        sub = gf_perf[gf_perf['tournament_name'] == t]
                        h = (sub['outcome'] == 'HIT').sum()
                        tourn_stats.append({
                            'Tournament': t,
                            'Graded': len(sub),
                            'Hits': int(h),
                            'Accuracy': f"{h/len(sub)*100:.1f}%",
                        })
                    if tourn_stats:
                        st.dataframe(
                            pd.DataFrame(tourn_stats).sort_values('Accuracy', ascending=False),
                            use_container_width=True, hide_index=True,
                        )

            with gft3:
                st.subheader("ML Readiness — Progress to 7,500 Graded per Combo")
                st.caption(
                    "Golf ML training requires 7,500 graded predictions per prop/line combination. "
                    "Make-cut only generated in Rounds 1–2 (~2 days/week). "
                    "Round score lines accumulate 4 days/week."
                )
                ml_data = fetch_golf_ml_readiness()
                target = 7500

                ml_combos = [
                    ('round_score', 68.5),
                    ('round_score', 70.5),
                    ('round_score', 72.5),
                    ('make_cut',    0.5),
                ]
                for prop, line in ml_combos:
                    key = f"{prop}_{line}"
                    count = ml_data.get(key, 0)
                    pct   = min(count / target * 100, 100)
                    label = f"{prop.replace('_', ' ').title()} {line}"
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.progress(pct / 100, text=f"{label}  —  {count:,} / {target:,}")
                    with col_b:
                        st.metric("", f"{pct:.1f}%", label_visibility="collapsed")

                st.divider()
                total_preds_all  = ml_data.get('_total_predictions', 0)
                total_graded_all = ml_data.get('_total_graded', 0)
                mc1, mc2 = st.columns(2)
                mc1.metric("Total Predictions", f"{total_preds_all:,}")
                mc2.metric("Total Graded", f"{total_graded_all:,}")
                st.caption(
                    "Bottleneck is make_cut_0.5 — only generated 2 days/week. "
                    "Estimated 2–3 full PGA seasons to reach training threshold."
                )

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB — SYSTEM HEALTH  (live orchestrator monitor)
    # ═══════════════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════════════
    # TAB — STATBOT  (Natural Language DB Query via Grok)
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_statbot:
        import os as _os_sb
        import json as _json_sb
        import sqlite3 as _sqlite3_sb
        from pathlib import Path as _Path_sb

        _STATBOT_SCHEMA = """You are StatBot — a SQL assistant for the SportsPredictor database system.
Translate natural language questions into SQLite queries.
Return ONLY valid JSON: {"db": "NBA|NHL|MLB", "sql": "SELECT ...", "note": "one-line plain English explanation"}

SEASON NOTE: "this season" or current season = game_date >= '2025-10-01'. All dates stored as 'YYYY-MM-DD'.
TODAY = date('now') in SQLite.

=== NBA DATABASE ===
player_game_logs:
  game_id TEXT, game_date TEXT, player_name TEXT, team TEXT, opponent TEXT, home_away TEXT,
  minutes REAL, points INT, rebounds INT, assists INT, steals INT, blocks INT,
  turnovers INT, threes_made INT, fga INT, fgm INT, fta INT, ftm INT,
  plus_minus INT, pra INT (points+rebounds+assists), stocks INT (steals+blocks)
predictions:
  game_date TEXT, player_name TEXT, team TEXT, opponent TEXT, home_away TEXT,
  prop_type TEXT, line REAL, prediction TEXT (OVER/UNDER), probability REAL, model_version TEXT
prediction_outcomes:
  game_date TEXT, player_name TEXT, prop_type TEXT, line REAL,
  prediction TEXT (OVER/UNDER), actual_value REAL, outcome TEXT (HIT/MISS), profit REAL

=== NHL DATABASE ===
player_game_logs:
  game_id TEXT, game_date TEXT, player_name TEXT, team TEXT, opponent TEXT,
  is_home INT (1=home 0=away), goals INT, assists INT, points INT,
  shots_on_goal INT, hits INT, blocked_shots INT, toi_seconds INT,
  plus_minus INT, pim INT (penalty minutes)
predictions:
  game_date TEXT, player_name TEXT, team TEXT, opponent TEXT, prop_type TEXT,
  line REAL, prediction TEXT (OVER/UNDER), probability REAL,
  confidence_tier TEXT (T1-ELITE/T2-STRONG/T3-GOOD/T4-LEAN/T5-FADE)
prediction_outcomes:
  game_date TEXT, player_name TEXT, prop_type TEXT, line REAL,
  prediction TEXT (OVER/UNDER), actual_value REAL, outcome TEXT (HIT/MISS)

=== MLB DATABASE ===
player_game_logs:
  game_id TEXT, game_date TEXT, player_name TEXT, team TEXT, opponent TEXT,
  home_away TEXT, player_type TEXT (batter/pitcher),
  innings_pitched REAL, strikeouts_pitched INT, hits_allowed INT, earned_runs INT,
  at_bats INT, hits INT, home_runs INT, rbis INT, runs INT,
  stolen_bases INT, strikeouts_batter INT, total_bases INT
predictions:
  game_date TEXT, player_name TEXT, team TEXT, prop_type TEXT, line REAL,
  prediction TEXT (OVER/UNDER), probability REAL
prediction_outcomes:
  game_date TEXT, player_name TEXT, prop_type TEXT, line REAL,
  prediction TEXT (OVER/UNDER), actual_value REAL, outcome TEXT (HIT/MISS)

QUERY PATTERNS:
- Player name matching: LIKE '%lastname%' for partial matches
- "this season" always add: AND game_date >= '2025-10-01'
- pra column exists directly in NBA player_game_logs
- For hit rates: COUNT CASE WHEN outcome='HIT' / COUNT(*) * 100.0
"""

        _SB_DB_PATHS = {
            "NBA": str(_Path_sb(__file__).parent.parent / "nba" / "database" / "nba_predictions.db"),
            "NHL": str(_Path_sb(__file__).parent.parent / "nhl" / "database" / "nhl_predictions_v2.db"),
            "MLB": str(_Path_sb(__file__).parent.parent / "mlb" / "database" / "mlb_predictions.db"),
        }

        def _sb_get_client():
            xai_key = _os_sb.environ.get("XAI_API_KEY", "")
            if not xai_key:
                # try loading from .env
                env_file = _Path_sb(__file__).parent.parent / ".env"
                if env_file.exists():
                    for line in env_file.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, _, v = line.partition("=")
                            if k.strip() == "XAI_API_KEY":
                                xai_key = v.strip()
                                break
            if not xai_key:
                return None
            try:
                from openai import OpenAI
                return OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
            except ImportError:
                return None

        def _sb_query(db_key: str, sql: str):
            path = _SB_DB_PATHS.get(db_key.upper())
            if not path or not _Path_sb(path).exists():
                return None, f"Database '{db_key}' not found"
            conn = _sqlite3_sb.connect(path)
            conn.row_factory = _sqlite3_sb.Row
            try:
                rows = conn.execute(sql).fetchall()
                conn.close()
                if not rows:
                    return pd.DataFrame(), None
                cols = list(rows[0].keys())
                data = [[r[c] for c in cols] for r in rows[:200]]
                return pd.DataFrame(data, columns=cols), None
            except Exception as e:
                conn.close()
                return None, str(e)

        st.subheader("StatBot — Natural Language DB Query")
        st.caption("Ask anything about NBA, NHL, or MLB player stats, predictions, or hit rates. Powered by Grok.")

        if "statbot_history" not in st.session_state:
            st.session_state.statbot_history = []

        # display history
        for msg in st.session_state.statbot_history:
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant":
                    if msg.get("note"):
                        st.markdown(f"*{msg['note']}*")
                    if msg.get("sql"):
                        st.code(f"[{msg['db']}] {msg['sql']}", language="sql")
                    if msg.get("df") is not None and not msg["df"].empty:
                        st.dataframe(msg["df"], use_container_width=True, hide_index=True)
                    elif msg.get("error"):
                        st.error(msg["error"])
                    elif msg.get("df") is not None:
                        st.info("No results found.")
                else:
                    st.markdown(msg["content"])

        sb_client = _sb_get_client()
        if not sb_client:
            st.warning("XAI_API_KEY not found. StatBot requires Grok access. Set XAI_API_KEY in .env or environment.")
        else:
            user_q = st.chat_input("Ask a question about the data...", key="statbot_input")
            if user_q:
                st.session_state.statbot_history.append({"role": "user", "content": user_q})
                with st.chat_message("user"):
                    st.markdown(user_q)

                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        try:
                            resp = sb_client.chat.completions.create(
                                model="grok-3-mini",
                                messages=[
                                    {"role": "system", "content": _STATBOT_SCHEMA},
                                    {"role": "user", "content": user_q},
                                ],
                                temperature=0,
                            )
                            raw = resp.choices[0].message.content.strip()
                            if raw.startswith("```"):
                                raw = raw.split("```")[1]
                                if raw.startswith("json"):
                                    raw = raw[4:]
                            result = _json_sb.loads(raw.strip())
                            db  = result.get("db", "NBA").upper()
                            sql = result.get("sql", "")
                            note = result.get("note", "")

                            if note:
                                st.markdown(f"*{note}*")
                            if sql:
                                st.code(f"[{db}] {sql}", language="sql")

                            df, err = _sb_query(db, sql)
                            if err:
                                st.error(f"SQL Error: {err}")
                                st.session_state.statbot_history.append({
                                    "role": "assistant", "note": note, "db": db, "sql": sql,
                                    "df": None, "error": f"SQL Error: {err}"
                                })
                            elif df is not None:
                                if not df.empty:
                                    st.dataframe(df, use_container_width=True, hide_index=True)
                                    st.caption(f"{len(df)} row(s) returned.")
                                else:
                                    st.info("No results found.")
                                st.session_state.statbot_history.append({
                                    "role": "assistant", "note": note, "db": db, "sql": sql,
                                    "df": df, "error": None
                                })
                        except _json_sb.JSONDecodeError:
                            st.error("Could not parse AI response. Try rephrasing.")
                            st.session_state.statbot_history.append({
                                "role": "assistant", "note": "", "db": "", "sql": "",
                                "df": None, "error": "Could not parse AI response."
                            })
                        except Exception as e:
                            st.error(f"Error: {e}")
                            st.session_state.statbot_history.append({
                                "role": "assistant", "note": "", "db": "", "sql": "",
                                "df": None, "error": str(e)
                            })

        if st.session_state.statbot_history:
            if st.button("Clear history", key="statbot_clear"):
                st.session_state.statbot_history = []
                st.rerun()

    with tab_system:
        now_str = datetime.now().strftime("%H:%M:%S")
        sys_r1, sys_r2 = st.columns([3, 1])
        sys_r1.markdown("### Orchestrator Health Monitor")
        sys_r2.markdown(
            f'<div class="terminal-refresh">Last loaded: {now_str}</div>',
            unsafe_allow_html=True,
        )

        if st.button("Force refresh", key="sys_refresh"):
            st.cache_data.clear()
            st.rerun()

        health = fetch_orchestrator_health()
        ml_info = get_ml_model_info()

        # ── Sport panels (2-column grid on desktop, stacks on mobile) ─────────
        col_pairs = [
            ("NHL", "NBA"),
            ("MLB", "GOLF"),
        ]

        for left_sport, right_sport in col_pairs:
            c_left, c_right = st.columns(2)
            for col, sport_key in [(c_left, left_sport), (c_right, right_sport)]:
                h = health.get(sport_key, {})
                if not h:
                    col.markdown(
                        f'<div class="terminal-panel">'
                        f'<span class="t-sport">[{sport_key}]</span> '
                        f'<span class="t-err">No data</span></div>',
                        unsafe_allow_html=True,
                    )
                    continue

                status = h["status"]
                failures = h["consecutive_failures"]
                status_html = (
                    '<span class="t-ok">&#9679; HEALTHY</span>' if status == "ok" else
                    f'<span class="t-warn">&#9679; WARNING ({failures} failures)</span>' if status == "warn" else
                    f'<span class="t-err">&#9679; ERRORS ({failures} consecutive)</span>'
                )

                sched = h["schedule"]
                sched_parts = [f'Grade {sched["grading"]}', f'Predict {sched["predictions"]}',
                                f'Sync {sched["pp_sync"]}']
                if sched.get("game_predictions"):
                    sched_parts.append(f'GameLines {sched["game_predictions"]}')
                sched_str = " &nbsp;·&nbsp; ".join(sched_parts)

                # ML progress for this sport
                ml = ml_info.get(sport_key, {})
                ml_count = ml.get("count", 0)
                ml_trained = ml.get("last_trained", "—")
                ml_acc = ml.get("avg_accuracy")
                ml_acc_str = f"{ml_acc*100:.1f}%" if ml_acc else "—"

                # Prediction count with progress toward target
                pred_count = h["pred_count"]
                target = h["ml_target"] * h["ml_combos"]
                pct = min(pred_count / target * 100, 100) if target else 0
                pct_bar_w = int(pct)
                pct_bar_c = "#3fb950" if pct >= 75 else ("#58a6ff" if pct >= 40 else "#f0883e")

                panel_html = f"""
<div class="terminal-panel">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;border-bottom:1px solid #21262d;padding-bottom:8px">
    <span class="t-sport">{h['emoji']} [{sport_key}] {h['name']} Orchestrator</span>
    {status_html}
  </div>

  <div style="margin-bottom:8px">
    <span class="t-label">Predictions &nbsp;</span>
    <span class="t-val" style="font-weight:600">{pred_count:,}</span>
    <span class="t-dim"> / {target:,} target</span>
    <div style="margin-top:4px;background:#21262d;border-radius:4px;height:5px;overflow:hidden">
      <div style="width:{pct_bar_w}%;height:5px;background:{pct_bar_c};border-radius:4px"></div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;margin-bottom:8px;">
    <span><span class="t-label">Last predict</span> <span class="t-val">{h['last_predict']}</span></span>
    <span><span class="t-label">Last grade</span> <span class="t-val">{h['last_grade']}</span></span>
    <span><span class="t-label">Last health</span> <span class="t-val">{h['last_health']}</span></span>
    <span><span class="t-label">Total runs</span> <span class="t-val">{h['total_runs']}</span></span>
  </div>

  <div style="margin-bottom:8px;padding:6px 8px;background:#1c2128;border-radius:6px">
    <span class="t-label" style="font-size:11px">ML &nbsp;</span>
    <span class="t-val">{ml_count} models</span>
    <span class="t-dim"> &nbsp;|&nbsp; </span>
    <span class="t-label">Retrained</span> <span class="t-val">{ml_trained}</span>
    <span class="t-dim"> &nbsp;|&nbsp; </span>
    <span class="t-label">Avg acc</span> <span class="t-val">{ml_acc_str}</span>
  </div>

  <div style="font-size:11px;border-top:1px solid #21262d;padding-top:7px;margin-top:4px">
    <span class="t-label">Schedule &nbsp;</span>
    <span class="t-sched">{sched_str}</span>
  </div>
</div>"""
                col.markdown(panel_html, unsafe_allow_html=True)

        # ── Cloud sync totals ──────────────────────────────────────────────────
        st.divider()
        st.markdown("#### Supabase Sync")
        st.caption("Counts reflect data synced to Supabase. Local SQLite holds full history.")

        sync_cols = st.columns(3)
        for col, sport_name in zip(sync_cols, ["NBA", "NHL", "MLB"]):
            try:
                r = (sb.table("daily_props")
                       .select("id", count="exact")
                       .eq("sport", sport_name)
                       .execute())
                graded = (sb.table("daily_props")
                            .select("id", count="exact")
                            .eq("sport", sport_name)
                            .not_.is_("result", "null")
                            .execute())
                synced = r.count or 0
                graded_n = graded.count or 0
                pct_graded = graded_n / synced * 100 if synced else 0
                col.metric(
                    f"{sport_name}",
                    f"{synced:,} synced",
                    delta=f"{graded_n:,} graded ({pct_graded:.0f}%)",
                )
            except Exception:
                col.metric(sport_name, "—")


if __name__ == "__main__":
    main()
