# services.py

from __future__ import annotations

import re
import statistics
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple, Set
from datetime import date as _date

from espn_api.basketball import League

from config import CATEGORIES, NEGATIVE_CATEGORIES, TURNOVER_WEIGHT
from data_loader import load_players_via_api
from fantasy_models import NBADraftPlayer, RosterPlayer, TeamProfile

try:
    # Used to detect which NBA teams play on a given date
    from nba_api.stats.endpoints import ScoreboardV2
except Exception:
    ScoreboardV2 = None  # fail-safe if nba_api isn't available

# Special key we stash injury severity into inside the stats dict
INJURY_KEY = "__INJ_SEV__"

# Categories to use for trade/streaming logic (ignore turnovers completely there)
TRADE_CATEGORIES = [c for c in CATEGORIES if c != "TOV"]

# Prefix used for per-player z-scores inside the stats dict
PLAYER_Z_PREFIX = "__Z__"


# -------------------------
# Injury heuristics
# -------------------------


def _estimate_injury_severity(status_raw: str, detail_raw: str) -> float:
    """
    Map ESPN-style injury strings → [0,1] severity.

    This is intentionally heuristic:
      - 0.0  ~ fully healthy
      - 0.3  ~ minor, day-to-day / probable
      - 0.6  ~ questionable / short multi-game absence
      - 1.0  ~ clearly out / IR or long-ish absence
    """
    if not status_raw and not detail_raw:
        return 0.0

    status = (status_raw or "").upper()
    detail = (detail_raw or "").lower()

    # Base on status label
    base = 0.0
    if any(tag in status for tag in ["OUT", "INJ", "IL", "IR"]):
        base = 1.0
    elif any(tag in status for tag in ["DOUBTFUL"]):
        base = 0.8
    elif any(tag in status for tag in ["QUESTIONABLE", "QST", "Q"]):
        base = 0.6
    elif any(tag in status for tag in ["DAY-TO-DAY", "DTD", "GTD", "PROBABLE"]):
        base = 0.3

    # Look for explicit durations in the description ("3 weeks", "10 days", etc.)
    duration_severity = 0.0
    m = re.search(r"(\d+)\s*(day|days|wk|wks|week|weeks)", detail)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        # Roughly map #days/weeks → 0..1 severity
        if "day" in unit:
            approx_games_missed = num  # ~1 game per day in a dense schedule
        else:
            approx_games_missed = num * 3  # ~3 games per week

        duration_severity = min(1.0, approx_games_missed / 10.0)

    return float(min(1.0, max(base, duration_severity)))


def _injury_severity(player: RosterPlayer) -> float:
    """Read precomputed injury severity from the stats dict."""
    try:
        return float(player.stats.get(INJURY_KEY, 0.0))
    except Exception:
        return 0.0


def _avg_injury_severity(players: List[RosterPlayer]) -> float:
    if not players:
        return 0.0
    return sum(_injury_severity(p) for p in players) / len(players)


# -------------------------
# Position helpers
# -------------------------


def _primary_position(pos_str: str) -> str:
    """
    Extract a single primary position from ESPN's position string.
    Examples:
      "PG" → "PG"
      "PG/SG" → "PG"
      "SF,PF" → "SF"
      "" or None → "UTIL"
    """
    if not pos_str:
        return "UTIL"
    s = pos_str.replace(" ", "").replace("-", "/")
    parts = s.split("/") if "/" in s else s.split(",")
    return parts[0].upper() if parts and parts[0] else "UTIL"


def _position_counts(players: List[RosterPlayer]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for p in players:
        pos = _primary_position(getattr(p, "fantasy_position", ""))
        counts[pos] = counts.get(pos, 0) + 1
    return counts


def _position_balance_delta(
    team: TeamProfile,
    players_out: List[RosterPlayer],
    players_in: List[RosterPlayer],
) -> float:
    """
    Compute how much this swap improves position balance.

    We treat the "ideal" number per position as:
        ideal = roster_size / (#unique_positions_on_roster)

    Then we compare total distance to this ideal before vs after.
    Positive return value ⇒ after-trade roster is more balanced.
    """
    before = _position_counts(team.players)
    if not before:
        return 0.0

    roster_size = len(team.players)
    num_positions = max(1, len(before))
    ideal = roster_size / float(num_positions)

    # Distance helper
    def dist(counts: Dict[str, int]) -> float:
        keys = set(before.keys()) | set(counts.keys())
        return sum(abs(counts.get(k, 0) - ideal) for k in keys)

    dist_before = dist(before)

    after = dict(before)
    for p in players_out:
        pos = _primary_position(getattr(p, "fantasy_position", ""))
        after[pos] = after.get(pos, 0) - 1
    for p in players_in:
        pos = _primary_position(getattr(p, "fantasy_position", ""))
        after[pos] = after.get(pos, 0) + 1

    dist_after = dist(after)
    return dist_before - dist_after  # > 0 ⇒ improved balance


def _position_note(delta: float) -> str:
    """
    Human-readable note for how position balance changes.
    """
    if delta > 0.4:
        return "Improves positional balance and helps avoid lineup logjams."
    if 0.15 < delta <= 0.4:
        return "Slightly improves positional balance across your roster."
    if delta < -0.4:
        return "Creates a noticeable positional imbalance — double-check your lineup slots."
    if -0.4 <= delta < -0.15:
        return "Slightly worsens positional balance; be mindful of your lineup constraints."
    return ""


# -------------------------
# NBA + fantasy aggregation
# -------------------------


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
            stats[INJURY_KEY] = _estimate_injury_severity(status_raw, detail_raw)

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


def apply_weights_and_scores(
    profiles: List[TeamProfile],
    category_weights: Dict[str, float],
) -> None:
    """
    - Compute weighted z-scores + total_score for each team.
    - Detect punts & strengths with simple, fantasy-realistic thresholds:

        • Manual punt: any category with weight == 0  → always in punts,
          and not counted toward total score.

        • Auto punts (1–3 max):
            - Look only at categories with weight > 0.
            - Consider cats with z < 0 as weak.
            - If any cats have z <= -0.5, punt up to the worst 3 of those.
            - Else, if only slightly negative, punt just the single worst cat.

        • Strengths:
            - Non-punted categories with z >= +0.4.
            - Take the top 4 strongest by z-score.
    """

    for tp in profiles:
        tp.weighted_zscores = {}
        total = 0.0

        # -------- Weighted z-scores & total score (respect manual weights) --------
        for cat in CATEGORIES:
            base_z = tp.raw_zscores.get(cat, 0.0)
            base_weight = category_weights.get(cat, 1.0)

            # If user sets weight to 0, treat as a hard punt and exclude from score.
            if base_weight <= 0.0:
                continue

            eff_weight = base_weight * (TURNOVER_WEIGHT if cat == "TOV" else 1.0)
            weighted_z = base_z * eff_weight

            tp.weighted_zscores[cat] = weighted_z
            total += weighted_z

        tp.total_score = total

        # -------- Manual punts (from UI weights) --------
        manual_punts = [
            cat for cat in CATEGORIES if category_weights.get(cat, 1.0) == 0.0
        ]

        # -------- Auto punts based on z-scores --------
        z_vals = {
            cat: tp.raw_zscores.get(cat, 0.0)
            for cat in CATEGORIES
            if category_weights.get(cat, 1.0) > 0.0
        }

        # Weak = below league average; serious weak = clearly bad.
        weak_cats = [cat for cat, z in z_vals.items() if z < 0.0]
        serious_weak = [cat for cat, z in z_vals.items() if z <= -0.5]

        auto_punts: List[str] = []

        if serious_weak:
            serious_weak_sorted = sorted(serious_weak, key=lambda c: z_vals[c])
            auto_punts = serious_weak_sorted[:3]
        elif weak_cats:
            weakest = min(weak_cats, key=lambda c: z_vals[c])
            auto_punts = [weakest]
        else:
            auto_punts = []

        punt_set = set(manual_punts) | set(auto_punts)
        punts = [cat for cat in CATEGORIES if cat in punt_set]

        # -------- Strengths (non-punted, clearly above average) --------
        strength_candidates = [
            (cat, z)
            for cat, z in z_vals.items()
            if cat not in punt_set and z >= 0.4
        ]
        strength_candidates.sort(key=lambda x: x[1], reverse=True)
        strengths = [cat for cat, _ in strength_candidates[:4]]

        tp.punt_categories = punts
        tp.strength_categories = strengths


# -------------------------
# League helpers
# -------------------------


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


def _get_matchup_stats_for_team(
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


def _matchup_need_vector(
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

    stats_pair = _get_matchup_stats_for_team(league, team.team_abbrev)
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


def get_matchup_category_needs(
    league: League,
    team: TeamProfile,
) -> List[Dict[str, Any]]:
    """
    Expose a detailed, matchup-aware view per category:

      [
        {
          "category": "PTS",
          "my_value": 410.0,
          "opp_value": 432.0,
          "margin": -22.0,          # >0 = you're ahead, <0 = behind (TOV flipped)
          "relative_gap": 0.05,     # |margin| / max(|opp_value|, 1e-3)
          "status": "LOSING",       # WIN / LOSS / TIE
          "need_weight": 0.23,      # from matchup_need_vector (normalized)
        },
        ...
      ]
    """
    out: List[Dict[str, Any]] = []
    if league is None:
        return out

    stats_pair = _get_matchup_stats_for_team(league, team.team_abbrev)
    if stats_pair is None:
        return out

    my_stats_raw, opp_stats_raw = stats_pair
    need_vec = _matchup_need_vector(league, team)

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

        if cat == "TOV":
            margin = opp_val_f - my_val_f  # positive margin = you're "winning" (fewer TOV)
        else:
            margin = my_val_f - opp_val_f

        denom = max(abs(opp_val_f), 1e-3)
        rel = abs(margin) / denom

        if abs(margin) < 1e-6:
            status = "TIE"
        elif margin > 0:
            status = "WIN"
        else:
            status = "LOSS"

        out.append(
            {
                "category": cat,
                "my_value": my_val_f,
                "opp_value": opp_val_f,
                "margin": margin,
                "relative_gap": rel,
                "status": status,
                "need_weight": float(need_vec.get(cat, 0.0)),
            }
        )

    return out


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


# -------------------------
# Matchup / streaming helpers
# -------------------------


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


# -------------------------
# Trade engine
# -------------------------


def _build_preference_vector(
    team: TeamProfile,
    category_weights: Dict[str, float],
) -> Dict[str, float]:
    """
    Build a normalized preference vector over categories for a given team.

    Intuition:
      - Categories where the team is already strong (positive z-score)
        get higher weight → we lean into existing strengths.
      - Punted categories are still considered but heavily downweighted.
      - Category weights from the UI scale the preference as well.
    """
    prefs: Dict[str, float] = {}
    punt_set = set(team.punt_categories or [])
    strengths_set = set(team.strength_categories or [])

    for cat in TRADE_CATEGORIES:
        z = float(team.raw_zscores.get(cat, 0.0))
        w = float(category_weights.get(cat, 1.0))

        # Base preference from team profile
        if cat in strengths_set and z > 0:
            # Strong cat → lean hard into it
            base = 1.0 + 0.5 * max(z, 0.0)
        elif z > 0:
            # Mild positive → still treat as a plus
            base = 0.7 + 0.3 * z
        else:
            # Weak/neutral cats get a smaller but non-zero weight
            # so we can still accept trades that clean up holes.
            base = 0.4 + 0.2 * (-min(z, 0.0))

        if cat in punt_set:
            base *= 0.3  # heavily reduce punted cats

        score = max(0.0, base * w)
        prefs[cat] = score

    total = sum(prefs.values())
    if total <= 0:
        # Fallback to uniform if something goes weird
        n = len(TRADE_CATEGORIES)
        return {cat: 1.0 / n for cat in TRADE_CATEGORIES}

    return {cat: val / total for cat, val in prefs.items()}


def _market_value(player: RosterPlayer, category_weights: Dict[str, float]) -> float:
    """
    Team-agnostic estimate of how valuable a player is in a standard 9-cat build.

    Used only for fairness checks: both sides should be sending/receiving similar
    total market value even if the *fit* of those players is very different.
    """
    sev = _injury_severity(player)
    durability = 1.0 - 0.7 * max(0.0, min(1.0, sev))

    total = 0.0
    for cat in TRADE_CATEGORIES:
        w = float(category_weights.get(cat, 1.0))
        z = float(player.stats.get(f"{PLAYER_Z_PREFIX}{cat}", 0.0))
        total += w * z

    return total * durability


def _fairness_score_for_packages(
    pack_a: List[RosterPlayer],
    pack_b: List[RosterPlayer],
    category_weights: Dict[str, float],
) -> float:
    """
    Symmetric fairness metric based on team-agnostic market values.

    Returns a score in (0,1]; 1.0 = perfectly even value, ~0.85+ is typically
    'fantasy fair'. Below that, one side is clearly overpaying.
    """
    val_a = sum(_market_value(p, category_weights) for p in pack_a)
    val_b = sum(_market_value(p, category_weights) for p in pack_b)

    avg = (abs(val_a) + abs(val_b)) / 2.0
    if avg <= 1e-6:
        # Both basically sending replacement-level talent
        return 1.0

    diff = abs(val_a - val_b)
    return max(0.0, 1.0 - diff / avg)


def _compute_local_player_z(players: List[RosterPlayer]) -> None:
    """
    Compute simple z-scores for each trade category across the given
    player pool and stash them in player.stats[f"{PLAYER_Z_PREFIX}{cat}"].

    This gives us a league-local normalization so that we can compare
    players across very different raw stat profiles.
    """
    if not players:
        return

    for cat in TRADE_CATEGORIES:
        vals = [float(p.stats.get(cat, 0.0)) for p in players]
        mean = statistics.mean(vals) if vals else 0.0
        std = statistics.pstdev(vals) or 1.0

        for p in players:
            raw = float(p.stats.get(cat, 0.0))
            z = (raw - mean) / std
            p.stats[f"{PLAYER_Z_PREFIX}{cat}"] = z


def _player_effect_vector(player: RosterPlayer) -> Dict[str, float]:
    """
    Convert a player's stat line into a 'fantasy effect' vector for trades/streaming.

    - Uses per-category z-scores computed across the relevant player pool.
    - Only uses TRADE_CATEGORIES (no TOV).
    - Higher is always better here.
    - We downweight injured players by a durability factor derived from injury severity.
    """
    effect: Dict[str, float] = {}
    severity = _injury_severity(player)
    # 0  → fully healthy (factor 1.0)
    # 1  → very injured / IR (factor ~0.3)
    durability = 1.0 - 0.7 * max(0.0, min(1.0, severity))

    for cat in TRADE_CATEGORIES:
        z_val = float(player.stats.get(f"{PLAYER_Z_PREFIX}{cat}", 0.0))
        effect[cat] = z_val * durability
    return effect


def _package_effect_vector(
    players: List[RosterPlayer],
) -> Dict[str, float]:
    """
    Sum effect vectors across a group of players (for multi-player packages).
    """
    agg: Dict[str, float] = {cat: 0.0 for cat in TRADE_CATEGORIES}
    for p in players:
        eff = _player_effect_vector(p)
        for cat in TRADE_CATEGORIES:
            agg[cat] += eff[cat]
    return agg


def _score_package_for_team(
    team: TeamProfile,
    preferences: Dict[str, float],
    players_out: List[RosterPlayer],
    players_in: List[RosterPlayer],
) -> Tuple[float, Dict[str, float]]:
    """
    Score how much this team improves by swapping out players_out for players_in.

    We combine:
      - 'Fit' improvement w.r.t. the team's preference vector over categories.
      - Position balance improvement (small bonus if roster becomes more balanced).

    Returns:
      - total_gain: single scalar 'how good' this is for the team.
      - per_cat_gain: dictionary of per-category contributions (for explanations).
    """
    out_eff = _package_effect_vector(players_out)
    in_eff = _package_effect_vector(players_in)

    total_gain = 0.0
    per_cat_gain: Dict[str, float] = {}

    for cat in TRADE_CATEGORIES:
        delta_raw = in_eff[cat] - out_eff[cat]
        weight = float(preferences.get(cat, 0.0))
        delta = delta_raw * weight
        per_cat_gain[cat] = delta
        total_gain += delta

    # Position-balance term: small but real effect
    pos_delta = _position_balance_delta(team, players_out, players_in)
    pos_weight = 0.12  # tuned to matter, but not dominate categories
    pos_gain = pos_weight * pos_delta
    per_cat_gain["_pos_balance"] = pos_gain
    total_gain += pos_gain

    return total_gain, per_cat_gain


def _compute_fairness(gain_a: float, gain_b: float) -> float:
    """
    Return a fairness score in [0,1], where 1 is perfectly fair (equal gains).
    (Currently unused; kept for potential alternative fairness experiments.)
    """
    total = max(gain_a + gain_b, 1e-8)
    gap = abs(gain_a - gain_b)
    return max(0.0, 1.0 - gap / total)


def _build_injury_note(
    team_a: TeamProfile,
    team_b: TeamProfile,
    pack_a: List[RosterPlayer],
    pack_b: List[RosterPlayer],
) -> str:
    """
    Natural-language summary of how injury risk shifts between the two teams.
    """
    sev_a_out = _avg_injury_severity(pack_a)
    sev_a_in = _avg_injury_severity(pack_b)
    sev_b_out = _avg_injury_severity(pack_b)
    sev_b_in = _avg_injury_severity(pack_a)

    delta_a = sev_a_in - sev_a_out
    delta_b = sev_b_in - sev_b_out

    pieces: List[str] = []

    if delta_a < -0.15:
        pieces.append(f"{team_a.team_name} sheds some injury risk in this deal.")
    elif delta_a > 0.15:
        pieces.append(f"{team_a.team_name} takes on a bit more injury risk for upside.")

    if delta_b < -0.15:
        pieces.append(f"{team_b.team_name} also ends up healthier after the swap.")
    elif delta_b > 0.15:
        pieces.append(f"{team_b.team_name} absorbs slightly more risk in return for stats.")

    return " ".join(pieces)


def _build_ai_reason(
    team_a: TeamProfile,
    team_b: TeamProfile,
    pack_a: List[RosterPlayer],
    pack_b: List[RosterPlayer],
    per_cat_a: Dict[str, float],
    per_cat_b: Dict[str, float],
    gain_a: float,
    gain_b: float,
    fairness_score: float,
) -> str:
    """
    Generate a short natural-language explanation of why this trade is fair & helpful.
    """

    def top_help(per_cat: Dict[str, float]) -> List[str]:
        return sorted(
            [c for c in TRADE_CATEGORIES if per_cat.get(c, 0.0) > 0],
            key=lambda c: per_cat[c],
            reverse=True,
        )[:3]

    help_a = top_help(per_cat_a)
    help_b = top_help(per_cat_b)

    # Injury risk deltas
    def avg_sev(players: List[RosterPlayer]) -> float:
        if not players:
            return 0.0
        return sum(_injury_severity(p) for p in players) / len(players)

    sev_a_out = avg_sev(pack_a)
    sev_a_in = avg_sev(pack_b)
    sev_b_out = avg_sev(pack_b)
    sev_b_in = avg_sev(pack_a)

    inj_lines: List[str] = []
    if sev_a_out > sev_a_in + 0.2:
        inj_lines.append(f"{team_a.team_name} also sheds some injury risk.")
    if sev_b_out > sev_b_in + 0.2:
        inj_lines.append(f"{team_b.team_name} lightens its injury risk as well.")

    # Position-balance commentary
    pos_delta_a = _position_balance_delta(team_a, pack_a, pack_b)
    pos_delta_b = _position_balance_delta(team_b, pack_b, pack_a)
    pos_lines: List[str] = []
    if pos_delta_a > 0.2 or pos_delta_b > 0.2:
        pos_lines.append("The swap smooths out roster positions instead of creating logjams.")

    lines: List[str] = []

    if help_a:
        lines.append(
            f"{team_a.team_name} gets clear help in {', '.join(help_a)}, "
            f"directly reinforcing its existing build."
        )
    if help_b:
        lines.append(
            f"{team_b.team_name} improves in {', '.join(help_b)}, "
            f"without giving up its core strengths."
        )

    if pos_lines:
        lines.extend(pos_lines)
    if inj_lines:
        lines.extend(inj_lines)

    lines.append(
        f"Overall, both sides trade away and receive similar total value "
        f"(fairness ≈ {fairness_score:.2f}), so neither team is clearly overpaying."
    )

    return " ".join(lines)


def generate_trade_suggestions(
    team_a: TeamProfile,
    team_b: TeamProfile,
    category_weights: Dict[str, float],
    max_trades: int = 3,
) -> List[Dict[str, Any]]:
    """
    Generate fair trade suggestions between team A and team B.

    Logic:
      - Use local per-player z-scores (over both rosters) as the base features.
      - Fit:
          • Each team has a preference vector over categories built from its strengths.
          • A trade must give both teams positive fit gain.
      - Fairness:
          • Each player has a team-agnostic market value.
          • Both sides must send/receive similar total market value
            (fairness_score >= 0.85).
      - Extras:
          • Injuries downweight player impact and market value.
          • Position balance gives a small bonus to trades that unjam positions.
      - Consider 1-for-1, 1-for-2, 2-for-1, and 2-for-2 packages.
    """
    # 1) Compute local z-scores for all players in the trade universe
    all_players: List[RosterPlayer] = list(team_a.players) + list(team_b.players)
    _compute_local_player_z(all_players)

    # 2) Build preference vectors (what each team *wants* more of)
    prefs_a = _build_preference_vector(team_a, category_weights)
    prefs_b = _build_preference_vector(team_b, category_weights)

    suggestions: List[Dict[str, Any]] = []

    # Allow asymmetric sizes: 1 or 2 players from each side
    sizes = (1, 2)

    for size_a in sizes:
        combos_a = list(combinations(team_a.players, size_a))
        for size_b in sizes:
            combos_b = list(combinations(team_b.players, size_b))

            for pack_a in combos_a:
                pack_a_list = list(pack_a)
                names_a = {p.display_name for p in pack_a_list}

                for pack_b in combos_b:
                    pack_b_list = list(pack_b)
                    names_b = {p.display_name for p in pack_b_list}

                    # Avoid silly "trading the same player back and forth" cases
                    if names_a == names_b:
                        continue

                    # 3) Fit gain for both teams
                    fit_a, per_cat_a = _score_package_for_team(
                        team=team_a,
                        preferences=prefs_a,
                        players_out=pack_a_list,
                        players_in=pack_b_list,
                    )

                    fit_b, per_cat_b = _score_package_for_team(
                        team=team_b,
                        preferences=prefs_b,
                        players_out=pack_b_list,
                        players_in=pack_a_list,
                    )

                    # Both teams must actually like the trade for their build
                    if fit_a <= 0.0 or fit_b <= 0.0:
                        continue

                    total_fit = fit_a + fit_b
                    if total_fit <= 0.05:
                        # Tiny nudges aren't worth surfacing
                        continue

                    # 4) Fairness check based on team-agnostic market value
                    fairness = _fairness_score_for_packages(
                        pack_a_list, pack_b_list, category_weights
                    )
                    if fairness < 0.85:
                        # Too lopsided in value terms
                        continue

                    # Categories each team benefits from the most
                    improve_a = sorted(
                        [c for c in TRADE_CATEGORIES if per_cat_a.get(c, 0.0) > 0],
                        key=lambda c: per_cat_a[c],
                        reverse=True,
                    )[:3]

                    improve_b = sorted(
                        [c for c in TRADE_CATEGORIES if per_cat_b.get(c, 0.0) > 0],
                        key=lambda c: per_cat_b[c],
                        reverse=True,
                    )[:3]

                    ai_reason = _build_ai_reason(
                        team_a=team_a,
                        team_b=team_b,
                        pack_a=pack_a_list,
                        pack_b=pack_b_list,
                        per_cat_a=per_cat_a,
                        per_cat_b=per_cat_b,
                        gain_a=fit_a,
                        gain_b=fit_b,
                        fairness_score=fairness,
                    )

                    suggestions.append(
                        {
                            "from_a": pack_a_list,
                            "from_b": pack_b_list,
                            "gain_a": fit_a,                # fit gain for A
                            "gain_b": fit_b,                # fit gain for B
                            "score": total_fit * fairness,  # overall ranking score
                            "fairness": fairness,
                            "improve_a": improve_a,
                            "improve_b": improve_b,
                            "ai_reason": ai_reason,
                        }
                    )

    # Best overall trades first
    suggestions.sort(key=lambda s: s["score"], reverse=True)
    return suggestions[:max_trades]


# -------------------------
# Streaming / waiver-wire engine
# -------------------------


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
    matchup_needs_full = _matchup_need_vector(league, my_team)

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
        stats[INJURY_KEY] = _estimate_injury_severity(status_raw, detail_raw)

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

        sev = _injury_severity(rp)
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
