"""League overview UI components."""

from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st
from espn_api.basketball import League

from fantasy_models import TeamProfile


def render_hero_and_metrics() -> None:
    league: League = st.session_state.league
    profiles: List[TeamProfile] = st.session_state.team_profiles

    league_name = (
        getattr(league, "league_name", "Fantasy Basketball League")
        if league
        else "Fantasy Basketball League"
    )

    with st.container():
        col_hero, col_metrics = st.columns([2.2, 1.3])

        with col_hero:
            st.markdown(
                """
                <div class="hero-card">
                    <div class="hero-pill">
                        LIVE LEAGUE ANALYZER · 9-CAT · AI COACH
                    </div>
                    <h1 style="margin-top: 14px; margin-bottom: 6px;">
                        Fantasy League AI Assistant
                    </h1>
                    <h3 style="margin-top: 0; color:#9ca3af; font-weight:400; font-size:15px;">
                        Real-time strength & punt detection, matchup context, and roster analytics —
                        all powered by NBA stats and your ESPN fantasy league.
                    </h3>
                    <div style="margin-top:18px; font-size:13px; color:#9ca3af;">
                        League:&nbsp;
                        <span style="color:#e5e7eb; font-weight:600;">
                        """
                + league_name
                + """
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with col_metrics:
            teams_count = len(profiles)
            total_players = sum(len(tp.players) for tp in profiles)
            best_score = max((tp.total_score for tp in profiles), default=0.0)

            st.markdown(
                f"""
                <div class="metric-card" style="margin-bottom:10px;">
                    <div class="metric-label">Teams in league</div>
                    <div class="metric-value">{teams_count}</div>
                    <div class="metric-subvalue">Rosters analyzed with NBA per-game stats.</div>
                </div>
                <div class="metric-card" style="margin-bottom:10px;">
                    <div class="metric-label">Players tracked</div>
                    <div class="metric-value">{total_players}</div>
                    <div class="metric-subvalue">Mapped from ESPN rosters → NBA stats.</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Top team score</div>
                    <div class="metric-value">{best_score:.2f}</div>
                    <div class="metric-subvalue">Overall weighted 9-cat z-score (TOV at 0.25 strength).</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_standings_section() -> None:
    """Standings only (used in League Overview tab)."""
    standings = st.session_state.standings

    st.markdown('<div class="section-title">Standings</div>', unsafe_allow_html=True)
    if standings:
        df = pd.DataFrame(standings)
        st.dataframe(df, use_container_width=True, height=260)
    else:
        st.markdown(
            "<span style='font-size:13px; color:#9ca3af;'>Standings not available from ESPN API.</span>",
            unsafe_allow_html=True,
        )

