"""Matchup tab UI components."""

from __future__ import annotations

import streamlit as st
from espn_api.basketball import League


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

