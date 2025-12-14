"""Team analyzer UI components."""

from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st

from config import CATEGORIES
from core.league import get_profile_by_name
from fantasy_models import TeamProfile


def render_ai_coach_and_team_detail() -> None:
    profiles: List[TeamProfile] = st.session_state.team_profiles
    if not profiles:
        st.info("Connect your ESPN league in the sidebar to see analysis.")
        return

    team_names = [tp.team_name for tp in profiles]
    selected_team_name = st.selectbox("Select team to analyze", team_names, index=0)
    profile = get_profile_by_name(profiles, selected_team_name)
    if profile is None:
        st.warning("Could not find selected team profile.")
        return

    strengths = profile.strength_categories
    punts = profile.punt_categories

    strengths_html = (
        "".join(f"<span class='pill pill-positive'>{cat}</span>" for cat in strengths)
        or "<span style='color:#9ca3af;'>None detected yet.</span>"
    )
    punts_html = (
        "".join(f"<span class='pill pill-negative'>{cat}</span>" for cat in punts)
        or "<span style='color:#9ca3af;'>No obvious punts detected.</span>"
    )

    st.markdown(
        f"""
        <div class="coach-card">
            <div class="coach-title">AI Coach Summary</div>
            <div class="coach-body">
                <p>
                    Team <strong>{profile.team_name}</strong> has an overall weighted league score of
                    <strong>{profile.total_score:.2f}</strong>.
                </p>
                <ul>
                    <li>
                        This roster is <strong>built to win in</strong>:
                        {strengths_html}
                    </li>
                    <li style="margin-top:6px;">
                        The <strong>auto-detected punt strategy</strong> is:
                        {punts_html}
                    </li>
                    <li style="margin-top:6px;">
                        In trades, you should aim to <strong>double down on your strengths</strong> and
                        move players who hurt those categories or don't fit your punt plan.
                        <span style="color:#9ca3af;">
                            Tip: tweak category weights in the sidebar to mirror your league settings.
                        </span>
                    </li>
                </ul>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("")

    st.subheader("Category Profile (team z-scores)")
    z_df = pd.DataFrame(
        {
            "Category": CATEGORIES,
            "Z-score": [profile.raw_zscores.get(cat, 0.0) for cat in CATEGORIES],
        }
    )
    st.bar_chart(z_df.set_index("Category"), height=260)

    # Roster table: current season per-game stats
    st.subheader("Roster – Current Season Per-Game Stats")
    stat_cols = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TOV"]

    rows = []
    for rp in profile.players:
        headshot_html = (
            f"<img src='{rp.headshot_url}' class='roster-headshot'/>"
            if rp.headshot_url
            else ""
        )

        row = {
            "Headshot": headshot_html,
            "Player": rp.display_name,
            "Pos": rp.fantasy_position or "",
            "Team": rp.nba_team_abbrev or "",
        }

        for cat in stat_cols:
            val = rp.stats.get(cat)
            if val is None:
                row[cat] = "-"
            else:
                if cat in ("FG%", "FT%"):
                    row[cat] = f"{val * 100:.1f}%"
                else:
                    row[cat] = f"{val:.1f}"

        rows.append(row)

    df = pd.DataFrame(rows, columns=["Headshot", "Player", "Pos", "Team"] + stat_cols)
    st.markdown(
        df.to_html(escape=False, index=False, classes="roster-table"),
        unsafe_allow_html=True,
    )

