from __future__ import annotations

from typing import Dict, List

import pandas as pd
import streamlit as st
from espn_api.basketball import League
from datetime import date as _date

from config import CATEGORIES
from fantasy_models import TeamProfile, RosterPlayer
from services import (
    apply_weights_and_scores,
    connect_league,
    get_profile_by_name,
    generate_trade_suggestions,
    get_opponent_profile_for_team,
    recommend_streaming_adds,
)


# -------------------------
# Sidebar
# -------------------------


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


# -------------------------
# League overview UI
# -------------------------


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


# -------------------------
# Matchups tab UI
# -------------------------


def render_matchups_tab() -> None:
    """Current Matchups tab: detailed per-category matchup tables."""
    league: League = st.session_state.league

    st.markdown(
        "<div class='section-title' style='margin-top:0.75rem;'>Matchup Details</div>",
        unsafe_allow_html=True,
    )

    if league is None:
        st.markdown(
            "<span style='font-size:13px; color:#9ca3af;'>Connect a league to see matchup details.</span>",
            unsafe_allow_html=True,
        )
        return

    try:
        box_scores = league.box_scores()
    except Exception as e:
        st.markdown(
            f"<span style='font-size:13px; color:#9ca3af;'>Could not load matchup details: {e}</span>",
            unsafe_allow_html=True,
        )
        return

    if not box_scores:
        st.markdown(
            "<span style='font-size:13px; color:#9ca3af;'>No box score data available for this scoring period.</span>",
            unsafe_allow_html=True,
        )
        return

    _render_matchup_detail_cards(box_scores)


def _render_matchup_detail_cards(box_scores) -> None:
    """ESPN-style per-category matchup view with highlighted winners (FG%, FT%, 3PM, REB, AST, STL, BLK, TO, PTS)."""

    def season_record(team) -> str:
        w = getattr(team, "wins", None)
        l = getattr(team, "losses", None)
        ties = getattr(team, "ties", 0) or 0
        if not (isinstance(w, (int, float)) and isinstance(l, (int, float))):
            return ""
        return f"{int(w)}-{int(l)}" if not ties else f"{int(w)}-{int(l)}-{int(ties)}"

    def fmt_val(cat: str, v):
        if v is None:
            return "-"
        try:
            v = float(v)
        except Exception:
            return str(v)
        if cat in ("FG%", "FT%"):
            return f"{v:.4f}".lstrip("0")  # .4892 style
        if abs(v - round(v)) < 1e-6:
            return str(int(round(v)))
        return f"{v:.1f}"

    cat_order = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "TO", "PTS"]

    for bs in box_scores:
        home_team = getattr(bs, "home_team", None)
        away_team = getattr(bs, "away_team", None)
        if not home_team or not away_team:
            continue

        home_name = getattr(home_team, "team_name", str(home_team))
        away_name = getattr(away_team, "team_name", str(away_team))
        home_abbrev = getattr(home_team, "team_abbrev", getattr(home_team, "abbr", "HOME"))
        away_abbrev = getattr(away_team, "team_abbrev", getattr(away_team, "abbr", "AWAY"))

        home_rec = season_record(home_team)
        away_rec = season_record(away_team)

        home_stats = getattr(bs, "home_stats", {}) or {}
        away_stats = getattr(bs, "away_stats", {}) or {}

        if not home_stats or not away_stats:
            st.markdown(
                "<span style='font-size:12px; color:#9ca3af;'>No category stats yet for this matchup.</span>",
                unsafe_allow_html=True,
            )
            continue

        cats = [c for c in cat_order if c in home_stats]

        home_w = home_l = home_t = 0
        away_w = away_l = away_t = 0
        for cat in cats:
            h_res = (home_stats.get(cat) or {}).get("result")
            a_res = (away_stats.get(cat) or {}).get("result")
            if h_res == "WIN":
                home_w += 1
            elif h_res == "LOSS":
                home_l += 1
            elif h_res == "TIE":
                home_t += 1
            if a_res == "WIN":
                away_w += 1
            elif a_res == "LOSS":
                away_l += 1
            elif a_res == "TIE":
                away_t += 1

        def week_record(w, l, t):
            if w == l == t == 0:
                return ""
            return f"{w}-{l}-{t}" if t else f"{w}-{l}"

        home_week = week_record(home_w, home_l, home_t)
        away_week = week_record(away_w, away_l, away_t)

        header_cells = "".join(
            f"<th class='matchup-cat-header'>{cat}</th>" for cat in cats
        )

        home_cells = ""
        away_cells = ""
        for cat in cats:
            hs = home_stats.get(cat, {}) or {}
            as_ = away_stats.get(cat, {}) or {}

            h_val = hs.get("value", hs.get("score"))
            a_val = as_.get("value", as_.get("score"))
            h_res = hs.get("result")
            a_res = as_.get("result")

            h_class = ""
            a_class = ""
            if h_res == "WIN":
                h_class = "matchup-cell-win"
            elif h_res == "TIE":
                h_class = "matchup-cell-tie"
                a_class = "matchup-cell-tie"
            if a_res == "WIN":
                a_class = "matchup-cell-win"

            home_cells += f"<td class='{h_class}'>{fmt_val(cat, h_val)}</td>"
            away_cells += f"<td class='{a_class}'>{fmt_val(cat, a_val)}</td>"

        home_row = f"<tr><td class='matchup-team-cell'>{home_abbrev}</td>{home_cells}</tr>"
        away_row = f"<tr><td class='matchup-team-cell'>{away_abbrev}</td>{away_cells}</tr>"

        html = f"""
        <div class="matchup-detail-card">
          <div class="matchup-header-row">
            <div>
              <div class="matchup-header-names">{home_name} vs {away_name}</div>
              <div class="matchup-header-sub">
                {home_abbrev}: {home_rec or "–"} &nbsp;·&nbsp;
                {away_abbrev}: {away_rec or "–"}
              </div>
            </div>
            <div class="matchup-header-record">
              {home_week or "–"} &nbsp;&nbsp;|&nbsp;&nbsp; {away_week or "–"}
            </div>
          </div>
          <table class="matchup-table">
            <thead>
              <tr>
                <th></th>{header_cells}
              </tr>
            </thead>
            <tbody>
              {home_row}
              {away_row}
            </tbody>
          </table>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)


# -------------------------
# Team analyzer UI
# -------------------------


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


# -------------------------
# Trade Analyzer UI
# -------------------------


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
        "Pick two teams and I’ll search for **multi-player deals** that "
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


# -------------------------
# Streaming / Waiver Wire UI
# -------------------------


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
        "Pick your team, choose a date, and I’ll surface one-day streamers that fit your build "
        "and your current matchup."
        "</span>",
        unsafe_allow_html=True,
    )

    if league is None or not profiles or not nba_players:
        st.info(
            "Connect your ESPN league in the sidebar first — I’ll then scan the waiver wire "
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
            help="I’ll only recommend players who actually have a game on this date (per NBA schedule).",
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
                        I’ll prioritize categories where you're currently behind or weakest.
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
                        I’ll target your weakest categories based on your season-long profile.
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
                    <li>Focus on 1–2 categories per stream instead of “fixing everything”.</li>
                    <li>Don’t be afraid to punt a cat in H2H and overload the rest.</li>
                    <li>Use the injury badge + schedule badge to avoid dead roster spots.</li>
                  </ul>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        "<div style='margin-top:0.75rem; font-size:13px; color:#9ca3af;'>"
        "Click the button below and I’ll rank the top waiver options for that day."
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
