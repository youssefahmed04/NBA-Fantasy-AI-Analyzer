"""Matchup analysis and opponent detection."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from espn_api.basketball import League

from config import CATEGORIES
from fantasy_models import TeamProfile


def get_matchup_stats_for_team(
    league: League,
    team_abbrev: str,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Return (my_stats, opp_stats) for the current scoring period, based on ESPN box_scores().

    Each stats dict looks like:
        {
          "FG%":  {"value": 0.487, "result": "WIN"},
          "PTS":  {"value": 418.0, "result": "LOSS"},
          ...
        }
    If no current matchup is found, returns None.
    """
    try:
        box_scores = league.box_scores()
    except Exception:
        return None

    if not box_scores:
        return None

    for bs in box_scores:
        home_team = getattr(bs, "home_team", None)
        away_team = getattr(bs, "away_team", None)

        home_abbrev = getattr(home_team, "team_abbrev", getattr(home_team, "abbr", None)) if home_team else None
        away_abbrev = getattr(away_team, "team_abbrev", getattr(away_team, "abbr", None)) if away_team else None

        if home_abbrev == team_abbrev:
            my_stats = getattr(bs, "home_stats", {}) or {}
            opp_stats = getattr(bs, "away_stats", {}) or {}
            return my_stats, opp_stats
        if away_abbrev == team_abbrev:
            my_stats = getattr(bs, "away_stats", {}) or {}
            opp_stats = getattr(bs, "home_stats", {}) or {}
            return my_stats, opp_stats

    return None


def matchup_need_vector(
    league: League,
    team: TeamProfile,
) -> Dict[str, float]:
    """
    Build a 'need' vector over categories for *this week*, based on the live matchup.

    Idea:
      - Look at the current box score vs your opponent.
      - For each category:
          • If you're LOSING and the margin is small → very high need.
          • If you're LOSING by a lot          → low/medium need (hard to flip with one streamer).
          • If you're WINNING but it's close   → small need (protect lead).
          • If you're WINNING comfortably      → essentially zero need.
      - Respect punts: punted cats get heavily downweighted.
      - Output is normalized so sum(need[cat]) ≈ 1 over CATEGORIES.
    """
    need: Dict[str, float] = {cat: 0.0 for cat in CATEGORIES}
    if league is None:
        return need

    stats_pair = get_matchup_stats_for_team(league, team.team_abbrev)
    if stats_pair is None:
        # No live matchup info (off day / playoffs not started, etc.)
        return need

    my_stats_raw, opp_stats_raw = stats_pair

    # Heuristics for what "close" vs "big" margins mean (relative scale)
    CLOSE_REL = 0.05   # ~within 5% relative → very swingy
    MED_REL = 0.15     # medium deficit window

    for cat in CATEGORIES:
        my_cat = (my_stats_raw.get(cat) or {})
        opp_cat = (opp_stats_raw.get(cat) or {})

        my_val = my_cat.get("value", my_cat.get("score"))
        opp_val = opp_cat.get("value", opp_cat.get("score"))

        if my_val is None or opp_val is None:
            continue

        try:
            my_val_f = float(my_val)
            opp_val_f = float(opp_val)
        except Exception:
            continue

        # Margin from *my* POV: positive = I'm winning, negative = I'm behind.
        if cat == "TOV":
            # Lower is better in turnovers.
            margin = opp_val_f - my_val_f
        else:
            margin = my_val_f - opp_val_f

        # Relative size of the margin so we can talk about 'close' vs 'blowout'
        denom = max(abs(opp_val_f), 1e-3)
        rel = abs(margin) / denom

        if margin >= 0:
            # I'm currently winning this category.
            # Only care if the lead is small (protect the lead).
            if rel < CLOSE_REL:
                # Super fragile lead: small but non-zero need
                need[cat] = 0.4 * (1.0 - rel / CLOSE_REL)
            else:
                need[cat] = 0.0
        else:
            # I'm behind in this category.
            if rel < CLOSE_REL:
                # Very close L → high priority to flip
                need[cat] = 1.0
            elif rel < MED_REL:
                # Medium deficit → medium priority
                need[cat] = 0.6
            else:
                # Huge deficit → still a bit of need, but don't over-invest
                need[cat] = 0.2

    # Respect punts: if you're punting a cat, that cat basically shouldn't drive streaming.
    punt_set = set(team.punt_categories or [])
    for cat in CATEGORIES:
        if cat in punt_set:
            need[cat] *= 0.1  # almost ignore punted cats

    # Normalize to sum ≈ 1 so we can treat it like a probability / weight vector.
    total = sum(need.values())
    if total <= 0:
        return need

    return {cat: val / total for cat, val in need.items()}


def get_opponent_profile_for_team(
    league: League,
    profiles: List[TeamProfile],
    my_team: TeamProfile,
) -> Optional[TeamProfile]:
    """
    Try to infer the current H2H opponent for `my_team` from league.scoreboard().

    Returns the matching TeamProfile or None if we can't find it.
    """
    try:
        box_scores = league.scoreboard()
    except Exception:
        return None

    opp_id: Optional[int] = None

    for bs in box_scores:
        home = getattr(bs, "home_team", None)
        away = getattr(bs, "away_team", None)

        if home and getattr(home, "team_id", None) == my_team.team_id:
            opp_id = getattr(away, "team_id", None)
            break
        if away and getattr(away, "team_id", None) == my_team.team_id:
            opp_id = getattr(home, "team_id", None)
            break

    if opp_id is None:
        return None

    for tp in profiles:
        if tp.team_id == opp_id:
            return tp

    return None

