"""Trade analyzer UI components."""

from __future__ import annotations

from typing import List

import streamlit as st
from espn_api.basketball import League

from analysis.trade import generate_trade_suggestions
from core.league import get_profile_by_name
from fantasy_models import RosterPlayer, TeamProfile


def render_trade_analyzer() -> None:
    """
    Trade Analyzer tab:
      1. Pick two teams.
      2. Run the AI engine to find multi-player trades that:
            • Improve both teams' builds (fit gain > 0),
            • Pass a z-score + injury-aware fairness check.
      3. Display up to 3 trade ideas as cards.
    """
    league: League = st.session_state.league
    profiles: List[TeamProfile] = st.session_state.team_profiles

    if league is None or not profiles:
        st.info("Connect your ESPN league in the sidebar to get trade suggestions.")
        return

    st.markdown("### 🤝 Trade Analyzer")
    st.write(
        "Pick two teams and I'll search for **multi-player deals** that "
        "**reinforce each roster's strengths** while passing a "
        "**market-value fairness check** (using z-scores + injury risk)."
    )

    team_names = [tp.team_name for tp in profiles]

    col_a, col_b = st.columns(2)
    with col_a:
        team_a_name = st.selectbox("Team A", team_names, key="trade_team_a")
    with col_b:
        default_b_idx = 1 if len(team_names) > 1 else 0
        team_b_name = st.selectbox(
            "Team B", team_names, index=default_b_idx, key="trade_team_b"
        )

    if team_a_name == team_b_name:
        st.warning("Choose **two different** teams to analyze a trade.")
        return

    team_a = get_profile_by_name(profiles, team_a_name)
    team_b = get_profile_by_name(profiles, team_b_name)

    if team_a is None or team_b is None:
        st.error("Could not find one of the selected teams in the loaded profiles.")
        return

    if st.button("💡 Generate Trade Ideas", type="primary", use_container_width=True):
        with st.spinner("Scanning rosters, strengths, and fairness..."):
            suggestions = generate_trade_suggestions(
                team_a=team_a,
                team_b=team_b,
                category_weights=st.session_state.category_weights,
            )

        if not suggestions:
            st.info(
                "I couldn't find obvious win–win trades for these teams that are also fair. "
                "Try different teams or tweak category weights in the sidebar."
            )
            return

        for idx, s in enumerate(suggestions, start=1):
            pack_a: List[RosterPlayer] = s["from_a"]
            pack_b: List[RosterPlayer] = s["from_b"]
            improve_a = s["improve_a"]
            improve_b = s["improve_b"]
            ai_reason = s.get("ai_reason", "")
            fairness = float(s.get("fairness", 1.0))
            combined_fit = s["gain_a"] + s["gain_b"]

            names_a = ", ".join(f"{p.display_name} ({p.fantasy_position})" for p in pack_a)
            names_b = ", ".join(f"{p.display_name} ({p.fantasy_position})" for p in pack_b)

            header_score_text = f"Fit gain: {combined_fit:.2f} · Fairness: {fairness:.2f}"

            st.markdown(
                f"""
                <div class="trade-card">
                  <div class="trade-card-header">
                    <span class="trade-card-title">Trade Idea #{idx}</span>
                    <span class="trade-card-score">{header_score_text}</span>
                  </div>
                  <div class="trade-card-body">
                """,
                unsafe_allow_html=True,
            )

            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown(f"**{team_a.team_name}**")
                st.write(f"▫️ Sends: **{names_a}**")
                st.write(f"▫️ Receives: **{names_b}**")
                if improve_a:
                    st.caption("Helps most in: " + ", ".join(improve_a))
                st.caption(f"Fit gain for this roster: `{s['gain_a']:.2f}`")

            with col_right:
                st.markdown(f"**{team_b.team_name}**")
                st.write(f"▫️ Sends: **{names_b}**")
                st.write(f"▫️ Receives: **{names_a}**")
                if improve_b:
                    st.caption("Helps most in: " + ", ".join(improve_b))
                st.caption(f"Fit gain for this roster: `{s['gain_b']:.2f}`")

            if ai_reason:
                st.markdown(
                    "<div style='margin-top:8px; font-size:12px; color:#9ca3af;'>"
                    f"<em>{ai_reason}</em></div>",
                    unsafe_allow_html=True,
                )

            st.markdown("</div></div>", unsafe_allow_html=True)

