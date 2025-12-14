from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class NBADraftPlayer:
    """Minimal representation of an NBA player from data_loader."""
    name: str
    team: str
    stats: Dict[str, float]


@dataclass
class RosterPlayer:
    """Player as it appears on a fantasy roster + mapped NBA stats."""
    display_name: str
    fantasy_position: str
    fantasy_team_abbrev: str
    nba_team_abbrev: Optional[str] = ""
    headshot_url: Optional[str] = ""
    stats: Dict[str, float] = field(default_factory=dict)


@dataclass
class TeamProfile:
    team_id: int
    team_name: str
    team_abbrev: str
    logo_url: Optional[str]

    players: List[RosterPlayer] = field(default_factory=list)

    category_totals: Dict[str, float] = field(default_factory=dict)
    raw_zscores: Dict[str, float] = field(default_factory=dict)
    weighted_zscores: Dict[str, float] = field(default_factory=dict)
    total_score: float = 0.0

    strength_categories: List[str] = field(default_factory=list)
    punt_categories: List[str] = field(default_factory=list)
