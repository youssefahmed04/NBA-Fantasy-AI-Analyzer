"""League connection, aggregation, and data extraction."""

from __future__ import annotations

import statistics
from typing import Dict, List, Optional, Tuple

from espn_api.basketball import League

from config import CATEGORIES, NEGATIVE_CATEGORIES
from data_loader import load_players_via_api
from fantasy_models import NBADraftPlayer, RosterPlayer, TeamProfile
from analysis.injury import INJURY_KEY, estimate_injury_severity


def build_nba_universe(season: str = "2025-26", top_n: int = 400) -> Dict[str, NBADraftPlayer]:
    """Load NBA per-game stats and index by player name."""
    all_players = load_players_via_api(season=season, top_n=top_n)
    name_to_player: Dict[str, NBADraftPlayer] = {}

    for p in all_players:
        # data_loader Player is expected to have .name, .team, .stats
        name_to_player[p.name] = NBADraftPlayer(name=p.name, team=p.team, stats=p.stats)

    return name_to_player


def aggregate_team_profiles(
    league: League,
    nba_players_by_name: Dict[str, NBADraftPlayer],
) -> List[TeamProfile]:
    """Map ESPN rosters → NBA stats → per-team category totals and raw z-scores."""
    profiles: List[TeamProfile] = []

    # First pass: build TeamProfile objects and aggregate raw category totals
    for team in league.teams:
        profile = TeamProfile(
            team_id=team.team_id,
            team_name=team.team_name,
            team_abbrev=team.team_abbrev,
            logo_url=getattr(team, "logo_url", None),
        )

        # Initialize category totals to zero
        profile.category_totals = {cat: 0.0 for cat in CATEGORIES}

        for player in team.roster:
            name = getattr(player, "name", getattr(player, "full_name", "Unknown Player"))
            pos = getattr(player, "position", "")
            nba_team = getattr(player, "proTeam", "")
            headshot = getattr(player, "headshot", None)

            if not headshot:
                pid = getattr(player, "playerId", getattr(player, "player_id", None))
                if pid:
                    headshot = f"https://a.espncdn.com/i/headshots/nba/players/full/{pid}.png"

            nba_stats_player = nba_players_by_name.get(name)

            stats: Dict[str, float] = {cat: 0.0 for cat in CATEGORIES}
            if nba_stats_player:
                for cat in CATEGORIES:
                    stats[cat] = float(nba_stats_player.stats.get(cat, 0.0))

                for cat, val in stats.items():
                    profile.category_totals[cat] += val

            # Try to capture injury information from ESPN player object
            status_raw = str(
                getattr(player, "injuryStatus", getattr(player, "injury_status", "")) or ""
            )
            detail_raw = str(
                getattr(
                    player,
                    "injuryStatusDescription",
                    getattr(player, "injuryStatusDetails", ""),
                )
                or ""
            )
            stats[INJURY_KEY] = estimate_injury_severity(status_raw, detail_raw)

            profile.players.append(
                RosterPlayer(
                    display_name=name,
                    fantasy_position=pos,
                    fantasy_team_abbrev=team.team_abbrev,
                    nba_team_abbrev=nba_team,
                    headshot_url=headshot or "",
                    stats=stats,
                )
            )

        profiles.append(profile)

    # Second pass: compute league-wide z-scores for each category
    for cat in CATEGORIES:
        values = [tp.category_totals.get(cat, 0.0) for tp in profiles]
        mean = statistics.mean(values) if values else 0.0
        std = statistics.pstdev(values) or 1.0

        for tp in profiles:
            v = tp.category_totals.get(cat, 0.0)
            z = (v - mean) / std

            if cat in NEGATIVE_CATEGORIES:
                z = -z

            tp.raw_zscores[cat] = z

    return profiles


def get_matchups_from_league(league: League) -> List[Dict[str, str]]:
    """High-level matchup list from league.scoreboard()."""
    try:
        box_scores = league.scoreboard()
    except Exception:
        return []

    matchups: List[Dict[str, str]] = []
    for bs in box_scores:
        home_team = getattr(bs, "home_team", None)
        away_team = getattr(bs, "away_team", None)
        if not home_team or not away_team:
            continue

        home_name = getattr(home_team, "team_name", "Home")
        away_name = getattr(away_team, "team_name", "Away")
        home_score = getattr(bs, "home_score", None)
        away_score = getattr(bs, "away_score", None)

        matchup_label = f"{home_name} vs {away_name}"
        score_label = (
            f"{home_score:.1f} – {away_score:.1f}"
            if isinstance(home_score, (int, float)) and isinstance(away_score, (int, float))
            else ""
        )

        matchups.append({"Matchup": matchup_label, "Score": score_label})

    return matchups


def get_standings_from_league(league: League) -> List[Dict[str, str]]:
    """Build a standings table with true win% from W/L/T."""
    try:
        teams_sorted = league.standings()
    except Exception:
        teams_sorted = league.teams

    standings: List[Dict[str, str]] = []
    for idx, t in enumerate(teams_sorted, start=1):
        team_name = getattr(t, "team_name", "Team")

        wins = getattr(t, "wins", None)
        losses = getattr(t, "losses", None)
        ties = getattr(t, "ties", 0) or 0

        record = ""
        pct_str = ""

        if isinstance(wins, (int, float)) and isinstance(losses, (int, float)):
            games = wins + losses + ties
            record = f"{wins}-{losses}" if not ties else f"{wins}-{losses}-{ties}"
            if games > 0:
                win_pct = (wins + 0.5 * ties) / games
                pct_str = f"{win_pct:.3f}"

        standings.append(
            {"Rank": idx, "Team": team_name, "Record": record, "Win %": pct_str}
        )

    return standings


def connect_league(
    league_id: int,
    year: int,
    nba_players: Dict[str, NBADraftPlayer],
    category_weights: Dict[str, float],
    espn_s2: Optional[str] = None,
    swid: Optional[str] = None,
) -> Tuple[League, List[TeamProfile], List[Dict[str, str]], List[Dict[str, str]]]:
    """Create League object, compute team profiles, matchups, and standings."""
    if espn_s2 and swid:
        league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    else:
        league = League(league_id=league_id, year=year)

    # Import here to avoid circular dependency
    from core.team_analysis import apply_weights_and_scores

    profiles = aggregate_team_profiles(league, nba_players)
    apply_weights_and_scores(profiles, category_weights)
    matchups = get_matchups_from_league(league)
    standings = get_standings_from_league(league)

    return league, profiles, matchups, standings


def get_profile_by_name(
    profiles: List[TeamProfile], team_name: str
) -> Optional[TeamProfile]:
    """Find a TeamProfile by ESPN team name."""
    for tp in profiles:
        if tp.team_name == team_name:
            return tp
    return None

