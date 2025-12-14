"""Sidebar controls for league connection and category weights."""

from __future__ import annotations

from typing import Dict, List

import streamlit as st

from config import CATEGORIES
from core.league import connect_league, get_profile_by_name
from core.team_analysis import apply_weights_and_scores
from fantasy_models import TeamProfile


def sidebar_controls() -> None:
    st.sidebar.markdown("### League Connection")

    league_id = st.sidebar.text_input(
        "ESPN League ID",
        value=st.session_state.get("input_league_id", ""),
        placeholder="e.g. 123456",
    )
    year = st.sidebar.number_input(
        "Season Year", min_value=2018, max_value=2030, value=2026, step=1
    )

    st.sidebar.markdown(
        "<small>For <b>public</b> leagues, League ID + Year is enough. "
        "For private leagues, optionally add cookies below.</small>",
        unsafe_allow_html=True,
    )

    espn_s2 = st.sidebar.text_input(
        "espn_s2 cookie (optional for public)", type="password"
    )
    swid = st.sidebar.text_input(
        "SWID cookie (optional for public)", type="password"
    )

    if st.sidebar.button("Connect to League", use_container_width=True):
        if not league_id:
            st.sidebar.error("Please enter a League ID.")
        else:
            try:
                with st.spinner("Connecting to ESPN and analyzing rosters..."):
                    league, profiles, matchups, standings = connect_league(
                        league_id=int(league_id),
                        year=int(year),
                        nba_players=st.session_state.nba_players,
                        category_weights=st.session_state.category_weights,
                        espn_s2=espn_s2 or None,
                        swid=swid or None,
                    )
                    st.session_state.league = league
                    st.session_state.team_profiles = profiles
                    st.session_state.matchups = matchups
                    st.session_state.standings = standings
                    st.session_state.input_league_id = league_id
                st.sidebar.success("League loaded! Scroll to see analysis.")
            except Exception as e:
                st.sidebar.error(f"Error connecting to league: {e}")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Category Weights")

    weights: Dict[str, float] = st.session_state.category_weights
    for cat in CATEGORIES:
        label = f"{cat} weight"
        if cat == "TOV":
            label += " (x0.25 in score)"
        weights[cat] = st.sidebar.slider(
            label, 0.0, 2.0, float(weights.get(cat, 1.0)), 0.1
        )

    st.session_state.category_weights = weights

    if st.sidebar.button(" Recalculate Scores", use_container_width=True):
        league = st.session_state.league
        profiles: List[TeamProfile] = st.session_state.team_profiles
        if league and profiles:
            apply_weights_and_scores(profiles, weights)
            st.sidebar.success("Scores updated!")

