from typing import List, Set

# 9-cat configuration
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

# Categories where *lower* is better
NEGATIVE_CATEGORIES: Set[str] = {"TOV"}

# Turnovers count at 25% weight toward total score
TURNOVER_WEIGHT: float = 0.25
