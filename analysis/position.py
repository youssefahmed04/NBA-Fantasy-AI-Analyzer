"""Position balance analysis for trades and roster management."""

from __future__ import annotations

from typing import Dict, List

from fantasy_models import RosterPlayer, TeamProfile


def primary_position(pos_str: str) -> str:
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


def position_counts(players: List[RosterPlayer]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for p in players:
        pos = primary_position(getattr(p, "fantasy_position", ""))
        counts[pos] = counts.get(pos, 0) + 1
    return counts


def position_balance_delta(
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
    before = position_counts(team.players)
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
        pos = primary_position(getattr(p, "fantasy_position", ""))
        after[pos] = after.get(pos, 0) - 1
    for p in players_in:
        pos = primary_position(getattr(p, "fantasy_position", ""))
        after[pos] = after.get(pos, 0) + 1

    dist_after = dist(after)
    return dist_before - dist_after  # > 0 ⇒ improved balance


def position_note(delta: float) -> str:
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

