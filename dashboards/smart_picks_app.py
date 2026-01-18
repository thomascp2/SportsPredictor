#!/usr/bin/env python3
"""
Smart Picks Dashboard - Interactive PrizePicks Parlay Builder

A Streamlit app that:
1. Shows ONLY plays actually available on PrizePicks
2. Calculates probabilities for the ACTUAL lines offered
3. Shows Expected Value for different parlay sizes
4. Helps build optimal parlays

Run with: streamlit run dashboards/smart_picks_app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

import streamlit as st
import pandas as pd
from datetime import date, datetime
from smart_pick_selector import SmartPickSelector, SmartPick
from typing import List

# Page config
st.set_page_config(
    page_title="Smart Picks - PrizePicks Parlay Builder",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stMetric > div {
        background-color: #1e1e1e;
        padding: 10px;
        border-radius: 5px;
    }
    .tier-elite { color: #00ff00; font-weight: bold; }
    .tier-strong { color: #90ee90; }
    .tier-good { color: #ffff00; }
    .tier-lean { color: #ffa500; }
    .tier-fade { color: #ff6b6b; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_smart_picks(sport: str, min_edge: float, min_prob: float,
                       include_demon: bool, overs_only: bool) -> List[SmartPick]:
    """Fetch smart picks with caching"""
    selector = SmartPickSelector(sport)

    odds_types = ['standard', 'goblin']
    if include_demon:
        odds_types.append('demon')

    picks = selector.get_smart_picks(
        min_edge=min_edge,
        min_prob=min_prob,
        odds_types=odds_types,
        refresh_lines=False,  # Don't auto-refresh, user can click button
        overs_only=overs_only
    )

    return picks


def picks_to_dataframe(picks: List[SmartPick]) -> pd.DataFrame:
    """Convert picks to DataFrame for display"""
    data = []
    for p in picks:
        data.append({
            'Player': p.player_name,
            'Prop': p.prop_type.upper(),
            'Line': f"{p.prediction} {p.pp_line:.1f}",
            'Type': p.pp_odds_type.title(),
            'Prob': f"{p.pp_probability*100:.1f}%",
            'Edge': f"{p.edge:+.1f}%",
            'Tier': p.tier,
            'EV(4-leg)': f"{p.ev_4leg*100:+.1f}%" if p.ev_4leg > 0 else "---",
            '_prob': p.pp_probability,
            '_edge': p.edge,
            '_tier_order': {'T1-ELITE': 1, 'T2-STRONG': 2, 'T3-GOOD': 3, 'T4-LEAN': 4, 'T5-FADE': 5}.get(p.tier, 6),
            '_ev4': p.ev_4leg,
            '_pick': p
        })
    return pd.DataFrame(data)


def main():
    # Header
    st.title("Smart Picks - PrizePicks Parlay Builder")
    st.markdown(f"**{date.today().strftime('%A, %B %d, %Y')}**")

    # Sidebar filters
    with st.sidebar:
        st.header("Filters")

        sport = st.selectbox("Sport", ["NHL", "NBA"], index=0)

        st.subheader("Edge & Probability")
        min_edge = st.slider("Min Edge %", 0.0, 30.0, 5.0, 1.0)
        min_prob = st.slider("Min Probability %", 50.0, 80.0, 55.0, 1.0) / 100

        st.subheader("Odds Types")
        include_standard = st.checkbox("Standard", value=True)
        include_goblin = st.checkbox("Goblin", value=True)
        include_demon = st.checkbox("Demon", value=False)

        st.subheader("Direction")
        overs_only = st.checkbox("OVERS Only", value=True)

        st.divider()

        if st.button("Refresh PrizePicks Lines", type="primary"):
            selector = SmartPickSelector(sport.lower())
            with st.spinner(f"Fetching {sport} lines..."):
                count = selector.fetch_fresh_lines()
            st.success(f"Fetched {count} lines!")
            st.cache_data.clear()

    # Main content
    # Fetch picks
    picks = fetch_smart_picks(
        sport.lower(),
        min_edge,
        min_prob,
        include_demon,
        overs_only
    )

    if not picks:
        st.warning("No picks match your filters. Try adjusting the settings.")
        return

    df = picks_to_dataframe(picks)

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Picks", len(picks))

    with col2:
        elite = len([p for p in picks if p.tier == 'T1-ELITE'])
        st.metric("T1-ELITE", elite)

    with col3:
        avg_prob = sum(p.pp_probability for p in picks) / len(picks)
        st.metric("Avg Probability", f"{avg_prob*100:.1f}%")

    with col4:
        avg_edge = sum(p.edge for p in picks) / len(picks)
        st.metric("Avg Edge", f"{avg_edge:+.1f}%")

    st.divider()

    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["All Picks", "By Prop Type", "Parlay Builder"])

    with tab1:
        st.subheader("All Smart Picks")

        # Sorting options
        sort_col = st.selectbox(
            "Sort by",
            ["Edge (High to Low)", "Probability (High to Low)", "Tier (Best First)", "EV(4-leg)"],
            index=0
        )

        if sort_col == "Edge (High to Low)":
            df_sorted = df.sort_values('_edge', ascending=False)
        elif sort_col == "Probability (High to Low)":
            df_sorted = df.sort_values('_prob', ascending=False)
        elif sort_col == "Tier (Best First)":
            df_sorted = df.sort_values('_tier_order')
        else:
            df_sorted = df.sort_values('_ev4', ascending=False)

        # Display table (hide internal columns)
        display_cols = ['Player', 'Prop', 'Line', 'Type', 'Prob', 'Edge', 'Tier', 'EV(4-leg)']
        st.dataframe(
            df_sorted[display_cols],
            use_container_width=True,
            height=400,
            hide_index=True
        )

    with tab2:
        st.subheader("Picks by Prop Type")

        # Group by prop type
        prop_types = df['Prop'].unique()

        for prop_type in sorted(prop_types):
            prop_df = df[df['Prop'] == prop_type].sort_values('_edge', ascending=False)

            with st.expander(f"{prop_type} ({len(prop_df)} picks)", expanded=True):
                st.dataframe(
                    prop_df[['Player', 'Line', 'Type', 'Prob', 'Edge', 'Tier']],
                    use_container_width=True,
                    hide_index=True
                )

    with tab3:
        st.subheader("Parlay Builder")

        st.markdown("""
        **How to use:**
        1. Select picks from the checkboxes below
        2. The calculator will show your combined probability and EV
        3. Aim for 4-leg parlays for best risk/reward
        """)

        # Parlay info box
        st.info("""
        **PrizePicks Payouts:**
        - 2 legs: 3x | 3 legs: 5x | 4 legs: 10x | 5 legs: 20x | 6 legs: 25x

        **Optimal Strategy:** 4-leg parlays with T1-ELITE and T2-STRONG picks
        """)

        # Select picks for parlay
        selected_picks = []

        # Show top picks with checkboxes
        st.markdown("**Top Picks (by edge):**")

        top_picks = df.sort_values('_edge', ascending=False).head(20)

        for idx, row in top_picks.iterrows():
            pick = row['_pick']
            col1, col2, col3, col4, col5 = st.columns([0.5, 2, 1.5, 1, 1])

            with col1:
                selected = st.checkbox("", key=f"pick_{idx}", label_visibility="collapsed")
            with col2:
                st.write(f"**{pick.player_name}**")
            with col3:
                st.write(f"{pick.prediction} {pick.pp_line:.1f} {pick.prop_type}")
            with col4:
                st.write(f"{pick.pp_probability*100:.1f}%")
            with col5:
                tier_color = {
                    'T1-ELITE': 'green',
                    'T2-STRONG': 'blue',
                    'T3-GOOD': 'orange',
                    'T4-LEAN': 'red'
                }.get(pick.tier, 'gray')
                st.markdown(f":{tier_color}[{pick.tier}]")

            if selected:
                selected_picks.append(pick)

        # Calculate parlay stats
        st.divider()
        st.subheader("Parlay Calculator")

        if selected_picks:
            # Calculate combined probability
            combined_prob = 1.0
            for p in selected_picks:
                combined_prob *= p.pp_probability

            legs = len(selected_picks)

            # Payout based on legs
            payouts = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 25.0}
            payout = payouts.get(legs, payouts.get(min(legs, 6), 25.0))

            # Calculate EV
            ev = combined_prob * payout - 1

            # Display
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Legs", legs)
            with col2:
                st.metric("Parlay Prob", f"{combined_prob*100:.2f}%")
            with col3:
                st.metric("Payout", f"{payout}x")
            with col4:
                color = "normal" if ev > 0 else "inverse"
                st.metric("Expected Value", f"{ev*100:+.1f}%", delta_color=color)

            # Show selected picks
            st.markdown("**Your Parlay:**")
            for i, p in enumerate(selected_picks, 1):
                st.write(f"{i}. {p.player_name} - {p.prediction} {p.pp_line:.1f} {p.prop_type} @ {p.pp_probability*100:.1f}%")

            # Warning if EV is negative
            if ev < 0:
                st.warning("This parlay has negative expected value. Consider picking higher probability plays.")
            elif ev > 0.5:
                st.success(f"Excellent parlay! {ev*100:.1f}% positive EV")
        else:
            st.info("Select picks above to calculate parlay statistics")


if __name__ == "__main__":
    main()
