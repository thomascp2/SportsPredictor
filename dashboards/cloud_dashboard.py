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
    df["Prob"]    = (df["ai_probability"] * 100).round(1).astype(str) + "%"
    df["Edge"]    = df["ai_edge"].round(1).apply(lambda x: f"+{x}%" if x >= 0 else f"{x}%")
    df["EV 4-leg"]= df["ai_ev_4leg"].apply(
        lambda x: f"+{x*100:.1f}%" if x and x > 0 else ("---" if not x else f"{x*100:.1f}%")
    )
    df["Line"]    = df["ai_prediction"] + " " + df["line"].astype(str)
    df["Prop"]    = df["prop_type"].str.upper().str.replace("_", " ")
    df["Matchup"] = df["matchup"].fillna(df["team"] + " vs " + df["opponent"])
    return df


@st.cache_data(ttl=300)
def fetch_performance(sport: str) -> pd.DataFrame:
    sb = get_supabase()
    if sb is None:
        return pd.DataFrame()
    r = (sb.table("model_performance")
           .select("*")
           .eq("sport", sport)
           .order("calc_date", desc=True)
           .limit(30)
           .execute())
    return pd.DataFrame(r.data) if r.data else pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_recent_results(sport: str, days: int = 7) -> pd.DataFrame:
    sb = get_supabase()
    if sb is None:
        return pd.DataFrame()
    since = (date.today() - timedelta(days=days)).isoformat()
    r = (sb.table("daily_props")
           .select("game_date,ai_prediction,ai_tier,result,ai_probability,prop_type")
           .eq("sport", sport)
           .gte("game_date", since)
           .not_.is_("result", "null")
           .execute())
    return pd.DataFrame(r.data) if r.data else pd.DataFrame()


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
            pt1, pt2, pt3 = st.tabs(["All Picks", "By Prop", "Parlay Builder"])

            display_cols = ["player_name", "Matchup", "Prop", "Line",
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

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2 — PERFORMANCE
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_perf:
        ps = st.selectbox("Sport", ["NBA", "NHL"], key="perf_sport")

        results_df = fetch_recent_results(ps, days=14)

        if not results_df.empty:
            hits = results_df[results_df["result"] == "HIT"]
            total = len(results_df)
            acc = len(hits) / total * 100 if total else 0

            pm1, pm2, pm3, pm4 = st.columns(4)
            pm1.metric("Graded (14d)", total)
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

            # Model performance history
            perf_df = fetch_performance(ps)
            if not perf_df.empty and "overall_accuracy" in perf_df.columns:
                st.divider()
                st.subheader("Model Accuracy Over Time")
                chart_df = perf_df[["calc_date", "overall_accuracy"]].copy()
                chart_df["overall_accuracy"] = (chart_df["overall_accuracy"] * 100).round(1)
                chart_df = chart_df.rename(columns={
                    "calc_date": "Date", "overall_accuracy": "Accuracy %"
                }).sort_values("Date")
                st.line_chart(chart_df.set_index("Date"))
        else:
            st.info(f"No graded results yet for {ps} in the last 14 days.")

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

        st.subheader("Data Totals")
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
            tc1.metric(f"{sport_name} Total Props", f"{r.count:,}")
            tc2.metric(f"{sport_name} Graded", f"{graded.count:,}")

        st.divider()
        st.caption("Dashboard reads from Supabase. Data syncs after each "
                   "prediction and grading run (6:15 AM CST daily).")
        if st.button("Force refresh all data"):
            st.cache_data.clear()
            st.rerun()


if __name__ == "__main__":
    main()
