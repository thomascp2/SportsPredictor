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
    sb = get_supabase()
    if sb is None:
        return pd.DataFrame()

    q = (sb.table("daily_props")
           .select("player_name,team,opponent,prop_type,line,odds_type,"
                   "ai_prediction,ai_probability,ai_edge,ai_tier,"
                   "ai_ev_4leg,game_time,matchup,status")
           .eq("sport", sport)
           .eq("game_date", game_date)
           .gte("ai_probability", min_prob)
           .lt("ai_probability", 0.95)   # exclude goblin lines (stat model returns 1.0 for trivially easy props)
           .gte("ai_edge", min_edge)
           .neq("status", "cancelled"))

    if direction:
        q = q.eq("ai_prediction", direction)
    if tier_filter:
        q = q.in_("ai_tier", tier_filter)

    r = q.order("ai_probability", desc=True).limit(200).execute()
    if not r.data:
        return pd.DataFrame()

    df = pd.DataFrame(r.data)
    # Enforce PP platform rule: goblin/demon lines only allow OVER bets
    df = df[~(df["odds_type"].isin(["goblin", "demon"]) & (df["ai_prediction"] == "UNDER"))]
    if df.empty:
        return pd.DataFrame()
    df["Prob"]    = (df["ai_probability"] * 100).round(1).astype(str) + "%"
    df["Edge"]    = df["ai_edge"].round(1).apply(lambda x: f"+{x}%" if x >= 0 else f"{x}%")
    df["EV 4-leg"]= df["ai_ev_4leg"].apply(
        lambda x: f"+{x*100:.1f}%" if x and x > 0 else ("---" if not x else f"{x*100:.1f}%")
    )
    df["Line"]    = df["ai_prediction"] + " " + df["line"].astype(str)
    df["Prop"]    = df["prop_type"].str.upper().str.replace("_", " ")
    df["Matchup"] = df["matchup"].fillna(df["team"] + " vs " + df["opponent"])
    df["Time"] = df["game_time"].apply(_fmt_time)
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
    for sport in ["nba", "nhl"]:
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
    for sport in ["NBA", "NHL"]:
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
    tab_picks, tab_perf, tab_system = st.tabs(["Today's Picks", "Performance", "System"])

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1 — TODAY'S PICKS
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_picks:
        # Filters row (compact for mobile)
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        with c1:
            sport = st.selectbox("Sport", ["NBA", "NHL"], label_visibility="collapsed")
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
            ps = st.selectbox("Sport", ["NBA", "NHL"], key="perf_sport")
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
    # TAB 3 — SYSTEM HEALTH
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
        for sport_name in ["NBA", "NHL"]:
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
        for sport_name in ["NBA", "NHL"]:
            info = ml_info.get(sport_name, {})
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric(f"{sport_name} Models", info.get("count", 0))
            mc2.metric("Last Retrained", info.get("last_trained", "—"))
            avg = info.get("avg_accuracy")
            mc3.metric("Avg Accuracy", f"{avg*100:.1f}%" if avg else "—")
        st.caption("Models auto-retrain every Sunday at 2 AM CST (NHL) / 2:30 AM (NBA) "
                   "when 500+ new predictions have accumulated since the last train.")

        st.divider()
        st.caption("Dashboard reads from Supabase. Data syncs after each "
                   "prediction and grading run (6:15 AM CST daily).")
        if st.button("Force refresh all data"):
            st.cache_data.clear()
            st.rerun()


if __name__ == "__main__":
    main()
