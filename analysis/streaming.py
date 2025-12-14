"""Streaming and waiver wire analysis."""

from __future__ import annotations

import statistics
from datetime import date as _date
from typing import Any, Dict, List, Optional, Set

from espn_api.basketball import League

from config import CATEGORIES
from fantasy_models import NBADraftPlayer, RosterPlayer, TeamProfile
from analysis.injury import INJURY_KEY, estimate_injury_severity, injury_severity
from analysis.trade import (
    TRADE_CATEGORIES,
    PLAYER_Z_PREFIX,
    _compute_local_player_z,
    _player_effect_vector,
)
from core.matchup import matchup_need_vector

try:
    # Used to detect which NBA teams play on a given date
    from nba_api.stats.endpoints import ScoreboardV2
except Exception:
    ScoreboardV2 = None  # fail-safe if nba_api isn't available


def _teams_playing_on(game_date: Optional[_date]) -> Set[str]:
    """
    Return a set of NBA team abbreviations that have a game on `game_date`.

    If nba_api fails for any reason, we return an empty set and the caller
    should treat that as "unknown" (i.e., don't filter by schedule).
    """
    if game_date is None:
        game_date = _date.today()

    if ScoreboardV2 is None:
        return set()

    try:
        sb = ScoreboardV2(game_date=game_date.strftime("%Y-%m-%d"))
        df = sb.line_score.get_data_frame()
        return set(str(abbr) for abbr in df["TEAM_ABBREVIATION"].unique())
    except Exception:
        return set()


def _build_streaming_needs(
    my_team: TeamProfile,
    opponent: Optional[TeamProfile],
    category_weights: Dict[str, float],
) -> Dict[str, float]:
    """
    Legacy / fallback streaming needs (season-long view).

    For streaming, we care about the *matchup*:

      - If opponent is known:
            need[cat] ∝ max(0, opp_z - my_z) * weight
        (categories where you're behind get higher need)

      - If opponent is unknown:
            fall back to your own weaknesses:
            need[cat] ∝ max(0, -my_z) * weight

    Only uses TRADE_CATEGORIES (no TOV).
    """
    needs: Dict[str, float] = {}

    if opponent is not None:
        for cat in TRADE_CATEGORIES:
            my_z = float(my_team.raw_zscores.get(cat, 0.0))
            opp_z = float(opponent.raw_zscores.get(cat, 0.0))
            diff = opp_z - my_z  # > 0 ⇒ you're behind
            w = float(category_weights.get(cat, 1.0))
            needs[cat] = max(0.0, diff) * w
    else:
        # No opponent info – just lean into fixing your weak cats
        for cat in TRADE_CATEGORIES:
            my_z = float(my_team.raw_zscores.get(cat, 0.0))
            w = float(category_weights.get(cat, 1.0))
            needs[cat] = max(0.0, -my_z) * w

    total = sum(needs.values())
    if total > 0:
        for cat in needs:
            needs[cat] /= total

    return needs


def recommend_streaming_adds(
    league: League,
    profiles: List[TeamProfile],
    my_team: TeamProfile,
    opponent: Optional[TeamProfile],
    category_weights: Dict[str, float],
    nba_players_by_name: Dict[str, NBADraftPlayer],
    game_date: Optional[_date] = None,
    max_results: int = 15,
) -> List[Dict[str, Any]]:
    """
    Recommend waiver-wire streaming adds for a given date.

    AI-ish logic:
      - First, build a matchup-based "need" vector using the *live box score*:
            • Categories you're losing by a small/medium margin
              get the highest need.
            • Categories you're barely winning get some "protect" need.
            • Blowouts (either way) get very low/zero need.
            • Punted categories are heavily downweighted.
      - If no box-score data is available, fall back to a season-long, z-score-based
        need vector via _build_streaming_needs(...).
      - Combine matchup needs with user category weights.
      - Compute local per-player z-scores across the waiver pool.
      - Score each free agent by:
            score(p) = sum_cat need[cat] * z_p[cat] * durability
        and filter to players whose NBA team actually plays that day.
      - Downweight injured players via the same injury severity heuristic.

    Returns a list of dicts:
      {
        "player": RosterPlayer,
        "score": float,
        "cats_helped": List[str],
        "injury_sev": float,
        "playing_today": bool,
        "explanation": str,
      }
    """
    # 1) Figure out which categories we need to catch up in, using LIVE matchup
    matchup_needs_full = matchup_need_vector(league, my_team)

    # Compress to trade categories (we don't stream on TOV)
    needs: Dict[str, float] = {cat: float(matchup_needs_full.get(cat, 0.0)) for cat in TRADE_CATEGORIES}
    total = sum(needs.values())

    if total > 0:
        # Blend in UI weights so user-deemphasized cats matter less even if matchup says otherwise
        for cat in list(needs.keys()):
            w = float(category_weights.get(cat, 1.0))
            needs[cat] *= w

        total = sum(needs.values())
        if total > 0:
            needs = {cat: val / total for cat, val in needs.items()}
    else:
        # No live matchup info or all zeros → fallback to season-long weakness-based needs
        needs = _build_streaming_needs(my_team, opponent, category_weights)

    # 2) Build waiver pool from ESPN free agents
    try:
        fa_raw = league.free_agents(size=200)
    except Exception:
        fa_raw = []

    waiver_players: List[RosterPlayer] = []

    for p in fa_raw:
        name = getattr(p, "name", getattr(p, "full_name", "Unknown Player"))
        pos = getattr(p, "position", "")
        nba_team = getattr(p, "proTeam", "")
        headshot = getattr(p, "headshot", None)

        if not headshot:
            pid = getattr(p, "playerId", getattr(p, "player_id", None))
            if pid:
                headshot = f"https://a.espncdn.com/i/headshots/nba/players/full/{pid}.png"

        nba_stats_player = nba_players_by_name.get(name)
        if not nba_stats_player:
            # If we can't map to NBA stats, we can't meaningfully score this player
            continue

        stats: Dict[str, float] = {cat: 0.0 for cat in CATEGORIES}
        for cat in CATEGORIES:
            stats[cat] = float(nba_stats_player.stats.get(cat, 0.0))

        # Injury info
        status_raw = str(
            getattr(p, "injuryStatus", getattr(p, "injury_status", "")) or ""
        )
        detail_raw = str(
            getattr(
                p,
                "injuryStatusDescription",
                getattr(p, "injuryStatusDetails", ""),
            )
            or ""
        )
        stats[INJURY_KEY] = estimate_injury_severity(status_raw, detail_raw)

        waiver_players.append(
            RosterPlayer(
                display_name=name,
                fantasy_position=pos,
                fantasy_team_abbrev="FA",
                nba_team_abbrev=nba_team,
                headshot_url=headshot or "",
                stats=stats,
            )
        )

    if not waiver_players:
        return []

    # 3) Compute local per-player z-scores over the waiver pool
    _compute_local_player_z(waiver_players)

    # 4) Figure out which NBA teams actually play that day
    teams_playing = _teams_playing_on(game_date)

    results: List[Dict[str, Any]] = []

    for rp in waiver_players:
        nba_team = (rp.nba_team_abbrev or "").upper()

        # If we successfully got a schedule and this team isn't playing, skip
        if teams_playing and nba_team not in teams_playing:
            continue

        eff = _player_effect_vector(rp)

        # Streaming score = how well this player pushes the categories you need
        raw_score = 0.0
        contrib_by_cat: Dict[str, float] = {}
        for cat in TRADE_CATEGORIES:
            contrib = eff[cat] * needs.get(cat, 0.0)
            contrib_by_cat[cat] = contrib
            raw_score += contrib

        if raw_score <= 0.0:
            # Doesn't meaningfully help your matchup needs
            continue

        # Which categories does this player help the most?
        cats_helped = sorted(
            [c for c in TRADE_CATEGORIES if contrib_by_cat.get(c, 0.0) > 0],
            key=lambda c: contrib_by_cat[c],
            reverse=True,
        )[:4]

        sev = injury_severity(rp)
        playing_today = not teams_playing or nba_team in teams_playing

        explanation_parts: List[str] = []
        if cats_helped:
            explanation_parts.append(
                f"Boosts {', '.join(cats_helped)} for this matchup."
            )
        if playing_today:
            explanation_parts.append(f"Plays today for {nba_team}.")
        if sev >= 0.6:
            explanation_parts.append("Carries notable injury risk.")
        elif sev >= 0.3:
            explanation_parts.append("Minor injury notes to monitor.")

        explanation = " ".join(explanation_parts)

        results.append(
            {
                "player": rp,
                "score": raw_score,
                "cats_helped": cats_helped,
                "injury_sev": sev,
                "playing_today": playing_today,
                "explanation": explanation,
            }
        )

    # 5) Rank by streaming score, best first
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:max_results]

