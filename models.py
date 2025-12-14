from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

# Standard 9-category fantasy basketball
CATEGORIES: List[str] = [
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "FG%",
    "FT%",
    "3PM",
    "TOV",
]

# Categories where lower is better (we'll invert the z-score sign)
NEGATIVE_CATEGORIES: Set[str] = {"TOV"}


@dataclass
class Player:
    """
    Represents an NBA player with both raw per-game stats and z-scores
    for the standard 9 fantasy categories.
    """
    name: str
    team: str
    stats: Dict[str, float] = field(default_factory=dict)
    zscores: Dict[str, float] = field(default_factory=dict)
    player_id: Optional[int] = None  # for NBA headshot URLs
