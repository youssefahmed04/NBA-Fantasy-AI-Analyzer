"""Trade suggestion engine."""

from __future__ import annotations

import statistics
from itertools import combinations
from typing import Any, Dict, List, Tuple

from config import CATEGORIES
from fantasy_models import RosterPlayer, TeamProfile
from analysis.injury import injury_severity
from analysis.position import position_balance_delta

# Categories to use for trade/streaming logic (ignore turnovers completely there)
TRADE_CATEGORIES = [c for c in CATEGORIES if c != "TOV"]

# Prefix used for per-player z-scores inside the stats dict
PLAYER_Z_PREFIX = "__Z__"


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
    sev = injury_severity(player)
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
    severity = injury_severity(player)
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
    pos_delta = position_balance_delta(team, players_out, players_in)
    pos_weight = 0.12  # tuned to matter, but not dominate categories
    pos_gain = pos_weight * pos_delta
    per_cat_gain["_pos_balance"] = pos_gain
    total_gain += pos_gain

    return total_gain, per_cat_gain


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
        return sum(injury_severity(p) for p in players) / len(players)

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
    pos_delta_a = position_balance_delta(team_a, pack_a, pack_b)
    pos_delta_b = position_balance_delta(team_b, pack_b, pack_a)
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

