"""Injury severity analysis and heuristics."""

from __future__ import annotations

import re
from typing import List

from fantasy_models import RosterPlayer

# Special key we stash injury severity into inside the stats dict
INJURY_KEY = "__INJ_SEV__"


def estimate_injury_severity(status_raw: str, detail_raw: str) -> float:
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


def injury_severity(player: RosterPlayer) -> float:
    """Read precomputed injury severity from the stats dict."""
    try:
        return float(player.stats.get(INJURY_KEY, 0.0))
    except Exception:
        return 0.0


def avg_injury_severity(players: List[RosterPlayer]) -> float:
    if not players:
        return 0.0
    return sum(injury_severity(p) for p in players) / len(players)

