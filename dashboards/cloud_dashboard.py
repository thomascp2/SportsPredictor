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

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FreePicks Dashboard",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="collapsed",   # collapsed = better on mobile
)

st.markdown("""
<style>
    /* Tighten padding on mobile */
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    /* Tier badge colours */
    .tier-elite  { color: #00e676; font-weight: bold; }
    .tier-strong { color: #69f0ae; }
    .tier-good   { color: #ffee58; }
    .tier-lean   { color: #ffa726; }
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
        # "2026-03-01T19:10:00+00:00" or "2026-03-01T13:10:00-05:00"
        s = str(ts)
        # Parse offset
        if '+' in s[10:]:
            base, off = s[:19], s[19:]
            sign = 1
            off = off.lstrip('+')
        elif s[19:20] == '-':
            base = s[:19]
            off = s[20:]
            sign = -1
        else:
            base, sign, off = s[:19], 0, '00:00'
        h_off, m_off = (int(x) for x in off.split(':')[:2])
        offset_min = sign * (h_off * 60 + m_off)
        dt = datetime.strptime(base, '%Y-%m-%dT%H:%M:%S')
        # Convert to ET (UTC-5 in winter, UTC-4 in summer)
        utc_dt = dt - timedelta(minutes=offset_min)
        et_dt = utc_dt - timedelta(hours=5)  # EST
        h = et_dt.hour % 12 or 12
        ampm = 'PM' if et_dt.hour >= 12 else 'AM'
        return f"{h}:{et_dt.minute:02d} {ampm} ET"
    except Exception:
        return ""


# ── Data fetchers ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_picks(sport: str, game_date: str, min_prob: float, min_edge: float,
                direction: Optional[str], tier_filter: list) -> pd.DataFrame:
    """
    Load today's smart picks directly from SQLite via SmartPickSelector.
    SQLite is the authoritative source for picks — Supabase sync can have
    stale or degenerate probability values before the migration is applied.
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
                           "ai_prediction,ai_probability,ai_edge,game_time")
                   .eq("sport", sport)
                   .eq("game_date", game_date)
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
                "ai_tier":        "—",
                "ai_ev_4leg":     None,
                "game_time":      p.get("game_time"),
                "matchup":        f"{p.get('team','')} vs {p.get('opponent','')}",
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["Prob"]     = (df["ai_probability"] * 100).round(1).astype(str) + "%"
        df["Edge"]     = df["ai_edge"].round(1).apply(lambda x: f"+{x}%" if x >= 0 else f"{x}%")
        df["EV 4-leg"] = "—"
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


# Break-even rates (must match smart_pick_selector.py BREAK_EVEN)
_BREAK_EVEN = {"standard": 0.56, "goblin": 0.76, "demon": 0.45}
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

                    be = _BREAK_EVEN.get(r["odds_type"], 0.56)
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


# ── Main app ──────────────────────────────────────────────────────────────────
def main():
    st.title("FreePicks Dashboard")
    st.caption(f"Last refresh: {datetime.now().strftime('%b %d %Y  %H:%M')}")

    sb = get_supabase()
    if sb is None:
        st.error("Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY.")
        st.info("Local run: set env vars.  Streamlit Cloud: add in app Secrets UI.")
        return

    # ── Top-level tabs ────────────────────────────────────────────────────────
    tab_picks, tab_perf, tab_season, tab_hb, tab_system = st.tabs(
        ["Today's Picks", "Performance", "MLB Season Props", "NHL Hits & Blocks", "System"]
    )

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
    # TAB 2 — PERFORMANCE
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
        days_shown = (date_range[1] - date_range[0]).days
        st.caption(f"Showing {days_shown}-day window ({perf_start} to {perf_end}). "
                   "DNP records (actual_value=0) excluded.")

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
                    BREAK_EVEN = {"standard": 0.56, "goblin": 0.76, "demon": 0.45}
                    ot_rows = []
                    for ot in ["standard", "goblin", "demon"]:
                        sub = df_cal[df_cal["odds_type"] == ot]
                        if len(sub) >= 5:
                            hr = sub["hit"].mean() * 100
                            avg_prob = sub["ai_probability"].mean() * 100
                            be = BREAK_EVEN.get(ot, 0.56) * 100
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

        sf1, sf2, sf3, sf4 = st.columns([2, 1, 1, 1])
        with sf1:
            stat_sel_label = st.selectbox("Stat", stat_options,
                                          key="sp_stat", label_visibility="visible")
            stat_sel = STAT_LABELS.get(stat_sel_label) if stat_sel_label != 'All' else None
        with sf2:
            ptype_sel = st.selectbox("Player type", ["All", "Batters", "Pitchers"],
                                     key="sp_ptype")
            ptype_map = {"Batters": "batter", "Pitchers": "pitcher", "All": None}
            ptype_filter = ptype_map[ptype_sel]
        with sf3:
            conf_sel = st.selectbox("Min confidence", ["All", "MEDIUM+", "HIGH only"],
                                    key="sp_conf")
            conf_map = {"All": "VERY LOW", "MEDIUM+": "MEDIUM", "HIGH only": "HIGH"}
            conf_filter = conf_map[conf_sel]
        with sf4:
            if st.button("Refresh projections", use_container_width=True, key="sp_refresh"):
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

                sort_col = st.selectbox("Sort by", ["Projection", "Player", "Confidence"],
                                        key="sp_sort")
                asc = sort_col == "Player"
                display_df = display_df.sort_values(sort_col, ascending=asc)

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
    # TAB 5 — SYSTEM HEALTH
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_system:
        st.subheader("Pipeline Status")
        pipeline = fetch_pipeline_status()

        for sport_name, info in pipeline.items():
            last = info["last_date"]
            count = info["count"]
            today_str = date.today().isoformat()
            yesterday_str = (date.today() - timedelta(days=1)).isoformat()

            if last == today_str:
                status_icon = "✅"
                status_msg = "Today's predictions synced"
            elif last == yesterday_str:
                status_icon = "🟡"
                status_msg = "Yesterday — today's run pending"
            else:
                status_icon = "🔴"
                status_msg = f"Last seen {last}"

            sc1, sc2, sc3 = st.columns([1, 2, 2])
            sc1.metric(sport_name, status_icon)
            sc2.metric("Last Date", last)
            sc3.metric("Predictions", f"{count:,}")
            st.caption(status_msg)
            st.divider()

        st.subheader("Cloud-Synced Totals")
        st.caption("Counts reflect data synced to Supabase. Historical predictions "
                   "pre-dating the sync layer live in local SQLite only.")
        for sport_name in ["NBA", "NHL", "MLB"]:
            r = (sb.table("daily_props")
                   .select("id", count="exact")
                   .eq("sport", sport_name)
                   .execute())
            graded = (sb.table("daily_props")
                        .select("id", count="exact")
                        .eq("sport", sport_name)
                        .not_.is_("result", "null")
                        .execute())
            tc1, tc2 = st.columns(2)
            tc1.metric(f"{sport_name} Synced Props", f"{r.count:,}")
            tc2.metric(f"{sport_name} Graded", f"{graded.count:,}")

        st.divider()
        st.subheader("ML Models")
        ml_info = get_ml_model_info()
        for sport_name in ["NBA", "NHL", "MLB"]:
            info = ml_info.get(sport_name, {})
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric(f"{sport_name} Models", info.get("count", 0))
            mc2.metric("Last Retrained", info.get("last_trained", "—"))
            avg = info.get("avg_accuracy")
            mc3.metric("Avg Accuracy", f"{avg*100:.1f}%" if avg else "—")
        st.caption("Models auto-retrain every Sunday at 2 AM CST (NHL) / 2:30 AM (NBA) / 8:30 AM (MLB) "
                   "when 500+ new predictions have accumulated since the last train. "
                   "MLB ML training target: 7,500 per prop/line combo (targets 2027 season).")

        st.divider()
        st.caption("Dashboard reads from Supabase. Data syncs after each "
                   "prediction and grading run (6:15 AM CST daily).")
        if st.button("Force refresh all data"):
            st.cache_data.clear()
            st.rerun()


if __name__ == "__main__":
    main()
