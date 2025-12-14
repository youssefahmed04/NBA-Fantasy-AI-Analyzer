"""Streaming / Waiver Wire UI components."""

from __future__ import annotations

from typing import Dict, List

from datetime import date as _date
import streamlit as st
from espn_api.basketball import League

from analysis.streaming import recommend_streaming_adds
from core.league import get_profile_by_name
from core.matchup import get_opponent_profile_for_team
from fantasy_models import RosterPlayer, TeamProfile


def render_streaming_tab() -> None:
    """
    Waiver Wire Streaming tab:

      - Pick "My Team".
      - Auto-detect current H2H opponent from ESPN scoreboard.
      - Build a matchup-based need profile (cats you're losing).
      - Recommend free agents who:
            • Actually play on the selected date, and
            • Push the categories you need most, while
            • Accounting for injury risk via AI heuristics.
    """
    league: League = st.session_state.league
    profiles: List[TeamProfile] = st.session_state.team_profiles
    nba_players = st.session_state.nba_players
    category_weights = st.session_state.category_weights

    st.markdown("### Waiver Wire Streaming Coach")
    st.markdown(
        "<span style='font-size:13px; color:#9ca3af;'>"
        "Pick your team, choose a date, and I'll surface one-day streamers that fit your build "
        "and your current matchup."
        "</span>",
        unsafe_allow_html=True,
    )

    if league is None or not profiles or not nba_players:
        st.info(
            "Connect your ESPN league in the sidebar first — I'll then scan the waiver wire "
            "and tell you who to stream based on your current matchup."
        )
        return

    team_names = [tp.team_name for tp in profiles]

    col_sel, col_date = st.columns([1.4, 1.0])
    with col_sel:
        my_team_name = st.selectbox("Your team", team_names, key="stream_my_team")
    with col_date:
        default_date = _date.today()
        stream_date = st.date_input(
            "Streaming date",
            value=default_date,
            key="stream_date_input",
            help="I'll only recommend players who actually have a game on this date (per NBA schedule).",
        )

    my_team = get_profile_by_name(profiles, my_team_name)
    if my_team is None:
        st.warning("Could not find that team in the loaded profiles.")
        return

    # Auto-detect current opponent from scoreboard
    opponent = get_opponent_profile_for_team(league, profiles, my_team)

    with st.container():
        col_ctx_left, col_ctx_right = st.columns([1.6, 1.4])

        with col_ctx_left:
            if opponent:
                st.markdown(
                    f"""
                    <div class="stream-context-card">
                      <div class="stream-context-title">Matchup context</div>
                      <div class="stream-context-body">
                        Using live ESPN scoreboard to detect your opponent:
                        <strong>{opponent.team_name}</strong>.<br/>
                        I'll prioritize categories where you're currently behind or weakest.
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
                    <div class="stream-context-card">
                      <div class="stream-context-title">Matchup context</div>
                      <div class="stream-context-body">
                        No active opponent detected (off week or API limits).<br/>
                        I'll target your weakest categories based on your season-long profile.
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        with col_ctx_right:
            st.markdown(
                """
                <div class="stream-tips-card">
                  <div class="stream-context-title">Streaming tips</div>
                  <ul class="stream-tips-list">
                    <li>Focus on 1–2 categories per stream instead of "fixing everything".</li>
                    <li>Don't be afraid to punt a cat in H2H and overload the rest.</li>
                    <li>Use the injury badge + schedule badge to avoid dead roster spots.</li>
                  </ul>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        "<div style='margin-top:0.75rem; font-size:13px; color:#9ca3af;'>"
        "Click the button below and I'll rank the top waiver options for that day."
        "</div>",
        unsafe_allow_html=True,
    )

    if st.button("🔍 Find Streaming Adds", type="primary", use_container_width=True):
        with st.spinner("Scanning free agents, matchup needs, and schedule..."):
            recs = recommend_streaming_adds(
                league=league,
                profiles=profiles,
                my_team=my_team,
                opponent=opponent,
                category_weights=category_weights,
                nba_players_by_name=nba_players,
                game_date=stream_date,
                max_results=15,
            )

        if not recs:
            st.info(
                "I couldn't find strong streaming options that both fit your needs and play on that day. "
                "Try another date, or expand your league's free agent pool."
            )
            return

        st.subheader(f"Top streaming targets for {stream_date.strftime('%b %d, %Y')}")

        # Quick summary of most-targeted categories across all recs
        cat_counts: Dict[str, int] = {}
        for r in recs:
            for c in r.get("cats_helped", []):
                cat_counts[c] = cat_counts.get(c, 0) + 1

        if cat_counts:
            sorted_cats = sorted(cat_counts.items(), key=lambda x: -x[1])
            top_cats = [c for c, _ in sorted_cats[:4]]
            cats_html = "".join(
                f"<span class='pill pill-positive'>{c}</span>" for c in top_cats
            )
            st.markdown(
                f"""
                <div style="margin-bottom:0.5rem; font-size:13px; color:#9ca3af;">
                  These picks are primarily targeting:&nbsp;{cats_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

        for idx, r in enumerate(recs, start=1):
            rp: RosterPlayer = r["player"]
            score = float(r["score"])
            cats_helped = r.get("cats_helped", [])
            injury_sev = float(r.get("injury_sev", 0.0))
            playing_today = bool(r.get("playing_today", True))
            explanation = r.get("explanation", "")

            # Injury label
            if injury_sev >= 0.8:
                inj_label = "High risk"
                inj_class = "pill pill-negative"
            elif injury_sev >= 0.4:
                inj_label = "Questionable"
                inj_class = "pill pill-neutral"
            else:
                inj_label = "Good to go"
                inj_class = "pill pill-positive"

            headshot_html = (
                f"<img src='{rp.headshot_url}' class='roster-headshot'/>"
                if rp.headshot_url
                else ""
            )

            cats_html = (
                "".join(f"<span class='pill pill-positive'>{cat}</span>" for cat in cats_helped)
                if cats_helped
                else "<span style='color:#9ca3af;'>General all-around boost.</span>"
            )

            playing_badge = (
                "<span class='pill pill-positive'>Plays on selected date</span>"
                if playing_today
                else "<span class='pill pill-negative'>Schedule uncertain</span>"
            )

            pos_text = rp.fantasy_position or ""
            team_text = rp.nba_team_abbrev or ""

            st.markdown(
                f"""
                <div class="stream-card">
                  <div class="stream-card-header">
                    <div class="stream-card-main">
                      {headshot_html}
                      <div class="stream-card-title-block">
                        <div class="stream-player-name">
                          #{idx} · {rp.display_name}
                        </div>
                        <div class="stream-player-meta">
                          {pos_text} · {team_text}
                        </div>
                      </div>
                    </div>
                    <div class="stream-card-score">
                      Matchup fit score<br/><strong>{score:.2f}</strong>
                    </div>
                  </div>
                  <div class="stream-card-body">
                    <div style="margin-bottom:6px;">
                      <span class="{inj_class}">{inj_label}</span>
                      &nbsp;{playing_badge}
                    </div>
                    <div style="margin-bottom:4px; font-size:12px; color:#9ca3af;">
                      Targets:&nbsp;{cats_html}
                    </div>
                    <div style="font-size:12px; color:#d1d5db;">
                      {explanation}
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

