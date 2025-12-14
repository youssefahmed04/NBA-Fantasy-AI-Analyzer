from __future__ import annotations

import streamlit as st

from config import CATEGORIES
from core.league import build_nba_universe
from styling import inject_css
from ui.sidebar import sidebar_controls
from ui.league_view import render_hero_and_metrics, render_standings_section
from ui.matchup_view import render_matchups_tab
from ui.team_view import render_ai_coach_and_team_detail
from ui.trade_view import render_trade_analyzer
from ui.streaming_view import render_streaming_tab


def init_session() -> None:
    """Initialize Streamlit session_state with shared objects."""
    if "nba_players" not in st.session_state:
        st.session_state.nba_players = build_nba_universe()

    if "category_weights" not in st.session_state:
        st.session_state.category_weights = {cat: 1.0 for cat in CATEGORIES}

    if "league" not in st.session_state:
        st.session_state.league = None
    if "team_profiles" not in st.session_state:
        st.session_state.team_profiles = []
    if "matchups" not in st.session_state:
        st.session_state.matchups = []
    if "standings" not in st.session_state:
        st.session_state.standings = []


def main() -> None:
    st.set_page_config(
        page_title="Fantasy League AI Assistant",
        page_icon="🏀",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    inject_css()
    init_session()
    sidebar_controls()

    st.markdown("")

    if st.session_state.league is None or not st.session_state.team_profiles:
        st.markdown("### Fantasy League AI Assistant")
        st.write(
            "Connect your ESPN league in the left sidebar to see live analysis of all teams, "
            "matchups, and AI-driven advice."
        )
        return

    (
        tab_league,
        tab_matchups,
        tab_team,
        tab_trades,
        tab_streaming,
    ) = st.tabs(
        [
            "League Overview",
            "Current Matchups",
            "Team Analyzer",
            "Trade Analyzer",
            "Streaming / Waiver Wire",
        ]
    )

    with tab_league:
        render_hero_and_metrics()
        st.markdown("")
        render_standings_section()

    with tab_matchups:
        render_matchups_tab()

    with tab_team:
        render_ai_coach_and_team_detail()

    with tab_trades:
        render_trade_analyzer()

    with tab_streaming:
        render_streaming_tab()


if __name__ == "__main__":
    main()
