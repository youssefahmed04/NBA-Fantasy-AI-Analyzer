from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import statistics

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
    position: str = ""
    stats: Dict[str, float] = field(default_factory=dict)
    zscores: Dict[str, float] = field(default_factory=dict)
    # Optional metadata
    adp: Optional[float] = None
    player_id: Optional[int] = None  # for NBA headshot URLs

    def overall_individual_value(self) -> float:
        """Simple measure: sum of z-scores across all categories."""
        return sum(self.zscores.get(cat, 0.0) for cat in CATEGORIES)

    def headshot_url(self) -> Optional[str]:
        """
        URL for the player's official NBA headshot, if we know their PLAYER_ID.
        """
        if self.player_id is None:
            return None
        return f"https://cdn.nba.com/headshots/nba/latest/260x190/{int(self.player_id)}.png"


@dataclass
class Team:
    """
    Represents a fantasy team (one manager's roster).
    """
    name: str
    players: List[Player] = field(default_factory=list)
    # Optional ESPN metadata
    owners: List[str] = field(default_factory=list)
    abbrev: Optional[str] = None
    logo_url: Optional[str] = None

    def add_player(self, player: Player) -> None:
        self.players.append(player)

    def remove_player_by_name(self, name: str) -> None:
        self.players = [p for p in self.players if p.name != name]

    def category_totals(self) -> Dict[str, float]:
        """
        Sum of player z-scores by category.
        """
        totals = {cat: 0.0 for cat in CATEGORIES}
        for p in self.players:
            for cat in CATEGORIES:
                totals[cat] += p.zscores.get(cat, 0.0)
        return totals

    def overall_score(
        self,
        punted: Optional[Set[str]] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Overall numeric score for the team:

        - Ignores punted categories (treats them as weight 0).
        - Applies per-category weights if provided.
        """
        punted = punted or set()
        weights = weights or {}
        totals = self.category_totals()
        score = 0.0
        for cat, val in totals.items():
            if cat in punted:
                continue
            w = weights.get(cat, 1.0)
            score += w * val
        return score

    def detect_punted_categories(self, threshold_std: float = 0.8) -> Set[str]:
        """
        Heuristic: any category whose total is more than `threshold_std` standard deviations
        BELOW the team's mean category score is considered "punted".
        """
        totals = self.category_totals()
        values = list(totals.values())
        if len(values) < 2:
            return set()
        mean = statistics.mean(values)
        std = statistics.pstdev(values) or 1.0
        punts = {cat for cat, val in totals.items() if val < mean - threshold_std * std}
        return punts

    def summarize_profile(self):
        """
        Summarize strengths and weaknesses based on category totals.

        Returns:
            strengths: list of categories with above-average totals
            weaknesses: list of categories with below-average totals
            neutral: list of categories near the mean
        """
        totals = self.category_totals()
        values = list(totals.values())
        if not values:
            return [], [], list(CATEGORIES)
        mean = statistics.mean(values)
        std = statistics.pstdev(values) or 1.0

        strengths = []
        weaknesses = []
        neutral = []
        for cat, val in totals.items():
            if val > mean + 0.5 * std:
                strengths.append(cat)
            elif val < mean - 0.5 * std:
                weaknesses.append(cat)
            else:
                neutral.append(cat)
        # Sort for nicer display
        strengths.sort(key=lambda c: -totals[c])
        weaknesses.sort(key=lambda c: totals[c])
        neutral.sort()
        return strengths, weaknesses, neutral
