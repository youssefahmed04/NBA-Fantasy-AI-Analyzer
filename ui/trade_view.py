"""Trade analyzer UI components."""

from __future__ import annotations

from typing import List

import streamlit as st
from espn_api.basketball import League

from analysis.trade import (
    generate_trade_suggestions,
    evaluate_trade_for_team,
    TRADE_CATEGORIES,
)
from analysis.trade_enhanced import generate_enhanced_trade_suggestions
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

    st.markdown("### Trade Analyzer")
    st.write(
        "Pick two teams and I'll search for **multi-player deals** that "
        "**reinforce each roster's strengths** while passing a "
        "**market-value fairness check** (using z-scores + injury risk)."
    )

    # Enhanced analysis option
    use_enhanced = st.checkbox(
        "✨ Use Enhanced Analysis",
        value=False,
        help=(
            "Enhanced analysis includes: diminishing returns on category improvements, "
            "volatility weighting, category swing value, and correlation penalties. "
            "Better at finding trades that actually move the needle in close matchups."
        ),
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
            if use_enhanced:
                suggestions = generate_enhanced_trade_suggestions(
                    team_a=team_a,
                    team_b=team_b,
                    category_weights=st.session_state.category_weights,
                )
            else:
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

    # Manual Trade Evaluation Section
    st.markdown("---")
    st.markdown("### Manual Trade Evaluation")
    st.write(
        "Evaluate a specific trade you're considering. Select players from each team "
        "and see how it impacts **Team A**."
    )

    eval_use_enhanced = st.checkbox(
        "✨ Use Enhanced Analysis (for evaluation)",
        value=False,
        key="eval_enhanced",
        help="Use enhanced analysis for manual trade evaluation.",
    )

    eval_col_a, eval_col_b = st.columns(2)
    
    with eval_col_a:
        eval_team_a_name = st.selectbox(
            "Your Team (Team A)", team_names, key="eval_team_a"
        )
        eval_team_a = get_profile_by_name(profiles, eval_team_a_name)
        
        if eval_team_a:
            eval_team_a_players = [p.display_name for p in eval_team_a.players]
            eval_players_out = st.multiselect(
                "Players you're sending",
                eval_team_a_players,
                key="eval_players_out",
                help="Select one or more players you're trading away.",
            )
    
    with eval_col_b:
        eval_team_b_name = st.selectbox(
            "Trading Partner (Team B)", 
            [tn for tn in team_names if tn != eval_team_a_name],
            key="eval_team_b",
        )
        eval_team_b = get_profile_by_name(profiles, eval_team_b_name)
        
        if eval_team_b:
            eval_team_b_players = [p.display_name for p in eval_team_b.players]
            eval_players_in = st.multiselect(
                "Players you're receiving",
                eval_team_b_players,
                key="eval_players_in",
                help="Select one or more players you're receiving.",
            )

    if st.button("🔍 Evaluate Trade", type="primary", use_container_width=True, key="eval_trade"):
        if not eval_team_a or not eval_team_b:
            st.error("Please select both teams.")
        elif not eval_players_out:
            st.warning("Please select at least one player you're sending.")
        elif not eval_players_in:
            st.warning("Please select at least one player you're receiving.")
        else:
            # Find the actual player objects
            players_out_objs = [
                p for p in eval_team_a.players 
                if p.display_name in eval_players_out
            ]
            players_in_objs = [
                p for p in eval_team_b.players 
                if p.display_name in eval_players_in
            ]

            if len(players_out_objs) != len(eval_players_out):
                st.error("Some selected players not found in Team A roster.")
            elif len(players_in_objs) != len(eval_players_in):
                st.error("Some selected players not found in Team B roster.")
            else:
                with st.spinner("Evaluating trade..."):
                    evaluation = evaluate_trade_for_team(
                        team=eval_team_a,
                        players_out=players_out_objs,
                        players_in=players_in_objs,
                        category_weights=st.session_state.category_weights,
                        use_enhanced=eval_use_enhanced,
                    )

                # Display evaluation results
                fit_gain = evaluation["fit_gain"]
                recommendation = evaluation["recommendation"]
                improve_cats = evaluation["improve_categories"]
                hurt_cats = evaluation["hurt_categories"]
                fairness = evaluation["fairness_estimate"]
                pos_delta = evaluation["position_balance_delta"]
                market_out = evaluation["market_value_out"]
                market_in = evaluation["market_value_in"]

                # Recommendation card
                rec_color = "green" if fit_gain > 0.1 else "orange" if fit_gain > 0 else "red"
                
                # Determine value assessment text
                if fairness > 0.9:
                    value_text = "You're getting good value"
                elif fairness > 0.8:
                    value_text = "Fair value"
                else:
                    value_text = "You may be overpaying"
                
                st.markdown(
                    f"""
                    <div class="coach-card">
                        <div class="coach-title" style="color: {rec_color};">
                            {recommendation}
                        </div>
                        <div class="coach-body">
                            <p><strong>Overall Fit Gain:</strong> {fit_gain:.3f}</p>
                            <p><strong>Value Fairness:</strong> {fairness:.2f} ({value_text})</p>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Category breakdown
                col_cats_left, col_cats_right = st.columns(2)
                
                with col_cats_left:
                    st.markdown("#### 📈 Categories Improved")
                    if improve_cats:
                        for cat in improve_cats:
                            gain = evaluation["per_cat_gain"].get(cat, 0.0)
                            st.markdown(
                                f"- **{cat}**: +{gain:.3f}",
                            )
                    else:
                        st.markdown("*No significant improvements*")
                
                with col_cats_right:
                    st.markdown("#### 📉 Categories Hurt")
                    if hurt_cats:
                        for cat in hurt_cats:
                            gain = evaluation["per_cat_gain"].get(cat, 0.0)
                            st.markdown(
                                f"- **{cat}**: {gain:.3f}",
                            )
                    else:
                        st.markdown("*No significant losses*")

                # Additional details
                with st.expander("📋 Detailed Analysis"):
                    st.markdown("**Market Values:**")
                    st.write(f"- Players you're sending: {market_out:.2f}")
                    st.write(f"- Players you're receiving: {market_in:.2f}")
                    st.write(f"- Net value: {market_in - market_out:.2f}")
                    
                    st.markdown("**Position Balance:**")
                    if pos_delta > 0.1:
                        st.write(f"✅ Improves position balance (+{pos_delta:.2f})")
                    elif pos_delta < -0.1:
                        st.write(f"⚠️ Worsens position balance ({pos_delta:.2f})")
                    else:
                        st.write(f"➡️ Neutral position impact ({pos_delta:.2f})")
                    
                    st.markdown("**All Category Changes:**")
                    for cat in TRADE_CATEGORIES:
                        gain = evaluation["per_cat_gain"].get(cat, 0.0)
                        if abs(gain) > 0.001:
                            st.write(f"- {cat}: {gain:+.3f}")

                # Trade summary
                names_out = ", ".join(p.display_name for p in players_out_objs)
                names_in = ", ".join(p.display_name for p in players_in_objs)
                
                st.markdown(
                    f"""
                    <div class="trade-card">
                        <div class="trade-card-header">
                            <span class="trade-card-title">Trade Summary</span>
                        </div>
                        <div class="trade-card-body">
                            <p><strong>{eval_team_a_name}</strong> sends: <strong>{names_out}</strong></p>
                            <p><strong>{eval_team_a_name}</strong> receives: <strong>{names_in}</strong></p>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

